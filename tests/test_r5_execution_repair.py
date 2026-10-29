import json
import sys
import time

import pytest

from twobyteasr.providers.ai_providers import CLIProvider, GrokCLIProvider, AIProviderError
from twobyteasr.providers.provider_diagnostics import collect_search_evidence, redact_diagnostics
from twobyteasr.providers.task_execution_events import ExecutionObserver


def event(kind, **kw):
    return {'type':'stream_event','event':{'type':kind,**kw}}


def test_actual_grok_incremental_search_envelopes_and_split_arguments():
    state={}; events=[]; receipts=[]
    packets=[event('content_block_start',index=2,content_block={'type':'server_tool_use','id':'a','name':'web_search','input':{}}),
             event('content_block_delta',index=2,delta={'type':'input_json_delta','partial_json':'{"query":"我的'}),
             event('content_block_delta',index=2,delta={'type':'input_json_delta','partial_json':'世界 生物"}'}),
             event('content_block_stop',index=2),
             event('content_block_start',index=3,content_block={'type':'web_search_tool_result','tool_use_id':'a',
                 'content':[{'type':'web_search_result','url':'https://zh.minecraft.wiki/w/生物','title':'生物'}]})]
    for packet in packets:
        collect_search_evidence(packet,receipts)
        CLIProvider._consume_cli_stream_line(json.dumps(packet),state,lambda *e:events.append(e))
    collect_search_evidence(packets[-1],receipts)
    assert len(receipts)==1 and len(receipts[0]['urls'])==1
    assert ('tool_request','web_search') in events
    assert json.loads(next(e[1] for e in events if e[0]=='tool_call'))['arguments']['query']=='我的世界 生物'
    assert not state.get('final')


def test_observer_does_not_publish_body_or_private_thinking():
    rows=[]; obs=ExecutionObserver(rows.append,{'model':'grok-4.7'})
    obs.stream('thinking','private full reasoning')
    obs.stream('final','private complete document')
    obs.stream('tool_call','{"api_key":"test-secret","query":"公开词"}')
    wire=json.dumps(rows,ensure_ascii=False)
    assert 'private' not in wire and 'test-secret' not in wire
    assert '公开词' in wire
    assert rows[0]['request_id']==rows[-1]['request_id']
    assert rows[-1]['request_seq']>rows[0]['request_seq']


def test_redact_proxy_and_query_credentials():
    value=redact_diagnostics('https://name:password@example.org/api?token=abc&x=1 Authorization: Bearer secret-value {"access_token":"xyz"}')
    assert all(secret not in value for secret in ('password','abc','secret-value','xyz'))


def test_cli_first_event_timeout_and_early_tls_error(tmp_path):
    provider=GrokCLIProvider(executable=sys.executable,model='test')
    with pytest.raises(AIProviderError) as error:
        provider._run_cli_stream([sys.executable,'-c','import time;time.sleep(5)'],purpose='isolated fixture',timeout=3,
            first_response_timeout=.15,cwd=tmp_path)
    assert error.value.category=='first_response_timeout'
    started=time.monotonic()
    with pytest.raises(AIProviderError) as error:
        provider._run_cli_stream([sys.executable,'-u','-c',"import sys,time;print('CERTIFICATE_VERIFY_FAILED',file=sys.stderr,flush=True);time.sleep(5)"],
            purpose='isolated fixture',timeout=3,cwd=tmp_path)
    assert error.value.category=='tls_certificate'
    assert time.monotonic()-started < 2


def test_cli_activity_resets_idle_but_not_total_and_consumer_failure(tmp_path):
    provider=GrokCLIProvider(executable=sys.executable,model='test')
    script="import json,time\nfor i in range(8):\n print(json.dumps({'type':'stream_event','event':{'type':'content_block_delta','delta':{'text':'片'}}}),flush=True);time.sleep(.1)\nprint(json.dumps({'type':'result','result':'{}'}),flush=True)"
    assert provider._run_cli_stream([sys.executable,'-u','-c',script],purpose='isolated fixture',timeout=2,
        first_response_timeout=.4,idle_timeout=.3,cwd=tmp_path)=='{}'
    def fail(*_):raise ValueError('callback failed')
    with pytest.raises(AIProviderError) as error:
        provider._run_cli_stream([sys.executable,'-u','-c',script],purpose='isolated fixture',timeout=2,cwd=tmp_path,on_stream_event=fail)
    assert error.value.category=='stream_consumer_error'


def test_terminal_and_other_task_events_do_not_pollute_state():
    from twobyteasr.glossary.glossary_task_manager import GlossaryUpdateManager,GlossaryTaskState
    manager=GlossaryUpdateManager(object())
    task=GlossaryTaskState('a','game','full','service','model',time.time(),status='running')
    manager._tasks['a']=task
    manager._on_event('a',dict(seq=2,source='provider',payload='response',timestamp=10))
    manager._on_event('a',dict(seq=1,source='provider',payload='stale',timestamp=20))
    manager._on_event('b',dict(seq=3,source='provider',payload='other',timestamp=20))
    assert len(task.events)==1 and task.last_event_at==10
    task.status='failed'
    manager._on_progress('a','bad','late',0,0,0)
    manager._on_event('a',dict(seq=4,source='provider',payload='late'))
    assert task.stage=='' and len(task.events)==1


def test_fast_exit_consumer_failure_is_not_success(tmp_path):
    provider=GrokCLIProvider(executable=sys.executable,model='test')
    def fail(*_):raise ValueError('callback failed after process exit')
    with pytest.raises(AIProviderError) as error:
        provider._run_cli_stream([sys.executable,'-u','-c',"print('{\"type\":\"result\",\"result\":\"{}\"}')"],
            purpose='isolated fixture',timeout=2,cwd=tmp_path,on_stream_event=fail)
    assert error.value.category=='stream_consumer_error'


def test_trace_does_not_retain_private_event_tail():
    from twobyteasr.providers.provider_diagnostics import public_stream_text
    assert 'SECRET_REASONING' not in public_stream_text('{"delta":{"thinking":"SECRET_REASONING"}}\n{"thinking":"SECRET_REASONING')


def test_minecraft_catalogs_are_sources_not_names():
    from twobyteasr.glossary.minecraft_catalogs import known_catalogs,SCOPES
    from twobyteasr.glossary.glossary_build import _covers_seed_category
    sources=known_catalogs('我的世界')
    assert len(sources)==7 and not known_catalogs('异环')
    assert {_covers_seed_category(c['covers'])[0] for c in sources}=={k for k,_ in SCOPES}


def test_int32_positive_full_scale_does_not_wrap():
    import numpy as np
    from types import SimpleNamespace
    from twobyteasr.playback.audio_engine import _PcmRingDevice,AudioOutputSpec
    from PySide6.QtMultimedia import QAudioFormat
    spec=AudioOutputSpec(48000,2,QAudioFormat.SampleFormat.Int32,4,'s32le')
    owner=SimpleNamespace(_mix_spec=spec,_mix_ids=('a',),_mix_gains=np.ones(1,dtype=np.float32),_mix_previous=np.ones(1,dtype=np.float32))
    out=np.frombuffer(_PcmRingDevice._mix_output(owner,np.ones(2,dtype='<f4').tobytes()),dtype='<i4')
    assert out.tolist()==[2147483647,2147483647]


def test_six_channel_decoder_keeps_short_reads_on_complete_frames(monkeypatch):
    import io
    from pathlib import Path
    from types import SimpleNamespace
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QAudioFormat
    from twobyteasr.playback.audio_engine import _AudioEngineWorker,_PcmRingDevice,AudioOutputSpec
    app=QApplication.instance() or QApplication([])
    values=np.linspace(-.7,.7,4800*6,dtype='<f4')
    data=values.tobytes()
    class ShortPipe(io.BytesIO):
        def read(self,n=-1):return super().read(min(n,8171))
    process=SimpleNamespace(stdout=ShortPipe(data),stderr=io.BytesIO(),poll=lambda:0)
    monkeypatch.setattr('twobyteasr.system.processes.popen_hidden_subprocess',lambda *a,**k:process)
    worker=_AudioEngineWorker(Path('fixture-ffmpeg.exe'))
    worker._output_spec=AudioOutputSpec(48000,6,QAudioFormat.SampleFormat.Int16,2,'s16le')
    worker.device=_PcmRingDevice(sample_format=worker._output_spec.sample_format)
    worker._ensure_sink=lambda:True
    worker._emit=lambda *_:None
    worker._trace_decoder=lambda *a,**k:None
    worker._start_decoder('fixture.wav',0,2.)
    worker._feeder.join(3)
    assert not worker._feeder.is_alive() and not worker._decoder_error
    ring=worker.device;ring.publish_enabled=True
    out=ring.read(len(values)*2)
    assert out==(values*32767).astype('<i2').tobytes()
