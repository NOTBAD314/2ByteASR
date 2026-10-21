"""P1 Project Library layout: computed column count fills the viewport.

The grid derives columns from live width (target card 320px, gap 24) instead
of hard breakpoints, so 16:9 desktops show a 4th column when space exists.
"""

import json
import shutil
import uuid
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton

import twobyteasr.projects.studio_project as studio_project
import twobyteasr.studio.studio_project_flow as studio_project_flow
import twobyteasr.studio.studio_ui as studio_ui
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio.studio_ui import SubtitleStudioPage


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


@pytest.mark.parametrize(
    "viewport_width,expected_columns",
    [(2560, 7), (1920, 5), (1600, 4), (1440, 3), (1366, 3), (1280, 3), (980, 2), (960, 2), (700, 1), (520, 1)],
)
def test_library_grid_metrics(viewport_width, expected_columns):
    columns, card_width, gap = SubtitleStudioPage._library_grid_metrics(viewport_width)
    assert columns == expected_columns, (viewport_width, columns, card_width)
    assert gap == 24
    assert 300 <= card_width <= 460, card_width


def test_desktop_grid_fills_viewport_without_huge_right_gap():
    for viewport_width in (1600, 1920):
        columns, card_width, _gap = SubtitleStudioPage._library_grid_metrics(viewport_width)
        assert columns == (4 if viewport_width==1600 else 5), (viewport_width, columns)
        assert 300 <= card_width <= 460, (viewport_width, card_width)
        used = columns * card_width + _gap * (columns - 1)
        assert used >= viewport_width - 84 - (card_width // 2), (
            viewport_width,
            used,
            "more than half a card of dead space remains on the right",
        )


def _hub_with_projects(tmp_path, monkeypatch, hub_project_dir, count=3):
    settings = tmp_path / "settings.json"
    records = []
    for index in range(count):
        path = hub_project_dir / f"project-{index}.2byteproj"
        project = SubtitleProject(
            media=StudioMedia(path=str(hub_project_dir / f"offline-{index}.mp4")),
            cues=[StudioCue(id=str(index + 1), start_ms=0, end_ms=1000, text=f"字幕 {index}")],
        )
        save_project(project, path)
        records.append({
            "path": str(path.resolve()), "name": path.stem, "cue_count": 1,
            "source_media": project.media.path,
        })
    settings.write_text(json.dumps({"recent_projects": records}), encoding="utf-8")
    monkeypatch.setattr(studio_ui, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project_flow, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project, "studio_settings_path", lambda: settings)
    monkeypatch.setattr("twobyteasr.studio.studio_hub.project_library_root", lambda:hub_project_dir)
    page = SubtitleStudioPage()
    monkeypatch.setattr(page, "_generate_waveform", lambda *_a, **_k: None)
    page.show_project_hub()
    return page


def test_card_structure_fixed_size_and_thumbnail_ratio(tmp_path, monkeypatch, hub_project_dir):
    app = QApplication.instance() or QApplication([])
    page = _hub_with_projects(tmp_path, monkeypatch, hub_project_dir, count=1)
    try:
        app.processEvents()
        record = page._project_library_records()[0]
        for card_width in (460, 440):
            card = page._build_project_card(record, card_width)
            try:
                assert card.width() == card_width
                assert card.height() == card.minimumHeight(), "card height must stay fixed"
                cover = card.findChildren(QLabel, "projectCardCover")[0]
                assert abs(cover.width() / cover.height() - 16 / 9) < 0.02
                ratio = cover.height() / card.height()
                assert 0.53 <= ratio <= 0.62, (card_width, ratio)
                title = card.findChildren(QLabel, "projectCardTitle")[0]
                meta = card.findChildren(QLabel, "projectCardMeta")[0]
                assert title.minimumHeight() >= 40
                assert meta.minimumHeight() == 20
            finally:
                card.deleteLater()
        app.processEvents()
    finally:
        page.close_page()


def test_cover_backfill_updates_matching_card(tmp_path, monkeypatch, hub_project_dir):
    """The backfill signal must find its card by path and swap the cover."""
    app = QApplication.instance() or QApplication([])
    page = _hub_with_projects(tmp_path, monkeypatch, hub_project_dir, count=1)
    try:
        app.processEvents()
        card = page.findChildren(QToolButton, "recentProjectCard")[0]
        before_key = None
        before_pixmap = card.findChildren(QLabel, "projectCardCover")[0].pixmap()
        if before_pixmap is not None and not before_pixmap.isNull():
            before_key = before_pixmap.cacheKey()
        from PySide6.QtGui import QPixmap

        source = QPixmap(420, 236)
        source.fill()
        fake_cover = tmp_path / "project-cover.jpg"
        source.save(str(fake_cover), "JPG")
        card = page.findChildren(QToolButton, "recentProjectCard")[0]
        before_key = None
        before_pixmap = card.findChildren(QLabel, "projectCardCover")[0].pixmap()
        if before_pixmap is not None and not before_pixmap.isNull():
            before_key = before_pixmap.cacheKey()
        page._cover_backfill_ready(str(card.toolTip()).splitlines()[-1], str(fake_cover))
        app.processEvents()
        # The hub may have rebuilt during processEvents; look the card up again.
        cards = page.findChildren(QToolButton, "recentProjectCard")
        assert cards
        covers = [
            label.pixmap() for label in cards[0].findChildren(QLabel, "projectCardCover")
            if label.pixmap() is not None and not label.pixmap().isNull()
        ]
        assert covers, "cover label lost its pixmap after backfill"
        assert before_key is None or covers[0].cacheKey() != before_key
    finally:
        page.close_page()


def _show_hub_at(page, app, width, height):
    page.resize(width, height)
    page.show()
    app.processEvents()
    page.show_project_hub()
    app.processEvents()
    if hasattr(page, "workspace_splitter"):
        origin = page.workspace_splitter.mapTo(page, page.workspace_splitter.rect().topLeft())
        page.studio_empty.setGeometry(origin.x(), origin.y(), page.workspace_splitter.width(), page.workspace_splitter.height())
    page.project_library_scroll.resize(max(640, page.studio_empty.width()), max(400, page.studio_empty.height()))
    app.processEvents()
    page._refresh_studio_empty_state()
    app.processEvents()


def test_header_actions_stay_visible_in_compact_window(tmp_path, monkeypatch, hub_project_dir):
    app = QApplication.instance() or QApplication([])
    page = _hub_with_projects(tmp_path, monkeypatch, hub_project_dir, count=4)
    try:
        _show_hub_at(page, app, 1100, 760)
        new_button = page.project_new_button
        import_button = page.project_import_button
        viewport = page.project_library_scroll.viewport().rect()
        new_rect = new_button.rect()
        new_rect.moveTopLeft(new_button.mapTo(page.project_library_scroll.viewport(), new_rect.topLeft()))
        import_rect = import_button.rect()
        import_rect.moveTopLeft(import_button.mapTo(page.project_library_scroll.viewport(), import_rect.topLeft()))
        assert viewport.contains(new_rect), (viewport, new_rect)
        assert viewport.contains(import_rect), (viewport, import_rect)
        assert new_button.width() >= 132
        assert new_button.height() >= 30  # shared control_qss: 28px content + border
        mascot = page.project_library_mascot
        assert mascot.width() >= 56
        assert mascot.height() >= 56
        assert mascot.pixmap() is not None and not mascot.pixmap().isNull()
    finally:
        page.close_page()


def test_hero_preview_is_16x9_and_larger_than_cards(tmp_path, monkeypatch, hub_project_dir):
    app = QApplication.instance() or QApplication([])
    page = _hub_with_projects(tmp_path, monkeypatch, hub_project_dir, count=3)
    try:
        _show_hub_at(page, app, 1280, 820)
        preview = page.resume_preview
        assert not preview.isVisible(), "no synthetic hero without a real cover"
        from PySide6.QtGui import QPixmap
        cover_image=QPixmap(640,360);cover_image.fill()
        page.resume_preview_image.set_cover(cover_image)
        page._resume_has_cover=True;page._resume_cover_aspect=16/9
        page._sync_resume_hero_geometry();app.processEvents()
        ratio = preview.width() / max(1, preview.height())
        assert abs(ratio - 16 / 9) < 0.08, (preview.width(), preview.height(), ratio)
        cards = page.findChildren(QToolButton, "recentProjectCard")
        assert cards
        cover = cards[0].findChildren(QLabel, "projectCardCover")[0]
        assert preview.height() >= round(cover.height() * 1.15), (preview.height(), cover.height())
        open_button = cards[0].findChildren(type(page.project_new_button), "projectCardOpen")[0]
        assert open_button.objectName() == "projectCardOpen"
        hero_right = page.resume_hero.mapTo(page.project_library_scroll.viewport(), page.resume_hero.rect().bottomRight())
        viewport = page.project_library_scroll.viewport().rect()
        assert hero_right.x() <= viewport.right() + 2, (hero_right, viewport)
        assert hero_right.y() <= viewport.bottom() + page.resume_hero.height()
    finally:
        page.close_page()
