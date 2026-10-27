"""Mac adapter boundaries; real decode/paint is the separate headed probe."""
import threading
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.studio.studio_qt_preview import QtEmbeddedVideoController


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
    import twobyteasr.playback.studio_mpv as mpv
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
    from twobyteasr.studio import studio_video_canvas
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
    from twobyteasr.studio import studio_video_canvas
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


def test_reloading_the_same_media_clears_the_source_first(controller, tmp_path):
    """QMediaPlayer ignores setSource(current URL): a reopen of the same file
    must clear first or it never reaches LoadedMedia (2026-10-14)."""
    from PySide6.QtCore import QUrl
    media = tmp_path / 'same.mp4'
    media.write_bytes(b'not decoded in this test')
    calls = []
    original = controller.player.setSource
    controller.player.setSource = lambda url: (calls.append(url.toLocalFile() or '<empty>'), original(url))[1]
    controller.load(str(media))
    controller.load(str(media))
    path = media.resolve().as_posix()
    assert calls == [path, '<empty>', path]


class QueuedFrame:
    """A decoded QVideoFrame as the sink delivers it to the GUI thread."""
    def __init__(self, seconds, colour='#204060', fps=30):
        self.start = round(seconds*1_000_000)
        self.end = self.start+round(1_000_000/fps)
        self.image = QImage(4, 4, QImage.Format_RGB32)
        self.image.fill(QColor(colour))
    def isValid(self): return True
    def toImage(self): return self.image
    def startTime(self): return self.start
    def endTime(self): return self.end


class PrerollPlayer:
    """Qt 6.9 FFmpeg player semantics the controller depends on.

    position() changes only through setPosition() (or the 50 ms timer, which
    a busy GUI thread never runs); pause() stops that timer without
    refreshing it.
    """
    def __init__(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QMediaPlayer
        self.calls, self.milliseconds, self.url = [], 0, QUrl()
        self.state = QMediaPlayer.StoppedState
    def stop(self):
        from PySide6.QtMultimedia import QMediaPlayer
        self.calls.append('stop'); self.state = QMediaPlayer.StoppedState
    def source(self): return self.url
    def setSource(self, url): self.url = url
    def setPosition(self, milliseconds):
        self.calls.append(('seek', milliseconds)); self.milliseconds = milliseconds
    def position(self): return self.milliseconds
    def play(self):
        from PySide6.QtMultimedia import QMediaPlayer
        self.calls.append('play'); self.state = QMediaPlayer.PlayingState
    def pause(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self.state != QMediaPlayer.PausedState: self.calls.append('pause')
        self.state = QMediaPlayer.PausedState
    def playbackState(self): return self.state
    def duration(self): return 12_000
    def audioOutput(self): return None
    def setAudioOutput(self, _output): pass


def readiness_page(controller, media, generation):
    clock = SimpleNamespace(exact_seek_pending=False, generation=generation)
    video = SimpleNamespace(_startup_state='READY', _playback_clock=clock,
                            _media_path=str(media.resolve()), _media_has_video=True,
                            controller=controller)
    return SimpleNamespace(video=video)


def preroll(controller, tmp_path, seconds=0.0, generation=2):
    from PySide6.QtMultimedia import QMediaPlayer
    media = tmp_path/'中文 字幕・日本語.mp4'
    media.write_bytes(b'not decoded in this test')
    player = controller.player = PrerollPlayer()
    controller._load(str(media), seconds, generation)
    controller._status(QMediaPlayer.LoadedMedia)
    assert player.calls[-2:] == [('seek', round(seconds*1000)), 'play']
    return media, player


def test_frames_queued_behind_a_busy_gui_preroll_resettle_the_paused_target(controller, tmp_path):
    """macOS 14 CI run 40507178649: the cold Studio load kept the GUI thread
    busy ~670 ms after the muted preroll play(). 21 frames queued; the target
    frame paused the player, the later ones replaced it, position() stayed 0
    and Studio waited at 准备播放器 until 准备超时."""
    from twobyteasr.studio.studio_readiness import player_surface_ready
    media, player = preroll(controller, tmp_path)
    page = readiness_page(controller, media, 2)
    for index in range(21):
        controller._frame(QueuedFrame(index/30, colour='#ff0000' if index > 1 else '#00ff00'))
    shown = controller.observed_properties()
    # Frames beyond one readiness tolerance never become the current picture;
    # the paused target is requested again instead of waiting for a frame
    # that never comes.
    assert controller.surface.frame.pixelColor(0, 0).name() == '#00ff00'
    assert shown['video-frame-info'] == {} and shown['seeking']
    assert player.calls.count(('seek', 0)) == 2
    assert not player_surface_ready(page)
    controller._frame(QueuedFrame(0.0, colour='#0000ff'))  # The paused seek's one frame.
    shown = controller.observed_properties()
    assert shown['video-frame-info']['pts'] == 0.0 and shown['time-pos'] == 0.0
    assert controller.surface.frame.pixelColor(0, 0).name() == '#0000ff'
    assert controller.applied_seek_state()['generation'] == 2
    assert controller.actor_status()['paused_target_resettles'] == 1
    assert player_surface_ready(page)


def test_unsettled_preroll_reproduces_the_stale_pts_gate(controller, tmp_path):
    """Without a second paused seek the 0.8.7 state is never ready."""
    from twobyteasr.studio.studio_readiness import player_surface_ready
    media, _player = preroll(controller, tmp_path)
    page = readiness_page(controller, media, 2)
    controller._frame(QueuedFrame(0.0))
    controller._settle_target = None  # The 0.8.7 controller had no settle step.
    for index in range(1, 21):
        controller._frame(QueuedFrame(index/30))
    shown = controller.observed_properties()
    assert shown['video-frame-info']['pts'] == pytest.approx(.666667)
    assert shown['time-pos'] == 0.0
    assert controller.applied_seek_state()['frame_pts'] == 0.0
    assert not player_surface_ready(page)


def test_pausing_while_playing_keeps_the_frames_it_reached(controller, tmp_path):
    media, player = preroll(controller, tmp_path)
    controller._frame(QueuedFrame(0.0))
    controller.set_paused(False)
    for index in range(1, 10):
        controller._frame(QueuedFrame(index/30))
    controller.set_paused(True)  # No position: nothing says where to stop.
    controller._frame(QueuedFrame(10/30))
    assert player.calls.count(('seek', 0)) == 1
    assert controller.observed_properties()['video-frame-info']['pts'] == pytest.approx(10/30)


def test_paused_seek_after_a_late_frame_resettles_a_bounded_number_of_times(controller, tmp_path):
    from twobyteasr.studio.studio_qt_preview import SETTLE_ATTEMPTS
    media, player = preroll(controller, tmp_path, seconds=5.0)
    controller._frame(QueuedFrame(5.0))
    for _attempt in range(SETTLE_ATTEMPTS+2):
        controller._frame(QueuedFrame(5.5))  # Late frame, then the seek's frame
        controller._frame(QueuedFrame(5.0))  # lands on target again.
    # A backend that keeps drifting is shown and left to readiness to report.
    assert player.calls.count(('seek', 5000)) == 1+SETTLE_ATTEMPTS
    controller._frame(QueuedFrame(5.5))
    assert controller.observed_properties()['video-frame-info']['pts'] == 5.5
    controller.seek(7.0)  # A new target gets its own attempts.
    controller._frame(QueuedFrame(7.0))
    controller._frame(QueuedFrame(7.5))
    assert player.calls[-1] == ('seek', 7000) and controller._settle_attempts == 1


def test_sync_player_operations_reject_worker_thread(controller):
    errors = []
    def worker():
        try: controller.set_paused(False)
        except RuntimeError as exc: errors.append(str(exc))
    thread = threading.Thread(target=worker)
    thread.start(); thread.join(2)
    assert len(errors) == 1 and 'GUI thread' in errors[0]


def test_stalled_playing_source_is_not_reported_alive(controller,monkeypatch):
    import twobyteasr.studio.studio_qt_preview as preview
    controller._desired_paused = False
    controller._last_activity = 1.0
    monkeypatch.setattr(preview.time,'monotonic',lambda:10.0)
    assert not controller.source_alive(max_silence_s=5)
    controller._desired_paused = True
    assert controller.source_alive(max_silence_s=5)


def test_windows_shortcut_defaults_are_unchanged(app,monkeypatch):
    import sys
    from twobyteasr.studio.studio_shortcuts import STUDIO_COMMANDS,studio_default_shortcuts
    monkeypatch.setattr(sys,'platform','win32')
    assert studio_default_shortcuts() == {key:row[1] for key,row in STUDIO_COMMANDS.items()}


@pytest.mark.parametrize('native_supported,expected',[ (False,True),(True,False)])
def test_single_cue_uses_scene_only_for_raster_only_backend(app,native_supported,expected):
    from twobyteasr.rendering.caption_scene import CaptionScene
    page = QWidget()
    page.project = SimpleNamespace(render_settings={},effects={})
    calls = []
    page.video = SimpleNamespace(controller=SimpleNamespace(supports_native_subtitles=native_supported),
                                clear_caption_boundaries=lambda:calls.append('clear'))
    page._stop_web_live_preview = lambda why:calls.append('web')
    page._revoke_advanced_preview = lambda **kw:calls.append('advanced')
    page._revision_store = SimpleNamespace(render=None)
    page.position_overlay = SimpleNamespace(_content_rect=lambda:QRectF())
    scene = CaptionScene(page)
    assert scene.present([SimpleNamespace(id='ordinary',effect_id='none')],500) is expected
    assert scene.active is expected
    assert bool(calls) is expected
    scene.close()
    page.close()
