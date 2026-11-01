"""Supplement the real mouse entry, using the isolated production Qt page."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue,load_project


def opened(tmp_path,monkeypatch,mode):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('click-stable',6333,11417,'Nonempty English caption',speaker_id='S00')])
    page.timeline.set_subtitle_layer('original')
    page._set_cue_list_view(mode,remember=False)
    page.select_cue('click-stable')
    index=page.cue_model.index(page.cue_model.row_for_cue_id('click-stable'),3)
    page.cue_table.scrollTo(index);app.processEvents()
    rect=page.cue_table.visualRect(index)
    assert rect.isValid()
    QTest.mouseClick(page.cue_table.viewport(),Qt.LeftButton,pos=rect.center())
    QTest.mouseDClick(page.cue_table.viewport(),Qt.LeftButton,pos=rect.center())
    app.processEvents()
    assert page._caption_draft is not None
    assert page._caption_draft.target.cue_id=='click-stable'
    assert page.subtitle_edit_input.toPlainText()=='Nonempty English caption'
    assert not page.cue_model.flags(index)&Qt.ItemFlag.ItemIsEditable
    assert not [w for w in page.cue_table.findChildren(QLineEdit) if w.isVisible()]
    return app,page


@pytest.mark.parametrize('mode',['reading','table'])
@pytest.mark.parametrize('trigger',['enter','shift_r','button'])
def test_mouse_double_click_edit_confirm_save_reopen(tmp_path,monkeypatch,mode,trigger):
    app,page=opened(tmp_path,monkeypatch,mode)
    try:
        page.subtitle_edit_input.setPlainText('Confirmed from actual double click')
        if trigger=='button':QTest.mouseClick(page.caption_confirm_button,Qt.LeftButton)
        elif trigger=='shift_r':QTest.keyClick(page.subtitle_edit_input,Qt.Key_R,Qt.ShiftModifier)
        else:QTest.keyClick(page.subtitle_edit_input,Qt.Key_Return)
        assert page.project.cues[0].text=='Confirmed from actual double click'
        assert page.undo_stack.count()==1
        assert load_project(page.project_path).cues[0].text==page.project.cues[0].text
        page.undo_stack.undo();assert page.project.cues[0].text=='Nonempty English caption'
        page.undo_stack.redo();assert page.project.cues[0].text=='Confirmed from actual double click'
    finally:page.close_page();page.deleteLater();app.processEvents()


@pytest.mark.parametrize('mode',['reading','table'])
@pytest.mark.parametrize('reason',['lock','conflict'])
@pytest.mark.parametrize('exit_kind',['cancel','escape','header_close','window_close'])
def test_mouse_double_click_reject_cancel_keeps_authority(tmp_path,monkeypatch,mode,reason,exit_kind):
    app,page=opened(tmp_path,monkeypatch,mode)
    try:
        page.subtitle_edit_input.setPlainText('Rejected draft')
        expected='Nonempty English caption'
        if reason=='lock':page.timeline.locked_speakers={'S00'}
        else:
            expected='Another legitimate write'
            page.cue_controller.set_text('click-stable',expected)
        index,count=page.undo_stack.index(),page.undo_stack.count()
        QTest.mouseClick(page.caption_confirm_button,Qt.LeftButton)
        code='track_locked' if reason=='lock' else 'text_conflict'
        assert page._caption_draft is not None and code in page.subtitle_edit_card.error_detail.text()
        if exit_kind=='cancel':QTest.mouseClick(page.caption_cancel_button,Qt.LeftButton)
        elif exit_kind=='escape':QTest.keyClick(page.subtitle_edit_input,Qt.Key_Escape)
        elif exit_kind=='header_close':QTest.mouseClick(page.caption_close_button,Qt.LeftButton)
        else:page.subtitle_edit_dock.close()
        QTest.qWait(250)
        assert page.project.cues[0].text==expected
        assert (page.undo_stack.index(),page.undo_stack.count())==(index,count)
        assert page._caption_draft is None and not page._live_edit_text_overrides
        page.save();assert load_project(page.project_path).cues[0].text==expected
    finally:page.close_page();page.deleteLater();app.processEvents()
