import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from twobyteasr.recognition.service import CancellationToken, RunOptions
from twobyteasr.recognition.task_journal import TaskJournal, read_record


def test_supervisor_survives_worker_exit_and_preserves_checkpoint(tmp_path,monkeypatch):
    from twobyteasr.recognition import queue_process
    from twobyteasr.recognition import task_journal
    root=tmp_path/'recognition-tasks'
    monkeypatch.setattr(task_journal,'task_root',lambda:root)
    script=("import json,sys,os;from twobyteasr.recognition.task_journal import TaskJournal;"
        "r=json.loads(sys.stdin.readline());j=TaskJournal(r['options']['job_id'],os.environ['FAULT_ROOT']);"
        "j.acquire();j.publish('asr:0',{'text':'completed'},{'pcm':'one'});os._exit(23)")
    monkeypatch.setenv('FAULT_ROOT',str(root))
    monkeypatch.setattr(queue_process,'_command',lambda:[sys.executable,'-c',script])
    with pytest.raises(RuntimeError,match='00000017'):
        queue_process.supervise(['media.wav'],RunOptions(job_id='fault'),CancellationToken(),lambda e:None,lambda *a:None)
    row=read_record(root/'fault'/'task.json')
    assert row['status']=='interrupted'
    assert TaskJournal('fault',root).load_artifact('asr:0',{'pcm':'one'})=={'text':'completed'}


def test_worker_launch_failure_does_not_leave_queued_task_forever(tmp_path,monkeypatch):
    from twobyteasr.recognition import queue_process,task_journal
    from twobyteasr.system import processes
    root=tmp_path/'recognition-tasks';monkeypatch.setattr(task_journal,'task_root',lambda:root)
    def denied(*a,**kw):raise OSError('injected spawn failure')
    monkeypatch.setattr(processes,'popen_hidden_subprocess',denied)
    with pytest.raises(OSError):
        queue_process.supervise(['input.wav'],RunOptions(job_id='launch'),CancellationToken(),lambda e:None,lambda *a:None)
    assert read_record(root/'launch/task.json')['status']=='failed'


def test_remote_acceptance_then_receipt_failure_never_posts_twice(tmp_path,monkeypatch):
    import numpy as np
    from twobyteasr.providers import mosi_asr as mosi
    from twobyteasr.providers.qwen31_asr import ASRProtocolError
    from tests.test_no_cuda_cloud_asr import Response,mosi_endpoint
    calls=[]
    class Client:
        def post(self,*args,**kwargs):
            calls.append(1)
            kwargs['data'].read()
            return Response({'task_id':'accepted-remote-id','status':'PENDING'})
    real=mosi._save
    def interrupted(path,payload):
        if path.name=='task.json' and payload.get('task_id'):
            raise OSError('injected failure before task-id receipt')
        real(path,payload)
    monkeypatch.setattr(mosi,'_save',interrupted)
    with pytest.raises(OSError):
        mosi.submit(np.zeros(1600,dtype=np.float32),mosi_endpoint(),client=Client(),
                    state_path=tmp_path/'task.json',state={})
    persisted=json.loads((tmp_path/'task.json').read_text(encoding='utf-8'))
    assert persisted['status']=='SUBMITTING' and persisted['client_request_id']
    with pytest.raises(ASRProtocolError) as failure:
        mosi._prepared_state(tmp_path,progress=lambda *a:None,restart_terminal=False)
    assert failure.value.category=='submission_uncertain'
    assert len(calls)==1


def test_firered_checkpoint_identity_and_admission(tmp_path):
    from twobyteasr.recognition.firered_checkpoints import batch_budget,save_row,read_row,VERSION
    gib=1024**3
    assert batch_budget(10*gib,10*gib)==4
    assert batch_budget(gib,10*gib)==1
    assert batch_budget(10*gib,gib)==1
    job=dict(audio_sha256='pcm-a',segment_id=12,duration=38.)
    row=dict(segment_id=12,text='测试',timestamp=[dict(text='测试',start=.2,end=.5)],
        evidence_version=VERSION,transcription_status='success',alignment_status='aligned',
        timestamp_source='ctc_forced_alignment',timestamp_reliability='measured')
    save_row(tmp_path,job,{'model':'one'},row)
    assert read_row(tmp_path,job,{'model':'one'})==row
    assert read_row(tmp_path,dict(job,audio_sha256='pcm-b'),{'model':'one'}) is None
    assert read_row(tmp_path,job,{'model':'two'}) is None


def test_chinese_admission_retains_global_dependencies():
    from twobyteasr.recognition.streaming_recognition import eligible
    from twobyteasr.providers.mosi_asr import MODEL
    context=SimpleNamespace(asr_endpoint_snapshot={'model':MODEL},requested_language='zh',
        recognition_purpose='final',enable_term_search=False,recognition_snapshot={},speaker_source='native',
        dialogue_coverage_mode='all_dialogue',expected_speakers=0)
    legacy=SimpleNamespace(PRIMARY_ASR_BACKEND='api',FIRERED_ASR_BACKEND='local',QWEN_ASR_BACKEND='off',
                           USE_QWEN_ASR_REFERENCE=False,PARALLEL_GPU_ASR=True)
    assert eligible(context,legacy,3600)[0]
    context.expected_speakers=2
    assert not eligible(context,legacy,3600)[0]
    context.expected_speakers=0
    legacy.USE_QWEN_ASR_REFERENCE=True;legacy.QWEN_ASR_BACKEND='local'
    assert not eligible(context,legacy,3600)[0]


def test_ready_acoustic_prefix_matches_full_overlap_ownership():
    from twobyteasr.recognition.asr_schema import normalize_firered_worker_result,flatten_segment_tokens
    jobs=[dict(segment_id=i+1,offset=i*36,duration=38) for i in range(3)]
    rows=[dict(segment_id=i+1,text='甲乙',timestamp=[dict(text='甲',start=1,end=2),dict(text='乙',start=36,end=38)]) for i in range(3)]
    prefix=flatten_segment_tokens(normalize_firered_worker_result({'results':rows[:2]},jobs))
    full=flatten_segment_tokens(normalize_firered_worker_result({'results':rows},jobs))
    assert prefix==[row for row in full if row['start']<72]
