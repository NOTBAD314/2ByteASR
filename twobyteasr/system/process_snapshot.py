"""One bounded process census for diagnostics; no names, paths or commands."""
from __future__ import annotations

import os


def process_snapshot() -> dict[int, tuple[int, int]]:
    """PID -> (parent PID, thread count). Windows ctypes releases the GIL.

    psutil's Windows num_threads walks system process information for each
    PID (~20 ms per call on the audit host). One Toolhelp census supplies both
    parentage and counts without repeating that walk for every child.
    """
    if os.name != 'nt':
        import psutil
        return {p.pid: (p.info['ppid'], p.info['num_threads'])
                for p in psutil.process_iter(['ppid', 'num_threads'])}
    import ctypes
    from ctypes import wintypes as W
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ProcessID', W.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', W.DWORD),
                    ('cntThreads', W.DWORD), ('th32ParentProcessID', W.DWORD),
                    ('pcPriClassBase', ctypes.c_long), ('dwFlags', W.DWORD), ('szExeFile', W.WCHAR*260)]
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    dll.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    dll.CreateToolhelp32Snapshot.restype = W.HANDLE
    dll.Process32FirstW.argtypes = dll.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(Entry)]
    dll.Process32FirstW.restype = dll.Process32NextW.restype = W.BOOL
    dll.CloseHandle.argtypes = [W.HANDLE]
    handle = dll.CreateToolhelp32Snapshot(2, 0)
    if not handle or handle == W.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    rows = {}
    try:
        entry = Entry(); entry.dwSize = ctypes.sizeof(entry)
        more = dll.Process32FirstW(handle, ctypes.byref(entry))
        while more and len(rows) < 65536:
            rows[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), int(entry.cntThreads))
            more = dll.Process32NextW(handle, ctypes.byref(entry))
        if ctypes.get_last_error() not in (0, 18):  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
        return rows
    finally:
        dll.CloseHandle(handle)


def descendant_pids(root, rows):
    children = {}
    for pid, (parent, _threads) in rows.items():
        children.setdefault(parent, []).append(pid)
    visited = {root}
    pending = [root]
    found = []
    while pending:
        for pid in children.get(pending.pop(), ()):
            if pid not in visited:
                visited.add(pid); pending.append(pid); found.append(pid)
    return found
