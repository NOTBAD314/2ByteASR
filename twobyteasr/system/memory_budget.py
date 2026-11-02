"""Cheap memory-pressure reads; no process enumeration on the GUI thread."""
import ctypes
import os

def memory_status():
    if os.name!='nt':
        try:
            import psutil
            memory=psutil.virtual_memory()
            return dict(available=memory.available,total=memory.total,rss=psutil.Process().memory_info().rss)
        except (ImportError,OSError):return dict(available=1024**3,total=8*1024**3,rss=0)
    class Status(ctypes.Structure):
        _fields_=[('length',ctypes.c_uint32),('load',ctypes.c_uint32)]+[
            (name,ctypes.c_uint64) for name in ('total','available','pagefile_total','pagefile_available',
                                              'virtual_total','virtual_available','extended')]
    value=Status();value.length=ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return dict(available=1024**3,total=8*1024**3,rss=0)
    class Counters(ctypes.Structure):
        _fields_=[('size',ctypes.c_uint32),('faults',ctypes.c_uint32)]+[
            (name,ctypes.c_size_t) for name in ('peak','rss','peak_paged','paged','peak_nonpaged',
                                              'nonpaged','pagefile','peak_pagefile','private')]
    counters=Counters();counters.size=ctypes.sizeof(counters)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1),ctypes.byref(counters),counters.size)
    return dict(available=value.available,total=value.total,rss=counters.rss,private=counters.private,
                peak_rss=counters.peak,page_faults=counters.faults,
                commit_limit=value.pagefile_total,commit_available=value.pagefile_available)
