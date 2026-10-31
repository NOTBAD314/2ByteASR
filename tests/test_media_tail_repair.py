"""Real media extents remain independent of navigation and high-resolution input."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent, QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.media_clip_shape import media_clip_shape as media_shape


@pytest.fixture
def timeline():
    app = QApplication.instance() or QApplication([])
    t = WaveformTimeline(); t.resize(1400, 430)
    t.set_project(SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=185000),
        cues=[StudioCue('a', 1000, 2000, '字幕')]))
    t._project_duration_ms=185000
    t.set_visible_window(0, 90000)
    yield t
    t.close(); t.deleteLater(); app.processEvents()


def wheel(t, *, angle=0, pixels=0, ctrl=False):
    p=QPointF(t.TRACK_HEADER_WIDTH+400,80)
    e=QWheelEvent(p,p,QPoint(pixels,0),QPoint(angle,0),Qt.NoButton,
        Qt.ControlModifier if ctrl else Qt.NoModifier,Qt.ScrollUpdate,False)
    QApplication.sendEvent(t,e)


def test_follow_uses_same_tail_range_as_manual_navigation(timeline):
    t=timeline;t.set_visible_window(10**9,90000)
    start=t.visible_start_ms
    assert start>t._duration_ms()-t.visible_duration_ms
    assert not t._follow_scroll(start)
    assert t.visible_start_ms==start==t.horizontal_scrollbar.maximum()


def test_paused_refresh_does_not_reclaim_manual_view_after_gesture_timeout(timeline):
    t=timeline;t.set_visible_window(10**9,90000);t.hold_manual_view()
    t._follow_suspended_until=0
    before=t.visible_start_ms
    assert not t.reveal_playhead(1000)
    assert not t.page_playhead(1000)
    assert t.visible_start_ms==before
    assert t.reveal_playhead(1000,force=True)


def test_trackpad_small_delta_is_not_a_full_wheel_notch(timeline):
    t=timeline;t.set_visible_window(50000,90000)
    start=t.visible_start_ms;wheel(t,pixels=-1)
    assert 0<t.visible_start_ms-start<200
    start=t.visible_start_ms;wheel(t,angle=-1)
    assert t.visible_start_ms-start==90


def test_small_zoom_keeps_mouse_anchor_and_scale_continuous(timeline):
    t=timeline;t.set_visible_window(50000,90000)
    x=t.TRACK_HEADER_WIDTH+400;before=t._x_to_time(x)
    wheel(t,angle=1,ctrl=True)
    assert 89000<t.visible_duration_ms<90000
    assert abs(t._x_to_time(x)-before)<=1


@pytest.mark.parametrize('left,right',[(50,300),(-10000,300),(50,10000),(50,52)])
def test_media_shape_clips_only_at_real_edges(left,right):
    image=QImage(500,60,QImage.Format_ARGB32);image.fill(QColor('white'))
    p=QPainter(image);rect,shape=media_shape(left,right,5,50,0,500)
    p.setClipPath(shape);p.fillRect(rect,QColor('blue'));p.end()
    if right<498:
        assert image.pixelColor(int(right)+1,30)==QColor('white')
    if left<0:
        assert image.pixelColor(0,6)==QColor('blue')  # no false corner at viewport
    if right>500:
        assert image.pixelColor(499,6)==QColor('blue')
    if right-left<=2:
        assert image.pixelColor(round((left+right)/2),30)==QColor('blue')
