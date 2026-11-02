"""Synthetic source text and simulated provider boundary; never user audio."""
import copy
import json
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.recognition.transcript_acceptance import gate_primary, pending_ranges
from twobyteasr.recognition.language_diagnostics import audit_primary_language
from twobyteasr.recognition.recognition_outcome import normalize_recognition_outcome, normalize_recognition_queue

DE = 'Hier ist das neue Spiel und wir sind jetzt auf der Insel. Ich habe die Karte und wir gehen mit dem Boot. '
EN = 'This is the new game and we are on the island. I have the map and we will go to the boat. '


def raw_rows(count=133, seconds=370.361, text=DE):
    rows = [dict(start=seconds*i/count, end=seconds*(i+1)/count, text=text, speaker='S00', source='synthetic_mosi') for i in range(count)]
    rows[0]['asr_language_receipt'] = dict(start=0., end=seconds, remote_task_id='synthetic-remote',
        request_language=None, language_control='automatic_only', transcript={'language':'de'})
    return rows


def gate(tmp_path, rows, language='en', audio=None):
    audio = np.zeros(round(max(r['end'] for r in rows)*16000), dtype=np.float32) if audio is None else audio
    ctx = RuntimeContext(requested_language=language, task_language=language)
    events = []
    legacy = SimpleNamespace(record_run_event=lambda event, **data: events.append(dict(event=event, **data)),
        add_review_item=lambda *args, **kw: None)
    from twobyteasr.recognition.language_decision import bind
    bind(ctx,[r['text'] for r in rows])
    audit = audit_primary_language(rows, ctx, legacy)
    selected = gate_primary({'segments':rows, 'references':rows}, audio, ctx, legacy, {'cache_dir':str(tmp_path)}, audit)
    return selected['segments'], ctx, events


def test_133_manual_candidates_are_retained_and_observation_actionable(tmp_path):
    rows=raw_rows();selected,ctx,events=gate(tmp_path,rows)
    assert selected==rows and ctx.task_language=='en'
    counts=ctx.transcript_acceptance['counts']
    assert (counts['candidate_segment_count'],counts['accepted_segment_count'],counts['pending_segment_count'])==(133,133,0)
    assert not pending_ranges(ctx.transcript_acceptance)
    observations=ctx.transcript_acceptance['observed_ranges']
    assert len(observations)==1 and len(observations[0]['raw_rows'])==133 and observations[0]['pcm_sha256']
    assert ctx.transcript_acceptance['candidate_rows']==rows


def test_legacy_attachment_shape_is_not_success():
    report = dict(status='degraded_success',result={'cue_count':0,'segment_count':0,'outputs':{'project':'empty'}},events=[
        dict(event='MODEL_RESULT_AVAILABLE',role='primary_transcription',segment_count=133),
        dict(event='transcript_acceptance',accepted_ranges=0,pending_ranges=[dict(start=0,end=370.361,reason='text_language_conflict')])])
    assert normalize_recognition_outcome(report).core_status == 'needs_recovery'


def test_actual_source_text_is_audited_not_old_receipt_or_translation(tmp_path):
    rows = raw_rows(text=EN)
    rows[0]['translation'] = DE*20
    selected, ctx, _ = gate(tmp_path, rows)
    assert len(selected) == 133
    assert not pending_ranges(ctx.transcript_acceptance)


def test_german_language_correction_reuses_all_candidates(tmp_path):
    selected, ctx, _ = gate(tmp_path, raw_rows(), language='de')
    assert len(selected) == 133 and not pending_ranges(ctx.transcript_acceptance)


def test_local_conflict_keeps_normal_part_of_same_request(tmp_path):
    rows = raw_rows(count=60, seconds=120.)
    for row in rows[30:]:
        row['text'] = EN
    selected, ctx, _ = gate(tmp_path, rows)
    assert selected == rows
    assert ctx.transcript_acceptance['counts']['pending_segment_count'] == 0
    assert all(r['end'] <= 60. for r in ctx.transcript_acceptance['observed_ranges'])


def test_pending_decision_recomputed_after_text_or_strategy_change(tmp_path):
    gate(tmp_path, raw_rows())
    selected, ctx, events = gate(tmp_path, raw_rows(text=EN))
    assert len(selected) == 133 and not pending_ranges(ctx.transcript_acceptance)
    assert any(e['event']=='transcript_selection_invalidated' for e in events)


@pytest.mark.parametrize('text', ['Doom Elden Ring DaVinci Resolve', 'Ich bin', EN + ' DaVinci ciao danke'])
def test_short_names_and_mixed_english_are_inconclusive_or_english(text):
    from twobyteasr.recognition.language_diagnostics import transcript_language_sample
    assert transcript_language_sample([text])['language'] in {None, 'en'}


@pytest.mark.parametrize('status,expected', [('no_speech','no_speech'),('failed','failed'),('empty_result','empty_result'),('needs_recovery','needs_recovery')])
def test_empty_terminals_are_distinct(status, expected):
    report=dict(status=status, result={'cue_count':0,'error':'VAD found no speech' if status=='no_speech' else ''})
    outcome=normalize_recognition_outcome(report)
    assert outcome.core_status==expected and not outcome.result_usable


def test_silence_is_vad_evidence_not_language_isolation():
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition.transcript_delivery import NoSpeechDetected
    with pytest.raises(NoSpeechDetected):
        pipeline.detect_lightweight_vad(np.zeros(16000,np.float32), SimpleNamespace(AUDIO_SAMPLE_RATE=16000))


def test_explicit_cloud_retry_bypasses_aggregate_and_native_results(tmp_path, monkeypatch):
    from twobyteasr.recognition.cache import cache_stage_signature, _stage_cache_path
    from twobyteasr.providers.cloud_asr_jobs import job_root
    from twobyteasr.providers import mosi_asr
    from tests.test_no_cuda_cloud_asr import MosiClient, mosi_endpoint
    audio=np.zeros(16000,np.float32)
    endpoint=mosi_endpoint()
    client=MosiClient(segments=[dict(start=.1,end=.9,text=EN,speaker='S00')])
    old_root=job_root(audio,endpoint,tmp_path)
    first=mosi_asr.transcribe(audio,endpoint,tmp_path,client=client,sleep=lambda _:None)
    assert len(client.posts)==1
    with activate_runtime_context(RuntimeContext(job_id='original')):
        old_sig=cache_stage_signature('primary_api')
        audio_sig=cache_stage_signature('audio')
        vad_sig=cache_stage_signature('firered_vad')
        old_path=_stage_cache_path('primary_api',{'cache_dir':str(tmp_path)},old_sig)
    prior={p:p.read_bytes() for p in old_root.rglob('result.json')}
    ctx=RuntimeContext(job_id='new-explicit-cloud',recognition_snapshot={'language_recovery_policy':{'force_cloud':True}})
    with activate_runtime_context(ctx):
        new_sig=cache_stage_signature('primary_api')
        assert old_sig!=new_sig
        assert _stage_cache_path('primary_api',{'cache_dir':str(tmp_path)},new_sig)!=old_path
        assert cache_stage_signature('audio')==audio_sig and cache_stage_signature('firered_vad')==vad_sig
        endpoint['asr_request_generation']=ctx.job_id
        assert job_root(audio,endpoint,tmp_path)!=old_root
        second=mosi_asr.transcribe(audio,endpoint,tmp_path,client=client,sleep=lambda _:None)
    assert len(client.posts)==2
    assert all(p.read_bytes()==data for p,data in prior.items())
    assert 'language' not in client.posts[-1][1]['form']
    assert 'asr_request_generation' not in client.posts[-1][1]['form']


def test_empty_result_never_clears_snapshot_cues_or_manual_fields(tmp_path):
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.recognition.recognition_input import attach_timeline_result
    p=SubtitleProject(StudioMedia('original.wav',duration_ms=2000),cues=[StudioCue('edited',0,2000,'My edited subtitle')])
    p.generation_metadata['translations']={'edited':'人工译文'}
    p.cues[0].appearance_override={'outline_width':3.5}
    empty=SubtitleProject(StudioMedia('input.wav',duration_ms=2000))
    empty.generation_metadata['transcript_acceptance']={'ranges':[{'status':'pending'}]}
    before=p.to_dict()
    result=attach_timeline_result(empty, {'project':before})
    assert [c.text for c in result.cues]==['My edited subtitle']
    assert result.generation_metadata['translations']=={'edited':'人工译文'}
    assert result.cues[0].appearance_override=={'outline_width':3.5}
    assert p.to_dict()==before


def test_candidate_replay_checks_input_and_never_calls_provider(tmp_path,monkeypatch):
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject
    from twobyteasr.recognition.candidate_reprocess import policy_for,replay_rows
    from twobyteasr.playback.audio_graph import capture_audio_graph
    from twobyteasr.recognition.alignment_audio import pcm_digest
    audio=np.zeros(32000,np.float32)
    p=SubtitleProject(StudioMedia('source.wav',duration_ms=2000))
    region=dict(id='scope',start=0.,end=2.,raw_rows=[dict(start=0.,end=2.,text=DE,speaker='S02')],pcm_sha256=pcm_digest(audio))
    policy=policy_for(p,region,'de',confirmed=True)
    ctx=RuntimeContext(requested_language='de',recognition_snapshot={'audio_graph':capture_audio_graph(p),
        'range_ms':[0,2000],'language_recovery_policy':policy})
    rows=replay_rows(audio,ctx)
    assert rows[0]['text']==DE and rows[0]['speaker']=='S02'
    ctx.recognition_snapshot['audio_graph']={'changed':True}
    with pytest.raises(ValueError,match='音轨或混音已变化'):
        replay_rows(audio,ctx)


def test_repeated_game_words_or_names_do_not_manufacture_foreign_language():
    from twobyteasr.recognition.language_diagnostics import transcript_language_sample
    assert transcript_language_sample(['die ' * 300])['language'] is None
    assert transcript_language_sample(['Bjoerk DaVinci ' * 150])['language'] is None


def test_cloud_button_policy_reaches_owned_worker_nonce(tmp_path,monkeypatch):
    from tests.test_no_cuda_cloud_asr import mosi_endpoint
    from twobyteasr.providers.asr_api_process import transcribe
    from twobyteasr.recognition import asr
    captured=[]
    def worker(command,output,**kw):
        captured.append(json.loads(kw['input_text']))
        return {'results':[{'start':0.,'end':1.,'text':EN}]}
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',worker)
    ctx=RuntimeContext(job_id='explicit-cloud-button',requested_language='en',asr_endpoint_snapshot=mosi_endpoint(),
        recognition_snapshot={'language_recovery_policy':{'force_cloud':True}},asr_settings_snapshot={'models':{}})
    with activate_runtime_context(ctx):
        transcribe(str(tmp_path/'input.wav'),[dict(start=0.,end=1.,audio=(np.zeros(16000,np.float32),16000))],publish_primary=True,cache_root=tmp_path/'jobs')
    assert captured[0]['endpoint']['asr_request_generation']=='explicit-cloud-button'
    assert captured[0]['requested_language']=='en'


def test_no_speech_failed_vad_stage_is_still_no_speech():
    report=dict(status='no_speech',result={'cue_count':0,'error':'VAD found no speech'},
        stages=[{'label':'VAD','status':'failed','error':'VAD found no speech'}])
    assert normalize_recognition_outcome(report).core_status=='no_speech'


def test_quarantine_diagnosis_does_not_claim_silence():
    from twobyteasr.recognition.run_diagnosis import DiagnosisInput,diagnose_run
    report=dict(status='needs_recovery',result={'cue_count':0,'transcript_counts':{
        'candidate_segment_count':133,'pending_range_count':1}})
    diagnosis=diagnose_run(DiagnosisInput(report=report))
    assert diagnosis.headline().rule_id=='transcript_quarantined'
    assert 'empty_result' not in diagnosis.rule_ids


def test_range_replay_shifts_native_word_times_to_local_clock(tmp_path):
    from twobyteasr.recognition.candidate_reprocess import replay_rows
    from twobyteasr.recognition.transcript_acceptance import digest
    from twobyteasr.recognition.alignment_audio import pcm_digest
    audio=np.zeros(32000,np.float32)
    rows=[dict(start=60.,end=62.,text='The game',tokens=[dict(start=60.,end=60.5,text='The'),dict(start=60.6,end=61.9,text='game')])]
    policy=dict(reuse_candidates=True,confirmed_after_listening=True,candidate_rows=rows,candidate_rows_sha256=digest(rows),
        candidate_scope=[60.,62.],audio_graph_digest=digest({}),pcm_sha256=pcm_digest(audio))
    context=RuntimeContext(recognition_snapshot={'range_ms':[60000,62000],'audio_graph':{},'language_recovery_policy':policy})
    got=replay_rows(audio,context)
    assert got[0]['start']==0 and got[0]['tokens'][0]['start']==0
    assert got[0]['tokens'][1]['end']==pytest.approx(1.9)
    assert rows[0]['tokens'][0]['start']==60.
