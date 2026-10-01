"""Run owned GUI verification on a new desktop; never switch the user's desktop."""
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import time
import uuid


def run_on_desktop(command, *, cwd, env, output, timeout):
    if os.name != 'nt':
        raise RuntimeError('Windows desktop isolation is required')
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class STARTUPINFO(ctypes.Structure):
        _fields_ = [('cb',W.DWORD),('lpReserved',W.LPWSTR),('lpDesktop',W.LPWSTR),('lpTitle',W.LPWSTR),
            ('dwX',W.DWORD),('dwY',W.DWORD),('dwXSize',W.DWORD),('dwYSize',W.DWORD),
            ('dwXCountChars',W.DWORD),('dwYCountChars',W.DWORD),('dwFillAttribute',W.DWORD),
            ('dwFlags',W.DWORD),('wShowWindow',W.WORD),('cbReserved2',W.WORD),
            ('lpReserved2',ctypes.POINTER(ctypes.c_byte)),('hStdInput',W.HANDLE),('hStdOutput',W.HANDLE),('hStdError',W.HANDLE)]
    class PROCESSINFO(ctypes.Structure):
        _fields_=[('hProcess',W.HANDLE),('hThread',W.HANDLE),('dwProcessId',W.DWORD),('dwThreadId',W.DWORD)]
    user.CreateDesktopW.argtypes=[W.LPCWSTR,W.LPCWSTR,ctypes.c_void_p,W.DWORD,W.DWORD,ctypes.c_void_p]
    user.CreateDesktopW.restype=W.HANDLE
    user.CloseDesktop.argtypes=[W.HANDLE]
    kernel.CreateProcessW.argtypes=[W.LPCWSTR,W.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,W.BOOL,W.DWORD,
        ctypes.c_void_p,W.LPCWSTR,ctypes.POINTER(STARTUPINFO),ctypes.POINTER(PROCESSINFO)]
    kernel.GetExitCodeProcess.argtypes=[W.HANDLE,ctypes.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes=[W.HANDLE]
    desktop_name='2ByteASR-verification-'+uuid.uuid4().hex
    desktop=user.CreateDesktopW(desktop_name,None,None,0,0x01ff,None)
    if not desktop:raise ctypes.WinError(ctypes.get_last_error())
    info=PROCESSINFO()
    try:
        import msvcrt
        with (output/'stdout.log').open('wb') as stdout, (output/'stderr.log').open('wb') as stderr, open(os.devnull,'rb') as stdin:
            handles=[msvcrt.get_osfhandle(stream.fileno()) for stream in (stdin,stdout,stderr)]
            for handle in handles:os.set_handle_inheritable(handle,True)
            startup=STARTUPINFO();startup.cb=ctypes.sizeof(startup)
            startup.lpDesktop=desktop_name;startup.dwFlags=0x100|1;startup.wShowWindow=0
            startup.hStdInput,startup.hStdOutput,startup.hStdError=handles
            block=ctypes.create_unicode_buffer('\0'.join(f'{k}={v}' for k,v in sorted(env.items()))+'\0\0')
            cmd=ctypes.create_unicode_buffer(subprocess.list2cmdline([str(x) for x in command]))
            ok=kernel.CreateProcessW(None,cmd,None,None,True,0x400|0x08000000,block,str(cwd),ctypes.byref(startup),ctypes.byref(info))
            for handle in handles:os.set_handle_inheritable(handle,False)
            if not ok:raise ctypes.WinError(ctypes.get_last_error())
            (output/'desktop.json').write_text(__import__('json').dumps(dict(desktop=desktop_name,pid=info.dwProcessId,
                switched=False,command=[str(x) for x in command])),encoding='utf8')
            end=time.monotonic()+timeout
            while True:
                code=W.DWORD()
                if not kernel.GetExitCodeProcess(info.hProcess,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
                if code.value != 259:return code.value
                if time.monotonic()>end:
                    # Only this explicitly created verification tree.
                    subprocess.run(['taskkill','/PID',str(info.dwProcessId),'/T','/F'],capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    raise TimeoutError(f'Owned verification process {info.dwProcessId} timed out')
                time.sleep(.1)
    finally:
        if info.hThread:kernel.CloseHandle(info.hThread)
        if info.hProcess:kernel.CloseHandle(info.hProcess)
        user.CloseDesktop(desktop)
