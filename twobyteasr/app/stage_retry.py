"""Execute stable failed units against current text, never restart successful ASR."""
from __future__ import annotations
import copy
import difflib
from dataclasses import asdict

from ..recognition.processing_recovery import recover_units,TERMINAL,input_matches


def proposal_hits(unit,after):
    """Map character edits inside their captured cue; never guess across splits."""
    from ..studio.studio_text_tools import TextOccurrence
    captured=unit['input'];before=captured['text'];parts=captured['parts'];changes={};pending=[]
    for kind,a,b,c,d in difflib.SequenceMatcher(a=before,b=after,autojunk=False).get_opcodes():
        if kind=='equal':continue
        owners=[p for p in parts if p['offset']<=a and b<=p['offset']+len(p['text'])
            and (a<b or a<p['offset']+len(p['text']))]
        if len(owners)!=1:
            pending.append({'before_span':[a,b],'after':after[c:d],'reason':'修改跨越已拆分字幕边界，需人工检查'});continue
        p=owners[0];changes.setdefault(p['cue_id'],[]).append((a-p['offset'],b-p['offset'],after[c:d]))
    hits=[]
    for p in parts:
        replacement=p['text']
        for a,b,text in sorted(changes.get(p['cue_id'],()),reverse=True):replacement=replacement[:a]+text+replacement[b:]
        if replacement!=p['text']:
            hits.append(TextOccurrence(p['cue_id'],p['start_ms'],p['text'],replacement,(0,len(p['text'])),
                reason='失败文字校对重试建议（当前人工修改保留，未核验原音）'))
    return hits,pending


def _settings(project,report,options,stage):
    from .completion_retry import _retry_options
    import json
    if options is None or not options.settings_snapshot_json:
        from ..storage.settings import load_runtime_settings
        from ..recognition.service import RunOptions
        current=load_runtime_settings();current=current[0] if isinstance(current,tuple) else current
        options=RunOptions(settings_snapshot_json=json.dumps(current,ensure_ascii=False))
    if stage=='grouping':
        configured=options
    else:configured=_retry_options(project,report,options)
    settings=json.loads(configured.settings_snapshot_json)
    from ..providers.asr_provider_snapshot import resolve_provider_snapshot
    role='group' if stage=='grouping' else 'polish'
    snapshot=resolve_provider_snapshot(settings,stage=role)
    saved=next((e for e in reversed(report.get('events') or ())
        if e.get('event')=='asr_provider_snapshot' and e.get('stage')==('grouped' if role=='group' else 'polished')),None)
    if saved:
        for key in ('provider','model','transport','protocol','endpoint_identity'):
            if saved.get(key) and str(getattr(snapshot,key))!=str(saved[key]):
                raise ValueError('原任务与当前重试服务身份不一致：'+key)
    return configured,settings,snapshot


def execute_unit(project,report,options,unit,token):
    from ..recognition.processing_recovery import digest
    result=copy.deepcopy(unit);stage=unit['stage'];token.raise_if_cancelled()
    locked=set(project.studio_state.get('locked_cue_ids',()))
    if any(c.id in locked or getattr(c,'locked',False) for c in project.cues if c.id in unit.get('cue_ids',())):
        return {**result,'status':'blocked','retryable':False,'reason':'失败范围有锁定字幕，请解锁后重试；原文保留'}
    if not input_matches(project,unit['input']):raise ValueError('重试输入已改变')
    configured,settings,provider=_settings(project,report,options,stage)
    result.update(status='running',provider=provider.public_identity(),attempts=int(unit.get('attempts',0))+1)
    if stage=='polish':
        import subtitle_core as core
        from ..recognition.transcript_data import SpeechSegment
        from ..recognition.run_context import activate_runtime_context
        from ..subtitle_rules.polishing import retry_failed_polish
        p=unit['input'];parts=p['parts'];record_id=int((unit.get('original_ids') or [1])[0])
        row=SpeechSegment(record_id,parts[0]['start_ms']/1000,parts[-1]['end_ms']/1000,p['text'],1.,[],
            speaker=parts[0]['speaker_id'],moss_text=p['text'],primary_source='current_edited_text',
            caption_arbitration={'retry_mapping_hint':unit.get('failure_detail') or unit.get('reason')})
        context=configured.create_runtime_context(core,cancellation_token=token)
        context.asr_settings_snapshot=settings;context.provider_snapshots={'polish':provider}
        from ..subtitle_rules.subtitle_translation import translation_source
        from ..subtitle_rules.correction_risk import words
        context.task_language=translation_source(project).language
        context.correction_lexical_words=frozenset(word.casefold() for cue in project.cues for word in words(cue.text))
        with activate_runtime_context(context):
            answer=retry_failed_polish([row],project.media.display_name or project.media.path,
                {'fallback_ids':[record_id],'fallback_cues':1},None)
        result['details']=copy.deepcopy(answer.details)
        if record_id not in answer.succeeded:
            result.update(status='failed',reason=answer.failures.get(record_id,'文字校对响应未通过校验'))
        else:
            after=answer.get(record_id,p['text']);hits,pending=proposal_hits(unit,after)
            result.update(status='proposals_pending' if hits or pending else 'completed_no_change',
                proposals=[asdict(h) for h in hits],pending_projection=pending,proposed_text=after,
                reason='文字校对已完成；有修改建议待确认' if hits or pending else '文字校对已完成，无需修改当前文字')
    elif stage=='grouping':
        from ..subtitle_rules.sentence_refine import refine_cues_with_llm,build_replacement_cues
        wanted=set(unit['cue_ids']);cues=[c for c in project.cues if c.id in wanted]
        answer=refine_cues_with_llm(cues,project=project,runtime_settings=settings,
            cancel_check=lambda:token.is_cancelled,batch_size=20,max_attempts=2)
        result['requests']=answer.requests;result['replacements']={};used={c.id for c in project.cues}
        failed=set(answer.failed_cue_ids)
        for action in answer.actions:
            cue=next(c for c in cues if c.id==action.cue_id)
            if action.action=='keep':continue
            replacements=build_replacement_cues(cue,action,project=project,used_ids=used)
            if not replacements:failed.add(cue.id);continue
            if ''.join(c.text for c in replacements).replace(' ','')!=cue.text.replace(' ',''):
                raise ValueError('断句结果不满足文字覆盖与顺序守恒')
            if replacements[0].start_ms!=cue.start_ms or replacements[-1].end_ms!=cue.end_ms:
                raise ValueError('断句结果越出原字幕时间范围')
            result['replacements'][cue.id]=[asdict(c) for c in replacements]
        result.update(status='failed' if failed else 'completed',failed_cue_ids=sorted(failed),
            reason=answer.llm_error or ('缺少可匹配的字词时间边界，已保留原文' if failed else '断句及文字、时间校验完成'))
    elif stage=='translation':
        from ..providers.ai_providers import provider_for_stage
        from ..subtitle_rules.subtitle_translation import translate,translation_source
        client=provider_for_stage(provider.execution_settings(),'polish')
        answer=translate(translation_source(project),unit['cue_ids'],client,target=unit['target'],
            cancel_check=lambda:token.is_cancelled,workers=1)
        result.update(status='failed' if answer.failed or answer.cancelled else 'completed',
            translation_result=answer,reason='; '.join(answer.failed.values()) or '失败译文已重新生成')
    else:raise ValueError('未知失败阶段：'+str(stage))
    token.raise_if_cancelled()
    result['result_digest']=digest({k:v for k,v in result.items() if k!='translation_result'})
    return result


def execute_failed_units(project,report,options=None,*,cancel_token=None,progress=None,unit_ready=None):
    from ..recognition.service import CancellationToken
    from ..providers.provider_diagnostics import redact_diagnostics
    token=cancel_token or CancellationToken();updates=[]
    units=[u for u in recover_units(project,report) if u.get('status') not in TERMINAL]
    for index,unit in enumerate(units,1):
        token.raise_if_cancelled()
        if progress:progress(index-1,len(units),unit)
        if not unit.get('retryable'):
            updates.append(unit)
            if unit_ready:unit_ready(unit)
            continue
        try:result=execute_unit(project,report,options,unit,token)
        except Exception as exc:
            token.raise_if_cancelled()
            result={**copy.deepcopy(unit),'status':'failed','attempts':int(unit.get('attempts',0))+1,'reason':str(redact_diagnostics(str(exc)))[:600]}
        updates.append(result)
        if unit_ready:unit_ready(result)
        if progress:progress(index,len(units),result)
    return updates
