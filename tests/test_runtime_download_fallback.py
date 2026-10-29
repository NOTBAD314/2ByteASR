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
import time
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
    for name in ('setuptools','wheel'):
        assert bundled[f"{name}-{backend[name]['version']}-py3-none-any.whl"] in backend[name]['sha256']
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
        output = self.freeze(arguments) if 'freeze' in arguments else ''
        def wait(process,timeout=None):
            deadline=None if timeout is None else time.monotonic()+timeout
            while process.poll() is None:
                if deadline is not None and time.monotonic()>=deadline:
                    raise subprocess.TimeoutExpired(arguments,timeout)
                time.sleep(.01)
            return process.returncode
        return type('Process', (), {'stdout': io.StringIO(output), 'pid': 123456,
            'returncode': code, 'poll': lambda self: code, 'wait': wait})()

    def check_output(self, arguments, **kwargs):
        return self.freeze(arguments).encode()

    def installs(self):
        return [' '.join(c) for c in self.commands if 'pip' in c and 'install' in c]


@pytest.fixture
def run_installer(monkeypatch):
    from twobyteasr.runtime_paths import user_data_root
    from twobyteasr.system import process_job
    # FakeUv never owns a Win32 process handle; real-process tests exercise
    # RequestProcessJob separately. Do not attach a native Job to this stub.
    class FakeJob:
        def __init__(self,process):pass
        def close(self,timeout=None):pass
    monkeypatch.setattr(process_job,'RequestProcessJob',FakeJob)
    managed = user_data_root()/'runtimes'
    if managed.exists():
        shutil.rmtree(managed)
    monkeypatch.setenv('2BYTEASR_CPU_ONLY', '1')
    monkeypatch.delenv(installer.RUNTIME_SOURCE_ENV, raising=False)
    backends=user_data_root()/'fake-build-wheels';backends.mkdir(parents=True,exist_ok=True)
    wheels=[backends/'setuptools.whl',backends/'wheel.whl']
    for wheel in wheels:wheel.write_bytes(b'FakeUv fixture; hash validation has separate tests')
    monkeypatch.setattr(installer,'verified_bundled_build_wheels',lambda root:wheels)

    def run(models, fails, freeze, left_official=lambda call: '', repair_roles='', prefetch=None, fastest=None):
        """``prefetch(call)`` stands in for the app's own PyPI download (default: it fails, so
        uv installs from the indexes); ``fastest`` names the label measuring would put first."""
        fake = FakeUv(fails, freeze)
        fake.fetches = []
        fake.prefetches = []
        fake.rankings = []
        def fetch(folder, pins, version, entry, sources):
            # No network: the real downloader has its own tests.
            call = dict(folder=Path(folder), pins=list(pins), version=version, sources=list(sources))
            fake.fetches.append(call)
            return left_official(call)
        def rank(sources, path, preference):
            # No network: measuring has its own tests (test_runtime_package_download.py).
            measured = {item['label']: dict(rate=0.0, bytes=0, error='fixture') for item in sources}
            order = list(sources)
            known = fastest in measured
            if known:
                order.sort(key=lambda item: item['label'] != fastest)
                measured[fastest]['rate'] = 9e6
            if preference in ('mirror', 'official') or not known:
                order = installer.order_by_preference(order, 'mirror' if preference == 'mirror' else 'official')
            fake.rankings.append(dict(path=path, preference=preference, order=[item['label'] for item in order]))
            return order, measured
        def fetch_files(folder, items, sources, **kwargs):
            call = dict(folder=Path(folder), items=list(items), sources=[item['label'] for item in sources])
            fake.prefetches.append(call)
            if prefetch is None:
                raise installer.SourcesExhausted('fixture: the app could not fetch the packages')
            return prefetch(call)
        monkeypatch.setattr(installer, 'fetch_pytorch_wheels', fetch)
        monkeypatch.setattr(installer, 'rank_sources', rank)
        monkeypatch.setattr(installer, 'fetch_files', fetch_files)
        monkeypatch.setattr(installer.subprocess, 'Popen', fake.popen)
        monkeypatch.setattr(installer.subprocess, 'check_output', fake.check_output)
        monkeypatch.setattr(sys, 'argv', ['install', '--root', str(ROOT), '--uv', 'uv-fixture.exe', '--models', models,
                                        *(['--repair-roles',repair_roles] if repair_roles else [])])
        try:
            installer.main()
        finally:
            fake.managed = managed
        return fake
    return run


@pytest.fixture
def cuda(monkeypatch):
    """Pretend an NVIDIA GPU with compute capability 12.x (modern CUDA build)."""
    monkeypatch.delenv('2BYTEASR_CPU_ONLY')
    real_is_file = Path.is_file
    monkeypatch.setattr(Path, 'is_file', lambda self: True if self.name == 'nvidia-smi.exe' else real_is_file(self))
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, '12.0\n', ''))
    return LOCK['runtime']['cuda_wheel_modern']


def table_freeze(role, tag='cpu', extra=''):
    entry = HASHES['environments'][f'{role}|{installer.role_python(role)}|{tag}']
    return lambda arguments: '\n'.join(f"{n}=={entry['packages'][n]['version']}" for n in ('torch', 'requests')
                                       if n in entry['packages']) + '\n' + extra



def _fetched(call):
    """A successful app download: every requested file appears in the folder."""
    call['folder'].mkdir(parents=True, exist_ok=True)
    return []


def test_app_fetches_unbundled_locked_files_then_uv_installs_offline(run_installer, cuda, capsys):
    """2026-10-28: uv no longer downloads; it installs what the app fetched and verified."""
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main', cuda), prefetch=_fetched)
    (call,) = fake.prefetches
    assert call['folder'] == fake.managed/installer.PYPI_HOUSE
    entry = HASHES['environments'][f'main|3.10.19|{cuda}']
    bundled = {item['sha256'] for item in json.loads((ROOT/'packaging/model_wheels.json').read_text('utf8'))['wheels']}
    locked = {digest for item in entry['packages'].values() for digest in item['sha256']}
    digests = {item['sha256'][0] for item in call['items']}
    assert digests and digests <= locked and not digests & bundled
    assert not any(item['name'].startswith(('torch-', 'torchaudio-')) for item in call['items'])  # PyTorch has its own step
    assert all(item['path'].startswith('packages/') and item['size'] > 0 for item in call['items'])
    assert call['sources'][0] == 'PyPI 官方'  # nothing measured faster in this fixture
    (install,) = fake.installs()
    assert '--no-index' in install and '--index-url' not in install
    assert f"--find-links {call['folder']}" in install and f"--find-links {fake.managed/installer.WHEELHOUSE}" in install
    assert 'mirror-constraints.txt' in install and 'mirror-build-constraints.txt' in install
    assert '离线安装' in capsys.readouterr().out
    assert next(fake.managed.rglob('managed-runtime.json')).is_file()


def test_measuring_a_faster_mirror_moves_the_whole_run_to_mirrors(run_installer, cuda, capsys):
    tencent = next(item['label'] for item in SOURCES['pypi_mirrors'] if 'tencent' in item['url'])
    fake = run_installer('moss,sensevoice', lambda command: False, _quick_freeze(cuda), prefetch=_fetched, fastest=tencent)
    assert fake.prefetches[0]['sources'][0] == tencent
    # PyTorch for main was ordered before the PyPI measurement; MOSS (after it) starts from mirrors.
    assert fake.fetches[0]['sources'][0]['official'] is True
    assert fake.fetches[1]['sources'][0]['official'] is False
    python_installs = [c for c in fake.commands if 'python' in c and 'install' in c and 'pip' not in c]
    assert '--mirror' in python_installs[-1] and '3.12.13' in python_installs[-1]
    assert all('--no-index' in command for command in fake.installs() if '--offline' not in command)
    output = capsys.readouterr().out
    assert '测速结果国内镜像更快' in output and 'PyPI 来源测速' in output


def test_official_choice_measures_but_keeps_official_first(run_installer, monkeypatch):
    monkeypatch.setenv(installer.RUNTIME_SOURCE_ENV, 'official')
    tencent = next(item['label'] for item in SOURCES['pypi_mirrors'] if 'tencent' in item['url'])
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main'), prefetch=_fetched, fastest=tencent)
    assert [ranking['preference'] for ranking in fake.rankings] == ['official']
    assert fake.prefetches[0]['sources'][0] == 'PyPI 官方'


def test_failed_app_download_falls_back_to_uv_with_measured_index_order(run_installer, capsys):
    tencent = next(item for item in SOURCES['pypi_mirrors'] if 'tencent' in item['url'])
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main'), fastest=tencent['label'])
    (install,) = fake.installs()
    assert f"--index-url {tencent['url']}" in install and '--no-index' not in install
    assert '改由 uv 依次从软件源安装' in capsys.readouterr().out


def test_failed_offline_install_falls_back_to_indexes(run_installer):
    fake = run_installer('sensevoice', lambda command: '--no-index' in command, table_freeze('main'), prefetch=_fetched)
    installs = fake.installs()
    assert '--no-index' in installs[0] and '--index-url https://pypi.org/simple' in installs[1]


def test_incomplete_file_table_skips_the_app_download(run_installer, monkeypatch, capsys):
    monkeypatch.setattr(installer, 'load_package_files', lambda root: {})
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main'), prefetch=_fetched)
    assert fake.prefetches == [] and '--index-url https://pypi.org/simple' in fake.installs()[0]
    assert '依赖文件清单不全' in capsys.readouterr().out


def test_file_table_covers_every_locked_pypi_file():
    """scripts/build_runtime_package_files.py must be rerun after the hash table changes."""
    table = json.loads((ROOT/'scripts/runtime_package_files.json').read_text('utf8'))
    for key, entry in HASHES['environments'].items():
        for name, item in entry['packages'].items():
            if '+' in item['version']:
                continue
            for digest in item['sha256']:
                row = table['files'].get(digest)
                assert row, (key, name, item['version'])
                filename, path, size = row
                assert path.startswith('packages/') and path.endswith('/' + filename) and size > 0
                assert filename.lower().replace('_', '-').startswith(name.replace('_', '-'))

def test_official_sources_also_use_the_pinned_hashed_closure(run_installer):
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main'))
    installs = fake.installs()
    assert len(installs) == 1
    assert '--index-url https://pypi.org/simple' in installs[0]
    assert 'torch==2.11.0+cpu' in installs[0] and '--find-links' in installs[0]
    assert '--constraint' in installs[0] and '--only-binary' in installs[0]
    assert not any('--mirror' in c for c in fake.commands)
    assert list(fake.managed.rglob('mirror-constraints.txt'))


def test_failed_official_source_installs_environment_from_hashed_mirrors(run_installer, cuda):
    # The CUDA build was fetched (and verified) into the wheelhouse beforehand,
    # so the mirror resolution needs PyPI mirrors only.
    tag = cuda
    first_mirror, second_mirror = (item['url'] for item in SOURCES['pypi_mirrors'][:2])
    fails = lambda command: 'https://pypi.org/simple' in command or first_mirror in command
    fake = run_installer('sensevoice', fails, table_freeze('main', tag))
    installs = fake.installs()
    assert [call['pins'] for call in fake.fetches] == [[f'torch==2.11.0+{tag}', f'torchaudio==2.11.0+{tag}']]
    wheelhouse = str(fake.managed/installer.WHEELHOUSE)
    assert 'https://pypi.org/simple' in installs[0] and f'--find-links {wheelhouse}' in installs[0]
    mirror = installs[-1]
    assert f'--index-url {second_mirror}' in mirror and f'--find-links {wheelhouse}' in mirror
    assert not any(item['url'].split('{')[0] in mirror for item in SOURCES['pytorch_mirrors'])
    assert 'mirror-constraints.txt' in mirror and 'mirror-build-constraints.txt' in mirror
    assert f'torch==2.11.0+{tag}' in mirror and 'funasr==1.4.1' in mirror
    # The PyPI step was covered by the mirror resolution, not retried officially.
    assert sum('https://pypi.org/simple' in command for command in installs) == 1
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


def test_cuda_build_installs_from_the_verified_wheelhouse_when_official_is_fine(run_installer, cuda):
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main', cuda))
    (call,) = fake.fetches
    assert call['folder'] == fake.managed/installer.WHEELHOUSE and call['version'] == '3.10.19'
    assert call['sources'][0] == {'label': 'PyTorch 官方', 'url': f'https://download.pytorch.org/whl/{cuda}', 'official': True}
    assert [item['url'] for item in call['sources'][1:]] == [item['url'].format(tag=cuda) for item in SOURCES['pytorch_mirrors']]
    installs = fake.installs()
    assert len(installs) == 1
    assert '--index-url https://pypi.org/simple' in installs[0]
    assert f'--find-links {call["folder"]}' in installs[0]
    assert f'torch==2.11.0+{cuda}' in installs[0]
    assert list(fake.managed.rglob('mirror-constraints.txt'))


def _quick_freeze(tag):
    return lambda arguments: f'torch==2.11.0+{tag}\nrequests==2.33.0\n'


def test_slow_official_pytorch_moves_this_and_later_environments_to_mirrors(run_installer, cuda, capsys):
    reason = f'官方 PyTorch 来源只有 0.9 MB/s，{SOURCES["pytorch_mirrors"][0]["label"]} 15.0 MB/s'
    fake = run_installer('moss,sensevoice', lambda command: False, _quick_freeze(cuda),
                         left_official=lambda call: reason if call['sources'][0]['official'] else '')
    assert [call['version'] for call in fake.fetches] == ['3.10.19', '3.12.13']
    assert fake.fetches[0]['sources'][0]['official'] is True
    # The MOSS environment (fetched after main) starts from the mirrors.
    assert fake.fetches[1]['sources'][0]['official'] is False and fake.fetches[1]['sources'][-1]['official'] is True
    installs = fake.installs()
    assert not any('download.pytorch.org' in command or 'https://pypi.org/simple' in command for command in installs)
    assert all(SOURCES['pypi_mirrors'][0]['url'] in command for command in installs if '--offline' not in command)
    offline=[command for command in installs if '--offline' in command]
    assert len(offline)==1 and '--no-index' in offline[0] and '--index-url' not in offline[0]
    output = capsys.readouterr().out
    assert reason in output and SOURCES['pypi_mirrors'][0]['label'] in output
    assert '之后的环境直接先用国内镜像' in output
    python_installs = [c for c in fake.commands if 'python' in c and 'install' in c and 'pip' not in c]
    assert '--mirror' not in python_installs[0] and '3.12.13' in python_installs[-1]
    assert '--mirror' in python_installs[-1]  # the MOSS Python came from a mirror first as well


def test_domestic_download_source_starts_every_runtime_step_from_mirrors(run_installer, monkeypatch, capsys):
    monkeypatch.setenv(installer.RUNTIME_SOURCE_ENV, 'mirror')
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main'))
    python_installs = [c for c in fake.commands if 'python' in c and 'install' in c and 'pip' not in c]
    assert python_installs[0][-2:] == ['--mirror', SOURCES['python_mirrors'][0]['url']]
    installs = fake.installs()
    assert len(installs) == 1 and f"--index-url {SOURCES['pypi_mirrors'][0]['url']}" in installs[0]
    assert not any('download.pytorch.org' in c or 'pypi.org/simple' in c for c in installs)
    assert '已选择国内下载源：运行环境先用国内镜像' in capsys.readouterr().out


def test_domestic_choice_fetches_cuda_pytorch_from_mirrors_first(run_installer, cuda, monkeypatch):
    monkeypatch.setenv(installer.RUNTIME_SOURCE_ENV, 'mirror')
    fake = run_installer('sensevoice', lambda command: False, table_freeze('main', cuda))
    sources = fake.fetches[0]['sources']
    assert [item['official'] for item in sources] == [False] * len(SOURCES['pytorch_mirrors']) + [True]


def test_quiet_uv_step_reports_that_it_is_still_running(run_installer, monkeypatch, capsys):
    from twobyteasr.system import deployment
    monkeypatch.setattr(deployment, 'HEARTBEAT_S', 0.3)
    original = FakeUv.popen

    def slow_popen(self, arguments, **kwargs):
        process = original(self, arguments, **kwargs)
        if 'pip' in arguments and 'install' in arguments:
            done_at = time.monotonic()+1.2
            code = process.returncode
            process.poll = lambda: code if time.monotonic() >= done_at else None
        return process
    monkeypatch.setattr(FakeUv, 'popen', slow_popen)
    run_installer('sensevoice', lambda command: False, table_freeze('main'))
    output = capsys.readouterr().out
    assert '"state": "waiting"' in output and '"waiting": "subprocess"' in output
    assert '"phase": "dependencies_installing"' in output


def test_mirror_install_with_unlisted_package_is_not_published(run_installer):
    fails = lambda command: 'pypi.org/simple' in command
    with pytest.raises(RuntimeError, match='锁定哈希表之外'):
        run_installer('sensevoice', fails, table_freeze('main', extra='injected==1.0'))
    from twobyteasr.system.runtime_registry import load_registry
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


def test_model_with_identical_dependencies_reuses_existing_environment(run_installer):
    first=run_installer('qwen_asr',lambda command:False,table_freeze('main'))
    receipt=next(first.managed.rglob('managed-runtime.json'))
    second=run_installer('qwen_aligner',lambda command:False,table_freeze('main'))
    assert not second.installs()
    assert not any('venv' in command for command in second.commands)
    assert set(json.loads(receipt.read_text('utf8'))['models'])=={'qwen_asr','qwen_aligner'}
    assert len(list(second.managed.rglob('managed-runtime.json')))==1


def test_explicit_repair_keeps_previous_directory_and_ignores_expanded_package_cache(run_installer):
    first=run_installer('qwen_asr',lambda command:False,table_freeze('main'))
    original=next(first.managed.rglob('managed-runtime.json'))
    repair=run_installer('qwen_asr',lambda command:False,table_freeze('main'),repair_roles='main')
    assert original.is_file()
    receipts=list(repair.managed.rglob('managed-runtime.json'))
    assert len(receipts)==2
    assert all('--no-cache' in command for command in repair.installs())
    replacement=next(path for path in receipts if path!=original)
    assert json.loads(replacement.read_text('utf8'))['previous_runtime']==str(original.parent/'Scripts/python.exe')


def test_moss_mirror_path_installs_locked_dependencies_then_builds_source(run_installer):
    fails = lambda command: 'download.pytorch.org' in command or 'https://pypi.org/simple' in command
    fake = run_installer('moss', fails, table_freeze('moss'))
    installs = fake.installs()
    entry = HASHES['environments']['moss|3.12.13|cpu']
    moss_mirror = next(c for c in installs if 'mirror-constraints.txt' in c and 'torch==2.11.0+cpu' in c)
    assert f"librosa=={entry['packages']['librosa']['version']}" in moss_mirror
    build = installs[-1]
    assert '--no-index' in build and '--offline' in build and '--no-deps' in build
    assert '--index-url' not in build and 'mirror-build-constraints.txt' in build
    assert build.endswith('MOSS-Transcribe-Diarize[torch-runtime]')
    # The official MOSS step (default index) was not attempted after the mirror took over.
    assert not any(c.endswith('[torch-runtime]') and '--offline' not in c for c in installs)


def _zip_with(names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in names:
            archive.writestr(name, b'fixture '+name.encode())
    return buffer.getvalue()


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell and curl.exe')
def test_powershell_uv_sources_and_system_proxy():
    work = Path(os.environ.get('TWOBYTEASR_TEST_ROOT') or ROOT/'tmp')/('runtime-fallback-'+uuid.uuid4().hex)
    served = work/'served'
    served.mkdir(parents=True)
    good = _zip_with(['uv.exe', 'uvw.exe'])
    (served/'good.zip').write_bytes(good)
    (served/'bad.zip').write_bytes(_zip_with(['uv.exe']))
    blob = os.urandom(150_000)
    (served/'blob.bin').write_bytes(blob)
    (served/'slow').mkdir()
    (served/'slow/blob.bin').write_bytes(blob)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def copyfile(self, source, outputfile):
            if not self.path.startswith('/slow/'):
                return super().copyfile(source, outputfile)
            for block in iter(lambda: source.read(3000), b''):  # ~30 KB/s
                outputfile.write(block)
                outputfile.flush()
                time.sleep(0.1)
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
                                 '-ListeningPort', str(port), '-WorkDir', str(work), '-Output', str(receipt),
                                 '-BlobSha', hashlib.sha256(blob).hexdigest()],
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
    assert actual['order_auto'] == actual['order_unset'] == ['good', 'dead', 'missing']
    assert actual['order_mirror'] == ['dead', 'missing', 'good']
    assert actual['order_single_fallback'] == ['good']
    assert actual['uv_order_auto']==actual['uv_order_unset']==['domestic','good','dead','missing']
    assert actual['uv_order_mirror']==['domestic','dead','missing','good']
    # A source under the first floor is left after the speed time; alone it is taken in the slower pass.
    assert actual['slow_then_fast_sha'] == actual['only_slow_sha'] == hashlib.sha256(blob).hexdigest()
    assert actual['slow_then_fast_s'] < 4.5 < actual['only_slow_s']


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell')
def test_download_source_choice_sets_the_runtime_source_preference():
    """The workshop passes -Source; ModelScope / HF 镜像 mean domestic runtime sources first,
    Hugging Face 官方 official first, 自动 measuring first."""
    script = (ROOT/'scripts/download_models.ps1').read_text('utf-8-sig')
    statement = next(line.strip() for line in script.splitlines() if line.strip().startswith('$env:2BYTEASR_RUNTIME_SOURCE'))
    assert script.index(statement) > script.index('$Source = switch -Regex ($Source)')
    assert script.index(statement) < script.index('& $backendSetup -ModelKey $backendKeys')
    shell = Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    for source, expected in (('AUTO', 'auto'), ('MODELSCOPE', 'mirror'), ('HF_MIRROR', 'mirror'), ('HF_OFFICIAL', 'official')):
        command = f"$Source='{source}'; {statement}; [Console]::Out.Write($env:2BYTEASR_RUNTIME_SOURCE)"
        result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, text=True, timeout=60)
        assert result.stdout.strip() == expected, (source, result.stdout, result.stderr)
    setup = (ROOT/'scripts/setup_managed_backend.ps1').read_text('utf-8-sig')
    assert '$uvSources=@(Get-UvSources $officialUv $uvFallbacks)' in setup
    assert "Get-PreferredOrder ([pscustomobject]@{label='默认来源';url=''}) @($script:pythonMirrors)" in setup


@pytest.mark.parametrize('corrupt', ['{', '[]', '{"role":"main","models":"qwen_asr"}',
                                    '{"role":"main","models":["unsupported-model"]}',
                                    '{"role":"moss","models":["moss"]}', None])
def test_corrupt_main_history_rebuilds_from_current_request_and_preserves_original(run_installer,capsys,corrupt):
    from twobyteasr.system import runtime_registry
    first=run_installer('qwen_asr,sensevoice',lambda command:False,table_freeze('main'))
    old=Path(runtime_registry.load_registry()['main']['python_executable'])
    receipt=old.parent.parent/'managed-runtime.json'
    if corrupt is None:receipt.unlink()
    else:receipt.write_text(corrupt,'utf8')
    old_python=old.read_bytes()
    sentinel=first.managed.parent/'project-media-key-model-canary'
    sentinel.write_bytes(b'owned fixture data must not change')
    run_installer('qwen_asr',lambda command:False,table_freeze('main'),repair_roles='main')
    current=Path(runtime_registry.load_registry()['main']['python_executable'])
    assert current!=old and old.read_bytes()==old_python
    assert not receipt.exists() if corrupt is None else receipt.read_text('utf8')==corrupt
    saved=json.loads((current.parent.parent/'managed-runtime.json').read_text('utf8'))
    assert saved['models']==['qwen_asr']
    assert saved['historical_models_complete'] is False
    assert saved['previous_runtime']==str(old)
    assert any(x['role']=='main' and x['historical_models']=='unavailable' for x in saved['previous_receipt_issues'])
    assert '历史模型集合无法恢复' in capsys.readouterr().out
    assert sentinel.read_bytes()==b'owned fixture data must not change'


def test_normal_prepare_does_not_reparse_or_overwrite_a_damaged_receipt(run_installer):
    from twobyteasr.system import runtime_registry
    run_installer('qwen_asr',lambda command:False,table_freeze('main'))
    old=Path(runtime_registry.load_registry()['main']['python_executable'])
    receipt=old.parent.parent/'managed-runtime.json';receipt.write_text('{','utf8')
    run_installer('qwen_asr',lambda command:False,table_freeze('main'))
    assert Path(runtime_registry.load_registry()['main']['python_executable'])!=old
    assert receipt.read_text('utf8')=='{' and old.is_file()


def test_only_moss_repair_survives_bad_main_history_without_republishing_main(run_installer):
    from twobyteasr.system import runtime_registry
    run_installer('qwen_asr,moss',lambda command:False,_quick_freeze('cpu'))
    before=runtime_registry.load_registry()
    main=Path(before['main']['python_executable'])
    receipt=main.parent.parent/'managed-runtime.json';receipt.write_text('{','utf8')
    run_installer('moss',lambda command:False,_quick_freeze('cpu'),repair_roles='moss')
    after=runtime_registry.load_registry()
    assert after['main']==before['main'] and receipt.read_text('utf8')=='{'
    assert after['moss']['python_executable']!=before['moss']['python_executable']
    saved=json.loads((Path(after['moss']['root'])/'managed-runtime.json').read_text('utf8'))
    assert saved['models']==['moss']
    assert any(x['role']=='main' for x in saved['previous_receipt_issues'])


def test_failed_new_generation_keeps_original_pointer_and_damaged_receipt(run_installer):
    from twobyteasr.system import runtime_registry
    run_installer('qwen_asr',lambda command:False,table_freeze('main'))
    before=runtime_registry.registry_path().read_bytes()
    old=Path(runtime_registry.load_registry()['main']['python_executable'])
    receipt=old.parent.parent/'managed-runtime.json';receipt.write_text('{','utf8')
    with pytest.raises(subprocess.CalledProcessError):
        run_installer('qwen_asr',lambda command:'validate_managed_runtime.py' in command,
                      table_freeze('main'),repair_roles='main')
    assert runtime_registry.registry_path().read_bytes()==before
    assert old.is_file() and receipt.read_text('utf8')=='{'
