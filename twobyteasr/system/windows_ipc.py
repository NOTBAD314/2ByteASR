"""Keep local IPC inside the Windows AppContainer namespace when applicable."""
from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def in_app_container() -> bool:
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = wintypes.HANDLE()
    if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(handle)):
        return False
    try:
        value, size = wintypes.DWORD(), wintypes.DWORD()
        return bool(adv.GetTokenInformation(handle, 29, ctypes.byref(value), 4, ctypes.byref(size)) and value.value)
    finally:
        kernel.CloseHandle(handle)


def process_pipe(context):
    """Use the stdlib pipe implementation, with only its private name adjusted.

    Windows requires \\LOCAL\\ named pipes inside a container. A private globals
    copy avoids monkey-patching multiprocessing for other threads or processes.
    Default token ACLs and normal handle transfer remain owned by the stdlib.
    """
    if not in_app_container():
        return context.Pipe()
    from multiprocessing import connection
    from types import FunctionType
    original_address = connection.arbitrary_address

    def local_address(family):
        address = original_address(family)
        return address.replace('\\\\.\\pipe\\', '\\\\.\\pipe\\LOCAL\\', 1) if family == 'AF_PIPE' else address

    scope = dict(connection.Pipe.__globals__, arbitrary_address=local_address)
    pipe = FunctionType(connection.Pipe.__code__, scope, argdefs=connection.Pipe.__defaults__)
    return pipe()
