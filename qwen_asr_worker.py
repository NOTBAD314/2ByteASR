"""Canonical isolated Qwen3-ASR launcher used by source and frozen runs."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def _emit(event: str, **payload: object) -> None:
    print("[2BYTEASR_QWEN3_ASR] " + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if root.name == 'workers':
        root = root.parent
    # Import app Python sources after this role's site-packages, never the
    # frozen GUI's binary extensions ahead of the managed environment.
    sys.path.append(str(root))
    import torch
    from qwen_asr import Qwen3ASRModel
    from twobyteasr.model_integrity import verify_model_files

    verify_model_files("qwen_asr", Path(args.model_dir), root=root)
    if not torch.cuda.is_available():
        raise RuntimeError("Qwen3-ASR requires CUDA")
    import numpy as np
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    jobs = manifest.get("jobs", [])
    policy = manifest.get("policy", {})
    if policy.get("version") != "qwen-worker-shared-float32-v1" or policy.get("audio_format") != "float32-mono-npy-v1":
        raise RuntimeError("Unsupported Qwen worker input protocol")
    batch_size = int(policy.get("batch_size", 0))
    max_new_tokens = int(policy.get("max_new_tokens", 0))
    sample_rate = int(policy.get("sample_rate", 0))
    if not 1 <= batch_size <= 12 or not 1 <= max_new_tokens <= 4096 or sample_rate != 16000:
        raise RuntimeError("Invalid Qwen worker generation policy")
    # Spoken language for every window: "Chinese", "Japanese", "English", or None
    # to let Qwen3-ASR identify it. Policies without the key keep the Chinese default.
    language = policy.get("language", "Chinese")
    if language not in {None, "Chinese", "Japanese", "English"}:
        raise RuntimeError("Invalid Qwen worker language")
    if not jobs:
        raise RuntimeError("Qwen3-ASR manifest is empty")
    load_started = time.perf_counter()
    _emit("loading", python=sys.executable, model_path=str(Path(args.model_dir).resolve()), pid=os.getpid())
    model = Qwen3ASRModel.from_pretrained(
        str(args.model_dir), local_files_only=True,
        dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        device_map="cuda:0", max_inference_batch_size=batch_size, max_new_tokens=max_new_tokens,
    )
    load_ms = (time.perf_counter() - load_started) * 1000.0
    _emit("loaded", elapsed_ms=round(load_ms, 3))
    try:
        results = []
        inference_started = time.perf_counter()
        for offset in range(0, len(jobs), batch_size):
            batch = jobs[offset:offset + batch_size]
            audio = []
            for job in batch:
                pcm = np.load(str(job["path"]), allow_pickle=False)
                if pcm.dtype != np.float32 or pcm.ndim != 1 or not np.isfinite(pcm).all():
                    raise RuntimeError("Qwen input is not finite mono float32 PCM")
                if pcm.size != int(job["samples"]) or hashlib.sha256(pcm.tobytes()).hexdigest() != job["pcm_sha256"]:
                    raise RuntimeError("Qwen PCM fingerprint mismatch")
                audio.append((pcm, sample_rate))
            values = model.transcribe(audio=audio,
                context=[str(job.get("context") or "") for job in batch],
                language=[language] * len(batch), return_time_stamps=False)
            if len(values) != len(batch):
                raise RuntimeError("Qwen returned a partial batch")
            for job, value in zip(batch, values):
                text = str(getattr(value, "text", "") or "").strip()
                try:
                    confidence = float(getattr(value, "confidence", 0.0)) if text else 0.0
                except (TypeError, ValueError):
                    confidence = 0.0
                results.append({"segment_id": int(job["segment_id"]), "text": text,
                    "language": str(getattr(value, "language", "") or ""),
                    "confidence": confidence, "start": job["start"], "end": job["end"],
                    "samples": job["samples"], "pcm_sha256": job["pcm_sha256"],
                    "context_sha256": hashlib.sha256(str(job.get("context") or "").encode("utf8")).hexdigest()})
        if not any(item.get("text") for item in results):
            raise RuntimeError("Qwen3-ASR returned no parsed output")
        inference_ms = (time.perf_counter() - inference_started) * 1000.0
        _atomic_write(Path(args.output), {"results": results, "policy": policy, "python": sys.executable, "pid": os.getpid(),
            "torch_version": torch.__version__, "dtype": str(model.model.dtype) if hasattr(model, "model") else "unrecorded",
            "load_ms": round(load_ms, 3), "inference_ms": round(inference_ms, 3)})
        _emit("completed", raw_result_count=len(results), parsed_result_count=sum(bool(item.get("text")) for item in results), inference_ms=round(inference_ms, 3))
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
