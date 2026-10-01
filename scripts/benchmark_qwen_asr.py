"""Benchmark Qwen3-ASR batch sizes without writing subtitle or cache files."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("media")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--result-json")
    return parser.parse_args()


def main():
    args = parse_args()
    import torch
    import twobyteasr.asr as asr

    asr.QWEN_ASR_BATCH_SIZE = max(1, min(12, int(args.batch_size)))
    audio = asr.decode_audio_to_array(args.media)
    audio_seconds = len(audio) / asr.AUDIO_SAMPLE_RATE
    # Short regions exercise the same 25-second VAD grouping used in production.
    regions = []
    offset = 0.0
    while offset < audio_seconds:
        regions.append({"start": offset, "end": min(audio_seconds, offset + 3.5)})
        offset += 3.7

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    references = asr.transcribe_qwen_reference(args.media, regions, audio)
    elapsed = time.perf_counter() - started
    text = "".join(item.get("text", "") for item in references)
    result = {
        "batch_size": asr.QWEN_ASR_BATCH_SIZE,
        "audio_seconds": round(audio_seconds, 3),
        "elapsed_seconds": round(elapsed, 3),
        "realtime_ratio": round(elapsed / max(audio_seconds, 0.001), 4),
        "chunks": len(references),
        "characters": len(text),
        "text_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / 1024**3, 3),
    }
    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print("BENCHMARK_JSON=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
