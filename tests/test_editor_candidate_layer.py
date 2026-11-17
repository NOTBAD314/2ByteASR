"""Candidate selection, scope, stale-target and local undo contracts."""
from PySide6.QtCore import Qt,QEvent
from PySide6.QtGui import QKeyEvent,QInputMethodEvent,QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tests.test_editor_download_repair import page, select

def shifted(widget,key):QTest.keyClick(widget,key,Qt.ShiftModifier)

def test_select_then_apply_then_body_and_undo(page):
    e=page.subtitle_edit_input;select(page,1,2);before=e.toPlainText()
    shifted(e,Qt.Key_F)
    v=page.caption_suggestion_text
    assert v.current_row().row.options[v.selected[1]].text=='它'
    assert e.toPlainText()==before[:1]+'它'+before[2:]
    assert page._caption_draft and page.project.cues[0].text==before
    assert v.current_row().row.options[v.selected[1]].text=='它'
    shifted(QApplication.focusWidget(),Qt.Key_S)
    assert e.hasFocus() and v.isHidden() and page.subtitle_edit_card.bubble.isHidden()
    assert page._caption_draft.target.cue_id=='a'
    QTest.keyClick(e,Qt.Key_Z,Qt.ControlModifier)
    assert e.toPlainText()==before

def test_wrap_same_row_highlight_applied_not_current_check(page):
    e=page.subtitle_edit_input;select(page,3,4);before=e.toPlainText()
    shifted(e,Qt.Key_F);v=page.caption_suggestion_text
    assert v.selected[1]==1 and e.toPlainText()==before[:3]+'她'+before[4:]
    shifted(QApplication.focusWidget(),Qt.Key_A)
    assert v.selected[1]==0
    shifted(QApplication.focusWidget(),Qt.Key_A)
    assert v.selected[1]==2
    shifted(QApplication.focusWidget(),Qt.Key_E)
    assert page._caption_draft is None
    assert page.project.cues[0].text==before[:3]+'她'+before[4:]

def test_unconfirmed_return_preserves_text_and_target(page):
    e=page.subtitle_edit_input;select(page,1,2);before=e.toPlainText();target=page._caption_draft.target
    shifted(e,Qt.Key_F);shifted(QApplication.focusWidget(),Qt.Key_S)
    assert e.toPlainText()==before[:1]+'它'+before[2:] and page._caption_draft.target==target
    assert e.textCursor().selectedText()=='它'
    assert e.document().isUndoAvailable()

def test_input_repeat_stale_and_retired_keys(page):
    e=page.subtitle_edit_input;select(page,1,2);before=e.toPlainText()
    shifted(e,Qt.Key_F);v=page.caption_suggestion_text;choice=v.selected
    QApplication.sendEvent(QApplication.focusWidget(),QKeyEvent(QEvent.KeyPress,Qt.Key_F,Qt.ShiftModifier,'F',True))
    assert v.selected==choice and e.toPlainText()==before[:1]+'它'+before[2:]
    e.setPlainText('没有代称 ABC');select(page,0)
    assert not page._apply_editor_suggestion()
    assert page._caption_editor_key(QKeyEvent(QEvent.KeyPress,Qt.Key_F,Qt.ShiftModifier,'F'),text_focus=True)
    for key,text in ((Qt.Key_1,'!'),(Qt.Key_2,'@'),(Qt.Key_3,'#'),(Qt.Key_A,'A'),(Qt.Key_D,'D')):
        assert not page._caption_editor_key(QKeyEvent(QEvent.KeyPress,key,Qt.ShiftModifier,text),text_focus=True)
    e.setPlainText(before);select(page,1,2)
    QApplication.sendEvent(e,QInputMethodEvent('ni',[]))
    assert page._caption_editor_key(QKeyEvent(QEvent.KeyPress,Qt.Key_F,Qt.ShiftModifier,'F'),text_focus=True)
    assert e._preediting
    composing_text=e.toPlainText()
    assert page._caption_editor_key(QKeyEvent(QEvent.KeyPress,Qt.Key_E,Qt.ShiftModifier,'E'),text_focus=True)
    assert e.toPlainText()==composing_text
    QApplication.sendEvent(e,QInputMethodEvent('',[]))

def test_retired_registry_bindings():
    from twobyteasr.studio.shortcut_registry import load_values
    values,*_=load_values({'editor_flip_pronoun':'Shift+P','editor_pronoun_he':'Shift+1'})
    assert not values.get('editor_flip_pronoun') and not values.get('editor_pronoun_he')


def test_s_dismisses_visible_caret_candidate_without_first_navigating(page):
    e=page.subtitle_edit_input;select(page,1,2);page._refresh_editor_suggestions()
    before=e.toPlainText();assert not page.caption_suggestion_text.isHidden()
    shifted(e,Qt.Key_S)
    assert e.toPlainText()==before and e.hasFocus() and page.caption_suggestion_text.isHidden()
