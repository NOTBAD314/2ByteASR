"""Cleanup must publish a whole edit and reject retired dialog/worker results."""
from __future__ import annotations

import copy
import threading
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.studio.ai_cleanup_dialog import AiCleanupDialog
from twobyteasr.studio.studio_text_tools import SCOPE_SELECTED, TextOccurrence
from twobyteasr.studio.studio_ui import SubtitleStudioPage
from twobyteasr.timeline.caption_tidy import plan_caption_tidy
from tests.test_caption_tidy import imported_as_before


@pytest.fixture
def page():
    app = QApplication.instance() or QApplication([])
    studio = SubtitleStudioPage()
    studio.project = imported_as_before()
    yield studio
    studio.close_page()
    studio.close()
    app.processEvents()


def prepared(page):
    dialog = AiCleanupDialog(page, page)
    project = page.project
    cue = next(c for c in project.cues if "favorite" in c.text)
    dialog._local_splices = plan_caption_tidy(project, [c.id for c in project.cues]).splices
    dialog._local_used = {"labels", "regroup"}
    dialog._fill_preview([TextOccurrence(cue.id, cue.start_ms, cue.text,
                          cue.text.replace("favorite", "favourite"), (0, len(cue.text)))])
    return dialog


def canonical(project):
    return copy.deepcopy((project.cues, project.studio_state, project.generation_metadata))


def test_mixed_cleanup_publishes_one_complete_revision_and_round_trips(page, tmp_path):
    from twobyteasr.projects.studio_project import save_project, load_project
    from twobyteasr.recognition.cue_word_alignment import cue_words
    dialog = prepared(page)
    state = state_for(page.project)
    before = canonical(page.project)
    revision = state.revision
    observed = []
    state.subscribe(lambda delta: observed.append((delta.revision, [c.text for c in page.project.cues])))
    try:
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        after = canonical(page.project)
        assert state.revision == revision + 1 and len(observed) == 1
        assert all("[Music]" not in text for text in observed[0][1])
        assert any("favourite" in text for text in observed[0][1])
        assert page.undo_stack.count() == 1
        page.undo_stack.undo()
        assert canonical(page.project) == before
        page.undo_stack.redo()
        assert canonical(page.project) == after and len(observed) == 3
        saved = save_project(page.project, tmp_path / "cleaned.2byteproj")
        reopened = load_project(saved)
        assert [c.text for c in reopened.cues] == [c.text for c in page.project.cues]
        for cue in reopened.cues:
            original = next(c for c in page.project.cues if c.id == cue.id)
            assert cue_words(reopened, cue) == cue_words(page.project, original)
    finally:
        dialog.reject()


def test_invalid_later_splice_does_not_leave_earlier_ai_or_local_changes(page):
    dialog = prepared(page)
    before = canonical(page.project)
    revision = state_for(page.project).revision
    # Old macro implementation first applied AI, then raised while
    # constructing the selected local splice.
    dialog._local_splices[-1].inserted[0].end_ms = -1
    try:
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert canonical(page.project) == before
        assert state_for(page.project).revision == revision
        assert page.undo_stack.count() == 0
        assert "清理没有完成" in dialog.status_label.text()
    finally:
        dialog.reject()


def test_apply_callback_reentry_and_second_click_cannot_commit_twice(page):
    dialog = prepared(page)
    state = state_for(page.project)
    revision = state.revision
    state.subscribe(lambda _delta: dialog._apply_checked())
    try:
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert page.undo_stack.count() == 1 and state.revision == revision + 1
        assert dialog.preview.count() == 0
    finally:
        dialog.reject()


def test_failure_inside_native_undo_push_rolls_back_and_removes_failed_command(page, monkeypatch):
    from twobyteasr.timeline.studio_commands import CleanupCuesCommand
    dialog = prepared(page)
    before = canonical(page.project)
    revision = state_for(page.project).revision
    original_mutate = CleanupCuesCommand._mutate
    def fail_after_mutation(self, cues):
        original_mutate(self, cues)
        raise RuntimeError("injected failure after canonical mutation")
    monkeypatch.setattr(CleanupCuesCommand, "_mutate", fail_after_mutation)
    published = []
    state_for(page.project).subscribe(published.append)
    try:
        # Real QPushButton -> real QUndoStack.push -> Python redo virtual.
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert canonical(page.project) == before
        assert state_for(page.project).revision == revision and not published
        assert page.undo_stack.count() == 0 and page.undo_stack.index() == 0
        assert "injected failure" in dialog.status_label.text()
        assert dialog.preview.count() > 0
    finally:
        dialog.reject()


def test_mismatched_candidate_original_rejects_the_whole_selection(page):
    dialog = prepared(page)
    before = canonical(page.project)
    first = dialog._preview_hits[0]
    dialog._preview_hits.append(TextOccurrence(first.cue_id, first.start_ms, "wrong", "bad", (90, 95)))
    dialog._rebuild_rows()
    try:
        QTest.mouseClick(dialog.all_button, Qt.LeftButton)
        assert canonical(page.project) == before and page.undo_stack.count() == 0
    finally:
        dialog.reject()


def test_old_run_closed_dialog_and_replaced_session_drop_local_results(page):
    dialog = AiCleanupDialog(page, page)
    plan = plan_caption_tidy(page.project, [c.id for c in page.project.cues])
    try:
        dialog._run_generation = 2
        dialog._message(("local", plan), generation=1)
        assert dialog.preview.count() == 0
        page.session.generation += 1
        dialog._message(("local", plan), generation=2)
        assert dialog.preview.count() == 0
        page.session.generation -= 1
        dialog.reject()
        dialog._message(("local", plan), generation=dialog._run_generation)
        assert dialog.preview.count() == 0
    finally:
        dialog.reject()


def test_closed_dialog_drops_a_real_delayed_worker_response(page, monkeypatch):
    from twobyteasr.studio import link_caption_cleanup
    from twobyteasr.app import api_key_explainer
    started, release, returned = threading.Event(), threading.Event(), threading.Event()
    def delayed(source, ids, options, settings=None, **kwargs):
        started.set()
        release.wait(3)
        returned.set()
        cue = source.cues[1]
        return [TextOccurrence(cue.id, cue.start_ms, cue.text, cue.text + ".", (0, len(cue.text)))]
    monkeypatch.setattr(link_caption_cleanup, "request_text_cleanup", delayed)
    monkeypatch.setattr(api_key_explainer, "ask_for_key_if_missing", lambda *a, **k: False)
    dialog = AiCleanupDialog(page, page)
    try:
        for box in dialog.local_boxes.values(): box.setChecked(False)
        dialog._do_ai_preview()
        assert started.wait(3)
        dialog.reject()
        page.project = imported_as_before()
        before = canonical(page.project)
        release.set()
        assert returned.wait(3)
        for _ in range(5):
            time.sleep(.01)
            QApplication.processEvents()
        assert canonical(page.project) == before and not page.undo_stack.count()
        assert dialog._project is None and dialog._preview_binding is None
        assert dialog._runner.mailbox.empty()
    finally:
        release.set()
        dialog.reject()


def test_translation_entry_carries_scope_and_target_without_editing(page, monkeypatch):
    selected = [page.project.cues[1].id, page.project.cues[2].id]
    monkeypatch.setattr(page, "selected_cue_ids", lambda: selected)
    opened = []
    monkeypatch.setattr(page, "_open_translation_dialog", lambda **kw: opened.append(kw))
    dialog = AiCleanupDialog(page, page)
    before = canonical(page.project)
    try:
        assert dialog.translation_target.currentData() == "zh-Hans"
        dialog.ai_scope.setCurrentIndex(dialog.ai_scope.findData(SCOPE_SELECTED))
        dialog.translation_target.setCurrentIndex(dialog.translation_target.findData("ja"))
        QTest.mouseClick(dialog.translation_button, Qt.LeftButton)
        QApplication.processEvents()
        assert opened == [dict(scope="selected", cue_ids=tuple(selected), target="ja")]
        assert canonical(page.project) == before and page.undo_stack.count() == 0
    finally:
        dialog.reject()


def test_retired_preview_click_does_not_select_in_a_new_project(page, monkeypatch):
    dialog = prepared(page)
    selections = []
    monkeypatch.setattr(page, "select_cue", selections.append)
    try:
        page.project = imported_as_before()
        dialog._preview_item_clicked(dialog.preview.item(0))
        assert selections == []
    finally:
        dialog.reject()


def test_translation_dialog_honors_explicit_scope_and_target(page):
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
    ids = [page.project.cues[2].id]
    dialog = SubtitleTranslationDialog(page, page, scope="selected", cue_ids=ids, target="zh-Hant")
    try:
        assert dialog._scope_ids() == ids and dialog._target() == "zh-Hant"
    finally:
        dialog.close()


def test_deleted_preview_item_callback_never_dereferences_native_item(page, monkeypatch):
    from shiboken6 import isValid
    dialog = prepared(page)
    selected = []
    monkeypatch.setattr(page, 'select_cue', selected.append)
    try:
        previous = dialog.preview.item(0)
        dialog._clear_rows()
        assert not isValid(previous)
        dialog._preview_item_clicked(previous)
        assert selected == []
    finally:
        dialog.reject()
