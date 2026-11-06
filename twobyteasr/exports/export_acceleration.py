"""Cheap device observations and bounded history of complete native exports.

No benchmark/probe jobs are added to the export click. Encoder functionality
continues to come from the existing capability scan and production fallback.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

_LOCK=threading.Lock()
_OBSERVATION=None

def device_observation():
    global _OBSERVATION
    with _LOCK:
        if _OBSERVATION and time.monotonic()-_OBSERVATION[0]<5:return dict(_OBSERVATION[1])
    from ..system.processes import run_hidden_subprocess
    try:
        result=run_hidden_subprocess(['nvidia-smi',
            '--query-gpu=index,uuid,driver_version,memory.total,memory.free,utilization.gpu,utilization.encoder,utilization.decoder',
            '--format=csv,noheader,nounits'],purpose='export device resource observation',
            capture_output=True,text=True,encoding='utf8',errors='replace',timeout=1.5)
        rows=[row.split(',') for row in result.stdout.splitlines()]
        row=next([v.strip() for v in r] for r in rows if r[0].strip()=='0')
        observed=dict(device=row[1],driver=row[2],total_vram_bytes=int(row[3])*1024**2,
            free_vram_bytes=int(row[4])*1024**2,gpu_percent=int(row[5]),
            encoder_percent=int(row[6]),decoder_percent=int(row[7]))
    except Exception:
        observed=dict(unavailable=True)
    with _LOCK:_OBSERVATION=(time.monotonic(),observed)
    return dict(observed)

def _directory():
    from ..projects.studio_project import studio_data_root
    return studio_data_root()/'export-performance-history'

def history_key(job,device,ffmpeg):
    from ..rendering.caption_asset_identity import file_digest
    p=Path(job.media_path)
    stat=p.stat()
    s=job.settings
    workload=dict(device=device['device'],driver=device['driver'],ffmpeg=file_digest(ffmpeg),
        input=[stat.st_size,stat.st_mtime_ns],clock=[s.width,s.height,s.fps,round(job.duration_seconds or 0,2)],
        encode=[s.encoder,s.codec,s.preset,s.quality_mode,s.quality,s.bitrate_kbps,s.pixel_format,
                s.audio_codec,s.audio_bitrate_kbps],graph=bool(job.direct_video_graph))
    # Relocating media or temporary directories is not a hardware/workload change.
    return hashlib.sha256(json.dumps(workload,sort_keys=True,default=str).encode()).hexdigest()

def read_history(key):
    try:
        d=json.loads((_directory()/(key+'.json')).read_text('utf8'))
        if d.get('schema')==1 and time.time()-d.get('updated',0)<30*86400:return d
    except (OSError,ValueError,TypeError):pass
    return {}

def record_outcome(job):
    selection=job.completion_metadata.get('parallel_selection') or {}
    key=selection.get('history_key')
    elapsed=job.completion_metadata.get('elapsed_seconds')
    if not key or not elapsed or not job.completion_metadata.get('output_path'):return
    folder=_directory();folder.mkdir(parents=True,exist_ok=True)
    destination=folder/(key+'.json');stage=destination.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    try:
        data=read_history(key) or dict(schema=1,samples={})
        mode=str(job.completion_metadata.get('parallel_segments') or selection.get('segments',1))
        samples=data.setdefault('samples',{}).setdefault(mode,[])
        samples.append(float(elapsed));del samples[:-5]
        data['updated']=time.time()
        stage.write_text(json.dumps(data),encoding='utf8');os.replace(stage,destination)
        for old in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[64:]:old.unlink(missing_ok=True)
    finally:stage.unlink(missing_ok=True)

def note_session_failure(job):
    key=(job.export_context.get('parallel_decision') or {}).get('history_key')
    if not key:return
    folder=_directory();folder.mkdir(parents=True,exist_ok=True)
    destination=folder/(key+'.json')
    data=read_history(key) or dict(schema=1,samples={})
    data.update(updated=time.time(),session_failure_until=time.time()+3600)
    stage=destination.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    try:stage.write_text(json.dumps(data),encoding='utf8');os.replace(stage,destination)
    finally:stage.unlink(missing_ok=True)

def advanced_selection(job):
    from .parallel_video_export import requested_segments
    requested=requested_segments(job)
    selection=dict(mode='auto' if requested==0 else 'single' if requested==1 else 'dual',
        requested_segments=requested,segments=1,reason='advanced captions retain the dedicated fidelity renderer')
    job.export_context['parallel_decision']=selection
    job.completion_metadata.update(parallel_selection=selection,parallel_segments=1)
    from .export_run_log import note_export
    note_export('parallel_selection',selection)
