"""Media clips (timeline redesign D/E/B, 2026-11-23) and no-blank waveform tiles."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from twobyteasr.design.timeline_theme import timeline_palette
from twobyteasr.studio.media_clip_folder import (
    INK_LINE, JOIN_HALF_GAP, clip_outline, clip_shape, media_colors, paint_cut_bridge, thumbnail_cells,
)


def test_cells_keep_16_by_9_fill_the_card_and_pin_first_and_last_frames():
    shape = clip_shape(100, 900, 0, 70, 0, 1200)
    cells = thumbnail_cells(shape, 10_000, 30_000, 0, 1200, 1000)
    assert len(cells) >= 3
    for rect, ms in cells:
        assert rect.width() / rect.height() <= 16 / 9 + 1e-6   # cropped, never stretched
        assert rect.top() == 0 and abs(rect.height() - (70 - INK_LINE)) < 1e-6
        assert 10_000 <= ms < 30_000 and ms % 1000 == 0
    assert abs(cells[-1][0].width() / cells[-1][0].height() - 16 / 9) < 1e-6
    gaps = [b[0].left() - a[0].right() for a, b in zip(cells, cells[1:])]
    assert all(-1e-6 <= gap <= 2 + 4 + 1e-6 for gap in gaps)
    assert abs(cells[0][0].left() - 100) < 1e-6
    assert abs(cells[-1][0].right() - 900) < 1e-6
    assert cells[0][1] == 10_000 and cells[-1][1] == 29_000
    assert [ms for _rect, ms in cells] == sorted(ms for _rect, ms in cells)


def test_short_clip_has_no_wide_light_bars_between_frames():
    shape = clip_shape(100, 280, 0, 50, 0, 1200)          # 180 px, cells ~82 px wide
    cells = thumbnail_cells(shape, 0, 6_000, 0, 1200, 500)
    assert len(cells) == 3
    assert all(b[0].left() - a[0].right() <= 2 + 1e-6 for a, b in zip(cells, cells[1:]))
    assert abs(cells[-1][0].right() - 280) < 1e-6


def test_short_clip_shows_one_cropped_first_frame():
    shape = clip_shape(100, 160, 0, 70, 0, 1200)
    cells = thumbnail_cells(shape, 5_000, 6_000, 0, 1200, 500)
    assert len(cells) == 1 and cells[0][1] == 5_000


def test_cells_outside_the_view_are_not_requested():
    shape = clip_shape(-20_000, 20_000, 0, 70, 0, 800)
    cells = thumbnail_cells(shape, 0, 400_000, 0, 800, 10_000)
    assert cells and all(rect.right() >= 0 and rect.left() <= 800 for rect, _ms in cells)


def test_cuts_keep_rounded_ends_with_a_small_gap():
    free = clip_shape(100, 400, 0, 70, 0, 1000)
    joined = clip_shape(100, 400, 0, 70, 0, 1000, join_left=True, join_right=True)
    assert free.body.left() == 100 and free.body.right() == 400
    assert joined.body.left() == 100 + JOIN_HALF_GAP and joined.body.right() == 400 - JOIN_HALF_GAP
    corner = QPointF(joined.body.left() + 0.5, 69.5)
    assert not joined.path().contains(corner)
    assert joined.path().contains(QPointF(joined.body.left() + 0.5, 35))
    assert joined.content_left == 100 + JOIN_HALF_GAP


def test_cuts_between_sources_are_flush_with_square_ends():
    left = clip_shape(100, 400, 0, 70, 0, 1000, flush_right=True)
    right = clip_shape(400, 700, 0, 70, 0, 1000, flush_left=True)
    assert left.body.right() == 400 and right.body.left() == 400   # no gap
    assert left.path().contains(QPointF(399.5, 69.5))              # square corner
    assert right.path().contains(QPointF(400.5, 0.5))
    assert not left.path().contains(QPointF(100.5, 69.5))          # free end stays round
    # A flush end never also gets the razor-cut gap.
    both = clip_shape(100, 400, 0, 70, 0, 1000, join_right=True, flush_right=True)
    assert both.body.right() == 400 and both.content_right == 400


def test_selection_outline_is_the_rounded_card_not_a_box():
    outline = clip_outline(100, 400, 10, 60, 0, 1000)
    assert not outline.contains(QPointF(100.6, 10.6)) and not outline.contains(QPointF(399.4, 69.4))
    assert outline.contains(QPointF(250, 40))


def test_bridge_fills_the_notch_between_two_rounded_ends():
    QApplication.instance() or QApplication([])
    image = QImage(200, 80, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    try:
        paint_cut_bridge(painter, 100, 10, 60, QColor("#ff0000"), QColor("#0000ff"), continuous=False)
    finally:
        painter.end()
    assert image.pixelColor(100, 40) != QColor("white")
    assert image.pixelColor(100, 14) == QColor("white")      # 42 % high, not full
    assert image.pixelColor(90, 40).red() > image.pixelColor(110, 40).red()  # before → after gradient
    full = QImage(200, 80, QImage.Format_ARGB32)
    full.fill(QColor("white"))
    painter = QPainter(full)
    try:
        paint_cut_bridge(painter, 100, 10, 60, QColor("#ff0000"), QColor("#ff0000"), continuous=True)
    finally:
        painter.end()
    assert full.pixelColor(100, 16) != QColor("white")


def test_source_colours_are_stable_and_the_name_text_is_dark_on_light_themes():
    QApplication.instance() or QApplication([])
    palette = timeline_palette("warm")
    first = media_colors(palette, "D:/clips/a.mp4")
    assert first.tint == media_colors(palette, "D:/clips/a.mp4").tint
    # Light enough to read the waveform, tinted enough to pair with the video.
    assert 195 < first.tint.lightness() < 232
    assert first.text.lightness() < 80 and first.pill.lightness() > 240
    offline = media_colors(palette, "D:/clips/a.mp4", offline=True)
    assert offline.ink != first.ink


def test_video_clip_paints_name_pill_and_thumbnail_cells():
    QApplication.instance() or QApplication([])
    from twobyteasr.studio.studio_video_track import paint_folder_media_clip

    calls, texts = [], []

    class Filmstrip:
        def paint(self, painter, rect, source, left, right, source_in, source_out, cells, radius, placeholder):
            calls.append((source, len(cells)))

    class Painter(QPainter):
        def drawText(self, *args):
            texts.append(str(args[-1]))
            return super().drawText(*args)

    image = QImage(900, 80, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = Painter(image)
    try:
        paint_folder_media_clip(
            painter, timeline_palette("warm"), left=240, right=860, top=4, height=70,
            header_width=228, content_right=900, source="clip.mp4", source_in=0, source_out=20_000,
            label="clip.mp4", duration_ms=20_000, selected=True, offline=False, thumbnails=Filmstrip())
    finally:
        painter.end()
    assert calls and calls[0][0] == "clip.mp4" and calls[0][1] >= 3
    assert "clip.mp4" in texts and "20.0s" in texts


class _Meta:
    def __init__(self, source):
        self.source_path = source
        self.audio_stream = 0
        self.incomplete = True
        self.coverage_end_ms = 60_000
        self.sample_timeline_origin_ms = 0.0


class _Cache:
    def __init__(self, source="a.wav"):
        self.metadata = _Meta(source)
        self.calls = 0

    def read_window(self, start_ms, end_ms, pixel_width):
        from twobyteasr.playback.waveform_cache import WaveformLevel

        self.calls += 1
        index = np.arange(int(start_ms // 10), int(end_ms // 10))
        values = (0.2 + 0.6 * np.abs(np.sin(index * 0.37))).astype("float32")
        return WaveformLevel(0, 1, 10.0, "fixture"), np.stack([-values, values], axis=1)


def test_new_progressive_cache_keeps_the_previous_tiles_on_screen():
    QApplication.instance() or QApplication([])
    from twobyteasr.studio.studio_timeline import WaveformTimeline

    timeline = WaveformTimeline()
    rect = QRectF(0, 100, 1600, 40)
    try:
        first = timeline._waveform_envelope_tiles(_Cache(), 10_000, 15_000, 228, 1028, rect, 0, 60_000)
        assert first
        # A newer publication of the same source, painted the asynchronous
        # way (misses become worker jobs): the old tiles stay visible.
        timeline._paint_geometry_cache = {}
        timeline._waveform_tile_jobs = {}
        newer = _Cache()
        second = timeline._waveform_envelope_tiles(newer, 10_000, 15_000, 228, 1028, rect, 0, 60_000)
        assert [x for _path, x in second] == [x for _path, x in first]
        assert newer.calls == 0 and timeline._waveform_tile_jobs
        # A different source never borrows another file's picture.
        other = timeline._waveform_envelope_tiles(_Cache("b.wav"), 10_000, 15_000, 228, 1028, rect, 0, 60_000)
        assert other == []
    finally:
        timeline._paint_geometry_cache = None
        timeline.deleteLater()
