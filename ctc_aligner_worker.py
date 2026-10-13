"""Isolated Japanese CTC aligner worker (main managed runtime, source and frozen runs) (2026-10-13).

Each job force-aligns one text (a run of one speaker's adjacent lines) to one
audio window of the shared task PCM with wav2vec2-large-xlsr-53-japanese
(character CTC, 20 ms frames) and ``torchaudio.functional.forced_align``.
Returns per-character spans in the original text with the mean frame
posterior, plus the model's own greedy transcript of the window. The worker
makes no timing decisions; ``twobyteasr.ctc_alignment`` decides what to use.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

PROTOCOL = "ja-ctc-align-v1"
MODEL_KEY = "ja_ctc_aligner"


def _emit(event: str, **payload: object) -> None:
    print("[2BYTEASR_JA_CTC_ALIGNER] " + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def alignable(text: str, vocab: dict) -> tuple[list[int], list[int]]:
    """Token ids and their character positions; unknown characters map to <unk>."""
    ids, positions = [], []
    for index, char in enumerate(text):
        if char.isspace() or not (char.isalnum() or char in "ー〜～"):
            continue
        ids.append(vocab.get(char, vocab["<unk>"]))
        positions.append(index)
    return ids, positions


def token_spans(path, scores) -> list[tuple[int, int, float]]:
    """(first frame, last frame, mean posterior) per aligned token of a CTC path."""
    spans, previous = [], 0
    for frame, label in enumerate(path):
        if label != 0 and (label != previous or (frame > 0 and path[frame - 1] == 0)):
            spans.append([frame, frame, [float(scores[frame])]])
        elif label != 0 and spans:
            spans[-1][1] = frame
            spans[-1][2].append(float(scores[frame]))
        previous = label
    return [(a, b, sum(s) / len(s)) for a, b, s in spans]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if root.name == "workers":
        root = root.parent
    sys.path.append(str(root))
    import numpy as np
    import torch
    import torchaudio
    from transformers import Wav2Vec2ForCTC
    from twobyteasr.model_integrity import verify_model_files

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    policy = manifest.get("policy", {})
    if policy.get("version") != PROTOCOL or policy.get("audio_format") != "float32-mono-npy-v1":
        raise RuntimeError("Unsupported CTC aligner protocol")
    sample_rate = int(policy.get("sample_rate", 0))
    if sample_rate != 16000:
        raise RuntimeError("CTC aligner needs 16 kHz audio")
    audio_spec = manifest.get("audio") or {}
    pcm = np.load(str(audio_spec["path"]), mmap_mode="r", allow_pickle=False)
    if pcm.dtype != np.float32 or pcm.ndim != 1 or pcm.size != int(audio_spec["samples"]):
        raise RuntimeError("CTC aligner input is not the declared mono float32 PCM")
    jobs = manifest.get("jobs") or []
    if not jobs:
        raise RuntimeError("CTC aligner manifest is empty")
    model_dir = Path(args.model_dir)
    verify_model_files(MODEL_KEY, model_dir, root=root)
    vocab = json.loads((model_dir / "vocab.json").read_text(encoding="utf-8"))
    inverse = {value: key for key, value in vocab.items()}
    device = "cuda" if torch.cuda.is_available() else "cpu"
    load_started = time.perf_counter()
    _emit("loading", python=sys.executable, model_path=str(model_dir.resolve()), pid=os.getpid(), jobs=len(jobs), device=device)
    model = Wav2Vec2ForCTC.from_pretrained(str(model_dir), local_files_only=True).to(device).eval()
    load_ms = (time.perf_counter() - load_started) * 1000.0
    _emit("loaded", elapsed_ms=round(load_ms, 3))
    try:
        results = []
        started = time.perf_counter()
        for done, job in enumerate(jobs, 1):
            text = str(job.get("text") or "")
            start = max(0, int(job["window_start_ms"]) * sample_rate // 1000)
            end = min(pcm.size, int(job["window_end_ms"]) * sample_rate // 1000)
            row = {"id": str(job["id"]), "text": text, "window_start_ms": int(job["window_start_ms"]),
                   "window_end_ms": int(job["window_end_ms"])}
            ids, positions = alignable(text, vocab)
            if end - start > 60 * sample_rate:
                row["status"] = "window_too_long"
            elif end - start < sample_rate // 10 or not ids:
                row["status"] = "nothing_to_align"
            else:
                audio = np.ascontiguousarray(pcm[start:end], dtype=np.float32)
                audio = (audio - audio.mean()) / (audio.std() + 1e-7)
                with torch.inference_mode():
                    log_probs = torch.log_softmax(model(torch.from_numpy(audio).to(device)[None]).logits.float(), dim=-1)
                frames = int(log_probs.shape[1])
                if frames < len(ids):
                    row["status"] = "window_too_short"
                else:
                    targets = torch.tensor([ids], dtype=torch.int32, device=device)
                    path, scores = torchaudio.functional.forced_align(log_probs, targets, blank=vocab["<pad>"])
                    path, scores = path[0].cpu().numpy(), scores[0].exp().cpu().numpy()
                    spans = token_spans(path, scores)
                    frame_ms = (end - start) * 1000 / sample_rate / frames
                    base = start * 1000 / sample_rate
                    if len(spans) != len(ids):
                        row["status"] = "path_mismatch"
                    else:
                        row["status"] = "aligned"
                        row["frame_ms"] = round(frame_ms, 3)
                        row["chars"] = [{"char": positions[i], "start_ms": round(base + a * frame_ms, 1),
                                         "end_ms": round(base + (b + 1) * frame_ms, 1), "score": round(score, 4)}
                                        for i, (a, b, score) in enumerate(spans)]
                    greedy = torch.unique_consecutive(log_probs[0].argmax(-1)).cpu().numpy()
                    row["heard"] = "".join(inverse.get(int(t), "") for t in greedy if int(t) not in (0, 1, 2))
            results.append(row)
            if done % 25 == 0:
                _emit("progress", done=done, total=len(jobs))
        inference_ms = (time.perf_counter() - started) * 1000.0
        _atomic_write(Path(args.output), {
            "protocol": PROTOCOL, "policy": policy, "results": results, "audio_sha256": audio_spec.get("sha256"),
            "python": sys.executable, "pid": os.getpid(), "torch_version": torch.__version__,
            "torchaudio_version": torchaudio.__version__, "device": device, "model_key": MODEL_KEY,
            "load_ms": round(load_ms, 3), "inference_ms": round(inference_ms, 3)})
        _emit("completed", jobs=len(jobs), inference_ms=round(inference_ms, 3))
    finally:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit("failed", error_type=type(exc).__name__, detail=str(exc))
        raise SystemExit(1)
