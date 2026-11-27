"""Haas workshop preparation, using the common repository downloader."""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path

from ..recognition.haas_backend import Configuration, SAMPLE_RATE, VARIANTS, runtime_executable
from ..runtime_paths import get_runtime_paths


def _receipt(config):
    return get_runtime_paths().user_data_root / 'model-readiness' / f'{config.model_key}-{config.device}.json'


def _model_path(config):
    return get_runtime_paths().model_root / f'Haas-ja-v1.0-{config.quantization}' / config.model_name


def _identity(config):
    from .haas_runtime import runtime_files

    runtime = runtime_executable(config.device)
    if runtime is None:
        raise FileNotFoundError('CrispASR 尚未配备。')
    stamps = {}
    for path in [*_runtime_paths(runtime, runtime_files(config.device)), _model_path(config)]:
        stat = path.stat()
        stamps[str(path)] = [stat.st_size, stat.st_mtime_ns]
    return stamps


def _runtime_paths(executable, files):
    return (executable.with_name(name) for name in files)


def readiness(config):
    from .haas_runtime import runtime_files

    runtime = runtime_executable(config.device)
    if not runtime or not all(path.is_file() for path in _runtime_paths(runtime, runtime_files(config.device))):
        return 'runtime_missing'
    try:
        record = json.loads(_receipt(config).read_text('utf8'))
        if record.get('inference_verified') is True and record.get('identity') == _identity(config):
            return 'installed'
        if record.get('status') == 'FAIL' and record.get('identity') == _identity(config):
            return 'load_failed'
    except (OSError, ValueError):
        pass
    return 'inference_pending'


def _phase(phase, **details):
    print('[2BYTEASR_PHASE] ' + json.dumps(dict(phase=phase, **details), ensure_ascii=False), flush=True)


def _sample(config, root):
    import numpy as np

    from ..recognition.haas_backend import transcribe
    from ..recognition.run_context import RuntimeContext, activate_runtime_context

    with wave.open(str(root / 'assets/diagnostics/speech_ja.wav'), 'rb') as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise ValueError('Haas 自检音频格式不正确。')
        pcm = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
    settings = {'models': {'haas_quantization': config.quantization, 'haas_device': config.device}}
    context = RuntimeContext(asr_settings_snapshot=settings, requested_language='ja', task_language='ja')
    with activate_runtime_context(context):
        rows = transcribe(pcm, [{'start': 0., 'end': len(pcm) / SAMPLE_RATE}], context)
    text = ''.join(row['text'] for row in rows)
    if not any(word in text for word in ('モルドバ', 'キリスト教')):
        raise RuntimeError('Haas 真实日语样本的输出没有通过检查。')
    return len(rows)


def _prepare(config, source, verify_only, import_path=None):
    from .haas_runtime import prepare
    from ..model_integrity import ModelIntegrityError, locked_model, sha256_file, verify_model_files
    from ..recognition.cache import atomic_write_json
    from ..repository_download import download_model, preparation_lock, require_isolated_download_path

    paths = get_runtime_paths()
    destination = _model_path(config).parent
    staging = paths.model_root / '.downloads'
    receipt = _receipt(config)
    for path in (destination, staging, receipt, paths.managed_runtime_root):
        require_isolated_download_path(path)
    spec = locked_model(config.model_key, root=paths.install_root)
    with preparation_lock(staging / config.model_key / '.haas.lock'):
        try:
            _phase('files_verifying', model=config.model_key)
            try:
                verify_model_files(config.model_key, destination, root=paths.install_root)
                if (destination / '.2byteasr-install-pending.json').exists():
                    raise ModelIntegrityError('Haas 权重的安装尚未完成。')
            except ModelIntegrityError:
                if verify_only:
                    raise
                required = spec['download_bytes']
                if shutil.disk_usage(paths.model_root).free < required:
                    raise RuntimeError(f'磁盘空间不足，Haas 权重需要 {required:,} 字节。')
                if import_path is None:
                    _phase('weights_downloading', model=config.model_key)
                    download_model(model_key=config.model_key, spec=spec, destination=destination,
                                   mode=source, staging_root=staging)
                else:
                    _import_weights(import_path, destination, config.model_name, spec, sha256_file)
            _phase('runtime_installing', model=config.model_key, device=config.device)
            prepare(config.device)
            identity = _identity(config)
            _phase('model_loading', model=config.model_key, device=config.device)
            count = _sample(config, paths.install_root)
            if identity != _identity(config):
                raise RuntimeError('Haas 权重或运行库在验证期间发生变化，请重新验证。')
            receipt.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(str(receipt), dict(status='PASS', model=config.model_key, device=config.device,
                                                 inference_verified=True, identity=identity, segments=count))
            _phase('ready', model=config.model_key, device=config.device, real_inference=True, segments=count)
        except Exception as exc:
            try:
                identity = _identity(config)
            except OSError:
                receipt.unlink(missing_ok=True)
            else:
                receipt.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(str(receipt), dict(status='FAIL', inference_verified=False,
                                                     identity=identity, message=str(exc)))
            raise


def _import_weights(source, destination, name, spec, sha256_file):
    if source.stat().st_size != spec['download_bytes']:
        raise ValueError('离线权重大小与当前量化版本不符。')
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.haas-import-', dir=destination) as temp:
        copied = Path(temp) / name
        shutil.copyfile(source, copied)
        if sha256_file(copied) != spec['sha256'][name]:
            raise ValueError('离线权重与固定版本的 SHA-256 不符。')
        os.replace(copied, destination / name)
        (destination / '.2byteasr-install-pending.json').unlink(missing_ok=True)


def bind_worker_output():
    for name, handle in (('stdout', -11), ('stderr', -12)):
        stream = getattr(sys, name)
        if stream is None and sys.platform == 'win32':
            from ..app.browser_native_host import _std_binary
            try:
                binary = _std_binary(handle, 'wb', None)
            except OSError:
                binary = open(os.devnull, 'wb')
            stream = io.TextIOWrapper(binary, encoding='utf-8', write_through=True)
            setattr(sys, name, stream)
        elif hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def main(argv):
    bind_worker_output()
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=VARIANTS.values(), required=True)
    parser.add_argument('--source', choices=('AUTO', 'HF_OFFICIAL', 'HF_MIRROR', 'MODELSCOPE'), default='AUTO')
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--import-file', type=Path)
    args = parser.parse_args(argv)
    if args.verify and args.import_file:
        parser.error('--verify and --import-file cannot be combined')
    config = Configuration(next(variant for variant, key in VARIANTS.items() if key == args.model), args.device)
    if not getattr(sys, 'frozen', False):
        os.environ['TWOBYTEASR_DOWNLOAD_PYTHON'] = sys.executable
    try:
        _phase('preparing', model=args.model)
        _prepare(config, args.source, args.verify, args.import_file)
    except Exception as exc:
        print('[2BYTEASR_INSTALL_ERROR] ' + json.dumps(dict(message=str(exc)), ensure_ascii=False), flush=True)
        return 1
    return 0
