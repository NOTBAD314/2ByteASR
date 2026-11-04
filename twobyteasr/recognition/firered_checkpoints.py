"""Durable per-window FireRed evidence and conservative live batch admission."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from ..storage.atomic_files import write_text_atomic


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def batch_budget(free_vram, available_ram, *, requested=0, maximum=4):
    gib=1024**3
    capacity = 4 if free_vram>=6*gib and available_ram>=6*gib else 2 if free_vram>=3*gib and available_ram>=3*gib else 1
    return max(1,min(maximum,int(requested) if requested>0 else capacity))


def read_row(root, job, identity):
    key=fingerprint({'input':job['audio_sha256'],'model':identity,'duration':job['duration']})
    path=Path(root)/(key+'.json')
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        if data['key']!=key or fingerprint(data['row'])!=data['sha256']:return None
        row=data['row']
        if not isinstance(row.get('timestamp'),list) or not isinstance(row.get('text'),str):return None
        return dict(row,segment_id=job['segment_id'])
    except (OSError,ValueError,KeyError,TypeError):return None


def save_row(root, job, identity, row):
    key=fingerprint({'input':job['audio_sha256'],'model':identity,'duration':job['duration']})
    path=Path(root)/(key+'.json')
    write_text_atomic(path,json.dumps({'key':key,'row':row,'sha256':fingerprint(row)},ensure_ascii=False))
    return str(path)
