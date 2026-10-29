"""Codex's caption panel text goes through the UI catalogs (2026-10-25).

The 2026-10-24 caption-marks round wrote its panel labels, tooltips and
messages as fixed 繁體 text: a 简体 interface mixed both scripts and every
other language showed Chinese. They are now Chinese-source catalog keys.
"""
import json
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QToolButton

from tests.test_studio_style_controller import _finish, _page

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("en", "ja", "ko", "es", "de", "fr", "pt", "it", "ru", "zh-Hant")
KEYS = (
    "整组", "双语位置与对齐：先选择「整组」", "选中的 {count} 条字幕 · {layer}",
    "选中的 {count} 条字幕 · 混合值：{fields}", "描边色", "背景色", "纯文字",
    "Markdown：**粗体**、*斜体*、==重点==（兔白扩展）；\\ 可转义，`文字` 原样输入。", "重点",
    "译文按自身词界估算分配，尚待核对；无法分配时保留整组译文。", "文字修改后已移除无法可靠对应的局部标记",
    "局部文字颜色", "在模板中显示姓名", "用于校对／替换", "用于字幕视觉强调",
    "下一条待审核 (W)", "下一条待审核 (A)", "上一条待审核 (S)", "上一条待审核 (D)",
    "双语字幕的位置与缩放请选择整组后调整", "不能在 emoji 或组合字符中间切分", "局部样式", "语言层样式",
    # Existing keys the panel now reuses.
    "原文", "译文", "字体", "字号", "颜色", "粗体", "斜体", "下划线", "描边", "阴影", "背景", "对齐", "字距", "清除",
)


def _fields(text):
    return sorted(re.findall(r"\{(\w+)", text))


def test_every_caption_panel_string_has_all_languages():
    for language in LANGUAGES:
        table = json.loads((ROOT / "twobyteasr" / "locales" / f"{language}.json").read_text("utf-8"))
        for key in KEYS:
            assert key in table, (language, key)
            assert _fields(table[key]) == _fields(key), (language, key)


def test_panel_and_text_tools_follow_the_interface_language(tmp_path, monkeypatch):
    monkeypatch.setattr("twobyteasr.i18n._CURRENT_LANGUAGE_CACHE", "en")
    app, page = _page(tmp_path, monkeypatch)
    try:
        from twobyteasr.i18n import apply_ui_language
        page.show()
        apply_ui_language(page, "en")
        page._load_style_inspector()
        app.processEvents()
        assert [page.style_layer.itemText(i) for i in range(3)] == ["Original", "Translated text", "Whole group"]
        tools = page.original_text_tools
        assert tools.mode.itemText(0) == "Plain text" and tools.mode.itemText(1) == "Markdown"
        assert tools.mode.toolTip().startswith("Markdown: **bold**")
        assert {"Highlight", "Color", "Clear"} <= {button.text() for button in tools.findChildren(QToolButton)}
        assert page.style_scope_summary.text() == "Selected subtitles: 1 · Original"
        page.style_layer.setCurrentIndex(2)
        app.processEvents()
        assert page.style_scope_summary.text() == "Selected subtitles: 1 · Whole group"
        # Back to Chinese: the same widgets show the Chinese source again.
        monkeypatch.setattr("twobyteasr.i18n._CURRENT_LANGUAGE_CACHE", "zh")
        apply_ui_language(page, "zh")
        app.processEvents()
        assert [page.style_layer.itemText(i) for i in range(3)] == ["原文", "译文", "整组"]
        assert page.style_scope_summary.text() == "选中的 1 条字幕 · 整组"
        assert tools.mode.itemText(0) == "纯文字"
    finally:
        _finish(page)


def test_text_mode_box_is_not_pinned_under_the_format_buttons(tmp_path, monkeypatch):
    """The real app pins combos to 180 px; this row is narrow (2026-10-25 real-window grab)."""
    monkeypatch.setattr("twobyteasr.i18n._CURRENT_LANGUAGE_CACHE", "en")
    app, page = _page(tmp_path, monkeypatch)
    try:
        from twobyteasr.design.presentation import prepare_controls
        from twobyteasr.i18n import apply_ui_language
        prepare_controls(page)
        page.resize(1440, 900)
        page.show()
        apply_ui_language(page, "en")
        page.context_drawer.setCurrentIndex(1)
        app.processEvents()
        tools = page.original_text_tools
        tools.resize(358, tools.height())
        tools.layout().activate()
        row = [tools.mode, *sorted(tools.findChildren(QToolButton), key=lambda button: button.x())]
        assert tools.mode.minimumWidth() < 180
        assert all(a.geometry().right() < b.geometry().left() for a, b in zip(row, row[1:]))
        assert row[-1].geometry().right() < tools.width()
    finally:
        _finish(page)


def test_refused_split_reads_in_the_interface_language(monkeypatch):
    monkeypatch.setattr("twobyteasr.i18n._CURRENT_LANGUAGE_CACHE", "en")
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.timeline.studio_commands import split_cue_command
    import pytest
    project = SubtitleProject(media=StudioMedia("", duration_ms=2000),
                              cues=[StudioCue("a", 0, 2000, "好👍🏽了")])
    project.validate()
    with pytest.raises(ValueError) as error:  # between 👍 and its skin tone
        split_cue_command(project, "a", 1000, "好👍", "🏽了")
    assert str(error.value) == "Cannot split inside an emoji or a combined character"
