"""Keep an isolated desktop alive until the actual GUI, not its launcher, exits."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def shell_open(command, project, *, registry_key):
    """Use a private registered class key without touching system defaults."""
    import winreg
    if len(command)!=1:
        raise ValueError('Shell association testing requires an EXE entry')
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,registry_key) as key:
            with winreg.CreateKey(key,'shell\\open\\command') as opening:
                winreg.SetValueEx(opening,'',0,winreg.REG_SZ,f'"{command[0]}" "%1"')
            class ShellInfo(ctypes.Structure):
                _fields_=[('cbSize',W.DWORD),('fMask',W.ULONG),('hwnd',W.HWND),('lpVerb',W.LPCWSTR),
                    ('lpFile',W.LPCWSTR),('lpParameters',W.LPCWSTR),('lpDirectory',W.LPCWSTR),
                    ('nShow',ctypes.c_int),('hInstApp',W.HINSTANCE),('lpIDList',ctypes.c_void_p),
                    ('lpClass',W.LPCWSTR),('hkeyClass',W.HKEY),('dwHotKey',W.DWORD),
                    ('hIcon',W.HANDLE),('hProcess',W.HANDLE)]
            info=ShellInfo();info.cbSize=ctypes.sizeof(info)
            info.fMask=0x00000003|0x00000040|0x00000100|0x00000400  # CLASSKEY, NOCLOSEPROCESS, NOASYNC, NO_UI
            info.lpVerb='open';info.lpFile=str(project);info.lpDirectory=os.getcwd()
            info.hkeyClass=int(key);info.nShow=0
            shell=ctypes.WinDLL('shell32',use_last_error=True)
            shell.ShellExecuteExW.argtypes=[ctypes.POINTER(ShellInfo)]
            if not shell.ShellExecuteExW(ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            handle=info.hProcess
    finally:
        # The UUID class belongs only to this audit. NOASYNC lets cleanup run
        # after synchronous launch or failure without touching shared defaults.
        for suffix in ('\\shell\\open\\command','\\shell\\open','\\shell',''):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER,registry_key+suffix)
            except FileNotFoundError:
                pass
    return handle


def main():
    output=Path(sys.argv[1]).resolve()
    plan=json.loads((output/'entry-plan.json').read_text('utf8'))
    command=plan['command']
    arguments=[plan['project']] if plan['case']=='project' else []
    result={'bridge':plan.get('bridge','direct'),'entry':command,'started_utc_ms':time.time()*1000}
    child=None;shell_handle=None;sender=None;gui_handle=None;owner_pid=None
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD]
    kernel.GetExitCodeProcess.argtypes=[W.HANDLE,ctypes.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes=[W.HANDLE]
    def capture_owner():
        nonlocal gui_handle,owner_pid
        if owner_pid is not None:return True
        try:lines=(output/'startup-trace.jsonl').read_text('utf8').splitlines()
        except OSError:return False
        for line in lines:
            try:event=json.loads(line)
            except ValueError:continue
            if event.get('stage')=='EARLY_INSTANCE_OWNER':
                owner_pid=int(event['pid'])
                gui_handle=kernel.OpenProcess(0x00100000|0x1000,False,owner_pid)
                result['actual_gui_pid']=owner_pid
                result['actual_gui_process_handle_opened']=bool(gui_handle)
                return True
        return False
    if result['bridge']=='shell':
        key='Software\\2ByteASR-Entry-Audit-'+uuid.uuid4().hex
        result['private_registry_class']=key
        result['shell_registration_command']=f'"{command[0]}" "%1"'
        shell_handle=shell_open(command,plan['project'],registry_key=key)
    else:
        child=subprocess.Popen(command+arguments,cwd=plan['invoker_cwd'],
                               creationflags=subprocess.CREATE_NO_WINDOW)
        result['entry_pid']=child.pid
    if result['bridge']=='startup':
        # The real owner event, not launcher lifetime or a fixed import sleep,
        # determines when the starting-instance sender is allowed to launch.
        owner_deadline=time.monotonic()+15
        while not capture_owner() and time.monotonic()<owner_deadline:time.sleep(.05)
        if owner_pid is None:
            result['error']='No actual early GUI owner event; startup sender was not guessed'
            (output/'bridge-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
            return 1
        result['startup_sender_started_utc_ms']=time.time()*1000
        sender=subprocess.Popen(command+[plan['project']],cwd=plan['invoker_cwd'],
                                creationflags=subprocess.CREATE_NO_WINDOW)
        result['startup_sender_pid']=sender.pid
    deadline=time.monotonic()+170
    while time.monotonic()<deadline:
        capture_owner()
        receipt=output/'entry-result.json'
        try:value=json.loads(receipt.read_text('utf8'))
        except (OSError,ValueError):value={}
        if value.get('gui_shutdown'):
            break
        time.sleep(.1)
    else:
        result['error']='Actual GUI did not complete; no unrelated processes were terminated'
        value={}
    if child is not None:
        try:
            result['entry_exit']=child.wait(timeout=5) if value.get('gui_shutdown') else child.poll()
        except subprocess.TimeoutExpired:
            result['entry_exit']=None
    if sender is not None:
        try:
            result['startup_sender_exit']=sender.wait(timeout=5) if value.get('gui_shutdown') else sender.poll()
        except subprocess.TimeoutExpired:
            result['startup_sender_exit']=None
    if shell_handle:
        code=W.DWORD();kernel.GetExitCodeProcess(shell_handle,ctypes.byref(code))
        result['shell_entry_exit']=code.value
        kernel.CloseHandle(shell_handle)
    if gui_handle:
        result['actual_gui_wait_result']=kernel.WaitForSingleObject(gui_handle,10000)
        code=W.DWORD();kernel.GetExitCodeProcess(gui_handle,ctypes.byref(code))
        result['actual_gui_exit']=code.value
        kernel.CloseHandle(gui_handle)
    elif child is not None and owner_pid==child.pid:
        result['actual_gui_exit']=child.poll()
    else:
        result['actual_gui_exit']=None
    result['passed']=bool(value.get('passed') and value.get('gui_shutdown') and not result.get('error')
                          and result.get('entry_exit',0)==0 and result.get('startup_sender_exit',0)==0
                          and result.get('shell_entry_exit',0)==0 and result.get('actual_gui_exit')==0
                          and owner_pid==value.get('gui_pid'))
    (output/'bridge-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
