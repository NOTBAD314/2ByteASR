"""P8B canonical stroke contract across LIVE and Remotion inputs."""

from __future__ import annotations

from twobyteasr.rendering.advanced_renderer import normalized_visual_snapshot, scale_visual_for_composition
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from dataclasses import replace

from twobyteasr.caption_design.visual_design_graph import (
    VisualDesignGraph,
    comic_burst_graph,
    style_recipe_from_graph,
)
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot


def _snapshot(width: float):
    graph = comic_burst_graph()
    recipe = style_recipe_from_graph(graph)
    # Deliberately leave the AI graph at its original width. The current style
    # is the canonical user-owned value that both compilers must consume.
    style = SubtitleStyle(
        "graph",
        "Graph",
        font_family="Arial",
        font_size=115,
        primary_color="#FFFFFFFF",
        outline_color="#FF000000",
        outline_width=width,
        bold=True,
        alignment=5,
        position_x=960,
        position_y=540,
    )
    recipe.outline["color"] = style.outline_color
    recipe.outline["width"] = width
    recipe.outline["layers"] = [
        {"color": style.outline_color, "width": width, "opacity": 1}
    ]
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=2_400, width=1920, height=1080),
        styles=[style],
        cues=[StudioCue("cue", 0, 2_400, "描边层级", style_id="graph")],
        style_recipes={"graph": recipe.to_dict()},
    )
    return build_visual_cue_snapshot(project, "cue", width=1920, height=1080, fps=30)


def test_snapshot_overrides_stale_visual_graph_stroke_width():
    snapshot = _snapshot(20)
    visual = normalized_visual_snapshot(snapshot)
    assert visual["strokes"][0]["width"] == 20
    assert visual["visualGraph"]["textLayer"]["strokes"][0]["width"] == 20
    assert visual["visualGraph"]["textLayer"]["font"]["size"] == 115


def test_reference_pixel_conversion_occurs_once_at_preview_compiler_boundary():
    visual = normalized_visual_snapshot(_snapshot(20))
    compiled = scale_visual_for_composition(visual, composition_width=640)
    assert round(compiled["strokes"][0]["width"], 4) == round(20 / 3, 4)
    # Graph values remain canonical; its trusted TS compiler applies the same
    # 640/1920 factor once when it constructs CSS.
    assert compiled["visualGraph"]["textLayer"]["strokes"][0]["width"] == 20


def test_canonical_stroke_levels_are_strictly_ordered():
    widths = [
        normalized_visual_snapshot(_snapshot(value))["strokes"][0]["width"]
        for value in (1, 5, 10, 20)
    ]
    assert widths == [1, 5, 10, 20]


def test_snapshot_gradient_kind_is_synchronized_to_valid_graph_fill():
    snapshot = replace(_snapshot(10), fill={
        "kind": "linear-gradient",
        "angle": 35,
        "stops": [
            {"position": 0.0, "color": "#FFFFD84A"},
            {"position": 1.0, "color": "#FF237A57"},
        ],
    })
    visual = normalized_visual_snapshot(snapshot)
    graph_fill = visual["visualGraph"]["textLayer"]["fill"]
    assert graph_fill == {
        "type": "linear-gradient",
        "angle": 35.0,
        "stops": [
            {"position": 0.0, "color": "#FFFFD84A"},
            {"position": 1.0, "color": "#FF237A57"},
        ],
    }
    VisualDesignGraph.from_dict(visual["visualGraph"]).validate()


def test_shadow_blur_radius_is_canonical_reference_pixel_alias():
    snapshot = replace(_snapshot(10), shadow={
        "enabled": True,
        "color": "#FF000000",
        "opacity": 0.8,
        "offset_x": 12,
        "offset_y": 12,
        "blur_radius": 12,
        "spread": 2,
    })
    visual = normalized_visual_snapshot(snapshot)
    assert visual["shadow"]["blur"] == 12
    compiled = scale_visual_for_composition(visual, composition_width=640)
    assert compiled["shadow"]["blur"] == 4
    assert visual["visualGraph"]["textLayer"]["shadow"]["blur_radius"] == 12
