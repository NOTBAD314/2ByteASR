"""Focused P9A-R4 contracts for packaged-runtime diagnostics."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.providers.ai_providers import ProviderStatus
from twobyteasr.diagnostics.build_identity import runtime_fingerprint_payload
from twobyteasr.playback.playback_clock import PlaybackPositionSnapshot
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_ui import AdvancedLiveCanvas, MpvCanvas, SubtitleStudioPage
from twobyteasr.caption_design.visual_design_graph import (
    comic_burst_graph,
    compile_live_scene,
    glitch_graph,
    streamer_gaming_graph,
)
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _app():
    return QApplication.instance() or QApplication([])


def test_packaged_runtime_fingerprint_reports_p9a_symbols():
    payload = runtime_fingerprint_payload()
    features = payload["features"]
    assert payload["source_hash"]
    assert features["P9A_R3_MOTION_NORMALIZER_PRESENT"] is True
    assert features["P9A_R3_EPOCH_SYNC_PRESENT"] is True
    assert features["P9A_R3_TWO_PHASE_ANTIGRAVITY_PRESENT"] is True
    assert features["P9A_R4_CUE_MOTION_PHASE_PRESENT"] is True


def test_transparent_compositor_frame_retains_overlay_until_after_cue(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    class Controller:
        running = True

        def post_raw_overlay(self, *_args, **_kwargs):
            return True

        def post_remove_overlay(self, *_args, **_kwargs):
            return True

    canvas = MpvCanvas()
    canvas.controller = Controller()
    canvas._media_attached = True  # explicit live-media precondition
    opaque = QImage(8, 8, QImage.Format.Format_ARGB32)
    opaque.fill(QColor("#FFFF0000"))
    transparent = QImage(8, 8, QImage.Format.Format_ARGB32)
    transparent.fill(QtGlobalTransparent)

    assert canvas.publish_compositor_overlay(
        9, opaque, QRect(0, 0, 8, 8), source_bounds=QRect(0, 0, 8, 8)
    )
    assert canvas.active_compositor_overlay_ids() == [9]
    assert not canvas.publish_compositor_overlay(9, transparent, QRect(0, 0, 8, 8), phase="HOLD")
    assert canvas.active_compositor_overlay_ids() == [9]
    assert not canvas.publish_compositor_overlay(9, transparent, QRect(0, 0, 8, 8), phase="AFTER_CUE")
    assert canvas.active_compositor_overlay_ids() == []
    canvas.deleteLater()


QtGlobalTransparent = 0


def test_advanced_frame_trace_contains_project_media_and_thread_fields(tmp_path):
    _app()
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "clip.mp4"), duration_ms=1_000),
        cues=[StudioCue("cue", 0, 1_000, "测试")],
    )
    project.validate()
    snapshot = build_visual_cue_snapshot(project, "cue", width=100, height=50, fps=30.0)
    scene = compile_live_scene(comic_burst_graph(), cue_duration_ms=1_000)
    records = []

    class Owner(QWidget):
        ADVANCED_OVERLAY_ID = 9
        project_path = Path("fixture-project.2byteproj")
        _studio_session_id = "session-r4"

        def _studio_trace(self, event, **fields):
            records.append((event, fields))

        def active_compositor_overlay_ids(self):
            return [9]

    owner = Owner()
    owner.project = project
    canvas = AdvancedLiveCanvas(owner)
    canvas._snapshot = snapshot
    canvas._compiled_scene = scene
    frame = QImage(100, 50, QImage.Format.Format_ARGB32)
    frame.fill(QColor("#00FFFFFF"))
    canvas._trace_frame_sample(
        absolute_ms=500,
        relative_ms=500,
        sample=scene.sample(500),
        frame_image=frame,
    )
    event, fields = records[-1]
    assert event == "ADVANCED_FRAME_TRACE"
    assert fields["project_id"].endswith("fixture-project.2byteproj")
    assert fields["studio_session_id"] == "session-r4"
    assert fields["media_id"].endswith("clip.mp4")
    assert fields["thread"] == threading.current_thread().name
    assert fields["overlay_present"] is True
    canvas.deleteLater()
    owner.deleteLater()


def test_legacy_project_probe_runs_after_open_on_worker_thread(tmp_path, monkeypatch):
    _app()
    media = tmp_path / "legacy.flv"
    media.write_bytes(b"fixture")
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=1_000),
        cues=[StudioCue("cue", 0, 1_000, "测试")],
    )
    page = SubtitleStudioPage()
    page.project = project
    project_path = tmp_path / "legacy.2byteproj"
    page.project_path = project_path
    seen = []

    def fake_probe(path):
        seen.append(threading.current_thread().name)
        return {
            "source_path": str(path), "duration_ms": 1_000,
            "has_video": True, "has_audio": True,
            "video_codec": "flv1", "audio_codec": "aac",
            "width": 640, "height": 360, "fps": 25.0,
            "video_timebase": "1/1000", "audio_timebase": "1/48000",
            "sample_rate": 48_000, "channels": 2,
            "audio_stream_index": 1, "fingerprint": "legacy-r4",
        }

    monkeypatch.setattr("twobyteasr.studio.studio_media_flow.probe_media_identity", fake_probe)
    page._schedule_project_media_probe(project, str(project_path))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and (not project.media_pool or not project.media_pool[0].audio_metadata.get("sample_rate")):
        _app().processEvents()
        time.sleep(0.01)
    assert seen and seen[0] != "MainThread"
    assert project.media_pool[0].audio_metadata["sample_rate"] == 48_000
    assert project.media_pool[0].audio_metadata["stream_index"] == 1
    page.close_page()
    page.deleteLater()


def test_antigravity_readiness_timeout_still_invokes_real_generation(tmp_path, monkeypatch):
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.caption_design.art_direction import fallback_art_directions

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    directions = (
        fallback_art_directions("美漫爆裂")[0],
        fallback_art_directions("赛博故障")[0],
        fallback_art_directions("游戏直播")[1],
    )
    calls = []

    class Provider:
        provider_id = "fixture-agy"
        transport = "antigravity_cli"
        model = "gemini-fixture"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def validate(**_kwargs):
            return ProviderStatus(True, False, "readiness request timeout")

        @staticmethod
        def structured_complete(messages, schema, **kwargs):
            calls.append((schema, kwargs.get("timeout")))
            user = __import__("json").loads(messages[1]["content"])
            if "art_directions" in (schema.get("properties") or {}):
                return {
                    "design_intent": "fixture",
                    "visual_changes": ["a", "b", "c"],
                    "motion_reason": "layered",
                    "art_directions": [item.to_dict() for item in directions],
                }
            graphs = (comic_burst_graph(), glitch_graph(), streamer_gaming_graph())
            return {"variant": graphs["ABC".index(user.get("variant_slot", "A"))].to_dict()}

    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: Provider())
    monkeypatch.setattr(
        studio_ai.GLOBAL_PROVIDER_REGISTRY,
        "selection",
        lambda *_a, **_k: SimpleNamespace(
            provider="fixture", service="fixture", model="gemini-fixture",
            credential_ready=True,
        ),
    )
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist",
        lambda **_kwargs: {"chinese_sans": ["Source Han Sans CN"]},
    )
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=4_000),
        cues=[StudioCue("cue", 0, 4_000, "测试")],
    )
    suggestion = studio_ai.request_style_design(
        project, "cue", "三套方向", {"models": {"ai_design_timeout_seconds": 5}},
    )
    assert suggestion.provider_succeeded
    assert len(calls) == 4
    assert suggestion.provider_error_category == ""
    trace_path = Path(suggestion.raw_response["_studio_telemetry"]["trace_path"])
    trace = __import__("json").loads(trace_path.read_text(encoding="utf-8"))
    assert trace["provider"]["effective_timeout_seconds"] == 300.0
