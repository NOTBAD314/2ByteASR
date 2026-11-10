"""Durable per-window FireRed evidence and conservative live batch admission."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
from ..storage.atomic_files import write_text_atomic

VERSION = 'firered-window-v2-explicit-alignment'


def reusable_result(value):
    if not isinstance(value,dict):
        return False
    rows=value.get('segments',value.get('results',[]))
    return bool(rows) and all(isinstance(r,dict) and r.get('evidence_version')==VERSION
        and r.get('transcription_status')=='success' and r.get('alignment_status')=='aligned'
        and r.get('timestamp_source')=='ctc_forced_alignment'
        and r.get('timestamp_reliability')=='measured' for r in rows)


def reusable_row(row, duration):
    """Success means observed alignment, never merely a process/file success."""
    if row.get('evidence_version') != VERSION or row.get('transcription_status')!='success':
        return False
    if (row.get('alignment_status')!='aligned'
            or row.get('timestamp_source')!='ctc_forced_alignment'
            or row.get('timestamp_reliability')!='measured'):
        return False
    times=row.get('timestamp')
    if not isinstance(times,list) or not times or not isinstance(row.get('text'),str):
        return False
    try:
        return all(isinstance(t,dict) and str(t.get('text','')).strip()
            and math.isfinite(float(t['start'])+float(t['end']))
            and 0 <= float(t['start']) < float(t['end']) <= float(duration)+.05 for t in times)
    except (KeyError,TypeError,ValueError):
        return False


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
        if data.get('version')!=VERSION or data['key']!=key or fingerprint(data['row'])!=data['sha256']:return None
        row=data['row']
        if not reusable_row(row,job['duration']):return None
        return dict(row,segment_id=job['segment_id'])
    except (OSError,ValueError,KeyError,TypeError):return None


def save_row(root, job, identity, row):
    if not reusable_row(row,job['duration']):
        return None
    key=fingerprint({'input':job['audio_sha256'],'model':identity,'duration':job['duration']})
    path=Path(root)/(key+'.json')
    write_text_atomic(path,json.dumps({'version':VERSION,'key':key,'row':row,'sha256':fingerprint(row)},ensure_ascii=False))
    return str(path)
