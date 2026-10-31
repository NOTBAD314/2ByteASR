"""2026-10-21 批量替换 redesign: one compact dialog, keyboard flow, AI 清理 and toolbar moves."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
from twobyteasr.studio import studio_find_replace
from twobyteasr.studio.studio_find_replace import (
    PREVIEW_HTML_ROLE,
    AiCleanupDialog,
    FindReplaceDialog,
)
from twobyteasr.studio.studio_text_tools import TextOccurrence
from twobyteasr.studio.studio_ui import SubtitleStudioPage


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, tmp_path):
    texts = ["尼奈这波打得好", "我觉得尼奈应该先撤，尼奈血不多了", "对面打野在上路", "尼奈的大招还有十秒"]
    project = SubtitleProject(
        media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=60_000),
        cues=[StudioCue(f"c{i}", i * 3000, i * 3000 + 1500, text, speaker_id="S01") for i, text in enumerate(texts)],
    )
    path = save_project(project, tmp_path / "studio.2byteproj")
    studio = SubtitleStudioPage()
    app.processEvents()
    studio.open_project(path)
    app.processEvents()
    yield studio
    studio.close_page()
    studio.deleteLater()
    app.processEvents()


def _texts(studio):
    return [cue.text for cue in studio.session.project.cues]


def _show(app, dialog):
    dialog.show()
    dialog.activateWindow()
    app.processEvents()


def test_dialog_is_find_replace_only(app, page):
    dialog = FindReplaceDialog(page, page)
    try:
        assert not dialog.findChildren(QTabWidget)
        assert not hasattr(dialog, "tabs") and not hasattr(dialog, "punct_combo")
        assert not hasattr(dialog, "terms_libraries") and not hasattr(dialog, "ai_run_button")
        for chip in (dialog.case_box, dialog.word_box, dialog.regex_box, dialog.body_box,
                     dialog.lock_box, dialog.project_entity_box):
            assert chip.isCheckable() and chip.objectName() == "findOptionChip"
        assert dialog.lock_box.isChecked()
        # Clicking an option must not pull the caret out of the field being typed into.
        assert dialog.case_box.focusPolicy() == Qt.FocusPolicy.TabFocus
        assert all(not button.autoDefault() for button in (dialog.next_button, dialog.all_button))
    finally:
        dialog.close()


def test_down_moves_to_replace_up_returns_and_enter_applies(app, page):
    dialog = FindReplaceDialog(page, page)
    try:
        _show(app, dialog)
        dialog.find_edit.setFocus()
        dialog.find_edit.setText("尼奈")  # keyClicks with Chinese text crashes Qt; setText types it
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Down)
        assert QApplication.focusWidget() is dialog.replace_edit
        QTest.keyClick(dialog.replace_edit, Qt.Key.Key_Up)
        assert QApplication.focusWidget() is dialog.find_edit
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Down)
        dialog.replace_edit.setText("她")
        # Enter straight after typing: the live preview has not run yet.
        assert dialog._search_timer.isActive()
        QTest.keyClick(dialog.replace_edit, Qt.Key.Key_Return)
        assert _texts(page) == ["她这波打得好", "我觉得她应该先撤，她血不多了", "对面打野在上路", "她的大招还有十秒"]
        assert page.session.undo_stack.count() == 1
        assert "4" in dialog.status_label.text() and "Ctrl+Z" in dialog.status_label.text()
        # Ready for the next pair.
        assert QApplication.focusWidget() is dialog.find_edit and dialog.find_edit.selectedText() == "尼奈"
        page.session.undo_stack.undo()
        assert _texts(page)[0] == "尼奈这波打得好"
    finally:
        dialog.close()


def test_enter_applies_only_checked_rows_and_rows_show_both_versions(app, page):
    dialog = FindReplaceDialog(page, page)
    try:
        _show(app, dialog)
        dialog.find_edit.setText("尼奈")
        dialog.replace_edit.setText("她")
        dialog._search_timer.stop()
        dialog._do_preview()
        # 2026-10-30 (draft C): one card per cue; two matches in one sentence share it.
        assert dialog.preview.count() == 3
        assert len(dialog._checked_hits()) == 4 and dialog.all_button.text() == "替换 4 处"
        row = dialog.preview.item(0).data(PREVIEW_HTML_ROLE)
        assert "line-through" in row and "尼奈" in row and "她" in row and "00:00.000" in row
        assert "尼奈" in dialog.preview.item(0).text()  # plain text kept for reading and tests
        assert "2 处" in dialog.preview.item(1).data(PREVIEW_HTML_ROLE)
        dialog.preview.item(1).setCheckState(Qt.CheckState.Unchecked)
        assert dialog.all_button.text() == "替换 2 处"
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Enter)
        assert _texts(page) == ["她这波打得好", "我觉得尼奈应该先撤，尼奈血不多了", "对面打野在上路", "她的大招还有十秒"]
        assert page.session.undo_stack.count() == 1
        # The unchecked cue is still offered afterwards, still unticked,
        # so a second Enter does not take it.
        assert dialog.preview.count() == 1
        assert dialog.preview.item(0).checkState() == Qt.CheckState.Unchecked
        assert "Ctrl+Z" in dialog.status_label.text()
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Enter)
        assert _texts(page)[1] == "我觉得尼奈应该先撤，尼奈血不多了"
        assert page.session.undo_stack.count() == 1
    finally:
        dialog.close()


def test_swap_and_select_none(app, page):
    dialog = FindReplaceDialog(page, page)
    try:
        dialog.find_edit.setText("尼奈")
        dialog.replace_edit.setText("她")
        dialog.swap_button.click()
        assert (dialog.find_edit.text(), dialog.replace_edit.text()) == ("她", "尼奈")
        dialog.swap_button.click()
        dialog._search_timer.stop()
        dialog._do_preview()
        dialog.select_none_button.click()
        assert not dialog._checked_hits() and not dialog.all_button.isEnabled()
        dialog.select_all_button.click()
        assert len(dialog._checked_hits()) == 4 and dialog.all_button.isEnabled()
    finally:
        dialog.close()


def test_regex_replacement_is_not_learned(app, page, monkeypatch):
    dialog = FindReplaceDialog(page, page)
    try:
        dialog.find_edit.setText("尼.")
        dialog.replace_edit.setText("她")
        dialog.regex_box.setChecked(True)
        dialog._search_timer.stop()
        dialog._do_preview()
        assert dialog._apply_extras(dialog._checked_hits()) == {"title": "尼."}
        dialog.regex_box.setChecked(False)
        dialog.find_edit.setText("尼奈")
        assert dialog._apply_extras([])["learn_pair"] == ("尼奈", "她")
    finally:
        dialog.close()


def test_regex_replaces_trailing_spaces_now_that_text_tidy_is_gone(app, page):
    """文本整理 left the dialog (2026-10-21); a regex replacement still trims cue ends."""
    project = page.session.project
    project.cues[2].text = "对面打野在上路  "
    project.cues[3].text = "尼奈的大招还有十秒 "
    dialog = FindReplaceDialog(page, page)
    try:
        dialog.regex_box.setChecked(True)
        dialog.find_edit.setText(r"\s+$")
        dialog.replace_edit.setText("")
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Return)
        assert _texts(page)[2:4] == ["对面打野在上路", "尼奈的大招还有十秒"]
        assert page.session.undo_stack.count() == 1
    finally:
        dialog.close()


def test_ai_cleanup_dialog_previews_and_applies(app, page, monkeypatch):
    asked = []

    def cleanup(project, cue_ids, options, settings=None, **_kwargs):
        asked.append((list(cue_ids), list(options)))
        cue = project.cues[0]
        return [TextOccurrence(cue.id, cue.start_ms, cue.text, "尼奈这波打得很好", (0, len(cue.text)))]

    # 2026-10-26: AI 清理 runs in the background for every project (batch by batch).
    from twobyteasr.studio import link_caption_cleanup
    monkeypatch.setattr(link_caption_cleanup, "request_text_cleanup", cleanup)
    from twobyteasr.app import api_key_explainer
    monkeypatch.setattr(api_key_explainer, "ask_for_key_if_missing", lambda *a, **k: False)
    dialog = AiCleanupDialog(page, page)
    try:
        assert not dialog.findChildren(QTabWidget) and not hasattr(dialog, "find_edit")
        assert [key for key, box in dialog.ai_option_boxes.items() if box.isChecked()] == ["fillers", "repeats", "punctuation"]
        # 2026-10-26 (design A): 口癖 asks for fillers and particles together.
        dialog.ai_option_boxes["glossary"].setChecked(True)
        dialog.ai_run_button.click()
        for _ in range(100):
            if dialog.preview.count() and not dialog._cleanup_running:
                break
            QTest.qWait(20)
        assert asked == [(["c0", "c1", "c2", "c3"], ["fillers", "particles", "repeats", "glossary", "punctuation"])]
        assert dialog.preview.count() == 1 and dialog.all_button.isEnabled()
        dialog.all_button.click()
        assert _texts(page)[0] == "尼奈这波打得很好" and page.session.undo_stack.count() == 1
        assert dialog.preview.count() == 0 and "Ctrl+Z" in dialog.status_label.text()
    finally:
        dialog.close()


def test_cleanup_beside_proofread_script_in_overflow_report_has_words(app, page):
    assert page.cue_cleanup_button.parentWidget() is page.cue_proofread_button.parentWidget()
    row = page.cue_proofread_button.parentWidget().layout()
    title_row = next(row.itemAt(i).layout() for i in range(row.count())
                     if row.itemAt(i).layout() is not None
                     and row.itemAt(i).layout().indexOf(page.cue_proofread_button) >= 0)
    assert title_row.indexOf(page.cue_cleanup_button) == title_row.indexOf(page.cue_proofread_button) + 1
    bar = page.studio_toolbar
    # 2026-10-22 (user, later than this round): 简繁 is a submenu of 双语 / 翻译, no button.
    assert not hasattr(page, "chinese_script_button")
    assert page.chinese_script_menu.menuAction() in page.bilingual_toggle_button.menu().actions()
    report = page.report_problem_button
    assert report.text() == "回报问题" and report.property("emphasis") == "warning" and bar.isAncestorOf(report)
    # 2026-10-21 (user): 回报问题 right of 双语; 压制成片 always the last command, so ⋯ ends
    # the middle commands. Since 2026-10-23 the commands sit in tonal tracks (design B).
    from PySide6.QtWidgets import QFrame, QToolButton
    layout = bar.layout()
    tool_track = page.bilingual_toggle_button.parentWidget()
    export_track = page.studio_render_button.parentWidget()
    assert tool_track.members.index(report) == tool_track.members.index(page.bilingual_toggle_button) + 1
    overflow = next(b for b in bar.findChildren(QToolButton) if b.property("commandSource") == "更多工作区操作")
    controls = bar.findChild(QFrame, "studioWindowControls")
    assert export_track.members[-1] is page.studio_render_button and page.studio_export_button in export_track.members
    assert layout.indexOf(overflow) == layout.indexOf(export_track) - 1
    assert layout.indexOf(export_track) == layout.indexOf(controls) - 1


def test_open_ai_cleanup_from_the_cue_list(app, page, monkeypatch):
    opened = []
    monkeypatch.setattr(AiCleanupDialog, "exec", lambda self: opened.append(type(self)) or 0)
    page.cue_cleanup_button.click()
    assert opened == [AiCleanupDialog]
