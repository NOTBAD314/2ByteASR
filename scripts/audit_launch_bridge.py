"""Wait for the actual audit GUI even when its desktop launcher exits first."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run_audit_on_desktop(command, *, cwd, env, output, timeout, receipt, passed_field='passed'):
    """Launch a normal app entry on a private desktop and verify both exits."""
    from isolated_windows_desktop import run_on_desktop
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    receipt=Path(receipt).resolve()
    if not receipt.is_relative_to(output):
        raise ValueError('The GUI receipt must belong to this owned audit output')
    trace=output/'startup-trace.jsonl'
    if trace.exists() or receipt.exists():
        raise ValueError('Use fresh audit receipt and startup trace paths')
    plan=dict(command=[str(x) for x in command],cwd=str(Path(cwd).resolve()),timeout=float(timeout),
              receipt=str(receipt),passed_field=passed_field,trace=str(trace))
    path=output/'launch-plan.json';path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),'utf8')
    launch_env=dict(env,TWOBYTEASR_STARTUP_TRACE=str(trace))
    bridge=[sys.executable,'-B',str(Path(__file__).resolve()),str(path)]
    return run_on_desktop(bridge,cwd=cwd,env=launch_env,output=output,timeout=timeout+20)


def main(plan_path):
    if os.name!='nt':
        raise RuntimeError('This bridge requires Windows process handles')
    plan_path=Path(plan_path).resolve();plan=json.loads(plan_path.read_text('utf8'))
    output=plan_path.parent
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
    kernel.GetExitCodeProcess.argtypes=[W.HANDLE,ctypes.POINTER(W.DWORD)]
    kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
    kernel.TerminateProcess.argtypes=[W.HANDLE,W.UINT]
    kernel.CloseHandle.argtypes=[W.HANDLE]
    result=dict(passed=False,command=plan['command'],started_utc_ms=time.time()*1000,
                receipt=plan['receipt'],desktop_switched=False)
    child=None;gui_handle=None;owner=None
    try:
        child=subprocess.Popen(plan['command'],cwd=plan['cwd'],creationflags=subprocess.CREATE_NO_WINDOW)
        result['entry_pid']=child.pid
        deadline=time.monotonic()+plan['timeout']
        while time.monotonic()<deadline:
            if owner is None:
                try:lines=Path(plan['trace']).read_text('utf8').splitlines()
                except OSError:lines=[]
                for line in lines:
                    try:event=json.loads(line)
                    except ValueError:continue
                    if event.get('stage')!='EARLY_INSTANCE_OWNER':continue
                    owner=int(event['pid'])
                    # Keep an actual process handle; never infer GUI completion
                    # from the launcher lifetime or a pre-shutdown JSON write.
                    gui_handle=kernel.OpenProcess(0x00100000|0x1000|0x0001,False,owner)
                    if not gui_handle:raise ctypes.WinError(ctypes.get_last_error())
                    result.update(actual_gui_pid=owner,owner_event=event,actual_gui_handle_opened=True)
                    image=ctypes.create_unicode_buffer(32768);size=W.DWORD(len(image))
                    if kernel.QueryFullProcessImageNameW(gui_handle,0,image,ctypes.byref(size)):
                        result['actual_gui_image']=image.value
                    break
            if gui_handle:
                status=kernel.WaitForSingleObject(gui_handle,0)
                if status==0:
                    code=W.DWORD()
                    if not kernel.GetExitCodeProcess(gui_handle,ctypes.byref(code)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    result['actual_gui_exit']=code.value
                    break
                if status==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
            elif child.poll() not in (None,0):
                raise RuntimeError('Normal app entry failed before the actual GUI owner event')
            time.sleep(.05)
        else:
            raise TimeoutError('The actual audit GUI did not exit within its owned deadline')
        try:result['entry_exit']=child.wait(timeout=5)
        except subprocess.TimeoutExpired:result['entry_exit']=None
        try:value=json.loads(Path(plan['receipt']).read_text('utf8'))
        except (OSError,ValueError):value={}
        result['receipt_passed']=bool(value.get(plan['passed_field']))
        result['passed']=bool(result['entry_exit']==0 and result.get('actual_gui_exit')==0 and result['receipt_passed'])
        if not result['passed']:result['error']=value.get('error') or 'Entry, GUI exit or GUI receipt failed'
    except Exception as exc:
        result['error']=f'{type(exc).__name__}: {exc}'
        if gui_handle and kernel.WaitForSingleObject(gui_handle,0)==258:
            # Only the real GUI identified in this fresh audit's owner trace.
            kernel.TerminateProcess(gui_handle,1);kernel.WaitForSingleObject(gui_handle,5000)
            result['owned_gui_terminated']=True
        if child is not None:
            result['entry_exit']=child.poll()
            if result['entry_exit'] is None:
                child.terminate();result['entry_exit']=child.wait(timeout=5)
    finally:
        if gui_handle:kernel.CloseHandle(gui_handle)
        result['finished_utc_ms']=time.time()*1000
        (output/'launch-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1]))