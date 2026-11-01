from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
from twobyteasr.studio.studio_timeline import WaveformTimeline
from twobyteasr.studio.timeline_scrub import TimelineScrub


@pytest.mark.parametrize('ending', ['deactivate', 'ungrab', 'hide', 'escape', 'no_buttons', 'project'])
@pytest.mark.parametrize('playing', [False, True])
def test_interrupted_ruler_drag_releases_clock_and_pending_seek(ending, playing):
    app = QApplication.instance() or QApplication([])
    timeline = WaveformTimeline()
    timeline.thumbnail_requests_enabled = False
    timeline.resize(1100, 420)
    timeline.set_project(SubtitleProject(StudioMedia('', duration_ms=30000)))
    timeline.set_visible_window(0, 30000)
    timeline.show()
    app.processEvents()
    state = SimpleNamespace(paused=not playing, seeking=False)
    seeks, pauses = [], []
    page = timeline
    page.timeline = timeline
    def pause(value):
        pauses.append(value)
        state.paused = value
    page.video = SimpleNamespace(playback_position_snapshot=lambda: state, set_paused=pause)
    page._seek = lambda value, accurate=True: seeks.append((value, accurate))
    router = TimelineScrub(page)
    timeline.seek_requested.connect(router.request)
    timeline.scrub_finished.connect(router.finish)
    if hasattr(timeline, 'scrub_cancelled'):
        timeline.scrub_cancelled.connect(router.cancel)
    try:
        first = QPoint(round(timeline._time_to_x(3000)), 12)
        last = QPoint(round(timeline._time_to_x(7000)), 12)
        QTest.mousePress(timeline, Qt.LeftButton, Qt.NoModifier, first)
        QApplication.sendEvent(timeline, QMouseEvent(QEvent.MouseMove, QPointF(last),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        assert timeline._scrub_drag and router.active
        target = timeline.playhead_ms / 1000
        if ending in ('deactivate', 'ungrab'):
            QApplication.sendEvent(timeline, QEvent(QEvent.WindowDeactivate if ending == 'deactivate' else QEvent.UngrabMouse))
        elif ending == 'hide':
            timeline.hide()
        elif ending == 'escape':
            QTest.keyClick(timeline, Qt.Key_Escape)
        elif ending == 'project':
            timeline.set_project(None)
        else:
            QApplication.sendEvent(timeline, QMouseEvent(QEvent.MouseMove, QPointF(last + QPoint(100, 0)),
                Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        app.processEvents()
        assert not timeline._scrub_drag
        assert not router.active and not router.pressed and not page._timeline_scrub_active
        assert not router.timer.isActive() and router.pending is None
        router._flush()
        if ending in ('hide', 'project'):
            assert not seeks and False not in pauses  # no late seek/resume into a hidden/new project
        else:
            assert seeks == [(target, True)]
            assert state.paused == (not playing)
        timeline.set_playhead(12000)
        assert timeline.playhead_ms == 12000
    finally:
        router.timer.stop()
        QTest.mouseRelease(timeline, Qt.LeftButton, Qt.NoModifier, last)
        timeline.close()
        timeline.deleteLater()
        app.processEvents()
