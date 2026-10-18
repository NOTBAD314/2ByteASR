"""2026-10-18 export dialogs: format cards, segmented choices, file preview, done page."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr import studio_export_ui, subtitle_export_widgets
from twobyteasr.completion_export import CompletionExportDialog
from twobyteasr.studio_export_ui import SubtitleExportDialog
from twobyteasr.studio_subtitle_export import SubtitleExportOptions, planned_subtitle_files
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject

APP = QApplication.instance() or QApplication([])


def _project(tmp_path, *, hidden=False):
    media = tmp_path / "艾尔登法环 DLC 直播.mp4"
    media.write_bytes(b"fixture")
    return SubtitleProject(
        media=StudioMedia(str(media), duration_ms=10_000),
        speakers=[StudioSpeaker("S01", "主播 小乔"), StudioSpeaker("S02", "阿凯"),
                  StudioSpeaker("GAME_BACKGROUND", "游戏背景声", hidden=hidden)],
        cues=[StudioCue("a", 0, 1000, "大家好", speaker_id="S01"),
              StudioCue("b", 1200, 2000, "宝箱还没开", speaker_id="S02"),
              StudioCue("c", 2500, 3000, "获得黄金种子", speaker_id="GAME_BACKGROUND")],
    )


def test_planned_files_follow_export_naming_and_mark_existing(tmp_path):
    project = _project(tmp_path, hidden=True)
    (tmp_path / "直播.srt").write_text("old", encoding="utf-8")
    both = planned_subtitle_files(project, tmp_path, "直播", SubtitleExportOptions(frozenset({"srt", "ass"}), "both"))
    assert [(item.name, item.status) for item in both] == [
        ("直播.ass", "new"), ("直播.srt", "replace"),
        ("直播_主播_小乔.ass", "new"), ("直播_主播_小乔.srt", "new"),
        ("直播_阿凯.ass", "new"), ("直播_阿凯.srt", "new")]
    assert not any("游戏背景声" in item.name for item in both)
    names_only = planned_subtitle_files(project, None, "直播", SubtitleExportOptions(frozenset({"txt"}), "combined"))
    assert [item.name for item in names_only] == ["直播.txt"]


def test_studio_dialog_cards_preview_and_remembered_choices(tmp_path):
    project = _project(tmp_path)
    dialog = SubtitleExportDialog(project, tmp_path / "work" / "p.2byteproj", export_on_accept=True)
    dialog.show()
    assert dialog.format_checks["srt"].isChecked() and not dialog.format_checks["ass"].isChecked()
    assert dialog.file_list.names() == ["艾尔登法环 DLC 直播.srt"]
    assert dialog.export_button.text() == "导出 1 个文件"
    dialog.format_checks["ass"].click()
    dialog.speaker_modes["per_speaker"].click()
    assert len(dialog.file_list.names()) == 6
    assert dialog.speaker_hint.text() == "每人一份：主播 小乔、阿凯、游戏背景声"
    assert dialog.path_row.path_label.path() == str(tmp_path)
    assert dialog.path_row.open_button.isEnabled() and not dialog.path_row.change_button.isVisible()
    dialog.destination_modes["project"].click()
    assert dialog.path_row.path_label.path() == str((tmp_path / "work" / "exports").resolve())
    assert not dialog.path_row.open_button.isEnabled()
    dialog.format_checks["srt"].click()
    dialog.format_checks["ass"].click()
    assert not dialog.export_button.isEnabled() and dialog.file_list.header.text() == "至少选一种格式"
    dialog.format_checks["srt"].click()
    dialog._accept()
    dialog.close()
    again = SubtitleExportDialog(project, tmp_path / "work" / "p.2byteproj")
    assert again.selected_speaker_mode() == "per_speaker" and again._selected_destination() == "project"
    assert again.selected_options().formats == frozenset({"srt"})
    again.deleteLater()


def test_custom_folder_cancel_keeps_previous_choice(tmp_path, monkeypatch):
    project = _project(tmp_path)
    dialog = SubtitleExportDialog(project)
    dialog.destination_modes["source"].click()
    dialog.custom_directory.setText("")
    monkeypatch.setattr(studio_export_ui.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    dialog.destination_modes["custom"].click()
    assert dialog._selected_destination() == "source"
    chosen = tmp_path / "out"
    chosen.mkdir()
    monkeypatch.setattr(studio_export_ui.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(chosen)))
    dialog.destination_modes["custom"].click()
    assert dialog._selected_destination() == "custom" and dialog.path_row.path_label.path() == str(chosen)
    assert dialog.path_row.change_button.isVisibleTo(dialog)
    dialog.deleteLater()


def test_export_runs_in_dialog_and_done_page_opens_folder_and_copies(tmp_path, monkeypatch):
    project = _project(tmp_path)
    dialog = SubtitleExportDialog(project, export_on_accept=True)
    dialog.show()
    dialog.destination_modes["source"].click()
    for name, card in dialog.format_checks.items():
        card.setChecked(name in {"srt", "txt"})
    dialog.speaker_modes["combined"].click()
    (tmp_path / "艾尔登法环 DLC 直播.srt").write_text("old", encoding="utf-8")
    dialog._refresh_preview()
    assert dialog.file_list.rows[0].text().endswith("已存在，会替换")
    dialog.export_button.click()
    assert dialog.pages.currentWidget() is dialog.done_page
    assert sorted(item.path.name for item in dialog.artifacts) == ["艾尔登法环 DLC 直播.srt", "艾尔登法环 DLC 直播.txt"]
    assert "大家好" in (tmp_path / "艾尔登法环 DLC 直播.srt").read_text(encoding="utf-8")
    assert dialog.done_title.text() == "已导出并检查 2 个文件"
    assert dialog.done_path.path_label.path() == str(tmp_path)
    dialog.copy_paths_button.click()
    assert QApplication.clipboard().text().splitlines() == [str(item.path.resolve()) for item in dialog.artifacts]
    opened = []
    monkeypatch.setattr(subtitle_export_widgets, "open_folder", lambda path: opened.append(Path(path)) or True)
    dialog.open_folder_button.click()
    assert opened == [tmp_path] and dialog.result() == 1


def test_export_failure_stays_on_choices(tmp_path, monkeypatch):
    project = _project(tmp_path)
    dialog = SubtitleExportDialog(project, export_on_accept=True)
    dialog.show()
    def fail(*_args, **_kwargs):
        raise OSError("磁盘已满")
    monkeypatch.setattr(studio_export_ui, "export_subtitle_artifacts", fail)
    dialog.export_button.click()
    assert dialog.pages.currentWidget() is dialog.setup_page and "磁盘已满" in dialog.warning.text()
    assert dialog.export_button.isEnabled()
    dialog.close()


def test_translations_add_language_layers(tmp_path):
    project = _project(tmp_path)
    project.generation_metadata["translations"] = {"a": "Hello"}
    dialog = SubtitleExportDialog(project, export_on_accept=True)
    dialog.show()
    assert dialog.language_row.isVisible()
    for name, card in dialog.format_checks.items():
        card.setChecked(name == "srt")
    dialog.speaker_modes["combined"].click()
    dialog._refresh_preview()
    names = dialog.file_list.names()
    assert len(names) == 3 and any(name.endswith(".bilingual.srt") for name in names)
    for button in dialog.language_checks.values():
        button.setChecked(False)
    assert not dialog.export_button.isEnabled() and dialog.file_list.header.text() == "SRT 至少选一种语言"
    dialog.close()


def test_completion_dialog_chips_preview_and_export(tmp_path, monkeypatch):
    from twobyteasr import completion_export
    project = _project(tmp_path)
    dialog = CompletionExportDialog(project, "直播.42250669220.456-467")
    dialog.show()
    assert dialog.name.text() == "直播.42250669220.456-467"
    assert dialog.speakers.count() == 3 and dialog.all_speakers.isChecked()
    assert dialog.file_list.names() == ["直播.42250669220.456-467.srt"]
    dialog.speakers.item(2).setCheckState(completion_export.Qt.CheckState.Unchecked)
    assert not dialog.all_speakers.isChecked()
    dialog.mode.setCurrentIndex(dialog.mode.findData("per_speaker"))
    assert dialog.file_list.names() == ["直播.42250669220.456-467_主播_小乔.srt", "直播.42250669220.456-467_阿凯.srt"]
    out = tmp_path / "chosen"
    out.mkdir()
    monkeypatch.setattr(completion_export.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out)))
    dialog.export_button.click()
    assert dialog.result() == 1
    assert sorted(item.path.name for item in dialog.artifacts) == [
        "直播.42250669220.456-467_主播_小乔.srt", "直播.42250669220.456-467_阿凯.srt"]
    dialog.all_speakers.setChecked(True)
    assert dialog.speakers.item(2).checkState() == completion_export.Qt.CheckState.Checked
    dialog.all_speakers.setChecked(False)
    assert not dialog.export_button.isEnabled()
    dialog.deleteLater()
