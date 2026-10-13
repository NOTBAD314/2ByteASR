"""Runtime download fallbacks (uv, Python, PyTorch, PyPI) never weaken hashes.

No network: the installer runs against a fake uv, and the PowerShell part
against a local HTTP server.
"""
import functools
import hashlib
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('install_managed_backend_under_test', ROOT/'scripts/install_managed_backend.py')
installer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(installer)
LOCK = json.loads((ROOT/'dependencies.lock.json').read_text('utf-8-sig'))
SOURCES = json.loads((ROOT/'scripts/runtime_sources.json').read_text('utf8'))
HASHES = json.loads((ROOT/'scripts/runtime_package_hashes.json').read_text('utf8'))
TAGS = ['cpu', LOCK['runtime']['cuda_wheel'], LOCK['runtime']['cuda_wheel_modern']]
SHA256 = re.compile(r'[0-9a-f]{64}')


def test_uv_fallbacks_are_the_locked_release_only():
    boot = LOCK['managed_bootstrap']
    uv = SOURCES['uv']
    assert uv['version'] == boot['uv_version']
    assert set(uv['binaries']) == {'uv.exe', 'uvw.exe'}
    assert all(SHA256.fullmatch(value) for value in uv['binaries'].values())
    wheel = f"uv-{boot['uv_version']}-py3-none-win_amd64.whl"
    wheel_hashes = set()
    for item in uv['fallbacks']:
        assert item['url'].startswith('https://')
        if item['url'].endswith('.zip'):
            assert item['sha256'] == boot['uv_sha256']
        else:
            assert item['url'].endswith('/'+wheel)
            wheel_hashes.add(item['sha256'])
    assert len(wheel_hashes) == 1 and SHA256.fullmatch(wheel_hashes.pop())
    for key in ('python_mirrors', 'pypi_mirrors', 'pytorch_mirrors'):
        assert SOURCES[key] and all(item['url'].startswith('https://') for item in SOURCES[key])
    assert all('{tag}' in item['url'] for item in SOURCES['pytorch_mirrors'])


def test_hash_table_covers_every_environment_with_current_pins():
    """Fails when dependencies.lock.json changes without regenerating the table."""
    environments = HASHES['environments']
    expected = set()
    for role, models in installer.planned_roles(set(LOCK['models'])):
        for tag in TAGS:
            key = f'{role}|{installer.role_python(role)}|{tag}'
            expected.add(key)
            entry = environments[key]
            pins = installer.role_pins(LOCK, role, models, tag)
            assert entry['pins'] == pins, key+' is stale: run scripts/build_runtime_package_hashes.py'
            assert installer.hashed_environment(ROOT, role, installer.role_python(role), tag, pins)[0] is not None
            for name, item in entry['packages'].items():
                assert name == installer.normalize(name)
                assert item['sha256'] and all(SHA256.fullmatch(value) for value in item['sha256']), name
    assert set(environments) == expected


def test_moss_mirror_requirements_match_the_locked_source():
    text = (ROOT/LOCK['sources']['moss']['path']/'pyproject.toml').read_text('utf8')
    def block(name):
        return re.findall(r'"([^"]+)"', re.search(rf'^{name}\s*=\s*\[(.*?)\]', text, re.M | re.S).group(1))
    entry = HASHES['environments']['moss|3.12.13|cu128']
    assert entry['extra_requirements'] == block('dependencies') + block('torch-runtime')
    assert installer.pinned_names(entry, entry['extra_requirements'])


def test_stale_or_missing_hashes_refuse_the_mirror():
    pins = installer.role_pins(LOCK, 'main', {'sensevoice'}, 'cpu')
    stale = [pin.replace('==', '==0.0.0.') if pin.startswith('requests==') else pin for pin in pins]
    entry, reason = installer.hashed_environment(ROOT, 'main', '3.10.19', 'cpu', stale)
    assert entry is None and 'requests' in reason
    entry, reason = installer.hashed_environment(ROOT, 'main', '3.10.19', 'cu999', pins)
    assert entry is None and 'cu999' in reason


def test_build_backend_for_mirror_path_is_the_locked_release():
    backend = HASHES['build_backend']
    assert {name: item['version'] for name, item in backend.items()} == {
        'setuptools': LOCK['runtime']['setuptools'], 'wheel': LOCK['runtime']['wheel']}
    bundled = {item['file']: item['sha256'] for item in
               json.loads((ROOT/'packaging/model_wheels.json').read_text('utf8'))['wheels']}
    assert bundled[f"setuptools-{backend['setuptools']['version']}-py3-none-any.whl"] in backend['setuptools']['sha256']
    lines = installer.mirror_build_constraints(ROOT).splitlines()
    assert [line.split('==')[0] for line in lines] == ['setuptools', 'wheel']
    assert all(' --hash=sha256:' in line for line in lines)


class FakeUv:
    """Records uv invocations; `fails(command)` decides which ones exit 1."""

    def __init__(self, fails, freeze):
        self.commands = []
        self.fails = fails
        self.freeze = freeze

    def popen(self, arguments, **kwargs):
        self.commands.append(arguments)
        if 'venv' in arguments:
            python = Path(kwargs['cwd'])/arguments[-1]/'Scripts/python.exe'
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b'fixture only')
        code = 1 if self.fails(' '.join(arguments)) else 0
        return type('Process', (), {'stdout': io.StringIO(''), 'wait': lambda self: code})()

    def check_output(self, arguments, **kwargs):
        return self.freeze(arguments).encode()

    def installs(self):
        return [' '.join(c) for c in self.commands if 'pip' in c and 'install' in c]


@pytest.fixture
def run_installer(monkeypatch):
    from twobyteasr.runtime_paths import user_data_root
    managed = user_data_root()/'runtimes'
    if managed.exists():
        shutil.rmtree(managed)
    monkeypatch.setenv('2BYTEASR_CPU_ONLY', '1')

    def run(models, fails, freeze):
        fake = FakeUv(fails, freeze)
        monkeypatch.setattr(installer.subprocess, 'Popen', fake.popen)
        monkeypatch.setattr(installer.subprocess, 'check_output', fake.check_output)
        monkeypatch.setattr(sys, 'argv', ['install', '--root', str(ROOT), '--uv', 'uv-fixture.exe', '--models', models])
        try:
            installer.main()
        finally:
            fake.managed = managed
        return fake
    return run


def table_freeze(role, tag='cpu', extra=''):
    entry = HASHES['environments'][f'{role}|{installer.role_python(role)}|{tag}']
    return lambda arguments: '\n'.join(f"{n}=={entry['packages'][n]['version']}" for n in ('torch', 'requests')
                                       if n in entry['packages']) + '\n' + extra


def test_official_sources_keep_the_original_commands(run_installer):
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main'))
    installs = fake.installs()
    assert len(installs) == 2
    assert '--index-url https://download.pytorch.org/whl/cpu' in installs[0]
    assert installs[0].endswith('torch==2.11.0+cpu torchaudio==2.11.0+cpu')
    assert '--index-url https://pypi.org/simple' in installs[1] and '--constraint' in installs[1]
    assert not any('mirror' in ' '.join(c) for c in fake.commands)
    assert not any('--mirror' in c for c in fake.commands)
    assert not list(fake.managed.rglob('mirror-constraints.txt'))


def test_failed_official_source_installs_environment_from_hashed_mirrors(run_installer, monkeypatch):
    # A CUDA build is not bundled, so it needs a PyTorch mirror.
    monkeypatch.delenv('2BYTEASR_CPU_ONLY')
    real_is_file = Path.is_file
    monkeypatch.setattr(Path, 'is_file', lambda self: True if self.name == 'nvidia-smi.exe' else real_is_file(self))
    # compute capability 12.x selects the modern CUDA build.
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, '12.0\n', ''))
    tag = LOCK['runtime']['cuda_wheel_modern']
    first_mirror = SOURCES['pypi_mirrors'][0]['url']
    first_torch = SOURCES['pytorch_mirrors'][0]['url'].format(tag=tag)
    fails = lambda command: ('download.pytorch.org' in command
                             or (first_mirror in command and first_torch in command))
    fake = run_installer('sensevoice', fails, table_freeze('main', tag))
    installs = fake.installs()
    assert 'download.pytorch.org' in installs[0]
    mirror = installs[-1]
    assert f'--index-url {first_mirror}' in mirror
    second_torch = SOURCES['pytorch_mirrors'][1]['url'].format(tag=tag)
    assert f'--find-links {second_torch}/torch/' in mirror
    assert 'mirror-constraints.txt' in mirror and 'mirror-build-constraints.txt' in mirror
    assert f'torch==2.11.0+{tag}' in mirror and 'funasr==1.4.1' in mirror
    # The PyPI step was covered by the mirror resolution, not retried officially.
    assert not any('https://pypi.org/simple' in command for command in installs)
    constraints = next(fake.managed.rglob('mirror-constraints.txt')).read_text('utf8').splitlines()
    assert constraints and all(' --hash=sha256:' in line for line in constraints)
    assert next(fake.managed.rglob('managed-runtime.json')).is_file()


def test_bundled_cpu_pytorch_does_not_depend_on_a_pytorch_mirror(run_installer):
    if not list((ROOT/'wheels').glob('torch-2.11.0+cpu-cp310-*.whl')):
        pytest.skip('bundled CPU PyTorch wheel not present in this checkout')
    fake = run_installer('sensevoice', lambda command: 'download.pytorch.org' in command, table_freeze('main'))
    mirror = fake.installs()[-1]
    assert 'torch==2.11.0+cpu' in mirror and '--find-links' in mirror
    assert not any(item['url'].split('{')[0] in mirror for item in SOURCES['pytorch_mirrors'])


def test_mirror_install_with_unlisted_package_is_not_published(run_installer):
    fails = lambda command: 'pypi.org/simple' in command
    with pytest.raises(RuntimeError, match='锁定哈希表之外'):
        run_installer('sensevoice', fails, table_freeze('main', extra='injected==1.0'))
    from twobyteasr.runtime_registry import load_registry
    assert 'main' not in load_registry()


def test_every_source_failing_reports_sources_exhausted(run_installer):
    with pytest.raises(installer.SourcesExhausted):
        run_installer('sensevoice', lambda command: 'pip install' in command, table_freeze('main'))
    assert installer.SOURCES_EXHAUSTED == 75
    script = (ROOT/'scripts/setup_managed_backend.ps1').read_text('utf-8-sig')
    assert '$LASTEXITCODE -eq 75' in script and "'runtime_network'" in script


def test_python_download_falls_back_to_mirror(run_installer):
    fails = lambda command: 'python install' in command and '--mirror' not in command
    fake = run_installer('sensevoice', fails, table_freeze('main'))
    python_installs = [c for c in fake.commands if 'python' in c and 'install' in c and 'pip' not in c]
    assert '--mirror' not in python_installs[0]
    assert python_installs[1][-2:] == ['--mirror', SOURCES['python_mirrors'][0]['url']]


def test_moss_mirror_path_installs_locked_dependencies_then_builds_source(run_installer):
    fails = lambda command: 'download.pytorch.org' in command or 'https://pypi.org/simple' in command
    fake = run_installer('moss', fails, table_freeze('moss'))
    installs = fake.installs()
    entry = HASHES['environments']['moss|3.12.13|cpu']
    moss_mirror = next(c for c in installs if 'mirror-constraints.txt' in c and 'torch==2.11.0+cpu' in c)
    assert f"librosa=={entry['packages']['librosa']['version']}" in moss_mirror
    build = installs[-1]
    assert f"--index-url {SOURCES['pypi_mirrors'][0]['url']}" in build
    assert 'mirror-constraints.txt' in build and 'mirror-build-constraints.txt' in build
    assert build.endswith('MOSS-Transcribe-Diarize[torch-runtime]')
    # The official MOSS step (default index) was not attempted after the mirror took over.
    assert not any(c.endswith('[torch-runtime]') and '--index-url' not in c for c in installs)


def _zip_with(names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in names:
            archive.writestr(name, b'fixture '+name.encode())
    return buffer.getvalue()


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell and curl.exe')
def test_powershell_uv_sources_and_system_proxy():
    work = ROOT/'tmp'/('runtime-fallback-'+uuid.uuid4().hex)
    served = work/'served'
    served.mkdir(parents=True)
    good = _zip_with(['uv.exe', 'uvw.exe'])
    (served/'good.zip').write_bytes(good)
    (served/'bad.zip').write_bytes(_zip_with(['uv.exe']))
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(served)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        receipt = work/'result.json'
        shell = Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        environment = dict(os.environ, NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
        result = subprocess.run([str(shell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                 str(ROOT/'tests/verify_runtime_download_fallback.ps1'),
                                 '-BaseUrl', f'http://127.0.0.1:{port}', '-GoodSha', hashlib.sha256(good).hexdigest(),
                                 '-ListeningPort', str(port), '-WorkDir', str(work), '-Output', str(receipt)],
                                env=environment, capture_output=True, text=True, encoding='utf8', errors='replace', timeout=180)
        assert result.returncode == 0, result.stdout+result.stderr
        actual = json.loads(receipt.read_text('utf-8-sig'))
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(work, ignore_errors=True)
    assert actual['fallback_sha'] == hashlib.sha256(good).hexdigest()
    assert actual['partial_left'] is False
    assert actual['network_throw'] is True and actual['network_category'] == 'runtime_network'
    assert actual['checksum_throw'] is True and actual['checksum_category'] == 'checksum'
    assert actual['archive_after_failures'] is False
    assert actual['system_https'] == actual['system_http'] == f'http://127.0.0.1:{port}'
    assert actual['system_no_proxy'] == 'localhost,127.0.0.1,::1'
    assert actual['user_https'] == 'http://user-choice.invalid:1' and actual['user_http'] == ''
    assert actual['dead_https'] == actual['bypass_https'] == actual['direct_https'] == ''
