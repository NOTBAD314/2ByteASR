import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QLabel
from twobyteasr.studio.studio_context_tabs import restored_context_tab
from tests.test_studio_cue_controller import _page, _finish


@pytest.mark.parametrize('old,expected', [(0,0),(1,1),(2,1),(3,2),(4,3),(5,4),(99,1),('bad',1)])
def test_old_context_index_migrates(old,expected):
    assert restored_context_tab({'context_tab':old})==expected
    assert restored_context_tab({'context_tab_id':'checks','context_tab':3})==1
    assert restored_context_tab({'context_tab_id':'media','context_tab':1})==4


def test_real_escape_clears_all_selection_domains_and_next_target_restores(tmp_path,monkeypatch):
    page=_page(tmp_path,monkeypatch)
    page.resize(1400,850);page.show();app=QApplication.instance();app.processEvents()
    QApplication.setActiveWindow(page);page.timeline.setFocus()
    page.timeline.playhead_ms=500;page._update_active_cues(500)
    QTest.keyClick(page.timeline,Qt.Key_Escape);app.processEvents()
    assert page.selected_cue_ids()==[] and not page.timeline.selected_ids
    assert page.session.playhead_target_id==''
    page._update_active_cues(600)
    assert page.selected_cue_ids()==[]
    page.follow_playhead_toggle.setChecked(False)
    page._update_active_cues(1500)
    assert page.selected_cue_id=='b'
    assert page.cue_table.selectionModel().selectedRows()[0].row()==1
    _finish(page)


def test_checks_widgets_removed_shared_review_and_undo_remain(tmp_path,monkeypatch):
    page=_page(tmp_path,monkeypatch);before=page.project.to_dict()['cues']
    assert [page.context_drawer.tabToolTip(i) for i in range(page.context_drawer.count())]==['AI设计','样式','视频','剪辑助手','素材']
    assert not hasattr(page,'safe_fix_button') and not hasattr(page,'_refresh_checks')
    assert not any('安全修复' in w.text() for w in page.findChildren(QPushButton))
    assert not any(w.text()=='检查' for w in page.findChildren(QLabel))
    page._refresh_review_risks(sync=True)
    assert page.project.to_dict()['cues']==before and page.undo_stack.count()==0
    assert not hasattr(page,'_safe_fix_plan')
    page.cue_controller.set_text('a','20 20')
    page.undo_stack.undo()
    assert page.project.to_dict()['cues']==before
    _finish(page)


def test_keyboard_editor_deleted_target_cannot_write_neighbor(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.timeline.studio_commands import delete_cues_command
    page=_page(tmp_path,monkeypatch);page.resize(1400,850);page.show()
    app=QApplication.instance();app.processEvents();QApplication.setActiveWindow(page)
    page.timeline.setFocus();page.timeline.playhead_ms=500
    monkeypatch.setattr(page.video,'playback_position_snapshot',lambda:SimpleNamespace(presentation_media_ms=500,paused=True))
    QTest.keyClick(page.timeline,Qt.Key_E)
    assert page._review_edit_lock['cue_id']=='a'
    QTest.keyClicks(page.subtitle_edit_input,'qwe')
    page.undo_stack.push(delete_cues_command(page.project,['a'],page.cue_controller.changed))
    QTest.keyClick(page.subtitle_edit_input,Qt.Key_Return)
    assert [cue.text for cue in page.project.cues]==['第二句']
    page.undo_stack.undo()
    assert [cue.text for cue in page.project.cues]==['第一句','第二句']
    _finish(page)
