"""Waveform lane tiles: playback follow reuses envelopes instead of rebuilding.

2026-10-12: at 4x the follow scroll repainted the timeline ~38 times a second
and every paint re-read and re-bucketed the visible waveform (about a third
of the GUI thread). Tiles on a fixed source-time grid keep their envelope
while only the view moves; still-decoding tiles are never cached.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication


class _Cache:
    """10 ms buckets whose values depend only on absolute time."""

    def __init__(self, covered_until_ms=None):
        self.calls = []
        self.covered_until_ms = covered_until_ms

    def read_window(self, start_ms, end_ms, pixel_width):
        from twobyteasr.waveform_cache import WaveformLevel

        self.calls.append((start_ms, end_ms))
        end = end_ms if self.covered_until_ms is None else min(end_ms, self.covered_until_ms)
        first, last = int(start_ms // 10), int(max(start_ms, end) // 10)
        index = np.arange(first, last)
        values = (0.2 + 0.6 * np.abs(np.sin(index * 0.37))).astype("float32")
        pairs = np.stack([-values, values], axis=1)
        return WaveformLevel(0, 1, 10.0, "fixture"), pairs


def _timeline():
    QApplication.instance() or QApplication([])
    from twobyteasr.studio_timeline import WaveformTimeline
    return WaveformTimeline()


def test_scrolling_at_one_zoom_reuses_tiles():
    timeline = _timeline()
    cache = _Cache()
    rect = QRectF(0, 100, 1600, 40)
    try:
        # 5 s of source across 800 px, then the view moves by 40 px steps.
        first = timeline._waveform_envelope_tiles(cache, 10_000, 15_000, 228, 1028, rect, 0, 60_000)
        assert first
        calls = len(cache.calls)
        for step in range(1, 20):
            shift = step * 250  # 250 ms = 40 px at 6.25 ms/px
            pieces = timeline._waveform_envelope_tiles(cache, 10_000 + shift, 15_000 + shift,
                                                       228, 1028, rect, 0, 60_000)
            assert pieces
        # Moving 4.75 s at this zoom crosses at most one new tile (6.4 s each).
        assert len(cache.calls) - calls <= 1
    finally:
        timeline.deleteLater()


def test_tile_positions_follow_time_and_stay_inside_the_clip():
    timeline = _timeline()
    cache = _Cache()
    rect = QRectF(0, 100, 1600, 40)
    try:
        pieces = timeline._waveform_envelope_tiles(cache, 10_000, 15_000, 228, 1028, rect, 9_000, 14_000)
        ms_per_px = 5000 / 800
        for path, origin_x in pieces:
            bounds = path.boundingRect()
            start_ms = 10_000 + (origin_x - 228) * ms_per_px
            end_ms = start_ms + bounds.width() * ms_per_px
            assert start_ms >= 9_000 - 1 and end_ms <= 14_000 + ms_per_px
        # Every source read stays inside the clip's own source range.
        assert all(9_000 <= start and end <= 14_000 for start, end in cache.calls)
    finally:
        timeline.deleteLater()


def test_partially_decoded_tiles_are_not_cached():
    timeline = _timeline()
    cache = _Cache(covered_until_ms=11_000)
    rect = QRectF(0, 100, 1600, 40)
    try:
        timeline._waveform_envelope_tiles(cache, 10_000, 15_000, 228, 1028, rect, 0, 60_000)
        calls = len(cache.calls)
        timeline._waveform_envelope_tiles(cache, 10_000, 15_000, 228, 1028, rect, 0, 60_000)
        assert len(cache.calls) > calls  # re-read until the decode covers it
        cache.covered_until_ms = None
        timeline._waveform_envelope_tiles(cache, 10_000, 15_000, 228, 1028, rect, 0, 60_000)
        calls = len(cache.calls)
        timeline._waveform_envelope_tiles(cache, 10_000, 15_000, 228, 1028, rect, 0, 60_000)
        assert len(cache.calls) == calls
    finally:
        timeline.deleteLater()
