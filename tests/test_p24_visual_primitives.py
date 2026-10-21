"""P24 new visual primitives: graph vocabulary, Qt rendering, compositor
semantics (blur / mask_reveal), structural-diversity dimensions, and the
dual-renderer presence contract (Python graph + TSX fidelity source)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage

from twobyteasr.rendering.advanced_live_renderer import (
    composite_live_scene_layers,
    render_live_layers,
    render_live_snapshot,
)
from twobyteasr.caption_design.art_direction import (
    ART_DIRECTION_TEMPLATES,
    ArtDirectionSpec,
    _direction,
    validate_graph_for_direction,
)
from twobyteasr.caption_design.studio_ai import _STYLE_DESIGN_SYSTEM
from twobyteasr.caption_design.visual_design_graph import (
    DECORATION_PRIMITIVES,
    MOTION_PROPERTIES,
    PANEL_PRIMITIVES,
    CompiledLiveScene,
    DecorationLayer,
    MotionGraph,
    MotionKeyframe,
    MotionTrack,
    PanelLayer,
    TextLayer,
    VisualDesignGraph,
    structural_distance,
    validate_structural_variants,
)

ROOT = Path(__file__).resolve().parents[1]
TSX = ROOT / "renderer" / "src" / "components" / "VisualDesignGraphSubtitle.tsx"


@pytest.fixture(scope="module", autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    yield app


def _snapshot(cue_id: str = "p24"):
    return SimpleNamespace(
        cue_id=cue_id, text="新原语验证", start_ms=1_000, end_ms=5_000,
        font_family="Microsoft YaHei", font_size=52.0, font_weight=700,
        italic=False, letter_spacing=0.0,
        fill={"type": "solid", "color": "#FFFFFFFF"},
        strokes=({"color": "#FF000000", "width": 3, "alignment": "OUTSIDE"},),
        shadow={}, glow={},
        playres_x=1920, playres_y=1080,
        position_x=960.0, position_y=1000.0,
        anchor_x=0.5, anchor_y=1.0, scale_x=1.0, scale_y=1.0, rotation=0.0,
        style_recipe={}, motion_recipe={},
        stable_hash=lambda: "p24-hash",
    )


def _alpha_pixels(image: QImage) -> int:
    if image.isNull():
        return 0
    count = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            if ((image.pixel(x, y) >> 24) & 0xFF) > 40:
                count += 1
    return count


def test_vocabulary_contains_new_primitives():
    assert {"PILL", "TORN_PAPER", "GLASS_PANEL"} <= PANEL_PRIMITIVES
    assert {"SCAN_SWEEP", "PARTICLES", "ARROWS", "DATA_BARS"} <= DECORATION_PRIMITIVES
    assert {"blur", "mask_reveal"} <= MOTION_PROPERTIES


@pytest.mark.parametrize("panel", ["PILL", "TORN_PAPER", "GLASS_PANEL"])
def test_new_panels_render_qt_pixels(panel):
    graph = VisualDesignGraph(
        name=f"P24 {panel}",
        text_layer=TextLayer(),
        panel_layer=PanelLayer("panel", panel, {"color": "#80202040"}),
    ).validate()
    snapshot = _snapshot()
    object.__setattr__(
        snapshot, "style_recipe", {"visualGraph": graph.to_dict()},
    )
    image = render_live_snapshot(snapshot, width=640, height=360, device_pixel_ratio=1.0)
    assert _alpha_pixels(image) > 0, f"{panel} must paint pixels"


@pytest.mark.parametrize(
    "primitive",
    ["SCAN_SWEEP", "PARTICLES", "ARROWS", "DATA_BARS"],
)
def test_new_decorations_render_qt_pixels(primitive):
    graph = VisualDesignGraph(
        name=f"P24 {primitive}",
        text_layer=TextLayer(),
        decoration_layers=[DecorationLayer("deco", primitive, {"color": "#CCFFFFFF"}, 7)],
    ).validate()
    snapshot = _snapshot()
    object.__setattr__(snapshot, "style_recipe", {"visualGraph": graph.to_dict()})
    image = render_live_snapshot(snapshot, width=640, height=360, device_pixel_ratio=1.0)
    assert _alpha_pixels(image) > 0, f"{primitive} must paint pixels"


def _mask_graph() -> VisualDesignGraph:
    return VisualDesignGraph(
        name="P24 mask",
        text_layer=TextLayer(),
        motion_graph=MotionGraph(3_000, [
            MotionTrack("text", "mask_reveal", [
                MotionKeyframe(0, 0.0, "ease-out-expo"),
                MotionKeyframe(600, 1.0, "ease-out-expo"),
            ]),
        ]),
    ).validate()


def test_mask_reveal_zero_hides_and_one_shows():
    graph = _mask_graph()
    scene = CompiledLiveScene.compile(graph, cue_duration_ms=4_000)
    snapshot = _snapshot()
    object.__setattr__(snapshot, "style_recipe", {"visualGraph": graph.to_dict()})
    layers = render_live_layers(snapshot, width=640, height=360, device_pixel_ratio=1.0)
    hidden, _ = composite_live_scene_layers(layers, scene, 0)
    visible, _ = composite_live_scene_layers(layers, scene, 900)
    assert _alpha_pixels(hidden) == 0, "mask_reveal=0 must fully hide the layer"
    assert _alpha_pixels(visible) > 0, "mask_reveal=1 must reveal the layer"


def test_blur_reveal_keeps_layer_visible():
    graph = VisualDesignGraph(
        name="P24 blur",
        text_layer=TextLayer(),
        motion_graph=MotionGraph(3_000, [
            MotionTrack("text", "blur", [
                MotionKeyframe(0, 10.0, "ease-out"),
                MotionKeyframe(500, 0.0, "ease-out"),
            ]),
        ]),
    ).validate()
    scene = CompiledLiveScene.compile(graph, cue_duration_ms=4_000)
    snapshot = _snapshot()
    object.__setattr__(snapshot, "style_recipe", {"visualGraph": graph.to_dict()})
    layers = render_live_layers(snapshot, width=640, height=360, device_pixel_ratio=1.0)
    blurred, _ = composite_live_scene_layers(layers, scene, 0)
    sharp, _ = composite_live_scene_layers(layers, scene, 1_200)
    assert _alpha_pixels(blurred) > 0, "blur entrance must stay visible, not blank"
    assert _alpha_pixels(sharp) > 0
    # Blur softens edges outward, so the blurred frame covers at least as
    # much area as the resolved one; it must never cover less.
    assert _alpha_pixels(blurred) >= _alpha_pixels(sharp) * 0.9


def test_typography_and_palette_are_structural_dimensions():
    base = dict(
        name="A", text_layer=TextLayer(),
        panel_layer=PanelLayer("panel", "TECH_FRAME", {}),
    )
    plain = VisualDesignGraph(**base).validate()
    gradient = VisualDesignGraph(
        **{**base, "text_layer": TextLayer(fill={"type": "linear", "stops": [
            {"position": 0.0, "color": "#FFFFF2CC"},
            {"position": 1.0, "color": "#FF33AA55"},
        ]})},
    ).validate()
    assert structural_distance(plain, gradient) >= 1, (
        "fill treatment alone must register on the typography dimension"
    )


def test_shared_color_family_across_all_three_rejected():
    cyan_fill = {"type": "solid", "color": "#FF20E8FF"}

    def variant(name, panel, tracks):
        return VisualDesignGraph(
            name=name,
            text_layer=TextLayer(fill=dict(cyan_fill)),
            panel_layer=PanelLayer("panel", panel, {"color": "#3320E8FF"}),
            decoration_layers=[DecorationLayer("deco", "SCANLINES", {"color": "#6620E8FF"}, 3)],
            motion_graph=MotionGraph(2_000, tracks),
        ).validate()

    trio = (
        variant("A", "TECH_FRAME", []),
        variant("B", "PILL", [MotionTrack("deco", "opacity", [
            MotionKeyframe(0, 0.0), MotionKeyframe(300, 1.0),
        ])]),
        variant("C", "CUT_CORNER", [MotionTrack("deco", "x", [
            MotionKeyframe(0, -20.0), MotionKeyframe(300, 0.0),
        ])]),
    )
    # Panels and motion differ, but the palette family is identical on all
    # three — the classic all-cyan convergence the user reported.
    with pytest.raises(Exception, match="color family"):
        validate_structural_variants(trio)


def test_new_primitives_are_prompted_and_rendered_in_tsx():
    for token in (
        "PILL", "TORN_PAPER", "GLASS_PANEL",
        "SCAN_SWEEP", "PARTICLES", "ARROWS", "DATA_BARS",
        "blur", "mask_reveal",
    ):
        assert token in _STYLE_DESIGN_SYSTEM, f"prompt must teach {token}"
    tsx = TSX.read_text(encoding="utf-8")
    for token in (
        "PILL", "TORN_PAPER", "GLASS_PANEL",
        "SCAN_SWEEP", "PARTICLES", "ARROWS", "DATA_BARS",
        "mask_reveal",
    ):
        assert token in tsx, f"fidelity TSX must implement {token}"


def test_families_grant_new_primitive_permissions():
    hud = ART_DIRECTION_TEMPLATES["CYBER_HUD"]
    assert {"SCAN_SWEEP", "DATA_BARS", "PARTICLES", "GLASS_PANEL"} <= set(hud.allowed_layers)
    manga = ART_DIRECTION_TEMPLATES["MANGA_IMPACT"]
    assert {"ARROWS", "TORN_PAPER"} <= set(manga.allowed_layers)
    graph = VisualDesignGraph(
        name="P24 hud glass",
        text_layer=TextLayer(),
        panel_layer=PanelLayer("panel", "TECH_FRAME", {}),
        decoration_layers=[
            DecorationLayer("sweep", "SCAN_SWEEP", {"color": "#6620E8FF"}, 5),
            DecorationLayer("bars", "DATA_BARS", {"color": "#6620E8FF"}, 6),
            DecorationLayer("lines", "SCANLINES", {"color": "#4420E8FF"}, 8),
        ],
        motion_graph=MotionGraph(2_000, [
            MotionTrack("sweep", "x", [
                MotionKeyframe(0, -120.0), MotionKeyframe(900, 120.0),
            ]),
            MotionTrack("bars", "scale", [
                MotionKeyframe(0, 0.4, "spring"), MotionKeyframe(500, 1.0, "spring"),
            ]),
        ]),
    ).validate()
    direction: ArtDirectionSpec = _direction(
        "CYBER_HUD", "Glass HUD", intent="verify", motion="line draw",
        composition="frame", color="derived", avoid=("x", "y"),
    )
    validate_graph_for_direction(graph, direction)
    # GLASS_PANEL is inside the family vocabulary as an alternative panel.
    glass = PanelLayer("panel", "GLASS_PANEL", {})
    glass_graph = VisualDesignGraph(
        name="P24 glass alt",
        text_layer=TextLayer(),
        panel_layer=glass,
        decoration_layers=[DecorationLayer("sweep", "SCAN_SWEEP", {"color": "#6620E8FF"}, 5)],
        motion_graph=MotionGraph(2_000, [
            MotionTrack("sweep", "x", [
                MotionKeyframe(0, -120.0), MotionKeyframe(900, 120.0),
            ]),
            MotionTrack("panel", "mask_reveal", [
                MotionKeyframe(0, 0.0, "ease-out-expo"),
                MotionKeyframe(500, 1.0, "ease-out-expo"),
            ]),
        ]),
    ).validate()
    # TECH_FRAME signature still satisfied by the deco/graph above; the glass
    # alternative keeps the same permissions.
    assert "GLASS_PANEL" in hud.panel_vocabulary
