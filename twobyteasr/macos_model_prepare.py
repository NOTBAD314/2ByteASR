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
    request = urllib.request.Request(spec['url'], headers={'User-Agent': '2ByteASR-native-CPU-bootstrap/0.5.0'})
    with urllib.request.urlopen(request, context=context, timeout=40) as response, pending.open('wb') as output:
        total = int(response.headers.get('Content-Length') or 0)
        filename = unquote(urlsplit(spec['url']).path.rsplit('/', 1)[-1])
        print('[2BYTEASR_FILE] ' + json.dumps(dict(file=filename, size=total)), flush=True)
        downloaded = 0
        last = 0.0
        for block in iter(lambda: response.read(1024 * 1024), b''):
            output.write(block)
            downloaded += len(block)
            if time.monotonic() - last >= 1:
                print('[2BYTEASR_PROGRESS] ' + json.dumps(dict(downloaded=downloaded, total=total,
                      file=filename, percent=downloaded * 100 / total if total else 0)), flush=True)
                last = time.monotonic()
    emit('files_verifying', file=filename)
    if sha256(pending) != spec['sha256']:
        raise RuntimeError('SHA-256 mismatch for native bootstrap archive')
    os.replace(pending, destination)
    return destination


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


def prepare(root: Path, *, models: Path, source: str, register: bool = True) -> Path:
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('SenseVoice CPU preparation requires native Apple Silicon macOS')
    from twobyteasr.runtime_paths import user_data_root
    from twobyteasr.runtime_registry import register_runtime, resolve_runtime_python
    from twobyteasr.repository_download import preparation_lock
    managed = user_data_root() / 'runtimes'
    managed.mkdir(parents=True, exist_ok=True)
    lock = json.loads((root / 'packaging/macos/bootstrap.lock.json').read_text('utf8'))
    requirements = root / 'packaging/macos/requirements-cpu.txt'
    identity = dict(target=lock['target'], python=lock['python'], uv=lock['uv'],
                    pip=lock['pip'], requirements={path.name: sha256(path) for path in (
                        requirements, root / 'packaging/macos/requirements-gui.txt',
                        root / 'packaging/macos/native-dependencies.lock.json')})
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    runtime = managed / 'main' / ('macos-cpu-' + signature)
    runtime_python = runtime / 'bin/python'
    receipt = runtime / 'managed-runtime.json'
    environment = _child_environment()
    environment['UV_CACHE_DIR'] = str(user_data_root() / 'cache/uv')
    phase = 'preparing'
    try:
        with preparation_lock(managed / '.macos-cpu-prepare.lock'):
            phase = 'runtime_installing'
            emit(phase, device='cpu', model='sensevoice')
            previous = resolve_runtime_python('main', register=False)
            # The deterministic locked runtime is an explicit recovery input
            # for legacy registry entries that stored only a base interpreter.
            if not (previous and check_runtime(Path(previous), root)) and check_runtime(runtime_python, root):
                previous = str(runtime_python)
            if previous and check_runtime(Path(previous), root):
                runtime_python = Path(previous)
                print('[运行库] 复用已核对的原生 CPU 环境', flush=True)
            else:
                phase = 'tools_preparing'
                emit(phase)
                uv_root = managed / 'tools' / ('uv-' + lock['uv']['version'])
                # Re-extract from the verified cache before executing a tool;
                # an executable left by a failed attempt is not trusted alone.
                extract_archive(download_archive(lock['uv'], managed / 'bootstrap-cache'), uv_root)
                uv = uv_root / lock['uv']['member']
                uv.chmod(uv.stat().st_mode | 0o700)
                phase = 'interpreter_preparing'
                emit(phase)
                python_root = managed / 'python' / ('cpython-' + lock['python']['version'] + '-arm64-' + lock['python']['build'])
                extract_archive(download_archive(lock['python'], managed / 'bootstrap-cache'), python_root)
                base = python_root / 'python/bin/python3.10'
                if not base.is_file():
                    raise RuntimeError('Verified Python archive has no native interpreter')
                run([base, '-I', '-c', 'import sys,platform; assert platform.machine()=="arm64"; assert platform.python_version()=="' + lock['python']['version'] + '"'], cwd=managed, environment=environment)
                phase = 'dependencies_installing'
                emit(phase)
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
                payload = dict(identity, signature=signature, role='main', models=['sensevoice'],
                               runtime_ready=True, inference_verified=False, native_wheels_verified=verified, prepared_at=time.time())
                pending = receipt.with_suffix('.pending')
                pending.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf8')
                os.replace(pending, receipt)
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
            phase = 'weights_downloading'
            emit(phase, model='sensevoice')
            run([runtime_python, '-I', root / 'scripts/macos_prepare_model.py', '--models', models,
                 '--source', source], cwd=managed, environment=environment)
            phase = 'model_loading'
            emit(phase, model='sensevoice', device='cpu')
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
        print('[2BYTEASR_INSTALL_ERROR] ' + json.dumps(dict(phase=phase, category=category,
              message=str(exc)), ensure_ascii=False), flush=True)
        raise


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
