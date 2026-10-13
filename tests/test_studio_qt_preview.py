"""Mac adapter boundaries; real decode/paint is the separate headed probe."""
import threading
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.studio_qt_preview import QtEmbeddedVideoController


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(app):
    canvas = QWidget()
    instance = QtEmbeddedVideoController(canvas)
    instance.start()
    yield instance
    instance.close()
    canvas.close()
    app.processEvents()


def test_factory_keeps_windows_process_owner_and_mac_owned_child(app, monkeypatch):
    import twobyteasr.studio_mpv as mpv
    marker = object()
    monkeypatch.setattr(mpv, 'MpvController', lambda: marker)
    assert mpv.create_preview_controller(platform='win32') is marker
    canvas = QWidget()
    controller = mpv.create_preview_controller(canvas, platform='darwin')
    controller.start()
    assert controller.surface.parentWidget() is canvas
    assert not controller.surface.isWindow()
    assert controller.player.audioOutput() is None
    controller.close()
    canvas.close()


def test_canvas_qt_start_never_promotes_native_window(app, monkeypatch, tmp_path):
    from PySide6.QtCore import Qt
    from twobyteasr import studio_video_canvas
    canvas = studio_video_canvas.MpvCanvas()
    canvas.setAttribute(Qt.WA_NativeWindow, False)
    monkeypatch.setattr(studio_video_canvas, 'studio_data_root', lambda: tmp_path)
    monkeypatch.setattr(studio_video_canvas, 'create_preview_controller', QtEmbeddedVideoController)
    def forbidden_handle():
        raise AssertionError('Qt child video must not call winId()')
    monkeypatch.setattr(canvas, 'winId', forbidden_handle)
    try:
        canvas._ensure_controller_started()
        assert canvas.controller.running
        assert not canvas.testAttribute(Qt.WA_NativeWindow)
        assert not canvas.controller.surface.testAttribute(Qt.WA_NativeWindow)
    finally:
        if canvas.controller:
            canvas.controller.close(); canvas.controller = None
        canvas.close(); app.processEvents()


def test_canvas_mpv_start_keeps_owned_native_handle(app, monkeypatch, tmp_path):
    from twobyteasr import studio_video_canvas
    seen = []
    controller = SimpleNamespace(running=False, start=lambda handle, **kw: seen.append(handle))
    canvas = studio_video_canvas.MpvCanvas()
    monkeypatch.setattr(studio_video_canvas, 'studio_data_root', lambda: tmp_path)
    monkeypatch.setattr(studio_video_canvas, 'create_preview_controller', lambda owner: controller)
    monkeypatch.setattr(canvas, 'winId', lambda: 1234)
    try:
        canvas._ensure_controller_started()
        assert seen == [1234]
    finally:
        canvas.controller = None
        canvas.close(); app.processEvents()


def test_qobject_creation_rejects_worker_thread(app):
    errors = []
    def worker():
        try: QtEmbeddedVideoController(None)
        except RuntimeError as exc: errors.append(str(exc))
    thread = threading.Thread(target=worker)
    thread.start(); thread.join(2)
    assert not thread.is_alive() and len(errors) == 1
    assert 'GUI thread' in errors[0]


def write_overlay(folder):
    image = QImage(3, 2, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('#ff112233'))
    path = folder/'owned.bgra'
    path.write_bytes(bytes(image.constBits()))
    return path, dict(x=2,y=3,width=3,height=2,stride=image.bytesPerLine())


def test_worker_post_coalesces_then_gui_copies_pixels_before_ack(app, controller, tmp_path):
    path, geometry = write_overlay(tmp_path)
    outcomes = []
    applied_thread = []
    def worker():
        controller.post_raw_overlay(1,path,**geometry,on_applied=lambda ok: outcomes.append(('old',ok)))
        controller.post_raw_overlay(1,path,**geometry,on_applied=lambda ok:
            (outcomes.append(('current',ok)),applied_thread.append(threading.get_ident())))
    thread = threading.Thread(target=worker)
    thread.start(); thread.join(2)
    assert outcomes == [('old',False)]
    app.processEvents()
    assert outcomes == [('old',False),('current',True)]
    assert applied_thread == [threading.get_ident()]
    path.write_bytes(b'\0'*24)
    assert controller.surface.overlays[1][0].pixelColor(0,0).name() == '#112233'
    controller.clear_media()
    assert not controller.surface.overlays
    assert not controller.applied_visual_state()['overlays'][1]['visible']


def test_source_clear_rejects_queued_old_overlay_and_close_is_idempotent(app,controller,tmp_path):
    path, geometry = write_overlay(tmp_path)
    outcomes = []
    controller.post_raw_overlay(1,path,**geometry,on_applied=outcomes.append)
    controller.clear_media()
    app.processEvents()
    assert outcomes == [False] and not controller.surface.overlays
    controller.close(); controller.close()
    assert not controller.running


def test_sync_player_operations_reject_worker_thread(controller):
    errors = []
    def worker():
        try: controller.set_paused(False)
        except RuntimeError as exc: errors.append(str(exc))
    thread = threading.Thread(target=worker)
    thread.start(); thread.join(2)
    assert len(errors) == 1 and 'GUI thread' in errors[0]


def test_stalled_playing_source_is_not_reported_alive(controller,monkeypatch):
    import twobyteasr.studio_qt_preview as preview
    controller._desired_paused = False
    controller._last_activity = 1.0
    monkeypatch.setattr(preview.time,'monotonic',lambda:10.0)
    assert not controller.source_alive(max_silence_s=5)
    controller._desired_paused = True
    assert controller.source_alive(max_silence_s=5)


def test_windows_shortcut_defaults_are_unchanged(app,monkeypatch):
    import sys
    from twobyteasr.studio_shortcuts import STUDIO_COMMANDS,studio_default_shortcuts
    monkeypatch.setattr(sys,'platform','win32')
    assert studio_default_shortcuts() == {key:row[1] for key,row in STUDIO_COMMANDS.items()}


@pytest.mark.parametrize('native_supported,expected',[ (False,True),(True,False)])
def test_single_cue_uses_scene_only_for_raster_only_backend(app,native_supported,expected):
    from twobyteasr.caption_scene import CaptionScene
    page = QWidget()
    page.project = SimpleNamespace(render_settings={})
    calls = []
    page.video = SimpleNamespace(controller=SimpleNamespace(supports_native_subtitles=native_supported),
                                clear_caption_boundaries=lambda:calls.append('clear'))
    page._stop_web_live_preview = lambda why:calls.append('web')
    page._revoke_advanced_preview = lambda **kw:calls.append('advanced')
    page._revision_store = SimpleNamespace(render=None)
    page.position_overlay = SimpleNamespace(_content_rect=lambda:QRectF())
    scene = CaptionScene(page)
    assert scene.present([SimpleNamespace(id='ordinary')],500) is expected
    assert scene.active is expected
    assert bool(calls) is expected
    scene.close()
    page.close()
