"""Risk checks for identity pollution, original spans, head slots and bounded OOM."""
import copy
import json
from types import SimpleNamespace
import numpy as np
import pytest
from twobyteasr.recognition.alignment_backend import profile, receipt_matches
from twobyteasr.recognition.ultra_local_head import safe_boundaries
from twobyteasr.forced_alignment import word_units, char_units


def receipt(backend='qwen_ultra_aligner'):
    identity=profile(backend)
    return {**{key:identity[key] for key in ('model','model_revision','code','unit_policy')},
            'alignment_identity':identity}


@pytest.mark.parametrize('key', ['files','model_revision','implementation','unit_policy','span_mapping',
                                  'postprocess','audio','tokenizers','local_head'])
def test_result_affecting_identity_change_cannot_borrow_evidence(key):
    data=receipt()
    data['alignment_identity'][key]='changed'
    assert not receipt_matches(data, profile('qwen_ultra_aligner'))


def test_legacy_official_can_never_be_relabelled_ultra():
    data=receipt('qwen_aligner');data.pop('alignment_identity')
    assert receipt_matches(data, profile('qwen_aligner'), allow_legacy=True)
    assert not receipt_matches(data, profile('qwen_ultra_aligner'), allow_legacy=True)
    data.update(model=profile('qwen_ultra_aligner')['model'],model_revision=profile('qwen_ultra_aligner')['model_revision'])
    assert not receipt_matches(data, profile('qwen_ultra_aligner'), allow_legacy=True)


@pytest.mark.parametrize('text,words', [
    ('ｶﾞｯﾂﾎﾟｰｽﾞ！',['ガッツポーズ']),
    ('か\u3099っこうー。',['がっこうー']),
    ('ＡＢＣ１２3、東京Qwen！',['ABC','123','東京','Qwen']),
    ('あっ、あっ、ゲームー！',['あっ','あっ','ゲームー']),
])
def test_mixed_japanese_keeps_original_display_spans(text,words):
    units=word_units(text,words)
    for unit in units:
        assert text[unit.char_start:unit.char_end]
    chars=char_units(text,units)
    assert chars and all(0<=u.char_start<u.char_end<=len(text) for u in chars)
    if 'ｶﾞ' in text:
        assert chars[0].char_start==0 and chars[0].char_end==2
    assert text.endswith(('！','。'))


@pytest.mark.parametrize('candidate,reason', [
    ([float('nan'),500],'nonfinite'), ([-1,500],'outside_window'),
    ([100,101],'degenerate_duration'), ([100,450],'possible_tail_shortening')])
def test_head_rejects_unsafe_window_without_inventing_times(candidate,reason):
    assert safe_boundaries([100,500],candidate,1000)==([100,500],reason)


def test_head_overlap_projection_keeps_refined_precision():
    value,reason=safe_boundaries([100,400,400,700],[96.412,420,410,690.77],1000)
    assert reason is None and value==[96.412,415.,415.,690.77]


def test_cache_rejects_wrong_actual_backend_and_poisoned_metadata(tmp_path):
    from twobyteasr.recognition.alignment_checkpoints import run_cached
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    import gzip
    jobs=[dict(id='one',text='a',language='English',window_start_ms=0,window_end_ms=1000)]
    identity=profile('qwen_ultra_aligner')
    calls=[]
    def runner(items):
        calls.append(len(items))
        return dict(receipt(),results=[dict(job,status='aligned') for job in items])
    with activate_runtime_context(RuntimeContext()):
        run_cached(np.zeros(16000,dtype=np.float32),jobs,identity=identity,runner=runner,root=tmp_path)
        cache=next(tmp_path.glob('*.json.gz'))
        data=json.loads(gzip.decompress(cache.read_bytes()))
        data['metadata']['alignment_identity']['files']={}
        cache.write_bytes(gzip.compress(json.dumps(data).encode()))
        run_cached(np.zeros(16000,dtype=np.float32),jobs,identity=identity,runner=runner,root=tmp_path)
        assert calls==[1,1]
        with pytest.raises(ValueError,match='backend identity'):
            run_cached(np.zeros(16000,dtype=np.float32),jobs,identity=profile('qwen_ultra_head'),
                       runner=lambda items:dict(receipt('qwen_aligner'),results=[dict(jobs[0],status='aligned')]),
                       root=tmp_path)


def test_oom_batch_reduction_is_finite_and_preserves_order(tmp_path,monkeypatch):
    import qwen_aligner_worker as worker
    from twobyteasr import forced_alignment as fa
    calls=[]
    def infer(aligner,audios,unit_lists,torch,**kwargs):
        calls.append(len(audios))
        if len(audios)>1: raise RuntimeError('CUDA out of memory (injected)')
        return [([80,160],[80,160],{'p_max':[.9,.9],'p_local':[.9,.9],'spread_ms':[1,1]})]
    monkeypatch.setattr(worker,'_tokenize',lambda aligner,text,language:([text],'space_lang'))
    monkeypatch.setattr(worker,'_align_batch',infer)
    torch=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False),__version__='injected')
    jobs=[dict(id=str(i),text='a',language='English',window_start_ms=i*1000,window_end_ms=(i+1)*1000) for i in range(4)]
    from twobyteasr.recognition.alignment_items import bind_jobs
    jobs=bind_jobs(jobs,dict(samples=64000,sha256='test'))
    policy=dict(sample_rate=16000,batch_size=4,passes=['word','char'],alignment_identity=profile('qwen_ultra_aligner'))
    out=tmp_path/'out.json'
    worker._infer_request(SimpleNamespace(timestamp_segment_time=80),dict(audio={'sha256':'test'}),
        np.zeros(64000,dtype=np.float32),jobs,policy,out,torch,np,fa,'cpu','float32',0)
    payload=json.loads(out.read_text('utf8'))
    assert [row['id'] for row in payload['results']]==['0','1','2','3']
    assert payload['oom_retries']==3 and max(calls)==4 and len(calls)==11
    assert all(row['status']=='aligned' for row in payload['results'])


def test_alignment_missing_posterior_is_missing_not_a_high_default():
    from twobyteasr.recognition.asr import aligner_tokens
    value=aligner_tokens({'results':[dict(id='S00',text='hello',segments=[
        dict(char_start=0,char_end=5,start_ms=100,end_ms=500,start_basis='model',end_basis='model')])]})[0]
    assert 'confidence' not in value and value['confidence_available'] is False


def test_benchmark_counts_missing_runs_and_matches_original_spans():
    from twobyteasr.acceptance.alignment_comparison import endpoint_stats,common_boundary,replacement_gate
    rows=[dict(reference={'start_ms':0},start_error_ms=100),dict(reference={'start_ms':0},start_error_ms=None)]
    stats=endpoint_stats(rows,'start')
    assert stats['expected']==2 and stats['missing_or_failed']==1
    assert stats['p95_all_cases_ms']=='unbounded_due_to_missing' and stats['over_250_or_missing_pct']==50
    sample=dict(text='one one',span=[4,7])
    row=dict(word_units=[dict(char_start=0,char_end=3,start_ms=10,end_ms=20,start_basis='model',end_basis='model'),
                         dict(char_start=4,char_end=7,start_ms=30,end_ms=50,start_basis='model',end_basis='model')])
    assert common_boundary(sample,row)==(30,50)
    assert not replacement_gate({'samples':[dict(language='Japanese',reference=None)]},{'runs':[]})['accepted']


def test_failed_window_preserves_existing_reliable_time_without_relabelling():
    from twobyteasr.recognition.cue_forced_alignment import attach_results,alignment_jobs
    cue=SimpleNamespace(text='hello',start=1.,end=2.,speaker='S00',
        forced_alignment=dict(model='old-official',text='hello',segments=[dict(start_ms=1100,end_ms=1800)]))
    _jobs,runs=alignment_jobs([cue],language='English')
    result=dict(receipt(),results=[dict(id='run-1',text='hello',language='English',
        status='unaligned',failure_reason='no_usable_measured_span',segments=[],stats={})])
    assert attach_results([cue],runs,result)==0
    assert cue.forced_alignment['model']=='old-official' and cue.forced_alignment['degraded']
    assert cue.forced_alignment['last_alignment_attempt']['model']==profile('qwen_ultra_aligner')['model']
    assert (cue.start,cue.end)==(1.,2.)


def test_retired_redirector_still_releases_owned_children():
    from twobyteasr.recognition.resident_aligner import ResidentAligner
    closed=[]
    job=SimpleNamespace(close=lambda **kwargs:closed.append(kwargs))
    session=ResidentAligner()
    session.process=SimpleNamespace(pid=123,poll=lambda:0,_request_job=job)
    session.close()
    assert closed==[{'timeout':3}] and session.process is None


def test_failed_tree_cleanup_keeps_process_owned():
    from twobyteasr.recognition.resident_aligner import ResidentAligner
    def blocked(**kwargs):raise TimeoutError('still releasing mapping')
    session=ResidentAligner()
    original=SimpleNamespace(pid=123,poll=lambda:0,_request_job=SimpleNamespace(close=blocked))
    session.process=original
    with pytest.raises(TimeoutError):session.close()
    assert session.process is original and session.loaded_signature is None


def test_realign_basis_changes_with_audio_edits_but_not_autosave(monkeypatch):
    from twobyteasr.studio.studio_realign import alignment_audio_basis
    from twobyteasr.playback import cue_audio_preview
    state=dict(request_id='random-1',project_revision='save-1',cue_id='1',cue_text='hello',
               cue_range_ms=[100,500],layers=[dict(source_path='unavailable-fixture.wav',playback_rate=1.)])
    def plan(*args):
        return SimpleNamespace(layers=state['layers'],diagnostic=lambda:copy.deepcopy(state))
    monkeypatch.setattr(cue_audio_preview,'plan_cue_preview',plan)
    before=alignment_audio_basis(object(),'1')
    state.update(request_id='random-2',project_revision='save-2')
    assert alignment_audio_basis(object(),'1')==before
    state['layers'][0]['playback_rate']=2.
    assert alignment_audio_basis(object(),'1')!=before


def test_scratch_retry_does_not_replace_original_cancellation(tmp_path,monkeypatch):
    import tempfile
    from twobyteasr.recognition.alignment_audio import alignment_scratch
    from twobyteasr.recognition.service import CancelledError
    target=tmp_path/'qwen_aligner_worker_owned';target.mkdir()
    (target/'audio.npy').write_bytes(b'owned')
    calls=[]
    class Temporary:
        name=str(target)
        def __init__(self,**kwargs):pass
        def cleanup(self):
            calls.append(1)
            if len(calls)==1:raise PermissionError('mapping release pending')
            (target/'audio.npy').unlink()
            target.rmdir()
    monkeypatch.setattr(tempfile,'TemporaryDirectory',Temporary)
    monkeypatch.setattr(tempfile,'gettempdir',lambda:str(tmp_path))
    with pytest.raises(CancelledError,match='original'):
        with alignment_scratch():raise CancelledError('original')
    assert len(calls)==2 and not target.exists()


def test_empty_initial_alignment_is_degraded_without_changing_transcript(monkeypatch):
    from twobyteasr.recognition import asr
    events=[];reviews=[]
    def worker(audio,jobs):
        return dict(receipt('qwen_aligner'),results=[dict(job,status='unaligned',segments=[]) for job in jobs])
    monkeypatch.setattr(asr,'run_qwen_aligner_worker',worker)
    monkeypatch.setattr(asr,'record_run_event',lambda name,**kw:events.append((name,kw)))
    monkeypatch.setattr(asr,'add_review_item',lambda *args,**kw:reviews.append((args,kw)))
    original=[dict(start=.1,end=.9,text=' Hello! ',speaker='S00')]
    before=copy.deepcopy(original)
    assert asr.transcribe_qwen_aligner_reference(np.zeros(16000,dtype=np.float32),original,language='English')==[]
    assert original==before and reviews
    assert any(name=='forced_alignment_degraded' for name,_ in events)


def test_cold_runtime_probe_is_cancellable_and_releases_its_owned_tree(monkeypatch):
    import subprocess
    from twobyteasr.recognition import alignment_backend as backend
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.recognition.service import CancellationToken,CancelledError
    from twobyteasr.system import processes
    token=CancellationToken();closed=[]
    def communicate(**kwargs):
        token.cancel()
        raise subprocess.TimeoutExpired('fixture',.1)
    process=SimpleNamespace(pid=123,returncode=None,communicate=communicate,
        _request_job=SimpleNamespace(close=lambda **kwargs:closed.append('closed')),
        wait=lambda **kwargs:0,poll=lambda:0)
    monkeypatch.setattr(processes,'popen_hidden_subprocess',lambda *args,**kwargs:process)
    context=RuntimeContext(cancellation_token=token)
    with activate_runtime_context(context):
        with pytest.raises(CancelledError):
            backend._execution_probe('fixture','stamp','cpu',None,context.job_id)
    assert closed==['closed']
