import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.exports.studio_export_ui import ExportTarget, StudioExportWorkspace
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
from twobyteasr.studio.studio_ui import SubtitleStudioPage


def test_export_target_is_single_source_of_truth(tmp_path):
    target = ExportTarget(tmp_path, "测试视频_字幕版", "mp4")
    assert target.full_path == tmp_path / "测试视频_字幕版.mp4"
    complete_name = ExportTarget(tmp_path, "测试视频_字幕版.mp4", "mp4")
    assert complete_name.full_path == tmp_path / "测试视频_字幕版.mp4"


def test_affixes_confirm_on_close_without_changing_video_preferences(tmp_path, monkeypatch):
    from PySide6 import QtCore
    from twobyteasr.exports import studio_export_ui
    import json
    app=QApplication.instance() or QApplication([])
    settings=QtCore.QSettings(str(tmp_path/'preferences.ini'),QtCore.QSettings.IniFormat)
    monkeypatch.setattr(studio_export_ui,'QSettings',lambda *args:settings)
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    first=SubtitleProject(media=StudioMedia(path='first.mp4',duration_ms=1000))
    ui=StudioExportWorkspace(first,str(tmp_path/'preview.ass'))
    app.processEvents()
    ui.filename_prefix.setText('[NOTBAD]'); ui.bitrate.setValue(14000)
    ui._confirm_export_preferences()
    confirmed=settings.value('render/preferences_v1')
    ui.filename_prefix.setText('取消内容'); ui.bitrate.setValue(999)
    ui.close(); ui.deleteLater(); app.processEvents()
    assert settings.value('render/preferences_v1')==confirmed
    second=SubtitleProject(media=StudioMedia(path='second.mp4',duration_ms=1000))
    ui=StudioExportWorkspace(second,str(tmp_path/'preview.ass'))
    app.processEvents()
    assert ui.filename_prefix.text()=='取消内容' and ui.bitrate.value()==14000
    assert ui.export_target().full_path.name=='取消内容second.mp4'
    ui.extension.setCurrentIndex(ui.extension.findData('mkv'))
    assert ui.export_target().full_path.suffix=='.mkv'
    assert json.loads(confirmed)['fps']==0
    ui.deleteLater(); app.processEvents()


def test_export_workspace_uses_project_exports_when_last_directory_missing(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from PySide6.QtCore import QSettings
    settings = QSettings("2ByteASR", "2ByteASR")
    settings.setValue("render/last_export_directory", str(tmp_path / "missing-export-dir"))
    settings.sync()
    project_path = tmp_path / "project" / "demo.2byteproj"
    project_path.parent.mkdir()
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=1000))
    workspace = StudioExportWorkspace(project, str(tmp_path / "preview.ass"), project_path=project_path)
    assert workspace.directory.text() == str(project_path.parent / "exports")
    assert workspace.export_target().full_path.name.endswith(".mp4")
    workspace.deleteLater()
    app.processEvents()


def test_studio_render_action_enters_embedded_export_workspace(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=1000))
    project_path = save_project(project, tmp_path / "demo.2byteproj")
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(project_path)
    preview_path = tmp_path / "preview.ass"
    preview_path.write_text("[Script Info]\n", encoding="utf-8")
    page._preview_path = preview_path
    page._open_render_dialog()
    page.show()
    app.processEvents()
    assert type(page.export_workspace).__name__ == "StudioExportWorkspace"
    assert not page.workspace_splitter.isVisible()
    assert page.export_workspace.isVisible()
    page._close_export_workspace()
    page.deleteLater()
    app.processEvents()


def test_export_workspace_21_exposes_range_rich_settings_and_state_pages(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=235_000, width=1920, height=1080)
    )
    workspace = StudioExportWorkspace(project, str(tmp_path / "preview.ass"))
    assert workspace.preset.count() >= 5
    assert workspace.quality.count() >= 4
    assert workspace.resolution.count() >= 4
    assert workspace.fps.count() >= 4
    assert workspace.audio.findData("none") >= 0
    assert workspace.advanced_panel.isHidden()
    workspace.advanced_button.click()
    assert not workspace.advanced_panel.isHidden()
    workspace.preview_scrub.setValue(14_320)
    workspace._set_in()
    workspace.preview_scrub.setValue(228_200)
    workspace._set_out()
    assert workspace.export_range.currentData() == "in_out"
    job = workspace._job(tmp_path / "out.mp4")
    assert job.start_seconds == 14.32
    assert job.duration_seconds == 213.88
    previous_dir = workspace._settings.value("render/last_export_directory", "")
    workspace._show_success(str(tmp_path / "out.mp4"))
    workspace._settings.setValue("render/last_export_directory", previous_dir)
    workspace._settings.sync()
    assert workspace.pages.currentWidget() is workspace.success_page
    assert not workspace.setup_page.isVisible()
    workspace.deleteLater()
    app.processEvents()


def test_export_workspace_compact_layout_scrolls_without_cta_overlap(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=8_000, width=1280, height=720)
    )
    workspace = StudioExportWorkspace(project, str(tmp_path / "preview.ass"))
    workspace.resize(924, 392)
    workspace.show()
    app.processEvents()

    assert workspace._compact_layout is True
    assert workspace.settings_scroll.minimumWidth() == 360
    assert workspace.preview_host.minimumWidth() == 360
    assert workspace.preview_scroll.verticalScrollBar().maximum() > 0
    summary = workspace.summary.parentWidget()
    summary_rect = summary.geometry().translated(summary.parentWidget().mapTo(workspace, summary.parentWidget().rect().topLeft()))
    viewport = workspace.preview_scroll.viewport()
    viewport_rect = viewport.rect().translated(viewport.mapTo(workspace, viewport.rect().topLeft()))
    # The summary scrolls inside its viewport; export actions now stay in the
    # fixed footer. Off-viewport geometry is clipped and cannot cover them.
    summary_rect = summary_rect.intersected(viewport_rect)
    for button in (workspace.queue_button, workspace.export_button):
        button_rect = button.geometry().translated(button.parentWidget().mapTo(workspace, button.parentWidget().rect().topLeft()))
        assert not summary_rect.intersects(button_rect)
        assert workspace.rect().contains(button_rect)
        assert button_rect.top() > viewport_rect.bottom()

    workspace.deleteLater()
    app.processEvents()


def test_export_workspace_can_export_only_srt_with_combined_and_per_speaker_files(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=5_000),
        speakers=[StudioSpeaker("host", "主播"), StudioSpeaker("guest", "嘉宾")],
        cues=[
            StudioCue("a", 0, 1_000, "开场", speaker_id="host"),
            StudioCue("b", 1_500, 2_500, "回应", speaker_id="guest"),
        ],
    )
    workspace = StudioExportWorkspace(project, str(tmp_path / "preview.ass"))
    export_directory = tmp_path / "exports"
    workspace.subtitle_custom_directory.setText(str(export_directory))
    workspace.subtitle_destination_modes["custom"].setChecked(True)
    workspace.filename.setText("creator-cut")
    workspace.subtitle_speaker_modes["both"].setChecked(True)
    workspace.subtitle_export_button.click()

    assert sorted(path.name for path in export_directory.glob("*")) == [
        "creator-cut.srt",
        "creator-cut_主播.srt",
        "creator-cut_嘉宾.srt",
    ]
    assert "已导出并验证 3 个文件" in workspace.subtitle_export_status.text()
    workspace.deleteLater()
    app.processEvents()


def test_p74c_subtitle_export_destination_modes(tmp_path, monkeypatch):
    from twobyteasr.exports.studio_export_ui import resolve_subtitle_export_destination

    media_dir = tmp_path / "source"
    media_dir.mkdir()
    media = media_dir / "video.mp4"
    media.write_bytes(b"x")
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=1000))
    project_path = tmp_path / "proj" / "demo.2byteproj"
    project_path.parent.mkdir()
    custom = tmp_path / "custom-out"
    custom.mkdir()

    dest, reason = resolve_subtitle_export_destination(project, project_path, "source")
    assert dest == media_dir
    assert "源媒体" in reason

    dest, reason = resolve_subtitle_export_destination(project, project_path, "project")
    assert dest == project_path.parent / "exports"
    assert "exports" in reason

    dest, reason = resolve_subtitle_export_destination(
        project, project_path, "custom", str(custom)
    )
    assert dest == custom
    assert "自定义" in reason

    monkeypatch.setattr(
        "twobyteasr.exports.studio_export_ui._directory_is_writable",
        lambda path: Path(path) != media_dir,
    )
    dest, reason = resolve_subtitle_export_destination(project, project_path, "source")
    assert dest == project_path.parent / "exports"
    assert "不可写" in reason
