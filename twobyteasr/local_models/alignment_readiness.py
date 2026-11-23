"""Read-only alignment readiness over the existing registry and real receipts.

Called by the shared registry reader. No weights, Torch or inference enter GUI.
"""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

KEYS = ('qwen_aligner', 'qwen_official', 'qwen_ultra_head', 'mfa_aligner')


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
        if key == 'qwen_ultra_aligner':
            directory = backend.model_directory(key)
        elif key == 'qwen_ultra_head':
            directory = backend.head_directory()
        else:
            directory = next((p for p in iter_model_dir_candidates(folder)
                              if all((Path(p)/n).is_file() for n in spec['required_files'])), None)
        directory = Path(directory) if directory else None
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


QWEN_LABELS = {
    'qwen_aligner': 'Qwen3 对齐（官方兼容版）',
    'qwen_ultra_aligner': 'Qwen3 对齐 · Ultra',
    'qwen_ultra_head': 'Qwen3 对齐 · Ultra Local Head',
}


def qwen_status(backend_name, *, registry=None, verify=False, directory=None):
    """Inspect the exact worker route without loading a model into this interpreter."""
    from ..model_integrity import load_dependency_lock, verify_model_files
    from ..recognition import alignment_backend as backend
    from ..recognition.asr import _main_worker_python

    ultra = backend_name in backend.ULTRA_ALIGNERS
    weight = 'qwen_ultra_aligner' if ultra else 'qwen_aligner'
    override = '2BYTEASR_QWEN3_ULTRA_ALIGNER_DIR' if ultra else '2BYTEASR_QWEN3_ALIGNER_DIR'
    directory = (backend.model_directory(backend_name) if directory is None else directory)
    label = QWEN_LABELS[backend_name]
    record = dict(state='missing', ready=False, files_ready=False, runtime='',
                  model=backend_name, directory=str(directory or ''), label=label, receipt_status='')

    def status(state, reason='', **fields):
        return dict(record, state=state, reason=reason, ready=state == 'installed', **fields)

    if not directory:
        if os.environ.get(override, '').strip():
            return status('path_mismatch', f'自定义路径 {override} 中找不到对应的 config.json')
        other = 'qwen_aligner' if ultra else 'qwen_ultra_aligner'
        if backend.model_directory(other):
            return status('path_mismatch', f'任务需要 {label}，当前只找到 {QWEN_LABELS[other]} 的目录')
        return status('missing', '缺少模型文件')

    lock = load_dependency_lock()['models']
    required = {weight: directory}
    if backend_name == 'qwen_ultra_head':
        head = backend.head_directory()
        if not head:
            if os.environ.get('2BYTEASR_QWEN3_ULTRA_HEAD_DIR', '').strip():
                return status('path_mismatch', '自定义 Local Head 路径中找不到配置')
            return status('partial', '缺少 Ultra Local Head 文件')
        required[backend_name] = head
    try:
        for key, location in required.items():
            file_identity(location, lock[key]['required_files'])
            row = registry.record(key) if registry is not None else None
            if row and Path(row.installation_path).resolve() == Path(location).resolve():
                if row.health.value in {'PARTIAL', 'CORRUPT'}:
                    return status('partial', '模型文件不完整或校验不符')
            if verify:
                verify_model_files(key, location)
    except (OSError, RuntimeError, ValueError) as exc:
        return status('partial', str(exc).splitlines()[0])
    record['files_ready'] = True

    try:
        python = _main_worker_python()
        record['runtime'] = python
        packages = runtime_identity(python)['packages']
        missing = {'qwen-asr', 'torch', 'transformers', 'numpy', 'safetensors', 'nagisa'} - packages.keys()
        if missing:
            return status('runtime_missing', '对齐运行环境缺少依赖：' + ', '.join(sorted(missing)))
        if packages.get('qwen-asr') != '0.0.6':
            return status('runtime_missing', '对齐运行库版本不匹配，需要配置环境')
    except (OSError, RuntimeError, ValueError) as exc:
        return status('runtime_missing', str(exc))
    if not ultra:
        # The official compatibility route predates Ultra inference receipts.
        return status('installed', verification='official_files_and_runtime')

    receipt = _read_receipt(backend_name)
    record['receipt_status'] = str(receipt.get('status') or '')
    if record['receipt_status'] in {'FAIL', 'BLOCKED'}:
        return status('load_failed', _failure(receipt))
    try:
        valid = backend.readiness_matches(backend_name, receipt) and runtime_matches(receipt, python)
        if valid:
            spec = backend.profile('qwen_ultra_aligner')
            if backend_name != 'qwen_ultra_head':
                valid = (str(Path(directory).resolve()) == receipt.get('ultra_directory')
                         and file_identity(directory, spec['files']) == receipt.get('ultra_file_stats'))
            observed = receipt.get('availability_identity')
            if valid and (observed or backend_name == 'qwen_ultra_head'):
                expected = validation_identity(backend_name, getattr(registry, 'install_root', None))
                if isinstance(expected.get('policy', {}).get('compatibility'), dict):
                    expected['policy']['compatibility']['available'] = (observed or {}).get('policy', {}).get('compatibility', {}).get('available')
                valid = observed == expected
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        valid = False
    if valid:
        return status('installed', verification='matching_actual_inference_receipt')
    return status('inference_pending', '文件与环境已准备，需验证当前模型及运行环境')


def inspect(registry, *, keys=None):
    from ..recognition import mfa_aligner
    snapshots = {}
    routes = {'qwen_aligner': 'qwen_ultra_aligner', 'qwen_official': 'qwen_aligner',
              'qwen_ultra_head': 'qwen_ultra_head'}
    for key, route in routes.items():
        if keys is None or key in keys:
            snapshots[key] = qwen_status(route, registry=registry)
    if keys is not None and 'mfa_aligner' not in keys:
        return snapshots

    key = 'mfa_aligner'
    record = dict(state='checking', reason='', ready=False, files_ready=False,
                  runtime='', receipt_status='', model=key)
    try:
        files = [registry.record(k) for k in (key, 'mfa_aligner_ja')]
        if any(f is None or f.health.value == 'MISSING' for f in files):
            record.update(state='missing', reason='缺少模型文件')
        elif any(f.health.value in {'PARTIAL', 'CORRUPT'} for f in files):
            record.update(state='partial', reason='模型文件不完整或校验不符')
        elif any(f.health.value != 'INSTALLED' for f in files):
            record.update(state='unreadable', reason='模型文件无法读取')
        else:
            record['files_ready'] = True
            python = mfa_aligner.runtime_python()
            if not python or not Path(python).is_file():
                raise OSError('MFA 独立环境缺失或尚未完成')
            record['runtime'] = str(python)
            receipt = _read_receipt(key)
            record['receipt_status'] = str(receipt.get('status') or '')
            if record['receipt_status'] in {'FAIL', 'BLOCKED'}:
                record.update(state='load_failed', reason=_failure(receipt))
            else:
                valid = bool(receipt.get('inference_verified') and
                             receipt.get('availability_identity') == validation_identity(key, registry.install_root))
                record.update(state='installed' if valid else 'inference_pending', ready=valid,
                              reason='' if valid else 'MFA 独立环境已准备，尚无匹配的可用性验证')
                if valid:
                    record['verification'] = 'matching_actual_inference_receipt'
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        record.update(state='runtime_missing' if record['files_ready'] else 'partial', reason=str(exc)[:180])
    snapshots[key] = record
    return snapshots


def effective_snapshot(registry, key, settings=None, *, base_only=False, resolve_official=False):
    """One effective view for cards, selectors and selection commit."""
    snapshots = getattr(registry, 'alignment_readiness', {}) or {}
    from .model_state_events import active_task
    from ..recognition.alignment_backend import selected_backend
    from ..recognition.qwen_family import head_requested
    official = (resolve_official and key == 'qwen_aligner' and not base_only
                and selected_backend(settings) == 'qwen_aligner')
    view = 'qwen_official' if official else key
    value = dict(snapshots.get(view) or dict(state='checking', ready=False, reason='状态检查中'))
    physical = 'qwen_ultra_aligner' if key == 'qwen_aligner' and not official else key
    task = active_task(physical)
    wants_head = key == 'qwen_aligner' and not official and not base_only and head_requested(settings)
    if wants_head and task is None:task = active_task('qwen_ultra_head')
    if task is not None:
        value.update(state='checking' if task.get('operation')=='check' else 'downloading',ready=False,task=task)
    elif wants_head and value.get('ready') and not snapshots.get('qwen_ultra_head',{}).get('ready'):
        value.update(state='experiment_unready',ready=False,base_ready=True,reason='基础可用，实验精修尚无匹配的可用性验证')
    return value


def qwen_task_snapshot(registry, models, timeline):
    """Cheap UI view of the effective route from the pending task snapshot."""
    from ..recognition.alignment_backend import TORCH_ALIGNERS
    if timeline not in TORCH_ALIGNERS:
        return None
    settings = {'models': dict(models, firered_asr_backend=timeline)}
    return effective_snapshot(registry, 'qwen_aligner', settings, resolve_official=True)
