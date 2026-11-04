# Legacy Qt decoder comparison tests; process backend contracts live in test_video_decode_pipe.py.
from __future__ import annotations

from types import SimpleNamespace

from pathlib import Path

from twobyteasr.playback.audio_engine import StudioAudioEngine, _PcmRingDevice, build_audio_decode_command
from twobyteasr.playback.audio_playback_graph import AudioPlaybackGraph, solo_track_ids
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QApplication

from twobyteasr.playback.secondary_video_legacy import SecondaryVideoSource, _DecoderWorker
from twobyteasr.timeline.studio_media_pool import (
    effective_audio_master_track_id,
    set_audio_master_mode,
    set_audio_master_track,
    set_video_track_state,
)
from twobyteasr.projects.studio_project import AudioTrack, AVTrackGroup, StudioMedia, SubtitleProject, VideoTrack


def _layers():
    return [
        {"track_id": "V1", "audio_enabled": True, "track_muted": False},
        {"track_id": "V2", "audio_enabled": True, "track_muted": False},
    ]


def test_audio_graph_selects_exactly_one_output_owner():
    graph = AudioPlaybackGraph(master_track_id="V1")
    first = graph.decide(_layers(), base_track_id="V1")
    assert first.audible_track_id == "V1"
    assert first.mpv_output_enabled is False
    assert first.secondary_track_id == ""

    graph.configure(master_track_id="V2")
    second = graph.decide(_layers(), base_track_id="V1")
    assert second.audible_track_id == "V2"
    assert second.mpv_output_enabled is False
    assert second.secondary_track_id == ""
    assert second.reason == "studio-sink"


def test_audio_graph_mute_and_solo_never_fall_through_to_another_track():
    graph = AudioPlaybackGraph(master_track_id="V1")
    muted = [dict(_layers()[0], track_muted=True), _layers()[1]]
    decision = graph.decide(muted, base_track_id="V1")
    assert decision.has_owner is False
    assert decision.reason == "master-inactive-or-muted"

    graph.configure(master_track_id="V1", solo_track_ids=("V2",))
    decision = graph.decide(_layers(), base_track_id="V1")
    assert decision.has_owner is False
    assert decision.reason == "master-not-soloed"


def test_linked_audio_solo_persists_with_track_state():
    project = SimpleNamespace(
        studio_state={},
        video_tracks=[VideoTrack(id="V1", name="Video 1")],
        audio_tracks=[AudioTrack(id="A1", name="Audio 1")],
        av_track_groups=[
            AVTrackGroup(id="AV1", video_track_id="V1", audio_track_id="A1")
        ],
    )
    set_video_track_state(project, "V1", soloed=True)
    assert project.video_tracks[0].soloed is True
    assert project.audio_tracks[0].soloed is True
    assert solo_track_ids(project) == frozenset({"V1"})


def test_secondary_source_exposes_gui_thread_audio_probe_defaults():
    source = SecondaryVideoSource()
    assert source.audio_output_attached is False
    assert source.video_output_attached is False
    assert source.playback_state == "StoppedState"
    source.close()


def test_secondary_decoder_source_has_no_qaudiooutput_backend():
    source = Path("twobyteasr/playback/secondary_video.py").read_text(encoding="utf-8")
    assert "QAudioOutput" not in source
    assert "setAudioOutput" not in source


def test_single_audio_engine_command_uses_mapped_source_and_tempo():
    command = build_audio_decode_command(
        "ffmpeg.exe", "v2.mp4", source_ms=12_345, rate=1.25,
    )
    assert command[command.index("-ss") + 1] == "12.345000"
    assert command[command.index("-af") + 1] == "atempo=1.250000"
    assert command[-7:] == ["-f", "s16le", "-ac", "2", "-ar", "48000", "pipe:1"]


def test_audio_ring_is_a_sequential_stream_and_sync_requests_are_coalesced(tmp_path):
    app = QApplication.instance() or QApplication([])
    device = _PcmRingDevice()
    assert device.isSequential()
    device.close()

    engine = StudioAudioEngine(ffmpeg_path=tmp_path / "ffmpeg.exe")
    captured = []
    engine._sync_call.disconnect(engine._worker.synchronize)
    engine._sync_call.connect(lambda payload: captured.append(dict(payload)))
    try:
        first = {"source_path": "v2.mp4", "source_ms": 1_000, "playback_rate": 1.0}
        second = {"source_path": "v2.mp4", "source_ms": 1_040, "playback_rate": 1.0}
        engine.synchronize(first, audible=True, paused=False, transport_rate=1.0, volume=0.8)
        engine.synchronize(second, audible=True, paused=False, transport_rate=1.0, volume=0.8)
        assert [item["source_ms"] for item in captured] == [1_000]
        engine._synchronize_complete()
        assert [item["source_ms"] for item in captured] == [1_000, 1_040]
    finally:
        engine.request_shutdown()
        assert engine.wait_for_shutdown(2.0)
        app.processEvents()


def test_follow_active_video_defaults_to_only_visible_track_and_manual_persists():
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=60_000),
        video_tracks=[
            VideoTrack(id="V1", name="Video 1"),
            VideoTrack(id="V2", name="Video 2"),
        ],
    )
    assert effective_audio_master_track_id(project, ("V2",)) == ""
    assert effective_audio_master_track_id(project, ("V1", "V2"), selected_track_id="V2") == ""

    set_audio_master_track(project, "V1")
    set_audio_master_mode(project, "manual")
    assert effective_audio_master_track_id(project, ("V2",), selected_track_id="V2") == "V1"


def test_secondary_decoder_coalesces_frames_until_gui_acknowledges_delivery():
    worker = _DecoderWorker()
    delivered = []
    worker.frame_ready.connect(lambda *payload: delivered.append(payload))

    for index in range(100):
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        image.fill(QColor(index, 0, 0))
        worker._wanted_ms = index
        worker._on_frame(QVideoFrame(image))

    assert len(delivered) == 1
    assert worker._latest_frame is not None
    assert worker._latest_frame[1] == 99

    worker.frame_consumed()
    assert len(delivered) == 2
    assert delivered[-1][1] == 99
    worker.frame_consumed()
    assert worker._frame_delivery_pending is False


def test_repeated_paused_request_does_not_create_a_new_seek_generation():
    source = SecondaryVideoSource()
    source._ensure_thread = lambda: None

    first = source.request_frame(1250, paused=True, seek=True)
    repeated = source.request_frame(1250, paused=True, seek=True)
    moved = source.request_frame(1260, paused=True, seek=True)

    assert first == repeated
    assert moved == first + 1


def test_secondary_release_destroys_media_objects_on_gui_thread():
    app = QApplication.instance() or QApplication([])
    source = SecondaryVideoSource()
    source._ensure_thread()
    worker = source._worker
    convert_thread = source._convert_thread
    assert convert_thread.isRunning()
    worker.path = "fixture.mp4"

    source.release()

    assert source._worker is None
    assert worker.path == ""
    assert worker.player is None
    assert worker.sink is None
    assert not convert_thread.isRunning()
    assert source.shutdown_acknowledged is True
    assert source.thread_stopped is True
    app.processEvents()


def test_secondary_release_is_idempotent_after_thread_shutdown():
    app = QApplication.instance() or QApplication([])
    source = SecondaryVideoSource()
    source._ensure_thread()

    source.release()
    source.release()

    assert source.shutdown_acknowledged is True
    assert source.thread_stopped is True
    app.processEvents()


def test_secondary_shutdown_defers_windows_video_backend_detach():
    class SignalProbe:
        def disconnect(self, _callback):
            return None

    class PlayerProbe:
        playbackStateChanged = SignalProbe()

        def __init__(self):
            self.unloaded = []

        def pause(self):
            self.paused = True

        def stop(self):
            self.unloaded.append("stop")

        def setVideoSink(self, sink):
            self.unloaded.append(("setVideoSink", sink))

        def setSource(self, source):
            self.unloaded.append(("setSource", source))

        def deleteLater(self):
            self.deleted = True

    worker = _DecoderWorker()
    player = PlayerProbe()
    worker.player = player
    worker.shutdown()

    assert player.deleted is True
    assert getattr(player, "paused", False) is True
    # 2026-09-07（打包关停滞留）：frozen 的 ffmpeg 媒体后端在带会话析构时
    # 死等解码线程——shutdown 必须先主动卸载媒体会话再延迟删除。
    assert "stop" in player.unloaded
    assert ("setVideoSink", None) in player.unloaded
    assert any(
        isinstance(entry, tuple) and entry[0] == "setSource" and bool(entry[1].isEmpty())
        for entry in player.unloaded
    )
    assert worker._shutdown_final_status == "DeferredDelete"


def test_secondary_shutdown_parks_media_objects_for_app_exit():
    from twobyteasr.playback import secondary_video_legacy as secondary_video

    class SignalProbe:
        def disconnect(self, _callback):
            return None

    class ParkProbe:
        playbackStateChanged = SignalProbe()

        def pause(self):
            self.paused = True

        def stop(self):
            raise AssertionError("parked players must not touch the media session")

        def setVideoSink(self, _sink):
            raise AssertionError("parked players must not touch the media session")

        def setSource(self, _source):
            raise AssertionError("parked players must not touch the media session")

        def deleteLater(self):
            raise AssertionError("parked players must not be deleted")

    worker = _DecoderWorker()
    player = ParkProbe()
    worker.player = player
    secondary_video.set_defer_media_destruction(True)
    parked_before = len(secondary_video._PARKED_MEDIA_OBJECTS)
    try:
        worker.shutdown()
    finally:
        secondary_video.set_defer_media_destruction(False)
    assert worker._shutdown_final_status == "ParkedForProcessExit"
    assert len(secondary_video._PARKED_MEDIA_OBJECTS) == parked_before + 1
    assert secondary_video._PARKED_MEDIA_OBJECTS[-1][1] is player
