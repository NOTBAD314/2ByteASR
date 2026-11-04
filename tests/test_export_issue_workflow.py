import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
    load_project, save_project)
from twobyteasr.exports.export_issues import export_issues, ExportPreflightError, EMPTY_CONFIRMATIONS
from twobyteasr.exports.caption_integrity import require_confirmed_empty_sources
from twobyteasr.exports.export_issues_ui import ConfirmEmptySourceCommand, ExportIssuesDialog, locate_issue
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand

ID='range-4e4aaa9b-236'


def project():
    return SubtitleProject(StudioMedia('synthetic.mp4',duration_ms=20000),
        speakers=[StudioSpeaker('S00','主播'),StudioSpeaker('S01','角色甲')],
        cues=[StudioCue(ID,3000,5000,'',original_text='アリスが来た',speaker_id='S01'),
              StudioCue('other',8000,9000,'別の話',original_text='別の話',speaker_id='S00')])


def test_empty_diagnostic_has_source_mapping_text_and_readable_time_without_mutation():
    p=project(); before=p.to_dict()
    rows=export_issues(p)
    assert len(rows)==1 and rows[0].cue_id==rows[0].view_id==ID
    assert rows[0].speaker=='角色甲' and rows[0].start_ms==3000 and rows[0].manuscript=='アリスが来た'
    assert '实际字幕ID' in rows[0].provenance
    with pytest.raises(ExportPreflightError,match='00:00:03.000'):
        require_confirmed_empty_sources(p)
    assert p.to_dict()==before
    view=copy.copy(p.cues[0]); view.id=ID+'#clip-instance'; view.start_ms=10000; view.end_ms=12000
    rows=export_issues(p,[view,copy.copy(view)],validate_structure=False)
    assert len(rows)==1 and rows[0].cue_id==ID and rows[0].view_id==view.id and rows[0].start_ms==10000


@pytest.mark.parametrize('kind',['range','hidden','eye','translation_only','imported_translation','independent_translation','new_blank'])
def test_out_of_scope_and_non_source_records_do_not_block(kind):
    p=project(); kwargs={}
    if kind=='range': kwargs['start_ms']=6000
    elif kind=='hidden': p.speakers[1].hidden=True
    elif kind=='eye': p.studio_state['subtitle_track_visibility']={'S01':False}
    elif kind=='translation_only': p.studio_state['bilingual']={'mode':'translation'}
    elif kind=='imported_translation': p.generation_metadata['subtitle_imports']={'tracks':{'S01':{'role':'translation','language':'zh-Hans'}}}
    elif kind=='independent_translation':
        p.generation_metadata.update(language={'code':'ja'},subtitle_imports={'tracks':{'S01':{'role':'independent','language':'zh-Hans'}}})
    elif kind=='new_blank': p.cues[0].original_text=''
    assert not export_issues(p,**kwargs)


def test_confirmation_is_per_record_and_current_state_undoable_and_persistent(tmp_path):
    p=project(); stack=QUndoStack()
    stack.push(ConfirmEmptySourceCommand(p,ID))
    assert not export_issues(p)
    saved=load_project(save_project(p,tmp_path/'confirmed.2byteproj'))
    assert not export_issues(saved) and saved.cues[0].text==''
    stack.undo(); assert export_issues(p)
    stack.redo(); assert not export_issues(p)
    p.cues[0].original_text='新しい原稿'
    assert export_issues(p)  # A changed manuscript is a different state.
    p.cues.append(StudioCue('second',10000,11000,'',original_text='保持原稿',speaker_id='S00'))
    assert len(export_issues(p))==2


def test_later_text_edit_and_undo_does_not_reuse_an_old_empty_confirmation():
    p=project(); stack=QUndoStack()
    stack.push(ConfirmEmptySourceCommand(p,ID)); assert not export_issues(p)
    stack.push(SetCueFieldsCommand(p,ID,{'text':'new content'},'编辑正文'))
    stack.undo()
    assert p.cues[0].text=='' and export_issues(p)


def test_restore_uses_normal_text_command_and_preserves_undo_and_manuscript(tmp_path):
    p=project(); stack=QUndoStack(); cue=p.cues[0]
    stack.push(SetCueFieldsCommand(p,ID,{'text':cue.original_text},'恢复原文'))
    assert not export_issues(p) and cue.original_text=='アリスが来た'
    saved=load_project(save_project(p,tmp_path/'restored.2byteproj'))
    assert saved.cues[0].text=='アリスが来た'
    stack.undo(); assert export_issues(p)
    stack.redo(); assert not export_issues(p)


def test_actual_entry_shows_issue_list_before_creating_export_window(tmp_path,monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app,page=_page(tmp_path,monkeypatch,project().cues)
    try:
        calls=[]
        def forbidden(*a,**kw): calls.append(1); raise AssertionError('export window must not be constructed')
        monkeypatch.setattr('twobyteasr.studio.studio_ui.StudioExportWorkspace',forbidden)
        page._open_render_dialog(); app.processEvents()
        dialog=page._export_issues_dialog
        assert dialog.isVisible() and not calls and dialog.current().cue_id==ID
        page.cue_search.setText('no match'); page._activate_filter('done')
        assert locate_issue(page,dialog.current())
        assert page.selected_cue_id==ID and page.cue_model.row_for_cue_id(ID)>=0
        assert page.cue_search.text()==''
        dialog.restore_current(); app.processEvents()
        assert not dialog.issues and page.project.cues[0].text=='アリスが来た'
        page.undo_stack.undo(); dialog.refresh(); assert dialog.issues
        dialog.confirm_current(); assert not dialog.issues
        page.undo_stack.undo(); dialog.refresh(); assert dialog.issues
        dialog.close()
    finally: page.close_page(); page.deleteLater(); app.processEvents()


def test_stale_problem_row_does_not_restore_old_manuscript(tmp_path,monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app,page=_page(tmp_path,monkeypatch,project().cues)
    try:
        dialog=ExportIssuesDialog(page)
        page.project.cues[0].original_text='后来的原稿'
        dialog.restore_current()
        assert page.project.cues[0].text=='' and page.undo_stack.count()==0
        dialog.close()
    finally:page.close_page();page.deleteLater();app.processEvents()


def test_multiple_problem_rows_locate_and_resolve_individually(tmp_path,monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    cues=project().cues+[StudioCue('another-empty',11000,12000,'',original_text='第二条原稿',speaker_id='S00')]
    app,page=_page(tmp_path,monkeypatch,cues)
    try:
        dialog=ExportIssuesDialog(page);dialog.show();app.processEvents()
        assert len(dialog.issues)==2 and dialog.next.isEnabled()
        first=dialog.current().cue_id
        dialog.next.click();assert dialog.current().cue_id!=first and page.selected_cue_id==dialog.current().view_id
        dialog.previous.click();assert dialog.current().cue_id==first and page.selected_cue_id==first
        dialog.confirm_current();assert len(dialog.issues)==1 and dialog.current().cue_id=='another-empty'
        dialog.restore_current();assert not dialog.issues
        page.undo_stack.undo();dialog.refresh();assert len(dialog.issues)==1
        page.undo_stack.undo();dialog.refresh();assert len(dialog.issues)==2
        dialog.close()
    finally:page.close_page();page.deleteLater();app.processEvents()
