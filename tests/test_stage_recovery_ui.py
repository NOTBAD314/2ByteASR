"""The visible retry task list runs a real worker and saves each unit."""
import copy
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QWidget,QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import save_project,load_project
from twobyteasr.recognition.processing_recovery import failure_summary
from twobyteasr.app import stage_retry,stage_retry_ui
from tests.test_stage_recovery import fixture
from tests.test_completion_retry_ui import drive_dialog

APP=QApplication.instance() or QApplication([])


def test_retry_dialog_executes_mapped_unit_shows_progress_and_keeps_missing_unit(tmp_path,monkeypatch):
    import subtitle_core
    monkeypatch.setattr(subtitle_core,'glossary_catalog',lambda:[])
    p,r=fixture();r['polishing_summary']['fallback_cues']=2
    w=QWidget();w.session=SimpleNamespace(project=p,undo_stack=QUndoStack(w));w.project_path=save_project(p,tmp_path/'u.2byteproj')
    w.selected_cue_ids=lambda:['split-a'];w.select_cue=lambda key:None;w._changed=lambda:None;w._show_studio_hint=lambda message:None
    called=[]
    def execute(project,report,options,unit,token):
        called.append((unit['key'],unit['input']['text']))
        return {**unit,'status':'completed_no_change','reason':'已完成，无需修改'}
    monkeypatch.setattr(stage_retry,'execute_unit',execute)
    def inspect(dialog):
        assert dialog._retry_tasks.topLevelItemCount()==2
        assert dialog._retry_tasks.topLevelItem(0).text(1)=='完成，无需修改'
        assert dialog._retry_tasks.topLevelItem(1).text(1)=='缺少输入'
        assert '失败任务 1 项' in dialog.status_label.text()
        assert dialog._completion_retry_receipt['saved']
    observed=drive_dialog(monkeypatch,inspect)
    before=copy.deepcopy(p.cues)
    receipt=stage_retry_ui.open_failed_stage_review(w,r)
    assert len(called)==1 and called[0][1]=='人工名第一句人工名第二句'
    assert receipt['saved'] and p.cues==before
    summary=failure_summary(load_project(w.project_path),r)
    assert summary['failed_tasks']==1 and summary['retryable_tasks']==0
    w.deleteLater();APP.processEvents()


def test_grouping_result_is_saved_once_and_undo_restores_failure(tmp_path):
    from twobyteasr.app.stage_retry_commit import commit_unit_result
    from twobyteasr.recognition.processing_recovery import recover_units
    from dataclasses import asdict
    p,r=fixture();p.studio_state['ai_sentence_refine']={'failed_cue_ids':['split-a'],'last_status':'failed'}
    unit=next(u for u in recover_units(p,r) if u['stage']=='grouping')
    updated=copy.deepcopy(p.cues[0]);updated.text='人工名 第一句'
    unit.update(status='completed',replacements={'split-a':[asdict(updated)]})
    stack=QUndoStack();w=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=stack),
        project_path=save_project(p,tmp_path/'g.2byteproj'),_changed=lambda:None)
    commit_unit_result(w,r,unit)
    assert p.cues[0].text==updated.text and stack.count()==1
    assert load_project(w.project_path).cues[0].text==updated.text
    assert not p.studio_state['ai_sentence_refine']['failed_cue_ids']
    stack.undo();assert p.cues[0].text=='人工名第一句'
    assert any(u['stage']=='grouping' and u['status'] not in {'completed','completed_no_change'} for u in recover_units(p,r))
    stack.redo();assert p.cues[0].text==updated.text


def test_partial_grouping_keeps_success_out_of_next_request(tmp_path):
    from twobyteasr.app.stage_retry_commit import commit_unit_result
    from twobyteasr.recognition.processing_recovery import recover_units
    from dataclasses import asdict
    p,r=fixture();r['events']=[{'event':'grouping_api_fallback','batch_index':1,'segment_start':0,'segment_end':2,
        'source_processing_ids':[67]}]
    unit=next(u for u in recover_units(p,r) if u['stage']=='grouping')
    replacement=copy.deepcopy(p.cues[0]);replacement.text='人工名 第一句'
    unit.update(status='failed',failed_cue_ids=['split-b'],replacements={'split-a':[asdict(replacement)]})
    w=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=QUndoStack()),project_path=save_project(p,tmp_path/'partial.2byteproj'),_changed=lambda:None)
    commit_unit_result(w,r,unit)
    remaining=next(u for u in recover_units(load_project(w.project_path),r) if u['stage']=='grouping')
    assert remaining['cue_ids']==['split-b'] and remaining['completed_cue_ids']==['split-a']
    assert remaining['input']['text']=='人工名第二句' and p.cues[0].text=='人工名 第一句'
    remaining.update(status='completed',failed_cue_ids=[],replacements={})
    commit_unit_result(w,r,remaining)
    assert next(u for u in recover_units(load_project(w.project_path),r) if u['stage']=='grouping')['status']=='completed'


@pytest.mark.parametrize('change',['object','save_as'])
def test_project_replacement_during_retry_cannot_save_old_cleanup_over_new_file(tmp_path,monkeypatch,change):
    import subtitle_core
    from twobyteasr.projects.studio_project import SubtitleProject
    monkeypatch.setattr(subtitle_core,'glossary_catalog',lambda:[])
    p,r=fixture();w=QWidget();w.session=SimpleNamespace(project=p,undo_stack=QUndoStack(w))
    w.project_path=save_project(p,tmp_path/'replaced.2byteproj')
    w.selected_cue_ids=lambda:['split-a'];w.select_cue=lambda key:None
    w._changed=lambda:None;w._show_studio_hint=lambda message:None
    monkeypatch.setattr(stage_retry,'execute_unit',lambda project,report,options,unit,token:{**unit,'status':'completed_no_change'})
    replacement=[];original_path=w.project_path
    def switch(dialog):
        original=original_path.read_bytes()
        new=SubtitleProject.from_dict(copy.deepcopy(p.to_dict())) if change=='object' else p
        new.cues[0].text='新工程对象中的人工修改'
        if change=='save_as':w.project_path=tmp_path/'save-as.2byteproj'
        w.session.project=new;save_project(new,w.project_path);replacement.append(w.project_path.read_bytes())
        if change=='save_as':replacement.append(original)
    def inspect(dialog):
        assert w.project_path.read_bytes()==replacement[0]
        assert load_project(w.project_path).cues[0].text=='新工程对象中的人工修改'
        assert not dialog.all_button.isEnabled()
        if change=='save_as':assert original_path.read_bytes()==replacement[1]
    drive_dialog(monkeypatch,inspect,begin=switch)
    stage_retry_ui.open_failed_stage_review(w,r)
    w.deleteLater();APP.processEvents()
