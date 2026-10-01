"""Small repeatable local-ASR benchmark; does not write subtitle outputs or caches."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def benchmark_firered(media_path: str, beam_size: int) -> dict:
    import torch
    import subtitle_core
    from twobyteasr.asr import transcribe_firered_reference

    audio = subtitle_core.decode_audio_to_array(media_path)
    duration = len(audio) / subtitle_core.AUDIO_SAMPLE_RATE
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    tokens = transcribe_firered_reference(
        audio,
        duration,
        beam_size=beam_size,
    )
    elapsed = time.perf_counter() - started
    text = "".join(str(item.get("text", "")) for item in tokens)
    return {
        "engine": "firered-aed",
        "beam_size": beam_size,
        "audio_seconds": round(duration, 3),
        "elapsed_seconds": round(elapsed, 3),
        "realtime_ratio": round(elapsed / max(0.001, duration), 4),
        "token_count": len(tokens),
        "text_chars": len(text),
        "text_digest": _digest(text),
        "text": text,
        "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / 1024**3, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("media")
    parser.add_argument("--engine", choices=("firered",), default="firered")
    parser.add_argument("--beam-size", type=int, default=3)
    parser.add_argument("--result-json", default="")
    args = parser.parse_args()
    media = os.path.abspath(args.media)
    if not os.path.isfile(media):
        raise FileNotFoundError(media)
    result = benchmark_firered(media, max(1, args.beam_size))
    if args.result_json:
        with open(args.result_json, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print("BENCHMARK_JSON=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
