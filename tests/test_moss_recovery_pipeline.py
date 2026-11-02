"""Full production post-ASR path with synthetic candidates and audio boundary."""
import copy
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from tests.test_moss_empty_recovery import EN, DE, raw_rows


def run_fixture(tmp_path, monkeypatch, text, *, language='en', snapshot=None, job='fixture', source_path=None):
    import subtitle_core as core
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    source=Path(source_path) if source_path else tmp_path/'input.wav'
    duration=370.361
    if not source.is_file():
        with wave.open(str(source),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(round(duration*16000)*2))
    settings=copy.deepcopy(core.RUNTIME_SETTINGS)
    settings.setdefault('models',{}).update(primary_asr_backend='api',firered_asr_backend='off',qwen_asr_backend='off',speaker_source='native')
    settings.setdefault('switches',{}).update(enable_ai_polish=False,use_ai_grouping=False,enable_qwen_asr_reference=False,enable_firered_boundary_refinement=False)
    monkeypatch.setattr(core,'RUNTIME_SETTINGS',settings)
    for key,value in dict(PRIMARY_ASR_BACKEND='api',FIRERED_ASR_BACKEND='off',QWEN_ASR_BACKEND='off',
        USE_QWEN_ASR_REFERENCE=False,USE_FIRERED_BOUNDARY_REFINEMENT=False,PARALLEL_CPU_VAD=False,PARALLEL_GPU_ASR=False,USE_AI_GROUPING=False,ENABLE_AI_POLISH=False).items():
        monkeypatch.setattr(core,key,value,raising=False)
    monkeypatch.setattr(pipeline,'detect_lightweight_vad',lambda audio,legacy:[{'start':0.,'end':duration}])
    monkeypatch.setattr(core,'transcribe_primary_reference',lambda *a:raw_rows(text=text))
    ctx=RuntimeContext(job_id=job,requested_language=language,task_language=language,identity_task_active=True,
        studio_project_path=str(tmp_path/f'{job}.2byteproj'),recognition_snapshot=snapshot or {},
        asr_settings_snapshot=settings,speaker_source='native')
    with activate_runtime_context(ctx,legacy=core):
        pipeline.process_media(str(source),1,1,core,ctx)
        report=Path(core.task_reporting.report_paths_for_media(source)[0])
        payload=json.loads(report.read_text('utf8'))
    from twobyteasr.projects.studio_project import load_project
    return load_project(tmp_path/f'{job}.2byteproj'),payload,ctx


def legacy_quarantine(project,report):
    """Construct the documented old outcome; the new pipeline must not create it."""
    from twobyteasr.recognition.transcript_delivery import acceptance_counts
    project.cues=[]
    state=project.generation_metadata['transcript_acceptance']
    state['ranges']=copy.deepcopy(state.get('observed_ranges') or [])
    for r in state['ranges']:r.update(status='pending',reason='text_language_conflict')
    state['observed_ranges']=[];state.pop('policy_version',None)
    state['counts']=acceptance_counts(state['candidate_rows'],[],state)
    report=copy.deepcopy(report);report['status']='degraded_success'
    report['result'].update(cue_count=0,segment_count=0,transcript_counts=state['counts'])
    return project,report


def test_full_chain_133_isolated_then_reused_to_generate_save_reopen_and_srt(tmp_path,monkeypatch):
    from twobyteasr.recognition.transcript_acceptance import pending_ranges
    from twobyteasr.recognition.candidate_reprocess import policy_for
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot
    from twobyteasr.projects.studio_project import save_project,load_project
    from twobyteasr.recognition.recognition_outcome import normalize_recognition_outcome
    pending,report,ctx=run_fixture(tmp_path,monkeypatch,DE)
    assert pending.cues and ctx.task_language=='en'
    pending,report=legacy_quarantine(pending,report)
    assert report['status']=='degraded_success' and not pending.cues
    assert report['result']['transcript_counts']['pending_segment_count']==133
    scopes=pending_ranges(pending.generation_metadata['transcript_acceptance'])
    assert len(scopes)==1
    region=scopes[0]
    policy=policy_for(pending,region,'de',confirmed=True)
    snapshot=capture_recognition_snapshot(pending,str(tmp_path/'fixture.2byteproj'),range_ms=(0,370361))
    snapshot['language_recovery_policy']=policy
    # No second ASR call is allowed on this path, even with an old cloud result.
    monkeypatch.setattr(ctx,'unused',True,raising=False)
    recovered,result,_=run_fixture(tmp_path,monkeypatch,EN,language='de',snapshot=snapshot,job='reuse')
    assert len(recovered.cues)>0 and result['result']['cue_count']>0
    assert result['status'] in {'success','degraded_success'}
    assert all('new game' not in c.text for c in recovered.cues)
    assert not pending_ranges(recovered.generation_metadata['transcript_acceptance'])
    # Replay the written range result through the same second merge as Studio.
    from twobyteasr.recognition.range_recognition import payload_from_result,splice_range
    from twobyteasr.timeline.range_replace import ReplaceRangeCuesCommand
    info=recovered.generation_metadata['timeline_recognition']['range']
    payload=payload_from_result(recovered,info)
    plan=splice_range(pending,info['window_ms'],payload,foreign_speakers=False)
    command=ReplaceRangeCuesCommand(pending,plan)
    command.redo()
    assert pending.generation_metadata['language']['code']=='de'
    command.undo()
    assert pending.generation_metadata['language']['code']=='en'
    command.redo()
    assert pending.generation_metadata['language']['code']=='de'

    save=save_project(recovered,tmp_path/'reopened.2byteproj')
    reopened=load_project(save)
    assert [(c.start_ms,c.end_ms,c.text) for c in reopened.cues]==[(c.start_ms,c.end_ms,c.text) for c in recovered.cues]
    from twobyteasr.exports.studio_subtitle_export import compile_srt
    from twobyteasr.exports.srt_codec import parse_srt
    target=tmp_path/'recovered.srt'
    target.write_text(compile_srt(reopened.cues),'utf8')
    rows,errors=parse_srt(target.read_text('utf8'))
    assert not errors and len(rows)==len(reopened.cues)
    assert [(r.start_ms,r.end_ms,r.text) for r in rows]==[(c.start_ms,c.end_ms,c.text) for c in reopened.cues]
    assert normalize_recognition_outcome(result).result_usable


def test_full_chain_normal_english_generates_subtitles(tmp_path,monkeypatch):
    project,report,_=run_fixture(tmp_path,monkeypatch,EN)
    assert project.cues and report['result']['cue_count']>0
    assert report['result']['transcript_counts']['accepted_segment_count']==133



def test_old_full_quarantine_can_continue_manual_english_without_switching_to_german(tmp_path,monkeypatch):
    from twobyteasr.recognition.transcript_acceptance import pending_ranges
    from twobyteasr.recognition.candidate_reprocess import policy_for
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot
    from twobyteasr.projects.studio_project import save_project
    project,report,_=run_fixture(tmp_path,monkeypatch,DE)
    project,report=legacy_quarantine(project,report)
    save_project(project,tmp_path/'legacy.2byteproj')
    region=pending_ranges(project.generation_metadata['transcript_acceptance'])[0]
    policy=policy_for(project,region,'en',confirmed=False)
    assert policy['kept_manual_choice'] and not policy['confirmed_after_listening']
    snapshot=capture_recognition_snapshot(project,str(tmp_path/'legacy.2byteproj'),range_ms=(0,370361))
    snapshot['language_recovery_policy']=policy
    recovered,result,context=run_fixture(tmp_path,monkeypatch,EN,language='en',snapshot=snapshot,job='manual-upgrade')
    assert context.task_language=='en' and recovered.generation_metadata['language']['requested']=='en'
    assert recovered.cues and result['result']['transcript_counts']['accepted_segment_count']==133
    assert not pending_ranges(recovered.generation_metadata['transcript_acceptance'])
    assert any(e['event']=='asr_candidate_reused' for e in result['events'])
    assert not any(e['event']=='cloud_worker_launch' for e in result['events'])
    assert all('new game' not in c.text for c in recovered.cues)
