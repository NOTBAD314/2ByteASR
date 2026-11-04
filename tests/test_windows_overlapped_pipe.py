"""Owned pipe lifecycle tests. Fake kernel first, real local Windows pipes next."""
from collections import deque
import gc
import sys
import threading
import time
import uuid

import pytest

import importlib.util
from pathlib import Path

_support_name = 'windows_overlapped_pipe_support'
if _support_name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_support_name, Path(__file__).with_name(_support_name + '.py'))
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_support_name] = _module
    _spec.loader.exec_module(_module)
transport = sys.modules[_support_name]


class Operation:
    def __init__(self, results, data=b'hello'):
        self.event=99
        self.results=deque(results)
        self.data=data
        self.cancelled=False
        self.kernel_pending=True
        self.result_wait_args=[]
    def cancel(self): self.cancelled=True  # Cancellation is deliberately NOT completion.
    def GetOverlappedResult(self,wait):
        self.result_wait_args.append(wait)
        assert wait is False, 'No unbounded completion wait is allowed'
        result=self.results.popleft() if len(self.results)>1 else self.results[0]
        if isinstance(result,BaseException): raise result
        if result[1]!=transport.INCOMPLETE:self.kernel_pending=False
        return result
    def getbuffer(self):
        assert not self.kernel_pending
        return self.data


class API:
    def __init__(self,operation,outcomes=(1,),initial=transport.PENDING):
        self.operation=operation;self.outcomes=deque(outcomes);self.initial=initial
        self.closed=[];self.signals=[];self.waits=[];self.operations=[]
    def CreateFile(self,*args):return 10
    def create_stop_event(self):return 20
    def signal_stop(self,event):self.signals.append(event)
    def CloseHandle(self,handle):
        assert (not self.operation.kernel_pending or getattr(self,'pinned',False)), 'Handle freed before pending lease was retained'
        assert handle!=self.operation.event, 'The OVERLAPPED owns its I/O event'
        self.closed.append(handle)
    def ReadFile(self,handle,size,*,overlapped):
        assert overlapped
        self.operations.append(('read',size));return self.operation,self.initial
    def WriteFile(self,handle,value,*,overlapped):
        assert overlapped
        self.operations.append(('write',bytes(value)));return self.operation,self.initial
    def WaitForMultipleObjects(self,handles,wait_all,milliseconds):
        assert not wait_all and milliseconds<0xffffffff
        self.waits.append((list(handles),milliseconds))
        value=self.outcomes.popleft()
        if isinstance(value,BaseException):raise value
        return value
    def PeekNamedPipe(self,handle):return (0,0)


def test_immediate_completion_is_confirmed_before_exposing_read_buffer():
    operation=Operation([(5,0)])
    api=API(operation,initial=0)
    pipe=transport.WindowsOverlappedPipe('owned',_api=api)
    assert pipe.read_deadline(8,time.monotonic()+1)==b'hello'
    assert operation.result_wait_args==[False] and api.waits==[]
    pipe.close();pipe.close()
    assert api.closed==[10,20]


@pytest.mark.parametrize('kind',['read','write'])
def test_pending_io_uses_its_event_and_separate_stop_event(kind):
    operation=Operation([(5,0)])
    api=API(operation)
    pipe=transport.WindowsOverlappedPipe('owned',_api=api)
    observed=[]
    if kind=='read':assert pipe.read_deadline(8,time.monotonic()+1,lambda *r:observed.append(r))==b'hello'
    else:assert pipe.write_deadline(b'hello',time.monotonic()+1,lambda *r:observed.append(r))==5
    assert api.waits[0][0]==[20,99]
    assert observed[0][0]==kind
    assert not operation.cancelled
    pipe.close()


@pytest.mark.parametrize('outcome,exception',[(0,transport.PipeCancelled),(258,transport.PipeDeadline)])
def test_cancel_must_confirm_completion_before_retirement(outcome,exception):
    operation=Operation([(0,996),(0,995)])
    api=API(operation,[outcome,0])
    pipe=transport.WindowsOverlappedPipe('owned',_api=api)
    with pytest.raises(exception):pipe.read_deadline(8,time.monotonic()+1)
    assert operation.cancelled and operation.result_wait_args==[False,False]
    assert api.waits[-1][0]==[99]
    assert pipe.snapshot()['cleanup_completed']==1
    pipe.close()
    assert api.closed==[10,20]


def test_cancel_racing_success_retires_safely_but_does_not_deliver_after_stop():
    operation=Operation([(5,0)])
    api=API(operation,[0])
    pipe=transport.WindowsOverlappedPipe('owned',_api=api)
    with pytest.raises(transport.PipeCancelled):pipe.read_deadline(8,time.monotonic()+1)
    assert operation.cancelled and len(api.waits)==1
    pipe.close()


def test_unconfirmed_cancel_is_retained_and_never_reused(monkeypatch):
    operation=Operation([(0,996)])
    api=API(operation,[258,258])
    retained=[]
    def pin(bundle):retained.append(bundle);api.pinned=True
    monkeypatch.setattr(transport,'_pin_unconfirmed',pin)
    pipe=transport.WindowsOverlappedPipe('owned',_api=api,cleanup_timeout=.01)
    with pytest.raises(transport.PipeCompletionUnconfirmed):pipe.read_deadline(8,time.monotonic()+1)
    assert len(retained)==1 and retained[0][0] is operation
    assert operation.kernel_pending and operation.cancelled
    assert pipe.snapshot()['quarantined'] and pipe.snapshot()['pending']
    assert not pipe.snapshot()['handle_open'] and api.closed==[10,20]
    pipe.close()
    with pytest.raises(transport.PipeCancelled):pipe.read_deadline(8,time.monotonic()+1)
    assert len(api.operations)==1 and api.closed==[10,20]


def test_wait_exception_still_cancels_and_confirms_before_release():
    operation=Operation([(0,995)])
    api=API(operation,[OSError('wait failed')])
    pipe=transport.WindowsOverlappedPipe('owned',_api=api)
    with pytest.raises(OSError,match='wait failed'):pipe.read_deadline(8,time.monotonic()+1)
    assert operation.cancelled and not operation.kernel_pending
    pipe.close()


def test_already_expired_deadline_does_not_issue_any_io():
    operation=Operation([(5,0)]);operation.kernel_pending=False
    api=API(operation)
    pipe=transport.WindowsOverlappedPipe('owned',_api=api)
    with pytest.raises(transport.PipeDeadline):pipe.write_deadline(b'hello',time.monotonic()-1)
    assert api.operations==[]
    pipe.close()


def test_observer_failure_cannot_break_native_completion():
    operation=Operation([(5,0)])
    api=API(operation)
    pipe=transport.WindowsOverlappedPipe('owned',_api=api)
    def broken(*args):raise RuntimeError('observer')
    assert pipe.read_deadline(8,time.monotonic()+1,broken)==b'hello'
    pipe.close()


WINDOWS=sys.platform=='win32' and sys.version_info[:2]==(3,10)


def owned_pair():
    import _winapi
    name=r'\\.\pipe\2byteasr-overlapped-test-'+uuid.uuid4().hex
    server=_winapi.CreateNamedPipe(name,3|0x40000000,0,1,4096,4096,0,0)
    connection=_winapi.ConnectNamedPipe(server,overlapped=True)
    client=transport.WindowsOverlappedPipe(name)
    assert _winapi.WaitForSingleObject(connection.event,1000)==0
    assert connection.GetOverlappedResult(False)[1]==0
    api=transport._WindowsAPI()
    api.CreateFile=lambda *args:server
    peer=transport.WindowsOverlappedPipe(name,_api=api)
    return client,peer


@pytest.mark.skipif(not WINDOWS,reason='Windows CPython3.10 primitive')
def test_real_owned_pipe_fragmented_response_and_handle_retirement():
    client,server=owned_pair()
    try:
        assert client.write_deadline(b'command\n',time.monotonic()+1)==8
        assert server.read_deadline(100,time.monotonic()+1)==b'command\n'
        for fragment in (b'{"data":',b'123}\n'):
            assert server.write_deadline(fragment,time.monotonic()+1)==len(fragment)
            assert client.read_deadline(100,time.monotonic()+1)==fragment
        assert client.snapshot()['pending'] is False
    finally:client.close();server.close()
    assert not client.snapshot()['handle_open']


@pytest.mark.skipif(not WINDOWS,reason='Windows CPython3.10 primitive')
def test_real_timeout_cancels_pending_read_and_can_close_without_leak():
    import psutil
    before=psutil.Process().num_handles()
    for _ in range(6):
        client,server=owned_pair()
        try:
            with pytest.raises(transport.PipeDeadline):
                client.read_deadline(65536,time.monotonic()+.02)
            assert client.snapshot()['cleanup_completed']==1
            assert not client.snapshot()['quarantined']
        finally:client.close();server.close()
    del client,server
    gc.collect()
    assert psutil.Process().num_handles()<=before+2


@pytest.mark.skipif(not WINDOWS,reason='Windows CPython3.10 primitive')
def test_real_close_wakes_actor_owned_read_without_closing_waited_event_early():
    client,server=owned_pair();started=threading.Event();failures=[]
    native_read=client._api.ReadFile
    def observed_read(*args,**kwargs):
        result=native_read(*args,**kwargs);started.set();return result
    client._api.ReadFile=observed_read
    def reader():
        try:client.read_deadline(65536,time.monotonic()+5)
        except BaseException as error:failures.append(error)
    thread=threading.Thread(target=reader)
    thread.start()
    try:
        assert started.wait(1)
        began=time.perf_counter();client.close()
        assert time.perf_counter()-began<.1
        thread.join(2)
        assert not thread.is_alive()
        assert len(failures)==1 and isinstance(failures[0],transport.PipeCancelled)
        assert client.snapshot()['cleanup_completed']==1 and not client.snapshot()['handle_open']
    finally:
        client.close();server.close();thread.join(2)


@pytest.mark.skipif(not WINDOWS,reason='Windows CPython3.10 primitive')
def test_real_pending_write_timeout_retains_buffer_until_cancel_completes():
    client,server=owned_pair()
    try:
        with pytest.raises(transport.PipeDeadline):
            client.write_deadline(b'x'*transport.MAX_WRITE_BYTES,time.monotonic()+.02)
        assert client.snapshot()['cleanup_completed']==1
        assert not client.snapshot()['quarantined']
    finally:client.close();server.close()


@pytest.mark.skipif(not WINDOWS,reason='Windows CPython3.10 primitive')
def test_real_peer_disconnect_is_terminal_and_does_not_keep_pending_buffers():
    client,server=owned_pair()
    server.close()
    try:
        with pytest.raises(OSError):client.read_deadline(100,time.monotonic()+1)
        assert not client.snapshot()['pending']
    finally:client.close()


@pytest.mark.skipif(not WINDOWS,reason='Windows CPython3.10 primitive')
def test_real_eight_endpoint_bound_and_release():
    pairs=[]
    try:
        for _ in range(transport.MAX_ENDPOINTS):pairs.append(owned_pair())
        with pytest.raises(OSError,match='endpoint limit'):
            transport.WindowsOverlappedPipe(r'\\.\pipe\must-not-open')
    finally:
        for client,server in pairs:client.close();server.close()
    client,server=owned_pair();client.close();server.close()


@pytest.mark.skipif(not WINDOWS,reason='Windows CPython3.10 primitive')
def test_unconfirmed_real_io_disconnects_peer_and_survives_python_global_teardown():
    # Isolate the intentional process-lifetime retention and disabled flag.
    import subprocess
    script=r'''
import _winapi,gc,json,time,uuid,weakref
import windows_overlapped_pipe_support as t
name=r"\\.\pipe\2byteasr-quarantine-test-"+uuid.uuid4().hex
server=_winapi.CreateNamedPipe(name,3|0x40000000,0,1,4096,4096,0,0)
connect=_winapi.ConnectNamedPipe(server,overlapped=True)
client=t.WindowsOverlappedPipe(name,cleanup_timeout=.01)
assert _winapi.WaitForSingleObject(connect.event,1000)==0
assert connect.GetOverlappedResult(False)[1]==0
native=client._api.ReadFile
held=[]
class UnconfirmedCancel:
    def __init__(self,operation):self.operation=operation;self.event=operation.event
    def cancel(self):pass
    def GetOverlappedResult(self,wait):return self.operation.GetOverlappedResult(wait)
    def getbuffer(self):return self.operation.getbuffer()
def pending(*a,**kw):
    operation,error=native(*a,**kw);wrapper=UnconfirmedCancel(operation)
    held.append(weakref.ref(wrapper));return wrapper,error
client._api.ReadFile=pending
try:client.read_deadline(65536,time.monotonic()+.01)
except t.PipeCompletionUnconfirmed:pass
else:raise AssertionError('fault injection did not quarantine')
assert client.snapshot()['quarantined'] and not client.snapshot()['handle_open']
try:_winapi.WriteFile(server,b'no observer remains',overlapped=False)
except OSError:pass
else:raise AssertionError('peer connection was not disconnected')
try:t.WindowsOverlappedPipe(name)
except OSError as error:assert 'disabled' in str(error)
else:raise AssertionError('new experimental endpoint was allowed')
t._quarantined.clear();del client;gc.collect()
assert held[0]() is not None, 'module/global teardown released pending wrapper'
_winapi.CloseHandle(server)
print(json.dumps({'quarantine_disconnected':True,'retained_after_global_clear':True,'new_endpoint_rejected':True}))
'''
    from pathlib import Path
    result=subprocess.run([sys.executable,'-B','-X','utf8','-c',script],cwd=Path(__file__).resolve().parent,capture_output=True,text=True,
        timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    assert 'retained_after_global_clear' in result.stdout
    assert 'still in flight while destroying' not in result.stderr
