from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QPushButton

from twobyteasr.providers.ai_providers import AntigravityCLIProvider
from twobyteasr.rendering.ass_compiler import compile_ass
from twobyteasr.design.color_picker import ColorPickerWidget
from twobyteasr.timeline.studio_edit_sequence import HighlightCandidate
from twobyteasr.timeline.studio_edit_sequence import sequence_of, store_sequence
from twobyteasr.studio.studio_highlight_ui import HighlightAssistantPanel
from twobyteasr.acceptance.p64_runtime_audit import parse_matrix_sizes
from twobyteasr.projects.studio_project import (
    StudioMedia,
    SubtitleProject,
    SubtitleStyle,
    create_studio_outputs,
    load_project,
    save_project,
)
from twobyteasr.studio.studio_ui import FillEditorDialog, SubtitleStudioPage
from twobyteasr.caption_style.style_presets import StylePresetStore
from twobyteasr.caption_style.style_recipe import ASSRecipe, StyleRecipeValidationError
from twobyteasr.design.theme_manager import apply_application_theme
from twobyteasr.app.ui import AI_SERVICE_SPECS, EndpointEditor, ProviderConnectionTester
from twobyteasr.design.ui_theme import THEMES


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_required_services_protocols_and_endpoint_theme_contract():
    app = _app()
    required = {
        "deepseek", "openai", "gemini", "antigravity",
        "grok_account", "xai", "custom",
    }
    assert required <= set(AI_SERVICE_SPECS)
    editor = EndpointEditor("AI 服务", "#5B8E63", "polish", {"models": {}})
    assert {editor.service.itemData(i) for i in range(editor.service.count())} >= required
    assert [editor.protocol.itemData(i) for i in range(editor.protocol.count())] == [
        "auto", "responses", "chat_completions", "openai_compatible_chat",
    ]
    sheets = []
    for key, theme in THEMES.items():
        apply_application_theme(app=app, key=key)
        editor.refresh_theme_palette()
        sheet = editor.styleSheet()
        sheets.append(sheet)
        assert theme.surface in sheet
        assert theme.surface_input in sheet
        assert theme.text in sheet
    assert len(set(sheets)) == len(THEMES)
    editor.deleteLater()


def test_cli_detection_merges_models_and_preserves_explicit_selection(monkeypatch):
    _app()
    editor = EndpointEditor("AI 服务", "#5B8E63", "polish", {"models": {}})
    editor.service.setCurrentIndex(editor.service.findData("antigravity"))
    editor.model.setCurrentText("gemini-3.7-flash")
    editor._tester = SimpleNamespace(models=("gemini-2.5-pro", "gemini-2.5-flash"))

    editor._detect_finished(True, "OAuth Session 可用")

    assert [editor.model.itemText(i) for i in range(editor.model.count())] == [
        "gemini-3.7-flash", "gemini-2.5-pro", "gemini-2.5-flash",
    ]
    assert editor.model.currentText() == "gemini-3.7-flash"

    editor.model.setCurrentText("gemini-2.5-flash")
    editor._detect_finished(True, "OAuth Session 可用")
    assert editor.model.currentText() == "gemini-2.5-flash"

    editor._tester = SimpleNamespace(models=())
    editor._detect_finished(False, "CLI 已安装，尚未登录")
    assert editor.model.currentText() == "gemini-2.5-flash"
    editor.deleteLater()


def test_provider_connection_tester_retains_validated_models(monkeypatch):
    status = SimpleNamespace(
        available=True,
        authenticated=True,
        message="OAuth Session 可用",
        models=("model-a-2", "model-b-3"),
    )
    provider = SimpleNamespace(validate=lambda **_kwargs: status)
    monkeypatch.setattr("twobyteasr.providers.endpoint_editor_ui.provider_for_stage", lambda *_args: provider)
    tester = ProviderConnectionTester({"models": {}}, "polish")

    tester.run()

    assert tester.models == status.models


def test_antigravity_model_parser_accepts_tab_separated_display_names():
    output = """Fetching available models...
gemini-3.7-flash-high\tGemini 3.7 Flash (High)
claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)
gpt-oss-120b-medium\tGPT-OSS 120B (Medium)
"""

    assert AntigravityCLIProvider._parse_models(output) == (
        "gemini-3.7-flash-high",
        "claude-sonnet-4-6",
        "gpt-oss-120b-medium",
    )


def test_color_picker_square_and_gradient_controls_above_picker():
    app = _app()
    picker = ColorPickerWidget()
    assert picker.sv_square.hasHeightForWidth()
    assert picker.sv_square.heightForWidth(360) == 360
    assert picker.sv_square.minimumWidth() == picker.sv_square.minimumHeight() == 300
    picker.set_color(QColor("#34A853"))
    assert picker.color().name().upper() == "#34A853"

    dialog = FillEditorDialog({
        "type": "linear-gradient",
        "stops": [
            {"position": 0.0, "color": "#FFFFE45E"},
            {"position": 1.0, "color": "#FF20D9FF"},
        ],
        "angle": 30,
    })
    dialog.show()
    app.processEvents()
    assert dialog.gradient.geometry().top() < dialog.picker.geometry().top()
    assert dialog._stop_host.geometry().top() < dialog.picker.geometry().top()
    assert dialog.width() >= 620 and dialog.height() >= 620
    dialog.close()
    picker.deleteLater()


def test_clip_assistant_is_compact_and_candidate_actions_are_buttons():
    app = _app()
    panel = HighlightAssistantPanel()
    assert not panel.config_body.isHidden()
    assert panel.active_stage() == "settings"
    panel.resize(340, 302)
    panel.reload_candidates([
        HighlightCandidate(
            "p64", "弹幕爆点", 10_000, 40_000, 0.91,
            reason="弹幕密度上升并形成明确回应",
        )
    ])
    panel.show()
    app.processEvents()
    assert panel.active_stage() == "candidates"
    card = panel.results.itemWidget(panel.results.item(0))
    buttons = {button.text(): button for button in card.findChildren(QPushButton)}
    assert {"预览", "加入剪辑", "忽略", "详情"} <= set(buttons)
    assert buttons["加入剪辑"].objectName() == "studioPrimary"
    assert all(button.cursor().shape() == Qt.CursorShape.PointingHandCursor for button in buttons.values())
    assert all(card.rect().contains(button.geometry()) for button in buttons.values())
    assert panel.results.horizontalScrollBar().maximum() == 0
    assert panel.results.height() / panel.height() >= 0.55
    assert panel.bin.isHidden()
    assert panel.generate_row_host.isHidden()
    panel.close()


def test_candidate_add_updates_runtime_without_stale_analysis_result(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    candidate = HighlightCandidate(
        "candidate-runtime", "实机候选", 1_000, 31_000, 0.88,
        reason="验证加入剪辑的正式 Runtime mutation",
    )
    sequence = sequence_of(page.project)
    sequence.clip_candidates = [candidate]
    store_sequence(page.project, sequence)
    page.highlight_panel.set_project_status(page.project, "")

    page._set_candidate_status(candidate.id, "accepted")
    app.processEvents()

    updated = sequence_of(page.project)
    assert updated.clip_candidates[0].status == "accepted"
    assert page.highlight_panel.bin.count() == 1
    page.close_page()


def test_formal_runtime_matrix_parser_is_bounded_and_deduplicated():
    assert parse_matrix_sizes("1366x768, 1600x900, 1366x768") == [
        (1366, 768), (1600, 900),
    ]
    assert parse_matrix_sizes("bad,100x100,2560x1440") == [(2560, 1440)]


def test_ass_recipe_rejects_raw_code_and_compiles_safe_override():
    recipe = ASSRecipe.from_value({
        "enabled": True,
        "tags": [
            {"name": "bord", "value": 4},
            {"name": "c", "value": "#FFE45E"},
            {"name": "fad", "values": [120, 160]},
        ],
    })
    compiled = recipe.to_override()
    assert "\\bord4" in compiled and "\\fad(120,160)" in compiled
    with pytest.raises(StyleRecipeValidationError):
        ASSRecipe.from_value({"enabled": True, "tags": [{"name": "raw", "value": "{\\p1}"}]})

    project = SubtitleProject(media=StudioMedia(path="fixture.mp4", duration_ms=1000))
    project.style_recipes["safe"] = {
        "name": "safe", "engine": "native", "ass": recipe.to_dict(),
    }
    project.cues = []
    assert "[Events]" in compile_ass(project)


def test_style_library_persists_ai_recipe_favorite_and_delete(tmp_path):
    store = StylePresetStore(tmp_path)
    style = SubtitleStyle("ai-paper", "AI · 手写纸片", font_family="KaiTi", outline_width=4)
    recipe = {
        "name": "手写纸片", "engine": "native",
        "colors": {"fill": "#FFF6E8"},
        "ass": {"enabled": True, "tags": [{"name": "bord", "value": 4}]},
    }
    store.upsert(style, recipe, source="ai")
    assert store.load_recipes()[style.id]["ass"]["enabled"] is True
    assert store.load_metadata()[style.id]["source"] == "ai"
    store.set_favorite(style.id, True)
    assert store.load_metadata()[style.id]["favorite"] is True
    store.delete(style.id)
    assert style.id not in store.load_user()


def test_zero_cue_studio_has_recognition_and_import_actions(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page._create_blank_studio()
    page._refresh_cue_list_summary()
    app.processEvents()
    assert not page.cue_zero_state.isHidden()
    assert page.cue_table.isHidden()
    assert page.cue_recognize_button.text() == "识别字幕"
    assert page.cue_import_subtitles_button.text() == "导入 SRT / ASS"
    page.close_page()


def test_formal_size_cue_table_and_tool_tabs_do_not_overflow(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    page.resize(1400, 850)
    page.show()
    page._create_blank_studio()
    app.processEvents()
    page.upper_splitter.setSizes([280, 800, 320])
    app.processEvents()
    page._update_cue_table_layout()
    app.processEvents()
    assert page.video_empty_note.text().startswith("支持 MP4 / FLV")
    assert all(
        page.video_drop_zone.rect().contains(widget.geometry())
        for widget in (
            page.video_empty_icon,
            page.video_empty_label,
            page.video_empty_import,
            page.video_empty_note,
        )
    )
    assert page.cue_table.horizontalScrollBar().maximum() == 0
    assert page.cue_table.viewport().width() < 370
    assert page.cue_table.isColumnHidden(4)
    tabs = page.context_drawer.tabBar()
    assert tabs.tabRect(tabs.count() - 1).right() < tabs.width()
    for button in (*page.cue_filter_buttons.values(), page.review_entry_button):
        assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 16
    page.close_page()


def test_transform_overlay_is_single_non_native_child(monkeypatch, tmp_path):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    interaction = page.position_overlay
    assert interaction._top_level_canvas is False
    assert not interaction.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    assert not interaction.isWindow()
    assert not hasattr(page, "position_visual_overlay")
    page.close_page()
    app.processEvents()


def test_recognition_output_updates_the_same_project_without_losing_style(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    media = tmp_path / "source.flv"
    media.write_bytes(b"fixture")
    target = tmp_path / "project" / "same.2byteproj"
    original = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=60_000))
    original.styles.append(SubtitleStyle("custom", "Custom", font_family="KaiTi"))
    original.studio_state["tool_tab"] = 2
    original_id = original.project_id
    save_project(original, target)
    txt = tmp_path / "result.txt"
    srt = tmp_path / "result.srt"
    txt.write_text("识别结果", encoding="utf-8")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n识别结果\n", encoding="utf-8")
    cue = SimpleNamespace(
        cue_id="recognized-1", start=0.0, end=1.0, text="识别结果", speaker="S00",
    )
    result = create_studio_outputs(
        media, [cue], txt_path=str(txt), srt_path=str(srt),
        target_project_path=str(target),
    )
    loaded = load_project(target)
    assert result["project"] == str(target.resolve())
    assert loaded.project_id == original_id
    assert loaded.cues[0].text == "识别结果"
    assert any(style.id == "custom" for style in loaded.styles)
    assert loaded.studio_state["tool_tab"] == 2
