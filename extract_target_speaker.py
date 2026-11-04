# -*- coding: utf-8 -*-
"""Separate a two-speaker mixture and select the target by ECAPA voiceprint."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
SEPFORMER_DIR = ROOT / "models" / "sepformer-whamr16k"
ECAPA_DIR = ROOT / "models" / "spkrec-ecapa-voxceleb"
SAMPLE_RATE = 16000


def run_ffmpeg(source: Path, destination: Path) -> None:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {source}: {completed.stderr[-600:]}")


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getframerate() != SAMPLE_RATE:
            raise ValueError(f"Expected mono {SAMPLE_RATE} Hz WAV: {path}")
        if wav.getsampwidth() != 2:
            raise ValueError(f"Expected 16-bit PCM WAV: {path}")
        pcm = wav.readframes(wav.getnframes())
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def write_wav(path: Path, audio: np.ndarray) -> None:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767.0).round().astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())


def patch_torchaudio() -> None:
    import torchaudio

    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]


def load_separator(device: str):
    patch_torchaudio()
    from speechbrain.inference.separation import SepformerSeparation
    from speechbrain.utils.fetching import LocalStrategy

    # SepFormer（sepformer-whamr16k）不在 dependencies.lock.json 中，需手动放置；
    # 因此这里只做文件存在性检查，不做 SHA-256 校验。
    required = [SEPFORMER_DIR / name for name in ("hyperparams.yaml", "masknet.ckpt", "encoder.ckpt", "decoder.ckpt")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing SepFormer files: " + ", ".join(missing))
    return SepformerSeparation.from_hparams(
        source=str(SEPFORMER_DIR),
        savedir=str(SEPFORMER_DIR),
        run_opts={"device": device},
        local_strategy=LocalStrategy.NO_LINK,
    )


def load_voice_encoder(device: str):
    from twobyteasr.model_integrity import verify_model_files

    verify_model_files("speaker_embedding", ECAPA_DIR)
    patch_torchaudio()
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    if not (ECAPA_DIR / "embedding_model.ckpt").is_file():
        raise FileNotFoundError(f"Missing ECAPA model: {ECAPA_DIR}")
    return EncoderClassifier.from_hparams(
        source=str(ECAPA_DIR),
        savedir=str(ECAPA_DIR),
        overrides={"pretrained_path": str(ECAPA_DIR)},
        local_strategy=LocalStrategy.NO_LINK,
        run_opts={"device": device},
    )


def loud_windows(audio: np.ndarray, seconds: float = 4.0, count: int = 5) -> list[np.ndarray]:
    """Select energetic, non-overlapping windows for robust voiceprint comparison."""
    size = int(seconds * SAMPLE_RATE)
    if audio.size <= size:
        return [audio]
    hop = max(SAMPLE_RATE, size // 2)
    ranked = []
    for start in range(0, audio.size - size + 1, hop):
        window = audio[start : start + size]
        rms = float(np.sqrt(np.mean(window * window) + 1e-12))
        ranked.append((rms, start, window))
    selected: list[tuple[int, np.ndarray]] = []
    for _, start, window in sorted(ranked, reverse=True):
        if all(abs(start - prior) >= size for prior, _ in selected):
            selected.append((start, window))
        if len(selected) >= count:
            break
    return [window for _, window in selected] or [audio[:size]]


def embeddings(encoder, audio: np.ndarray):
    import torch

    windows = loud_windows(audio)
    batch = torch.from_numpy(np.stack(windows)).to(encoder.device)
    lengths = torch.ones(batch.shape[0], device=encoder.device)
    with torch.inference_mode():
        vectors = encoder.encode_batch(batch, lengths).squeeze(1)
        vectors = torch.nn.functional.normalize(vectors, dim=-1)
    return vectors


def similarity(reference_vectors, candidate_vectors) -> float:
    import torch

    with torch.inference_mode():
        scores = reference_vectors @ candidate_vectors.T
        # A few clean matching windows should dominate over silent/contaminated ones.
        best_per_candidate = scores.max(dim=0).values
        take = min(3, best_per_candidate.numel())
        return float(torch.topk(best_per_candidate, take).values.mean().item())


def main() -> int:
    parser = argparse.ArgumentParser(description="Separate two voices and keep the target speaker")
    parser.add_argument("mixture", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    mixture = args.mixture.resolve()
    reference = args.reference.resolve()
    if not mixture.is_file() or not reference.is_file():
        parser.error("mixture and reference must both exist")
    output_dir = (args.output_dir or (ROOT / "outputs" / mixture.stem)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}", flush=True)
    with tempfile.TemporaryDirectory(prefix="target_speaker_") as folder:
        temp = Path(folder)
        mixture_wav = temp / "mixture.wav"
        reference_wav = temp / "reference.wav"
        run_ffmpeg(mixture, mixture_wav)
        run_ffmpeg(reference, reference_wav)
        mixture_audio = read_wav(mixture_wav)
        reference_audio = read_wav(reference_wav)

        separator = load_separator(device)
        mixture_tensor = torch.from_numpy(mixture_audio).unsqueeze(0).to(device)
        with torch.inference_mode():
            separated = separator.separate_batch(mixture_tensor).squeeze(0).detach().cpu().numpy()
        if separated.ndim != 2:
            raise RuntimeError(f"Unexpected separator output shape: {separated.shape}")
        # SpeechBrain returns [time, speakers].
        if separated.shape[0] < separated.shape[1]:
            separated = separated.T

        encoder = load_voice_encoder(device)
        reference_vectors = embeddings(encoder, reference_audio)
        scores = []
        candidate_paths = []
        for index in range(separated.shape[1]):
            candidate = separated[:, index]
            candidate_path = output_dir / f"candidate_{index + 1}.wav"
            write_wav(candidate_path, candidate)
            candidate_paths.append(candidate_path)
            score = similarity(reference_vectors, embeddings(encoder, candidate))
            scores.append(score)
            print(f"Candidate {index + 1} voiceprint similarity: {score:.4f}", flush=True)

        selected = int(np.argmax(scores))
        target_path = output_dir / "target_speaker.wav"
        write_wav(target_path, separated[:, selected])
        report = {
            "mixture": str(mixture),
            "reference": str(reference),
            "sample_rate": SAMPLE_RATE,
            "device": device,
            "candidate_scores": {path.name: round(score, 6) for path, score in zip(candidate_paths, scores)},
            "selected": candidate_paths[selected].name,
            "output": str(target_path),
        }
        (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Selected candidate {selected + 1}: {target_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
