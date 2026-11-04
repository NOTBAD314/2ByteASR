import json
import shutil
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QWidget
from PySide6.QtTest import QTest

import twobyteasr.studio.studio_hub as studio_hub
import twobyteasr.studio.studio_media_flow as studio_media_flow
import twobyteasr.projects.studio_project as studio_project
import twobyteasr.studio.studio_project_flow as studio_project_flow
import twobyteasr.studio.studio_ui as studio_ui
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio.studio_hub import StudioHubMixin
from twobyteasr.studio.studio_sentence_refine_ui import StudioSentenceRefineMixin
from twobyteasr.studio.studio_review_ui import StudioReviewMixin
from twobyteasr.studio.studio_ui import SubtitleStudioPage


HUB_METHODS = (
    "_apply_hub_paper_texture",
    "_refresh_studio_empty_state",
    "_project_library_records",
    "_open_recent_project_card",
    "_remove_recent_project_metadata",
    "_set_hub_toolbar_mode",
    "_show_hub_preferences",
    "_choose_hub_project_root",
    "_save_hub_preferences",
    "_clear_recent_project_metadata",
    "_recent_project_menu",
)

STUDIO_SIGNALS = {
    "ai_provider_progress_signal",
    "library_records_ready_signal",
    "library_cover_ready_signal",
    "recognition_cancel_requested",
    "recognition_detail_requested",
    "return_requested",
    "recognition_requested",
    "cover_ready_signal",
    "waveform_ready_signal",
    "waveform_progress_signal",
    "waveform_failed_signal",
    "startup_milestone_signal",
    "media_ingest_ready_signal",
    "project_media_probe_ready_signal",
    "ai_ready_signal",
    "ai_failed_signal",
    "ai_stage_signal",
    "ai_web_theme_signal",
    # 十五轮新增的 AI 修改信号（存量失败：信号进了页面，此白名单漏更新——
    # 二十四轮顺手补齐，HEAD stash 对照确认非本轮引入）。
    "ai_refine_signal",
    "ai_web_adjust_signal",
    "ai_stream_line_signal",
    "ai_provider_probe_signal",
    "reasr_ready_signal",
    "reasr_failed_signal",
    "ass_ready_signal",
    "ass_failed_signal",
    "autosave_ready_signal",
    "autosave_failed_signal",
    "advanced_preview_ready_signal",
    "advanced_preview_failed_signal",
    "ai_variant_preview_ready_signal",
    # P25.3 fine-tune revision round additions
    "ai_revision_signal",
    "ai_revision_failed_signal",
    "close_ready_signal",
}

STUDIO_SIGNAL_SIGNATURES = {
    "return_requested()",
    "cover_ready_signal(QString,QString)",
    "waveform_ready_signal(int,QString,QString,PyObject)",
    "waveform_failed_signal(int,QString,QString)",
    "ai_ready_signal(PyObject)",
    "ai_failed_signal(QString)",
    "reasr_ready_signal(PyObject)",
    "reasr_failed_signal(QString)",
    "ass_ready_signal(int,QString)",
    "ass_failed_signal(int,QString)",
    "autosave_ready_signal(int)",
    "autosave_failed_signal(int,QString)",
    "advanced_preview_ready_signal(PyObject,int,QString,bool)",
    "advanced_preview_failed_signal(PyObject,int,QString)",
}


def _patch_hub_settings(monkeypatch, settings):
    project_root = settings.parent / "projects"
    project_root.mkdir(exist_ok=True)
    monkeypatch.setattr(studio_hub, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_hub, "project_library_root", lambda: project_root)
    monkeypatch.setattr(studio_project, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_ui, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project_flow, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_media_flow, "project_library_root", lambda: project_root)


@pytest.fixture
def hub_project_dir(tmp_path):
    base = tmp_path.resolve()
    root = (base / "projects").resolve()
    assert root.parent == base
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        try:
            base.rmdir()
        except OSError:
            pass


def test_project_hub_behavior_mixin_structure_and_resolution():
    assert not issubclass(StudioHubMixin, QObject)
    assert "__init__" not in StudioHubMixin.__dict__
    assert not any(isinstance(value, Signal) for value in StudioHubMixin.__dict__.values())
    assert not {
        name
        for name, value in StudioHubMixin.__dict__.items()
        if not name.startswith("__") and name not in HUB_METHODS and not callable(value)
        and not name.isupper()  # 类常量（如 _LIBRARY_BUILD_BATCH 分批大小）
    }
    assert issubclass(SubtitleStudioPage, QWidget)
    assert SubtitleStudioPage.__mro__[:4] == (
        SubtitleStudioPage,
        StudioHubMixin,
        StudioSentenceRefineMixin,
        StudioReviewMixin,
    )
    assert QWidget in SubtitleStudioPage.__mro__
    assert not (set(HUB_METHODS) & set(SubtitleStudioPage.__dict__))
    assert not (set(HUB_METHODS) & set(dir(QWidget)))
    assert {
        name
        for name, value in SubtitleStudioPage.__dict__.items()
        if isinstance(value, Signal)
    } == STUDIO_SIGNALS
    for name in HUB_METHODS:
        assert callable(getattr(SubtitleStudioPage, name))
        assert getattr(SubtitleStudioPage, name) is getattr(StudioHubMixin, name)

    app = studio_ui.QApplication.instance() or studio_ui.QApplication([])
    page = SubtitleStudioPage()
    meta = page.metaObject()
    assert meta.className() == "SubtitleStudioPage"
    assert {
        signature
        for signature in STUDIO_SIGNAL_SIGNATURES
        if meta.indexOfSignal(signature) >= 0
    } == STUDIO_SIGNAL_SIGNATURES
    page.close_page()


def test_recent_cards_real_mouse_click_open_five_projects(
    tmp_path, monkeypatch, hub_project_dir
):
    app = studio_ui.QApplication.instance() or studio_ui.QApplication([])
    settings = tmp_path / "settings.json"
    projects = []
    records = []
    for index in range(5):
        path = hub_project_dir / f"project-{index}.2byteproj"
        project = SubtitleProject(
            media=StudioMedia(path=str(hub_project_dir / f"offline-{index}.mp4")),
            cues=[StudioCue(id=str(index + 1), start_ms=0, end_ms=1000, text=f"字幕 {index}")],
        )
        save_project(project, path)
        projects.append(path.resolve())
        records.append({"path": str(path.resolve()), "name": path.stem, "cue_count": 1, "source_media": project.media.path})
    settings.write_text(json.dumps({"recent_projects": records}), encoding="utf-8")
    _patch_hub_settings(monkeypatch, settings)

    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.show_project_hub()
    app.processEvents()

    for expected in projects:
        cards = page.findChildren(studio_ui.QToolButton, "recentProjectCard")
        card = next(item for item in cards if str(expected) in item.toolTip())
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
        app.processEvents()
        assert page._project_view_state == "open"
        assert page.project_path == expected
        assert page.project is not None
        page.show_project_hub()
        app.processEvents()
    page.close_page()


def test_media_load_failure_keeps_valid_project_open(tmp_path, monkeypatch):
    app = studio_ui.QApplication.instance() or studio_ui.QApplication([])
    path = tmp_path / "offline-project.2byteproj"
    media = tmp_path / "broken.mp4"
    media.write_bytes(b"not a video")
    project = SubtitleProject(
        media=StudioMedia(path=str(media)),
        cues=[StudioCue(id="1", start_ms=0, end_ms=1000, text="离线字幕")],
    )
    save_project(project, path)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"recent_projects": []}), encoding="utf-8")
    _patch_hub_settings(monkeypatch, settings)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("mpv unavailable")))
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.open_project(path)
    app.processEvents()
    assert page.project is not None
    assert page._project_view_state == "open"
    assert page.project_path == path.resolve()
    page.close_page()


def test_missing_project_card_prioritizes_project_status(
    tmp_path, monkeypatch, hub_project_dir
):
    app = studio_ui.QApplication.instance() or studio_ui.QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "recent_projects": [
                    {
                            "path": str(hub_project_dir / "moved.2byteproj"),
                        "name": "已移动工程",
                        "cue_count": 3,
                            "source_media": str(hub_project_dir / "moved.mp4"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _patch_hub_settings(monkeypatch, settings)
    page = SubtitleStudioPage()
    page.show_project_hub()
    app.processEvents()
    card = page.findChild(studio_ui.QToolButton, "recentProjectCard")
    assert card is not None
    assert "工程文件已移动" in card.text()
    assert "素材离线" not in card.text()
    page.close_page()


def test_project_hub_uses_one_searchable_scrollable_library(tmp_path, monkeypatch):
    app = studio_ui.QApplication.instance() or studio_ui.QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"recent_projects": []}), encoding="utf-8")
    _patch_hub_settings(monkeypatch, settings)
    page = SubtitleStudioPage()
    page.show_project_hub()
    app.processEvents()
    assert not hasattr(page, "recent_projects_host")
    assert page.project_library_scroll.widgetResizable()
    assert page.project_search.placeholderText() == "搜索工程..."
    assert page.project_sort.currentData() == "recent"
    assert page.all_projects_layout.horizontalSpacing() == 24
    page.close_page()


def test_hub_preference_save_keeps_reduce_motion_and_startup_page(tmp_path, monkeypatch):
    # 2026-10-15: a second _save_hub_preferences in studio_hub rebuilt the
    # whole studio_preferences object from its own arguments and dropped
    # reduce_motion / startup_page written by Application Settings.
    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", str(tmp_path / "data"))
    settings = studio_project.studio_settings_path()
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"recent_projects": [], "studio_preferences": {
        "reduce_motion": True, "startup_page": "project_library", "autosave_enabled": True,
    }}), encoding="utf-8")
    app = studio_ui.QApplication.instance() or studio_ui.QApplication([])
    page = SubtitleStudioPage()
    refreshes = []
    monkeypatch.setattr(page, "_refresh_visible_library", lambda: refreshes.append(True))
    library = str(tmp_path / "library")
    try:
        page._save_hub_preferences(library, False, 120, 9, True, False, "official")
        page._save_hub_preferences(library, False, 300, 9, True, False, "official")
    finally:
        page.close_page()
    payload = json.loads(settings.read_text(encoding="utf-8"))
    preferences = payload["studio_preferences"]
    assert preferences.get("reduce_motion") is True
    assert preferences.get("startup_page") == "project_library"
    assert (preferences["autosave_enabled"], preferences["autosave_interval_seconds"],
            preferences["recovery_policy"]) == (False, 300, "official")
    assert payload["project_root"] == library
    # Only the save that moved the library root refreshes the visible library.
    assert refreshes == [True]
