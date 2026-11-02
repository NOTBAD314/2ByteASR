"""Bounded PCM validation and shared, read-only audio for model workers."""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

BLOCK_SAMPLES = 8 * 1024 * 1024


def bounded_jobs(jobs):
    from .run_context import get_runtime_context
    bounds=get_runtime_context().shard_bounds
    if not bounds:return jobs
    left,right=round(bounds[0]*1000),round(bounds[1]*1000)
    return [dict(job,window_start_ms=max(left,int(job['window_start_ms'])),
                 window_end_ms=min(right,int(job['window_end_ms']))) for job in jobs]


def pcm_digest(audio, *, check=None):
    """Hash the exact float32 bytes without a waveform-sized bytes/bool copy."""
    import numpy as np
    pcm = np.ascontiguousarray(audio, dtype=np.float32)
    if pcm.ndim != 1:
        raise ValueError('对齐需要单声道 float32 PCM')
    digest = hashlib.sha256()
    for start in range(0, pcm.size, BLOCK_SAMPLES):
        if check:
            check()
        block = pcm[start:start + BLOCK_SAMPLES]
        if not np.isfinite(block).all():
            raise ValueError('对齐音频包含非有限值')
        digest.update(memoryview(block).cast('B'))
    return digest.hexdigest()


def prepare_audio(audio, temporary_dir, *, check=None, jobs=None):
    """Return a declared NPY input; full read-only memmaps need no rewrite.

    A slice, writable array, altered file or non-native dtype never borrows
    the full-file identity. Cached digests live only in the owning task.
    """
    import numpy as np
    from .run_context import get_runtime_context
    started = time.perf_counter()
    pcm = np.ascontiguousarray(audio, dtype=np.float32)
    borrowed, key = None, None
    if isinstance(audio, np.memmap) and not audio.flags.writeable and audio.dtype == np.dtype('float32'):
        try:
            path = Path(audio.filename).resolve()
            stat = path.stat()
            header = np.load(path, mmap_mode='r', allow_pickle=False)
            try:
                root = audio
                while isinstance(getattr(root, 'base', None), np.ndarray):
                    root = root.base
                if (pcm.ndim == 1 and header.dtype == pcm.dtype and header.shape == pcm.shape
                        and root.shape == pcm.shape and root.dtype == pcm.dtype
                        and root.ctypes.data == pcm.ctypes.data and audio.offset == header.offset
                        and getattr(root, 'filename', None) == audio.filename):
                    borrowed = path
            finally:
                header._mmap.close()
            if borrowed:
                key = (str(path), stat.st_size, stat.st_mtime_ns, int(audio.offset), int(pcm.size))
        except (OSError, ValueError, AttributeError, TypeError):
            borrowed = None
    context = get_runtime_context()
    preparation=getattr(context,'streaming_preparation',None)
    if preparation is not None and preparation.owns(audio) and jobs:
        preparation.wait_ready(max(int(job['window_end_ms'])*16 for job in jobs))
        valid=preparation.valid_samples
        windows={str(job['id']):pcm_digest(pcm[max(0,int(job['window_start_ms'])*16):
            min(valid,int(job['window_end_ms'])*16)],check=check) for job in jobs}
        if borrowed is None:
            raise ValueError('流式对齐只接受已发布前缀的只读NPY映射。')
        return dict(path=str(borrowed),samples=int(pcm.size),sha256=None,
            valid_samples=valid,audio_clock_identity=preparation.clock_identity,window_hashes=windows)
    lock = context.media_identity_lock
    with lock:
        saved = context.alignment_audio_inputs.get(key) if key is not None else None
        digest = saved or pcm_digest(pcm, check=check)
        if key is not None:
            context.alignment_audio_inputs[key] = digest
    if borrowed is None:
        borrowed = Path(temporary_dir) / 'audio.npy'
        np.save(borrowed, pcm, allow_pickle=False)
    from .cache import record_run_event
    record_run_event('alignment_audio_prepared', samples=int(pcm.size), borrowed=key is not None,
                     digest_reused=bool(saved), elapsed_seconds=round(time.perf_counter() - started, 6))
    return {'path': os.fspath(borrowed), 'samples': int(pcm.size), 'sha256': digest}
