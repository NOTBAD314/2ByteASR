"""Apple Silicon local speech via the MLX runtime (2026-10-13).

Two backends, kept separate everywhere (cards, settings, receipts):

* ``mlx_qwen3_asr`` / ``mlx_qwen3_asr_1_7b`` — primary transcription with
  Qwen3-ASR 0.6B / 1.7B (mlx-community 8-bit). It recognizes each VAD speech
  window; it gives
  text per window, so window bounds are its only times (marked as such).
* ``mlx_qwen_aligner`` — timeline. Qwen3-ForcedAligner 0.6B (MLX 8-bit) aligns
  any transcript (local or cloud) with the same receipts as the PyTorch
  aligner. It is not a speech recognizer.

Both run in the ``mlx`` runtime (no PyTorch) through ``mlx_worker.py``. The
GUI process never imports mlx. Not yet verified on a real Mac by 2ByteASR.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Primary backend value (settings) -> locked model key. Two values instead of
# a separate variant setting keep the settings schema unchanged.
PRIMARY_BACKENDS = {'mlx_qwen3_asr': 'mlx_qwen3_asr_0_6b', 'mlx_qwen3_asr_1_7b': 'mlx_qwen3_asr_1_7b'}
TIMELINE_BACKEND = 'mlx_qwen_aligner'
ALIGNER_KEY = 'mlx_qwen_aligner'
FOLDERS = {'mlx_qwen3_asr_0_6b': 'Qwen3-ASR-0.6B-8bit', 'mlx_qwen3_asr_1_7b': 'Qwen3-ASR-1.7B-8bit',
           'mlx_qwen_aligner': 'Qwen3-ForcedAligner-0.6B-8bit'}
ASR_PROTOCOL = 'mlx-qwen3-asr-windows-v1'


class MlxUnavailableError(RuntimeError):
    """The MLX runtime or model is missing, or this is not an Apple Silicon Mac."""


def platform_supported() -> bool:
    import platform
    return sys.platform == 'darwin' and platform.machine().lower() in {'arm64', 'aarch64'}


def asr_key(backend: str) -> str:
    return PRIMARY_BACKENDS.get(str(backend or ''), PRIMARY_BACKENDS['mlx_qwen3_asr'])


def model_dir(key: str) -> Path | None:
    from .runtime_paths import resolve_model_dir
    folder = FOLDERS[key]
    candidate = resolve_model_dir(folder)
    if not candidate.is_dir() or (candidate / '.2byteasr-install-pending.json').exists():
        return None
    return candidate if (candidate / 'model.safetensors').is_file() else None


def runtime_python() -> str:
    from .runtime_registry import resolve_runtime_python
    try:
        python = resolve_runtime_python('mlx')
    except Exception:
        python = ''
    return python if python and os.path.isfile(python) else ''


def _worker_path() -> str:
    from .runtime_paths import detect_install_root
    root = detect_install_root()
    for candidate in (root / 'workers' / 'mlx_worker.py', root / 'mlx_worker.py'):
        if candidate.is_file():
            return str(candidate)
    raise MlxUnavailableError('MLX worker 脚本缺失')


def _run(mode: str, key: str, audio, jobs: list, policy: dict) -> dict:
    import numpy as np
    from .asr import _run_isolated_asr_worker
    if not platform_supported():
        raise MlxUnavailableError('MLX 只能在 Apple Silicon（M 系列芯片）的 Mac 上运行。')
    python = runtime_python()
    if not python:
        raise MlxUnavailableError('还没有准备 MLX 运行环境；请在模型工坊下载 MLX 模型（会同时准备运行环境）。')
    directory = model_dir(key)
    if directory is None:
        raise MlxUnavailableError(f'MLX 模型未安装：{FOLDERS[key]}。请在模型工坊下载。')
    pcm = np.ascontiguousarray(audio, dtype=np.float32)
    if pcm.ndim != 1 or not np.isfinite(pcm).all():
        raise RuntimeError('MLX worker 需要有限值单声道 float32 PCM')
    digest = hashlib.sha256(pcm.tobytes()).hexdigest()
    jobs = [dict(job, id=str(job['id'])) for job in jobs]
    with tempfile.TemporaryDirectory(prefix='mlx_worker_') as temp:
        audio_path = os.path.join(temp, 'audio.npy')
        np.save(audio_path, pcm, allow_pickle=False)
        manifest = os.path.join(temp, 'manifest.json')
        output = os.path.join(temp, 'results.json')
        Path(manifest).write_text(json.dumps({'policy': policy, 'jobs': jobs, 'model_key': key, 'audio': {
            'path': audio_path, 'samples': int(pcm.size), 'sha256': digest}}, ensure_ascii=False), encoding='utf-8')
        payload = _run_isolated_asr_worker(
            [python, '-I', _worker_path(), '--mode', mode, '--manifest', manifest, '--output', output,
             '--model-dir', str(directory)],
            output, model_id='MLX-' + mode.upper(), audio_input='shared_audio', model_path=str(directory),
            entrypoint='mlx_worker.py')
    results = payload.get('results') if isinstance(payload, dict) else None
    if not isinstance(results, list) or [str(r.get('id')) for r in results] != [job['id'] for job in jobs]:
        raise RuntimeError('MLX worker 返回的任务缺失、重复或乱序')
    if payload.get('policy') != policy or payload.get('audio_sha256') != digest:
        raise RuntimeError('MLX worker 回执与输入不一致')
    return payload


def run_aligner(audio, jobs, *, passes=('word', 'char'), batch_size=8) -> dict:
    """Same contract as ``asr.run_qwen_aligner_worker`` (receipts are interchangeable)."""
    from .asr import ALIGNER_PROTOCOL, AUDIO_SAMPLE_RATE
    policy = {'version': ALIGNER_PROTOCOL, 'audio_format': 'float32-mono-npy-v1', 'sample_rate': AUDIO_SAMPLE_RATE,
              'batch_size': max(1, min(16, int(batch_size))), 'passes': list(passes)}
    payload = _run('align', ALIGNER_KEY, audio, jobs, policy)
    if payload.get('protocol') != ALIGNER_PROTOCOL:
        raise RuntimeError('MLX 对齐回执协议不符')
    for job, row in zip(jobs, payload['results']):
        if row.get('text') != job['text']:
            raise RuntimeError('MLX 对齐 worker 改写了输入文字')
    return payload


def transcribe_reference(audio, speech_regions, *, backend='mlx_qwen3_asr', language=None) -> list:
    """Primary rows from MLX Qwen3-ASR, one per VAD speech window."""
    from .asr import build_qwen_asr_chunks
    from .cache import record_run_event
    key = asr_key(backend)
    chunks = build_qwen_asr_chunks(audio, speech_regions, 16000)
    jobs = [{'id': f'w{index:05d}', 'window_start_ms': int(round(chunk['start'] * 1000)),
             'window_end_ms': int(round(chunk['end'] * 1000)), 'language': language}
            for index, chunk in enumerate(chunks)]
    if not jobs:
        return []
    policy = {'version': ASR_PROTOCOL, 'audio_format': 'float32-mono-npy-v1', 'sample_rate': 16000,
              'max_tokens': 2048}
    payload = _run('asr', key, audio, jobs, policy)
    record_run_event('mlx_asr', model=key, device=(payload.get('device') or {}).get('default_device'),
                     metal=(payload.get('device') or {}).get('metal_available'), windows=len(jobs),
                     load_ms=payload.get('load_ms'), inference_ms=payload.get('inference_ms'))
    rows = []
    for job, row in zip(jobs, payload['results']):
        text = str(row.get('text') or '').strip()
        if not text:
            continue
        rows.append({'start': job['window_start_ms'] / 1000.0, 'end': job['window_end_ms'] / 1000.0, 'text': text,
                     'source': 'mlx-qwen3-asr-primary', 'timestamp_source': 'vad_window',
                     'timing_precision': 'window', 'confidence': 0.78})
    return rows
