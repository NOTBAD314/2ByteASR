"""Stable failure mapping, partial persistence and current-edit protection."""
import copy,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia,save_project,load_project
from twobyteasr.recognition.processing_recovery import recover_units,failure_summary,capture_unit,input_matches,save_unit_states,effective_report

APP=QApplication.instance() or QApplication([])


def fixture():
    p=SubtitleProject(StudioMedia('source.mp4',duration_ms=3000),cues=[
        StudioCue('split-a',0,1000,'人工名第一句',evidence_refs=['segment:67']),
        StudioCue('split-b',1000,2000,'人工名第二句',evidence_refs=['segment:67']),
        StudioCue('success',2000,3000,'其他成功句',evidence_refs=['segment:69'])],
        asr_evidence={'segment:67':{'text':'旧名第一句旧名第二句','start_ms':0,'end_ms':2000,
            'caption_arbitration':{'terminology_polish':{'response_state':'fallback','input_text':'旧名第一句旧名第二句'}}},
            'segment:69':{'text':'其他成功句','start_ms':2000,'end_ms':3000}},generation_metadata={'job_id':'task-1'})
    p.validate()
    report={'job_id':'task-1','polishing_summary':{'fallback_ids':[69],'fallback_cues':1,'failure_records':{'69':'semantic_validation'}},
        'review_items':[{'cue_id':69,'text':'旧名第一句旧名第二句','timestamp':0,'category':'校对回退'}]}
    return p,report


def test_legacy_renumber_maps_by_identity_and_keeps_current_manual_text():
    p,r=fixture();unit=recover_units(p,r)[0]
    assert unit['original_ids']==[69] and unit['evidence_refs']==['segment:67']
    assert unit['cue_ids']==['split-a','split-b'] and unit['input']['text']=='人工名第一句人工名第二句'
    assert failure_summary(p,r)['affected_cues']==2


def test_counter_without_identity_stays_blocked_and_does_not_invent_second_task():
    p,r=fixture();r['polishing_summary']['fallback_cues']=2
    summary=failure_summary(p,r)
    assert summary['failed_tasks']==2 and summary['retryable_tasks']==1
    assert summary['units'][1]['status']=='blocked' and not summary['units'][1]['cue_ids']


@pytest.mark.parametrize('change',['text','time','media','job','remove'])
def test_late_result_is_fenced_by_current_input(change):
    p,r=fixture();captured=recover_units(p,r)[0]['input'];assert input_matches(p,captured)
    if change=='text':p.cues[0].text='新手动修改'
    elif change=='time':p.cues[0].start_ms+=10
    elif change=='media':p.media.path='other.mp4'
    elif change=='job':p.generation_metadata['job_id']='other-task'
    else:p.cues.pop(0)
    assert not input_matches(p,captured)


def test_success_only_clears_after_save_and_historical_report_remains_unchanged(tmp_path,monkeypatch):
    p,r=fixture();original=copy.deepcopy(r);unit=recover_units(p,r)[0];unit['status']='completed_no_change'
    def fail(*a,**k):raise OSError('disk full')
    with monkeypatch.context() as m:
        m.setattr('twobyteasr.projects.studio_project.save_project',fail)
        with pytest.raises(OSError):save_unit_states(p,r,[unit],path=tmp_path/'p.2byteproj')
    assert failure_summary(p,r)['failed_tasks']==1
    path=tmp_path/'p.2byteproj';save_unit_states(p,r,[unit],path=path)
    reopened=load_project(path)
    assert failure_summary(reopened,r)['failed_tasks']==0 and r==original
    assert effective_report(reopened,r)['polishing_summary']['fallback_cues']==0
    assert [c.text for c in reopened.cues]==[c.text for c in p.cues]


def test_partial_execution_reports_progress_and_never_restarts_asr(monkeypatch):
    from twobyteasr.app import stage_retry
    p,r=fixture();r['polishing_summary']['fallback_cues']=2;events=[];done=[]
    monkeypatch.setattr(stage_retry,'execute_unit',lambda p,r,o,u,t:{**u,'status':'completed_no_change'})
    answer=stage_retry.execute_failed_units(p,r,progress=lambda a,b,u:events.append((a,b)),unit_ready=done.append)
    assert len(answer)==2 and len(done)==2 and answer[0]['status']=='completed_no_change' and answer[1]['status']=='blocked'
    assert events[0]==(0,2) and len({u['key'] for u in answer})==2


def test_proposal_projection_uses_current_text_and_does_not_duplicate_split_source():
    from twobyteasr.app.stage_retry import proposal_hits
    p,r=fixture();unit=recover_units(p,r)[0]
    hits,pending=proposal_hits(unit,'人工名第一句人工名下一句')
    assert [(h.cue_id,h.original,h.replacement) for h in hits]==[('split-b','人工名第二句','人工名下一句')]
    assert not pending and [c.text for c in p.cues][:2]==['人工名第一句','人工名第二句']


def test_grouping_and_translation_are_distinct_retryable_stages():
    p,r=fixture();p.studio_state['ai_sentence_refine']={'failed_cue_ids':['split-b'],'last_error':'bad indices'}
    from twobyteasr.subtitle_rules.subtitle_translation import TranslationResult,apply_translation_result
    result=TranslationResult('en','m','p',sources={'success':p.cues[2].text},failed={'success':'timeout'})
    apply_translation_result(p,result)
    units=recover_units(p,r)
    assert {u['stage'] for u in units}=={'polish','grouping','translation'}
    assert next(u for u in units if u['stage']=='translation')['cue_ids']==['success']


def test_real_short_project_maps_69_to_67_without_restoring_old_names():
    root=Path(__file__).resolve().parents[2]
    if not (root/'original-short.2byteproj').exists():pytest.skip('local readonly real fixture unavailable')
    p=load_project(root/'original-short.2byteproj');r=json.loads((root/'original-report.json').read_text('utf-8-sig'))
    units=recover_units(p,r)
    assert len(units)==1 and units[0]['stage']=='polish'
    unit=units[0];assert unit['original_ids']==[69] and unit['evidence_refs']==['segment:67']
    assert len(unit['cue_ids'])==6 and '末王' in unit['input']['text'] and '反主' in unit['input']['text']
    assert '墨王' not in unit['input']['text'] and '凡人' not in unit['input']['text']


def test_noop_stage_commit_persists_and_does_not_mutate_text(tmp_path):
    from twobyteasr.app.stage_retry_commit import commit_unit_result
    p,r=fixture();path=save_project(p,tmp_path/'live.2byteproj');stack=QUndoStack()
    studio=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=stack),project_path=path)
    unit={**recover_units(p,r)[0],'status':'completed_no_change'}
    before=copy.deepcopy(p.cues);commit_unit_result(studio,r,unit)
    assert p.cues==before and failure_summary(load_project(path),r)['failed_tasks']==0


def test_interrupted_running_unit_is_retryable_after_restart(tmp_path):
    p,r=fixture();unit={**recover_units(p,r)[0],'status':'running'}
    path=tmp_path/'interrupted.2byteproj';save_unit_states(p,r,[unit],path=path)
    restored=recover_units(load_project(path),r)[0]
    assert restored['status']=='failed' and restored['retryable'] and '中断' in restored['reason']


def test_translation_commit_uses_existing_records_and_preserves_source(tmp_path):
    from twobyteasr.subtitle_rules.subtitle_translation import TranslationResult,TranslatedItem,apply_translation_result,source_sha,records_of
    from twobyteasr.app.stage_retry_commit import commit_unit_result
    p,r=fixture();source=p.cues[2].text
    failed=TranslationResult('en','m','p',sources={'success':source},failed={'success':'timeout'})
    apply_translation_result(p,failed)
    unit=next(u for u in recover_units(p,r) if u['stage']=='translation')
    answer=TranslationResult('en','m','p',sources={'success':source},requested=('success',),
        translations={'success':TranslatedItem('success','A successful line.',source,source_sha(source),'context')})
    unit.update(status='completed',translation_result=answer)
    path=save_project(p,tmp_path/'translation.2byteproj');stack=QUndoStack()
    w=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=stack),project_path=path,_changed=lambda:None)
    before=copy.deepcopy(p.cues);commit_unit_result(w,r,unit)
    assert p.cues==before and records_of(p)['success']['text']=='A successful line.'
    assert records_of(load_project(path))['success']['status']=='done' and stack.count()==1
    stack.undo();assert records_of(p)['success']['status']=='failed'


def test_late_stage_commit_cannot_overwrite_manual_edit_or_clear_failure(tmp_path):
    from twobyteasr.app.stage_retry_commit import commit_unit_result
    p,r=fixture();unit={**recover_units(p,r)[0],'status':'completed_no_change'}
    path=save_project(p,tmp_path/'late.2byteproj');p.cues[0].text='重试期间手动修改'
    w=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=QUndoStack()),project_path=path)
    with pytest.raises(ValueError,match='编辑'):commit_unit_result(w,r,unit)
    assert p.cues[0].text=='重试期间手动修改' and failure_summary(p,r)['failed_tasks']==1


def test_real_polish_execution_calls_only_mapped_current_unit(context,monkeypatch):
    from tests.test_stage9_provider_snapshot import config
    from twobyteasr.recognition.service import RunOptions,CancellationToken
    from twobyteasr.app.stage_retry import execute_unit
    p,r=fixture();sent=[]
    def complete(messages,**kw):
        payload=json.loads(messages[1]['content']);sent.extend(payload['cues'])
        return json.dumps({'checked_ids':[69],'cues':[]})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    answer=execute_unit(p,r,RunOptions(settings_snapshot_json=json.dumps(config())),recover_units(p,r)[0],CancellationToken())
    assert answer['status']=='completed_no_change' and len(sent)==1
    assert sent[0]['id']==69 and '人工名' in sent[0]['primary_text'] and '旧名' not in sent[0]['primary_text']


from tests.test_stage9_cache_and_budget import context
