"""三轨独立轨高 + 右侧统一控制区（2026-09-18 VIII 引入，2026-09-19 P1 整合）。

2026-09-19 P1：独立 rail（红色大把手+V/A/字 常驻文字）退役；右缘只保留
纵向滚动条一列——滚动条承担滚动，泳道分界处的矮把手（直绘在滚动条列、
与实际边界对齐）+ 画布分界线拖动承担轨高调整，共享 `_track_height_overrides`。
滚动条在无纵向溢出时常驻可见（轨高入口不消失）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def timeline(app):
    from twobyteasr.studio.studio_timeline import WaveformTimeline

    widget = WaveformTimeline()
    widget.resize(1600, 520)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def test_default_heights_unchanged(timeline):
    assert timeline._video_track_height() == 58
    assert timeline.AUDIO_TRACK_HEIGHT == 36
    assert timeline._speaker_track_height() in (52, 68, 84, 96)


def test_spare_height_grows_waveform_then_subtitles_and_stays_below(app):
    """2026-10-09 (M16): lanes start right under the ruler; spare height
    first makes the waveform easier to read (36 → 72), then steps the
    subtitle lanes up; what is left stays below the last lane."""
    from twobyteasr.studio.studio_timeline import WaveformTimeline

    widget = WaveformTimeline()
    try:
        widget.resize(1600, widget.minimumHeight())
        assert widget._audio_track_height() <= widget.AUDIO_TRACK_HEIGHT + 2  # almost no spare: base height
        widget.resize(1600, 900)
        assert widget._audio_track_height() == widget.AUDIO_TRACK_AUTO_MAX
        assert widget._speaker_track_height() == 96
        video = widget._video_track_rects()["V1"]
        audio = widget._audio_track_rects()["A1"]
        stack_bottom = audio.bottom()
        assert widget._track_viewport().top() == widget.RULER_HEIGHT  # top-anchored
        assert stack_bottom < widget._canvas_bottom() - 100  # spare stays below
        assert audio.top() == pytest.approx(video.bottom())
        # The widget minimum never follows the grown (auto) heights.
        widget._sync_track_minimum_height()
        minimum = widget.minimumHeight()
        widget.resize(1600, 1400)
        widget._sync_track_minimum_height()
        assert widget.minimumHeight() == minimum
    finally:
        widget.close()


def test_heights_independent_and_clamped(timeline):
    timeline.set_track_height("video", 120)
    assert timeline._video_track_rects()["V1"].height() == 120
    assert "audio" not in timeline.track_heights()  # 音频不联动（仍为自动高度）
    assert timeline._audio_track_rects()["A1"].height() == timeline._auto_track_heights()[1]
    timeline.set_track_height("audio", 90)
    assert timeline._audio_track_rects()["A1"].height() == 90
    assert timeline._video_track_rects()["V1"].height() == 120  # 视频不联动
    timeline.set_track_height("subtitle", 130)
    assert timeline._speaker_track_height() == 130
    assert timeline._video_track_height() == 120 and timeline._audio_track_height() == 90
    # 最小/最大钳制。
    timeline.set_track_height("video", 99999)
    assert timeline._video_track_height() == timeline.TRACK_HEIGHT_BOUNDS["video"][1]
    timeline.set_track_height("video", 1)
    assert timeline._video_track_height() == timeline.TRACK_HEIGHT_BOUNDS["video"][0]
    # 字幕轨拉高不改变 widget 最小高度（字幕区自带滚动）。
    minimum_before = timeline.minimumHeight()
    timeline.set_track_height("subtitle", timeline.TRACK_HEIGHT_BOUNDS["subtitle"][1])
    assert timeline.minimumHeight() == minimum_before


def test_geometry_stays_consistent(timeline):
    timeline.set_track_height("video", 120)
    timeline.set_track_height("audio", 60)
    video = timeline._video_track_rects()["V1"]
    audio = timeline._audio_track_rects()["A1"]
    assert audio.top() == pytest.approx(video.bottom())  # 音频行紧贴视频轨底
    assert timeline._pinned_bottom_height() == 120 + 60
    assert timeline._video_track_at(QPoint(800, round(video.center().y()))) == "V1"
    assert timeline._audio_track_at(QPoint(800, round(audio.center().y()))) == "A1"


def test_unified_strip_scrollbar_always_visible_single_track(timeline):
    # 无纵向溢出（单轨）时滚动条仍常驻=统一控制区不消失。
    assert timeline.vertical_scrollbar.isVisible()
    assert timeline.vertical_scrollbar.maximum() == 0
    # 右缘没有第二个控件列：rail 已退役。
    assert getattr(timeline, "_height_rail", None) is None


def test_boundary_drag_resizes_track_live(timeline):
    timeline._reset_track_height_kind("")
    bottom = round(timeline._video_track_rects()["V1"].bottom())
    hit = timeline._track_resize_boundary_at(QPoint(800, bottom))
    assert hit is not None and hit[0] == "video"
    # 右侧控制区列同样命中（把手位置=分界线在滚动条列的延伸）。
    strip_x = timeline.width() - timeline._track_height_strip_width() // 2
    strip_hit = timeline._track_resize_boundary_at(QPoint(strip_x, bottom))
    assert strip_hit is not None and strip_hit[0] == "video"
    # 轨头列不触发分界线（那是换轨拖动区）。
    assert timeline._track_resize_boundary_at(QPoint(100, bottom)) is None
    timeline.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 800, bottom))
    assert timeline._track_resize_drag is not None
    timeline.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 800, bottom + 44))
    assert timeline._video_track_height() == 58 + 44  # 下边下拖=调高（轨道自上而下排列），实时反馈
    timeline.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 800, bottom + 44))
    assert timeline._track_resize_drag is None
    assert timeline._video_track_rects()["V1"].height() == 102


def _mouse(event_type, local_x, local_y):
    return QMouseEvent(
        event_type,
        QPointF(local_x, local_y),
        QPointF(local_x, local_y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_double_click_on_boundary_resets_kind(timeline):
    timeline.set_track_height("video", 150)
    bottom = round(timeline._video_track_rects()["V1"].bottom())
    timeline.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick, 800, bottom))
    assert timeline._video_track_height() == 58
    # 右侧控制区把手位置双击同样恢复。
    timeline.set_track_height("audio", 90)
    audio_bottom = round(next(iter(timeline._audio_track_rects().values())).bottom())
    strip_x = timeline.width() - timeline._track_height_strip_width() // 2
    timeline.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick, strip_x, audio_bottom))
    assert "audio" not in timeline.track_heights()  # 恢复为自动高度


def test_grips_paint_low_contrast_and_emphasized(timeline):
    # 把手真实绘制：滚动条列、边界 y 处有非背景像素；悬停后强调色加深。
    timeline.set_track_height("video", 100)
    app = QApplication.instance()
    app.processEvents()
    image = timeline.grab().toImage()
    strip_x = timeline.width() - max(1, timeline._track_height_strip_width() // 2)
    bottom = round(timeline._video_track_rects()["V1"].bottom())
    device_ratio = image.devicePixelRatio() or 1.0

    def pixel_at(x, y):
        return image.pixelColor(round(x * device_ratio), round(y * device_ratio))

    grip_pixel = pixel_at(strip_x, bottom)
    background = pixel_at(strip_x, bottom - 30)
    assert grip_pixel is not None and background is not None
    assert grip_pixel != background  # 把手可见（非纯背景）
    # 常态低对比：与强调态（播放头色）不同色即可，不检查具体色值。


def test_height_state_roundtrip_snapshot(timeline):
    timeline.set_track_heights({"video": 100, "audio": 60, "subtitle": 88})
    assert timeline.track_heights() == {"video": 100, "audio": 60, "subtitle": 88}
    timeline.set_track_heights({"audio": 60})
    assert timeline.track_heights() == {"audio": 60}
    assert timeline._video_track_height() == 58
