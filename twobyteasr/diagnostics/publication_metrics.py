"""Bounded publication measurements; submission and ACK are never presentation.

The caller passes a copy of its bounded mailbox history. Missing samples stay
unknown; a previously observed stream with no recent activity is explicitly idle.
No filesystem, native window or player queries belong in a periodic snapshot.
"""
from __future__ import annotations

import math


def event_rate(timestamps, now, *, window=2.0):
    times = sorted(float(value) for value in timestamps
                   if isinstance(value, (int, float)) and math.isfinite(value) and value <= now)
    recent = [value for value in times if value >= now - window]
    state, fps = 'not_sampled', None
    if times and (not recent or now - recent[-1] >= .5):
        state, fps = 'idle', 0.0
    elif len(recent) >= 2 and recent[-1] > recent[0]:
        state = 'measured'
        fps = round((len(recent) - 1) / (recent[-1] - recent[0]), 3)
    elif recent:
        state = 'insufficient_samples'
    return {'status': state, 'events_per_second': fps, 'sample_count': len(recent),
            'window_seconds': window, 'last_event_age_ms':
            round((now - times[-1]) * 1000, 3) if times else None}


def percentile95(values):
    values = sorted(float(value) for value in values
                    if isinstance(value, (int, float)) and math.isfinite(value))
    return round(values[max(0, math.ceil(len(values) * .95) - 1)], 3) if values else None


def upload_snapshot(rows, now):
    """Native command receipts, including denied commands, with explicit scope."""
    recent = [row for row in rows if row.get('started', 0) >= now - 2.0]
    accepted = [row for row in rows if row.get('accepted') and row.get('applied_at')]
    rate = event_rate([row['applied_at'] for row in accepted], now)
    return {
        'measurement': 'native overlay command ACK; not texture upload completion or display',
        'ack': rate,
        'attempts_in_window': len(recent),
        'rejected_in_window': sum(not row.get('accepted', False) for row in recent),
        'cost_p95_ms': {key: percentile95(row.get(key) for row in recent) for key in (
            'raster_queue_ms', 'write_ms', 'actor_queue_ms', 'ipc_ack_ms', 'total_ms')},
        'last_raster': next((row.get('raster') for row in reversed(recent) if row.get('raster')), None),
        'gpu_upload_ms': None,
        'gpu_upload_status': 'unsupported: external mpv IPC does not expose GPU upload timestamps',
        'screen_events_per_second': None,
        'screen_status': 'not_collected: use desktop frame codes or PID-matched system events',
    }
