"""Opt-in, actor-owned Windows named-pipe I/O with bounded cancellation.

Uses CPython's _winapi.Overlapped to own OVERLAPPED/event/read/write buffers.
cancel() alone is NOT completion in Python 3.10: GetOverlappedResult(False)
must confirm completion before normal retirement. Unconfirmed operations are
pinned for process lifetime before disconnecting the file; their buffers and
OVERLAPPED events are never released or reused by this process.
No reader thread, polling loop, Qt object or playback clock lives here.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
import math
import sys
import threading
import time


INCOMPLETE = 996
PENDING = 997
ABORTED = 995
MORE_DATA = 234
WAIT_TIMEOUT = 258
MAX_ENDPOINTS = 8
MAX_WRITE_BYTES = 1024*1024
_registry_lock = threading.Lock()
_endpoints = 0
_disabled = False
_quarantined = []


class PipeCancelled(OSError):
    pass


class PipeDeadline(TimeoutError):
    pass


class PipeCompletionUnconfirmed(RuntimeError):
    pass


def _reserve_endpoint():
    global _endpoints
    with _registry_lock:
        if _disabled or _endpoints >= MAX_ENDPOINTS:
            raise OSError('overlapped experiment unavailable: disabled or endpoint limit reached')
        _endpoints += 1


def _release_endpoint():
    global _endpoints
    with _registry_lock:
        _endpoints -= 1


def _pin_unconfirmed(bundle):
    """Fail closed if a local kernel operation cannot confirm cancellation.

    At most MAX_ENDPOINTS leases can exist, and the first failure prevents new
    experimental endpoints. A deliberately unreleased CPython reference keeps
    the OVERLAPPED and its buffers alive even during module teardown. The OS
    reclaims these process-owned resources at process exit. Merely keeping a
    Python global would be unsafe because interpreter shutdown clears globals.
    This exceptional bounded leak is never treated as successful cleanup.
    """
    global _disabled
    with _registry_lock:
        _disabled = True
        retain = ctypes.pythonapi.Py_IncRef
        retain.argtypes = [ctypes.py_object]
        retain.restype = None
        retain(bundle)
        _quarantined.append(bundle)


class _WindowsAPI:
    def __init__(self):
        if sys.platform != 'win32' or sys.version_info[:2] != (3, 10):
            raise OSError('overlapped experiment is validated only for Windows CPython 3.10')
        import _winapi
        self.winapi = _winapi
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR]
        self.kernel.CreateEventW.restype = W.HANDLE
        self.kernel.SetEvent.argtypes = [W.HANDLE]
        self.kernel.SetEvent.restype = W.BOOL

    def __getattr__(self,name):
        return getattr(self.winapi,name)

    def create_stop_event(self):
        handle = self.kernel.CreateEventW(None,True,False,None)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)

    def signal_stop(self,handle):
        if not self.kernel.SetEvent(handle): raise ctypes.WinError(ctypes.get_last_error())


class WindowsOverlappedPipe:
    transport_name = 'windows-overlapped-experiment-v1'

    def __init__(self,path,*,_api=None,cleanup_timeout=1.):
        self._api = _api or _WindowsAPI()
        self._registered = _api is None
        self._lock = threading.RLock()
        self._owner = None
        self._active = None
        self._handle = self._stop = None
        self._closing = self._quarantined = False
        self._cleanup_timeout = min(1.,max(.01,float(cleanup_timeout)))
        self._counts = dict(reads=0,writes=0,cancel_requests=0,cleanup_completed=0)
        if self._registered: _reserve_endpoint()
        try:
            self._handle = self._api.CreateFile(str(path),0x80000000|0x40000000,
                0,0,3,0x40000000,0)  # GENERIC_READ|WRITE, OPEN_EXISTING, OVERLAPPED
            self._stop = self._api.create_stop_event()
        except BaseException:
            self._closing = True
            self._retire_handles()
            raise

    def snapshot(self):
        with self._lock:
            return dict(transport=self.transport_name,closing=self._closing,
                pending=self._active is not None or self._quarantined,quarantined=self._quarantined,
                handle_open=self._handle is not None,**self._counts)

    def close(self):
        # May be called by GUI shutdown. The actor retains all handles until
        # its pending wait has returned and the cancellation has completed.
        with self._lock:
            if self._closing: return
            self._closing = True
            if self._stop is not None: self._api.signal_stop(self._stop)
            if self._active is None: self._retire_handles()

    def _retire_handles(self):
        if self._active is not None or self._quarantined: return
        handle,stop = self._handle,self._stop
        self._handle = self._stop = None
        try:
            if handle is not None: self._api.CloseHandle(handle)
        finally:
            try:
                if stop is not None: self._api.CloseHandle(stop)
            finally:
                if self._registered:
                    self._registered=False
                    _release_endpoint()

    def _check_owner(self):
        if self._closing or self._handle is None:
            raise PipeCancelled('named-pipe transport is closing')
        thread=threading.get_ident()
        if self._owner is None: self._owner=thread
        if self._owner != thread: raise RuntimeError('named-pipe I/O must stay on its actor thread')
        if self._active is not None: raise RuntimeError('another named-pipe operation is pending')

    @staticmethod
    def _observe(observer,kind,started,requested_ms,result):
        if observer is not None:
            try: observer(kind,started,(time.perf_counter()-started)*1000,requested_ms,result)
            except Exception: pass  # Diagnostics cannot invalidate native buffer ownership.

    def _wait(self,handles,milliseconds,observer,kind):
        started=time.perf_counter()
        result=None
        try:
            result=self._api.WaitForMultipleObjects(handles,False,milliseconds)
            return result
        finally:
            self._observe(observer,kind,started,milliseconds,result)

    @staticmethod
    def _result(operation):
        try:
            return operation.GetOverlappedResult(False)
        except OSError as error:
            # These terminal pipe statuses are also documented completions.
            if getattr(error,'winerror',None) in {ABORTED,109,232,233}:
                return 0,error.winerror
            raise

    def _cancel_and_confirm(self,operation,observer):
        self._counts['cancel_requests']+=1
        try: operation.cancel()
        except OSError: pass  # A racing completion can still be confirmed below.
        deadline=time.monotonic()+self._cleanup_timeout
        try:
            count,error=self._result(operation)
            if error==INCOMPLETE:
                remaining=max(0,math.ceil((deadline-time.monotonic())*1000))
                self._wait([operation.event],remaining,observer,'cancel_cleanup')
                count,error=self._result(operation)
            if error!=INCOMPLETE:
                self._counts['cleanup_completed']+=1
                return
        except OSError:
            pass
        # Never call GetOverlappedResult(True), release the wrapper, close its
        # event or reuse this file when completion is still unconfirmed.
        with self._lock:
            self._closing=self._quarantined=True
            bundle=(operation,self._handle,self._stop,self._api)
            _pin_unconfirmed(bundle)
            self._active=None
            # Disconnect the observer so the peer cannot accumulate an
            # unread stream. Closing the file may cancel the native request,
            # but is NOT proof that its OVERLAPPED/buffer is now releasable.
            # Those are already pinned above; never query the old handle.
            handle,stop=self._handle,self._stop
            self._api.CloseHandle(handle)
            self._handle=None
            self._api.CloseHandle(stop)  # Our cancellation event has no waiter now.
            self._stop=None
        raise PipeCompletionUnconfirmed('cancelled I/O did not confirm completion; experiment disabled until restart')

    def _perform(self,kind,value,deadline,observer):
        with self._lock:
            self._check_owner()
            if time.monotonic()>=deadline: raise PipeDeadline('named-pipe response deadline expired')
            if kind=='read':
                operation,error=self._api.ReadFile(self._handle,value,overlapped=True)
                self._counts['reads']+=1
            else:
                operation,error=self._api.WriteFile(self._handle,value,overlapped=True)
                self._counts['writes']+=1
            self._active=operation
        terminal=False
        try:
            if error==PENDING:
                remaining=max(0,math.ceil((deadline-time.monotonic())*1000))
                outcome=self._wait([self._stop,operation.event],remaining,observer,kind)
                if outcome==0: raise PipeCancelled('named-pipe operation cancelled by close')
                if outcome==WAIT_TIMEOUT: raise PipeDeadline('named-pipe response deadline expired')
                if outcome!=1: raise OSError('unexpected named-pipe event wait result')
            count,error=self._result(operation)
            if error==INCOMPLETE: raise OSError('signalled named-pipe operation is still incomplete')
            terminal=True
            if error==ABORTED: raise PipeCancelled('named-pipe operation aborted')
            if error not in (0,MORE_DATA): raise OSError(error,'named-pipe I/O failed')
            if kind=='read':
                data=operation.getbuffer()
                if not data: raise BrokenPipeError('named pipe closed')
                return data
            return count
        except BaseException:
            if not terminal:
                self._cancel_and_confirm(operation,observer)
                terminal=True
            raise
        finally:
            if terminal:
                with self._lock:
                    self._active=None
                    if self._closing: self._retire_handles()

    def write_deadline(self,data,deadline,observer=None):
        data=bytes(data)
        if len(data)>MAX_WRITE_BYTES: raise ValueError('experimental IPC write exceeds1MiB bound')
        offset=0
        while offset<len(data):
            written=self._perform('write',data[offset:],deadline,observer)
            if written<=0: raise BrokenPipeError('named-pipe write made no progress')
            offset+=written
        return offset

    def read_deadline(self,size,deadline,observer=None):
        return self._perform('read',min(65536,max(1,int(size))),deadline,observer)

    def read_available(self):
        with self._lock:
            self._check_owner()
            available=self._api.PeekNamedPipe(self._handle)[0]
        if not available: return b''
        return self.read_deadline(min(65536,available),time.monotonic()+.025)
