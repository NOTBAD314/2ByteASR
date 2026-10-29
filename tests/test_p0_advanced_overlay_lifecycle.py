"""P0.1 regression: the advanced overlay must never outlive Studio visibility.

AdvancedLiveCanvas is a Qt.Tool top-level window positioned in global screen
coordinates over the mpv viewport. Leaving the Studio page (QStackedWidget
switch) must hide it; returning may restore it through the normal sync path.
"""

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtGui import QHideEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import QApplication

import twobyteasr.projects.studio_project as studio_project
import twobyteasr.studio.studio_ui as studio_ui
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project


def _project_page(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    path = tmp_path / "leaky.2byteproj"
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "offline.mp4")),
        cues=[StudioCue(id="1", start_ms=0, end_ms=1000, text="特效字幕")],
    )
    save_project(project, path)
    settings.write_text(json.dumps({"recent_projects": []}), encoding="utf-8")
    monkeypatch.setattr(studio_ui, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project, "studio_settings_path", lambda: settings)
    page = studio_ui.SubtitleStudioPage()
    page.show()
    QApplication.processEvents()
    return page


def test_hiding_studio_page_hides_advanced_overlay(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    page = _project_page(tmp_path, monkeypatch)
    try:
        overlay = page.advanced_cue_overlay
        # Offscreen tool windows never report isVisible(); emulate the real
        # platform state so the restore intent is recorded.
        monkeypatch.setattr(overlay, "isVisible", lambda: True, raising=False)
        overlay.setVisible(True)
        QApplication.processEvents()
        page.hideEvent(QHideEvent())
        QApplication.processEvents()
        assert overlay.isHidden(), "overlay leaked over other pages after leaving Studio"
        assert page._advanced_overlay_restore, "restore intent must be remembered"
    finally:
        page.close_page()


def test_showing_studio_page_reschedules_overlay_sync(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    page = _project_page(tmp_path, monkeypatch)
    try:
        page._advanced_overlay_restore = True
        synced = []
        monkeypatch.setattr(page, "_sync_advanced_cue_overlay", lambda: synced.append(1))
        page.showEvent(QShowEvent())
        QApplication.processEvents()
        assert synced, "returning to Studio must re-sync the overlay geometry"
        assert not page._advanced_overlay_restore
    finally:
        page.close_page()


def test_publish_ready_never_shows_overlay_while_page_hidden(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    page = _project_page(tmp_path, monkeypatch)
    try:
        page.hideEvent(QHideEvent())
        QApplication.processEvents()
        from twobyteasr.rendering.advanced_preview import AdvancedPreviewIdentity

        identity = AdvancedPreviewIdentity(
            cue_id="1", snapshot_hash="x", glyph_key="g", motion_key="m",
            request_key="k", motion_time_ms=300, resolution=(640, 360), fps=30.0,
        )
        source = QPixmap(640, 360)
        source.fill()
        fake = tmp_path / "frame.png"
        source.save(str(fake), "PNG")
        page._advanced_preview_snapshot = None
        state = page._advanced_preview_state
        state.identity = identity
        state.phase = studio_ui.AdvancedPreviewPhase.PREPARING
        page._advanced_preview_generation = state.generation
        page._publish_advanced_frame(identity, state.generation, str(fake), False)
        QApplication.processEvents()
        assert page.advanced_cue_overlay.isHidden()
    finally:
        page.close_page()
