"""Approved A editor: keyboard context, transactions, Unicode and layout ownership."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QFont, QInputMethodEvent, QPalette, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.studio.caption_editor import qt_position
from twobyteasr.subtitle_rules.review_suggestions import ReviewSuggestion, SuggestionOption


@pytest.fixture
def page(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, [
        StudioCue('a', 0, 5000, '她说在营第等一下，吉它留在营地。'),
        StudioCue('b', 5100, 8000, '第二条保持不变')])
    page.select_cue('a')
    page._open_caption_editor('a', 'original')
    QTest.qWait(35)
    yield page
    page.close_page()
    page.deleteLater()
    app.processEvents()


def key(widget, value):
    QTest.keyClick(widget, value, Qt.KeyboardModifier.ShiftModifier)


def seed_candidates(page, monkeypatch):
    from twobyteasr.studio import caption_editor as module
    monkeypatch.setattr(module, 'review_suggestions', lambda *args, **kwargs: [])
    monkeypatch.setattr(module, 'current_issue_view', lambda *args: SimpleNamespace(for_cue=lambda *a, **kw: ()))
    monkeypatch.setattr(page, '_review_suggestions_for', lambda *args: ())
    text = page.subtitle_edit_input.toPlainText()
    def row(word, *options):
        start = text.index(word)
        return ReviewSuggestion(start, start+len(word), word, tuple(SuggestionOption(v) for v in options), 'model')
    draft = page._caption_draft
    draft.suggestions = (row('营第', '营地', '营区'), row('吉它', '吉他'))
    draft.suggestion_text = text
    page._refresh_editor_suggestions()
    return text


def test_shift_r_in_draft_confirms_bound_caption_and_closes(page):
    page.subtitle_edit_input.setPlainText('原文已改好')
    page.select_cue('b')
    key(page.subtitle_edit_input, Qt.Key.Key_R)
    assert page.project.cues[0].text == '原文已改好'
    assert page.project.cues[1].text == '第二条保持不变'
    assert page._caption_draft is None and not page.subtitle_edit_dock.isVisible()
    page.undo_stack.undo()
    assert page.project.cues[0].text == '她说在营第等一下，吉它留在营地。'
    page.undo_stack.redo()
    assert page.project.cues[0].text == '原文已改好'


def test_shift_ad_moves_one_unicode_character_without_selection(page):
    editor = page.subtitle_edit_input
    editor.setPlainText('甲😀乙\n丙')
    cursor = editor.textCursor(); cursor.setPosition(0); editor.setTextCursor(cursor)
    for position in (1, 3, 4, 5):
        key(editor, Qt.Key.Key_D)
        assert editor.textCursor().position() == position
        assert not editor.textCursor().hasSelection()
    key(editor, Qt.Key.Key_A)
    assert editor.textCursor().position() == 4
    assert editor.toPlainText() == '甲😀乙\n丙'


@pytest.mark.parametrize('direction,expected', [(Qt.Key.Key_A, 0), (Qt.Key.Key_D, 3)])
def test_shift_ad_collapses_existing_selection_towards_direction(page, direction, expected):
    editor = page.subtitle_edit_input
    editor.setPlainText('甲😀乙')
    cursor = editor.textCursor();cursor.setPosition(0)
    cursor.setPosition(3, QTextCursor.MoveMode.KeepAnchor);editor.setTextCursor(cursor)
    key(editor, direction)
    assert editor.textCursor().position() == expected and not editor.textCursor().hasSelection()


def test_complete_left_hand_candidate_path_then_confirm(page, monkeypatch):
    before = seed_candidates(page, monkeypatch)
    view = page.caption_suggestion_text
    key(page.subtitle_edit_input, Qt.Key.Key_W)
    assert view.owns_focus() and view.selected == (0, 0)
    key(QApplication.focusWidget(), Qt.Key.Key_D)
    assert view.selected == (0, 1)
    key(QApplication.focusWidget(), Qt.Key.Key_D)
    assert view.selected == (1, 0)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Space)
    assert page._caption_draft is not None
    assert page.subtitle_edit_input.toPlainText() == before.replace('吉它', '吉他')
    assert page.project.cues[0].text == before
    assert view.owns_focus() and len(page._caption_draft.suggestions) == 1
    assert view.selected == (-1, -1)  # current row is handled, not the next proposal
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Space)
    assert page.subtitle_edit_input.toPlainText() == before.replace('吉它', '吉他')
    key(QApplication.focusWidget(), Qt.Key.Key_D)
    assert page.subtitle_edit_input.hasFocus()
    assert not page.subtitle_edit_input.textCursor().hasSelection()
    key(page.subtitle_edit_input, Qt.Key.Key_R)
    assert page._caption_draft is None and not page.subtitle_edit_dock.isVisible()
    assert page.project.cues[0].text == before.replace('吉它', '吉他')


def test_candidate_left_up_and_mouse_apply_stay_in_current_draft(page, monkeypatch):
    before = seed_candidates(page, monkeypatch)
    view = page.caption_suggestion_text
    key(page.subtitle_edit_input, Qt.Key.Key_W)
    key(QApplication.focusWidget(), Qt.Key.Key_D)
    key(QApplication.focusWidget(), Qt.Key.Key_A)
    assert view.selected == (0, 0)
    key(QApplication.focusWidget(), Qt.Key.Key_D)
    key(QApplication.focusWidget(), Qt.Key.Key_D)
    key(QApplication.focusWidget(), Qt.Key.Key_W)
    assert view.selected == (0, 0)
    button = view.candidate_button(0, 1)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert page.subtitle_edit_input.toPlainText() == before.replace('营第', '营区')
    assert len(page._caption_draft.suggestions) == 1 and page.project.cues[0].text == before


def test_manual_text_cannot_apply_old_offsets_and_shift_r_confirms_current_text(page, monkeypatch):
    seed_candidates(page, monkeypatch)
    editor = page.subtitle_edit_input
    editor.setPlainText('前面插入新内容：营第和吉它')
    assert not page._apply_editor_suggestion(0, 0)
    key(editor, Qt.Key.Key_R)
    assert page.project.cues[0].text == '前面插入新内容：营第和吉它'
    assert page._caption_draft is None and not page.subtitle_edit_dock.isVisible()


def test_tool_panel_is_near_video_bottom_and_text_is_bold_left_aligned(page):
    card, host = page.subtitle_edit_card, page.video_overlay_host
    assert card.parentWidget() is page.subtitle_edit_dock
    assert not host.isAncestorOf(card)
    QTest.qWait(10)
    card_top = card.mapToGlobal(QPoint()).y()
    host_top = host.mapToGlobal(QPoint()).y()
    assert page.subtitle_edit_dock.isWindow() and card_top >= host_top
    dock=page.subtitle_edit_dock
    row_top=page.timeline.mapToGlobal(QPoint(0,page.timeline.RULER_HEIGHT)).y()
    assert abs(dock.y()+dock.height()-(row_top-8))<=1
    assert dock.y()+dock.height()//2>host_top+host.height()//2
    assert page.subtitle_edit_input.font().weight() >= QFont.Weight.DemiBold
    assert page.subtitle_edit_input.font().pixelSize() == 18
    assert page.subtitle_edit_input.document().defaultTextOption().alignment() & Qt.AlignmentFlag.AlignLeft
    assert page.subtitle_edit_input.palette().color(QPalette.ColorRole.Base) != card.palette().color(QPalette.ColorRole.Window)


def test_failure_is_readable_retains_text_and_has_collapsed_technical_details(page, monkeypatch):
    kind = type(page.cue_controller)
    original = kind.set_text
    def broken(*args, **kwargs):
        raise ValueError('isolated write validation failure')
    monkeypatch.setattr(kind, 'set_text', broken)
    page.subtitle_edit_input.setPlainText('失败后仍保留')
    key(page.subtitle_edit_input, Qt.Key.Key_R)
    panel = page.subtitle_edit_card
    assert page._caption_draft is not None
    assert panel.editor.toPlainText() == '失败后仍保留'
    assert '输入内容已保留' in panel.error_label.text()
    assert 'isolated' not in panel.error_label.text()
    assert 'isolated' in panel.error_detail.text() and not panel.error_detail.isVisible()
    monkeypatch.setattr(kind, 'set_text', original)
    key(page.subtitle_edit_input, Qt.Key.Key_R)
    assert not page._caption_edit_locked and page.project.cues[0].text == '失败后仍保留'


def test_shift_r_during_preedit_does_not_confirm_caption(page):
    editor = page.subtitle_edit_input
    QApplication.sendEvent(editor, QInputMethodEvent('ni', []))
    key(editor, Qt.Key.Key_R)
    assert page._caption_draft is not None
    commit = QInputMethodEvent();commit.setCommitString('你')
    QApplication.sendEvent(editor, commit)
    QTest.qWait(5)
    key(editor, Qt.Key.Key_R)
    assert not page._caption_edit_locked and '你' in page.project.cues[0].text


@pytest.mark.parametrize('button', ['caption_cancel_button'])
def test_mouse_exit_works_during_preedit_without_result_page(page, button):
    before = page.project.cues[0].text
    page.subtitle_edit_input.setPlainText('放弃这次编辑')
    QApplication.sendEvent(page.subtitle_edit_input, QInputMethodEvent('ni', []))
    QTest.mouseClick(getattr(page, button), Qt.MouseButton.LeftButton)
    assert page._caption_draft is None and page.project.cues[0].text == before
    assert not page.subtitle_edit_dock.isVisible()


def test_close_cannot_discard_uncommitted_composition(page):
    editor = page.subtitle_edit_input
    editor.setPlainText('需要保存')
    QApplication.sendEvent(editor, QInputMethodEvent('ni', []))
    QTest.mouseClick(page.caption_close_button, Qt.MouseButton.LeftButton)
    assert page._caption_draft is not None and editor.toPlainText() == '需要保存'
    commit = QInputMethodEvent();commit.setCommitString('你')
    QApplication.sendEvent(editor, commit)
    QTest.mouseClick(page.caption_close_button, Qt.MouseButton.LeftButton)
    assert page._caption_draft is None and '你' in page.project.cues[0].text


def test_pronoun_target_is_whole_draft_even_away_from_caret(page):
    editor = page.subtitle_edit_input
    editor.setPlainText('她在营地等其他人，吉他在门口。')
    editor.moveCursor(QTextCursor.MoveOperation.End)
    key(editor, Qt.Key.Key_P)
    assert editor.toPlainText() == '他在营地等其他人，吉他在门口。'
    cursor = editor.textCursor();cursor.setPosition(qt_position(editor.toPlainText(), 0));editor.setTextCursor(cursor)
    key(editor, Qt.Key.Key_P)
    assert editor.toPlainText().startswith('她在')


def test_hidden_panel_supports_no_argument_theme_refresh_callback(page):
    from twobyteasr.design.theme_manager import apply_theme, theme_key
    previous = theme_key()
    try:
        page._set_subtitle_editor_visible(False)
        apply_theme('grape')
        page.subtitle_edit_card.refresh_theme_palette()
        page._set_subtitle_editor_visible(True)
        QTest.qWait(5)
        assert page.subtitle_edit_card.isVisible()
        assert page.subtitle_edit_input.font().weight() >= QFont.Weight.DemiBold
        assert page.subtitle_edit_input.palette().color(QPalette.ColorRole.Base) != page.subtitle_edit_card.palette().color(QPalette.ColorRole.Window)
    finally:
        apply_theme(previous)
