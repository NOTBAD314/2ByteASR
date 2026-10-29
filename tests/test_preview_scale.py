"""Playback preview at full, 1/2 or 1/4 size (2026-10-21)."""
from types import SimpleNamespace

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication

from twobyteasr.playback.platform_mpv import preview_scale_filter, preview_scale_value
from twobyteasr.playback.secondary_video import SourceState
from twobyteasr.playback.studio_mpv import MpvController
from twobyteasr.playback.video_compositor import VideoCompositionScene
from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin
from twobyteasr.studio.studio_video_canvas import MpvCanvas

APP = QApplication.instance() or QApplication([])


class _RunningProcess:
    def poll(self):
        return None


class _RecordingActor:
    def __init__(self, hwdec=""):
        self.posts = []
        self.values = {"hwdec-current": hwdec}

    def property(self, name, default=None):
        return self.values.get(name, default)

    def post(self, callback, *, coalesce_key="", foreground=False, deferred=False, on_discard=None):
        self.posts.append((callback, coalesce_key))
        return True


def test_filter_follows_the_decoder_and_snaps_to_offered_sizes():
    cpu_half = "scale=w=trunc(iw*0.5/2)*2:h=-2:flags=fast_bilinear"
    assert preview_scale_filter(1.0, hwdec="d3d11va", platform="win32") == ""
    # Zero-copy hardware frames: GPU scaling (lavfi scale cannot touch them).
    assert preview_scale_filter(0.5, hwdec="d3d11va", platform="win32") == "d3d11vpp=scale=0.5"
    assert preview_scale_filter(0.25, hwdec="d3d11va", platform="win32") == "d3d11vpp=scale=0.25"
    # Before mpv reports a decoder, Windows assumes the usual d3d11va.
    assert preview_scale_filter(0.5, hwdec="", platform="win32") == "d3d11vpp=scale=0.5"
    # Software or copy-back frames: CPU scaling; d3d11vpp would upload full frames.
    assert preview_scale_filter(0.5, hwdec="no", platform="win32") == cpu_half
    assert preview_scale_filter(0.5, hwdec="d3d11va-copy", platform="win32") == cpu_half
    assert preview_scale_filter(0.5, platform="linux") == cpu_half
    # Registry values come back as text; anything unreadable is full size.
    assert preview_scale_value("0.5") == 0.5
    assert preview_scale_value(0.3) == 0.25
    assert preview_scale_value(None) == 1.0
    assert preview_scale_value("full") == 1.0


def test_preview_scale_is_latest_wins_and_replays_after_reconnect(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    controller = MpvController(executable)
    controller._process = _RunningProcess()
    actor = _RecordingActor(hwdec="d3d11va")
    controller._actor = actor
    sent = []
    controller._send = lambda command, timeout=2.0: sent.append(list(command)) or {}

    assert controller.post_set_preview_scale(0.5)
    assert controller.post_set_preview_scale(0.25)
    assert [key for _callback, key in actor.posts] == ["preview-scale", "preview-scale"]
    actor.posts[-1][0]()
    expected = ["set_property", "vf", "d3d11vpp=scale=0.25"]
    assert sent == [expected]

    replayed = []

    class Actor:
        def _exchange_on_pipe(self, command, *, timeout):
            replayed.append(list(command))
            return {"error": "success"}

    controller._restore_desired_state(Actor())
    assert replayed == [expected]

    # mpv fell back to software decoding: the next post switches to CPU scaling.
    actor.values["hwdec-current"] = "no"
    assert controller.post_set_preview_scale(0.25)
    actor.posts[-1][0]()
    assert sent[-1] == ["set_property", "vf", "scale=w=trunc(iw*0.25/2)*2:h=-2:flags=fast_bilinear"]


def test_canvas_applies_the_scale_now_and_to_a_restarted_player(monkeypatch):
    canvas = MpvCanvas()
    posted = []
    canvas.controller = SimpleNamespace(running=True, post_set_preview_scale=posted.append)
    canvas.set_preview_scale(0.5)
    assert posted == [0.5] and canvas.preview_scale() == 0.5

    started = []

    class Restarted:
        backend = "mpv"
        running = False

        def start(self, window_id, *, log_path=""):
            started.append(window_id)
            self.running = True

        def post_set_preview_scale(self, value):
            posted.append(("restarted", value))

    canvas.controller = None
    monkeypatch.setattr("twobyteasr.studio.studio_video_canvas.create_preview_controller", lambda _canvas: Restarted())
    canvas._ensure_controller_started()
    assert started and posted[-1] == ("restarted", 0.5)
    canvas.controller = None
    canvas.deleteLater()


def test_overlay_aspect_follows_the_source_not_the_reduced_output():
    size = MpvCanvas._source_display_size
    assert size({"dw": 960, "dh": 540}, {"dw": 3840, "dh": 2160}) == (3840, 2160)
    # 1/4 of 1366x768 rounds; the decoder's size keeps the exact aspect.
    assert size({"dw": 342, "dh": 192}, {"dw": 1366, "dh": 768}) == (1366, 768)
    assert size({"dw": 1920, "dh": 1080}, None) == (1920, 1080)
    # No output yet means no frame yet, whatever the decoder reports.
    assert size({}, {"dw": 3840, "dh": 2160}) == (0, 0)


def test_followers_decode_at_the_reduced_preview_size(monkeypatch):
    sizes = []

    class Decoder(QObject):
        frame_updated = Signal()
        state = SourceState.IDLE

        def set_preview_size(self, width, height):
            sizes.append((round(width), round(height)))

        def prepare(self, path):
            self._pending_path = path

        def request_frame(self, *args, **kwargs):
            pass

        def release(self):
            pass

        def suspend(self):
            pass

    monkeypatch.setattr("twobyteasr.playback.video_compositor.SecondaryVideoSource", Decoder)
    scene = VideoCompositionScene()
    scene.resize(800, 450)
    dpr = scene.devicePixelRatioF()
    layers = [{"clip_id": "v2", "track_id": "V2", "source_path": "secondary.mp4"}]

    def compose():
        scene.set_composition(layers, paused=True, rate=1, audio_master_track_id="",
                              base_track_id="V2", volume=0, mpv_path="primary.mp4")

    compose()
    scene.set_preview_scale(0.5)
    compose()
    full_width, full_height = min(1920, 800 * dpr * 1.25), min(1080, 450 * dpr * 1.25)
    assert sizes == [(round(full_width), round(full_height)),
                     (round(full_width / 2), round(full_height / 2))]
    scene.suspend()
    scene.clear()
    scene.deleteLater()


def test_page_choice_reaches_both_previews_and_is_remembered_per_machine():
    applied = []
    host = SimpleNamespace(
        video=SimpleNamespace(set_preview_scale=lambda value: applied.append(("video", value))),
        video_compositor=SimpleNamespace(set_preview_scale=lambda value: applied.append(("followers", value))),
    )
    settings = QSettings("2ByteASR", "2ByteASR")
    settings.remove("studio/preview_scale")

    StudioPlaybackFlowMixin._set_preview_scale(host, 0.25, remember=False)
    assert settings.value("studio/preview_scale") is None
    StudioPlaybackFlowMixin._set_preview_scale(host, "0.5")
    assert applied == [("video", 0.25), ("followers", 0.25), ("video", 0.5), ("followers", 0.5)]
    assert preview_scale_value(QSettings("2ByteASR", "2ByteASR").value("studio/preview_scale")) == 0.5
    settings.remove("studio/preview_scale")
