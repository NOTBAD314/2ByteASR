"""P8B Applied Motion sampling and cue-duration normalization."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.rendering.advanced_live_renderer import composite_live_scene_layers, render_live_layers
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.caption_design.visual_design_graph import (
    CompiledLiveScene,
    MotionGraph,
    MotionKeyframe,
    MotionTrack,
    normalize_motion_graph_to_cue,
    comic_burst_graph,
    motion_phases,
    style_recipe_from_graph,
)
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


_APP = None


def _snapshot_for_graph(graph):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    recipe = style_recipe_from_graph(graph)
    text = graph.text_layer
    first = text.strokes[0]
    style = SubtitleStyle(
        "graph", graph.name,
        font_family=str(text.font.get("family") or "Arial"),
        font_size=float(text.font.get("size", 56)),
        primary_color=str(text.fill.get("color") or "#FFFFFF"),
        outline_color=str(first.get("color") or "#000000"),
        outline_width=float(first.get("width", 4)),
        bold=True,
        alignment=5,
        position_x=960,
        position_y=540,
    )
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=5_000, width=1920, height=1080),
        styles=[style],
        cues=[StudioCue("cue", 0, 5_000, "空中打拳", style_id="graph")],
        style_recipes={"graph": recipe.to_dict()},
    )
    return build_visual_cue_snapshot(project, "cue", width=640, height=360, fps=30)


def test_track_uses_property_default_before_first_keyframe_and_holds_last():
    graph = comic_burst_graph()
    graph.motion_graph = MotionGraph(1_000, [
        MotionTrack("group", "opacity", [
            MotionKeyframe(100, 0.0, "step"),
            MotionKeyframe(220, 1.0, "ease-out"),
        ]),
    ])
    scene = CompiledLiveScene.compile(graph)
    assert scene.sample(50).value("group", "opacity") == 1.0
    assert scene.sample(100).value("group", "opacity") == 0.0
    assert scene.sample(900).value("group", "opacity") == 1.0


def test_reset_is_explicit_and_restores_property_default_after_last_keyframe():
    graph = comic_burst_graph()
    graph.motion_graph = MotionGraph(1_000, [
        MotionTrack("group", "x", [
            MotionKeyframe(0, -20.0, "ease-out"),
            MotionKeyframe(180, 12.0, "ease-out"),
        ], post_behavior="RESET"),
    ])
    scene = CompiledLiveScene.compile(graph)
    assert scene.sample(180).value("group", "x") == 12.0
    assert scene.sample(181).value("group", "x") == 0.0


def test_short_graph_extends_readable_hold_and_anchors_exit_to_cue_end():
    graph = comic_burst_graph()
    original_entrance = next(
        track for track in graph.motion_graph.tracks
        if track.target == "group" and track.property == "opacity"
    )
    assert original_entrance.keyframes[1].time_ms == 70
    normalized = normalize_motion_graph_to_cue(graph, 5_000)
    opacity = next(
        track for track in normalized.motion_graph.tracks
        if track.target == "group" and track.property == "opacity"
    )
    assert opacity.keyframes[1].time_ms == 70
    assert opacity.keyframes[-2].time_ms == 4_780
    assert opacity.keyframes[-1].time_ms == 5_000
    scene = CompiledLiveScene.compile(normalized)
    assert scene.sample(2_500).value("group", "opacity") == 1.0
    assert scene.sample(4_700).value("group", "opacity") == 1.0
    assert scene.sample(5_000).value("group", "opacity") == 0.0
    phases = motion_phases(normalized)
    assert phases.entrance_end_ms < phases.exit_start_ms
    assert phases.exit_end_ms == 5_000


def test_live_pixels_remain_visible_through_hold_and_seek_reentry():
    graph = normalize_motion_graph_to_cue(comic_burst_graph(), 5_000)
    snapshot = _snapshot_for_graph(graph)
    layers = render_live_layers(snapshot, width=640, height=360)
    scene = CompiledLiveScene.compile(graph)
    alpha_counts = []
    for local_ms in (320, 900, 2_500, 4_500, 900):
        frame, _sample = composite_live_scene_layers(layers, scene, local_ms)
        alpha_counts.append(sum(
            1
            for y in range(frame.height())
            for x in range(frame.width())
            if frame.pixelColor(x, y).alpha() > 0
        ))
    assert all(value > 1_000 for value in alpha_counts)
    assert alpha_counts[1] == alpha_counts[-1]
