"""Benchmark production-style concurrent FireRed-AED and Qwen3-ASR."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("media")
    parser.add_argument("--qwen-batch-size", type=int, default=8)
    return parser.parse_args()


def main():
    args = parse_args()
    import torch
    import twobyteasr.asr as asr

    asr.QWEN_ASR_BATCH_SIZE = max(1, min(12, int(args.qwen_batch_size)))
    audio = asr.decode_audio_to_array(args.media)
    audio_seconds = len(audio) / asr.AUDIO_SAMPLE_RATE
    regions = []
    offset = 0.0
    while offset < audio_seconds:
        regions.append({"start": offset, "end": min(audio_seconds, offset + 3.5)})
        offset += 3.7

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="local-asr-bench") as pool:
        firered_future = pool.submit(
            asr.transcribe_firered_reference, audio, audio_seconds
        )
        qwen_future = pool.submit(
            asr.transcribe_qwen_reference, args.media, regions, audio
        )
        firered_tokens = firered_future.result()
        qwen_chunks = qwen_future.result()
    elapsed = time.perf_counter() - started
    qwen_text = "".join(item.get("text", "") for item in qwen_chunks)
    result = {
        "audio_seconds": round(audio_seconds, 3),
        "elapsed_seconds": round(elapsed, 3),
        "qwen_batch_size": asr.QWEN_ASR_BATCH_SIZE,
        "firered_tokens": len(firered_tokens),
        "qwen_chunks": len(qwen_chunks),
        "qwen_characters": len(qwen_text),
        "qwen_text_digest": hashlib.sha256(qwen_text.encode("utf-8")).hexdigest(),
        "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / 1024**3, 3),
    }
    print("BENCHMARK_JSON=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
