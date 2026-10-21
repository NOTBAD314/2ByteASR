"""Playback lifecycle truth: idle/death must never leave the UI faking Playing.

The mpv/media clock is the only playback truth. When its transport dies
(process exit or wedged IPC) the canvas must adopt an explicit dead state,
force the presentation clock honest, and allow user-initiated revive.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_video_canvas import MpvCanvas


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class FakeActorBackedController:
    """Duck-typed controller mirroring the MpvController surface the canvas uses."""

    def __init__(self, *, running: bool = True, alive: bool = True) -> None:
        self.running = running
        self._alive = alive
        self.paused_commands: list[bool] = []
        self.load_calls: list[object] = []
        self.start_calls: list[int] = []
        self.closed = False
        self.observed = {
            "pause": True,
            "time-pos": 0.0,
            "core-idle": False,
            "eof-reached": False,
            "idle-active": False,
            "seeking": False,
            "path": "media.mp4",
        }

    def source_alive(self, *, max_silence_s: float = 5.0) -> bool:
        return self.running and self._alive

    def actor_status(self) -> dict:
        return {"degraded": not self._alive, "thread_alive": True, "pipe_open": self._alive}

    def observed_properties(self) -> dict:
        return dict(self.observed)

    def observed_position(self) -> dict:
        return {
            "source_generation": 1,
            "actor_sequence": 1,
            "observed_monotonic_ts": 0.0,
            "position": self.observed.get("time-pos"),
            "source": "property_change",
        }

    def applied_seek_state(self) -> dict:
        return {}

    def post_set_paused(self, paused: bool) -> bool:
        self.paused_commands.append(bool(paused))
        return self.running

    def set_paused(self, paused: bool) -> None:
        self.paused_commands.append(bool(paused))

    def post_set_speed(self, speed: float) -> bool:
        self.observed['speed'] = speed
        return self.running

    def load(self, media_path: str) -> None:
        self.load_calls.append(media_path)

    def post_load_at(self, media_path, seconds, *, generation) -> bool:
        return False

    def post_seek(self, seconds: float, **_kwargs) -> bool:
        return self.running

    def start(self, window_id: int, *, log_path: str = "") -> None:
        self.start_calls.append(int(window_id))

    def close(self) -> None:
        self.closed = True
        self.running = False


def _playing_canvas(*, paused: bool = False) -> tuple[MpvCanvas, FakeActorBackedController]:
    _app()
    canvas = MpvCanvas()
    controller = FakeActorBackedController()
    canvas.controller = controller
    canvas._media_path = "media.mp4"
    canvas._media_attached = True
    canvas._startup_state = "READY"
    canvas._duration = 60.0
    canvas._playback_clock.force_position(12_000.0, paused=paused, reason="setup")
    canvas._adopt_playback_snapshot(canvas._playback_clock.snapshot(), emit=False)
    canvas._paused = paused
    canvas._timer.start()
    canvas._sync_timer.start()
    return canvas, controller


def test_play_idle_death_forces_honest_paused_state():
    canvas, controller = _playing_canvas(paused=False)
    assert canvas._paused is False
    assert not canvas.playback_source_dead

    errors: list[str] = []
    canvas.error.connect(errors.append)
    controller.running = False

    canvas._reconcile_position()

    assert canvas.playback_source_dead
    assert canvas.playback_position_snapshot().paused is True
    assert canvas._paused is True
    assert not canvas._timer.isActive()
    assert not canvas._sync_timer.isActive()
    assert len(errors) == 1 and "恢复" in errors[0]
    # Position is preserved so revive can resume where playback stopped.
    assert canvas.playback_position_snapshot().presentation_media_ms == pytest.approx(12_000.0)
    canvas.deleteLater()


def test_paused_idle_death_then_play_revives():
    canvas, controller = _playing_canvas(paused=True)
    controller.running = False
    canvas._reconcile_position()
    assert canvas.playback_source_dead

    replacement = FakeActorBackedController()
    created: list[FakeActorBackedController] = []

    import twobyteasr.studio.studio_video_canvas as canvas_module

    original_controller_cls = canvas_module.create_preview_controller

    def _factory(*_args, **_kwargs):
        created.append(replacement)
        return replacement

    canvas_module.create_preview_controller = staticmethod(_factory)
    try:
        assert canvas.revive_dead_source(paused=False) is True
    finally:
        canvas_module.create_preview_controller = original_controller_cls

    assert created == [replacement]
    assert replacement.start_calls, "revive must start a fresh mpv child"
    assert replacement.load_calls == ["media.mp4"]
    assert not canvas.playback_source_dead
    # set_paused during MEDIA_OPENING records the startup intent instead of
    # issuing an IPC command that could race file initialization.
    assert canvas._startup_play_requested is True
    canvas.deleteLater()


def test_seek_while_dead_keeps_optimistic_playhead_without_raise():
    canvas, controller = _playing_canvas(paused=True)
    controller.running = False
    canvas._reconcile_position()

    canvas.seek(30.0, accurate=True)

    snapshot = canvas.playback_position_snapshot()
    assert snapshot.presentation_media_ms == pytest.approx(30_000.0)
    assert snapshot.paused is True
    assert canvas.playback_source_dead
    canvas.deleteLater()


def test_transport_stall_enters_dead_state_while_process_alive():
    canvas, controller = _playing_canvas(paused=False)
    controller._alive = False  # running, but IPC silent past the heartbeat budget

    canvas._reconcile_position()

    assert canvas.playback_source_dead
    assert canvas.playback_position_snapshot().paused is True
    canvas.deleteLater()


def test_project_reload_replaces_dead_controller():
    """切换项目 → idle → play: load() must never inherit a dead controller."""
    canvas, controller = _playing_canvas(paused=True)
    controller.running = False
    canvas._reconcile_position()
    assert canvas.playback_source_dead

    replacement = FakeActorBackedController()
    created: list[FakeActorBackedController] = []

    import twobyteasr.studio.studio_video_canvas as canvas_module

    original_controller_cls = canvas_module.create_preview_controller

    def _factory(*_args, **_kwargs):
        created.append(replacement)
        return replacement

    canvas_module.create_preview_controller = staticmethod(_factory)
    try:
        canvas.load("media.mp4", "", start_seconds=5.0)
    finally:
        canvas_module.create_preview_controller = original_controller_cls

    assert controller.closed, "dead controller must be closed, not reused"
    assert created == [replacement]
    assert not canvas.playback_source_dead
    assert replacement.start_calls
    canvas.deleteLater()


def test_playback_health_reports_requested_diagnostics():
    canvas, _controller = _playing_canvas(paused=False)
    health = canvas.playback_health(reason="probe")
    for key in (
        "requested_paused", "clock_generation", "clock_position_ms", "clock_paused",
        "mpv_running", "mpv_pause", "mpv_time_pos", "mpv_core_idle",
        "mpv_eof_reached", "mpv_path", "actor", "external_clock",
        "media_attached", "startup_state",
    ):
        assert key in health, f"playback_health missing {key}"
    assert health["requested_paused"] is False
    assert health["mpv_core_idle"] is False
    canvas.deleteLater()


def test_load_at_saved_cue_preserves_clock_for_initial_media_binding():
    canvas, controller = _playing_canvas(paused=False)
    posted = []
    controller.post_load_at = lambda path, seconds, **kw: posted.append(seconds) or True
    controller.post_set_speed = lambda speed: True

    canvas.load("media.mp4", start_seconds=1.766)

    snapshot = canvas.playback_position_snapshot()
    assert posted == [1.766]
    assert snapshot.presentation_media_ms == pytest.approx(1766)
    assert snapshot.paused
    assert canvas._playback_clock.exact_seek_pending
    assert canvas.visual_position() == pytest.approx(1.766)
    canvas.deleteLater()


def test_dead_pause_click_is_recorded_not_faked():
    canvas, controller = _playing_canvas(paused=False)
    controller.running = False
    canvas._reconcile_position()

    canvas.set_paused(False)

    # The UI must not flip back to Playing against a dead transport.
    assert canvas.playback_position_snapshot().paused is True
    assert canvas._startup_play_requested is True
    canvas.deleteLater()


def test_toggle_playback_routes_revive_when_dead():
    _app()
    from twobyteasr.studio.studio_playback_flow import StudioPlaybackFlowMixin

    revive_calls: list[bool] = []
    sync_calls: list[bool] = []
    status: list[str] = []

    class DeadCanvas(SimpleNamespace):
        controller = FakeActorBackedController(running=False)
        playback_source_dead = True
        at_eof = False

        def playback_position_snapshot(self):
            return SimpleNamespace(paused=True)

        def revive_dead_source(self, *, paused):
            revive_calls.append(bool(paused))
            return True

        def setToolTip(self, text):
            pass

    owner = SimpleNamespace(
        video=DeadCanvas(),
        _sync_play_button=lambda paused: sync_calls.append(bool(paused)),
        save_state=SimpleNamespace(setText=lambda text: status.append(str(text))),
        _show_video_error=lambda message: status.append(str(message)),
    )
    StudioPlaybackFlowMixin._toggle_playback(owner)
    assert revive_calls == [False], "play click on dead source must attempt revive"
    assert sync_calls == [False], "successful revive must show the playing state"
    assert status == ["播放已恢复"], "successful revive must clear the dead status"
