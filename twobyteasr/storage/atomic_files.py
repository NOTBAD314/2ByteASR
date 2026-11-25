"""Atomic text writes, tolerating a brief Windows reader/scanner share lock.

Formerly ``twobyteasr/theme_persistence.py``: it started with theme drafts
but is now the shared atomic writer for model, download, speaker and design
records.
"""
import os
from pathlib import Path
import time
import uuid


def replace_atomic(temporary, target):
    """Publish complete bytes, retrying only a brief Windows share lock."""
    for attempt in range(4):
        try:
            os.replace(temporary, target)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in (5, 32) or attempt == 3:
                raise
            time.sleep(.01 * (2 ** attempt))


def write_text_atomic(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('w',encoding='utf8',newline='\n') as handle:
        handle.write(text);handle.flush();os.fsync(handle.fileno())
    replace_atomic(temporary, path)
    return path
