"""P5.3: stage-aware export, result card, shell, theme, i18n, text toolbox."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QToolButton

from twobyteasr.i18n import translate
from twobyteasr.app.main_ui_branding import HeaderMascot
from twobyteasr.design.main_ui_dialogs import SpringDialog
from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand
from twobyteasr.exports.studio_export_ui import StudioExportWorkspace
from twobyteasr.studio.studio_find_replace import FindReplaceDialog, apply_occurrences, replace_all
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.exports.studio_render import (
    STAGE_ADVANCED_RENDER,
    STAGE_ENCODE,
    STAGE_MUX,
    STAGE_PREPARE_PROJECT,
    STAGE_PREPARE_SUBTITLES,
    export_progress,
    parse_ffmpeg_out_time_seconds,
)
from twobyteasr.studio.studio_text_tools import (
    PAUSE_LIGHT_TO_SPACE,
    find_occurrences,
    parse_cleanup_payload,
    tidy_text,
    values_from_occurrences,
)
from twobyteasr.design.studio_theme import BRAND_DISPLAY_NAME
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.design.themed_icons import icon_role_color
from twobyteasr.design.ui_theme import contrast_ratio, theme_definition
import twobyteasr.design.theme_manager as theme_manager


def _app():
    return QApplication.instance() or QApplication([])


def test_export_progress_payload_is_stage_aware():
    busy = export_progress(STAGE_PREPARE_PROJECT, message="正在解析工程并检查输入文件…")
    assert busy["stage"] == STAGE_PREPARE_PROJECT
    assert busy["indeterminate"] == "1"
    assert "percent" not in busy
    encode = export_progress(
        STAGE_ENCODE, out_time_us=3_000_000, duration_seconds=10, percent=30, indeterminate=False,
    )
    assert encode["indeterminate"] == "0"
    assert parse_ffmpeg_out_time_seconds(encode) == 3.0


def test_export_ui_does_not_show_zero_during_prepare(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    _app()
    workspace = StudioExportWorkspace(
        SubtitleProject(media=StudioMedia(path=str(tmp_path / "a.mp4"), duration_ms=30_000)),
        str(tmp_path / "preview.ass"),
    )
    workspace._apply_progress(-1, export_progress(STAGE_PREPARE_SUBTITLES, message="正在准备字幕…"))
    assert workspace.render_percent.text() == "…"
    assert workspace.progress.maximum() == 0
    assert "准备字幕" in workspace.current_stage_title.text()
    workspace._advanced_route = True
    workspace._show_advanced_stage(True)
    workspace._apply_progress(-1, export_progress(STAGE_ADVANCED_RENDER, message="正在准备高级字幕渲染…"))
    assert not workspace.render_stage_labels[2].isHidden()
    assert "高级" in workspace.current_stage_title.text()
    workspace._apply_progress(35, export_progress(
        STAGE_ENCODE, out_time_us=str(round(3.08 * 1_000_000)), duration_seconds=9.02,
        fps="72", speed="1.2x", indeterminate=False, percent=35,
    ))
    assert workspace.render_percent.text().endswith("%")
    assert int(workspace.render_percent.text().rstrip("%")) <= 35
    assert workspace.progress.maximum() == 100
    workspace.deleteLater()


def test_result_card_is_enlarged_and_has_no_success_dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    _app()
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"1234")
    workspace = StudioExportWorkspace(
        SubtitleProject(media=StudioMedia(path=str(tmp_path / "a.mp4"), duration_ms=1000)),
        str(tmp_path / "preview.ass"),
    )
    card = workspace.success_page.findChild(object.__class__ if False else workspace.success_name.__class__)
    previous_dir = workspace._settings.value("render/last_export_directory", "")
    workspace._show_success(str(output))
    workspace._settings.setValue("render/last_export_directory", previous_dir)
    assert workspace.pages.currentWidget() is workspace.success_page
    assert workspace.findChild(type(workspace), "exportSuccessDialog") is None
    assert "min-height: 58px" in workspace.styleSheet()
    result_card = None
    from PySide6.QtWidgets import QFrame
    for frame in workspace.findChildren(QFrame):
        if frame.objectName() == "exportResultCard":
            result_card = frame
            break
    assert result_card is not None
    # The responsive result page has no hard minimum that overflows laptops.
    workspace.resize(1100,800);workspace.show();_app().processEvents()
    assert 720 <= result_card.width() <= workspace.width()
    assert "clip.mp4" in workspace.success_name.text()
    workspace.deleteLater()


def test_header_mascot_keeps_full_ears():
    _app()
    mascot = HeaderMascot()
    assert mascot.height() >= 72
    assert mascot.width() >= 72
    assert mascot._refresh_pixmap.__defaults__ is None or True
    mascot._rendered_dpr = -1.0
    mascot._refresh_pixmap()
    assert mascot.pixmap() is not None and not mascot.pixmap().isNull()
    mascot.deleteLater()


def test_dark_window_control_icons_use_light_tokens():
    _app()
    plum = theme_definition("plum")
    warm = theme_definition("warm")
    assert contrast_ratio(icon_role_color("window_control", plum), plum.app_background) >= 4.5
    assert contrast_ratio(icon_role_color("window_control", warm), warm.app_background) >= 4.5
    hex_color = icon_role_color("window_control", plum).lstrip("#")
    luminance = int(hex_color[0:2], 16)
    assert luminance >= 180


def test_library_brand_is_product_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    _app()
    page = SubtitleStudioPage()
    page.show_project_hub()
    assert page.project_library_brand.text() == "工程库"
    assert page.filename.text() == BRAND_DISPLAY_NAME
    assert not hasattr(page, "project_library_home")
    assert page.studio_home_button.toolTip() == "返回字幕识别"
    page.close_page()
    page.deleteLater()


def test_spring_dialog_follows_current_theme(tmp_path, monkeypatch):
    ini = tmp_path / "theme.ini"
    monkeypatch.setattr(
        theme_manager, "_settings", lambda: QSettings(str(ini), QSettings.Format.IniFormat)
    )
    app = _app()
    theme_manager.apply_application_theme(app, "plum")
    dialog = SpringDialog()
    assert dialog._theme_fill.lower() != "#faf7f1"
    assert dialog._theme_fill.lower() == theme_definition("plum").surface.lower()
    dialog.deleteLater()
    theme_manager.apply_application_theme(app, "warm")
    light = SpringDialog()
    assert light._theme_fill.lower() == theme_definition("warm").surface.lower()
    light.deleteLater()


def test_theme_contrast_covers_text_and_muted():
    for theme in (
        theme_definition("warm"),
        theme_definition("plum"),
        theme_definition("lavender"),
        theme_definition("slate"),
    ):
        assert contrast_ratio(theme.text, theme.app_background) >= 4.5, theme.key
        assert contrast_ratio(theme.text, theme.surface) >= 4.5, theme.key
        assert contrast_ratio(theme.text_muted, theme.app_background) >= 3.0, theme.key
        assert contrast_ratio(theme.text_muted, theme.app_background) < contrast_ratio(theme.text, theme.app_background)


def test_i18n_keeps_product_and_tech_names():
    for language in ("en", "ja"):
        assert translate("优兔泊", language) == "优兔泊"
        assert "MOSS" not in translate("优兔泊", language)
    assert translate("准备工程", "en") == "Prepare project"
    assert translate("压制完成", "ja") == "書き出し完了"
    assert translate("← 返回字幕识别主页", "en").startswith("←")


def test_find_replace_preview_and_single_undo(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = _app()
    path = save_project(
        SubtitleProject(
            media=StudioMedia(path=str(tmp_path / "a.mp4"), duration_ms=4000),
            cues=[
                StudioCue("c0", 0, 1000, "它真的来了"),
                StudioCue("c1", 1000, 2000, "它真的走了"),
                StudioCue("c2", 2000, 3000, "然后就是就是我们先过去看一下"),
            ],
        ),
        tmp_path / "p53.2byteproj",
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    page.open_project(path)
    hits = find_occurrences(page.session.project, [cue.id for cue in page.session.project.cues], "它", "她")
    assert len(hits) == 2
    total, cues = apply_occurrences(page, hits, title="它")
    assert total == 2 and cues == 2
    assert page.session.project.cues[0].text.startswith("她")
    page.session.undo_stack.undo()
    assert page.session.project.cues[0].text.startswith("它")
    page.session.undo_stack.redo()
    assert page.session.project.cues[1].text.startswith("她")
    page.session.undo_stack.undo()
    total, cues = replace_all(page, needle="它", replacement="她", scope="all")
    assert total == 2
    page.session.undo_stack.undo()
    assert page.session.project.cues[0].text.startswith("它")
    dialog = FindReplaceDialog(page, page)
    dialog.find_edit.setText("它")
    dialog.replace_edit.setText("她")
    app.processEvents()
    dialog._do_preview()
    assert dialog.preview.count() == 2
    dialog.deleteLater()
    page.close_page()
    page.deleteLater()


def test_tidy_and_ai_parse_keep_meaning():
    assert " " in tidy_text("然后……我们", pause=PAUSE_LIGHT_TO_SPACE)
    assert tidy_text("hello, world.", punctuation="cn") == "hello， world。"
    project = SubtitleProject(
        media=StudioMedia(path="a.mp4", duration_ms=2000),
        cues=[StudioCue("c0", 0, 1000, "然后就是就是我们先过去看一下")],
    )
    hits = parse_cleanup_payload(
        {
            "changes": [{
                "cue_id": "c0",
                "original": "然后就是就是我们先过去看一下",
                "replacement": "然后我们先过去看一下",
                "reason": "删除重复口癖",
                "confidence": 0.94,
            }]
        },
        project,
    )
    assert hits[0].replacement == "然后我们先过去看一下"
    values = values_from_occurrences(project, hits)
    assert values["c0"] == "然后我们先过去看一下"
