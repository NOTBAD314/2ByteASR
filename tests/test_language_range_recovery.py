"""Local recovery and accepted-result boundaries; no real network or model load."""
import copy
import json
from types import SimpleNamespace
import numpy as np
import pytest

from twobyteasr.recognition.local_language_recovery import plan_windows
from twobyteasr.recognition.transcript_acceptance import (
    apply_selection, digest, gate_primary, pending_ranges, register_candidate)
from twobyteasr.recognition.run_context import RuntimeContext
from tests.test_asr_language_provenance import IT, EN


def candidate(language='English', probes=('English','English')):
    return dict(attempt_id='attempt-local', model='Qwen3-ASR-1.7B', policy={'language':language}, identity={},
        rows=[dict(start=0.,end=2.,text='So I will reset the saturation parameter.',language=language)],
        language_evidence={'language':'en'}, raw_payload='isolated.json',
        acoustic_samples=[dict(request_language=None,language=p,text='A real sample') for p in probes])


def pending():
    return dict(version=1,identity={'requested_language':'en'},ranges=[dict(id='scope',start_sample=0,
        end_sample=32000,start=0.,end=2.,status='pending',attempts=[],raw_rows=[])])


def test_sample_exact_quiet_windows_cover_every_sample():
    audio=np.ones(1800000,dtype=np.float32)*.1
    audio[330000:334000]=0
    windows=plan_windows(audio,123,1799999)
    assert windows[0][0]==123 and windows[-1][1]==1799999
    assert all(a[1]==b[0] for a,b in zip(windows,windows[1:]))
    assert all(0<end-start<=26*16000 for start,end in windows)
    assert sum(end-start for start,end in windows)==1799999-123


def test_forced_english_label_is_not_automatic_acoustic_evidence():
    result=register_candidate(pending(),'scope',candidate(probes=('Italian','Italian')))
    assert result['ranges'][0]['status']=='pending'
    assert result['ranges'][0]['reason']=='acoustic_language_unconfirmed'
    assert pending_ranges(result)


def test_selected_english_persists_and_old_cloud_rows_never_win(tmp_path):
    result=register_candidate(pending(),'scope',candidate(),speaker_intervals=[dict(start=0,end=2,speaker='stable-person')])
    p=tmp_path/'selection.json';p.write_text(json.dumps(result),encoding='utf8')
    reopened=json.loads(p.read_text('utf8'))
    old=[dict(start=0,end=2,text=IT,speaker='old'),dict(start=4,end=5,text='Valid later English',speaker='stable-person')]
    for _ in range(3):
        selected=apply_selection(old,reopened)
        assert selected[0]['text'].startswith('So I will reset')
        assert selected[0]['speaker']=='stable-person'
        assert selected[1]==old[1]
    reopened['ranges'][0]['accepted_rows'][0]['text']='tampered'
    with pytest.raises(ValueError,match='身份损坏'):apply_selection(old,reopened)


def test_ambiguous_audio_intervals_keep_unknown_speaker():
    from twobyteasr.recognition.transcript_acceptance import recovered_rows
    rows=recovered_rows(candidate(),speaker_intervals=[dict(start=0,end=1,speaker='a'),dict(start=1,end=2,speaker='b')])
    assert rows[0]['speaker']=='RECOVERY_UNCONFIRMED'
    assert not rows[0]['speaker_assignment']['confirmed']


def _audit():
    return dict(conflicts=1,regions=[dict(start=0,end=2,transcript={'language':'it'},remote_task_id='remote-success')])


def _legacy():
    return SimpleNamespace(record_run_event=lambda *a,**kw:None)


def test_gate_keeps_remote_success_but_never_aligns_wrong_primary(tmp_path):
    ctx=RuntimeContext(requested_language='en',task_language='en')
    raw=[dict(start=0,end=2,text=IT),dict(start=3,end=4,text=EN)]
    got=gate_primary({'segments':raw,'references':raw},np.zeros(64000),ctx,_legacy(),{'cache_dir':str(tmp_path)},_audit())
    assert got['segments']==[raw[1]]
    state=ctx.transcript_acceptance
    assert state['ranges'][0]['remote_status']=='SUCCESS'
    assert state['ranges'][0]['raw_rows']==[raw[0]]
    assert len(pending_ranges(state))==1
    assert (tmp_path/'primary-selection-en.json').exists()


def test_normal_task_does_not_hash_audio_or_start_second_asr(tmp_path,monkeypatch):
    from twobyteasr.recognition import transcript_acceptance as acceptance
    monkeypatch.setattr(acceptance,'identity_for',lambda *a:(_ for _ in ()).throw(AssertionError('unexpected audio work')))
    raw={'segments':[dict(start=0,end=1,text=EN)]}
    assert gate_primary(raw,np.zeros(10),RuntimeContext(requested_language='en'),_legacy(),
                        {'cache_dir':str(tmp_path)},{'conflicts':0}) is raw


@pytest.mark.parametrize('error',['model not installed','CUDA unavailable','CUDA out of memory'])
def test_unavailable_local_recovery_is_pending_and_attempted_only_once(tmp_path,monkeypatch,error):
    from twobyteasr.recognition import local_language_recovery as local
    calls=[]
    def fail(*a,**kw):calls.append(1);raise RuntimeError(error)
    monkeypatch.setattr(local,'recognize_range',fail)
    ctx=RuntimeContext(requested_language='en',task_language='en',
                       recognition_snapshot={'language_recovery_policy':{'allow_local_once':True}})
    raw={'segments':[dict(start=0,end=2,text=IT),dict(start=3,end=4,text=EN)]}
    for _ in range(2):
        got=gate_primary(raw,np.zeros(64000),ctx,_legacy(),{'cache_dir':str(tmp_path)},_audit())
        assert got['segments']==[raw['segments'][1]]
    assert len(calls)==1 and len(pending_ranges(ctx.transcript_acceptance))==1


def test_cancellation_keeps_saved_pending_scope(tmp_path,monkeypatch):
    from twobyteasr.recognition import local_language_recovery as local
    from twobyteasr.recognition.service import CancelledError
    def cancel(*a,**kw):raise CancelledError('cancel')
    monkeypatch.setattr(local,'recognize_range',cancel)
    ctx=RuntimeContext(requested_language='en',task_language='en',
                       recognition_snapshot={'language_recovery_policy':{'allow_local_once':True}})
    with pytest.raises(CancelledError):
        gate_primary({'segments':[dict(start=0,end=2,text=IT)]},np.zeros(32000),ctx,_legacy(),{'cache_dir':str(tmp_path)},_audit())
    assert pending_ranges(json.loads((tmp_path/'primary-selection-en.json').read_text('utf8')))


@pytest.mark.parametrize('backend,model',[('qwen_local','Qwen3-ASR-1.7B'),('api','explicit-alternate-model')])
def test_range_translations_styles_outside_and_undo_are_stable(tmp_path,backend,model):
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,load_project
    from twobyteasr.recognition.range_recognition import range_payload,splice_range,apply_plan,history_entry
    from twobyteasr.recognition.language_recovery_project import inherit_range_appearance
    from twobyteasr.subtitle_rules import subtitle_translation as tr
    from twobyteasr.timeline.range_replace import ReplaceRangeCuesCommand
    p=SubtitleProject(StudioMedia('',duration_ms=10000),cues=[StudioCue('old',0,2000,IT),StudioCue('keep',4000,6000,'Valid later English')])
    p.validate();p.cues[0].appearance_override={'outline_width':2.5}
    tr.set_manual(p,'old','旧意大利语的译文',target='zh-Hans');tr.set_manual(p,'keep','保留译文',target='zh-Hans')
    p.generation_metadata['transcript_acceptance']=pending()
    result=SubtitleProject(StudioMedia('',duration_ms=2000),cues=[StudioCue('new',0,2000,'So I will reset the saturation parameter.')])
    result.validate();tr.set_manual(result,'new','所以我会重置饱和度参数。',target='zh-Hans')
    result.generation_metadata['transcript_acceptance']=register_candidate(pending(),'scope',candidate())
    result.generation_metadata['transcript_acceptance']['ranges'][0]['selected_attempt'].update(backend=backend,model=model)
    payload=range_payload(result,0,2000,prefix='recovered')
    plan=splice_range(p,(0,2000),payload,foreign_speakers=False);inherit_range_appearance(p,plan)
    before=copy.deepcopy(p.to_dict());entry=history_entry(plan)
    command=ReplaceRangeCuesCommand(p,plan,entry)
    command.redo()
    assert p.cues[-1].to_dict() if hasattr(p.cues[-1],'to_dict') else p.cues[-1].text=='Valid later English'
    assert p.generation_metadata['translations']['keep']=='保留译文'
    assert p.generation_metadata['translations']['recovered-new']=='所以我会重置饱和度参数。'
    assert 'old' not in p.generation_metadata['translation_records']['records']
    assert p.cues[0].appearance_override['outline_width']==2.5
    assert not pending_ranges(p.generation_metadata['transcript_acceptance'])
    assert p.generation_metadata['transcript_acceptance']['ranges'][0]['requested_language']=='en'
    receipt=p.generation_metadata['transcript_acceptance']['range_results'][-1]
    assert (receipt['backend'],receipt['model'])==(backend,model)
    save=save_project(p,tmp_path/'copy.2byteproj');reopened=load_project(save)
    assert reopened.cues[0].text.startswith('So I will reset')
    command.undo()
    after=p.to_dict()
    # Saving intentionally advances this bookkeeping timestamp; undo restores
    # authored fields, translations and scope state rather than the clock.
    after.pop('updated_at',None);before.pop('updated_at',None)
    assert after==before


def test_sheet_language_override_does_not_change_home_choice():
    from twobyteasr.app.ui import studio_translation_choice
    home={'recognition_language':'it','subtitle_output':'original','translation_script':'zh-Hans'}
    result=studio_translation_choice(home,{'recognition_language':'en','subtitle_output':'bilingual'},True)
    assert result['recognition_language']=='en' and home['recognition_language']=='it'


def test_local_attempt_cache_and_generation_cap_are_real_dependencies(tmp_path,monkeypatch):
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.local_language_recovery import recognize_range
    import sys
    model=tmp_path/'model';model.mkdir();(model/'config.json').write_text('{}')
    monkeypatch.setattr(asr,'resolve_qwen_asr_local_source',lambda:str(model))
    monkeypatch.setattr(asr,'_main_worker_python',lambda:sys.executable)
    calls=[]
    def worker(command,output,**kw):
        manifest=json.loads(open(command[command.index('--manifest')+1],encoding='utf8').read())
        calls.append(manifest['policy']['language'])
        return {'results':[dict(segment_id=j['segment_id'],start=j['start'],end=j['end'],samples=j['samples'],
            pcm_sha256=j['pcm_sha256'],text=EN if manifest['policy']['language']=='English' else IT,
            language=manifest['policy']['language'],request_language=j['language'],
            generation={'output_tokens':80,'eos_observed':True,'token_limit_reached':False}) for j in manifest['jobs']]}
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',worker)
    a=np.zeros(32000,np.float32)
    first=recognize_range(a,0,len(a),language='en',cache_root=tmp_path/'cache')
    assert recognize_range(a,0,len(a),language='en',cache_root=tmp_path/'cache')['attempt_id']==first['attempt_id']
    recognize_range(a,0,len(a),language='it',cache_root=tmp_path/'cache')
    assert calls==['English','Italian']


def test_cached_primary_restores_its_acceptance_receipt(tmp_path):
    from twobyteasr.recognition.transcript_acceptance import identity_for
    a=np.zeros(32000,np.float32);c=candidate();c['identity']={'pcm_sha256':identity_for(a,'en')['pcm_sha256']}
    state=register_candidate(pending(),'scope',c)
    row=copy.deepcopy(state['ranges'][0]['accepted_rows'][0]);row['transcript_acceptance_receipt']=state
    ctx=RuntimeContext(requested_language='en',recognition_snapshot={'language_recovery_policy':{'explicit_local_range':True}})
    gate_primary({'segments':[row]},a,ctx,_legacy(),{'cache_dir':str(tmp_path)},{'conflicts':0})
    assert ctx.transcript_acceptance['ranges'][0]['status']=='accepted'


def test_accepted_zero_cues_can_save_pending_project_without_alignment(tmp_path):
    import wave
    import subtitle_core as core
    from twobyteasr.recognition.run_context import activate_runtime_context
    from twobyteasr.recognition.pipeline_runtime import complete_media_run
    from twobyteasr.recognition.recognition_result import media_identity_for_task
    from twobyteasr.recognition.language_diagnostics import audit_primary_language
    from twobyteasr.projects.studio_project import load_project
    source=tmp_path/'source.wav'
    with wave.open(str(source),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(64000))
    ctx=RuntimeContext(job_id='e'*32,requested_language='en',task_language='en',media_path=str(source),
                       studio_project_path=str(tmp_path/'pending.2byteproj'),identity_task_active=True)
    rows=[dict(start=0.,end=2.,text=IT)]
    with activate_runtime_context(ctx,legacy=core):
        cache=core.media_cache_context(source);ctx.media_identity=media_identity_for_task(source,ctx)
        core.begin_media_report(source,cache)
        audit=audit_primary_language(rows,ctx,core)
        result=gate_primary({'segments':rows},np.zeros(32000),ctx,core,cache,audit)
        assert not result['segments']
        complete_media_run(cues=[],segments=[],file_index=1,file_total=1,started=__import__('time').perf_counter(),
            audio_seconds=2,txt_path='',srt_path='',stage_index=1,stage_total=1,legacy=core,runtime_context=ctx)
    p=load_project(tmp_path/'pending.2byteproj')
    assert not p.cues and len(pending_ranges(p.generation_metadata['transcript_acceptance']))==1


def test_unknown_recovery_speaker_is_not_forced_onto_first_old_track():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker
    from twobyteasr.recognition.range_recognition import range_payload,splice_range,apply_plan
    p=SubtitleProject(StudioMedia('',duration_ms=4000),cues=[StudioCue('a',0,2000,IT,speaker_id='person-a')],
        speakers=[StudioSpeaker(id='person-a')]);p.validate()
    result=SubtitleProject(StudioMedia('',duration_ms=2000),cues=[StudioCue('b',0,2000,'English',speaker_id='RECOVERY_UNCONFIRMED')])
    result.validate();result.generation_metadata['transcript_acceptance']=register_candidate(pending(),'scope',candidate())
    payload=range_payload(result,0,2000,prefix='recovery');plan=splice_range(p,(0,2000),payload,foreign_speakers=True)
    apply_plan(p,plan)
    assert p.cues[0].speaker_id=='RECOVERY_UNCONFIRMED'
    assert {s.id for s in p.speakers}=={'person-a','RECOVERY_UNCONFIRMED'}


def test_reopened_project_selection_beats_old_moss_cache(tmp_path):
    import hashlib
    audio=np.zeros(64000,np.float32);source=tmp_path/'source.bin';source.write_bytes(b'same audio source')
    state=dict(version=1,audio_graph_digest=digest({}),
        source_identities={str(source):{'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}},ranges=[dict(
        id='chosen',start=0.,end=2.,status='accepted',accepted_cue_ids=['recovered'])])
    snapshot={'audio_graph':{},'project':{'generation_metadata':{'transcript_acceptance':state,'language':{'requested':'en'}},
        'cues':[dict(id='recovered',start_ms=0,end_ms=2000,text='The recovered English remains selected.',speaker_id='stable')]}}
    ctx=RuntimeContext(requested_language='en',task_language='en',recognition_snapshot=snapshot)
    raw={'segments':[dict(start=0,end=2,text=IT),dict(start=3,end=4,text=EN)]}
    selected=gate_primary(raw,audio,ctx,_legacy(),{'cache_dir':str(tmp_path/'cache')},_audit())
    assert selected['segments'][0]['text']=='The recovered English remains selected.'
    assert selected['segments'][1]==raw['segments'][1]
    assert not pending_ranges(ctx.transcript_acceptance)


def test_cancelled_worker_reuses_valid_partial_windows_on_explicit_retry(tmp_path,monkeypatch):
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.local_language_recovery import recognize_range
    import sys
    model=tmp_path/'model';model.mkdir();(model/'config.json').write_text('{}')
    monkeypatch.setattr(asr,'resolve_qwen_asr_local_source',lambda:str(model))
    monkeypatch.setattr(asr,'_main_worker_python',lambda:sys.executable)
    dispatched=[]
    def row(j):
        return dict(segment_id=j['segment_id'],start=j['start'],end=j['end'],samples=j['samples'],
                    pcm_sha256=j['pcm_sha256'],request_language=j['language'],text=EN,language='English',
                    generation={'eos_observed':True,'output_tokens':80,'token_limit_reached':False})
    def worker(command,output,**kw):
        manifest=json.loads(open(command[command.index('--manifest')+1],encoding='utf8').read())
        dispatched.append([j['segment_id'] for j in manifest['jobs']])
        if len(dispatched)==1:
            from pathlib import Path
            Path(output).with_suffix('.partial.json').write_text(json.dumps({'results':[row(manifest['jobs'][0])]}))
            raise RuntimeError('simulated interrupted process')
        return {'results':[row(j) for j in manifest['jobs']]}
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',worker)
    audio=np.zeros(60*16000,np.float32)
    with pytest.raises(RuntimeError,match='interrupted'):
        recognize_range(audio,0,len(audio),language='en',cache_root=tmp_path/'cache')
    with pytest.raises(RuntimeError,match='明确重试'):
        recognize_range(audio,0,len(audio),language='en',cache_root=tmp_path/'cache')
    result=recognize_range(audio,0,len(audio),language='en',cache_root=tmp_path/'cache',retry=True)
    assert result['resumed_windows']==1 and 1 not in dispatched[1]
    assert len(dispatched)==2
