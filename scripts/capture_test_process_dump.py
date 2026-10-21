"""Capture an explicitly owned synthetic-test process, not a system-wide debugger.

MiniDumpWithThreadInfo is a live post-fault snapshot, not a second-chance
exception-context dump. It can contain private memory and is never auto-shared.
"""
from pathlib import Path
import ctypes,hashlib,os
from ctypes import wintypes as W

def capture(pid,target, *, phase="post-fault"):
    if os.name!='nt':raise RuntimeError('Windows required')
    import msvcrt
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    dbg=ctypes.WinDLL('dbghelp',use_last_error=True)
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.CloseHandle.argtypes=[W.HANDLE]
    dbg.MiniDumpWriteDump.argtypes=[W.HANDLE,W.DWORD,W.HANDLE,W.DWORD,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
    dbg.MiniDumpWriteDump.restype=W.BOOL
    handle=kernel.OpenProcess(0x0400|0x0010,False,pid)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    try:
        with target.open('wb') as stream:
            if not dbg.MiniDumpWriteDump(handle,pid,msvcrt.get_osfhandle(stream.fileno()),0x1000|0x20,None,None,None):
                raise ctypes.WinError(ctypes.get_last_error())
    finally:kernel.CloseHandle(handle)
    raw=target.read_bytes()
    if raw[:4]!=b'MDMP':raise ValueError('Invalid minidump header')
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),kind=phase+' live process snapshot with thread/module stacks; private memory')
