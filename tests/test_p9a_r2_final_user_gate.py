from __future__ import annotations

import copy
import os
import time
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_p8b_stroke_contract import _snapshot
from twobyteasr.providers import llm_config
from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot
from twobyteasr.playback.audio_engine import StudioAudioEngine
from twobyteasr.providers.provider_registry import ProviderRegistry
from twobyteasr.projects.studio_session import StudioSession
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.caption_style.style_recipe import normalize_shadow_contract
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_dpapi_precedes_environment_and_current_input(monkeypatch):
    provider = "deepseek"
    base_url = "https://api.deepseek.com"
    scoped = llm_config._provider_key_id(provider, base_url)
    monkeypatch.setattr(
        llm_config,
        "_read_secrets",
        lambda: {"schema": 2, scoped: "dpapi-key"},
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "environment-key")
    settings = {"models": {}, "switches": {}}
    llm_config.activate_ai_service(settings, "deepseek", stage="polish")
    settings["models"]["polish_api_key"] = "current-input-key"

    endpoint = llm_config.endpoint_from_settings(settings, "polish")

    assert endpoint["provider"] == "deepseek"
    assert endpoint["api_key"] == "dpapi-key"
    assert endpoint["key_source"].startswith("Windows DPAPI")


def test_home_and_studio_registry_share_one_live_selection():
    settings = {"models": {}, "switches": {}}
    registry = ProviderRegistry()
    registry.bind(settings)
    registry.activate("deepseek", model="deepseek-chat")

    home_client = registry.client(stage="polish")
    studio_client = registry.client(stage="polish", settings=settings)

    assert registry.settings() is settings
    assert registry.selection().service == "deepseek"
    assert registry.selection().model == "deepseek-chat"
    assert home_client._service is studio_client._service
    assert home_client._settings["models"]["ai_service"] == "deepseek"
    assert studio_client._settings["models"]["ai_service"] == "deepseek"


def test_audio_project_generation_fence_survives_twenty_cycles(app):
    engine = StudioAudioEngine()
    thread_identity = id(engine._thread)
    session = StudioSession()
    clock_generations = []
    try:
        for index in range(20):
            session.project_path = None
            assert session.close(f"cycle-{index}") == index + 1
            clock_generations.append(engine.unload())
        QTest.qWait(100)
        app.processEvents()

        telemetry = engine.telemetry_snapshot()
        assert clock_generations == list(range(1, 21))
        assert telemetry["session_generation"] == 20
        assert telemetry["state"] == "SILENT"
        assert telemetry["engine_thread_count"] == 1
        assert id(engine._thread) == thread_identity

        engine._capture_telemetry({
            "session_generation": 19,
            "state": "PLAYING",
            "source_path": "old-project.wav",
        })
        assert engine.telemetry_snapshot()["state"] == "SILENT"
        assert engine.telemetry_snapshot().get("source_path", "") == ""
    finally:
        assert engine.wait_for_shutdown(timeout=2.0)


def test_worker_silent_telemetry_drops_closed_project_source(app):
    """The worker's SILENT emit must not resurrect the closed project identity.

    Regression for the packaged audit finding: engine.unload() clears the
    GUI-side telemetry, but the queued worker SILENT emit used to carry the
    old ``_source_path`` at the same session generation and overwrote it.
    """
    engine = StudioAudioEngine(ffmpeg_path=Path("missing-ffmpeg.exe"), isolated=False)
    try:
        worker = engine._worker
        worker._source_path = "old-project.wav"
        worker._source_start_ms = 42_000
        worker._effective_rate = 1.5
        worker._drift_ms = 25.0
        worker._active = True
        worker._paused = False

        generation = engine.unload()
        deadline = time.perf_counter() + 3.0
        while time.perf_counter() < deadline:
            app.processEvents()
            telemetry = engine.telemetry_snapshot()
            if telemetry.get("state") == "SILENT" and telemetry.get("clock_sequence"):
                break
            QTest.qWait(20)

        telemetry = engine.telemetry_snapshot()
        assert telemetry["state"] == "SILENT"
        assert telemetry["session_generation"] == generation
        assert telemetry.get("source_path", "") == ""
        assert int(telemetry.get("source_start_ms") or 0) == 0
        assert float(telemetry.get("effective_rate") or 0.0) == 1.0
        assert worker._source_path == ""
        assert worker._active is False
        assert worker._paused is True
    finally:
        assert engine.wait_for_shutdown(timeout=2.0)


def test_real_studio_page_reuses_one_engine_across_a_b_a_cycles(app):
    page = SubtitleStudioPage()
    video_identity = id(page.video)
    engine_identity = id(page.audio_engine)
    thread_identity = id(page.audio_engine._thread)
    clock_identities = []
    try:
        for index in range(20):
            name = "A" if index % 2 == 0 else "B"
            page.project = SubtitleProject(
                media=StudioMedia(path="", display_name=name, duration_ms=1_000)
            )
            page.project_path = Path(f"{name}.2byteproj")
            clock_identities.append(id(page.video._playback_clock))
            page._close_project_session(f"route-{name}-{index}")
            app.processEvents()

            assert page.project is None
            assert page.project_path is None
            assert page.video._media_path == ""
            assert page.audio_engine.telemetry_snapshot()["session_generation"] == index + 1
            assert id(page.video) == video_identity
            assert id(page.audio_engine) == engine_identity
            assert id(page.audio_engine._thread) == thread_identity
        assert len(set(clock_identities)) >= 2
        assert page.audio_engine.telemetry_snapshot()["engine_thread_count"] == 1
    finally:
        page.close_page()


def test_shadow_inspector_preserves_polar_distance_and_materializes_live_graph(app):
    page = SubtitleStudioPage()
    cue = StudioCue("shadow", 0, 2_000, "SHADOW TEST")
    try:
        page.project = SubtitleProject(
            media=StudioMedia(path="", duration_ms=2_000), cues=[cue],
        )
        page._cue_lookup = {cue.id: cue}
        page.selected_cue_id = cue.id
        page._load_style_inspector()
        page._updating_style_ui = True
        try:
            page.style_shadow_opacity.setValue(50)
            page.style_shadow_angle.setAngle(45)
            page.style_shadow_distance.setValue(12)
            page.style_shadow_blur.setValue(40)
            page.style_shadow_spread.setValue(4)
        finally:
            page._updating_style_ui = False
        page._apply_style()

        snapshot = build_visual_cue_snapshot(page.project, cue.id)
        graph_shadow = (
            snapshot.style_recipe["visualGraph"]["textLayer"]["shadow"]
        )
        assert page.style_shadow_distance.value() == 12
        assert normalize_shadow_contract(graph_shadow) == snapshot.shadow
        assert snapshot.shadow["opacity"] == 0.5
        assert snapshot.shadow["blur_radius"] == 40.0
        assert snapshot.shadow["spread"] == 4.0
    finally:
        page.close_page()


def _shadow_snapshot(*, opacity: float, blur: float, spread: float):
    base = _snapshot(0)
    shadow = normalize_shadow_contract({
        "enabled": opacity > 0,
        "color": "#FF000000",
        "opacity": opacity,
        "offset_x": 18,
        "offset_y": 12,
        "blur_radius": blur,
        "spread": spread,
    })
    recipe = copy.deepcopy(dict(base.style_recipe))
    recipe.setdefault("outline", {})["shadow"] = copy.deepcopy(shadow)
    graph = recipe.get("visualGraph")
    if isinstance(graph, dict) and isinstance(graph.get("textLayer"), dict):
        graph["textLayer"]["shadow"] = copy.deepcopy(shadow)
    return replace(
        base,
        text="SHADOW TEST",
        shadow=shadow,
        style_recipe=recipe,
    )


def _effect_image(snapshot):
    return render_live_snapshot(
        snapshot,
        width=640,
        height=360,
        layers=frozenset({"effects"}),
    )


def _image_hash(image) -> bytes:
    return bytes(image.constBits())


def _alpha_count(image) -> int:
    return sum(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


def test_shadow_opacity_blur_and_spread_have_independent_pixels(app):
    opacity_images = [
        _effect_image(_shadow_snapshot(opacity=value, blur=12, spread=2))
        for value in (0.0, 0.25, 0.5, 1.0)
    ]
    blur_images = [
        _effect_image(_shadow_snapshot(opacity=0.8, blur=value, spread=2))
        for value in (0.0, 5.0, 20.0, 40.0)
    ]
    spread_images = [
        _effect_image(_shadow_snapshot(opacity=0.8, blur=12, spread=value))
        for value in (0.0, 4.0, 10.0)
    ]

    assert len({_image_hash(image) for image in opacity_images}) == 4
    assert len({_image_hash(image) for image in blur_images}) == 4
    assert len({_image_hash(image) for image in spread_images}) == 3
    assert [_alpha_count(image) for image in blur_images] == sorted(
        _alpha_count(image) for image in blur_images
    )
    assert [_alpha_count(image) for image in spread_images] == sorted(
        _alpha_count(image) for image in spread_images
    )

    # Editing blur/spread never rewrites direction or distance.
    for candidate in blur_images + spread_images:
        assert not candidate.isNull()
    for blur in (0.0, 5.0, 20.0, 40.0):
        payload = _shadow_snapshot(opacity=0.8, blur=blur, spread=2).shadow
        assert payload["offset_x"] == 18
        assert payload["offset_y"] == 12
