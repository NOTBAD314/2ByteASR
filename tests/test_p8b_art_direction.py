"""P8B semantic art direction, curated families, and quality policy."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr.caption_design.art_direction import (
    ART_DIRECTION_TEMPLATES,
    DecorationDensity,
    art_direction_manifest,
    fallback_art_directions,
    score_visual_graph,
    validate_and_repair_graph,
    validate_graph_for_direction,
)
from twobyteasr.caption_design.visual_design_graph import (
    DecorationLayer,
    MotionGraph,
    MotionKeyframe,
    MotionTrack,
    comic_burst_graph,
    glitch_graph,
    manga_impact_graph,
    streamer_gaming_graph,
)
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject


def test_curated_family_library_has_at_least_twelve_complete_templates():
    assert len(ART_DIRECTION_TEMPLATES) >= 12
    assert {
        "AMERICAN_COMIC_BURST", "MANGA_IMPACT", "HALFTONE_SLAM",
        "SPEEDLINE_PUNCH", "CRT_GLITCH", "SIGNAL_LOSS", "CYBER_HUD",
        "DATA_SCAN", "CRITICAL_HIT", "ACHIEVEMENT_POP",
        "STREAMER_EMPHASIS", "KILL_FEED", "CLEAN_EDITORIAL",
    } <= set(ART_DIRECTION_TEMPLATES)
    for item in ART_DIRECTION_TEMPLATES.values():
        assert item.allowed_layers
        assert item.motion_vocabulary
        assert item.easing
        assert item.readability_rules
        assert item.forbidden_cheap_patterns
    comic = next(
        item for item in art_direction_manifest()
        if item["family_id"] == "AMERICAN_COMIC_BURST"
    )
    assert comic["required_signature_groups"] == [
        ["COMIC_BURST"], ["IMPACT_RAYS"], ["IMPACT"],
    ]


def test_fallback_abc_are_semantically_and_structurally_distinct_directions():
    directions = fallback_art_directions("赛博故障，但 hold 期间稳定")
    assert len(directions) == 3
    assert len({item.primary_family for item in directions}) == 3
    assert len({item.motion_concept for item in directions}) == 3
    assert all(item.family_mix[0] >= 60 for item in directions)
    assert all(item.regeneration_anchor for item in directions)
    assert directions[0].density is DecorationDensity.MEDIUM


def test_offline_planner_pairs_each_direction_with_its_family_graph():
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    from twobyteasr.caption_design.visual_design_graph import VisualDesignGraph

    directions = fallback_art_directions("美漫爆裂")
    recipes = studio_ai._fallback_graph_recipes(
        "美漫爆裂",
        StyleRecipe(name="base"),
        {"chinese_sans": ["Source Han Sans CN"]},
        directions,
    )
    graphs = [VisualDesignGraph.from_dict(item.visual_graph) for item in recipes]
    assert [item.primary_family for item in directions] == [
        "AMERICAN_COMIC_BURST", "MANGA_IMPACT", "HALFTONE_SLAM",
    ]
    assert graphs[0].panel_layer.primitive == "COMIC_BURST"
    assert {item.primitive for item in graphs[1].decoration_layers} == {
        "SPEED_LINES", "SHARDS",
    }
    assert graphs[2].panel_layer.primitive == "CUT_CORNER"
    assert [item.primitive for item in graphs[2].decoration_layers] == ["HALFTONE"]


def test_streamer_family_has_stable_hold_and_explicit_exit():
    graph = streamer_gaming_graph()
    opacity = next(
        item for item in graph.motion_graph.tracks
        if item.target == "group" and item.property == "opacity"
    )
    assert [(item.time_ms, item.value) for item in opacity.keyframes[-2:]] == [
        (2_180, 1), (2_400, 0),
    ]


def test_quality_score_exposes_every_required_dimension():
    direction = fallback_art_directions("美漫爆裂")[0]
    score = score_visual_graph(comic_burst_graph(), direction)
    payload = score.to_dict()
    assert score.accepted
    assert {
        "readability", "hierarchy", "composition", "motion_quality",
        "effect_specificity", "visual_density", "renderer_support",
    } <= set(payload)


def test_graph_must_implement_its_declared_family_not_every_prompt_keyword():
    comic, manga, _halftone = fallback_art_directions("美漫爆裂")
    validate_graph_for_direction(comic_burst_graph(), comic)
    validate_graph_for_direction(manga_impact_graph(), manga)
    with pytest.raises(ValueError, match="AMERICAN_COMIC_BURST"):
        validate_graph_for_direction(glitch_graph(), comic)


def test_cheap_named_motion_is_repaired_once_with_family_specific_layers():
    direction = fallback_art_directions("美漫爆裂")[0]
    graph = comic_burst_graph()
    graph.effect_layers = []
    graph.decoration_layers = []
    graph.motion_graph = MotionGraph(1_000, [
        MotionTrack("group", "scale", [
            MotionKeyframe(0, 0.8, "linear"),
            MotionKeyframe(180, 1.0, "linear"),
        ]),
        MotionTrack("group", "opacity", [
            MotionKeyframe(0, 0.0, "linear"),
            MotionKeyframe(180, 1.0, "linear"),
        ]),
    ])
    graph.validate()
    before = score_visual_graph(graph, direction)
    assert "CHEAP_MOTION" in before.issues
    repaired, after = validate_and_repair_graph(graph, direction)
    assert after.repaired
    assert any(track.target == repaired.panel_layer.id for track in repaired.motion_graph.tracks)


def test_primitive_soup_is_detected_and_reduced_by_one_repair():
    direction = fallback_art_directions("故障")[0]
    graph = glitch_graph()
    graph.decoration_layers.extend([
        DecorationLayer(f"decor-{index}", "HALFTONE", {"opacity": 1.0}, index)
        for index in range(8)
    ])
    graph.validate()
    before = score_visual_graph(graph, direction)
    assert "OVERDECORATED" in before.issues
    repaired, after = validate_and_repair_graph(copy.deepcopy(graph), direction)
    assert len(repaired.decoration_layers) <= 4
    assert "OVERDECORATED" not in after.issues


def test_rhetoric_tokens_cannot_demand_primitives_the_family_forbids():
    """CLEAN_EDITORIAL prose mentioning "impact" is rhetoric, not a declaration.

    Regression for the real P9A-R2 DeepSeek trace: variant C declared
    CLEAN_EDITORIAL + DATA_SCAN with "relying on motion for impact" and the
    validator demanded an IMPACT layer those families forbid, producing an
    unsatisfiable ART_DIRECTION_MISMATCH no local repair could resolve.
    """
    from twobyteasr.caption_design.art_direction import ArtDirectionSpec

    direction = ArtDirectionSpec(
        concept_name="quiet editorial",
        intent="Typography-led readable emphasis",
        emotion="calm",
        visual_language="editorial",
        reference_family="CLEAN_EDITORIAL",
        hierarchy="text is the whole mass",
        text_emphasis="weight and spacing only",
        composition="centered line",
        shape_language="none",
        color_strategy="neutral pair plus one accent",
        contrast_strategy="high contrast text",
        motion_concept="Text slides in with soft anticipation and a stable hold.",
        entrance_feel="soft",
        hold_feel="still",
        exit_feel="quiet",
        decoration_strategy="Use ACCENT_BARS sparingly.",
        effect_strategy="No effects, relying on motion for impact.",
        density=DecorationDensity.LOW,
        primary_family="CLEAN_EDITORIAL",
        secondary_family="DATA_SCAN",
        avoid=("no decorative panels",),
    )
    graph = streamer_gaming_graph()
    graph.panel_layer.primitive = "NONE"
    graph.panel_layer.params = {}
    graph.decoration_layers = [DecorationLayer("bars", "ACCENT_BARS", {"opacity": 0.6}, 1)]
    graph.effect_layers = []
    graph.motion_graph.tracks = [
        track for track in graph.motion_graph.tracks
        if track.target in {"group", graph.panel_layer.id, "bars", "text"}
    ]
    graph.validate()
    direction.validate()

    validate_graph_for_direction(graph, direction)
    repaired, score = validate_and_repair_graph(copy.deepcopy(graph), direction)
    assert score.accepted
    assert {item.primitive for item in repaired.effect_layers} == set()


def test_real_deepseek_trace_responses_parse_schema_and_quality_pass():
    """Replay the two raw payloads from the 2026-08-30 packaged DeepSeek run."""
    from twobyteasr.caption_design.studio_ai import _parse_design_payload

    trace = json.loads(
        (Path(__file__).parent / "data" / "p9a_r2_deepseek_raw_responses.json")
        .read_text(encoding="utf-8")
    )
    instruction = trace["instruction"]
    fonts = {"chinese_sans": ["Source Han Sans CN"]}
    assert len(trace["raw_provider_responses"]) == 2
    for payload in trace["raw_provider_responses"]:
        recipes, intent, changes, reason, directions, scores = _parse_design_payload(
            payload, instruction, fonts,
        )
        assert len(recipes) == 3
        assert intent and reason
        assert len(directions) == 3
        assert all(score.accepted for score in scores)
        assert all("ART_DIRECTION_MISMATCH" not in score.issues for score in scores)


def test_provider_contract_returns_directions_before_corresponding_graphs(monkeypatch):
    from twobyteasr.caption_design import studio_ai

    directions = (
        fallback_art_directions("美漫爆裂")[0],
        fallback_art_directions("赛博故障")[0],
        fallback_art_directions("游戏直播")[1],
    )
    captured = {}

    class Provider:
        provider_id = "fixture-art-director"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def structured_complete(messages, schema, **_kwargs):
            captured["messages"] = messages
            captured["schema"] = schema
            return {
                "design_intent": "Readable, controlled, expressive",
                "visual_changes": ["hierarchy", "composition", "temporal structure"],
                "motion_reason": "Each direction uses a distinct layered rhythm",
                "art_directions": [item.to_dict() for item in directions],
                "variants": [
                    comic_burst_graph().to_dict(),
                    glitch_graph().to_dict(),
                    streamer_gaming_graph().to_dict(),
                ],
            }

    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: Provider())
    monkeypatch.setattr(
        studio_ai,
        "available_font_shortlist",
        lambda **_kwargs: {"chinese_sans": ["Source Han Sans CN"]},
    )
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=3_000, width=1920, height=1080),
        cues=[StudioCue("cue", 0, 3_000, "高能时刻")],
    )
    suggestion = studio_ai.request_style_design(
        project,
        "cue",
        "三套具有独立图层动作的字幕方向",
        {"models": {"ai_design_timeout_seconds": 5}},
    )
    assert suggestion.provider_succeeded
    assert len(suggestion.art_directions) == 3
    assert len({item.primary_family for item in suggestion.art_directions}) == 3
    assert all(score.accepted for score in suggestion.quality_scores)
    assert "art_directions" in captured["schema"]["required"]
    system_prompt = captured["messages"][0]["content"]
    assert system_prompt.index("ArtDirectionSpec") < system_prompt.index("VisualDesignGraph V1")


def test_provider_quality_repair_is_bounded_to_one_retry(monkeypatch):
    from twobyteasr.caption_design import studio_ai

    directions = (
        fallback_art_directions("美漫爆裂")[0],
        fallback_art_directions("赛博故障")[0],
        fallback_art_directions("游戏直播")[1],
    )
    calls = []

    class Provider:
        provider_id = "fixture-repair"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def structured_complete(_messages, _schema, **_kwargs):
            calls.append(object())
            if len(calls) == 1:
                return {"invalid": True}
            return {
                "design_intent": "Readable, controlled, expressive",
                "visual_changes": ["hierarchy", "composition", "motion"],
                "motion_reason": "Distinct layered timing",
                "art_directions": [item.to_dict() for item in directions],
                "variants": [
                    comic_burst_graph().to_dict(),
                    glitch_graph().to_dict(),
                    streamer_gaming_graph().to_dict(),
                ],
            }

    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: Provider())
    monkeypatch.setattr(
        studio_ai,
        "available_font_shortlist",
        lambda **_kwargs: {"chinese_sans": ["Source Han Sans CN"]},
    )
    project = SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=3_000, width=1920, height=1080),
        cues=[StudioCue("cue", 0, 3_000, "高能时刻")],
    )
    stages = []
    suggestion = studio_ai.request_style_design(
        project, "cue", "三套具有独立图层动作的字幕方向",
        {"models": {"ai_design_timeout_seconds": 5}},
        stage_callback=stages.append,
    )
    assert suggestion.provider_succeeded
    assert len(calls) == 2
    assert stages.count("REPAIRING") == 1
