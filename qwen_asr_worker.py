"""Canonical isolated Qwen3-ASR launcher used by source and frozen runs."""
from __future__ import annotations

import argparse
import gc
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
    jobs = json.loads(Path(args.manifest).read_text(encoding="utf-8")).get("jobs", [])
    if not jobs:
        raise RuntimeError("Qwen3-ASR manifest is empty")
    load_started = time.perf_counter()
    _emit("loading", python=sys.executable, model_path=str(Path(args.model_dir).resolve()), pid=os.getpid())
    model = Qwen3ASRModel.from_pretrained(
        str(args.model_dir), local_files_only=True,
        dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        device_map="cuda:0", max_inference_batch_size=1, max_new_tokens=512,
    )
    load_ms = (time.perf_counter() - load_started) * 1000.0
    _emit("loaded", elapsed_ms=round(load_ms, 3))
    try:
        results = []
        inference_started = time.perf_counter()
        for job in jobs:
            value = model.transcribe(
                audio=[str(job["path"])],
                context=[str(job.get("context") or "")],
                language=["Chinese"], return_time_stamps=False,
            )[0]
            text = str(getattr(value, "text", "") or "").strip()
            if text:
                confidence = getattr(value, "confidence", 0.0)
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 0.0
            else:
                confidence = 0.0
            results.append({"segment_id": int(job["segment_id"]), "text": text, "confidence": confidence})
        if not any(item.get("text") for item in results):
            raise RuntimeError("Qwen3-ASR returned no parsed output")
        inference_ms = (time.perf_counter() - inference_started) * 1000.0
        _atomic_write(Path(args.output), {"results": results, "load_ms": round(load_ms, 3), "inference_ms": round(inference_ms, 3)})
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
