"""“微调设计”: one-round PATCH revision of a single AI design variant."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr.caption_design import studio_ai
from twobyteasr.caption_design.art_direction import fallback_art_directions
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.caption_design.visual_design_graph import victorian_mechanical_graph


def _project():
    return SubtitleProject(
        media=StudioMedia(path="fixture.mp4", duration_ms=5_000, width=1920, height=1080),
        cues=[StudioCue("cue", 0, 4_500, "蒸汽朋克字幕")],
    )


def _previous_payload():
    return {
        "direction": fallback_art_directions("蒸汽朋克风格")[1].to_dict(),
        "graph": victorian_mechanical_graph().to_dict(),
    }


class Provider:
    provider_id = "fixture"
    transport = "openai_compatible"

    def __init__(self, response):
        self._response = response
        self.requests: list[object] = []

    def validate(self, *args, **kwargs):
        return SimpleNamespace(authenticated=True, available=True, message="ready")

    def structured_complete(self, messages, schema, **kwargs):
        self.requests.append((messages, schema, kwargs))
        return self._response


def _revision_response(payload=None):
    return payload or {
        "revision_notes": "加重黄铜金属感",
        "direction": _previous_payload()["direction"],
        "variant": victorian_mechanical_graph().to_dict(),
    }


def test_revision_round_trip_returns_recipe_direction_notes(monkeypatch):
    provider = Provider(_revision_response())
    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: provider)
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist",
        lambda **_k: {"chinese_sans": ["Source Han Sans CN"]},
    )
    recipe, direction, notes = studio_ai.request_style_revision(
        _project(), "cue", "蒸汽朋克风格", "金属感再重一点",
        fallback_art_directions("蒸汽朋克风格")[1],
        _previous_payload()["graph"],
        {"models": {"ai_design_timeout_seconds": 5}},
    )
    assert notes == "加重黄铜金属感"
    assert direction.primary_family == "VICTORIAN_MECHANICAL"
    assert recipe.visual_graph, "revised recipe must carry the patched graph"
    # PATCH semantics: previous graph travels to the provider.
    user = provider.requests[0][0][1]["content"]
    assert "previous_graph" in user and "user_feedback" in user


def test_revision_rejects_fake_patch(monkeypatch):
    graph = victorian_mechanical_graph().to_dict()
    graph["textLayer"]["fill"] = {"type": "solid", "color": "#FFFFFFFF"}
    graph["textLayer"]["strokes"] = []
    provider = Provider({
        "revision_notes": "改好了",
        "direction": _previous_payload()["direction"],
        "variant": graph,
    })
    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: provider)
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist",
        lambda **_k: {"chinese_sans": ["Source Han Sans CN"]},
    )
    with pytest.raises(RuntimeError, match="微调结果未通过校验"):
        studio_ai.request_style_revision(
            _project(), "cue", "蒸汽朋克风格", "金属感再重一点",
            fallback_art_directions("蒸汽朋克风格")[1],
            _previous_payload()["graph"],
            {"models": {"ai_design_timeout_seconds": 5}},
        )


def test_revision_without_previous_graph_fails_fast(monkeypatch):
    monkeypatch.setattr(
        studio_ai, "available_font_shortlist",
        lambda **_k: {"chinese_sans": ["Source Han Sans CN"]},
    )
    monkeypatch.setattr(studio_ai, "provider_for_stage", lambda *_a, **_k: Provider({}))
    with pytest.raises(RuntimeError, match="没有可用的 VisualDesignGraph"):
        studio_ai.request_style_revision(
            _project(), "cue", "蒸汽朋克风格", "改一下",
            None, None, {"models": {}},
        )
