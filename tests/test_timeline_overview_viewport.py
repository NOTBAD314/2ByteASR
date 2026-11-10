"""Viewport-aligned review markers and bounded local navigation."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.timeline_overview import TimelineOverview


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def view(application):
    project = SubtitleProject(media=StudioMedia('', duration_ms=1_000_000), cues=[
        StudioCue('early', 2000, 3000, '片头错误'),
        StudioCue('edge', 95_000, 105_000, '跨越左边缘'),
        StudioCue('local', 110_000, 120_000, '当前窗口错误'),
        StudioCue('right', 155_000, 170_000, '跨越右边缘'),
        StudioCue('late', 950_000, 951_000, '片尾错误')])
    timeline = WaveformTimeline()
    timeline.resize(1000, 350)
    timeline.set_project(project)
    timeline.set_visible_window(100_000, 60_000)
    overview = TimelineOverview(SimpleNamespace(project=project), timeline)
    overview.resize(1000, overview.HEIGHT)
    overview.show()
    application.processEvents()
    yield overview, timeline
    overview.close()
    timeline.close()
    overview.deleteLater()
    timeline.deleteLater()
    application.processEvents()


def test_markers_include_only_cues_intersecting_the_visible_interval(view):
    overview, _ = view
    assert {cue.id for cue in overview._cues()[1]} == {'edge', 'local', 'right'}


def test_marker_coordinates_match_the_timeline_ruler(view):
    overview, timeline = view
    assert overview._x(110_000) == timeline._time_to_x(110_000)
    assert overview._ms(overview._track().center().x()) == 130_000


def test_scroll_and_zoom_both_invalidate_the_marker_cache(view):
    overview, timeline = view
    overview.grab()
    original = overview._marker_key
    timeline.set_visible_window(300_000, 60_000)
    overview.grab()
    scrolled = overview._marker_key
    assert scrolled != original
    assert not overview._cues()[1]
    timeline.set_visible_window(300_000, 15_000)
    overview.grab()
    assert overview._marker_key != scrolled


def test_click_uses_local_time_instead_of_project_fraction(view):
    overview, timeline = view
    track = overview._track()
    point = QPoint(round(track.left() + track.width() * .75), round(track.center().y()))
    QTest.mouseClick(overview, Qt.MouseButton.LeftButton, pos=point)
    assert 114_000 <= timeline.visible_start_ms <= 116_000
    assert timeline.visible_duration_ms == 60_000


def test_drag_keeps_the_press_window_as_its_coordinate_frame(view):
    overview, timeline = view
    track = overview._track()
    point = QPoint(round(track.left() + track.width() * .75), round(track.center().y()))
    QTest.mousePress(overview, Qt.MouseButton.LeftButton, pos=point)
    after_press = timeline.visible_start_ms
    for _ in range(5):
        overview._jump(point.x())
        assert timeline.visible_start_ms == after_press
    overview._jump(track.right() + 10_000)
    assert timeline.visible_start_ms == 130_000
    QTest.mouseRelease(overview, Qt.MouseButton.LeftButton, pos=point)
    assert overview._drag_window is None


def test_header_click_does_not_navigate(view):
    overview, timeline = view
    QTest.mouseClick(overview, Qt.MouseButton.LeftButton, pos=QPoint(5, 9))
    assert timeline.visible_start_ms == 100_000


def test_empty_tail_uses_the_same_visible_coordinates_as_the_ruler(view):
    overview, timeline = view
    timeline.set_visible_window(990_000, 60_000)
    assert overview._ms(overview._track().right() + 1000) == timeline.visible_start_ms + timeline.visible_duration_ms


def test_playback_follow_repaints_without_waiting_for_the_poll_timer(view, application):
    overview, timeline = view
    overview._timer.stop()
    before = overview._marker_key
    assert timeline._follow_scroll(101_234)
    application.processEvents()
    assert overview._marker_key != before
    assert overview._painted_state[1] == 101_234


def test_scrollbar_repaints_without_polling(view, application):
    overview, timeline = view
    overview._timer.stop()
    timeline.horizontal_scrollbar.setValue(104_321)
    application.processEvents()
    assert overview._painted_state[1] == 104_321


def test_playhead_alone_keeps_markers_fixed(view, application):
    overview, timeline = view
    before = overview._marker_key
    timeline.set_playhead(112_345)
    application.processEvents()
    overview._tick()
    application.processEvents()
    assert overview._marker_key == before


def test_cursor_only_paint_reuses_markers_without_querying_cues(view, application, monkeypatch):
    overview, timeline = view
    overview.grab()
    def fail():
        raise AssertionError('cursor-only paint enumerated captions')
    monkeypatch.setattr(overview, '_cues', fail)
    timeline.set_playhead(112_000)
    overview._tick()
    application.processEvents()
    overview.grab()
