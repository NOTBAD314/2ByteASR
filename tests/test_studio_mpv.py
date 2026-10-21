import json
import threading
from collections import deque
from pathlib import Path

import pytest

from twobyteasr.playback.studio_mpv import (
    _MpvCommandActor,
    ADVANCED_OVERLAY_ID,
    TRANSFORM_OVERLAY_ID,
    MpvCommandError,
    MpvController,
    MpvUnavailableError,
    find_mpv_executable,
    mpv_startup_arguments,
)


class _RunningProcess:
    def poll(self):
        return None


class _Pipe:
    def __init__(self):
        self.responses = iter(
            (
                b'{"event":"property-change"}\n',
                b'{"request_id":1,"error":"success","data":12.5}\n',
            )
        )
        self.written = b""

    def write(self, value):
        self.written += value

    def close(self):
        pass

    def readline(self):
        try:
            return next(self.responses)
        except StopIteration:
            raise BrokenPipeError("pipe closed")


def _decode_last_frame(written):
    return json.loads(written.decode("utf-8").strip().splitlines()[-1])


class _RecordingActor:
    def __init__(self):
        self.posts = []
        self.foreground = []
        self.deferred = []
        self.seeks = []
        self.values = {"pause": True, "time-pos": 12.5}

    def post(
        self, callback, *, coalesce_key="", foreground=False, deferred=False, on_discard=None,
    ):
        self.posts.append((callback, coalesce_key))
        self.foreground.append(bool(foreground))
        self.deferred.append(bool(deferred))
        return True

    def property(self, name, default=None):
        return self.values.get(name, default)

    def properties(self):
        return dict(self.values)

    def begin_seek(self, generation, target):
        self.seeks.append((int(generation), float(target)))


def test_find_mpv_prefers_explicit_override(tmp_path):
    explicit = tmp_path / "custom" / "mpv.exe"
    bundled = tmp_path / "project" / "tools" / "mpv" / "mpv.exe"
    explicit.parent.mkdir(parents=True)
    bundled.parent.mkdir(parents=True)
    explicit.write_bytes(b"explicit")
    bundled.write_bytes(b"bundled")

    found = find_mpv_executable(
        tmp_path / "project", {"TWOBYTEASR_MPV": str(explicit)}
    )

    assert found == explicit.resolve()


def test_find_mpv_uses_bundled_tool(tmp_path):
    bundled = tmp_path / "tools" / "mpv" / "mpv.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"mpv")

    assert find_mpv_executable(tmp_path, {}) == bundled.resolve()


def test_mpv_arguments_use_native_hwnd_gpu_decode_and_isolated_config(tmp_path):
    args = mpv_startup_arguments(
        tmp_path / "mpv.exe",
        12345,
        r"\\.\pipe\studio-test",
        log_path=str(tmp_path / "mpv.log"),
    )

    assert "--wid=12345" in args
    assert "--hwdec=auto-safe" in args
    assert "--vo=gpu-next" in args
    assert "--gpu-api=d3d11" in args
    assert "--no-config" in args
    assert "--sub-ass-override=no" in args
    assert "--sid=no" in args
    assert "--sub-auto=no" in args
    assert any(item.startswith("--input-ipc-server=") for item in args)


def test_mpv_arguments_reject_non_native_window_id(tmp_path):
    with pytest.raises(ValueError, match="positive native HWND"):
        mpv_startup_arguments(tmp_path / "mpv.exe", 0, "pipe")


def test_ipc_skips_event_before_matching_command_response(tmp_path, monkeypatch):
    monkeypatch.setattr(_MpvCommandActor,'_heartbeat',lambda self:None)
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    controller = MpvController(executable)
    controller._process = _RunningProcess()
    actor = _MpvCommandActor(controller)
    controller._actor = actor
    actor._pipe = _Pipe()

    try:
        assert controller.get_property("time-pos") == 12.5
        assert _decode_last_frame(actor._pipe.written)["command"] == [
            "get_property", "time-pos"
        ]
    finally:
        actor.close()


def test_subtitle_load_does_not_remove_missing_track(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    subtitle = tmp_path / "subtitle.ass"
    subtitle.write_text("[Script Info]", encoding="utf-8")
    controller = MpvController(executable)
    commands = []

    def send(command, timeout=2.0):
        commands.append(command)
        return {"data": "no"} if command == ["get_property", "sid"] else {}

    controller._send = send
    controller._subtitle_media_ready = True  # fixture has completed file-loaded
    controller.set_subtitle_file(subtitle)
    assert commands == [
        ["get_property", "track-list"],
        ["sub-add", str(subtitle.resolve()), "select"],
        ["get_property", "sid"],
    ]


def test_subtitle_reload_removes_previous_studio_track(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    subtitle = tmp_path / "subtitle.ass"
    subtitle.write_text("[Script Info]", encoding="utf-8")
    controller = MpvController(executable)
    controller._studio_subtitle_sid = 3
    commands = []

    def send(command, timeout=2.0):
        commands.append(command)
        if command == ['get_property','track-list']:
            return {'data':[{'type':'sub','id':3,'external':True}]}
        return {"data": 3} if command == ["get_property", "sid"] else {}

    controller._send = send
    controller._subtitle_media_ready = True  # fixture has completed file-loaded
    controller.set_subtitle_file(subtitle)
    assert commands == [
        ["get_property", "track-list"],
        ["sub-remove", 3],
        ["sub-add", str(subtitle.resolve()), "select"],
        ["get_property", "sid"],
    ]


def test_subtitle_load_treats_temporarily_unavailable_sid_as_empty(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    subtitle = tmp_path / "subtitle.ass"
    subtitle.write_text("[Script Info]", encoding="utf-8")
    controller = MpvController(executable)
    commands = []

    def send(command, timeout=2.0):
        commands.append(command)
        if command == ["get_property", "sid"]:
            raise RuntimeError("mpv command failed: property unavailable")
        return {}

    controller._send = send
    controller._subtitle_media_ready = True  # fixture has completed file-loaded
    controller.set_subtitle_file(subtitle)
    assert commands == [
        ["get_property", "track-list"],
        ["sub-add", str(subtitle.resolve()), "select"],
        ["get_property", "sid"],
    ]


def test_subtitle_load_removes_all_external_tracks_and_selects_authoritative_ass(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    subtitle = tmp_path / "studio.ass"
    subtitle.write_text("[Script Info]", encoding="utf-8")
    controller = MpvController(executable)
    commands = []

    def send(command, timeout=2.0):
        commands.append(command)
        if command == ["get_property", "track-list"]:
            return {"data": [
                {"id": 1, "type": "sub", "external": True, "external-filename": "master.srt"},
                {"id": 2, "type": "sub", "external": False},
                {"id": 3, "type": "video", "external": False},
            ]}
        if command == ["get_property", "sid"]:
            return {"data": 4}
        return {}

    controller._send = send
    controller._subtitle_media_ready = True  # fixture has completed file-loaded
    controller.set_subtitle_file(subtitle)
    assert ["sub-remove", 1] in commands
    assert ["sub-remove", 2] not in commands
    assert controller._studio_subtitle_sid == 4
    assert controller._studio_subtitle_path == str(subtitle.resolve())


def test_playback_speed_supports_premiere_style_eight_x_limit(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    controller = MpvController(executable)
    commands = []
    controller._send = lambda command, timeout=2.0: commands.append(command) or {}

    controller.set_speed(8.0)
    controller.set_speed(12.0)

    assert commands == [
        ["set_property", "speed", 8.0],
        ["set_property", "speed", 8.0],
    ]


def test_clear_media_uses_single_stop_ipc_and_keeps_controller_reusable(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    controller = MpvController(executable)
    controller._studio_subtitle_sid = 7
    controller._studio_subtitle_path = "old.ass"
    commands = []
    controller._send = lambda command, timeout=2.0: commands.append(command) or {}

    controller.clear_media()

    assert commands == [["stop"]]
    assert controller._studio_subtitle_sid is None
    assert controller._studio_subtitle_path == ""


def test_interactive_posts_are_latest_wins_actor_messages(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    controller = MpvController(executable)
    controller._process = _RunningProcess()
    actor = _RecordingActor()
    controller._actor = actor

    assert controller.post_seek(7.5)
    assert controller.post_seek(8.0)
    assert controller.post_set_paused(True)
    assert controller.post_set_speed(3.0)
    assert [key for _callback, key in actor.posts] == ["seek", "seek", "pause", "speed"]
    assert controller.observed_property("time-pos") == 12.5
    assert controller.observed_properties()["pause"] is True


def test_command_rejection_does_not_reconnect_valid_actor_pipe():
    actor = object.__new__(_MpvCommandActor)
    actor.controller = type("Controller", (), {"running": True})()
    actor._thread = threading.current_thread()
    actor._stopping = False
    actor._degraded = False
    actor._last_error = ""
    actor._reconnect_attempts = 0
    actor._pipe = object()
    actor._open_pipe = lambda _timeout: None
    dropped = []
    actor._drop_pipe = lambda: dropped.append(True)
    actor._exchange_on_pipe = lambda _values, timeout: (_ for _ in ()).throw(
        MpvCommandError(["seek", 1.0], "error running command")
    )

    with pytest.raises(MpvCommandError, match="error running command"):
        actor.exchange(["seek", 1.0], timeout=0.1)

    assert dropped == []
    assert actor._reconnect_attempts == 0
    assert actor._degraded is False


def test_desired_state_restore_never_replays_position_commands(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    controller = MpvController(executable)
    controller._desired_commands = {
        "seek": ["seek", 1.0, "absolute+exact"],
        "loadfile": ["loadfile", "a.mp4", "replace"],
        "speed": ["set_property", "speed", 2.0],
    }
    commands = []

    class Actor:
        def _exchange_on_pipe(self, command, *, timeout):
            commands.append((list(command), timeout))
            return {"error": "success"}

    controller._restore_desired_state(Actor())

    # An IPC reconnect must never yank playback back to a remembered seek or
    # reload the media: mpv kept its state, only transport properties replay.
    assert commands == [
        (["set_property", "speed", 2.0], 0.75),
    ]


def test_media_switch_posts_loadfile_as_foreground_actor_work(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    media = tmp_path / "b-roll.mp4"
    media.write_bytes(b"video")
    controller = MpvController(executable)
    controller._process = _RunningProcess()
    actor = _RecordingActor()
    controller._actor = actor

    assert controller.post_load(media)

    assert [key for _callback, key in actor.posts] == ["loadfile"]
    assert actor.foreground == [True]


def test_media_switch_at_loads_with_start_and_matching_actor_generation(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    media = tmp_path / "b-roll.mp4"
    media.write_bytes(b"video")
    controller = MpvController(executable)
    controller._process = _RunningProcess()
    actor = _RecordingActor()
    controller._actor = actor
    commands = []
    controller._send = lambda command, timeout=2.0: commands.append(command) or {
        "error": "success"
    }

    assert controller.post_load_at(media, 10.017, generation=7)
    callback, key = actor.posts[0]
    callback()

    assert key == "loadfile"
    assert actor.foreground == [True]
    assert actor.seeks == [(7, 10.017)]
    assert commands == [[
        "loadfile",
        str(media.resolve()),
        "replace",
        -1,
        {"start": "10.017000"},
    ]]
    assert controller.applied_seek_state()["generation"] == 7
    assert controller.applied_seek_state()["command"] == "loadfile-start"


def test_subtitle_visibility_is_latest_wins_actor_state(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    controller = MpvController(executable)
    controller._process = _RunningProcess()
    actor = _RecordingActor()
    controller._actor = actor

    assert controller.post_set_subtitle_visible(False)
    assert controller.post_set_subtitle_visible(True)

    assert [key for _callback, key in actor.posts] == [
        "subtitle-visibility", "subtitle-visibility",
    ]
    assert controller._desired_commands["subtitle-visibility"] == [
        "set_property", "sub-visibility", True,
    ]
    assert controller._subtitle_visible is True
    assert "sub-visibility" in _MpvCommandActor.OBSERVED_PROPERTIES


def test_applied_visual_sequence_suppresses_native_before_advanced_overlay(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    overlay = tmp_path / "advanced.bgra"
    overlay.write_bytes(b"\x00" * 16)
    controller = MpvController(executable)
    commands = []
    controller._send = lambda command, timeout=2.0: commands.append(command) or {
        "error": "success"
    }

    controller.set_subtitle_visible(False)
    controller.set_raw_overlay(
        0,
        overlay,
        x=0,
        y=0,
        width=2,
        height=2,
        stride=8,
    )

    applied = controller.applied_visual_state()
    assert applied["subtitle"]["visible"] is False
    assert applied["overlays"][0]["visible"] is True
    assert applied["subtitle"]["sequence"] < applied["overlays"][0]["sequence"]
    assert commands[0] == ["set_property", "sub-visibility", False]
    assert commands[1][0:2] == ["overlay-add", 0]


def test_transform_chrome_posts_are_deferred_behind_foreground(tmp_path):
    executable = tmp_path / "mpv.exe"
    executable.write_bytes(b"mpv")
    overlay = tmp_path / "overlay.bgra"
    overlay.write_bytes(b"\x00" * 16)
    controller = MpvController(executable)
    controller._process = _RunningProcess()
    actor = _RecordingActor()
    controller._actor = actor

    assert controller.post_raw_overlay(
        TRANSFORM_OVERLAY_ID, overlay, x=0, y=0, width=2, height=2, stride=8,
    )
    assert controller.post_set_subtitle_visible(False)
    assert controller.post_raw_overlay(
        ADVANCED_OVERLAY_ID, overlay, x=0, y=0, width=2, height=2, stride=8,
    )

    assert [key for _callback, key in actor.posts] == [
        f"overlay:{TRANSFORM_OVERLAY_ID}", "subtitle-visibility", f"overlay:{ADVANCED_OVERLAY_ID}",
    ]
    assert actor.deferred == [True, False, False]
    assert actor.foreground == [False, True, True]


def test_actor_keeps_foreground_fifo_ahead_of_deferred_chrome():
    actor = object.__new__(_MpvCommandActor)
    actor._condition = threading.Condition()
    actor._requests = deque()
    actor._stopping = False

    actor.post(lambda: "seek", coalesce_key="seek")
    actor.post(lambda: "transform", coalesce_key="overlay:1", deferred=True)
    actor.post(
        lambda: "native-off",
        coalesce_key="subtitle-visibility",
        foreground=True,
    )
    actor.post(lambda: "advanced", coalesce_key="overlay:0", foreground=True)

    assert [request.callback() for request in actor._requests] == [
        "native-off", "advanced", "seek", "transform",
    ]
