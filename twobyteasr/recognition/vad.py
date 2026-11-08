"""Bounded energy features and truthful VAD provenance for existing callers."""
from __future__ import annotations

import numpy as np

ALGORITHM = 'pcm-chunks30-scored-context500-energy-bounded-v3'
CHUNK_SECONDS = 30


class VadRegions(list):
    def __init__(self, regions=(), *, execution):
        super().__init__(regions)
        self.execution = dict(execution)


def receipt(requested, actual, duration, *, reason='', **details):
    return dict(requested_backend=requested, actual_backend=actual,
        degraded=requested != actual, failure_reason=reason, start=0., end=float(duration),
        algorithm_version=ALGORITHM, status='complete', **details)


def encode(value):
    return dict(regions=list(value), execution=value.execution)


def decode(value):
    execution = value['execution']
    if execution.get('algorithm_version') != ALGORITHM or not execution.get('actual_backend'):
        raise ValueError('VAD cache has no verifiable backend identity')
    if execution.get('degraded'):
        raise ValueError('Retry requested backend instead of reusing a degraded result')
    return VadRegions(value['regions'], execution=execution)


def cacheable(value):
    return not value.execution['degraded'] and value.execution['status'] in {'complete', 'no_speech'}


def completion_label(value):
    execution = value.execution
    if execution['degraded']:
        return 'FireRedVAD 失败，已使用轻量检测'
    return 'FireRedVAD 人声安全检查' if execution['actual_backend'] == 'firered_vad' else '轻量静音与人声区间检测'


def detected_tail(regions):
    execution = getattr(regions, 'execution', {})
    if execution.get('degraded') or execution.get('actual_backend', 'firered_vad') != 'firered_vad':
        return None
    return max((float(row['end']) for row in regions), default=0.)


def selected_detection(firered, lightweight, *, requested, duration, check=lambda: None, event=lambda *a, **k: None):
    """A fallback is useful evidence, never proof that missing ASR was silence."""
    check()
    reason = ''
    failed_execution = {}
    if requested == 'firered_vad':
        try:
            value = firered()
            execution = dict(getattr(value, 'execution', receipt(requested, requested, duration)))
            execution['status'] = 'complete' if value else 'no_speech'
            result = VadRegions(value, execution=execution)
            event('vad_execution', **result.execution)
            return result
        except Exception as exc:
            check()
            if exc.__class__.__name__ == 'CancelledError':
                raise
            from ..providers.provider_diagnostics import redact_diagnostics
            failed_execution = dict(getattr(exc, 'vad_execution', {}))
            reason = str(redact_diagnostics(f'{type(exc).__name__}: {exc}'))[-1600:]
    check()
    try:
        detected = lightweight()
    except RuntimeError as exc:
        check()
        if exc.__class__.__name__ == 'CancelledError':
            raise
        detected = []
        reason = (reason + '\n' + str(exc)).strip()
    execution = receipt(requested, 'lightweight_vad', duration, reason=reason,
        failed_backend_execution=failed_execution, detected_regions=list(detected), conservative_coverage=True)
    execution['status'] = 'complete' if detected else 'uncertain_no_speech'
    # An energy miss must not delete an independent, reliable transcript or
    # shorten its timing. Keep all audio eligible when the requested model failed.
    regions = [dict(start=0., end=duration, detector='energy', processing_only=True)] if duration > 0 else []
    result = VadRegions(regions, execution=execution)
    event('vad_execution', **execution)
    return result


def merge_regions(regions, *, tolerance=0.):
    """Merge touching intervals only when their evidence has the same strength."""
    from .speech_coverage import AUTO_CONFIDENCE
    result = []
    def identity(row):
        score = row.get('confidence')
        return (row.get('detector'), bool(row.get('processing_only')),
                row.get('confidence_bounds_verified', True),
                None if score is None else float(score) >= AUTO_CONFIDENCE)
    for value in sorted(regions, key=lambda row: (row['start'], row['end'])):
        row = dict(value)
        previous = result[-1] if result else None
        if (previous is not None and row['start'] <= previous['end']+tolerance
                and identity(previous) == identity(row)
                and row.get('confidence_bounds_verified', True)
                and (row.get('confidence') is None or
                     previous.get('probability_frames', 0) > 0 and row.get('probability_frames', 0) > 0)):
            previous['end'] = max(previous['end'], row['end'])
            frames = previous.get('probability_frames', 0)+row.get('probability_frames', 0)
            total = previous.get('probability_sum', 0.)+row.get('probability_sum', 0.)
            if frames:
                previous.update(probability_frames=frames, probability_sum=total, confidence=total/frames)
        else:
            result.append(row)
    return result


def bounded_rms(samples, frame, hop, *, block_frames=1024, check=lambda: None):
    """Same global frame grid and float32 mean-square, with a bounded square."""
    samples = np.asarray(samples).reshape(-1)
    if len(samples) < frame:
        return np.sqrt(np.mean(np.square(samples, dtype=np.float32), keepdims=True) + 1e-10)
    count = 1 + (len(samples)-frame)//hop
    rms = np.empty(count, dtype=np.float32)
    for first in range(0, count, block_frames):
        check()
        size = min(block_frames, count-first)
        piece = samples[first*hop:(first+size-1)*hop+frame]
        frames = np.lib.stride_tricks.as_strided(piece, shape=(size,frame),
            strides=(piece.strides[0]*hop,piece.strides[0]), writeable=False)
        rms[first:first+size] = np.sqrt(np.mean(np.square(frames, dtype=np.float32), axis=1)+1e-10)
    return rms


def wav_rms(path, *, check=lambda: None):
    """Read overlapping PCM frames on the global 10 ms grid without a full WAV copy."""
    import wave
    frame, hop, block_frames = 480, 160, 1024
    with wave.open(str(path), 'rb') as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Expected 16 kHz mono PCM16 WAV')
        total = stream.getnframes()
        count = max(0, 1+(total-frame)//hop)
        rms = np.empty(count, dtype=np.float32)
        for first in range(0, count, block_frames):
            check()
            size = min(block_frames, count-first)
            stream.setpos(first*hop)
            samples = np.frombuffer(stream.readframes((size-1)*hop+frame), dtype='<i2').astype(np.float32)/32768
            rms[first:first+size] = bounded_rms(samples, frame, hop, check=check)
    return rms, total
