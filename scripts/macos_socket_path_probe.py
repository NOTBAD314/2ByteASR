"""Observe the native IPC limit without modifying application code."""
from pathlib import Path
import json, os, subprocess, sys
out = Path(sys.argv[1]).resolve()
assert 'tmp' in out.parts and not out.exists()
out.mkdir(parents=True)
long = Path('/Users/runner/work/_temp/tmp/2byteasr-macos-43209827566-1/chinese-complete-expression/temp')
short = out / 't'
code = """from PySide6.QtCore import QCoreApplication,QDir
from PySide6.QtNetwork import QLocalServer
import json,os
app=QCoreApplication([]); server=QLocalServer()
ok=server.listen('2ByteASR-123456789abc')
result=dict(ok=ok,error=server.errorString(),temp=QDir.tempPath(),endpoint_bytes=len((QDir.tempPath()+'/2ByteASR-123456789abc').encode()))
server.close();QLocalServer.removeServer('2ByteASR-123456789abc')
print(json.dumps(result))
"""
results = {}
for label, temp in [('long',long),('short',short)]:
    temp.mkdir(parents=True,exist_ok=True)
    env = dict(os.environ,TMPDIR=str(temp),TMP=str(temp),TEMP=str(temp))
    value = subprocess.check_output([sys.executable,'-c',code],env=env,text=True)
    results[label] = json.loads(value)
assert not results['long']['ok'] and results['short']['ok'],results
results['passed']=True
(out/'socket-path-boundary.json').write_text(json.dumps(results,indent=2),'utf8')
print(json.dumps(results),flush=True)
