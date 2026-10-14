# SPDX-License-Identifier: GPL-3.0-only
"""GUI-owned native CPU preparation; no system Python, shell or Homebrew.

Run as a dedicated child of the frozen app. Only a fully checked versioned
runtime is registered; cancelled/failed attempts retain their private cache
and never replace the previous working interpreter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import ssl
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlsplit


def emit(phase: str, **fields) -> None:
    print('[2BYTEASR_PHASE] ' + json.dumps(dict(phase=phase, **fields), ensure_ascii=False), flush=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def download_archive(spec: dict, cache: Path) -> Path:
    """A cached archive is reusable only after its exact upstream SHA matches."""
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / spec['sha256'] / spec['filename'] if spec.get('filename') else cache / (spec['sha256'] + '.tar.gz')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256(destination) == spec['sha256']:
        return destination
    pending = destination.with_suffix('.pending')
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    failures = []
    # Official URL first, then sources serving the identical file (2026-10-14,
    # mainland networks); each attempt must match the locked SHA-256.
    for url in _bootstrap_urls(spec['url']):
        try:
            _fetch(url, pending, context)
            emit('files_verifying', file=unquote(urlsplit(url).path.rsplit('/', 1)[-1]))
            if sha256(pending) != spec['sha256']:
                raise RuntimeError('SHA-256 mismatch for native bootstrap archive')
            os.replace(pending, destination)
            return destination
        except Exception as exc:
            failures.append(f'{urlsplit(url).hostname}: {exc}')
            print('[下载] ' + failures[-1] + '；换下一个来源', flush=True)
            pending.unlink(missing_ok=True)
    raise RuntimeError('Bootstrap archive could not be downloaded from any source: ' + '; '.join(failures))


def _bootstrap_urls(url: str) -> list:
    try:
        from twobyteasr.download_sources import bootstrap_urls
        return list(bootstrap_urls(url)) or [url]
    except (ImportError, AttributeError):
        return [url]


def _pip_index_urls() -> list:
    try:
        from twobyteasr.download_sources import pip_index_urls
        return list(pip_index_urls()) or ['https://pypi.org/simple']
    except (ImportError, AttributeError):
        return ['https://pypi.org/simple']


# A source slower than this for 60 s is abandoned for the next one (slow, not refused, is common).
LOW_SPEED_BYTES_PER_SECOND = 32 * 1024


def _fetch(url: str, pending: Path, context) -> None:
    request = urllib.request.Request(url, headers={'User-Agent': '2ByteASR-native-CPU-bootstrap/0.5.0'})
    with urllib.request.urlopen(request, context=context, timeout=15) as response, pending.open('wb') as output:
        total = int(response.headers.get('Content-Length') or 0)
        filename = unquote(urlsplit(url).path.rsplit('/', 1)[-1])
        print('[2BYTEASR_FILE] ' + json.dumps(dict(file=filename, size=total)), flush=True)
        downloaded = 0
        last = window_start = time.monotonic()
        window_bytes = 0
        for block in iter(lambda: response.read(1024 * 1024), b''):
            output.write(block)
            downloaded += len(block)
            window_bytes += len(block)
            now = time.monotonic()
            if now - window_start >= 60:
                if window_bytes / (now - window_start) < LOW_SPEED_BYTES_PER_SECOND:
                    raise TimeoutError('too slow (%.0f KB/s)' % (window_bytes / (now - window_start) / 1024))
                window_start, window_bytes = now, 0
            if now - last >= 1:
                print('[2BYTEASR_PROGRESS] ' + json.dumps(dict(downloaded=downloaded, total=total,
                      file=filename, percent=downloaded * 100 / total if total else 0)), flush=True)
                last = now


def run_hashed_pip_install(arguments, *, cwd: Path, environment: dict) -> None:
    """``pip install --require-hashes …`` against each index in turn (official PyPI first).

    Only for fully hash-pinned installs: a mirror can fail, never install other bytes.
    """
    assert '--require-hashes' in arguments
    indexes = _pip_index_urls()
    for position, index in enumerate(indexes):
        try:
            run([*arguments, '--index-url', index], cwd=cwd, environment=environment)
            return
        except subprocess.CalledProcessError:
            if position == len(indexes) - 1:
                raise
            print('[依赖] ' + str(urlsplit(index).hostname) + ' 安装没有完成，换下一个软件源（同样按哈希校验）', flush=True)


def extract_archive(archive: Path, destination: Path) -> None:
    """Reject traversal/special entries while retaining safe native symlinks."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, 'r:gz') as bundle:
        for member in bundle.getmembers():
            target = root / member.name
            if Path(member.name).is_absolute() or not target.resolve().is_relative_to(root):
                raise ValueError('Bootstrap archive path escapes its private directory')
            if member.ischr() or member.isblk() or member.isfifo():
                raise ValueError('Bootstrap archive contains a special device')
            if member.issym() or member.islnk():
                linked = target.parent / member.linkname if member.issym() else root / member.linkname
                if Path(member.linkname).is_absolute() or not linked.resolve().is_relative_to(root):
                    raise ValueError('Bootstrap archive link escapes its private directory')
        bundle.extractall(root)


def run(command, *, cwd: Path, environment: dict) -> None:
    # The workshop creates one POSIX process group. Every child inherits it,
    # so explicit cancellation also retires uv/download/model descendants.
    from twobyteasr.processes import external_python_environment
    env = external_python_environment(environment)
    process = subprocess.Popen([str(value) for value in command], cwd=cwd, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding='utf8', errors='replace')
    for line in process.stdout:
        print(line, end='', flush=True)
    code = process.wait()
    if code:
        raise subprocess.CalledProcessError(code, command)


def check_runtime(python: Path, root: Path, *, exact_python: str | None = None) -> bool:
    """Bounded native identity and real CPU/import probe; no model claim."""
    if not python.is_file():
        return False
    probe = (
        'import sys,platform,json,importlib.metadata as m; '
        'import torch,funasr; '
        'assert sys.platform=="darwin" and platform.machine()=="arm64"; '
        'assert sys.version_info[:2]==(3,10); '
        'assert not torch.version.cuda; '
        'assert torch.__version__.split("+")[0]=="2.11.0"; '
        'assert m.version("torchaudio").split("+")[0]=="2.11.0"; '
        'assert m.version("funasr")=="1.4.1"; '
        'assert (torch.ones(1,device="cpu")+1).item()==2; '
        'print(json.dumps(dict(python=platform.python_version(),machine=platform.machine(),device="cpu")))'
    )
    try:
        result = subprocess.run([str(python), '-I', '-c', probe], cwd=root, capture_output=True,
                                text=True, timeout=120, env=_child_environment())
        if result.returncode:
            return False
        if exact_python and json.loads(result.stdout.splitlines()[-1])['python'] != exact_python:
            return False
        native_lock = root / 'packaging/macos/native-dependencies.lock.json'
        proof = json.loads((python.parent.parent / 'mac-native-wheels.json').read_text('utf8'))
        if proof.get('lock_sha256') != sha256(native_lock):
            return False
        from scripts.macos_dependency_contract import verify_native_wheels
        verify_native_wheels(json.loads(Path(proof['install_report']).read_text('utf8')),
                             json.loads(native_lock.read_text('utf8')))
        from twobyteasr.environment import deep_preflight
        return bool(deep_preflight('main', interpreter=str(python), use_cache=False).ok)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
        return False


def _child_environment() -> dict:
    from twobyteasr.processes import external_python_environment
    environment = external_python_environment()
    environment.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', **{'2BYTEASR_CPU_ONLY': '1'})
    return environment


def _bootstrap_interpreter(managed: Path, lock: dict, environment: dict, *, python: str = 'python') -> tuple[Path, Path]:
    """Verified uv and CPython arm64 from the bootstrap lock (``python``: 3.10, ``python312``: MOSS)."""
    emit('tools_preparing')
    uv_root = managed / 'tools' / ('uv-' + lock['uv']['version'])
    # Re-extract from the verified cache before executing a tool;
    # an executable left by a failed attempt is not trusted alone.
    extract_archive(download_archive(lock['uv'], managed / 'bootstrap-cache'), uv_root)
    uv = uv_root / lock['uv']['member']
    uv.chmod(uv.stat().st_mode | 0o700)
    emit('interpreter_preparing')
    spec = lock[python]
    python_root = managed / 'python' / ('cpython-' + spec['version'] + '-arm64-' + spec['build'])
    extract_archive(download_archive(spec, managed / 'bootstrap-cache'), python_root)
    base = python_root / ('python/bin/python' + '.'.join(spec['version'].split('.')[:2]))
    if not base.is_file():
        raise RuntimeError('Verified Python archive has no native interpreter')
    run([base, '-I', '-c', 'import sys,platform; assert platform.machine()=="arm64"; assert platform.python_version()=="' + spec['version'] + '"'], cwd=managed, environment=environment)
    return uv, base


def ensure_main_runtime(root: Path, managed: Path, lock: dict, environment: dict, state: dict,
                        *, models=('sensevoice',)) -> Path:
    """The locked native main runtime (PyTorch, FunASR, FireRed and ECAPA dependencies).

    A registered or deterministic runtime that passes ``check_runtime`` is
    reused; otherwise it is built from the verified bootstrap and checked.
    The caller holds ``.macos-cpu-prepare.lock`` and owns registration.
    """
    from twobyteasr.runtime_registry import resolve_runtime_python
    requirements = root / 'packaging/macos/requirements-cpu.txt'
    identity = dict(target=lock['target'], python=lock['python'], uv=lock['uv'],
                    pip=lock['pip'], requirements={path.name: sha256(path) for path in (
                        requirements, root / 'packaging/macos/requirements-gui.txt',
                        root / 'packaging/macos/native-dependencies.lock.json')})
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    runtime = managed / 'main' / ('macos-cpu-' + signature)
    runtime_python = runtime / 'bin/python'
    receipt = runtime / 'managed-runtime.json'
    previous = resolve_runtime_python('main', register=False)
    # The deterministic locked runtime is an explicit recovery input
    # for legacy registry entries that stored only a base interpreter.
    if not (previous and check_runtime(Path(previous), root)) and check_runtime(runtime_python, root):
        previous = str(runtime_python)
    if previous and check_runtime(Path(previous), root):
        print('[运行库] 复用已核对的原生 CPU 环境', flush=True)
        return Path(previous)
    state['phase'] = 'tools_preparing'
    uv, base = _bootstrap_interpreter(managed, lock, environment)
    state['phase'] = 'dependencies_installing'
    emit(state['phase'])
    if not runtime_python.is_file():
        run([uv, '--no-config', '--system-certs', 'venv', '--no-project', '--python', base,
             '--no-python-downloads', runtime], cwd=managed, environment=environment)
    pip_wheel = download_archive(lock['pip'], managed / 'bootstrap-cache')
    run([uv, '--no-config', 'pip', 'install', '--python', runtime_python, pip_wheel], cwd=managed, environment=environment)
    report = runtime / 'pip-install.json'
    # Fresh reports include the critical wheels on retries too;
    # pip's verified cache can reuse completed downloads.
    run([runtime_python, '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install', '--force-reinstall', '--report', report,
         '--index-url', 'https://pypi.org/simple', '-r', requirements.name], cwd=requirements.parent, environment=environment)
    from scripts.macos_dependency_contract import verify_native_wheels
    native_lock = root / 'packaging/macos/native-dependencies.lock.json'
    verified = verify_native_wheels(json.loads(report.read_text('utf8')), json.loads(native_lock.read_text('utf8')))
    run([runtime_python, '-I', '-m', 'pip', '--isolated', 'check'], cwd=managed, environment=environment)
    proof = dict(native_wheels_verified=verified, lock_sha256=sha256(native_lock), install_report=str(report))
    proof_path = runtime / 'mac-native-wheels.json'
    pending_proof = proof_path.with_suffix('.pending')
    pending_proof.write_text(json.dumps(proof, indent=2), encoding='utf8')
    os.replace(pending_proof, proof_path)
    if not check_runtime(runtime_python, root, exact_python=lock['python']['version']):
        raise RuntimeError('Native CPU runtime probe failed; previous registration was preserved')
    payload = dict(identity, signature=signature, role='main', models=list(models),
                   runtime_ready=True, inference_verified=False, native_wheels_verified=verified, prepared_at=time.time())
    pending = receipt.with_suffix('.pending')
    pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(pending, receipt)
    return runtime_python


def prepare(root: Path, *, models: Path, source: str, register: bool = True) -> Path:
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('SenseVoice CPU preparation requires native Apple Silicon macOS')
    from twobyteasr.runtime_paths import user_data_root
    from twobyteasr.runtime_registry import register_runtime, resolve_runtime_python
    from twobyteasr.repository_download import preparation_lock
    managed = user_data_root() / 'runtimes'
    managed.mkdir(parents=True, exist_ok=True)
    lock = json.loads((root / 'packaging/macos/bootstrap.lock.json').read_text('utf8'))
    environment = _child_environment()
    environment['UV_CACHE_DIR'] = str(user_data_root() / 'cache/uv')
    state = {'phase': 'preparing'}
    try:
        with preparation_lock(managed / '.macos-cpu-prepare.lock'):
            state['phase'] = 'runtime_installing'
            emit(state['phase'], device='cpu', model='sensevoice')
            runtime_python = ensure_main_runtime(root, managed, lock, environment, state)
            environment['TWOBYTEASR_MAIN_PYTHON'] = str(runtime_python)
            environment['TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY'] = '1'
            from .python_runtime_identity import file_identity, save_identity
            from .runtime_paths import user_data_root
            diagnostics = user_data_root() / 'logs/python-runtime'
            save_identity('installation-selected', dict(python=file_identity(runtime_python),
                install_report=str(runtime_python.parent.parent/'pip-install.json'),
                install_report_sha256=sha256(runtime_python.parent.parent/'pip-install.json')), diagnostics)
            run([runtime_python, '-I', '-m', 'pip', '-V'], cwd=managed, environment=environment)
            # Reproduce the old resolver's entry->base transformation against
            # this actual installation, without importing/loading a model.
            base_probe = subprocess.run([str(runtime_python.resolve()), '-I', '-c',
                'import sys,json,importlib.util; s=importlib.util.find_spec("funasr"); '
                'print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,'
                'funasr_spec=s.origin if s else None)))'], cwd=managed, env=environment,
                capture_output=True, text=True, encoding='utf8', timeout=30)
            save_identity('old-resolver-counterfactual', dict(entry=str(runtime_python),
                resolved_target=str(runtime_python.resolve()),exit_code=base_probe.returncode,
                stdout=base_probe.stdout,stderr=base_probe.stderr), diagnostics)
            # The actual production entrypoint imports FunASR before weights
            # are downloaded. Success here is import readiness, not inference.
            run([runtime_python, '-I', root/'sensevoice_worker.py', '--probe-import',
                 '--expected-prefix', runtime_python.parent.parent, '--expected-funasr-version', '1.4.1',
                 '--diagnostics-dir', diagnostics], cwd=managed, environment=environment)
            state['phase'] = 'weights_downloading'
            emit(state['phase'], model='sensevoice')
            run([runtime_python, '-I', root / 'scripts/macos_prepare_model.py', '--models', models,
                 '--source', source], cwd=managed, environment=environment)
            state['phase'] = 'model_loading'
            emit(state['phase'], model='sensevoice', device='cpu')
            run([runtime_python, '-I', root / 'scripts/validate_prepared_model.py', '--root', root,
                 '--model', 'sensevoice'], cwd=managed, environment=environment)
            # Commit registration only after real model readiness succeeds;
            # failure preserves both valid weights and any older healthy role.
            if register:
                register_runtime('main', str(runtime_python), source='macos-gui-cpu-bootstrap')
            save_identity('registration-ready', dict(returned_python=str(runtime_python),
                registered_python=resolve_runtime_python('main') if register else None), diagnostics)
            emit('ready', model='sensevoice', device='cpu', model_inference_verified=True)
            return runtime_python
    except Exception as exc:
        category = 'permission' if isinstance(exc, PermissionError) else 'prepare_failed'
        print('[2BYTEASR_INSTALL_ERROR] ' + json.dumps(dict(phase=state['phase'], category=category,
              message=str(exc)), ensure_ascii=False), flush=True)
        raise


# MOSS-Transcribe-Diarize and FireRedASR2-AED on the Apple GPU (MPS), 2026-10-14.
# FireRed, FireRedVAD and the ECAPA speaker model run in the main runtime (as on
# Windows); MOSS needs its own Python 3.12 + transformers 5 runtime.
LOCAL_TORCH_KEYS = ('moss', 'firered_vad', 'speaker_embedding', 'firered_aed')
# Small models first, so a broken runtime shows before the long MOSS check.
_LOCAL_READINESS_ORDER = ('firered_vad', 'speaker_embedding', 'firered_aed', 'moss')
MOSS_SOURCE = Path('third_party/MOSS-Transcribe-Diarize/moss_transcribe_diarize')
MOSS_SITE_PACKAGES = Path('lib/python3.12/site-packages')


def _source_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob('*') if item.is_file()
                       and '__pycache__' not in item.parts and item.suffix not in {'.pyc', '.pyo'}):
        digest.update(path.relative_to(directory).as_posix().encode('utf8') + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def install_moss_source(root: Path, runtime: Path) -> str:
    """Copy the vendored pure-Python MOSS package into the runtime, replaced as a whole.

    Copying (not ``pip install``) keeps the hash-pinned install free of a
    source build and of the upstream demo's web-server dependencies.
    """
    import shutil
    source = root / MOSS_SOURCE
    if not (source / '__init__.py').is_file():
        raise RuntimeError('This build has no MOSS-Transcribe-Diarize source')
    expected = _source_digest(source)
    packages = runtime / MOSS_SITE_PACKAGES
    target = packages / 'moss_transcribe_diarize'
    stamp = packages / 'moss_transcribe_diarize.2byteasr.json'
    try:
        if target.is_dir() and json.loads(stamp.read_text('utf8')).get('sha256') == expected:
            return expected
    except (OSError, ValueError):
        pass
    packages.mkdir(parents=True, exist_ok=True)
    pending = packages / 'moss_transcribe_diarize.pending'
    retired = packages / 'moss_transcribe_diarize.retired'
    shutil.rmtree(pending, ignore_errors=True)
    shutil.copytree(source, pending, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    if _source_digest(pending) != expected:
        raise RuntimeError('MOSS source copy does not match the bundled files')
    shutil.rmtree(retired, ignore_errors=True)
    if target.exists():
        os.replace(target, retired)
    os.replace(pending, target)
    shutil.rmtree(retired, ignore_errors=True)
    stamp.write_text(json.dumps(dict(sha256=expected, source=MOSS_SOURCE.as_posix())), encoding='utf8')
    return expected


def check_moss_runtime(python: Path, root: Path) -> bool:
    """Import probe of the MOSS runtime (no model): versions, the vendored package, arm64."""
    if not python.is_file():
        return False
    probe = (
        # No speechbrain here: it needs torchaudio.list_audio_backends (gone in 2.11), which the
        # app patches before using it; moss_worker itself never imports it (2026-10-14 Mac run).
        'import sys,platform,json; import torch,torchaudio,transformers,librosa,av,soundfile; '
        'from moss_transcribe_diarize import parse_transcript; '
        'from moss_transcribe_diarize.inference_utils import build_transcription_messages; '
        'assert sys.platform=="darwin" and platform.machine()=="arm64"; '
        'assert sys.version_info[:2]==(3,12); '
        'assert torch.__version__.split("+")[0]=="2.11.0"; '
        'assert torchaudio.__version__.split("+")[0]=="2.11.0"; '
        'assert transformers.__version__=="5.14.1"; '
        'mps=getattr(torch.backends,"mps",None); '
        'print(json.dumps(dict(python=platform.python_version(),mps=bool(mps and mps.is_available()))))'
    )
    try:
        result = subprocess.run([str(python), '-I', '-c', probe], cwd=root, capture_output=True,
                                text=True, timeout=300, env=_child_environment())
        if result.returncode:
            print('[运行库] MOSS 运行库检查未通过：' + (result.stderr or result.stdout)[-600:], flush=True)
            return False
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        print('[运行库] MOSS 运行库：Python ' + payload['python'] + '，Apple GPU（MPS）'
              + ('可用' if payload['mps'] else '不可用，将用 CPU'), flush=True)
        return True
    except (OSError, ValueError, IndexError, KeyError, subprocess.TimeoutExpired):
        return False


def ensure_moss_runtime(root: Path, managed: Path, lock: dict, environment: dict, state: dict) -> Path:
    """Python 3.12 runtime for MOSS from hash-pinned wheels; the caller owns registration."""
    from twobyteasr.runtime_registry import resolve_runtime_python
    if 'python312' not in lock:
        raise RuntimeError('This build has no verified Python 3.12 for MOSS')
    requirements = root / 'packaging/macos/requirements-moss.txt'
    identity = dict(target=lock['target'], python=lock['python312'], uv=lock['uv'], pip=lock['pip'],
                    requirements={requirements.name: sha256(requirements)})
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    runtime = managed / 'moss' / ('macos-moss-' + signature)
    runtime_python = runtime / 'bin/python'
    previous = resolve_runtime_python('moss', register=False)
    # Only runtimes this preparation owns are refreshed and reused; a developer's
    # own environment (TWOBYTEASR_MOSS_PYTHON) is never written into.
    candidates = [Path(previous)] if previous else []
    candidates.append(runtime_python)
    moss_root = (managed / 'moss').resolve()
    for candidate in candidates:
        owned = candidate.parent.parent   # <runtime>/bin/python; the entry itself is a symlink
        if not (owned.resolve().parent == moss_root and (owned / 'managed-runtime.json').is_file()):
            continue
        if candidate.is_file():
            install_moss_source(root, owned)
            if check_moss_runtime(candidate, root):
                print('[运行库] 复用已核对的 MOSS 环境', flush=True)
                return candidate
    state['phase'] = 'tools_preparing'
    uv, base = _bootstrap_interpreter(managed, lock, environment, python='python312')
    state['phase'] = 'dependencies_installing'
    emit(state['phase'], model='moss')
    if not runtime_python.is_file():
        run([uv, '--no-config', '--system-certs', 'venv', '--no-project', '--python', base,
             '--no-python-downloads', runtime], cwd=managed, environment=environment)
    pip_wheel = download_archive(lock['pip'], managed / 'bootstrap-cache')
    run([uv, '--no-config', 'pip', 'install', '--python', runtime_python, pip_wheel], cwd=managed, environment=environment)
    report = runtime / 'pip-install.json'
    # Every requirement is hash-pinned: pip refuses any other file.
    run_hashed_pip_install([runtime_python, '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check', 'install',
                            '--require-hashes', '--only-binary', ':all:', '--report', report, '-r', requirements.name],
                           cwd=requirements.parent, environment=environment)
    run([runtime_python, '-I', '-m', 'pip', '--isolated', 'check'], cwd=managed, environment=environment)
    source_digest = install_moss_source(root, runtime)
    if not check_moss_runtime(runtime_python, root):
        raise RuntimeError('MOSS 运行库检查失败；之前的登记保持不变')
    receipt = runtime / 'managed-runtime.json'
    pending = receipt.with_suffix('.pending')
    pending.write_text(json.dumps(dict(identity, signature=signature, role='moss', runtime_ready=True,
                                       moss_source_sha256=source_digest, prepared_at=time.time()),
                                  ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(pending, receipt)
    return runtime_python


def physical_memory_bytes() -> int:
    try:
        result = subprocess.run(['sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, timeout=10)
        return int(result.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


def prepare_local(root: Path, *, models: Path, source: str, keys, register: bool = True) -> dict:
    """MOSS / FireRed (and their VAD + speaker models) for the Apple GPU.

    Runtimes are registered only after every requested model passed the same
    readiness check the Windows installer uses, run on this Mac's GPU.
    """
    keys = tuple(dict.fromkeys(keys))
    if not keys or not set(keys) <= set(LOCAL_TORCH_KEYS):
        raise ValueError('unknown local model keys: ' + ','.join(keys))
    if 'moss' in keys:
        # Like scripts/download_models.ps1: MOSS runs with FireRedVAD and the
        # ECAPA speaker model, so the MOSS card (key 'moss' only) brings them.
        keys = tuple(dict.fromkeys(keys + ('firered_vad', 'speaker_embedding')))
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('MOSS 与 FireRed 只能在 Apple 芯片（M 系列）的 Mac 上运行')
    from twobyteasr.runtime_paths import MODEL_ROOT_ENV, user_data_root
    from twobyteasr.runtime_registry import register_runtime
    from twobyteasr.repository_download import preparation_lock
    managed = user_data_root() / 'runtimes'
    managed.mkdir(parents=True, exist_ok=True)
    lock = json.loads((root / 'packaging/macos/bootstrap.lock.json').read_text('utf8'))
    environment = _child_environment()
    environment['UV_CACHE_DIR'] = str(user_data_root() / 'cache/uv')
    state = {'phase': 'preparing'}
    label = ','.join(keys)
    try:
        memory = physical_memory_bytes()
        if memory:
            print('[设备] 这台 Mac 的内存约 %.0f GB（Apple 芯片的显卡与内存共用）' % (memory / 1e9), flush=True)
        with preparation_lock(managed / '.macos-cpu-prepare.lock'):
            state['phase'] = 'runtime_installing'
            emit(state['phase'], device='mps', model=label)
            main_python = ensure_main_runtime(root, managed, lock, environment, state, models=keys)
        moss_python = None
        if 'moss' in keys:
            with preparation_lock(managed / '.macos-moss-prepare.lock'):
                state['phase'] = 'runtime_installing'
                emit(state['phase'], device='mps', model='moss')
                moss_python = ensure_moss_runtime(root, managed, lock, environment, state)
        state['phase'] = 'weights_downloading'
        from twobyteasr.model_integrity import locked_model, verify_model_files
        from twobyteasr.repository_download import download_model
        # The main interpreter runs the resumable downloader (requests is in requirements-gui.txt).
        os.environ['TWOBYTEASR_DOWNLOAD_PYTHON'] = str(main_python)
        for key in keys:
            emit(state['phase'], model=key)
            spec = locked_model(key, root=root)
            destination = models.expanduser().resolve() / Path(spec['path']).name
            download_model(model_key=key, spec=spec, destination=destination, mode=source,
                           staging_root=models.resolve() / '.download-staging')
            verify_model_files(key, destination, root=root)
        state['phase'] = 'model_loading'
        # The readiness check resolves these unregistered runtimes and the chosen model folder.
        environment.update({'TWOBYTEASR_MAIN_PYTHON': str(main_python), 'TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY': '1',
                            MODEL_ROOT_ENV: str(models.expanduser().resolve()),
                            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'})
        environment.pop('2BYTEASR_CPU_ONLY', None)
        if moss_python:
            environment['TWOBYTEASR_MOSS_PYTHON'] = str(moss_python)
        for key in [item for item in _LOCAL_READINESS_ORDER if item in keys]:
            emit(state['phase'], model=key, device='mps')
            run([main_python, '-I', root / 'scripts/validate_prepared_model.py', '--root', root,
                 '--model', key, '--force'], cwd=managed, environment=environment)
        # Registration only after every requested model ran on this Mac.
        if register:
            register_runtime('main', str(main_python), source='macos-gui-local-bootstrap')
            if moss_python:
                register_runtime('moss', str(moss_python), source='macos-gui-moss-bootstrap')
        emit('ready', model=label, device='mps', model_inference_verified=True)
        return dict(main=str(main_python), moss=str(moss_python) if moss_python else '', keys=list(keys))
    except Exception as exc:
        category = 'permission' if isinstance(exc, PermissionError) else 'prepare_failed'
        print('[2BYTEASR_INSTALL_ERROR] ' + json.dumps(dict(phase=state['phase'], category=category,
              message=str(exc)), ensure_ascii=False), flush=True)
        raise


MLX_MODEL_KEYS = ('mlx_qwen3_asr_0_6b', 'mlx_qwen3_asr_1_7b', 'mlx_qwen_aligner')
READINESS_TEXT = 'Hello this is a local speech recognition test the weather is sunny today'


def _mlx_worker(root: Path) -> Path:
    for candidate in (root / 'workers' / 'mlx_worker.py', root / 'mlx_worker.py'):
        if candidate.is_file():
            return candidate
    raise RuntimeError('mlx_worker.py is missing from this build')


def check_mlx_runtime(python: Path, root: Path) -> bool:
    """Torch-free MLX runtime: the worker's own import/device probe."""
    if not python.is_file():
        return False
    try:
        result = subprocess.run([str(python), '-I', str(_mlx_worker(root)), '--mode', 'probe'], cwd=root,
                                capture_output=True, text=True, timeout=180, env=_child_environment())
        if result.returncode:
            return False
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        return bool(payload.get('ok')) and payload.get('machine') == 'arm64'
    except (OSError, ValueError, IndexError, RuntimeError, subprocess.TimeoutExpired):
        return False


def validate_mlx_model(key: str, runtime_python: Path) -> dict:
    """Real inference through the production adapter on the bundled sample.

    Readiness only (the sample is synthetic English speech), not accuracy.
    """
    import wave
    import numpy as np
    from twobyteasr import mlx_backend
    from twobyteasr.runtime_paths import detect_install_root
    os.environ['TWOBYTEASR_MLX_PYTHON'] = str(runtime_python)
    sample = detect_install_root() / 'assets/diagnostics/speech_en.wav'
    with wave.open(str(sample), 'rb') as stream:
        rate = stream.getframerate()
        audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32) / 32768
    if rate != 16000:
        raise RuntimeError('readiness sample must be 16 kHz')
    duration = len(audio) / rate
    started = time.time()
    if key == mlx_backend.ALIGNER_KEY:
        payload = mlx_backend.run_aligner(audio, [dict(id='readiness', text=READINESS_TEXT, window_start_ms=0,
                                                       window_end_ms=int(duration * 1000), language='English')])
        row = payload['results'][0]
        units = row.get('word_units') or []
        limit = duration * 1000 + 200
        if (row.get('status') != 'aligned' or not units
                or not all(0 <= unit['start_ms'] <= unit['end_ms'] <= limit for unit in units)
                or not any(unit['start_ms'] < unit['end_ms'] for unit in units)):
            raise RuntimeError('MLX 对齐没有返回有效的字词时间')
        output = dict(units=len(units))
    else:
        backend = next(name for name, model in mlx_backend.PRIMARY_BACKENDS.items() if model == key)
        rows = mlx_backend.transcribe_reference(audio, [dict(start=0.0, end=duration)], backend=backend,
                                                language='English')
        if not any(str(row.get('text') or '').strip() for row in rows):
            raise RuntimeError('MLX Qwen3-ASR 没有返回文字')
        output = dict(text=' '.join(row['text'] for row in rows)[:200])
    return dict(model=key, inference_verified=True, elapsed_s=round(time.time() - started, 2),
                sample=str(sample), sample_kind='bundled synthetic speech; readiness only, not accuracy', **output)


def prepare_mlx(root: Path, *, models: Path, source: str, keys, register: bool = True) -> Path:
    """Private torch-free MLX runtime plus locked MLX models (Apple Silicon)."""
    keys = tuple(dict.fromkeys(keys))
    if not keys or not set(keys) <= set(MLX_MODEL_KEYS):
        raise ValueError('unknown MLX model keys: ' + ','.join(keys))
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('MLX 只能在 Apple Silicon（M 系列芯片）的 Mac 上运行')
    release = tuple(int(part) for part in (platform.mac_ver()[0] or '0').split('.')[:2] if part.isdigit())
    if release and release < (14,):
        raise RuntimeError('MLX 运行库需要 macOS 14 或更新版本（当前 ' + platform.mac_ver()[0] + '）')
    from twobyteasr.runtime_paths import user_data_root
    from twobyteasr.runtime_registry import register_runtime, resolve_runtime_python
    from twobyteasr.repository_download import preparation_lock
    managed = user_data_root() / 'runtimes'
    managed.mkdir(parents=True, exist_ok=True)
    lock = json.loads((root / 'packaging/macos/bootstrap.lock.json').read_text('utf8'))
    requirements = root / 'packaging/macos/requirements-mlx.txt'
    identity = dict(target=lock['target'], python=lock['python'], uv=lock['uv'], pip=lock['pip'],
                    requirements={requirements.name: sha256(requirements)})
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    runtime = managed / 'mlx' / ('macos-mlx-' + signature)
    runtime_python = runtime / 'bin/python'
    environment = _child_environment()
    environment['UV_CACHE_DIR'] = str(user_data_root() / 'cache/uv')
    phase = 'preparing'
    try:
        with preparation_lock(managed / '.macos-mlx-prepare.lock'):
            phase = 'runtime_installing'
            emit(phase, device='mlx', model=','.join(keys))
            previous = resolve_runtime_python('mlx', register=False)
            if previous and Path(previous) != runtime_python and check_mlx_runtime(Path(previous), root):
                runtime_python = Path(previous)
                print('[运行库] 复用已核对的 MLX 环境', flush=True)
            elif not check_mlx_runtime(runtime_python, root):
                phase = 'tools_preparing'
                uv, base = _bootstrap_interpreter(managed, lock, environment)
                phase = 'dependencies_installing'
                emit(phase)
                if not runtime_python.is_file():
                    run([uv, '--no-config', '--system-certs', 'venv', '--no-project', '--python', base,
                         '--no-python-downloads', runtime], cwd=managed, environment=environment)
                pip_wheel = download_archive(lock['pip'], managed / 'bootstrap-cache')
                run([uv, '--no-config', 'pip', 'install', '--python', runtime_python, pip_wheel],
                    cwd=managed, environment=environment)
                report = runtime / 'pip-install.json'
                # Every requirement is hash-pinned: pip refuses any other file.
                run_hashed_pip_install([runtime_python, '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check',
                                        'install', '--require-hashes', '--only-binary', ':all:', '--report', report,
                                        '-r', requirements.name], cwd=requirements.parent, environment=environment)
                run([runtime_python, '-I', '-m', 'pip', '--isolated', 'check'], cwd=managed, environment=environment)
                if not check_mlx_runtime(runtime_python, root):
                    raise RuntimeError('MLX 运行库探测失败（需要 Apple Silicon 与 Metal）；之前的登记保持不变')
                receipt = runtime / 'managed-runtime.json'
                pending = receipt.with_suffix('.pending')
                pending.write_text(json.dumps(dict(identity, signature=signature, role='mlx', runtime_ready=True,
                                                   prepared_at=time.time()), ensure_ascii=False, indent=2),
                                   encoding='utf8')
                os.replace(pending, receipt)
            phase = 'weights_downloading'
            from twobyteasr.model_integrity import locked_model, verify_model_files
            from twobyteasr.repository_download import download_model
            # The MLX interpreter runs the resumable downloader (requests is in requirements-mlx.txt).
            os.environ['TWOBYTEASR_DOWNLOAD_PYTHON'] = str(runtime_python)
            for key in keys:
                emit(phase, model=key)
                spec = locked_model(key, root=root)
                destination = models.expanduser().resolve() / Path(spec['path']).name
                download_model(model_key=key, spec=spec, destination=destination, mode=source,
                               staging_root=models.resolve() / '.download-staging')
                verify_model_files(key, destination, root=root)
            phase = 'model_loading'
            receipts = user_data_root() / 'model-readiness'
            receipts.mkdir(parents=True, exist_ok=True)
            for key in keys:
                emit(phase, model=key, device='mlx')
                result = validate_mlx_model(key, runtime_python)
                pending = receipts / (key + '.pending')
                pending.write_text(json.dumps(dict(result, status='PASS', python=str(runtime_python)),
                                              ensure_ascii=False, indent=2), encoding='utf8')
                os.replace(pending, receipts / (key + '.json'))
            # Registration only after real inference succeeded.
            if register:
                register_runtime('mlx', str(runtime_python), source='macos-gui-mlx-bootstrap')
            emit('ready', model=','.join(keys), device='mlx', model_inference_verified=True)
            return runtime_python
    except Exception as exc:
        category = 'permission' if isinstance(exc, PermissionError) else 'prepare_failed'
        print('[2BYTEASR_INSTALL_ERROR] ' + json.dumps(dict(phase=phase, category=category,
              message=str(exc)), ensure_ascii=False), flush=True)
        raise


def main_mlx(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--keys', required=True)
    parser.add_argument('--source', choices=['AUTO', 'HF_OFFICIAL', 'HF_MIRROR', 'MODELSCOPE'], default='AUTO')
    args = parser.parse_args(argv)
    try:
        prepare_mlx(args.root.resolve(), models=args.models.resolve(), source=args.source,
                    keys=[key for key in args.keys.split(',') if key])
    except Exception:
        return 1
    return 0


def main_local(argv=None) -> int:
    """``--macos-prepare-local``: MOSS / FireRed for the Apple GPU (2026-10-14)."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--keys', required=True)
    parser.add_argument('--source', choices=['AUTO', 'HF_OFFICIAL', 'HF_MIRROR', 'MODELSCOPE'], default='AUTO')
    args = parser.parse_args(argv)
    try:
        prepare_local(args.root.resolve(), models=args.models.resolve(), source=args.source,
                      keys=[key for key in args.keys.split(',') if key])
    except Exception:
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--source', choices=['AUTO', 'HF_OFFICIAL', 'HF_MIRROR', 'MODELSCOPE'], default='AUTO')
    args = parser.parse_args(argv)
    try:
        prepare(args.root.resolve(), models=args.models.resolve(), source=args.source)
    except Exception:
        return 1
    return 0
