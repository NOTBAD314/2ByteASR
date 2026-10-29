"""Stable stage units recovered from receipts, independent of final cue numbers.

The original report/evidence are historical. Current operational state lives in
optional generation metadata; validated results are saved before completion.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

KEY='processing_recovery'
TERMINAL=frozenset({'completed','completed_no_change','proposals_pending','applied','removed'})
ACTIVE_KEYS=set()  # GUI ownership only; never persisted as a process identity.


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _evidence(project):
    return [(str(key),row) for key,row in project.asr_evidence.items() if str(key).startswith('segment:') and isinstance(row,dict)]


def _polish_detail(row):
    return (row.get('caption_arbitration') or {}).get('terminology_polish') or {}


def _input_text(row):
    detail=_polish_detail(row)
    return str(detail.get('input_text') or detail.get('original_text') or row.get('text') or '')


def _current_parts(project,refs,start,end):
    parts=[];offset=0
    for cue in sorted(project.cues,key=lambda c:(c.start_ms,c.end_ms,c.id)):
        if not set(cue.evidence_refs)&set(refs):continue
        overlap=min(end,cue.end_ms)-max(start,cue.start_ms)
        # Source refs can touch the previous caption by one rounded frame.
        # Such a neighbour is context, not ownership of this failed utterance.
        if overlap<=10 and end-start>50:continue
        row={'cue_id':cue.id,'start_ms':cue.start_ms,'end_ms':cue.end_ms,'speaker_id':cue.speaker_id,
             'text':cue.text,'evidence_refs':list(cue.evidence_refs),'offset':offset}
        parts.append(row);offset+=len(cue.text)
    return parts


def capture_unit(project,unit):
    if unit.get('capture_by_id'):
        chosen=set(unit.get('cue_ids',()))
        parts=[];offset=0
        for cue in sorted(project.cues,key=lambda c:(c.start_ms,c.end_ms,c.id)):
            if cue.id not in chosen:continue
            parts.append({'cue_id':cue.id,'start_ms':cue.start_ms,'end_ms':cue.end_ms,'speaker_id':cue.speaker_id,
                'text':cue.text,'evidence_refs':list(cue.evidence_refs),'offset':offset})
            offset+=len(cue.text)
    else:parts=_current_parts(project,unit.get('evidence_refs',()),*unit.get('source_range_ms',(0,0)))
    text=''.join(row['text'] for row in parts)
    from ..subtitle_rules.subtitle_translation import records_of
    return {'parts':parts,'text':text,'version':digest(parts),'project_id':str(project.project_id),
            'job_id':str(project.generation_metadata.get('job_id') or ''),'media_path':project.media.path,
            'translation_version':digest({p['cue_id']:records_of(project).get(p['cue_id']) for p in parts})}


def input_matches(project,captured):
    if str(project.project_id)!=captured.get('project_id'):return False
    if str(project.generation_metadata.get('job_id') or '')!=captured.get('job_id'):return False
    if project.media.path!=captured.get('media_path'):return False
    from ..subtitle_rules.subtitle_translation import records_of
    if digest({p['cue_id']:records_of(project).get(p['cue_id']) for p in captured.get('parts',())})!=captured.get('translation_version'):return False
    by_id={c.id:c for c in project.cues}
    actual=[]
    for row in captured.get('parts',()):
        cue=by_id.get(row['cue_id'])
        if cue is None:return False
        actual.append({'cue_id':cue.id,'start_ms':cue.start_ms,'end_ms':cue.end_ms,'speaker_id':cue.speaker_id,
            'text':cue.text,'evidence_refs':list(cue.evidence_refs),'offset':row['offset']})
    return digest(actual)==captured.get('version')


def recover_units(project,report):
    """Never use final caption index or a bare segment:N as a failed identity."""
    report=report or {};meta=project.generation_metadata
    job=str(report.get('job_id') or meta.get('job_id') or project.project_id)
    stored=copy.deepcopy((meta.get(KEY) or {}).get('units') or {})
    summary=report.get('polishing_summary') or meta.get('polishing_summary') or {}
    failed=list(dict.fromkeys(summary.get('fallback_ids') or ()))
    if not failed:
        failed=[str((row.get('caption_arbitration',{}).get('processing_identity') or {}).get('polish_record_id') or ref.partition(':')[2])
            for ref,row in _evidence(project) if _polish_detail(row).get('response_state')=='fallback']
    review={str(r.get('cue_id')):r for r in report.get('review_items',())
            if r.get('category')=='校对回退' and r.get('cue_id') is not None}
    evidence=_evidence(project);rows=[]
    for original in failed:
        key=f'{job}:polish:{original}'
        if key in stored and stored[key].get('status') in TERMINAL:
            rows.append(stored[key]);continue
        hint=review.get(str(original),{})
        quote=str(hint.get('text') or '')
        time_ms=round(float(hint.get('timestamp') or 0)*1000) if hint.get('timestamp') is not None else None
        stamped=[(ref,row) for ref,row in evidence if str((row.get('caption_arbitration',{}).get('processing_identity') or {}).get('polish_record_id',''))==str(original)]
        matches=stamped or [(ref,row) for ref,row in evidence if quote and _input_text(row)==quote
            and (time_ms is None or abs(int(row.get('start_ms',0))-time_ms)<=50)]
        if not matches and len(failed)==1:
            matches=[(ref,row) for ref,row in evidence if _polish_detail(row).get('response_state')=='fallback']
        unit=copy.deepcopy(stored.get(key) or {})
        unit.update(key=key,job_id=job,project_id=str(project.project_id),stage='polish',original_ids=[original],
            reason=(summary.get('failure_records') or {}).get(str(original),'polish_failed'),retryable=False)
        if len(matches)==1:
            ref,row=matches[0];detail=_polish_detail(row)
            unit.update(evidence_refs=[ref],source_range_ms=[int(row.get('start_ms',0)),int(row.get('end_ms',0))],
                source_text_sha256=digest(_input_text(row)),failure_detail=copy.deepcopy(detail.get('validation_failure') or {}))
            captured=capture_unit(project,unit)
            unit.update(input=captured,cue_ids=[p['cue_id'] for p in captured['parts']],
                status=unit.get('status','failed'),retryable=bool(captured['parts']))
            if not captured['parts']:unit.update(status='blocked',reason='失败处理记录仍在，但当前字幕缺少可确认的对应范围')
        else:unit.update(status='blocked',reason='原失败输入关联缺失或不唯一，不能按同号字幕猜测重试范围',evidence_refs=[],cue_ids=[])
        rows.append(unit)
    missing=max(0,int(summary.get('fallback_cues',0) or 0)-len(failed))
    for index in range(missing):
        key=f'{job}:polish:missing-{index}'
        rows.append(stored.get(key) or {'key':key,'job_id':job,'project_id':str(project.project_id),'stage':'polish',
            'status':'blocked','retryable':False,'reason':'历史摘要有失败计数，但未保存任务ID与输入范围','original_ids':[],
            'evidence_refs':[],'cue_ids':[]})
    def add_stage(stage,identity,ids,reason,**extra):
        key=f'{job}:{stage}:{identity}'
        prior=stored.get(key)
        if prior and prior.get('status') in TERMINAL:
            rows.append(prior);return
        if prior and prior.get('completed_cue_ids'):
            ids=[key for key in ids if key not in prior['completed_cue_ids']]
        unit={**copy.deepcopy(prior or {}),'key':key,'job_id':job,'project_id':str(project.project_id),'stage':stage,
              'status':'failed','retryable':bool(ids),'cue_ids':list(ids),'capture_by_id':True,'reason':reason,**extra}
        unit['input']=capture_unit(project,unit)
        if not unit['input']['parts']:unit.update(status='blocked',retryable=False,reason='原失败字幕已移除；缺少可确认的当前输入')
        rows.append(unit)
    refine=(project.studio_state or {}).get('ai_sentence_refine') or {}
    for cue_id in refine.get('failed_cue_ids') or ():
        add_stage('grouping','refine-'+str(cue_id),[cue_id],refine.get('last_error') or '断句校验未通过')
    for event in report.get('events') or ():
        if event.get('event')!='grouping_api_fallback':continue
        start=round(float(event.get('segment_start',0))*1000);end=round(float(event.get('segment_end',0))*1000)
        source_ids=event.get('source_processing_ids') or ()
        refs={'segment:'+str(key) for key in source_ids} if source_ids else {
            ref for ref,row in evidence if min(end,int(row.get('end_ms',0)))-max(start,int(row.get('start_ms',0)))>10}
        ids=[c.id for c in project.cues if refs.intersection(c.evidence_refs)]
        add_stage('grouping','batch-'+str(event.get('batch_index')),ids,event.get('category') or '断句回退',diagnostic=event)
    from ..subtitle_rules.subtitle_translation import records_of,container_target
    translation_records=records_of(project)
    for cue_id,record in translation_records.items():
        if record.get('status')=='failed':
            add_stage('translation',cue_id,[cue_id],record.get('error') or '翻译未完成',target=container_target(project))
    translation_events=[e for e in report.get('events',()) if e.get('event')=='subtitle_translation']
    old_translation_failed=int(translation_events[-1].get('failed',0) or 0) if translation_events else 0
    if old_translation_failed and not translation_records:
        add_stage('translation','missing-input',[],'原报告记有翻译失败，但工程没有保存译文记录及输入ID；请在双语面板明确选择字幕重新翻译')
    # New stage units retain their persisted identities.
    known={u['key'] for u in rows}
    rows.extend(v for k,v in stored.items() if k not in known)
    for unit in rows:
        if unit.get('status')=='running' and unit['key'] not in ACTIVE_KEYS:
            unit.update(status='failed',reason='上次重试已中断或窗口已关闭；保留当前文字，可继续重试')
    return rows


def failure_summary(project,report):
    units=recover_units(project,report)
    failed=[u for u in units if u.get('status') not in TERMINAL]
    return {'units':units,'failed_tasks':len(failed),'retryable_tasks':sum(bool(u.get('retryable')) for u in failed),
            'affected_cues':len({c for u in failed for c in u.get('cue_ids',())}),
            'pending_proposals':sum(u.get('status')=='proposals_pending' and input_matches(project,u['input']) for u in units)}


def effective_report(project,report):
    """Reconcile current completion UI without editing historical diagnostics."""
    result=copy.deepcopy(report);summary=failure_summary(project,report)
    units=summary['units'];polish=[u for u in units if u['stage']=='polish']
    pending=[u for u in polish if u.get('status') not in TERMINAL]
    resolved={str(i) for u in polish if u.get('status') in TERMINAL for i in u.get('original_ids',())}
    if polish:
        value=result.setdefault('polishing_summary',copy.deepcopy(project.generation_metadata.get('polishing_summary') or {}))
        result['historical_polishing_summary']=copy.deepcopy(report.get('polishing_summary') or {})
        value['fallback_ids']=[i for u in pending for i in u.get('original_ids',())]
        value['fallback_cues']=len(pending);value['fallback_batches']=int(bool(pending))
        value['failure_records']={str(i):u.get('reason','failed') for u in pending for i in u.get('original_ids',())}
        success={str(i) for i in value.get('success_ids') or ()}|resolved
        success_ids=sorted(map(int,success)) if all(i.isdigit() for i in success) else sorted(success)
        value.update(success_ids=success_ids,success_cues=len(success))
        result['review_items']=[row for row in result.get('review_items',()) if not(row.get('category')=='校对回退' and str(row.get('cue_id')) in resolved)]
        if resolved:
            from .recognition_outcome import review_severity
            from collections import Counter
            result['review_severity_counts']=dict(Counter(review_severity(r) for r in result['review_items']))
    result['_stage_recovery']={k:v for k,v in summary.items() if k!='units'}
    remaining={u['stage'] for u in units if u.get('status') not in TERMINAL}
    if 'grouping' not in remaining and any(u['stage']=='grouping' for u in units):
        result['events']=[e for e in result.get('events',()) if e.get('event')!='grouping_api_fallback']
        result['review_items']=[r for r in result.get('review_items',()) if r.get('category')!='断句回退']
    if 'translation' not in remaining and any(u['stage']=='translation' for u in units):
        result['review_items']=[r for r in result.get('review_items',()) if r.get('category')!='翻译未全部完成']
        for event in result.get('events',()):
            if event.get('event')=='subtitle_translation':event['failed']=0
    if 'review_items' in result:
        from .recognition_outcome import review_severity
        from collections import Counter
        result['review_severity_counts']=dict(Counter(review_severity(r) for r in result['review_items']))
    return result


def refresh_completion_evidence(project,evidence):
    """Completion page and retry button read the same reconciled units."""
    if project is None or not evidence.get('display_payload'):return
    if not recover_units(project,evidence['display_payload']):return
    original=evidence.setdefault('historical_payload',copy.deepcopy(evidence['display_payload']))
    display=effective_report(project,original)
    from .recognition_outcome import normalize_recognition_outcome
    evidence['display_payload']=display
    evidence['outcome']=normalize_recognition_outcome(display)
    evidence['stage_recovery']=failure_summary(project,original)


def save_unit_states(project,report,updates,*,path):
    """Successful states become visible only after the current project saves."""
    metadata=copy.deepcopy(project.generation_metadata)
    ledger=copy.deepcopy(metadata.get(KEY) or {'version':1,'units':{}})
    ledger.setdefault('units',{})
    for unit in updates:
        if unit.get('project_id')!=str(project.project_id):raise ValueError('重试工程已改变')
        if unit.get('input') and not input_matches(project,unit['input']):raise ValueError('重试范围已被编辑；结果未覆盖新修改')
        ledger['units'][unit['key']]=copy.deepcopy(unit)
    metadata[KEY]=ledger
    candidate=copy.copy(project);candidate.generation_metadata=metadata
    from ..projects.studio_project import save_project
    save_project(candidate,Path(path))
    from ..projects.studio_runtime_state import state_for,DirtyDomain
    with state_for(project).transaction(project,action_id='保存阶段重试状态',dirty=DirtyDomain.AUTOSAVE,
            affected_cue_ids=tuple({c for u in updates for c in u.get('cue_ids',())})):
        project.generation_metadata=metadata
    return ledger
