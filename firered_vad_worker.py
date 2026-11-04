"""Isolated FireRedVAD launcher used by source and frozen runs.

The frozen GUI deliberately ships no torch stack, so voice detection runs in
the registered "main" runtime venv (same architecture as firered_aed_worker).
Input arrives as a 16 kHz PCM16 WAV path; the region list is written as JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    # Windows readers may briefly hold a handle without FILE_SHARE_DELETE.
    # Keep the previous complete JSON visible until the reader releases it.
    for attempt in range(20):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.05)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument('--progress-file')
    parser.add_argument('--chunk-seconds', type=float, default=0)
    parser.add_argument('--speech-padding-frames', type=int, default=8)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if root.name == "workers":
        root = root.parent
    source = root / "third_party" / "FireRedASR2S"
    sys.path.insert(0, str(source))
    sys.path.append(str(root))
    from twobyteasr.model_integrity import verify_model_files

    verify_model_files("firered_vad", Path(args.model_dir).parent, root=root)
    from fireredasr2s.fireredvad import FireRedVad, FireRedVadConfig

    config = FireRedVadConfig(
        use_gpu=False,
        smooth_window_size=5,
        speech_threshold=0.30,
        min_speech_frame=8,
        max_speech_frame=2000,
        min_silence_frame=12,
        merge_silence_frame=3,
        extend_speech_frame=max(0, args.speech_padding_frames),
        chunk_max_frame=30000,
    )
    started = time.perf_counter()
    model = FireRedVad.from_pretrained(args.model_dir, config)
    if args.chunk_seconds > 0:
        import wave
        import numpy as np
        import torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        timestamps = []
        with wave.open(args.wav, 'rb') as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
                raise ValueError('Expected 16 kHz mono PCM16 WAV')
            total = wav.getnframes()
            step = max(16000, round(args.chunk_seconds * 16000))
            for position in range(0, total, step):
                # Context overlaps chunk boundaries; merged below by caller.
                lo, hi = max(0, position - 8000), min(total, position + step + 8000)
                wav.setpos(lo)
                audio = np.frombuffer(wav.readframes(hi-lo), dtype='<i2').copy()
                with torch.inference_mode():
                    chunk, _ = model.detect(audio)
                timestamps.extend((max(position/16000, a+lo/16000), min((position+step)/16000, b+lo/16000))
                                  for a,b in chunk.get('timestamps', [])
                                  if b+lo/16000 > position/16000 and a+lo/16000 < (position+step)/16000)
                if args.progress_file:
                    _atomic_write(Path(args.progress_file), {'processed_seconds': min(total,position+step)/16000,
                        'total_seconds':total/16000, 'stage':'voice_activity'})
        result = {'timestamps': timestamps}
    else:
        result, _ = model.detect(args.wav)
    regions = [
        {"start": max(0.0, float(start)), "end": max(float(start), float(end))}
        for start, end in result.get("timestamps", [])
        if float(end) > float(start)
    ]
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    _atomic_write(Path(args.output), {"regions": regions, "elapsed_ms": elapsed_ms})
    print(
        "[2BYTEASR_FIRERED_VAD] "
        + json.dumps({"regions": len(regions), "elapsed_ms": elapsed_ms}, ensure_ascii=False),
        flush=True,
    )


if __name__ == "__main__":
    main()
