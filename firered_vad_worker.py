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


def scored_regions(result, probabilities, *, offset=0.0, bounds=None, statistics=False):
    """Score the owned portion using the real detector probability vector."""
    scores = probabilities.reshape(-1).tolist() if probabilities is not None else []
    duration = float(result.get('dur') or 0)
    frame_seconds = duration/len(scores) if scores and duration > 0 else .01
    regions = []
    for start, end in result.get('timestamps', []):
        a, b = float(start)+offset, float(end)+offset
        if bounds is not None:
            a, b = max(a, bounds[0]), min(b, bounds[1])
        if b <= a:
            continue
        low = max(0, int((a-offset)/frame_seconds))
        high = min(len(scores), int((b-offset)/frame_seconds)+1)
        values = scores[low:high]
        total = sum(values)
        region = dict(start=max(0., a), end=b, detector='firered_vad',
            confidence=total/len(values) if values else None,
            confidence_basis='mean_vad_model_probability')
        if probabilities is None:
            region['confidence_bounds_verified'] = False
        if statistics:
            region.update(probability_sum=total, probability_frames=len(values))
        regions.append(region)
    return regions


def detect_chunks(model, wav_path, *, chunk_seconds=30, progress=lambda **values: None):
    """Read PCM before feature extraction, owning one bounded chunk at a time."""
    import gc
    import math
    import wave
    import numpy as np
    import torch
    from twobyteasr.recognition.vad import merge_regions
    if not math.isfinite(chunk_seconds) or chunk_seconds <= 0:
        chunk_seconds = 30
    step = max(16000, round(min(30, chunk_seconds)*16000))
    regions = []
    retries = chunks = 0
    with wave.open(str(wav_path), 'rb') as wav:
        rate = wav.getframerate()
        if (rate, wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Expected 16 kHz mono PCM16 WAV')
        total = wav.getnframes()
        position = 0
        while position < total:
            attempts = 0
            while True:
                end = min(total, position+step)
                lo, hi = max(0, position-8000), min(total, end+8000)
                wav.setpos(lo)
                audio = np.frombuffer(wav.readframes(hi-lo), dtype='<i2')
                try:
                    with torch.inference_mode():
                        detected, probabilities = model.detect(audio)
                    detected = dict(detected, dur=(hi-lo)/rate)
                    chunk_regions = scored_regions(detected, probabilities, offset=lo/rate,
                        bounds=(position/rate, end/rate), statistics=True)
                    del detected, probabilities, audio
                    break
                except (MemoryError, RuntimeError) as exc:
                    del audio
                    if not isinstance(exc, MemoryError) and not any(marker in str(exc).lower()
                            for marker in ('bad allocation', 'out of memory', 'cannot allocate')):
                        raise
                    if attempts >= 2 or step <= rate:
                        raise
                    attempts += 1
                    retries += 1
                    step = max(rate, step//2)
                    gc.collect()
            regions = merge_regions([*regions, *chunk_regions], tolerance=1/rate)
            position = end
            chunks += 1
            progress(processed_seconds=position/rate, total_seconds=total/rate,
                chunks=chunks, memory_retries=retries, chunk_seconds=step/rate, stage='voice_activity')
    return regions, dict(samples=total, sample_rate=rate, chunks=chunks, memory_retries=retries,
                         chunk_seconds=step/rate, context_samples=8000)


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
    parser.add_argument('--chunk-seconds', type=float, default=30)
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
    import torch
    from twobyteasr.recognition.vad import receipt
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    def progress(**values):
        if args.progress_file:
            _atomic_write(Path(args.progress_file), values)
        print('[2BYTEASR_FIRERED_VAD] '+json.dumps(dict(event='progress', **values)), flush=True)
    regions, details = detect_chunks(model, args.wav, chunk_seconds=args.chunk_seconds, progress=progress)
    execution = receipt('firered_vad', 'firered_vad', details['samples']/16000, **details)
    execution['status'] = 'complete' if regions else 'no_speech'
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    _atomic_write(Path(args.output), {"regions": regions, "execution": execution, "elapsed_ms": elapsed_ms})
    print(
        "[2BYTEASR_FIRERED_VAD] "
        + json.dumps({"regions": len(regions), "elapsed_ms": elapsed_ms}, ensure_ascii=False),
        flush=True,
    )


if __name__ == "__main__":
    main()
