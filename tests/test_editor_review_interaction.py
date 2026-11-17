"""Session shortcuts and real click-to-fix commands, including the empty state."""
import pytest
from PySide6.QtCore import Qt, QEvent, QPoint
from PySide6.QtGui import QKeyEvent, QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from tests.test_editor_download_repair import page, select
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue, save_project, load_project
from twobyteasr.subtitle_rules.pronouns import edit_pronoun_target


def focus(widget):
    QApplication.setActiveWindow(widget.window()); widget.setFocus(); QApplication.processEvents()


def key(widget, value):
    QTest.keyClick(widget, value, Qt.ShiftModifier)


@pytest.mark.parametrize('caret', [0, 9, 7])
def test_no_selection_direct_cycle_keeps_caret_focus_and_draft(page, caret):
    e = page.subtitle_edit_input
    e.setPlainText('她打不出什么东西'); select(page, caret if caret < 9 else len(e.toPlainText()))
    focus(e); pos = e.textCursor().position()
    for value in '它他她':
        key(e, Qt.Key_F)
        assert e.toPlainText() == value + '打不出什么东西'
        assert e.hasFocus() and not e.textCursor().hasSelection()
        assert e.textCursor().position() == pos
        assert page.project.cues[0].text.startswith('😀她')
        row = page.caption_suggestion_text.current_row().row
        assert row.start == 0 and row.options[page.caption_suggestion_text.selected[1]].text == value
    assert e.extraSelections()


@pytest.mark.parametrize('owner', ['body', 'toolbar', 'candidate', 'review'])
def test_single_shift_e_commits_from_every_session_owner(page, owner, tmp_path):
    e = page.subtitle_edit_input; select(page, 1, 2); focus(e)
    key(e, Qt.Key_F); expected = e.toPlainText()
    if owner == 'toolbar': target = page.caption_pronoun_button
    elif owner == 'candidate':
        page._show_editor_pronouns(); target = QApplication.focusWidget()
        # Changing a candidate highlight must not implicitly accept it on E.
        key(target, Qt.Key_D); target = QApplication.focusWidget()
    elif owner == 'review':
        page._review_mode = True; page.review_summary_strip.show()
        target = page.review_summary_text
        target.setFocusPolicy(Qt.StrongFocus)
    else: target = e
    focus(target); key(target, Qt.Key_E)
    assert page._caption_draft is None and not page.subtitle_edit_dock.isVisible()
    assert not page._caption_following and page.project.cues[0].text == expected
    page._open_caption_editor('a', 'original')
    assert e.toPlainText() == expected
    page._cancel_canvas_inline_edit()
    path = save_project(page.project, tmp_path / 'saved.2byteproj')
    assert load_project(path).cues[0].text == expected


@pytest.mark.parametrize('trigger', ['enter', 'shift_e', 'button'])
def test_all_confirm_commands_save_same_draft_and_undo(page, trigger):
    e = page.subtitle_edit_input; before = page.project.cues[0].text
    select(page, 1, 2); focus(e); key(e, Qt.Key_F)
    expected = e.toPlainText(); index = page.undo_stack.index()
    if trigger == 'enter': QTest.keyClick(e, Qt.Key_Return)
    elif trigger == 'shift_e': key(e, Qt.Key_E)
    else: page.caption_confirm_button.click()
    assert page.project.cues[0].text == expected and page._caption_draft is None
    assert page.undo_stack.index() == index + 1
    page.undo_stack.undo(); assert page.project.cues[0].text == before
    page.undo_stack.redo(); assert page.project.cues[0].text == expected


def test_target_stays_single_and_tracks_document_edits(page):
    e = page.subtitle_edit_input
    e.setPlainText('他告诉她们今天晚点来，其他人弹吉他。'); select(page, 3, 4); focus(e)
    key(e, Qt.Key_F); assert e.toPlainText().startswith('他告诉它们')
    select(page, len(e.toPlainText())); key(e, Qt.Key_F)
    assert e.toPlainText().startswith('他告诉他们')
    # A manual prefix insertion shifts the live target, it does not retarget.
    select(page, 2); e.insertPlainText('今天'); select(page, len(e.toPlainText()))
    key(e, Qt.Key_F); assert e.toPlainText().startswith('他告今天诉她们')
    select(page, 0, 1); key(e, Qt.Key_F)
    assert e.toPlainText().startswith('她告今天诉她们')
    assert e.toPlainText().endswith('其他人弹吉他。')


def test_repeat_no_pronoun_cancel_and_preedit(page):
    e = page.subtitle_edit_input; focus(e); select(page, 1, 2)
    key(e, Qt.Key_F); before = e.toPlainText()
    QApplication.sendEvent(e, QKeyEvent(QEvent.KeyPress, Qt.Key_F, Qt.ShiftModifier, 'F', True))
    assert e.toPlainText() == before
    QTest.keyClick(e, Qt.Key_Z, Qt.ControlModifier); assert e.toPlainText() != before
    QTest.keyClick(e, Qt.Key_Y, Qt.ControlModifier); assert e.toPlainText() == before
    e.setPlainText('其他人弹吉他，没有代称'); select(page, 6)
    key(e, Qt.Key_F); assert e.toPlainText() == '其他人弹吉他，没有代称'
    QApplication.sendEvent(e, QInputMethodEvent('ni', [])); before = e.toPlainText()
    key(e, Qt.Key_F); assert e._preediting and e.toPlainText() == before
    # First confirmation finishes composition, never submits the subtitle.
    key(e, Qt.Key_E); assert page._caption_draft is not None
    QTest.keyClick(e, Qt.Key_Escape)
    assert page._caption_draft is None and page.project.cues[0].text.startswith('😀她')
    assert not page._caption_editor_key(QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.ShiftModifier, 'E'))


def test_toolbar_f_after_dismissal_and_candidates_keep_one_target(page):
    e=page.subtitle_edit_input; e.setPlainText('他告诉她今天晚点来');select(page,6);focus(e)
    key(e,Qt.Key_F);assert e.toPlainText().startswith('他告诉它')
    focus(page.caption_pronoun_button); key(page.caption_pronoun_button,Qt.Key_F)
    assert e.toPlainText().startswith('他告诉他') and page.caption_pronoun_button.hasFocus()
    key(page.caption_pronoun_button,Qt.Key_D)
    assert page.caption_suggestion_text.candidate_mode
    key(QApplication.focusWidget(),Qt.Key_S)
    before=e.toPlainText();assert page.caption_suggestion_text.dismissed
    key(e,Qt.Key_F)
    assert e.toPlainText().startswith('他告诉她') and page.caption_suggestion_text.dismissed
    assert e.hasFocus()
    current=e.toPlainText();key(e,Qt.Key_S)
    assert e.toPlainText()==current and e.hasFocus()


@pytest.mark.parametrize('text,position,previous,expected', [
    ('他告诉她', 2, None, 0), ('他告诉她', 4, None, 3),
    ('她们在弹吉他', 6, None, 0), ('其他和吉他', 1, None, None),
    ('他告诉她', 4, 0, 0), ('她告诉它', 2, 99, 0)])
def test_shared_target_rules(text, position, previous, expected):
    assert edit_pronoun_target(text, position, previous=previous) == expected


def test_review_real_red_click_keeps_widgets_offsets_and_empty_exit(tmp_path, monkeypatch):
    from twobyteasr.studio import studio_review_ui
    from twobyteasr.studio.studio_cards import ReviewCandidateCard
    from twobyteasr.subtitle_rules.studio_qc import QCCandidate
    app, p = _page(tmp_path, monkeypatch, [StudioCue('a', 0, 4000, '坏猫在这里等错狗'), StudioCue('b', 5000, 8000, '下一句')])
    monkeypatch.setattr(studio_review_ui, 'review_candidates', lambda project, cue:
        (QCCandidate(cue.text, ('Current',)), QCCandidate('可爱猫在这里等好狗', ())) if cue.id == 'a'
        else (QCCandidate(cue.text, ('Current',)),))
    try:
        p._review_all_explicit = (p.project.project_id, p.session.generation)
        p._set_review_mode(True); p.select_cue('a'); p._refresh_review_summary_strip(); app.processEvents()
        card = p._review_inline_card
        assert isinstance(card, ReviewCandidateCard) and len(p._review_suggestions) == 2
        original = p.project.cues[0].text; clock = p.timeline.playhead_ms
        binding = p._review_suggestions_binding
        def click_first():
            rect = card.text_label.chip_rects()[(0, 0)]
            QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, card.text_label.mapTo(card, rect.center().toPoint()))
            app.processEvents()
        click_first()
        assert p.project.cues[0].text == '可爱猫在这里等错狗'
        assert p._review_inline_card is card and getattr(p, '_canvas_editor', None) is None
        assert getattr(p, '_caption_draft', None) is None and not p.subtitle_edit_dock.isVisible()
        assert p.selected_cue_id == 'a' and p.timeline.playhead_ms == clock
        assert len(p._review_suggestions) == 1 and p._review_suggestions[0].start == 7
        index = p.undo_stack.index()
        assert not p._apply_review_suggestion(0, binding=binding) and p.undo_stack.index() == index
        click_first()
        assert p.project.cues[0].text == '可爱猫在这里等好狗'
        assert not p._review_suggestions and p._review_inline_card is card
        p.undo_stack.undo(); assert p.project.cues[0].text == '可爱猫在这里等错狗'
        p.undo_stack.undo(); assert p.project.cues[0].text == original
        p.undo_stack.redo(); p.undo_stack.redo()
        for exit_kind in ('enter', 'shift_e', 'cancel', 'close', 'return'):
            p._open_caption_editor('a', 'original'); focus(p.subtitle_edit_input)
            p.subtitle_edit_input.insertPlainText('改')
            if exit_kind == 'enter': QTest.keyClick(p.subtitle_edit_input, Qt.Key_Return)
            elif exit_kind == 'shift_e': key(p.subtitle_edit_input, Qt.Key_E)
            elif exit_kind == 'cancel': QTest.keyClick(p.subtitle_edit_input, Qt.Key_Escape)
            elif exit_kind == 'close': p.caption_close_button.click()
            else: p._set_review_mode(False)
            assert p._caption_draft is None and not p.subtitle_edit_dock.isVisible()
            if exit_kind != 'return': assert p._review_mode
        p._set_review_mode(True); p._step_cue(1)
        assert p.selected_cue_id == 'b'
        focus(p.review_mode_button); QTest.keyClick(p.review_mode_button, Qt.Key_Escape)
        assert not p._review_mode
    finally:
        p.close_page(); p.deleteLater(); app.processEvents()


def test_same_red_pixel_twice_does_not_confirm_caption(tmp_path, monkeypatch):
    from twobyteasr.studio import studio_review_ui
    from twobyteasr.subtitle_rules.studio_qc import QCCandidate
    app,p=_page(tmp_path,monkeypatch,[StudioCue('a',0,4000,'坏猫在这里等错狗'),StudioCue('b',5000,8000,'下一句')])
    monkeypatch.setattr(studio_review_ui,'review_candidates',lambda project,cue:
        (QCCandidate(cue.text,('Current',)),QCCandidate('可爱猫在这里等好狗',())) if cue.id=='a' else (QCCandidate(cue.text,('Current',)),))
    try:
        p._review_all_explicit=(p.project.project_id,p.session.generation)
        p._set_review_mode(True);p.select_cue('a');p._refresh_review_summary_strip();app.processEvents()
        card=p._review_inline_card
        rect=card.text_label.chip_rects()[(0,0)];point=card.text_label.mapTo(card,rect.center().toPoint())
        QTest.mouseClick(card,Qt.LeftButton,Qt.NoModifier,point);app.processEvents()
        before=(p.project.cues[0].text,p.undo_stack.index(),p.selected_cue_id)
        QTest.mouseClick(card,Qt.LeftButton,Qt.NoModifier,point);app.processEvents()
        QTest.mouseDClick(card,Qt.LeftButton,Qt.NoModifier,point);app.processEvents()
        after=(p.project.cues[0].text,p.undo_stack.index(),p.selected_cue_id)
        assert before==after,(before,after)
    finally:p.close_page();p.deleteLater();app.processEvents()
