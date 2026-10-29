"""Cancelable, process-owned high-resolution timer for an opt-in poll wait.

This is still polling, not pipe readiness. No I/O buffers, reader threads,
APCs, periodic timers or system timer-resolution changes are introduced.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
import math
import sys
import threading


class TimerCancelled(RuntimeError):
    pass


class _TimerAPI:
    def __init__(self):
        if sys.platform!='win32': raise OSError('high-resolution poll timer requires Windows')
        import _winapi
        self.winapi=_winapi
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        for name,args,result in (
            ('CreateWaitableTimerExW',[ctypes.c_void_p,W.LPCWSTR,W.DWORD,W.DWORD],W.HANDLE),
            ('SetWaitableTimerEx',[W.HANDLE,ctypes.POINTER(ctypes.c_longlong),W.LONG,
                ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,W.ULONG],W.BOOL),
            ('CancelWaitableTimer',[W.HANDLE],W.BOOL),
            ('CreateEventW',[ctypes.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR],W.HANDLE),
            ('SetEvent',[W.HANDLE],W.BOOL),
        ):
            fn=getattr(self.kernel,name);fn.argtypes=args;fn.restype=result

    def timer(self):
        # HIGH_RESOLUTION; synchronization timer, unnamed and non-inheritable.
        handle=self.kernel.CreateWaitableTimerExW(None,None,0x2,0x00100002)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)
    def event(self):
        handle=self.kernel.CreateEventW(None,True,False,None)
        if not handle: raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)
    def arm(self,timer,seconds):
        due=ctypes.c_longlong(-max(1,round(seconds*10_000_000)))
        if not self.kernel.SetWaitableTimerEx(timer,ctypes.byref(due),0,None,None,None,0):
            raise ctypes.WinError(ctypes.get_last_error())
    def cancel(self,timer):
        if not self.kernel.CancelWaitableTimer(timer): raise ctypes.WinError(ctypes.get_last_error())
    def signal(self,event):
        if not self.kernel.SetEvent(event): raise ctypes.WinError(ctypes.get_last_error())
    def wait(self,handles,timeout_ms):
        return self.winapi.WaitForMultipleObjects(handles,False,timeout_ms)
    def close(self,handle): self.winapi.CloseHandle(handle)


class HighResolutionPollTimer:
    name='windows-highres-timer-poll-v1'
    def __init__(self,*,_api=None):
        self._api=_api or _TimerAPI()
        self._lock=threading.Lock()
        self._timer=self._stop=None
        self._waiting=self._closed=False
        self._owner=None
        try:
            self._timer=self._api.timer()
            self._stop=self._api.event()
        except BaseException:
            self._closed=True
            self._retire()
            raise

    def _retire(self):
        timer,stop=self._timer,self._stop
        self._timer=self._stop=None
        try:
            if timer is not None:self._api.close(timer)
        finally:
            if stop is not None:self._api.close(stop)

    def wait(self,seconds):
        seconds=float(seconds)
        if not math.isfinite(seconds) or seconds<=0 or seconds>1:
            raise ValueError('poll timer interval must be in (0,1] seconds')
        with self._lock:
            if self._closed:raise TimerCancelled('poll timer closed')
            owner=threading.get_ident()
            if self._owner is None:self._owner=owner
            if self._owner!=owner or self._waiting:
                raise RuntimeError('poll timer is owned by one actor thread')
            self._api.arm(self._timer,seconds)
            self._waiting=True
            handles=[self._stop,self._timer]
        try:
            # Bound the native wait even if a timer does not signal. No
            # repeated wait or busy-spin occurs; the caller checks its IPC
            # deadline again. The one-ms margin lets the timer signal first.
            outcome=self._api.wait(handles,max(1,math.ceil(seconds*1000))+1)
            if outcome==0:raise TimerCancelled('poll timer cancelled')
            if outcome==1:return 'timer_signalled'
            if outcome==258:return 'bounded_timeout'
            raise OSError('unexpected poll timer wait result')
        finally:
            with self._lock:
                try:self._api.cancel(self._timer)
                finally:
                    self._waiting=False
                    if self._closed:self._retire()

    def close(self):
        with self._lock:
            if self._closed:return
            self._closed=True
            if self._waiting:
                # CancelWaitableTimer does not wake waiters. Signal our own
                # event; handles stay alive until the actor returns from wait.
                self._api.signal(self._stop)
            else:self._retire()
