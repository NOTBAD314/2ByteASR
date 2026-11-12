"""Keyboard ownership uses the actual Studio E editor, including composition."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import StudioCue
from tests.test_review_replay_and_window_bounds import _page


def test_endpoint_combination_in_e_editor_is_suspended_without_inserting_during_ime(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',10000,13000,'输入法与正文')])
    calls=[]
    def seek(seconds,**kwargs):
        calls.append(seconds);page.timeline.set_playhead(round(seconds*1000))
    monkeypatch.setattr(page,'_seek',seek)
    page.select_cue('a');page._open_caption_editor('a','original')
    editor=page.subtitle_edit_input
    try:
        app.setActiveWindow(page.subtitle_edit_dock);editor.setFocus();app.processEvents()
        original=editor.toPlainText()
        QApplication.sendEvent(editor,QInputMethodEvent('拼',[]))
        QTest.keyClick(editor,Qt.Key_J,Qt.AltModifier)
        assert not calls and editor.toPlainText()==original
        QApplication.sendEvent(editor,QInputMethodEvent('',[]))
        QTest.keyClick(editor,Qt.Key_J,Qt.AltModifier)
        assert calls==[10.0] and editor.toPlainText()==original
        QTest.keyClick(editor,Qt.Key_J,Qt.AltModifier)
        assert calls==[10.0,13.0] and editor.toPlainText()==original
        assert page._caption_draft.target.cue_id=='a'
        QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
        assert editor.textCursor().selectedText()==original
    finally:
        page._cancel_bound_caption_editor(trigger='test_cleanup')
        page.close_page();page.deleteLater();app.processEvents()


def test_native_list_keyboard_selection_navigates_and_configured_key_reaches_e(tmp_path,monkeypatch):
    from PySide6.QtCore import QItemSelectionModel
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',10000,13000,'甲'),StudioCue('b',14000,16000,'乙')])
    calls=[]
    def seek(seconds,**kwargs):
        calls.append(seconds);page.timeline.set_playhead(round(seconds*1000))
    monkeypatch.setattr(page,'_seek',seek)
    try:
        page._remember_subtitle_navigation('')
        page._select_cue_observation('a')
        assert not page._held_subtitle_navigation()
        page._timeline_cue_clicked('a')
        assert page._held_subtitle_navigation()
        assert page.selection_center_toggle.accessibleName()=='选中定位并居中'
        page.select_cue('a');calls.clear()
        row=page.cue_model.row_for_cue_id('b')
        page.cue_table.selectionModel().setCurrentIndex(page.cue_model.index(row,0),
            QItemSelectionModel.ClearAndSelect|QItemSelectionModel.Rows)
        assert page.selected_cue_id=='b' and calls==[]
        page.selection_center_toggle.click()
        assert calls==[14.0] and page.timeline.visible_duration_ms==15000
        values=dict(page._shortcut_values,jump_cue_boundary='Ctrl+Shift+J')
        page._shortcut_registry_changed(values)
        assert 'Ctrl+Shift+J' in page.cue_boundary_button.toolTip()
        page._open_caption_editor('b','original');app.setActiveWindow(page.subtitle_edit_dock)
        editor=page.subtitle_edit_input;editor.setFocus();app.processEvents()
        page.timeline.set_playhead(14000)  # mocked video.load has no presented-frame clock
        QTest.keyClick(editor,Qt.Key_J,Qt.ControlModifier|Qt.ShiftModifier)
        assert calls[-1]==16.0 and editor.toPlainText()=='乙'
        assert 'Ctrl+Shift+J' in page.subtitle_edit_card.hint.text()
        page._shortcut_registry_changed(dict(page._shortcut_values,jump_cue_boundary='Ctrl+C'))
        editor.selectAll();before=len(calls)
        QTest.keyClick(editor,Qt.Key_C,Qt.ControlModifier)
        assert len(calls)==before and app.clipboard().text()=='乙'
    finally:
        page._cancel_bound_caption_editor(trigger='test_cleanup')
        page.close_page();page.deleteLater();app.processEvents()
