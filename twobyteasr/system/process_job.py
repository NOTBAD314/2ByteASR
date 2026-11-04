"""Windows request-owned process trees, including descendants after root exit."""
import ctypes
import os
import time
from ctypes import wintypes


class RequestProcessJob:
    """Attach while suspended, then resume; never capture another request's PID."""
    def __init__(self, process):
        self.handle=None
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        api=self.api
        api.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        api.CreateJobObjectW.restype=wintypes.HANDLE
        api.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        api.TerminateJobObject.argtypes=[wintypes.HANDLE,wintypes.UINT]
        api.QueryInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
                ('flags',wintypes.DWORD),('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),
                ('active_limit',wintypes.DWORD),('affinity',ctypes.c_size_t),
                ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',ctypes.c_ulonglong*6),('process_memory',ctypes.c_size_t),
                ('job_memory',ctypes.c_size_t),('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]
        self.handle=api.CreateJobObjectW(None,None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info=Extended();info.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not api.SetInformationJobObject(self.handle,9,ctypes.byref(info),ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not api.AssignProcessToJobObject(self.handle,wintypes.HANDLE(int(process._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
            resume=ctypes.WinDLL('ntdll').NtResumeProcess
            resume.argtypes=[wintypes.HANDLE];resume.restype=ctypes.c_long
            if resume(wintypes.HANDLE(int(process._handle))) < 0:
                raise OSError('Unable to resume the owned CLI process')
        except BaseException:
            api.CloseHandle(self.handle);self.handle=None
            raise

    def close(self,timeout=3):
        if not self.handle:
            return
        class Accounting(ctypes.Structure):
            _fields_=[('times',ctypes.c_longlong*4),('page_faults',wintypes.DWORD),
                ('total',wintypes.DWORD),('active',wintypes.DWORD),('terminated',wintypes.DWORD)]
        if not self.api.TerminateJobObject(self.handle,0):
            raise ctypes.WinError(ctypes.get_last_error())
        until=time.monotonic()+timeout
        while True:
            info=Accounting()
            if not self.api.QueryInformationJobObject(self.handle,1,ctypes.byref(info),ctypes.sizeof(info),None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not info.active:
                self.api.CloseHandle(self.handle);self.handle=None
                return
            if time.monotonic()>=until:
                raise TimeoutError('CLI descendants have not finished; keep request resources')
            time.sleep(.01)

    def __del__(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
