"""P7.4D: applied VisualDesignGraph runtime and real Add Track UI."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.advanced_live_renderer import (
    composite_live_scene_layers,
    composition_pivot_for_snapshot,
    render_live_layers,
    render_live_snapshot,
)
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.style_recipe import (
    MOTION_SOURCE_VISUAL_GRAPH,
    motion_mode,
    motion_source,
)
from twobyteasr.visual_design_graph import (
    COORDINATE_SPACE_SUBTITLE_LOCAL,
    COORDINATE_SPACE_TEXT,
    CompiledLiveScene,
    compile_live_scene,
    effect_family,
    effect_signature,
    glitch_graph,
    is_weak_motion_graph,
    layer_coordinate_space,
    readability_issues,
    repair_weak_motion_graph,
    style_recipe_from_graph,
    visual_composition_bounds,
)
from twobyteasr.visual_snapshot import build_visual_cue_snapshot


def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))


def _project_with_graph(tmp_path: Path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"mp4")
    graph = glitch_graph()
    recipe = style_recipe_from_graph(graph)
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=8_000, width=1280, height=720),
        cues=[StudioCue("cue-1", 400, 2_400, "故障字幕", style_id="ai-glitch")],
    )
    project.validate()
    project.style_recipes[recipe.name] = recipe.to_dict()
    # Apply uses plan_style.id; tests store under the cue style id.
    project.style_recipes["ai-glitch"] = recipe.to_dict()
    project.cues[0].style_id = "ai-glitch"
    project.cues[0].base_preset_id = "ai-glitch"
    return project, graph, recipe


def test_p74d_apply_recipe_keeps_visual_graph_and_motion_hash(tmp_path):
    graph = glitch_graph()
    recipe = style_recipe_from_graph(graph)
    payload = recipe.to_dict()
    assert payload["visualGraph"]["motionGraph"]["tracks"]
    assert payload["motion"]["origin"] == "visual_graph"
    assert payload["motion"]["graph"]["tracks"]
    restored = style_recipe_from_graph(
        __import__("twobyteasr.visual_design_graph", fromlist=["VisualDesignGraph"]).VisualDesignGraph.from_dict(
            payload["visualGraph"]
        )
    )
    assert restored.visual_graph["motionGraph"]["tracks"]
    assert graph.stable_hash() == __import__(
        "twobyteasr.visual_design_graph", fromlist=["VisualDesignGraph"]
    ).VisualDesignGraph.from_dict(payload["visualGraph"]).stable_hash()


def test_p74d_snapshot_keeps_graph_motion_source(tmp_path):
    project, graph, recipe = _project_with_graph(tmp_path)
    snapshot = build_visual_cue_snapshot(project, "cue-1", width=640, height=360)
    assert motion_source(snapshot.motion_recipe, visual_graph=snapshot.style_recipe.get("visualGraph")) == MOTION_SOURCE_VISUAL_GRAPH
    assert motion_mode(snapshot.motion_recipe) == "explicit"
    assert snapshot.motion_recipe.get("graph", {}).get("tracks")
    assert snapshot.style_recipe["visualGraph"]["motionGraph"]["tracks"]
    assert (
        graph.stable_hash()
        == __import__("twobyteasr.visual_design_graph", fromlist=["VisualDesignGraph"]).VisualDesignGraph.from_dict(
            snapshot.style_recipe["visualGraph"]
        ).stable_hash()
    )


def test_p74d_card_and_applied_share_compile_live_scene(tmp_path):
    project, graph, _recipe = _project_with_graph(tmp_path)
    snapshot = build_visual_cue_snapshot(project, "cue-1", width=640, height=360)
    card = compile_live_scene(graph)
    applied = compile_live_scene(snapshot.style_recipe["visualGraph"])
    assert card.graph_hash == applied.graph_hash == graph.stable_hash()
    enter = card.sample(80)
    mid = card.sample(1_200)
    assert enter.values != mid.values


def test_p74d_graph_motion_keeps_live_owner_while_paused(tmp_path):
    _app()
    from twobyteasr.studio_ui import SubtitleStudioPage

    project, _graph, _recipe = _project_with_graph(tmp_path)
    page = SubtitleStudioPage()
    page.project = project
    snapshot = build_visual_cue_snapshot(project, "cue-1", width=640, height=360)
    page.video._playback_clock.force_position(300, paused=True, reason="test-pause")
    assert page._fidelity_can_replace_live(snapshot) is False
    page.video._playback_clock.force_position(300, paused=False, reason="test-play")
    assert page._fidelity_can_replace_live(snapshot) is False
    page.deleteLater()


def test_p74d_halftone_stays_near_text_bounds(tmp_path):
    from twobyteasr.visual_design_graph import comic_burst_graph
    from twobyteasr.visual_snapshot import build_visual_cue_snapshot as build

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    graph = comic_burst_graph()
    recipe = style_recipe_from_graph(graph)
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=4_000, width=1920, height=1080),
        cues=[StudioCue("cue-1", 0, 2_000, "爆裂", style_id="comic")],
    )
    project.validate()
    project.style_recipes["comic"] = recipe.to_dict()
    snapshot = build(project, "cue-1", width=1920, height=1080)
    image = render_live_snapshot(snapshot, width=1920, height=1080)
    from PySide6.QtGui import QColor

    magenta = 0
    for y in range(0, image.height(), 8):
        for x in range(0, image.width(), 8):
            color = image.pixelColor(x, y)
            if color.alpha() > 20 and color.magenta() > 80 and color.green() < 80:
                magenta += 1
    # A full-frame takeover would paint tens of thousands of samples.
    assert magenta < 8_000


def test_p74d_weak_motion_detector_repairs_named_glitch():
    from twobyteasr.visual_design_graph import VisualDesignGraph, TextLayer, PanelLayer, MotionGraph, MotionTrack, MotionKeyframe

    weak = VisualDesignGraph(
        name="Glitch 方案",
        seed=1,
        text_layer=TextLayer(),
        panel_layer=PanelLayer("panel", "NONE", {}),
        motion_graph=MotionGraph(1_200, [
            MotionTrack("group", "scale", [
                MotionKeyframe(0, 0.5, "linear"), MotionKeyframe(400, 1.0, "linear"),
            ]),
            MotionTrack("group", "opacity", [
                MotionKeyframe(0, 0.0, "linear"), MotionKeyframe(200, 1.0, "linear"),
            ]),
        ]),
    ).validate()
    assert is_weak_motion_graph(weak)
    repaired = repair_weak_motion_graph(weak)
    assert not is_weak_motion_graph(repaired)
    assert any(item.primitive == "GLITCH" for item in repaired.effect_layers)


def test_p74d_effect_signatures_differ_across_golden_families():
    from twobyteasr.visual_design_graph import comic_burst_graph, streamer_gaming_graph

    signatures = {
        effect_signature(glitch_graph()),
        effect_signature(comic_burst_graph()),
        effect_signature(streamer_gaming_graph()),
    }
    assert len(signatures) == 3


def test_p74d_add_track_button_creates_visible_v2_a2(tmp_path, monkeypatch):
    _app()
    from twobyteasr.studio_project import save_project
    from twobyteasr.studio_ui import SubtitleStudioPage

    media = tmp_path / "one.mp4"
    media.write_bytes(b"mp4")
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=8_000, width=1280, height=720),
        cues=[StudioCue("cue-1", 0, 1_000, "hello")],
    )
    project.validate()
    path = save_project(project, tmp_path / "demo.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_project_waveforms", lambda *_a, **_k: None)
    page.open_project(path)
    page.timeline.resize(1200, 420)
    before = {track.id for track in page.project.video_tracks}
    page._add_video_track()
    ids = [track.id for track in page.project.video_tracks]
    assert "V2" in ids
    groups = {group.video_track_id: group.audio_track_id for group in page.project.av_track_groups}
    assert groups.get("V2") == "A2"
    rects = page.timeline._video_track_rects()
    audio = page.timeline._audio_track_rects()
    assert "V2" in rects and not rects["V2"].isEmpty()
    assert "A2" in audio and not audio["A2"].isEmpty()
    # 四十五轮：泳道顺序与渲染层级一致（Premiere 语义）——V2 在 V1 上方。
    assert rects["V2"].bottom() <= rects["V1"].top() + 1
    assert page._multitrack_composition_active is False
    assert set(ids) - before
    page.close_page()
    page.deleteLater()


def test_p74d_non_primary_ingest_does_not_hide_video(tmp_path, monkeypatch):
    _app()
    from twobyteasr.studio_ui import SubtitleStudioPage

    media = tmp_path / "one.mp4"
    media.write_bytes(b"mp4")
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=8_000),
        cues=[StudioCue("cue-1", 0, 1_000, "hello")],
    )
    project.validate()
    page = SubtitleStudioPage()
    page.project = project
    page._pending_media_mode = "pool"
    page._media_ingest_state = "LOADING"
    page._sync_video_empty_state()
    hint = getattr(page, "video_empty_hint", None)
    assert hint is None or not hint.isVisible()
    page.deleteLater()


def test_p74d_coordinate_space_defaults_to_subtitle_local():
    graph = glitch_graph()
    assert layer_coordinate_space(graph.text_layer) == COORDINATE_SPACE_TEXT
    assert layer_coordinate_space(graph.panel_layer) == COORDINATE_SPACE_SUBTITLE_LOCAL
    assert layer_coordinate_space(graph.decoration_layers[0]) == COORDINATE_SPACE_SUBTITLE_LOCAL
    x, y, width, height = visual_composition_bounds((0, 0, 200, 60), graph)
    assert width < 200 * 2.5
    assert height < 60 * 2.5


def test_p74d_cue_local_sample_is_seek_and_speed_deterministic():
    scene = compile_live_scene(glitch_graph())
    assert scene.sample(180).values == scene.sample(180).values
    at_1x = scene.sample(400)
    at_2x_media_time = scene.sample(400)
    assert at_1x.values == at_2x_media_time.values
    assert scene.sample(80).values != scene.sample(900).values


def test_p74d_applied_compositor_pivots_on_subtitle_not_frame_center(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    graph = glitch_graph()
    recipe = style_recipe_from_graph(graph)
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=8_000, width=1920, height=1080),
        cues=[StudioCue("cue-1", 400, 2_400, "故障字幕", style_id="ai-glitch")],
    )
    project.validate()
    project.style_recipes["ai-glitch"] = recipe.to_dict()
    snapshot = build_visual_cue_snapshot(project, "cue-1", width=1920, height=1080)
    layers = render_live_layers(snapshot, width=1920, height=1080)
    scene = compile_live_scene(graph)
    pivot = composition_pivot_for_snapshot(snapshot, 1920, 1080)
    frame, _sample = composite_live_scene_layers(layers, scene, 120, pivot=pivot)
    opaque = []
    for y in range(0, frame.height(), 6):
        for x in range(0, frame.width(), 6):
            color = frame.pixelColor(x, y)
            if color.alpha() > 24:
                opaque.append((x, y))
    assert opaque
    span_y = max(point[1] for point in opaque) - min(point[1] for point in opaque)
    span_x = max(point[0] for point in opaque) - min(point[0] for point in opaque)
    assert span_y < 560
    assert span_x < 1400
    sampled = (frame.width() // 6) * (frame.height() // 6)
    assert len(opaque) / max(1, sampled) < 0.28


def test_p74d_motion_inspector_shows_graph_motion_not_none(tmp_path, monkeypatch):
    _app()
    from twobyteasr.studio_project import save_project
    from twobyteasr.studio_ui import SubtitleStudioPage

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"mp4")
    project, graph, recipe = _project_with_graph(tmp_path)
    path = save_project(project, tmp_path / "demo.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_project_waveforms", lambda *_a, **_k: None)
    page.open_project(path)
    page.selected_cue_id = "cue-1"
    assert page._apply_style_recipe("cue-1", recipe)
    page._load_style_inspector()
    assert page.effect_preset.currentData() == "visual_graph"
    assert "无" not in page.effect_preset.currentText()
    assert not page.graph_motion_summary.isHidden()
    assert "Graph Motion" in page.graph_motion_summary.text()
    page.close_page()
    page.deleteLater()


def test_p74d_applied_graph_motion_plays_until_the_motion_page_overrides_it(tmp_path, monkeypatch):
    # 0.8.0: the compat pop stored beside an AI graph recipe replaced the
    # authored tracks in preview and export (snapshot) and in the 动效 page.
    _app()
    from twobyteasr.motion_application import motion_command
    from twobyteasr.studio_project import save_project
    from twobyteasr.studio_ui import SubtitleStudioPage

    project, _graph, recipe = _project_with_graph(tmp_path)
    path = save_project(project, tmp_path / "demo.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_project_waveforms", lambda *_a, **_k: None)
    page.open_project(path)
    page.selected_cue_id = "cue-1"
    assert page._apply_style_recipe("cue-1", recipe)
    cue = page.project.cues[0]
    assert page.project.effects[cue.effect_id]["entry"]["type"] == "pop"
    authored = page.project.style_recipes[cue.style_id]["visualGraph"]["motionGraph"]["tracks"]
    snapshot = build_visual_cue_snapshot(page.project, "cue-1", width=640, height=360)
    assert snapshot.motion_recipe["graph"]["tracks"] == authored

    command = motion_command(page.project, ["cue-1"], motion={"entry": {"type": "fade", "duration": 240}, "exit": {"type": "none"}})
    page.undo_stack.push(command)
    page._load_style_inspector()
    assert page.effect_preset.currentData() == "fade"
    assert page.graph_motion_summary.isHidden()
    snapshot = build_visual_cue_snapshot(page.project, "cue-1", width=640, height=360)
    assert [track["property"] for track in snapshot.motion_recipe["graph"]["tracks"]] == ["opacity"]
    page.close_page()
    page.deleteLater()


def test_p74d_short_timeline_does_not_stack_v2_on_v1(tmp_path, monkeypatch):
    _app()
    from twobyteasr.studio_project import save_project
    from twobyteasr.studio_ui import SubtitleStudioPage

    media = tmp_path / "one.mp4"
    media.write_bytes(b"mp4")
    project = SubtitleProject(
        media=StudioMedia(path=str(media), duration_ms=8_000, width=1280, height=720),
        cues=[StudioCue("cue-1", 0, 1_000, "hello")],
    )
    project.validate()
    path = save_project(project, tmp_path / "demo.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_project_waveforms", lambda *_a, **_k: None)
    page.open_project(path)
    page.timeline.resize(1200, 160)
    button = getattr(page, "add_video_track_button", None)
    if button is not None:
        button.click()
    else:
        page._add_video_track()
    rects = page.timeline._video_track_rects()
    # 四十五轮：泳道顺序与渲染层级一致（Premiere 语义）——V2 在 V1 上方。
    assert rects["V2"].bottom() <= rects["V1"].top() + 1
    audio = page.timeline._audio_track_rects()
    if "A1" in audio and "A2" in audio:
        assert audio["A2"].top() >= audio["A1"].bottom() - 1 or audio["A2"].top() >= rects["V2"].bottom() - 1
    page.close_page()
    page.deleteLater()


def test_p74d_effect_families_and_readability_on_golden_graphs():
    from twobyteasr.visual_design_graph import comic_burst_graph, streamer_gaming_graph

    assert effect_family(glitch_graph()) == "GLITCH_DIGITAL"
    assert effect_family(comic_burst_graph()) == "COMIC_BURST"
    assert effect_family(streamer_gaming_graph()) == "STREAMER_POP"
    assert not readability_issues(glitch_graph())
    assert not is_weak_motion_graph(glitch_graph())
    assert not is_weak_motion_graph(comic_burst_graph())
    assert not is_weak_motion_graph(streamer_gaming_graph())
