"""Studio project library: one rebuild per real change (2026-10-12)."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

import twobyteasr.studio_hub as studio_hub
import twobyteasr.studio_media_flow as studio_media_flow
import twobyteasr.studio_project as studio_project
import twobyteasr.studio_project_flow as studio_project_flow
import twobyteasr.studio_ui as studio_ui
from twobyteasr.studio_hub import _library_display_signature
from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio_ui import SubtitleStudioPage


@pytest.fixture
def library(tmp_path, monkeypatch):
    base = tmp_path.resolve()
    root = base / "projects"
    root.mkdir()
    settings = base / "settings.json"
    recent = []
    for index in range(6):
        path = root / f"project-{index}.2byteproj"
        media = base / f"media-{index}.mp4"
        if index % 2 == 0:
            media.write_bytes(b"0")
        project = SubtitleProject(media=StudioMedia(path=str(media)),
                                  cues=[StudioCue(id=str(n + 1), start_ms=0, end_ms=900, text=f"字幕{n}")
                                        for n in range(index + 1)])
        save_project(project, path)
        if index < 3:
            recent.append({"path": str(path.resolve()), "name": path.stem, "cue_count": index + 1,
                           "source_media": str(media)})
    settings.write_text(json.dumps({"recent_projects": recent,
                                    "studio_preferences": {"auto_cover": False}}), encoding="utf-8")
    for module in (studio_hub, studio_project, studio_ui, studio_project_flow):
        monkeypatch.setattr(module, "studio_settings_path", lambda *a: settings)
    for module in (studio_hub, studio_media_flow):
        monkeypatch.setattr(module, "project_library_root", lambda *a: root)
    QApplication.instance() or QApplication([])
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _wait_scan(page, timeout=8.0):
    app = QApplication.instance()
    end = time.monotonic() + timeout
    while (getattr(page, "_hub_scan_pending", False) or getattr(page, "_hub_scan_again", False)) \
            and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def _page_with_index(library):
    # A previous session's scan wrote the persisted summary index.
    seed = SubtitleStudioPage()
    seed._project_library_records()
    seed.close_page()
    assert studio_project.library_index_path().is_file()
    page = SubtitleStudioPage()
    page.resize(1500, 950)
    page.show()
    return page


def test_signature_ignores_bookkeeping_but_sees_real_changes():
    base = [{"path": "C:/p/a.2byteproj", "name": "a", "cue_count": 3, "source_media": "D:/a.mp4"}]
    noisy = [dict(base[0], _summary_loaded=True, _needs_metadata_repair=False, status="可打开")]
    assert _library_display_signature(base) == _library_display_signature(noisy)
    assert _library_display_signature(base) != _library_display_signature([dict(base[0], cue_count=4)])
    assert _library_display_signature(base) != _library_display_signature(base + base)


def test_first_entry_from_index_is_not_rebuilt_by_the_unchanged_scan(library):
    page = _page_with_index(library)
    try:
        page.show_project_hub()
        app = QApplication.instance()
        app.processEvents()
        generation = page._library_build_generation
        assert page._hub_card_widgets
        _wait_scan(page)
        assert page._library_build_generation == generation  # scan result == first paint
        # Statuses arrived in place: offline media and ready projects.
        texts = {card.text().splitlines()[-1] for card in page._hub_card_widgets}
        assert "正在检查…" not in texts and {"可继续", "素材离线"} <= texts
        # Re-entry with nothing changed: no rebuild either.
        page.show_project_hub()
        _wait_scan(page)
        assert page._library_build_generation == generation
    finally:
        page.close_page()


def test_only_the_visible_view_is_built_and_the_other_on_switch(library):
    page = _page_with_index(library)
    try:
        page.show_project_hub()
        _wait_scan(page)
        assert page._hub_card_widgets and not page._hub_row_widgets
        generation = page._library_build_generation
        page._set_project_library_view("list")
        _wait_scan(page)
        assert len(page._hub_row_widgets) == len(page._hub_card_widgets)
        assert page._library_build_generation == generation
    finally:
        page._set_project_library_view("card", refresh=False)
        page.close_page()


def test_scan_result_while_library_hidden_is_rendered_only_when_shown(library):
    page = _page_with_index(library)
    try:
        page.show_project_hub()
        _wait_scan(page)
        generation = page._library_build_generation
        page.hide()
        records = list(page._hub_library_records)
        records.append({"path": str(library / "late.2byteproj"), "name": "late", "cue_count": 1,
                        "source_media": "", "last_opened": ""})
        page._library_scan_ready(records, getattr(page, "_hub_scan_generation", 0))
        assert page._hub_rebuild_pending and page._library_build_generation == generation
        page.show()
        page._refresh_studio_empty_state(rescan=False)
        assert page._library_build_generation == generation + 1
        assert any(card.text().startswith("late") for card in page._hub_card_widgets)
    finally:
        page.close_page()


def test_status_is_unknown_until_checked_and_never_probes_drives_on_gui(library, monkeypatch):
    page = SubtitleStudioPage()
    try:
        record = {"path": str(library / "project-1.2byteproj"), "source_media": "H:/sleeping/drive.mp4"}

        def no_disk(*_args, **_kwargs):
            raise AssertionError("GUI thread touched the file system")
        monkeypatch.setattr(Path, "is_file", no_disk)
        assert page._project_status(record)[1] == "checking"
        page._library_presence = {record["path"]: (True, False)}
        assert page._project_status(record)[1] == "offline"
        page._library_presence = {record["path"]: (False, None)}
        assert page._project_status(record)[1] == "missing"
    finally:
        monkeypatch.undo()
        page.close_page()


def test_cover_cache_is_bounded_by_bytes_not_thrashed_by_two_views(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    page = SubtitleStudioPage()
    try:
        monkeypatch.setattr(studio_hub, "_COVER_CACHE_BYTES", 3 * 400 * 400 * 4)
        cover = tmp_path / "cover.png"
        cover.write_bytes(b"x")
        page._library_cover_labels = {}
        page._library_cover_queued = set()
        for width in range(10):
            image = QImage(400, 400, QImage.Format.Format_ARGB32)
            image.fill(0)
            page._on_library_cover_ready(str(cover), 400 + width, 400, image)
        assert len(page._library_cover_images) == 3
        assert page._library_cover_bytes <= studio_hub._COVER_CACHE_BYTES
    finally:
        page.close_page()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_cards_beyond_the_first_screens_are_built_when_scrolled_to(library):
    for index in range(6, 40):
        save_project(SubtitleProject(media=StudioMedia(path=""), cues=[]), library / f"extra-{index}.2byteproj")
    page = SubtitleStudioPage()
    page.resize(1100, 700)
    page.show()
    try:
        page.show_project_hub()
        _wait_scan(page)
        app = QApplication.instance()
        for _ in range(20):
            app.processEvents()
        total = len(page._hub_display_records)
        built = len(page._hub_card_widgets)
        assert total == 40 and 16 <= built < total
        bar = page.project_library_scroll.verticalScrollBar()
        for _ in range(12):
            bar.setValue(bar.maximum())
            for _ in range(10):
                app.processEvents()
        assert len(page._hub_card_widgets) == total
    finally:
        page.close_page()
