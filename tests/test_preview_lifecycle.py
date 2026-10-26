"""Regressions for native surface ownership and deferred callbacks."""
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

@pytest.fixture
def app():return QApplication.instance() or QApplication([])


def test_hub_hides_the_native_editor_subtree(app,monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_DIAGNOSTIC_NO_PLAYER','1')
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    page=SubtitleStudioPage();page.show();app.processEvents()
    try:
        page._set_hub_toolbar_mode(False);page.studio_empty.hide();app.processEvents()
        assert page.video.isVisible()
        page._set_hub_toolbar_mode(True);page.studio_empty.show();page.studio_empty.raise_();app.processEvents()
        assert not page.video.isVisible()
        assert not page.workspace_splitter.isVisible()
        page._set_hub_toolbar_mode(False);page.studio_empty.hide();app.processEvents()
        assert page.video.isVisible()
    finally:page.close_page();page.close();page.deleteLater()


def test_old_media_callback_cannot_cross_hide_show_or_replacement(app):
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=MpvCanvas();seen=[]
    canvas._defer_media_callback(0,lambda:seen.append('old'),source='old')
    canvas.set_navigation_visible(False);canvas.set_navigation_visible(True)
    app.processEvents();assert seen==[]
    canvas._defer_media_callback(0,lambda:seen.append('replaced'),source='replacement')
    canvas._load_generation=1
    app.processEvents();assert seen==[]
    canvas._defer_media_callback(0,lambda:seen.append('current'),source='current')
    app.processEvents();assert seen==['current']
    canvas.deleteLater()


def test_hidden_surface_rejects_delayed_play_and_reopens_paused(app):
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=MpvCanvas();canvas._clock_only=True
    canvas.set_paused(False);assert not canvas._paused
    canvas.set_navigation_visible(False)
    canvas.set_paused(False)
    assert canvas._paused
    assert not canvas._timer.isActive() and not canvas._buffered_play_timer.isActive()
    canvas.set_navigation_visible(True)
    assert canvas._paused
    canvas.set_paused(False);assert not canvas._paused
    canvas.set_paused(True);canvas._timer.stop();canvas.deleteLater()



def test_cancel_for_library_invalidates_loading_without_reopening_old_view(app):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from twobyteasr.studio.studio_readiness import StudioReadiness
    page=SimpleNamespace(video=Mock(),timeline=Mock(),project=object(),_project_view_state='hub',
                         _studio_trace=Mock(),_sync_navigation_chrome=Mock(),show_project_hub=Mock())
    gate=SimpleNamespace(page=page,generation=4,active=True,ready=False,steps=object(),timer=Mock(),
                         on_ready=Mock(),overlay=Mock(),finished=Mock(),path='owned-project')
    StudioReadiness.cancel(gate,navigate=False)
    assert gate.generation==5 and not gate.active and gate.on_ready is None
    assert page._project_view_state=='hub'
    gate.finished.emit.assert_not_called()
    page.show_project_hub.assert_not_called()


def test_hidden_picture_keeps_active_audio_only_project_clock(app,monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtGui import QHideEvent
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=MpvCanvas()
    page=SimpleNamespace(isVisible=lambda:True,workspace_splitter=SimpleNamespace(isVisible=lambda:True),project=None,
                         _studio_trace=lambda *args,**kwargs:None)
    monkeypatch.setattr(canvas,'_studio_page',lambda:page)
    canvas.enter_timeline_gap(0,10000)
    canvas.hideEvent(QHideEvent())
    assert canvas._navigation_visible and canvas._timer.isActive()
    canvas.set_paused(False)
    assert not canvas._paused
    # Leaving the owning editor still pauses audio, even though its picture was already hidden.
    canvas.set_navigation_visible(False)
    assert canvas._paused
    canvas.set_navigation_visible(True)
    assert canvas._paused
    canvas._timer.stop();canvas._sync_timer.stop();canvas.deleteLater()


def test_replacing_project_does_not_cancel_its_own_readiness(app,monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_DIAGNOSTIC_NO_PLAYER','1')
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.studio.studio_readiness import StudioReadiness
    page=SubtitleStudioPage();gate=page._readiness=StudioReadiness(page)
    try:
        gate.active=True;gate.generation=12
        page._close_project_session('project_switch')
        assert gate.active and gate.generation==12
        page._close_project_session('project_hub')
        assert not gate.active and gate.generation==13
    finally:page.close_page();page.close();page.deleteLater()
