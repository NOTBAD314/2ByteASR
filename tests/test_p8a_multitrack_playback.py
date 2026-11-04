"""P8A true multi-track: one project clock, dynamic base, overlay decoder."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.timeline.clip_time_mapper import map_project_time
from twobyteasr.timeline.studio_media_pool import (
    add_media_asset,
    add_video_clip,
    create_video_track,
    set_video_track_state,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_ui import MpvCanvas, SubtitleStudioPage, WaveformTimeline
from twobyteasr.playback.video_compositor import VideoCompositionScene


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _project(tmp_path: Path) -> SubtitleProject:
    v1 = tmp_path / "v1.mp4"
    v2 = tmp_path / "v2.mp4"
    v1.write_bytes(b"v1")
    v2.write_bytes(b"v2")
    project = SubtitleProject(
        media=StudioMedia(path=str(v1), duration_ms=175_000, width=1920, height=1080),
        cues=[StudioCue("c1", 0, 1_000, "cue")],
    )
    project.validate()
    project.video_tracks[0].locked = False
    asset = add_media_asset(project, v2, fingerprint="v2", duration_ms=180_000)
    track = create_video_track(project)
    add_video_clip(project, track.id, asset.asset_id, timeline_in_ms=9_000)
    project.validate()
    return project


def test_hide_v1_makes_v2_the_base_layer(tmp_path):
    _app()
    project = _project(tmp_path)
    page = SubtitleStudioPage()
    page.project = project
    both = page._multitrack_preview_layers(10_000)
    assert [layer["track_id"] for layer in both] == ["V1", "V2"]
    assert both[0]["source_ms"] == 10_000
    assert both[1]["source_ms"] == 1_000
    set_video_track_state(project, "V1", enabled=False)
    only_v2 = page._multitrack_preview_layers(10_000)
    assert [layer["track_id"] for layer in only_v2] == ["V2"]
    target = page._multitrack_preview_target(10_000)
    assert target is not None
    assert target["track_id"] == "V2"
    assert target["source_ms"] == 1_000
    page.close_page()
    page.deleteLater()


def test_compositor_does_not_require_v1_and_skips_base_layer(tmp_path):
    _app()
    scene = VideoCompositionScene()
    v1 = tmp_path / "v1.mp4"
    v2 = tmp_path / "v2.mp4"
    v1.write_bytes(b"v1")
    v2.write_bytes(b"v2")
    layers = [
        {
            "track_id": "V2",
            "clip_id": "clip-v2",
            "source_path": str(v2),
            "source_ms": 1_000,
            "transform": {},
        }
    ]
    scene.set_composition(
        layers,
        paused=True,
        rate=1.0,
        audio_master_track_id="V1",
        base_track_id="V2",
        volume=0.0,
        project_ms=10_000,
        mpv_path=str(v2),
    )
    assert scene._layers == []
    assert not scene.isVisible()
    scene.set_composition(
        layers,
        paused=True,
        rate=1.0,
        audio_master_track_id="V1",
        base_track_id="V2",
        volume=0.0,
        project_ms=10_000,
        mpv_path=str(v1),
    )
    assert scene._layers
    assert scene._layers[0]["track_id"] == "V2"
    assert scene.isVisible()
    scene.close()
    scene.deleteLater()


def test_compositor_suspends_decoder_between_overlap_ranges_and_releases_on_clear(tmp_path):
    _app()
    scene = VideoCompositionScene()
    source = tmp_path / "v2.mp4"
    source.write_bytes(b"v2")

    class Runtime:
        def __init__(self):
            self.suspended = 0
            self.released = 0

        def suspend(self):
            self.suspended += 1

        def release(self):
            self.released += 1

        class FrameSignal:
            @staticmethod
            def disconnect(_callback):
                return None

        frame_updated = FrameSignal()

    runtime = Runtime()
    scene._players["clip-v2"] = runtime
    scene._layers = [{"clip_id": "clip-v2"}]
    scene.set_composition(
        [{
            "track_id": "V2",
            "clip_id": "clip-v2",
            "source_path": str(source),
            "source_ms": 1_000,
        }],
        paused=True,
        rate=1.0,
        audio_master_track_id="V1",
        base_track_id="V2",
        volume=0.0,
        project_ms=10_000,
        mpv_path=str(source),
    )
    assert runtime.suspended == 1
    assert runtime.released == 0
    assert scene._players["clip-v2"] is runtime

    scene.clear()
    assert runtime.released == 1
    assert not scene._players
    scene.deleteLater()


def test_secondary_overlay_receives_mapped_source_not_project_time(tmp_path):
    _app()
    project = _project(tmp_path)
    page = SubtitleStudioPage()
    page.project = project
    layers = page._multitrack_preview_layers(10_000)
    v2 = next(layer for layer in layers if layer["track_id"] == "V2")
    mapped = map_project_time(
        {
            "timeline_in_ms": v2["timeline_in_ms"],
            "timeline_out_ms": v2["timeline_out_ms"],
            "source_in_ms": v2["source_in_ms"],
            "source_out_ms": v2["source_out_ms"],
            "playback_rate": v2["playback_rate"],
        },
        10_000,
    )
    assert v2["source_ms"] == mapped.source_ms == 1_000
    page.close_page()
    page.deleteLater()


def test_empty_v2_does_not_replace_v1_preview(tmp_path):
    _app()
    project = _project(tmp_path)
    project.video_tracks[1].clips.clear()
    page = SubtitleStudioPage()
    page.project = project
    layers = page._multitrack_preview_layers(1_000)
    assert [layer["track_id"] for layer in layers] == ["V1"]
    assert page._multitrack_preview_target(1_000)["track_id"] == "V1"
    page.close_page()
    page.deleteLater()


def test_project_position_is_not_mapped_twice_for_secondary_base():
    _app()
    page = SubtitleStudioPage()
    page._playback_mode = "multitrack"
    page._active_video_preview_timeline_in_ms = 7_000
    page._active_video_preview_source_in_ms = 0
    applied: list[int] = []
    page._apply_project_playhead = lambda milliseconds, **_kwargs: applied.append(milliseconds)
    page._position_changed(10.0)
    assert applied == [10_000]
    page.close_page()
    page.deleteLater()


def test_dynamic_base_switch_loads_at_mapped_time_without_followup_seek(tmp_path):
    _app()
    project = _project(tmp_path)
    set_video_track_state(project, "V1", enabled=False)
    page = SubtitleStudioPage()
    page.project = project

    class Controller:
        running = True

        def __init__(self):
            self.load_at = []
            self.seeks = []
            self.paused = []
            self.speeds = []

        def post_load_at(self, path, seconds, *, generation):
            self.load_at.append((str(Path(path).resolve()), seconds, generation))
            return True

        def post_seek(self, seconds, **kwargs):
            self.seeks.append((seconds, kwargs))
            return True

        def post_set_paused(self, paused):
            self.paused.append(bool(paused))
            return True

        def set_speed(self, value):
            # 8x 修复后换绑必压速度回传输层；假控制器补齐该方法（此前单跑
            # 必炸 AttributeError，只有被同进程其它测试污染后才偶然通过）。
            self.speeds.append(float(value))

    controller = Controller()
    page.video.controller = controller
    page.video._media_path = project.media.path
    page.video._paused = True
    page._sync_video_compositor = lambda _milliseconds: None
    page._apply_active_video_track_volume = lambda _track_id: None

    page._sync_multitrack_preview_at(10_000)

    v2_path = next(
        item.canonical_source
        for item in project.media_pool
        if Path(item.canonical_source).name == "v2.mp4"
    )
    assert controller.load_at == [(str(Path(v2_path).resolve()), 1.0, 1)]
    assert controller.seeks == []
    assert controller.paused == [True]
    page.close_page()
    page.deleteLater()


def test_secondary_source_observation_maps_to_project_once():
    _app()
    canvas = MpvCanvas()
    canvas.set_project_time_mapping(
        enabled=True,
        timeline_in_ms=7_000,
        source_in_ms=0,
        playback_rate=1.0,
    )
    assert canvas._source_position_to_project_ms(3.0) == 10_000
    assert canvas._source_position_to_project_ms(10.0) == 17_000
    canvas.set_project_time_mapping(enabled=False)
    assert canvas._source_position_to_project_ms(10.0) == 10_000
    canvas.deleteLater()


def test_long_video_clip_trim_handle_is_fixed_logical_pixels():
    assert WaveformTimeline.VIDEO_CLIP_TRIM_HANDLE_PX == 10.0
    assert WaveformTimeline.VIDEO_CLIP_TRIM_HANDLE_PX <= 12.0
