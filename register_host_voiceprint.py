
# -*- coding: utf-8 -*-
"""Enroll dual-host ECAPA voiceprints for 2ByteASR host matching."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(SCRIPT_DIR))) / "2ByteASR"
REG_DIR = LOCAL / "host_voiceprints"
REG_PATH = REG_DIR / "registry.json"
SAMPLE_DIR = REG_DIR / "samples"
ECAPA_DIR = SCRIPT_DIR / "models" / "spkrec-ecapa-voxceleb"
SAMPLE_RATE = 16000
MAX_SECONDS = 14.0


def load_audio(path: Path) -> np.ndarray:
    import subprocess
    import tempfile
    import wave

    path = path.resolve()
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as wav:
                if wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == SAMPLE_RATE:
                    pcm = wav.readframes(wav.getnframes())
                    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        except wave.Error:
            pass
    with tempfile.TemporaryDirectory(prefix="host_vp_") as folder:
        out = Path(folder) / "audio.wav"
        completed = subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", str(SAMPLE_RATE), str(out)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise RuntimeError(f"ffmpeg 转采样失败：{completed.stderr[-400:]}")
        with wave.open(str(out), "rb") as wav:
            pcm = wav.readframes(wav.getnframes())
            audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    if audio.size < SAMPLE_RATE * 2:
        raise RuntimeError(f"音频过短：{path}")
    if audio.size > int(MAX_SECONDS * SAMPLE_RATE):
        audio = audio[: int(MAX_SECONDS * SAMPLE_RATE)]
    return audio


def encode(audio: np.ndarray) -> list[float]:
    from twobyteasr.model_integrity import verify_model_files

    verify_model_files("speaker_embedding", ECAPA_DIR)
    import warnings
    import torch
    import torchaudio

    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]
    if not (ECAPA_DIR / "embedding_model.ckpt").is_file():
        raise RuntimeError(f"缺少 ECAPA 模型：{ECAPA_DIR}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy

        encoder = EncoderClassifier.from_hparams(
            source=str(ECAPA_DIR),
            savedir=str(ECAPA_DIR),
            overrides={"pretrained_path": str(ECAPA_DIR)},
            local_strategy=LocalStrategy.NO_LINK,
            run_opts={"device": "cpu"},
        )
    tensor = torch.from_numpy(np.asarray(audio, dtype=np.float32)).unsqueeze(0)
    length = torch.tensor([1.0], dtype=torch.float32)
    with torch.inference_mode():
        emb = encoder.encode_batch(tensor, length).squeeze().cpu().numpy()
        emb = emb / max(float(np.linalg.norm(emb)), 1e-8)
    return [float(x) for x in emb.tolist()]


def main():
    parser = argparse.ArgumentParser(description="注册两位主播声纹")
    parser.add_argument("--name", action="append", default=[], help="主播名，可重复")
    parser.add_argument("--audio", action="append", default=[], help="对应音频路径，可重复")
    parser.add_argument("--label", action="append", default=[], help="可选 S01/S02 标签")
    args = parser.parse_args()

    REG_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    if REG_PATH.is_file():
        registry = json.loads(REG_PATH.read_text(encoding="utf-8"))
    else:
        registry = {
            "schema": 1,
            "hosts": [
                {"id": "host_a", "name": "主播A", "label": "S01", "embedding": []},
                {"id": "host_b", "name": "主播B", "label": "S02", "embedding": []},
            ],
        }

    pairs = list(zip(args.name, args.audio))
    if not pairs:
        for path in sorted(SAMPLE_DIR.iterdir()):
            if path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"}:
                pairs.append((path.stem, str(path)))
    if not pairs:
        print(f"没有找到样本。请把音频放到：{SAMPLE_DIR}")
        return 2

    hosts = {str(h.get("name")): h for h in registry.get("hosts") or [] if isinstance(h, dict)}
    for index, (name, audio_path) in enumerate(pairs):
        label = args.label[index] if index < len(args.label) else ""
        audio = load_audio(Path(audio_path))
        emb = encode(audio)
        host = hosts.get(name) or {
            "id": f"host_{name}",
            "name": name,
            "label": label or f"S{index+1:02d}",
            "embedding": [],
        }
        host["name"] = name
        if label:
            host["label"] = label
        if not host.get("label"):
            host["label"] = f"S{index+1:02d}"
        host["embedding"] = emb
        host["sample_path"] = str(Path(audio_path).resolve())
        host["sample_seconds"] = round(len(audio) / SAMPLE_RATE, 3)
        host["updated"] = time.strftime("%Y-%m-%d")
        hosts[name] = host
        print(f"[OK] {name} -> {host['label']} ({host['sample_seconds']}s)")

    registry["hosts"] = list(hosts.values())
    registry["hosts"].sort(key=lambda item: str(item.get("label") or "S99"))
    tmp = REG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, REG_PATH)
    print(f"已写入 {REG_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[失败] {exc}")
        raise SystemExit(1)
