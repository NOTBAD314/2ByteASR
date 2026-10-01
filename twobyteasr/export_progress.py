"""Monotonic work-based progress; wall time never advances completion."""
import time
from .studio_render import parse_ffmpeg_out_time_seconds


class ExportProgress:
    def __init__(self, duration, *, raster=False, advanced=False, static_advanced=False):
        self.duration = max(.001, duration)
        self.weights = [('prepare_project', 2)]
        if raster:
            self.weights.append(('compose_video', 75 if not advanced else 45))
        self.weights.append(('prepare_subtitles', 1))
        if advanced:
            self.weights.append(('advanced_render', 2 if static_advanced else 35))
        used = sum(w for _, w in self.weights)
        self.weights.extend([('encode', 96-used), ('mux', 4)])
        self.percent = 0.
        self.started = time.monotonic()
        self.stage = ''
        self.stage_started = self.started
        self.last_update = self.started

    def update(self, payload):
        stage = payload.get('stage') or 'prepare_project'
        now = time.monotonic()
        if stage != self.stage:
            self.stage, self.stage_started = stage, now
        self.last_update = now
        raw = payload.get('percent')
        media_time = parse_ffmpeg_out_time_seconds(payload)
        fraction = float(raw)/100 if raw not in (None, '') else (
            media_time/self.duration if media_time is not None and stage == 'encode' else 0)
        fraction = max(0., min(1., fraction))
        base = 0
        for key, weight in self.weights:
            if key == stage:
                self.percent = max(self.percent, min(99., base + weight*fraction))
                break
            base += weight
        if stage == 'mux' and raw not in (None, '') and float(raw) >= 100:
            self.percent = 100.
        return self.percent, fraction*100 if raw not in (None, '') or media_time is not None else None
