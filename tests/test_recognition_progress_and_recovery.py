import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_recovery_reuses_edited_project_without_duplicating(tmp_path):
    from twobyteasr.recognition.recognition_recovery import recover_report
    from twobyteasr.projects.studio_project import load_project, save_project
    srt=tmp_path/'captions.srt';srt.write_text('1\n00:00:01,000 --> 00:00:02,000\n真实字幕\n','utf8')
    report=tmp_path/'report.json';report.write_text(json.dumps({'media':{'path':str(tmp_path/'missing.mp4')},
        'result':{'outputs':{'srt':str(srt)}}}),'utf8')
    path=recover_report(report,recovery_root=tmp_path/'recovery')
    project=load_project(path);assert len(project.cues)==1
    project.cues[0].text='用户后续修改';save_project(project,path)
    saved=path.read_bytes()
    assert recover_report(report,recovery_root=tmp_path/'recovery')==path
    assert path.read_bytes()==saved and load_project(path).cues[0].text=='用户后续修改'


def test_incremental_ids_are_stable_and_sorted(monkeypatch):
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.recognition.asr_progress import PrimaryProgress
    events=[];monkeypatch.setattr('twobyteasr.recognition.cache.record_run_event',lambda kind,**kw:events.append((kind,kw)))
    context=RuntimeContext(job_id='fixed')
    with activate_runtime_context(context):
        progress=PrimaryProgress('source.flv',3)
        progress.complete(2,[dict(start=20,end=22,text='第三段')],force=True)
        progress.complete(0,[dict(start=0,end=2,text='第一段')],force=True)
        progress.complete(0,[dict(start=0,end=2,text='第一段修订')],force=True)
    assert [r['text'] for r in context.asr_provisional_cues]==['第一段修订','第三段']
    assert len({r['id'] for r in context.asr_provisional_cues})==2
    assert events[-1][1]['completed_batches']==2


def test_owned_api_cancel_terminates_requests_and_process_tree(tmp_path,monkeypatch):
    import numpy as np
    import psutil
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import subtitle_core
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context
    from twobyteasr.recognition.service import CancellationToken,CancelledError
    from twobyteasr.recognition.cache import run_event_observer
    arrived=threading.Event();release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            arrived.set();release.wait(20)
            try:self.send_response(200);self.end_headers();self.wfile.write(b'{"text":"late"}')
            except OSError:pass
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    endpoint=dict(provider='custom',protocol='openai_transcription',model='test',
        url=f'http://127.0.0.1:{server.server_port}/audio/transcriptions',api_key='test-only-dummy')
    monkeypatch.setattr('twobyteasr.providers.llm_config.qwen_asr_endpoint_from_settings',lambda _:endpoint)
    monkeypatch.setattr(asr,'build_qwen_asr_context',lambda *_:'')
    monkeypatch.setattr(asr,'CLOUD_BATCH_WORKERS',1)
    token=CancellationToken();context=RuntimeContext(cancellation_token=token)
    events=[];outcome={}
    def work():
        with activate_runtime_context(context),run_event_observer(lambda kind,payload:events.append((kind,payload))):
            try:outcome['value']=asr._transcribe_api_owned('local-test.wav',[
                dict(start=i,end=i+1,audio=(np.zeros(16000,dtype='float32'),16000)) for i in range(4)],publish_primary=True)
            except BaseException as exc:
                import traceback
                outcome['error']=exc;outcome['traceback']=traceback.format_exc()
    thread=threading.Thread(target=work)
    try:
        thread.start();assert arrived.wait(15),repr(outcome)
        parent=next(p['pid'] for k,p in events if k=='asr_worker_started')
        owned=[psutil.Process(parent),*psutil.Process(parent).children(recursive=True)]
        start=time.monotonic();token.cancel();thread.join(8)
        assert not thread.is_alive() and isinstance(outcome.get('error'),CancelledError),outcome
        assert time.monotonic()-start<8
        assert all(not p.is_running() for p in owned)
        assert not context.asr_provisional_cues
        assert any(k=='asr_worker_exited' and p['readers_stopped'] for k,p in events)
    finally:
        token.cancel();release.set();server.shutdown();server.server_close();thread.join(10)
