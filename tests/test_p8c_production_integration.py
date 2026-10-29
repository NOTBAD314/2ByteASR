from __future__ import annotations

import copy
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from twobyteasr.caption_design import studio_ai
from twobyteasr.studio import studio_ui, studio_ai_flow  # noqa: E402
from twobyteasr.design.main_ui_dialogs import SpringDialog  # noqa: E402
from twobyteasr.caption_design.art_direction import (  # noqa: E402
    fallback_art_directions,
    score_visual_graph,
    validate_and_repair_graph,
)
from twobyteasr.providers.llm_config import AI_SERVICE_SPECS, endpoint_from_settings  # noqa: E402
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject  # noqa: E402
from twobyteasr.design.studio_theme import StudioComboBox  # noqa: E402
from twobyteasr.caption_style.style_recipe import StyleRecipe  # noqa: E402
from twobyteasr.caption_design.visual_design_graph import VisualDesignGraph  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_spring_dialog_reopen_reuses_unchanged_theme_palette(monkeypatch):
    app = _app()
    dialog = SpringDialog()
    refresh_calls = []
    original = dialog.refresh_theme_palette

    def refresh():
        refresh_calls.append(True)
        original()

    monkeypatch.setattr(dialog, "refresh_theme_palette", refresh)
    dialog.show()
    app.processEvents()
    dialog.hide()
    dialog.show()
    app.processEvents()
    assert refresh_calls == []
    assert dialog._entrance_motion is not None
    dialog.close()


def _direction_graph(instruction: str, index: int):
    directions = fallback_art_directions(instruction)
    recipes = studio_ai._fallback_graph_recipes(
        instruction,
        StyleRecipe(name="base"),
        {"chinese_sans": ["Source Han Sans CN"]},
        directions,
    )
    return directions[index], VisualDesignGraph.from_dict(recipes[index].visual_graph)


def _remove_motion_for_primitives(graph: VisualDesignGraph, primitives: set[str]) -> None:
    target_ids = {
        item.id
        for item in (*graph.decoration_layers, *graph.effect_layers)
        if item.primitive in primitives
    }
    graph.motion_graph.tracks = [
        track for track in graph.motion_graph.tracks if track.target not in target_ids
    ]
    graph.validate()


def _assert_one_repair_animates(
    direction,
    graph: VisualDesignGraph,
    primitives: set[str],
) -> None:
    before = score_visual_graph(graph, direction)
    assert "ART_DIRECTION_MISMATCH" in before.issues
    repaired, after = validate_and_repair_graph(graph, direction)
    repaired_ids = {
        item.id
        for item in (*repaired.decoration_layers, *repaired.effect_layers)
        if item.primitive in primitives
    }
    assert after.repaired is True
    assert after.accepted is True
    assert repaired_ids
    assert any(track.target in repaired_ids for track in repaired.motion_graph.tracks)


def test_art_direction_repair_materializes_scan_glitch_impact_and_shards():
    glitch_direction, glitch = _direction_graph("赛博故障", 0)
    _remove_motion_for_primitives(glitch, {"GLITCH"})
    _assert_one_repair_animates(glitch_direction, glitch, {"GLITCH"})

    scan_direction, scan = _direction_graph("赛博故障", 1)
    _remove_motion_for_primitives(scan, {"SCANLINES"})
    _assert_one_repair_animates(scan_direction, scan, {"SCANLINES"})

    impact_direction, impact = _direction_graph("美漫爆裂", 0)
    _remove_motion_for_primitives(impact, {"IMPACT", "IMPACT_RAYS"})
    _assert_one_repair_animates(impact_direction, impact, {"IMPACT", "IMPACT_RAYS"})

    shard_direction, shards = _direction_graph("美漫爆裂", 1)
    shard_direction = replace(shard_direction, effect_strategy="碎片飞散并在停留前收束")
    _remove_motion_for_primitives(shards, {"SHARDS"})
    _assert_one_repair_animates(shard_direction, shards, {"SHARDS"})


def test_ai_design_uses_quality_deadline_before_legacy_polish_timeout(monkeypatch):
    captured = {}

    class Provider:
        provider_id = "deadline-fixture"

        @staticmethod
        def capabilities():
            return SimpleNamespace(vision=False, structured_output=True)

        @staticmethod
        def structured_complete(_messages, _schema, **kwargs):
            captured["timeout"] = kwargs["timeout"]
            raise RuntimeError("fixture stop")

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
        "三套游戏字幕方向",
        {"models": {"ai_design_timeout_seconds": 120, "polish_timeout_seconds": 5}},
    )
    telemetry = suggestion.raw_response["_studio_telemetry"]
    assert captured["timeout"] > 100
    assert telemetry["deadline_seconds"] == 120
    assert suggestion.provider_succeeded is False


class _ProviderHarness:
    _refresh_ai_design_provider_summary = (
        studio_ui.SubtitleStudioPage._refresh_ai_design_provider_summary
    )
    _ai_design_provider_changed = (
        studio_ui.SubtitleStudioPage._ai_design_provider_changed
    )
    _ai_design_model_changed = studio_ui.SubtitleStudioPage._ai_design_model_changed
    _commit_ai_design_provider_selection = (
        studio_ui.SubtitleStudioPage._commit_ai_design_provider_selection
    )

    def window(self):
        return SimpleNamespace(legacy=None)


def test_ai_design_provider_popup_updates_shared_settings_with_real_qt_events(monkeypatch):
    app = _app()
    saved = []

    def save_settings(payload):
        saved.append(copy.deepcopy(payload))
        return copy.deepcopy(payload), Path("fixture-settings.json"), []

    monkeypatch.setattr(studio_ai_flow, "save_runtime_settings", save_settings)
    harness = _ProviderHarness()
    harness.runtime_settings = {
        "models": {
            "polish_transport": "openai_compatible",
            "polish_provider": "deepseek",
            "polish_base_url": AI_SERVICE_SPECS["deepseek"]["base_url"],
            "polish_model": "deepseek-chat",
        },
        "switches": {"unified_glm_processing": True},
    }
    harness.ai_provider = StudioComboBox()
    for service_id, spec in AI_SERVICE_SPECS.items():
        if "structured_output" in spec.get("capabilities", ()):
            harness.ai_provider.addItem(str(spec["label"]), service_id)
    harness.ai_provider.setCurrentIndex(harness.ai_provider.findData("deepseek"))
    harness.ai_model = StudioComboBox()
    harness.ai_model.setEditable(True)
    harness.ai_model.addItem("deepseek-chat", "deepseek-chat")
    harness.ai_provider_capabilities = QLabel()
    harness.ai_provider.currentIndexChanged.connect(harness._ai_design_provider_changed)
    harness.ai_model.currentTextChanged.connect(harness._ai_design_model_changed)

    harness.ai_provider.resize(260, 38)
    harness.ai_provider.show()
    QTest.mouseClick(
        harness.ai_provider,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        harness.ai_provider.rect().center(),
    )
    harness.ai_provider.showPopup()
    app.processEvents()
    assert harness.ai_provider.view().isVisible()
    gemini_index = harness.ai_provider.findData("gemini")
    popup_index = harness.ai_provider.model().index(gemini_index, 0)
    harness.ai_provider.view().scrollTo(popup_index)
    harness.ai_provider.view().setFocus(Qt.FocusReason.PopupFocusReason)
    QTest.qWait(20)
    popup_rect = harness.ai_provider.view().visualRect(popup_index)
    assert popup_rect.isValid() and not popup_rect.isEmpty()
    harness.ai_provider.view().setCurrentIndex(popup_index)
    QTest.keyClick(harness.ai_provider.view(), Qt.Key.Key_Return)
    QTest.qWait(20)
    app.processEvents()

    assert harness.ai_provider.currentData() == "gemini"
    assert harness.ai_model.currentText() == "gemini-3.7-flash-high"
    assert "支持图片" in harness.ai_provider_capabilities.text()
    assert saved
    models = harness.runtime_settings["models"]
    assert models["polish_provider"] == "gemini"
    assert models["group_provider"] == "gemini"
    assert models["polish_model"] == "gemini-3.7-flash-high"
    endpoint = endpoint_from_settings(harness.runtime_settings, "polish")
    assert endpoint["provider"] == "gemini"
    assert endpoint["model"] == "gemini-3.7-flash-high"
    assert endpoint["url"].endswith("/v1beta/openai/chat/completions")

    harness.ai_provider.hidePopup()
    harness.ai_provider.close()
    harness.ai_model.close()
