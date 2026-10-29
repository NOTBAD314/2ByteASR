"""ArtDirection → VisualDesignGraph fidelity: prose must materialize.

用户写“蒸汽朋克”，三稿必须都是蒸汽朋克子方向，且 graph 真实包含对应的
视觉原语/金属渐变/多层描边——描述写得再好、graph 还是白字单描边就是
QUALITY FAIL。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.caption_design.art_direction import (
    ART_DIRECTION_TEMPLATES,
    fallback_art_directions,
    validate_graph_for_direction,
    validate_graph_matches_instruction,
    validate_variants_match_instruction,
)
from twobyteasr.caption_design.visual_design_graph import (
    clean_subtitle_graph,
    comic_burst_graph,
    glitch_graph,
    industrial_brass_hud_graph,
    steam_gauge_graph,
    victorian_mechanical_graph,
)


def _steampunk_triple():
    return fallback_art_directions("蒸汽朋克风格")


def _steampunk_graphs():
    return [
        industrial_brass_hud_graph(),
        victorian_mechanical_graph(),
        steam_gauge_graph(),
    ]


def test_steampunk_instruction_routes_to_steampunk_family_triple():
    directions = fallback_art_directions("蒸汽朋克风格")
    assert tuple(item.primary_family for item in directions) == (
        "INDUSTRIAL_BRASS_HUD",
        "VICTORIAN_MECHANICAL",
        "STEAM_GAUGE_TYPO",
    )


def test_fake_design_rejected_white_text_single_stroke():
    """The exact human symptom: prose says steampunk, graphs stay default."""
    from twobyteasr.caption_design.art_direction import fallback_art_directions as fallback

    default_directions = fallback("随便")
    default_graphs = [
        clean_subtitle_graph(),
        comic_burst_graph(),
        glitch_graph(),
    ]
    with pytest.raises(ValueError, match="ART_DIRECTION_MISMATCH"):
        validate_variants_match_instruction(
            "蒸汽朋克风格", default_directions, default_graphs,
        )


def test_steampunk_golden_triple_passes_both_fidelity_gates():
    directions = _steampunk_triple()
    graphs = _steampunk_graphs()
    for direction, graph in zip(directions, graphs):
        validate_graph_for_direction(graph, direction)
        validate_graph_matches_instruction("蒸汽朋克风格", direction, graph)
    validate_variants_match_instruction("蒸汽朋克风格", directions, graphs)


def test_unrelated_family_inside_triple_rejected():
    """One draft jumping to Manga under a steampunk brief fails the triple."""
    directions = list(_steampunk_triple())
    directions[1] = fallback_art_directions("漫画")[1]
    with pytest.raises(ValueError, match="ART_DIRECTION_MISMATCH"):
        validate_variants_match_instruction(
            "蒸汽朋克风格", tuple(directions), _steampunk_graphs(),
        )


def test_signature_primitive_floor_rejected_when_missing():
    graphs = _steampunk_graphs()
    for graph in graphs:
        graph.decoration_layers = [
            item for item in graph.decoration_layers
            if item.primitive not in {"GEARS", "RIVETS", "GAUGE", "PIPES", "STEAM"}
        ]
        graph.panel_layer.primitive = "NONE"
        graphs[0].text_layer.fill = {"type": "solid", "color": "#FFFFFFFF"}
    with pytest.raises(ValueError, match="ART_DIRECTION_MISMATCH"):
        validate_variants_match_instruction(
            "蒸汽朋克风格", _steampunk_triple(), graphs,
        )


def test_user_typed_primitive_required_per_graph():
    instruction = "蒸汽朋克风格，一定要有齿轮"
    graphs = _steampunk_graphs()
    directions = _steampunk_triple()
    # Industrial Brass HUD has rivets/gauge/pipes but no gears: the user's
    # explicit word is binding on every variant.
    with pytest.raises(ValueError, match="GEARS"):
        for direction, graph in zip(directions, graphs):
            validate_graph_matches_instruction(instruction, direction, graph)


def test_declared_multilayer_outline_requires_two_strokes():
    graph = industrial_brass_hud_graph()
    direction = _steampunk_triple()[0]
    graph.text_layer.strokes = graph.text_layer.strokes[:1]
    with pytest.raises(ValueError, match="multi-layer outline"):
        validate_graph_matches_instruction(
            "brass multilayer outline steampunk", direction, graph
        )


def test_metallic_request_requires_metallic_evidence():
    graph = industrial_brass_hud_graph()
    graph.text_layer.fill = {"type": "solid", "color": "#FFFFFFFF"}
    graph.text_layer.strokes = []
    direction = _steampunk_triple()[0]
    with pytest.raises(ValueError, match="metallic"):
        validate_graph_matches_instruction("金属感 steampunk", direction, graph)


def test_neutral_instruction_imposes_no_family_binding():
    """Without a named direction the model stays free (不限制自由发挥)."""
    directions = fallback_art_directions("柔和清晰的对白字幕")
    graphs = [clean_subtitle_graph(), comic_burst_graph(), glitch_graph()]
    validate_variants_match_instruction("柔和清晰的对白字幕", directions, graphs)


def test_steampunk_templates_declare_the_new_primitives():
    for family_id in ("INDUSTRIAL_BRASS_HUD", "VICTORIAN_MECHANICAL", "STEAM_GAUGE_TYPO"):
        template = ART_DIRECTION_TEMPLATES[family_id]
        assert "MECHANICAL_PLATE" in template.panel_vocabulary or "LOWER_THIRD" in template.panel_vocabulary
        assert set(template.allowed_layers) & {"GEARS", "RIVETS", "GAUGE", "PIPES", "STEAM"}
