"""Pinned Qwen alignment profiles shared by every entry point (no torch import)."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

TORCH_ALIGNERS = frozenset({'qwen_aligner', 'qwen_ultra_aligner', 'qwen_ultra_head'})
ULTRA_ALIGNERS = frozenset({'qwen_ultra_aligner', 'qwen_ultra_head'})
IMPLEMENTATION = 'twobyte-qwen-slots-v5-parent'
POSTPROCESS = 'official-fix-once+sentence-granularity-v5-independent-points-context'
SPAN_MAPPING = 'nfkc-grapheme-original-spans-v1'
COMPANION_VERSION = '0.1.1'
COMPANION_WHEEL = 'companion/dist/qwen_fa_ultra-0.1.1-py3-none-any.whl'


def selected_backend(settings=None):
    if settings is None:
        from .run_context import get_runtime_context
        settings = get_runtime_context().asr_settings_snapshot
    backend = str(((settings or {}).get('models') or {}).get('firered_asr_backend', 'qwen_aligner'))
    backend=backend if backend in TORCH_ALIGNERS else 'qwen_aligner'
    if backend=='qwen_aligner' and ((settings or {}).get('models') or {}).get('qwen_alignment_profile')=='ultra-v5':
        from .qwen_family import head_requested
        return 'qwen_ultra_head' if head_requested(settings) else 'qwen_ultra_aligner'
    return backend


def profile(backend=None):
    from ..model_integrity import load_dependency_lock
    from ..forced_alignment import ALIGNER_CODE, UNIT_POLICY_VERSION
    backend = backend or selected_backend()
    if backend not in TORCH_ALIGNERS:
        raise ValueError(f'Unknown Qwen alignment profile: {backend}')
    lock = load_dependency_lock()
    key = 'qwen_ultra_aligner' if backend in ULTRA_ALIGNERS else 'qwen_aligner'
    spec = lock['models'][key]
    head = lock['models']['qwen_ultra_head'] if backend == 'qwen_ultra_head' else None
    compatibility=(dict(policy='explicit-parent-ownership-conflict-only-v1',model_key='qwen_aligner',
        repository=lock['models']['qwen_aligner']['repository'],revision=lock['models']['qwen_aligner']['revision'],
        files=lock['models']['qwen_aligner']['sha256'],available=bool(official_compat_directory())) if backend=='qwen_ultra_aligner' else None)
    return dict(compatibility=compatibility,backend=backend, model_key=key, model=spec['repository'],
                model_revision=spec['revision'], files=spec['sha256'], code=ALIGNER_CODE,
                implementation=IMPLEMENTATION, runtime='qwen-asr==0.0.6',
                unit_policy=UNIT_POLICY_VERSION, span_mapping=SPAN_MAPPING,
                tokenizers={'Japanese': 'nagisa==0.2.11', 'Korean': 'soynlp', 'other': 'space_lang'},
                local_head=(dict(version=COMPANION_VERSION, revision=head['revision'],
                                 files=head['sha256'], policy='fixed-center+same-pass-slots-v1',
                                 selection='all-endpoints', device='cpu', dtype='float32', fallback='window-base-on-invalid-v1') if head else None),
                postprocess=POSTPROCESS, timestamp_grid_ms=80, storage_unit='milliseconds',
                audio=dict(input_policy='unit-peak-f64-to-f32+owned-padding80+verified-parent-or-context-v3' if backend=='qwen_ultra_aligner' else 'preserve',
                           audio_feature_reuse='exact-input-eval-request-pair-v1' if backend!='qwen_ultra_head' else 'off',inferred_zero_trimming=False,context_batching='bounded-independent-items-v1',source_context_retry_ms=1000 if backend=='qwen_ultra_aligner' else 0,sample_rate=16000, format='float32-mono-npy-v1',
                           resampling='task-pcm-owned-v1', padding_ms=300,
                           chunks='asr-speaker-vad-anchors-v1', timebase='task-pcm-window-offset-once-v1'))


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


@lru_cache(maxsize=8)
def _gpu_identity(visible):
    try:
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        result = subprocess.run(['nvidia-smi', '--query-gpu=uuid,driver_version', '--format=csv,noheader'],
                                capture_output=True, text=True, timeout=3, **options)
        return result.stdout.strip() if result.returncode == 0 else 'unavailable'
    except (OSError, subprocess.TimeoutExpired):
        return 'unavailable'


@lru_cache(maxsize=32)
def _execution_probe(python, runtime_stamp, requested, gpu, task_id):
    # A short owned child answers device/precision; torch never enters the GUI.
    program = """import json,torch
available=torch.cuda.is_available()
device='cuda:0' if available and REQUEST!='cpu' else 'cpu'
dtype=str(torch.bfloat16 if device.startswith('cuda') and torch.cuda.is_bf16_supported() else torch.float16 if device.startswith('cuda') else torch.float32)
print(json.dumps(dict(device=device,dtype=dtype,torch_version=torch.__version__,cuda_available=available)))
""".replace('REQUEST', repr(requested))
    from ..system.processes import popen_hidden_subprocess, python_utf8_command, stop_process_tree
    from .run_context import get_runtime_context
    from .asr import _raise_if_queue_cancelled
    from .cache import record_run_event
    import time
    context=get_runtime_context()
    process=popen_hidden_subprocess(python_utf8_command([str(python),'-I','-c',program]),
        purpose='alignment device/precision probe',own_process_tree=True,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',errors='replace')
    deadline=time.monotonic()+60
    succeeded=False
    try:
        record_run_event('alignment_progress',engine='QWEN3-ALIGNER',worker_pid=process.pid,
                         worker_state='runtime_check',label='检查对齐运行库与设备')
        while True:
            _raise_if_queue_cancelled()
            if time.monotonic()>deadline:
                raise TimeoutError('对齐运行库设备检查超过安全时限')
            try:
                output,error=process.communicate(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError('对齐运行库设备检查失败：'+error[-500:])
        result=json.loads(output.strip().splitlines()[-1])
        succeeded=True
        return result
    finally:
        job=getattr(process,'_request_job',None)
        if job is not None:
            job.close(timeout=3)
            process.wait(timeout=3)
        elif process.poll() is None:
            stop_process_tree(process)
        record_run_event('alignment_progress',engine='QWEN3-ALIGNER',worker_pid=process.pid,
                         worker_state='completed' if succeeded else 'failed',label='运行库设备检查')


def runtime_identity(python):
    """Read distribution metadata in the worker environment without importing it."""
    from ..python_runtime_identity import python_entry_path
    executable = Path(python_entry_path(python))
    env_root = executable.parent.parent if executable.parent.name.lower() in {'scripts', 'bin'} else executable.parent
    sites = [env_root / 'Lib/site-packages', *env_root.glob('lib/python*/site-packages')]
    packages = {'qwen-asr', 'torch', 'transformers', 'nagisa', 'soynlp', 'numpy', 'safetensors'}
    versions = {}
    for dist in importlib.metadata.distributions(path=[str(path) for path in sites if path.is_dir()]):
        name = str(dist.metadata.get('Name', '')).lower().replace('_', '-')
        if name in packages:
            versions[name] = dist.version
    stat = executable.stat()
    requested = os.environ.get('TWOBYTEASR_ALIGNER_DEVICE', 'auto')
    gpu = _gpu_identity(os.environ.get('CUDA_VISIBLE_DEVICES')) if requested != 'cpu' else None
    loaded_torch = sys.modules.get('torch')
    if loaded_torch is not None and os.path.normcase(str(executable)) == os.path.normcase(sys.executable):
        available = loaded_torch.cuda.is_available()
        device = 'cuda:0' if available and requested != 'cpu' else 'cpu'
        dtype = (loaded_torch.bfloat16 if device.startswith('cuda') and loaded_torch.cuda.is_bf16_supported()
                 else loaded_torch.float16 if device.startswith('cuda') else loaded_torch.float32)
        resolved = dict(device=device, dtype=str(dtype), torch_version=loaded_torch.__version__, cuda_available=available)
    else:
        from .run_context import get_runtime_context
        resolved = _execution_probe(str(executable), fingerprint(versions), requested, gpu, get_runtime_context().job_id)
    return dict(python=str(executable), resolved_binary=str(executable.resolve()), python_size=stat.st_size, python_mtime_ns=stat.st_mtime_ns,
                resolved_execution=resolved, packages=versions, platform=platform.system(), machine=platform.machine(),
                requested_device=requested, precision='cpu-float32/cuda-bfloat16-or-float16-v1',
                cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'),
                gpu=gpu)


def request_identity(backend, python, *, passes=('word', 'char'), batch_size=8):
    return dict(profile(backend), execution=runtime_identity(python), passes=list(passes),
                batch_size=max(1, min(16, int(batch_size))), batching='length-bucket-oom-bisect-v1')


def receipt_matches(payload, expected=None, *, allow_legacy=False):
    expected = expected or profile()
    if not isinstance(payload, dict):
        return False
    if any(payload.get(key) != expected[key] for key in ('model', 'model_revision', 'code', 'unit_policy')):
        return False
    identity = payload.get('alignment_identity')
    if identity is None:
        # Historical official receipts remain readable/reusable ONLY as the exact
        # old official profile. They can never qualify an Ultra/head result.
        return allow_legacy and expected['backend'] == 'qwen_aligner'
    return all(identity.get(key) == value for key, value in expected.items()) if isinstance(identity, dict) else False


def model_directory(backend=None):
    from ..runtime_paths import iter_model_dir_candidates
    backend = backend or selected_backend()
    ultra = backend in ULTRA_ALIGNERS
    folder = 'Qwen3-ForcedAligner-Ultra' if ultra else 'Qwen3-ForcedAligner-0.6B'
    override = os.environ.get('2BYTEASR_QWEN3_ULTRA_ALIGNER_DIR' if ultra else '2BYTEASR_QWEN3_ALIGNER_DIR', '').strip()
    candidates = ([Path(override).expanduser()] if override else []) + list(iter_model_dir_candidates(folder))
    return next((str(path) for path in candidates if (path / 'config.json').is_file()), '')


def head_directory():
    from ..runtime_paths import iter_model_dir_candidates
    override = os.environ.get('2BYTEASR_QWEN3_ULTRA_HEAD_DIR', '').strip()
    candidates = ([Path(override).expanduser()] if override else []) + list(iter_model_dir_candidates('Qwen3-ForcedAligner-Ultra-LocalHead'))
    return next((str(path) for path in candidates if (path / 'local_head/config.json').is_file()), '')


def cache_identity(settings=None):
    from .asr import _main_worker_python
    backend = selected_backend(settings)
    try:
        return request_identity(backend, _main_worker_python())
    except (OSError, RuntimeError) as exc:
        if type(exc).__name__=='CancelledError':
            raise
        return dict(profile(backend), runtime_unavailable=type(exc).__name__)


def readiness_matches(backend, readiness):
    if not isinstance(readiness,dict) or not readiness.get('inference_verified'):return False
    expected=profile('qwen_ultra_aligner' if backend=='qwen_aligner' else backend)
    observed=readiness.get('alignment_receipt') or {}
    # Base readiness does not depend on whether an optional old compatibility
    # bundle was present. Acoustic caches still compare the complete identity.
    actual=(observed.get('alignment_identity') or {}).get('compatibility')
    if expected.get('compatibility') and isinstance(actual,dict):
        expected['compatibility']=dict(expected['compatibility'],available=actual.get('available'))
    return receipt_matches(observed,expected)


def official_compat_directory():
    from ..runtime_paths import iter_model_dir_candidates
    override=os.environ.get('2BYTEASR_QWEN3_ALIGNER_DIR','').strip()
    candidates=([Path(override).expanduser()] if override else [])+list(iter_model_dir_candidates('Qwen3-ForcedAligner-0.6B'))
    return next((str(p) for p in candidates if (p/'config.json').is_file() and (p/'model.safetensors').is_file()),'')
