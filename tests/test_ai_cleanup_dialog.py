"""AI 清理 on one page (2026-10-26, design A): local tidy and AI batches in one list."""
from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.studio import link_caption_cleanup
from twobyteasr.studio.ai_cleanup_dialog import KIND_ROLE, AiCleanupDialog
from twobyteasr.studio.studio_text_tools import CleanupResult, TextOccurrence
from twobyteasr.studio.studio_ui import SubtitleStudioPage

from tests.test_caption_tidy import imported_as_before


@pytest.fixture
def page(monkeypatch):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.app import api_key_explainer
    monkeypatch.setattr(api_key_explainer, "ask_for_key_if_missing", lambda *a, **k: False)
    studio = SubtitleStudioPage()
    studio.project = imported_as_before()
    yield studio
    studio.close_page()
    studio.close()
    app.processEvents()


def _wait(dialog):
    for _ in range(500):
        if not dialog._cleanup_running:
            return
        QTest.qWait(20)
    raise AssertionError("cleanup did not finish")


def _rows(dialog):
    return [(dialog.preview.item(i).data(KIND_ROLE), dialog.preview.item(i).isHidden())
            for i in range(dialog.preview.count())]


def _favourite(project, cue_ids, options, settings=None, **_):
    cue = next(c for c in project.cues if "favorite" in c.text)
    return CleanupResult([TextOccurrence(cue.id, cue.start_ms, cue.text, cue.text.replace("favorite", "favourite"),
                                         (0, len(cue.text)), reason="错字")], batches=1, done=1)


def test_one_list_filters_and_one_undo_step(page, monkeypatch):
    monkeypatch.setattr(link_caption_cleanup, "request_text_cleanup", _favourite)
    dialog = AiCleanupDialog(page, page)
    try:
        assert all(box.isChecked() for box in dialog.local_boxes.values())     # English download
        dialog._do_ai_preview()
        _wait(dialog)
        assert sorted(kind for kind, _hidden in _rows(dialog)) == ["break", "delete", "text"]
        assert dialog.filter_buttons["break"].text() == "断句 1" and dialog.all_button.text() == "应用 3 处"
        dialog._set_filter("delete")
        assert [kind for kind, hidden in _rows(dialog) if not hidden] == ["delete"]
        # Keep ">> Nice shot." as it is.
        dialog.preview.item([kind for kind, _ in _rows(dialog)].index("delete")).setCheckState(Qt.CheckState.Unchecked)
        assert dialog.count_label.text() == "已选 2 / 3 · 一步撤销"
        before = [c.text for c in page.project.cues]
        dialog._do_apply_preview()
        assert [c.text for c in page.project.cues] == [
            "Breaking people's faces in MMA has been America's new favourite pastime",   # AI edit kept
            "and that's what we do.", ">> Nice shot.", "wearing"]
        stack = page.session.undo_stack
        assert stack.count() == 1 and "Ctrl+Z" in dialog.status_label.text() and dialog.preview.count() == 0
        stack.undo()
        assert [c.text for c in page.project.cues] == before
    finally:
        dialog.reject()


def test_local_steps_alone_need_no_ai(page, monkeypatch):
    called = []
    monkeypatch.setattr(link_caption_cleanup, "request_text_cleanup", lambda *a, **k: called.append(a) or [])
    dialog = AiCleanupDialog(page, page)
    try:
        for chip in dialog.ai_option_boxes.values():
            chip.setChecked(False)
        dialog.local_boxes["regroup"].setChecked(False)
        dialog._do_ai_preview()
        _wait(dialog)
        assert called == [] and [kind for kind, _ in _rows(dialog)] == ["delete", "delete"]
        dialog._do_apply_preview()
        assert [c.text for c in page.project.cues][-2:] == ["Nice shot.", "wearing"]
        assert not any("[Music]" in c.text for c in page.project.cues)
    finally:
        dialog.reject()


def test_cancel_and_failed_batches_keep_what_was_found(page, monkeypatch):
    release = threading.Event()

    def slow(project, cue_ids, options, settings=None, *, cancel_check=None, progress=None, **_):
        found = _favourite(project, cue_ids, options)
        progress(dict(done=1, total=4, found=1))
        release.wait(5)
        return CleanupResult(found, batches=4, done=1, error="" if cancel_check() else "超时")

    monkeypatch.setattr(link_caption_cleanup, "request_text_cleanup", slow)
    dialog = AiCleanupDialog(page, page)
    try:
        dialog.local_boxes["regroup"].setChecked(False)
        dialog._do_ai_preview()
        for _ in range(500):
            if "第 1 / 4 批" in dialog.status_label.text():
                break
            QTest.qWait(20)
        assert dialog.status_label.text() == "AI 第 1 / 4 批 · 已找到 1 处" and dialog.cancel_button.isVisibleTo(dialog)
        # The local rows are already there; an untick made now survives the AI result.
        assert dialog.preview.count() == 2
        dialog.preview.item(0).setCheckState(Qt.CheckState.Unchecked)
        dialog.cancel_button.click()
        release.set()
        _wait(dialog)
        assert dialog.preview.count() == 3 and "已取消" in dialog.status_label.text()
        assert dialog.count_label.text() == "已选 2 / 3 · 一步撤销"
        for box in dialog.local_boxes.values():
            box.setChecked(False)
        release.clear()
        dialog._do_ai_preview()
        QTest.qWait(100)
        release.set()
        _wait(dialog)
        assert dialog.preview.count() == 1 and "已完成 1 / 4 批" in dialog.status_label.text()
        assert dialog.all_button.isEnabled()
    finally:
        release.set()
        dialog.reject()


def test_download_window_defaults(page):
    dialog = link_caption_cleanup.LinkCaptionCleanupDialog(page, page)
    try:
        assert isinstance(dialog, AiCleanupDialog)
        assert {k for k, chip in dialog.ai_option_boxes.items() if chip.isChecked()} == {"glossary", "punctuation"}
        assert dialog.local_boxes["regroup"].isChecked() and dialog.chrome.radius > 0
    finally:
        dialog.reject()
