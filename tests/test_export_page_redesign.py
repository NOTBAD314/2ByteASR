"""Export page design A (2026-10-23): the same controls, regrouped and dressed."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import MediaAsset, StudioMedia, SubtitleProject


@pytest.fixture
def make(tmp_path, monkeypatch):
    from twobyteasr.exports import studio_export_ui
    app = QApplication.instance() or QApplication([])
    ini = lambda *a: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(studio_export_ui, "QSettings", ini)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    made = []

    def create(project=None):
        project = project or SubtitleProject(media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=60_000,
                                                               width=1920, height=1080))
        window = studio_export_ui.StudioExportWorkspace(project, str(tmp_path / "preview.ass"))
        window.resize(1600, 830)
        window.show()
        app.processEvents()
        made.append(window)
        return window
    yield app, create
    for window in made:
        window.close()
        window.deleteLater()
    app.processEvents()


def test_preset_chips_follow_the_preset_dropdown(make):
    app, create = make
    window = create()
    chips = window.preset_chips
    assert [b.text() for b in chips.buttons] == [window.preset.itemText(i) for i in range(window.preset.count())]
    high = window.preset.findData("high")
    chips.buttons[high].click()
    assert window.preset.currentData() == "high" and chips.buttons[high].isChecked()
    # A hand-made encoding change moves the dropdown with its signals blocked.
    window.bitrate.setValue(9000)
    custom = window.preset.findData("custom")
    assert window.preset.currentData() == "custom" and chips.buttons[custom].isChecked()
    assert chips.trailing is window.preset_menu_button


def test_advanced_fold_is_the_old_toggle_and_fields_hide_with_their_frames(make):
    app, create = make
    window = create()
    assert window.advanced_panel.isHidden()
    window.quality.setCurrentIndex(window.quality.findData("custom"))
    app.processEvents()
    assert window.advanced_card.is_expanded() and not window.advanced_panel.isHidden()
    window.rate_control.setCurrentIndex(window.rate_control.findData("limited"))
    app.processEvents()
    assert window.quality_value._caption_host.isHidden()
    assert not window.bitrate._caption_host.isHidden() and not window.max_bitrate._caption_host.isHidden()
    assert window.rate_control_choice.buttons[window.rate_control.currentIndex()].isChecked()
    window.audio.setCurrentIndex(window.audio.findData("aac"))
    assert not window.audio_bitrate._caption_host.isHidden()
    window.resolution.setCurrentIndex(window.resolution.count() - 1)  # 自定义
    assert not window.custom_resolution_host.isHidden()
    assert "kbps" in window.advanced_card.summary.text()


def test_range_lives_on_the_preview_and_summary_reads_as_pills(make):
    app, create = make
    window = create()
    assert window.export_range_choice.buttons[0].isChecked()
    window.preview_scrub.setValue(10_000)
    window._set_in()
    window.preview_scrub.setValue(40_000)
    window._set_out()
    app.processEvents()
    assert window.export_range.currentData() == "in_out"
    assert window.export_range_choice.buttons[1].isChecked()
    assert window.preview_scrub._range_start == 10_000 and window.preview_scrub._range_end == 40_000
    # The bar's duration line and 清除范围 sit under the points, outside the bar.
    status = window.project_range_bar.status
    assert not window.project_range_bar.isAncestorOf(status) and "00:00:30" in status.text()
    pills = [window.summary_chips.itemAt(i).widget() for i in range(window.summary_chips.count())]
    texts = [pill.text() for pill in pills if pill.isVisible()]
    assert "1920 × 1080" in texts and any("00:30" in text for text in texts)
    assert window.renderer_badge.text() == "无字幕处理"


def test_subtitle_fold_opens_when_its_header_button_reports(make):
    app, create = make
    window = create()
    assert not window.subtitle_card.is_expanded()
    assert window.subtitle_card.summary.text().startswith("SRT")
    for check in window.subtitle_format_checks.values():
        check.setChecked(False)
    window.subtitle_export_button.click()
    app.processEvents()
    assert window.subtitle_card.is_expanded()
    assert window.subtitle_export_status.text() == "至少选择一种字幕格式"
    window.subtitle_speaker_modes["both"].setChecked(True)
    assert "两者" in window.subtitle_card.summary.text()
    # Left open, it opens again next time; folded, it stays folded.
    assert create().subtitle_card.is_expanded()
    window.subtitle_card.set_expanded(False)
    assert not create().subtitle_card.is_expanded()


def test_audio_only_source_says_the_picture_is_black(make, tmp_path):
    app, create = make
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "talk.mp3"), duration_ms=30_000),
                              media_pool=[MediaAsset("a1", str(tmp_path / "talk.mp3"),
                                                     video_metadata={"has_video": False})])
    window = create(project)
    assert window.source_pill.isVisible() and window.source_pill.text() == "源是音频 · 黑色画面"
    assert not create().source_pill.isVisible()


def test_file_name_well_shows_prefix_name_suffix_and_extension(make):
    app, create = make
    window = create()
    window.filename_prefix.setEditText("大饭包")
    window.extension.setCurrentIndex(window.extension.findData("mkv"))
    app.processEvents()
    assert window.filename_extension.text() == ".mkv"
    assert window.complete_name_preview.text() == "大饭包video.mkv"
    assert window.filename_prefix.property("empty") is False and window.filename_suffix.property("empty") is True
    assert window.extension_choice.buttons[window.extension.currentIndex()].isChecked()
