"""Isolated FireRedASR2-LLM worker for primary and review ASR evidence."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir", required=True)
    return parser.parse_args()


def atomic_write(path, payload):
    output = Path(path)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _emit(event, **payload):
    print(
        "[2BYTEASR_FIRERED_LLM] "
        + json.dumps({"event": event, **payload}, ensure_ascii=False),
        flush=True,
    )


def _cuda_snapshot(torch):
    if not torch.cuda.is_available():
        return {"available": False}
    free, total = torch.cuda.mem_get_info(0)
    return {
        "available": True,
        "device": torch.cuda.get_device_name(0),
        "free_bytes": int(free),
        "total_bytes": int(total),
        "allocated_bytes": int(torch.cuda.memory_allocated(0)),
        "reserved_bytes": int(torch.cuda.memory_reserved(0)),
    }


def main():
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    source_dir = script_dir / "third_party" / "FireRedASR2S"
    sys.path.append(str(script_dir))
    sys.path.insert(0, str(source_dir))

    import torch

    from twobyteasr.model_integrity import verify_model_files

    verify_model_files("firered_llm", Path(args.model_dir), root=script_dir)
    if not torch.cuda.is_available():
        raise RuntimeError("FireRedASR2-LLM requires an available CUDA GPU.")

    from fireredasr2s.fireredasr2 import FireRedAsr2, FireRedAsr2Config

    with open(args.manifest, "r", encoding="utf-8") as file:
        jobs = list(json.load(file).get("jobs", []))
    if not jobs:
        atomic_write(args.output, {"results": []})
        return

    model = None
    try:
        _emit("loading", cuda=_cuda_snapshot(torch))
        started = time.perf_counter()
        config = FireRedAsr2Config(
            use_gpu=True,
            use_half=True,
            beam_size=1,
            decode_min_len=0,
            repetition_penalty=1.0,
            llm_length_penalty=0.0,
            temperature=1.0,
        )
        model = FireRedAsr2.from_pretrained("llm", args.model_dir, config)
        _emit(
            "loaded",
            elapsed_seconds=round(time.perf_counter() - started, 3),
            cuda=_cuda_snapshot(torch),
        )

        results = []
        inference_started = time.perf_counter()
        batch_size = 2
        for offset in range(0, len(jobs), batch_size):
            batch = jobs[offset : offset + batch_size]
            ids = [int(job["segment_id"]) for job in batch]
            values = model.transcribe(
                [f"segment_{segment_id}" for segment_id in ids],
                [str(job["path"]) for job in batch],
            )
            if len(values) != len(batch):
                raise RuntimeError(
                    f"FireRedASR2-LLM returned {len(values)} rows for {len(batch)} inputs."
                )
            for segment_id, value in zip(ids, values):
                text = str(value.get("text") or "").strip()
                if not text:
                    raise RuntimeError(
                        f"FireRedASR2-LLM returned empty text for segment {segment_id}."
                    )
                results.append({"segment_id": segment_id, "text": text})
            _emit("batch", completed=min(offset + len(batch), len(jobs)), total=len(jobs))
        atomic_write(args.output, {"results": results})
        _emit(
            "transcribed",
            elapsed_seconds=round(time.perf_counter() - inference_started, 3),
            result_count=len(results),
            cuda=_cuda_snapshot(torch),
        )
    finally:
        if model is not None:
            del model
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
        _emit("released", cuda=_cuda_snapshot(torch))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        main()
    except Exception as exc:
        _emit("failed", error_type=type(exc).__name__, detail=str(exc))
        raise SystemExit(1)
