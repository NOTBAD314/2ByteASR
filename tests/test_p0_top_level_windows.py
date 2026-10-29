"""P0 regression: startup must not flash blank top-level QWidget windows.

The original bug: ``_style_section`` called ``body.setVisible(expanded)``
while ``body`` was still a parentless QWidget, so every expanded style
section forced Qt to create (and immediately destroy) a real blank native
top-level window during ``MainWindow`` construction. These tests pin both
the style-panel construction path and the Project Hub refresh path.

Run with the same environment as other Qt tests (offscreen is fine): the
TopLevelWindowAudit records widget Show events regardless of window manager.
"""

import json
import uuid
import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QToolButton
from PySide6.QtTest import QTest

import twobyteasr.studio.studio_media_flow as studio_media_flow
import twobyteasr.projects.studio_project as studio_project
import twobyteasr.studio.studio_project_flow as studio_project_flow
import twobyteasr.studio.studio_ui as studio_ui
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.acceptance.window_audit import TopLevelWindowAudit


@pytest.fixture
def hub_project_dir(tmp_path,monkeypatch):
    base = tmp_path.resolve()
    root = (base / "projects").resolve()
    assert root.parent == base
    root.mkdir(parents=True)
    monkeypatch.setattr("twobyteasr.studio.studio_hub.project_library_root",lambda:root)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        try:
            base.rmdir()
        except OSError:
            pass


def _anonymous_shows(audit: TopLevelWindowAudit) -> list[dict]:
    return [
        record
        for record in audit.records
        if record["event"] == "Show"
        and record["class"] == "QWidget"
        and not record["objectName"]
        and not record["windowTitle"]
    ]


def _wait_cover_backfill(page, timeout_ms: int = 3000) -> None:
    import time

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        QApplication.processEvents()
        if not getattr(page, "_cover_backfill_inflight", set()):
            return
        time.sleep(0.02)


def test_style_panel_construction_creates_no_blank_top_level_windows(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    audit = TopLevelWindowAudit(app)
    try:
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"recent_projects": []}), encoding="utf-8")
        monkeypatch.setattr(studio_ui, "studio_settings_path", lambda: settings)
        monkeypatch.setattr(studio_project_flow, "studio_settings_path", lambda: settings)
        page = SubtitleStudioPage()
        QApplication.processEvents()
        # The pre-fix code flashed one blank top-level QWidget per expanded
        # style section (Advanced Style / 预设 / 文字 / 外观 / 动效 / 应用范围).
        assert _anonymous_shows(audit) == []
        page.close_page()
    finally:
        audit.close()


def test_hub_refresh_keeps_recent_cards_child_widgets(tmp_path, monkeypatch, hub_project_dir):
    app = QApplication.instance() or QApplication([])
    audit = TopLevelWindowAudit(app)
    try:
        settings = tmp_path / "settings.json"
        project_root = settings.parent / "projects"
        project_root.mkdir(exist_ok=True)
        records = []
        for index in range(3):
            path = hub_project_dir / f"project-{index}.2byteproj"
            project = SubtitleProject(
                media=StudioMedia(path=str(hub_project_dir / f"offline-{index}.mp4")),
                cues=[StudioCue(id=str(index + 1), start_ms=0, end_ms=1000, text=f"字幕 {index}")],
            )
            save_project(project, path)
            records.append({
                "path": str(path.resolve()),
                "name": path.stem,
                "cue_count": 1,
                "source_media": project.media.path,
            })
        settings.write_text(json.dumps({"recent_projects": records}), encoding="utf-8")
        monkeypatch.setattr(studio_ui, "studio_settings_path", lambda: settings)
        monkeypatch.setattr(studio_project_flow, "studio_settings_path", lambda: settings)
        monkeypatch.setattr(studio_project, "studio_settings_path", lambda: settings)
        monkeypatch.setattr(studio_media_flow, "project_library_root", lambda: project_root)
        monkeypatch.setattr(
            studio_project, "project_library_root", lambda: project_root
        )

        page = SubtitleStudioPage()
        page.show_project_hub()
        QApplication.processEvents()
        _wait_cover_backfill(page)

        cards = page.findChildren(QToolButton, "recentProjectCard")
        card_paths = {card.toolTip() for card in cards}
        assert len(card_paths) >= 3, "expected all three recent projects to be carded"
        for card in cards:
            assert not card.isWindow(), "recent project card leaked as a top-level window"
        visible_card_top_levels = [
            widget for widget in QApplication.topLevelWidgets()
            if widget.isVisible()
            and widget is not page.window()
            and (
                widget.objectName() in {"recentProjectCard", "projectCard", "projectListRow"}
                or type(widget).__name__ == "_ProjectCard"
            )
        ]
        assert visible_card_top_levels == []
        assert _anonymous_shows(audit) == []
        page.close_page()
    finally:
        audit.close()


def test_card_click_still_opens_project_after_window_fix(tmp_path, monkeypatch, hub_project_dir):
    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    path = hub_project_dir / "clickable.2byteproj"
    project = SubtitleProject(
        media=StudioMedia(path=str(hub_project_dir / "offline.mp4")),
        cues=[StudioCue(id="1", start_ms=0, end_ms=1000, text="点击字幕")],
    )
    save_project(project, path)
    settings.write_text(
        json.dumps({"recent_projects": [{
            "path": str(path.resolve()), "name": path.stem, "cue_count": 1,
            "source_media": project.media.path,
        }]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(studio_ui, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project_flow, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project, "studio_settings_path", lambda: settings)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page.video, "load", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(page, "_generate_waveform", lambda *_args, **_kwargs: None)
    page.show_project_hub()
    QApplication.processEvents()
    _wait_cover_backfill(page)
    card = page.findChildren(QToolButton, "recentProjectCard")[0]
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
    QApplication.processEvents()
    assert page._project_view_state == "open"
    assert page.project_path == path.resolve()
    assert page.project is not None
    page.close_page()
