"""Per-window acoustic checkpoints; cue numbers never enter their identity."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

VERSION = 'acoustic-window-v1'


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _valid(row, job):
    return (isinstance(row, dict) and row.get('status') == 'aligned'
            and all(row.get(key) == job.get(key) for key in ('text', 'language', 'window_start_ms', 'window_end_ms')))


def save_worker_checkpoint(spec, row, metadata):
    """Pure writer also used by the worker after each successful GPU batch."""
    if not spec or not _valid(row, spec['identity']):
        return
    material = spec['identity']
    if _digest(material) != spec['key']:
        raise ValueError('checkpoint key mismatch')
    path = Path(spec['root']) / (spec['key'] + '.json.gz')
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = dict(identity=material, row=row, checksum=_digest(row), metadata=metadata)
        temporary.write_bytes(gzip.compress(json.dumps(record, ensure_ascii=False).encode('utf-8'), compresslevel=1))
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)


def run_cached(audio, jobs, *, identity, runner, root=None, check=None):
    """Run only missing immutable windows, retaining validated completed work.

    The identity includes the actual interval PCM, language, exact text,
    pinned engine/code and parameters. A late or malformed receipt cannot
    replace a current one. Cache writes are optional; acoustic failures are
    never converted into successful timestamps.
    """
    from .run_context import get_runtime_context
    from .alignment_audio import pcm_digest
    from .cache import record_run_event
    owner = get_runtime_context()
    preparation=getattr(owner,'streaming_preparation',None)
    if preparation is not None and not preparation.owns(audio):preparation=None
    if preparation is not None and jobs:
        preparation.wait_ready(max(int(job['window_end_ms'])*16 for job in jobs))
    valid_samples=preparation.valid_samples if preparation is not None else len(audio)
    root = root or owner.alignment_checkpoint_dir
    if not root:
        return runner(jobs)
    root = Path(root)
    reused, missing, keys, metadata, materials = {}, [], {}, None, {}
    began = time.perf_counter()

    def current():
        if check:
            check()
        if get_runtime_context() is not owner or bool(getattr(owner.cancellation_token, 'is_cancelled', False)):
            from .service import CancelledError
            raise CancelledError('对齐检查点属于已结束的任务。')

    for job in jobs:
        current()
        start = max(0, int(job['window_start_ms']) * 16)
        end = min(valid_samples, int(job['window_end_ms']) * 16)
        material = dict(version=VERSION, engine=identity,
            audio_sha256=pcm_digest(audio[start:end], check=current),
            **{name: job.get(name) for name in ('text', 'language', 'window_start_ms', 'window_end_ms')})
        key = keys[str(job['id'])] = _digest(material)
        materials[str(job['id'])] = material
        try:
            with gzip.open(root / (key + '.json.gz'), 'rt', encoding='utf-8') as stream:
                saved = json.load(stream)
            row = saved.get('row')
            # Tuple-valued model parameters round-trip through JSON as lists.
            # Compare the same canonical wire identity used to name the file.
            if (_digest(saved.get('identity')) != key or saved.get('checksum') != _digest(row)
                    or not _valid(row, job)):
                raise ValueError('checkpoint identity mismatch')
            reused[str(job['id'])] = dict(row, id=str(job['id']))
            metadata = metadata or saved['metadata']
        except (OSError, ValueError, KeyError, TypeError, EOFError):
            missing.append(job)
    current()
    record_run_event('alignment_checkpoint_plan', engine=str(identity.get('engine', '')),
        jobs=len(jobs), reused=len(reused), missing=len(missing), planning_seconds=round(time.perf_counter()-began,6))
    worker_jobs = [dict(job, _checkpoint=dict(root=str(root), key=keys[str(job['id'])],
                            identity=materials[str(job['id'])])) for job in missing]
    payload = runner(worker_jobs) if missing else dict(metadata or {}, results=[], load_ms=0., inference_ms=0.,
        model_load_count=0, resident_session_request=None, execution='checkpoint_reuse')
    current()
    returned = payload.get('results') or []
    if len(returned) != len(missing) or {str(row.get('id')) for row in returned} != {str(job['id']) for job in missing}:
        raise ValueError('对齐检查点收到缺失或重复的任务。')
    by_id = {str(row['id']): row for row in returned}
    meta = {key: value for key, value in payload.items() if key not in ('results', 'audio_sha256')}
    # Cache identities are recomputed locally; a worker supplies only rows.
    for job in missing:
        current()
        row = by_id[str(job['id'])]
        if not _valid(row, job):
            continue
        save_worker_checkpoint(dict(root=str(root), key=keys[str(job['id'])],
                                    identity=materials[str(job['id'])]), row, meta)
    rows = {**reused, **by_id}
    windows={str(job['id']):materials[str(job['id'])]['audio_sha256'] for job in jobs}
    return dict(payload, results=[copy.deepcopy(rows[str(job['id'])]) for job in jobs],
                audio_sha256=None if preparation is not None else pcm_digest(audio, check=current),
                audio_clock_identity=preparation.clock_identity if preparation is not None else None,
                window_hashes=windows,
                checkpoint_hits=len(reused), checkpoint_jobs=len(jobs))
