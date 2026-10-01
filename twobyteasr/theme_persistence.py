"""Atomic draft writes, tolerating a brief Windows reader/scanner share lock."""
import os
from pathlib import Path
import time
import uuid

def write_text_atomic(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('w',encoding='utf8',newline='\n') as handle:
        handle.write(text);handle.flush();os.fsync(handle.fileno())
    for attempt in range(4):
        try:temporary.replace(path);return path
        except PermissionError as exc:
            if getattr(exc,'winerror',None) not in (5,32) or attempt==3:raise
            time.sleep(.01*(2**attempt))
    return path
