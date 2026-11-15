"""Read-only alignment readiness over the existing registry and real receipts.

Called by the shared registry reader. No weights, Torch or inference enter GUI.
"""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

KEYS = ('qwen_aligner', 'qwen_ultra_head', 'mfa_aligner')


def _stamp(path):
    path = Path(path)
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns]


def file_identity(directory, required):
    return {name: _stamp(Path(directory) / name) for name in required}


def runtime_identity(python, *, mfa=False):
    """Metadata only; never import a runtime's packages into this interpreter."""
    executable = Path(python)
    prefix = executable.parent.parent if executable.parent.name.lower() in {'scripts', 'bin'} else executable.parent
    sites = [prefix / 'Lib/site-packages', *prefix.glob('lib/python*/site-packages')]
    wanted = ({'montreal-forced-aligner', 'kalpy', 'pynini', 'sudachipy', 'spacy-pkuseg'} if mfa else
              {'qwen-asr', 'torch', 'transformers', 'nagisa', 'soynlp', 'numpy', 'safetensors'})
    versions = {}
    for dist in importlib.metadata.distributions(path=[str(p) for p in sites if p.is_dir()]):
        name = str(dist.metadata.get('Name', '')).lower().replace('_', '-')
        if name in wanted:
            versions[name] = dist.version
    result = dict(python=str(executable.resolve()), executable=_stamp(executable), packages=versions)
    if not mfa:
        critical = {}
        for site in sites:
            for name in ('c10.dll','torch_cpu.dll','torch_cuda.dll','libc10.so','libtorch_cpu.so'):
                p = site/'torch/lib'/name
                if p.is_file():critical[str(p)]=_stamp(p)
        result['native'] = critical
    if mfa:
        from ..recognition.mfa_aligner import RUNTIME_MARKER
        result['marker'] = _stamp(prefix / 'conda-meta' / RUNTIME_MARKER)
    return result


def runtime_matches(receipt, python):
    observed = (receipt.get('alignment_receipt') or {}).get('alignment_identity', {}).get('execution') or {}
    if not observed:
        return False
    actual = runtime_identity(python)
    checked_at = float(receipt.get('checked_at') or receipt.get('started') or 0)
    unchanged_native = not checked_at or all(stamp[1] <= checked_at*1e9 for stamp in actual.get('native',{}).values())
    return (unchanged_native and Path(observed.get('python', '')).resolve() == Path(actual['python'])
            and observed.get('python_size') == actual['executable'][0]
            and observed.get('python_mtime_ns') == actual['executable'][1]
            and observed.get('packages') == actual['packages'])


def validation_identity(model_key, root=None):
    """Only this model, its runtime/dependencies and its execution adapter."""
    from ..runtime_paths import get_runtime_paths, iter_model_dir_candidates, detect_install_root
    from ..model_integrity import load_dependency_lock
    from ..recognition import alignment_backend as backend
    root = Path(root or detect_install_root())
    lock = load_dependency_lock()['models']
    if model_key == 'qwen_aligner':model_key = 'qwen_ultra_aligner'
    keys = (['qwen_ultra_aligner', 'qwen_ultra_head'] if model_key == 'qwen_ultra_head' else
            ['mfa_aligner', 'mfa_aligner_ja'] if model_key == 'mfa_aligner' else [model_key])
    files = {}
    for key in keys:
        spec = lock[key]
        folder = Path(spec['path']).name
        directory = next((Path(p) for p in iter_model_dir_candidates(folder) if all((Path(p)/n).is_file() for n in spec['required_files'])), None)
        if directory is None:raise OSError('模型文件未完整准备：'+key)
        files[key] = dict(directory=str(directory.resolve()), revision=spec.get('revision'), expected=spec.get('sha256'), stats=file_identity(directory, spec['required_files']))
    if model_key == 'mfa_aligner':
        from ..recognition.mfa_aligner import runtime_python
        python = runtime_python()
        if not python:raise OSError('MFA 独立环境未准备完成')
        adapter_files = ['mfa_aligner_worker.py', 'twobyteasr/recognition/mfa_aligner.py']
        policy = 'mfa-aligner-units-v1'
    else:
        from ..recognition.asr import _main_worker_python
        python = _main_worker_python()
        adapter_files = ['qwen_aligner_worker.py', 'twobyteasr/forced_alignment.py', 'twobyteasr/recognition/alignment_measurements.py']
        if model_key == 'qwen_ultra_head':adapter_files.append('twobyteasr/recognition/ultra_local_head.py')
        policy = backend.profile('qwen_ultra_head' if model_key == 'qwen_ultra_head' else 'qwen_ultra_aligner')
    code = {}
    for relative in adapter_files:
        p = root / relative
        if not p.is_file():p = Path(__file__).resolve().parents[2] / relative
        code[relative] = hashlib.sha256(p.read_bytes()).hexdigest()
    sample=root/('assets/diagnostics/speech_zh.wav' if model_key=='mfa_aligner' else 'assets/diagnostics/speech_en.wav')
    return dict(version='alignment-readiness-v1', model=model_key, files=files, runtime=runtime_identity(python, mfa=model_key=='mfa_aligner'), adapter=code, policy=policy, sample_sha256=hashlib.sha256(sample.read_bytes()).hexdigest())


def _read_receipt(key):
    from ..runtime_paths import user_data_root
    try:
        value = json.loads((user_data_root()/'model-readiness'/(key+'.json')).read_text('utf8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):return {}


def _failure(receipt):
    message = str(receipt.get('message') or receipt.get('error') or '上次可用性验证未通过').strip().splitlines()
    return message[-1][:180] if message else '上次可用性验证未通过'


def inspect(registry, *, keys=None):
    from ..recognition import alignment_backend as backend
    from ..recognition.asr import _main_worker_python
    from ..recognition import mfa_aligner
    snapshots = {}
    for key, required in [('qwen_aligner', ('qwen_ultra_aligner',)), ('qwen_ultra_head', ('qwen_ultra_aligner','qwen_ultra_head')), ('mfa_aligner', ('mfa_aligner','mfa_aligner_ja'))]:
        if keys is not None and key not in keys:
            continue
        record = dict(state='checking', reason='', ready=False, files_ready=False, runtime='', receipt_status='', model=key)
        try:
            files = [registry.record(k) for k in required]
            if any(f is None or f.health.value == 'MISSING' for f in files):record.update(state='missing',reason='缺少模型文件')
            elif any(f.health.value in {'PARTIAL','CORRUPT'} for f in files):record.update(state='partial',reason='模型文件不完整或校验不符')
            elif any(f.health.value!='INSTALLED' for f in files):record.update(state='unreadable',reason='模型文件无法读取')
            else:
                record['files_ready'] = True
                python = mfa_aligner.runtime_python() if key=='mfa_aligner' else _main_worker_python()
                if not python or not Path(python).is_file():raise OSError('MFA 独立环境缺失或尚未完成' if key=='mfa_aligner' else '主运行环境未准备完成')
                record['runtime'] = str(python)
                if key != 'mfa_aligner':
                    packages=runtime_identity(python)['packages']
                    missing={'qwen-asr','torch','transformers','numpy','safetensors','nagisa'}-packages.keys()
                    if missing:raise OSError('对齐环境缺少组件：'+', '.join(sorted(missing)))
                    if packages.get('qwen-asr')!='0.0.6':raise OSError('对齐运行库版本不匹配，需要配置环境')
                receipt_key = 'qwen_ultra_aligner' if key=='qwen_aligner' else key
                receipt = _read_receipt(receipt_key);record['receipt_status'] = str(receipt.get('status') or '')
                if receipt.get('status') in {'FAIL','BLOCKED'}:
                    record.update(state='load_failed',reason=_failure(receipt))
                elif key == 'mfa_aligner':
                    valid = bool(receipt.get('inference_verified') and receipt.get('availability_identity') == validation_identity(receipt_key, registry.install_root))
                    record.update(state='installed' if valid else 'inference_pending',ready=valid,reason='' if valid else 'MFA 独立环境已准备，尚无匹配的可用性验证')
                else:
                    valid = backend.readiness_matches(key, receipt) and runtime_matches(receipt, python)
                    if valid:
                        spec = backend.profile('qwen_ultra_aligner')
                        directory = backend.model_directory('qwen_ultra_aligner')
                        if key=='qwen_aligner':
                            valid = (str(Path(directory).resolve()) == receipt.get('ultra_directory') and file_identity(directory, spec['files']) == receipt.get('ultra_file_stats'))
                            if valid and receipt.get('availability_identity'):
                                observed=receipt['availability_identity']
                                expected=validation_identity(receipt_key,registry.install_root)
                                # Optional old fallback installation does not affect base validation.
                                if isinstance(expected.get('policy',{}).get('compatibility'),dict):
                                    expected['policy']['compatibility']['available']=observed.get('policy',{}).get('compatibility',{}).get('available')
                                valid=observed==expected
                        else:
                            from ..model_integrity import verify_model_files
                            verify_model_files('qwen_ultra_head', Path(backend.head_directory()))
                            identity = receipt.get('availability_identity')
                            valid = bool(identity and identity == validation_identity(receipt_key, registry.install_root))
                    record.update(state='installed' if valid else 'inference_pending', ready=bool(valid),reason='' if valid else '文件与环境已准备，需验证当前身份的可用性')
                if record['ready']:record['verification']='matching_actual_inference_receipt'
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            record.update(state='runtime_missing' if record['files_ready'] else 'partial',reason=str(exc)[:180],ready=False)
        snapshots[key] = record
    return snapshots


def effective_snapshot(registry, key, settings=None, *, base_only=False):
    """One effective view for cards, selectors and selection commit."""
    snapshots = getattr(registry, 'alignment_readiness', {}) or {}
    value = dict(snapshots.get(key) or dict(state='checking', ready=False, reason='状态检查中'))
    from .model_state_events import active_task
    from ..recognition.qwen_family import head_requested
    physical = 'qwen_ultra_aligner' if key == 'qwen_aligner' else key
    task = active_task(physical)
    wants_head = key == 'qwen_aligner' and not base_only and head_requested(settings)
    if wants_head and task is None:task = active_task('qwen_ultra_head')
    if task is not None:
        value.update(state='checking' if task.get('operation')=='check' else 'downloading',ready=False,task=task)
    elif wants_head and value.get('ready') and not snapshots.get('qwen_ultra_head',{}).get('ready'):
        value.update(state='experiment_unready',ready=False,base_ready=True,reason='基础可用，实验精修尚无匹配的可用性验证')
    return value
