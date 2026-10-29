"""P6.1 usability: timeline order, live find, blank project, hub clip assistant."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from twobyteasr.studio.studio_find_replace import FindReplaceDialog
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio.studio_ui import SubtitleStudioPage, WaveformTimeline


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _project() -> SubtitleProject:
    return SubtitleProject(
        media=StudioMedia(path="D:/rec.mp4", duration_ms=30_000),
        speakers=[StudioSpeaker("S01", "主播")],
        cues=[StudioCue("c1", 1000, 2500, "尼奈今天", "S01"), StudioCue("c2", 4000, 6000, "尼奈也好", "S01")],
    )


def test_untitled_media_path_is_allowed():
    media = StudioMedia(path="", display_name="未命名工程")
    media.validate()
    assert media.path == ""
    project = SubtitleProject(media=media)
    project.validate()


def test_video_track_sits_above_waveform(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    timeline = WaveformTimeline()
    timeline.resize(1200, 320)
    timeline.set_project(_project())
    timeline.show()
    QTest.qWait(20)
    video = timeline._video_track_rect()
    speakers, _translation, _legacy_waveform = timeline._track_layout()
    waveform=timeline._audio_track_rects()["A1"]
    speaker_rects = list(speakers.values())
    assert speaker_rects, "expected subtitle tracks"
    assert max(rect.bottom() for rect in speaker_rects) <= video.top() + 2
    assert abs(video.bottom() - waveform.top()) <= CANDIDATE_OR_ZERO(timeline) + 2
    assert waveform.top() >= video.bottom() - 1
    assert video.top() >= speaker_rects[-1].bottom() - 2
    timeline.setParent(None)
    timeline.deleteLater()


def CANDIDATE_OR_ZERO(timeline) -> int:
    rect = timeline._candidate_lane_rect()
    return int(rect.height()) if rect is not None else 0


def test_find_replace_live_search_fills_results(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    from twobyteasr.projects.studio_project import save_project
    path = save_project(_project(), tmp_path / "p61.2byteproj")
    page.open_project(path)
    dialog = FindReplaceDialog(page, page)
    dialog.find_edit.setText("尼奈")
    QTest.qWait(220)
    app.processEvents()
    assert dialog.preview.count() == 2
    assert "2" in dialog.status_label.text() or "尼奈" in dialog.preview.item(0).text()
    dialog.deleteLater()
    page.close_page()
    page.deleteLater()


def test_new_project_opens_blank_studio_without_file_dialog(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        "twobyteasr.projects.studio_project.project_library_root",
        lambda _base=None: tmp_path / "library",
    )
    monkeypatch.setattr(
        "twobyteasr.projects.studio_project_controller.project_library_root",
        lambda _base=None: tmp_path / "library",
    )
    opened = {"dialog": False}
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: opened.__setitem__("dialog", True) or ("", ""))
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    page.show_project_hub()
    page._create_blank_studio()
    app.processEvents()
    assert opened["dialog"] is False
    assert page.project is not None
    assert page.project.media.path == ""
    assert page.project.cues == []
    assert getattr(page, "_project_view_state", "") == "open"
    page.close_page()
    page.deleteLater()


def test_hub_clip_assistant_creates_blank_and_opens_tab(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        "twobyteasr.projects.studio_project.project_library_root",
        lambda _base=None: tmp_path / "library",
    )
    monkeypatch.setattr(
        "twobyteasr.projects.studio_project_controller.project_library_root",
        lambda _base=None: tmp_path / "library",
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    page.show_project_hub()
    page.studio_clip_assistant_button.click()
    app.processEvents()
    assert page.project is not None
    assert page.project.media.path == ""
    assert page.context_drawer.tabToolTip(page.context_drawer.currentIndex()) == "剪辑助手"
    page.close_page()
    page.deleteLater()


def test_workspace_splitter_follows_live():
    # 2026-10-22 (user): the video follows the timeline divider while it is
    # dragged; the 2026-08 rubber band moved it only after release. The host
    # minimum is the toolbar plus the timeline, not a fixed 260 px floor.
    _app()
    page = SubtitleStudioPage()
    assert page.workspace_splitter.opaqueResize() is True
    host = page.timeline.parent()
    assert host.minimumSizeHint().height() >= page.timeline.minimumHeight() + 30
    assert host.minimumHeight() != 260
    page.close_page()
    page.deleteLater()


def test_home_cta_and_window_minimum_are_usable(tmp_path, monkeypatch):
    _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow

    window = MainWindow([], legacy, object(), None)
    assert window.minimumWidth() <= 1080
    assert window.minimumHeight() <= 640
    assert window.studio_footer_button.minimumHeight() == window.start_button.minimumHeight()
    assert window.studio_footer_button.objectName() == "studioFooterButton"
    assert window.start_button.objectName() == "primary"
    assert window.header_status.isHidden()
    window.close()
    window.deleteLater()


def test_blank_studio_shows_import_media_empty_state(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        "twobyteasr.projects.studio_project.project_library_root",
        lambda _base=None: tmp_path / "library",
    )
    monkeypatch.setattr(
        "twobyteasr.projects.studio_project_controller.project_library_root",
        lambda _base=None: tmp_path / "library",
    )
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    page._create_blank_studio()
    app.processEvents()
    assert not page.video_empty_hint.isHidden()
    assert hasattr(page, "video_empty_import")
    assert hasattr(page, "studio_import_media_button")
    page.close_page()
    page.deleteLater()
