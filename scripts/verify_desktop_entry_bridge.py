"""Keep the private desktop alive through the actual launcher child exit."""
import ctypes
from ctypes import wintypes as W
import json
from pathlib import Path
import subprocess
import sys
import time

output=Path(sys.argv[1]); command=json.loads(sys.argv[2])
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD]
kernel.GetExitCodeProcess.argtypes=[W.HANDLE,ctypes.POINTER(W.DWORD)]
kernel.CloseHandle.argtypes=[W.HANDLE]
entry=subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW)
record={'entry':command,'entry_pid':entry.pid}
handle=None
deadline=time.monotonic()+890
try:
    while time.monotonic()<deadline:
        if handle is None:
            try:lines=(output/'startup.jsonl').read_text('utf8').splitlines()
            except OSError:lines=[]
            for line in lines:
                event=json.loads(line)
                if event.get('stage')=='EARLY_INSTANCE_OWNER':
                    record['gui_pid']=int(event['pid'])
                    handle=kernel.OpenProcess(0x00100000|0x1000,False,record['gui_pid'])
                    if not handle:raise ctypes.WinError(ctypes.get_last_error())
                    break
        try:result=json.loads((output/'result.json').read_text('utf8'))
        except (OSError,ValueError):result={}
        if result.get('gui_shutdown') and handle:
            record['gui_wait']=kernel.WaitForSingleObject(handle,10000)
            code=W.DWORD()
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):raise ctypes.WinError(ctypes.get_last_error())
            record['gui_exit']=code.value;record['entry_exit']=entry.wait(timeout=5)
            record['passed']=bool(result.get('passed') and record['gui_wait']==0 and code.value==0 and record['entry_exit']==0)
            break
        time.sleep(.1)
    else:record.update(passed=False,error='Actual GUI did not complete')
finally:
    if handle:kernel.CloseHandle(handle)
    (output/'bridge-result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
raise SystemExit(0 if record.get('passed') else 1)
