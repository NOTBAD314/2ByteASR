"""Bounded, real recognition progress; no synthetic text or percentage clock."""
from __future__ import annotations
import hashlib
import os
import time


class PrimaryProgress:
    def __init__(self, source_path, total, backend='api', *, publish_primary=True):
        from .runtime import get_runtime_context
        self.context = get_runtime_context()
        self.source_path = str(source_path)
        identity = os.path.normcase(os.path.abspath(self.source_path)) + self.context.job_id + backend
        self.key = hashlib.sha256(identity.encode('utf8')).hexdigest()[:20]
        self.backend, self.total = backend, total
        self.publish_primary = publish_primary
        self.completed = set()
        self.rows, self.pending = {}, {}
        self.last_emit = 0.
        self.started = time.monotonic()

    def complete(self, index, rows, *, force=False):
        from .cache import record_run_event
        self.completed.add(index)
        for ordinal, row in enumerate(rows):
            cue = dict(id=f'asr-{self.key}-{index:05d}-{ordinal:03d}',
                start_ms=round(float(row['start'])*1000), end_ms=round(float(row['end'])*1000),
                text=str(row.get('text') or ''), speaker_id=str(row.get('speaker') or 'S00'),
                state='provisional')
            if cue['text'] and cue['end_ms'] > cue['start_ms']:
                self.rows[cue['id']] = cue
                self.pending[cue['id']] = cue
        now = time.monotonic()
        if force or now-self.last_emit >= .25 or len(self.completed) == self.total:
            ordered = sorted(self.rows.values(), key=lambda item:(item['start_ms'],item['id']))
            if self.publish_primary:
                self.context.asr_manifest_key = self.key
                self.context.asr_provisional_cues = ordered
            if self.pending:
                record_run_event('cue_delta' if self.publish_primary else 'asr_reference_delta', source_path=self.source_path, manifest_key=self.key,
                    job_id=self.context.job_id, backend=self.backend, chunk_index=index, state='provisional',
                    reused=False, cues=sorted(self.pending.values(),key=lambda item:(item['start_ms'],item['id'])))
                self.pending.clear()
            record_run_event('asr_progress', backend=self.backend, status='batch_completed',
                completed_batches=len(self.completed), total_batches=self.total,
                elapsed_seconds=round(now-self.started,3), cue_count=len(ordered),
                processed_ranges_ms=[[row['start_ms'],row['end_ms']] for row in ordered[-8:]],
                last_progress_monotonic=now)
            self.last_emit=now


def api_local_admission(gpu, *, audio_bytes=0, system=None):
    """One local model + bounded HTTP queue, never concurrent heavy GPU loads."""
    if system is None:
        import psutil
        system = {'cpu_count':os.cpu_count() or 1, 'cpu_percent':psutil.cpu_percent(interval=.1),
                  'available_ram_bytes':psutil.virtual_memory().available}
        from .processes import run_hidden_subprocess
        try:
            probe=run_hidden_subprocess(['nvidia-smi','--query-gpu=utilization.gpu','--format=csv,noheader,nounits'],
                capture_output=True,text=True,timeout=3,purpose='ASR bounded concurrency admission')
            gpu=dict(gpu,utilization_percent=float(probe.stdout.splitlines()[0].strip()))
        except (OSError,ValueError,IndexError):gpu=dict(gpu,utilization_percent=None)
    reasons=[]
    if gpu.get('status') != 'READY':reasons.append('gpu_not_ready')
    if float(gpu.get('free_vram_gb') or 0) < 6.:reasons.append('single_model_vram_reserve')
    if gpu.get('utilization_percent') is not None and float(gpu['utilization_percent'])>=85:reasons.append('gpu_busy')
    if int(system.get('cpu_count') or 1) < 4 or float(system.get('cpu_percent') or 0) > 90:
        reasons.append('cpu_busy')
    if int(system.get('available_ram_bytes') or 0) < 3*1024**3+2*audio_bytes:
        reasons.append('ram_reserve')
    return {'admitted':not reasons,'reasons':reasons,'gpu':gpu,'system':system,
            'max_local_workers':1,'max_stage_workers':2,'vram_reserve_gb':6.,
            'reserve_basis':'FireRed batch1 measured 2.76 GiB reserved + driver/other-process headroom; conservative 6 GiB gate'}
