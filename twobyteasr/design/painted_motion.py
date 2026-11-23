"""Advance only when the previous image reached the Qt paint surface."""
from __future__ import annotations

import time


class PaintedMotion:
    """Clock for a visual surface with one outstanding paint at most.

    Qt can coalesce updates, and a newly shown backing store may take several
    turns to receive its first paint. Those turns do not consume the flight.
    A late paint advances by at most one and a half refresh intervals.
    """

    def __init__(self, duration_ms: int, refresh_ms: int):
        self.duration_ms = duration_ms
        self.refresh_ms = refresh_ms
        self.elapsed_ms = 0.0
        self.prepared = time.perf_counter()
        self.started = None
        self.last = None
        self.pending = True

    def painted(self) -> None:
        if not self.pending:
            return
        now = time.perf_counter()
        if self.started is None:
            self.started = now
            self.last = now
        self.pending = False

    @property
    def finished(self) -> bool:
        return self.elapsed_ms >= self.duration_ms and not self.pending

    def step(self) -> float | None:
        if self.pending or self.last is None or self.finished:
            return None
        now = time.perf_counter()
        elapsed = min((now - self.last) * 1000, self.refresh_ms * 1.5)
        self.last = now
        self.elapsed_ms = min(self.duration_ms, self.elapsed_ms + elapsed)
        self.pending = True
        return self.elapsed_ms / self.duration_ms
