"""Exit and IME recovery exercise the real floating editor event routes."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import StudioCue
from tests.test_review_replay_and_window_bounds import _page


@pytest.fixture
def page(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 0, 2000, '他来了'), StudioCue('b', 2100, 4000, '第二条')])
    page.select_cue('a')
    page._open_caption_editor('a', 'original')
    QTest.qWait(30)
    yield page
    page.close_page()
    page.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('key', [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_enter_commits_bound_target_and_follows(page, key):
    page.subtitle_edit_input.setPlainText('编辑后')
    page.select_cue('b')
    QTest.keyClick(page.subtitle_edit_input, key)
    assert page.project.cues[0].text == '编辑后'
    assert page.project.cues[1].text == '第二条'
    assert not page._caption_edit_locked and page.subtitle_edit_dock.isVisible()


def test_abandoned_preedit_escape_then_escape_can_exit(page):
    editor = page.subtitle_edit_input
    QApplication.sendEvent(editor, QInputMethodEvent('ni', []))
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert page._caption_draft is not None  # cancel composition first
    assert not editor._preediting
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert page._caption_draft is None and not page.subtitle_edit_card.isVisible()
    assert not page.position_overlay._inline_editing


def test_candidate_enter_is_not_caption_submit_and_newline_survives(page):
    editor = page.subtitle_edit_input
    QApplication.sendEvent(editor, QInputMethodEvent('ni', []))
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert page._caption_draft is not None
    assert not editor._preediting
    event = QInputMethodEvent(); event.setCommitString('你')
    QApplication.sendEvent(editor, event)
    QTest.keyClick(editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert '\n' in editor.toPlainText() and page._caption_draft is not None
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert not page._caption_edit_locked and page.subtitle_edit_dock.isVisible()


def test_ime_commit_before_candidate_key_does_not_submit_caption(page):
    editor = page.subtitle_edit_input
    QApplication.sendEvent(editor, QInputMethodEvent('ni', []))
    commit = QInputMethodEvent();commit.setCommitString('你')
    QApplication.sendEvent(editor,commit)
    QTest.keyClick(editor,Qt.Key.Key_Return)
    assert page._caption_draft is not None and '你' in editor.toPlainText()
    QTest.qWait(5)
    QTest.keyClick(editor,Qt.Key.Key_Return)
    assert not page._caption_edit_locked and page.subtitle_edit_dock.isVisible()


@pytest.mark.parametrize('action', ['caption_confirm_button', 'caption_cancel_button', 'caption_close_button'])
def test_mouse_exits_and_repeated_open_has_no_interaction_blocker(page, action):
    for _ in range(10):
        page.subtitle_edit_input.setPlainText('修改')
        QTest.mouseClick(getattr(page, action), Qt.MouseButton.LeftButton)
        if action == 'caption_confirm_button':
            assert not page._caption_edit_locked and page.subtitle_edit_dock.isVisible()
            page._end_caption_editor(keep_open=False)
        else:
            assert page._canvas_editor is None and page._caption_draft is None
            assert not page.subtitle_edit_card.isVisible() and not page.position_overlay._inline_editing
        page.select_cue('b'); page.select_cue('a')
        page._open_caption_editor('a', 'original')
    if action == 'caption_cancel_button':
        assert page.project.cues[0].text == '他来了'
    else:
        assert page.project.cues[0].text == '修改'


def test_commit_error_keeps_actionable_cancel(page, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError('写入失败的具体原因')
    monkeypatch.setattr(type(page.cue_controller), 'set_text', broken)
    page.subtitle_edit_input.setPlainText('修改')
    QTest.mouseClick(page.caption_confirm_button, Qt.MouseButton.LeftButton)
    assert page._caption_draft is not None
    assert '输入内容已保留' in page.caption_editor_error.text()
    assert '具体原因' in page.subtitle_edit_card.error_detail.text()
    assert not page.subtitle_edit_card.error_detail.isVisible()
    QTest.mouseClick(page.caption_close_button, Qt.MouseButton.LeftButton)
    assert page._caption_draft is not None  # ordinary close retries, never discards
    QTest.mouseClick(page.caption_cancel_button, Qt.MouseButton.LeftButton)
    assert page._caption_draft is None and page._canvas_editor is None


def test_buttons_focus_keys_and_shift_p_do_not_steal_literal_text(page):
    editor = page.subtitle_edit_input
    QTest.keyClick(editor, Qt.Key.Key_P)
    assert editor.toPlainText().endswith('p')
    editor.setPlainText('他来了')
    QTest.keyClick(editor, Qt.Key.Key_P, Qt.KeyboardModifier.ShiftModifier)
    assert editor.toPlainText() == '她来了'
    page.caption_pronoun_button.setFocus()
    QTest.keyClick(page.caption_pronoun_button, Qt.Key.Key_Escape)
    assert page._caption_draft is None
