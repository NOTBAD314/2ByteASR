"""Own JSON pipe, real actor read loop, both poll wait primitives; no player/UI."""
from collections import deque
import json
import sys
import threading
import time
from types import SimpleNamespace
import uuid

import pytest

from twobyteasr.playback.studio_mpv import _MpvCommandActor


@pytest.mark.skipif(sys.platform!='win32' or sys.version_info[:2]!=(3,10),reason='Windows CPython3.10 own pipe')
@pytest.mark.parametrize('mode',['sleep','highres_timer'])
def test_actor_reassembles_fragments_and_keeps_poll_primitive_identity(monkeypatch,mode):
    import _winapi
    import importlib.util
    from pathlib import Path
    support_name = 'windows_overlapped_pipe_support'
    if support_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(support_name, Path(__file__).with_name(support_name + '.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[support_name] = module
        spec.loader.exec_module(module)
    from windows_overlapped_pipe_support import WindowsOverlappedPipe,_WindowsAPI
    monkeypatch.setenv('TWOBYTEASR_MPV_POLL_WAIT',mode)
    name=r'\\.\pipe\2byteasr-actor-timer-test-'+uuid.uuid4().hex
    handle=_winapi.CreateNamedPipe(name,3|0x40000000,0,1,4096,4096,0,0)
    connected=_winapi.ConnectNamedPipe(handle,overlapped=True)
    stream=open(name,'r+b',buffering=0)  # Production poll transport stays synchronous.
    assert _winapi.WaitForSingleObject(connected.event,1000)==0
    assert connected.GetOverlappedResult(False)[1]==0
    api=_WindowsAPI();api.CreateFile=lambda *args:handle
    peer=WindowsOverlappedPipe(name,_api=api)
    actor=object.__new__(_MpvCommandActor)
    actor._init_request_metrics()
    actor.controller=SimpleNamespace(_request_id=0,running=True)
    actor._condition=threading.Condition();actor._requests=deque()
    actor._thread=threading.current_thread();actor._stopping=False
    actor._pipe=stream;actor._read_buffer=b'';actor._reconnect_attempts=0
    actor._command_error_count=0;actor._open_pipe=lambda timeout:None
    actor._remember_property=lambda *args,**kwargs:None
    events=[];actor._handle_event=events.append
    failures=[]
    def server():
        try:
            request=json.loads(peer.read_deadline(65536,time.monotonic()+1))
            time.sleep(.008)
            peer.write_deadline(b'{"event":"fixture"}\n',time.monotonic()+1)
            response=json.dumps({'request_id':request['request_id'],'error':'success','data':13}).encode()+b'\n'
            peer.write_deadline(response[:8],time.monotonic()+1)
            time.sleep(.008)
            peer.write_deadline(response[8:],time.monotonic()+1)
        except BaseException as error:failures.append(error)
    thread=threading.Thread(target=server);thread.start()
    try:
        result=actor.exchange(['get_property','fixture'],timeout=.5)
        thread.join(2)
        assert not thread.is_alive() and not failures
        assert result['data']==13 and events==[{'event':'fixture'}]
        receipt=result['_ipc_poll_receipt'];snapshot=actor.request_metrics()
        assert snapshot['ipc_read_transport']=='windows-peek-sync'
        assert receipt['attempts'][0]['request_id']==1
        if mode=='highres_timer':
            assert receipt['timer_poll_calls']>0 and receipt['timer_poll_wall_ms']>0
            assert receipt['calls']==0 and receipt['wall_ms']==0
            assert snapshot['poll_wait_last_observed']=='highres_timer_poll'
            assert snapshot['poll_timer_error'] is None
        else:
            assert receipt['calls']>0 and receipt['timer_poll_calls']==0
            assert snapshot['poll_wait_last_observed']=='time_sleep'
        assert actor._reconnect_attempts==0
    finally:
        actor.close();peer.close();thread.join(2)
