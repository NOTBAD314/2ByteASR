"""Engineering integrity tests; these do not assert acoustic accuracy."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import moss_firered_pipeline as pipeline
import moss_worker as worker


def legacy():
    return SimpleNamespace(AUDIO_SAMPLE_RATE=16000, MOSS_PARALLEL_WORKERS=2,
        MOSS_PARALLEL_MIN_VRAM_GB=0, record_run_event=lambda *a, **k: None,
        add_review_item=lambda *a, **k: None)


def payload(audio, rows):
    return {"inference_mode": worker.INFERENCE_MODE, "cache_version": worker.CACHE_VERSION,
        "chunks": [{"offset": 0, "duration": len(audio)/16000, "segments": rows}],
        "execution": {"sample_count": len(audio), "sample_rate": 16000,
            "task_audio_fingerprint": worker.audio_fingerprint(audio, 16000),
            "complete": True, "worker_count": 1, "generation_attempts": 1,
            "application_chunk_count": 1}}


@pytest.mark.parametrize("count", [16000, 180*16000+1, 3572736, 400*16000])
def test_scheduler_transports_every_ordered_sample_once(tmp_path, monkeypatch, count):
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(pipeline, "_script_paths", lambda _: {"moss_python": "python", "moss_worker": "moss_worker.py"})
    monkeypatch.setattr(pipeline, "_merge_moss_chunks", lambda *a, **k: pytest.fail("cross-context merger called"))
    # Both ends differ; a first-block-only implementation cannot satisfy this.
    audio=np.arange(count, dtype=np.float32) / max(1,count)
    calls=[]
    def execute(command, *_a, **_k):
        actual=np.load(command[command.index("--audio")+1])
        np.testing.assert_array_equal(actual,audio)
        assert command[command.index("--task-audio-fingerprint")+1]==worker.audio_fingerprint(audio,16000)
        calls.append(command)
        rows=[dict(start=0,end=.5,text="开始",speaker="S04"),
              dict(start=len(audio)/16000-.5,end=len(audio)/16000,text="尾部",speaker="S04")]
        Path(command[command.index("--output")+1]).write_text(json.dumps(payload(audio,rows)),"utf8")
        return 0,["real transport fixture; no model inference"]
    monkeypatch.setattr(pipeline,"_run_streaming_worker",execute)
    result=pipeline.transcribe_moss_global("uncut-source.mp4",audio,legacy(),{"cache_dir":str(tmp_path)})
    assert len(calls)==1
    assert result["segments"][-1]["end"]==count/16000
    assert result["metadata"]["raw_speaker_to_internal_speaker_id"]=={"S04":"S04"}


@pytest.mark.parametrize("speakers", [("S04",),("S03","S01"),("S04","S02","S04")])
def test_native_labels_and_simultaneous_rows_survive(speakers):
    audio=np.zeros(160000,np.float32)
    rows=[dict(start=1,end=3,text=f"原文{i}",speaker=sp) for i,sp in enumerate(speakers)]
    result=pipeline._normalize_moss_full_context(payload(audio,rows),audio,legacy())
    assert result["segments"]==rows


def test_old_chunks_and_altered_task_audio_rejected():
    audio=np.zeros(16000,np.float32)
    raw=payload(audio,[dict(start=0,end=.5,text="原文",speaker="S01")])
    for mutate in (lambda p:p.update(inference_mode="chunked"),
                   lambda p:p["chunks"].append(copy.deepcopy(p["chunks"][0])),
                   lambda p:p["execution"].update(sample_count=1),
                   lambda p:p["chunks"][0].update(offset=160)):
        value=copy.deepcopy(raw); mutate(value)
        with pytest.raises(RuntimeError):pipeline._normalize_moss_full_context(value,audio,legacy())
    raw['execution']['complete']=False
    with pytest.raises(ValueError):pipeline._decode_moss_full_context_cache(raw,audio,legacy())


def test_old_parallel_settings_cannot_activate_independent_requests(tmp_path):
    assert pipeline._moss_parallel_worker_count([{},{}],legacy(),100,100)==1
    with pytest.raises(ValueError):
        pipeline._run_moss_manifest_jobs([{"offset":0},{"offset":160}],str(tmp_path),{},legacy(),"test",force_workers=2)


def test_budget_uses_real_context_and_output_limit_is_incomplete():
    assert worker.generation_budget(223.296,3200,131072)==(5360,5360)
    assert worker.generation_budget(1000,13000,16000)==(2968,24000)
    with pytest.raises(ValueError):worker.generation_budget(223.296,130000,131072)
    assert worker.ending_assessment(5360,5360,151645,151645)==("token_limit",False)
    assert worker.ending_assessment(4000,5360,151645,151645)==("eos",True)
    assert worker.ending_assessment(4000,5360,99,151645)==("unexpected_stop",False)


def test_cache_names_do_not_read_or_replace_old_moss(tmp_path):
    from twobyteasr.recognition.cache import _stage_cache_path,cache_stage_signature
    old=tmp_path/'moss.json';old.write_text('legacy independent blocks','utf8')
    new=Path(_stage_cache_path('moss',{'cache_dir':str(tmp_path)},'new'))
    assert new!=old and not new.exists()
    assert old.read_text('utf8')=='legacy independent blocks'
    assert cache_stage_signature('moss',{'inference_mode':'full_context'})!=cache_stage_signature('moss',{'inference_mode':'chunked'})


def test_cancel_before_launch_does_not_start_worker(tmp_path,monkeypatch):
    from twobyteasr.recognition.service import CancellationToken,CancelledError
    import torch
    token=CancellationToken();token.cancel()
    monkeypatch.setattr(pipeline,'_CANCELLATION_TOKEN',token)
    monkeypatch.setattr(torch.cuda,'is_available',lambda:True)
    monkeypatch.setattr(pipeline,'_run_streaming_worker',lambda *a,**k:pytest.fail('cancelled task launched'))
    with pytest.raises(CancelledError):pipeline.transcribe_moss_global('x',np.zeros(16000,np.float32),legacy(),{'cache_dir':str(tmp_path)})


def test_oom_retry_keeps_single_context_and_bounds_calls(monkeypatch):
    import torch
    import sys
    # Load the official utility without importing its Transformers5 model package
    # into the distinct GUI/test environment (Transformers4).
    import importlib.util
    utility=Path(__file__).resolve().parents[1]/'third_party/MOSS-Transcribe-Diarize/moss_transcribe_diarize/inference_utils.py'
    spec=importlib.util.spec_from_file_location('moss_transcribe_diarize.inference_utils',utility)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules,'moss_transcribe_diarize.inference_utils',module)
    class Inputs(dict):
        def to(self,device):return self
    inputs=Inputs(input_ids=torch.tensor([[1,2]]),attention_mask=torch.tensor([[1,1]]),
                  input_features=torch.zeros((8,2,2)),audio_feature_lengths=torch.ones(8,dtype=torch.long),
                  audio_chunk_mapping=torch.zeros(8,dtype=torch.long))
    processor=SimpleNamespace(feature_extractor=SimpleNamespace(sampling_rate=16000),
        apply_chat_template=lambda *a,**k:'prompt',tokenizer=SimpleNamespace(decode=lambda *a,**k:'[0][S04]原文[1]'))
    class Processor:
        feature_extractor=processor.feature_extractor
        tokenizer=processor.tokenizer
        apply_chat_template=staticmethod(processor.apply_chat_template)
        def __call__(self,**kw):
            assert len(kw['audio'][0])==3572736
            return inputs
    calls=[]
    def generate(**kw):
        calls.append(kw)
        if len(calls)==1:raise torch.cuda.OutOfMemoryError('fixture OOM')
        return torch.tensor([[1,2,99,151645]])
    model=SimpleNamespace(config=SimpleNamespace(text_config=SimpleNamespace(max_position_embeddings=131072)),
        generation_config=SimpleNamespace(eos_token_id=151645),generate=generate)
    state={'batch_size':2}
    monkeypatch.setattr(worker,'install_encoder_batching',lambda *a:state)
    receipt={'generation_attempts':0,'retries':[]}
    worker.generate_full_context(model,Processor(),np.zeros(3572736,np.float32),[],torch.device('cpu'),torch.float16,worker.ExecutionProgress(),receipt)
    assert len(calls)==2 and receipt['generation_attempts']==2 and state['batch_size']==1
    assert calls[0]['input_ids'] is calls[1]['input_ids'] and calls[0]['audio_chunk_mapping'] is calls[1]['audio_chunk_mapping']
    assert receipt['end_reason']=='eos'
    calls.clear()
    model.generate=lambda **kw:(_ for _ in ()).throw(torch.cuda.OutOfMemoryError('persistent'))
    receipt={'generation_attempts':0,'retries':[]}
    with pytest.raises(torch.cuda.OutOfMemoryError):
        worker.generate_full_context(model,Processor(),np.zeros(3572736,np.float32),[],torch.device('cpu'),torch.float16,worker.ExecutionProgress(),receipt)
    assert receipt['generation_attempts']==2


def test_real_child_cancellation_stops_late_write(tmp_path,monkeypatch):
    import sys
    import time
    from twobyteasr.recognition import cache
    marker=tmp_path/'late-result.txt'
    started=time.monotonic()
    monkeypatch.setattr(pipeline,'_cancel_requested',lambda: time.monotonic()-started>1)
    events=[]
    monkeypatch.setattr(cache,'record_run_event',lambda kind,**p:events.append((kind,p)))
    code='import time;from pathlib import Path;print("MOSS_EVENT {\\"phase\\":\\"generation\\",\\"generated_tokens\\":1}",flush=True);time.sleep(10);Path('+repr(str(marker))+').write_text("late")'
    with pytest.raises(KeyboardInterrupt):pipeline._run_streaming_worker([sys.executable,'-c',code],30)
    assert not marker.exists()
    exited=[p for k,p in events if k=='asr_worker_exited']
    assert len(exited)==1 and exited[0]['returncode'] is not None and exited[0]['readers_stopped']


def test_independent_evidence_signature_kept_derived_batches_versioned(monkeypatch):
    from twobyteasr.recognition import cache
    captured=[]
    monkeypatch.setattr(cache,'stable_digest',lambda value:captured.append(value) or 'digest')
    for stage in ('audio','firered','qwen','moss','firered_primary','firered_llm','grouped_local','final_timing'):
        cache.cache_stage_signature(stage)
        base=captured[-1]
        assert ('primary_context_contract' in base)==(stage in {'firered_primary','firered_llm','grouped_local','final_timing'})


def test_cancelled_report_keeps_actual_counts_and_rejects_old_job(monkeypatch):
    from twobyteasr.recognition import reporting
    report={'job_id':'current','events':[]}
    monkeypatch.setattr(reporting,'_active_report',report)
    reporting.record_media_event('moss_full_context_preparing',job_id='current',inference_mode='full_context')
    reporting.record_media_event('asr_worker_started',job_id='current',backend='moss',pid=123)
    reporting.record_media_event('asr_worker_progress',job_id='current',backend='moss',phase='generation',
        application_chunk_count=1,generation_attempt=1,generated_tokens=100)
    reporting.record_media_event('asr_worker_exited',job_id='current',backend='moss',returncode=1)
    execution=copy.deepcopy(report['moss_execution'])
    assert (execution['application_chunk_count'],execution['worker_count'],execution['generation_attempts'])==(1,1,1)
    assert execution['failure_stage']=='generation' and not execution['complete']
    reporting.record_media_event('moss_full_context_result',job_id='old',complete=True,worker_count=99)
    assert report['moss_execution']==execution


def test_cached_receipt_cannot_claim_source_pid_tokens_or_elapsed_time():
    source={'worker_pids':[123], 'worker_count':1, 'generation_attempts':2,
        'application_chunk_count':1,'elapsed_seconds':120,'generated_tokens':3197,
        'input_tokens':2990,'retries':[{'reason':'cuda_oom'}], 'complete':True}
    saved=copy.deepcopy(source)
    receipt=pipeline._moss_cache_reuse_receipt(source)
    assert receipt['cache_hit'] and receipt['worker_pids']==[]
    assert (receipt['worker_count'],receipt['generation_attempts'],receipt['application_chunk_count'])==(0,0,0)
    assert receipt['input_tokens'] is None and receipt['generated_tokens'] is None
    assert receipt['elapsed_seconds']==0 and receipt['retries']==[]
    assert receipt['source_execution']==saved and source==saved
