"""macOS runtimes: locked PyPI files fetched by the app, pip installs offline (2026-10-28).

A Mac user in mainland China waited minutes on files.pythonhosted.org
("Resuming download torch-2.11.0-cp310-cp310-macosx_11_0_arm64.whl (262 kB/80.5 MB)")
although the download source was ModelScope. No internet and no Mac here: the
download itself and pip are stand-ins; the real downloader has its own tests.
"""
import json
from pathlib import Path
import re
import subprocess

import pytest
from packaging.tags import compatible_tags, cpython_tags, mac_platforms

from twobyteasr.local_models import macos_model_prepare as prepare
from twobyteasr.system import runtime_package_download as downloads

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT/'scripts/runtime_package_files.json').read_text('utf8'))
PIN = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;\\]+)')


def mac_tags(python, macos):
    platforms = list(mac_platforms(macos, 'arm64'))
    interpreter = f'cp{python[0]}{python[1]}'
    return [str(tag) for tag in [*cpython_tags(python, [interpreter], platforms),
                                 *compatible_tags(python, interpreter, platforms)]]


def pins(path, seen=None):
    seen = set() if seen is None else seen
    if path in seen:
        return {}
    seen.add(path)
    found = {}
    for line in path.read_text('utf8').splitlines():
        include = re.match(r'^-(r|c)\s+(\S+)', line.strip())
        if include:
            found.update(pins(path.parent/include.group(2), seen))
            continue
        match = PIN.match(line)
        if match:
            found[re.sub(r'[-_.]+', '-', match.group(1)).lower()] = match.group(2)
    return found


@pytest.fixture(autouse=True)
def default_source():
    prepare._RUNTIME_SOURCES.update(preference='auto', pypi=None)
    yield
    prepare._RUNTIME_SOURCES.update(preference='auto', pypi=None)


@pytest.mark.parametrize('key,requirement', [('main|3.10', 'requirements-cpu.txt'), ('moss|3.12', 'requirements-moss.txt'),
                                             ('mlx|3.10', 'requirements-mlx.txt')])
def test_file_table_matches_the_macos_requirement_files(key, requirement):
    """scripts/build_runtime_package_files.py must be rerun after these files change."""
    bundled = set(TABLE['macos_bundled_source_wheels'])
    expected = {name: version for name, version in pins(ROOT/'packaging/macos'/requirement).items() if name not in bundled}
    table = TABLE['macos'][key]['packages']
    assert {name: item['version'] for name, item in table.items()} == expected
    for name, item in table.items():
        for digest in item['sha256']:
            filename, path, size = TABLE['files'][digest]
            assert path.startswith('packages/') and path.endswith('/' + filename) and size > 0


@pytest.mark.parametrize('key,python', [('main|3.10', (3, 10)), ('moss|3.12', (3, 12)), ('mlx|3.10', (3, 10))])
@pytest.mark.parametrize('macos', [(14, 0), (15, 5), (26, 0)])
def test_every_locked_package_has_a_wheel_for_each_supported_macos(key, python, macos):
    supported = mac_tags(python, macos)
    for name, item in TABLE['macos'][key]['packages'].items():
        candidates = [(digest, TABLE['files'][digest][0]) for digest in item['sha256']]
        assert downloads.choose_for_tags(candidates, supported), (key, macos, name)


def test_torch_for_the_screenshot_runtime_is_the_reviewed_wheel():
    native = json.loads((ROOT/'packaging/macos/native-dependencies.lock.json').read_text('utf8'))
    for name, spec in native['critical_wheel_availability'].items():
        item = TABLE['macos']['main|3.10']['packages'][re.sub(r'[-_.]+', '-', name).lower()]
        candidates = [(digest, TABLE['files'][digest][0]) for digest in item['sha256']]
        chosen = downloads.choose_for_tags(candidates, mac_tags((3, 10), (14, 0)))
        assert chosen in {wheel['sha256'] for wheel in spec['arm64_cp310_or_universal']}, name


def test_locked_packages_are_chosen_for_this_mac_and_fetched(tmp_path, monkeypatch):
    sonoma = mac_tags((3, 12), (14, 0))
    monkeypatch.setattr(prepare, '_supported_tags', lambda python, environment: sonoma)
    monkeypatch.setattr(prepare, '_pypi_sources', lambda path: [{'label': '腾讯云', 'url': 'https://m.invalid'}])
    fetched = []
    monkeypatch.setattr(downloads, 'fetch_files', lambda folder, items, sources, **kw: fetched.append((folder, items, sources)))
    house = prepare.fetch_locked_packages(ROOT, tmp_path, tmp_path/'bin/python', {}, 'moss|3.12')
    assert house == tmp_path/prepare.PYPI_HOUSE and house.is_dir()
    (folder, items, sources), = fetched
    assert folder == house and sources[0]['label'] == '腾讯云'
    names = {item['package'] for item in items}
    assert names == set(TABLE['macos']['moss|3.12']['packages'])
    numpy = next(item for item in items if item['package'] == 'numpy')
    assert numpy['name'].endswith('macosx_14_0_arm64.whl')  # Sonoma takes the 14.0 build, as pip would
    assert all(item['path'].startswith('packages/') for item in items)


def test_a_build_without_the_table_or_a_failed_fetch_leaves_pip_to_the_indexes(tmp_path, monkeypatch, capsys):
    assert prepare.fetch_locked_packages(tmp_path, tmp_path, tmp_path/'python', {}, 'main|3.10') is None
    monkeypatch.setattr(prepare, '_supported_tags', lambda python, environment: mac_tags((3, 10), (14, 0)))
    monkeypatch.setattr(prepare, '_pypi_sources', lambda path: [{'label': 'x', 'url': 'https://x.invalid'}])
    def fail(*args, **kwargs):
        raise downloads.SourcesExhausted('every source failed')
    monkeypatch.setattr(downloads, 'fetch_files', fail)
    assert prepare.fetch_locked_packages(ROOT, tmp_path, tmp_path/'python', {}, 'main|3.10') is None
    assert '改由 pip 依次从软件源安装' in capsys.readouterr().out


def test_hashed_install_uses_the_verified_files_offline_first(tmp_path, monkeypatch):
    seen = []
    def run(command, *, cwd, environment):
        seen.append([str(item) for item in command])
    monkeypatch.setattr(prepare, 'run', run)
    prepare.run_hashed_pip_install(['python', '-m', 'pip', 'install', '--require-hashes', '-r', 'r.txt'],
                                   cwd=tmp_path, environment={}, house=tmp_path/'house')
    assert seen == [['python', '-m', 'pip', 'install', '--require-hashes', '-r', 'r.txt', '--no-index',
                     '--find-links', str(tmp_path/'house')]]


def test_a_failed_offline_install_tries_the_indexes_in_measured_order(tmp_path, monkeypatch):
    prepare._RUNTIME_SOURCES['pypi'] = [{'label': '腾讯云', 'url': 'https://mirrors.cloud.tencent.com/pypi'},
                                        {'label': 'PyPI 官方', 'url': 'https://files.pythonhosted.org', 'official': True}]
    seen = []
    def run(command, *, cwd, environment):
        seen.append(command[-1] if '--no-index' not in command else 'offline')
        if '--no-index' in command:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(prepare, 'run', run)
    prepare.run_hashed_pip_install(['python', '-m', 'pip', 'install', '--require-hashes', '-r', 'r.txt'],
                                   cwd=tmp_path, environment={}, house=tmp_path)
    assert seen == ['offline', 'https://mirrors.cloud.tencent.com/pypi/simple']


def test_domestic_download_source_puts_mirrors_first_without_measuring(monkeypatch):
    monkeypatch.setattr(downloads, 'measure_sources', lambda *a, **k: pytest.fail('a fixed preference does not measure'))
    prepare._use_download_source('MODELSCOPE')
    assert prepare._pip_index_urls()[-1] == 'https://pypi.org/simple'
    urls = prepare._bootstrap_urls('https://github.com/astral-sh/python-build-standalone/releases/download/1/x.tar.gz')
    assert 'github.com' in urls[-1] and 'github.com' not in urls[0]
    prepare._use_download_source('HF_OFFICIAL')
    assert prepare._pip_index_urls()[0] == 'https://pypi.org/simple'
    assert 'github.com' in prepare._bootstrap_urls('https://github.com/astral-sh/uv/releases/download/0.11.7/uv.tar.gz')[0]


def test_automatic_source_measures_bootstrap_hosts(monkeypatch, capsys):
    def measure(sources, path, **kwargs):
        return [dict(rate=1e6 if 'npmmirror' in item['url'] else 0.0, bytes=1, error='') for item in sources]
    monkeypatch.setattr(downloads, 'measure_sources', measure)
    urls = prepare._bootstrap_urls('https://github.com/astral-sh/python-build-standalone/releases/download/1/x.tar.gz')
    assert 'npmmirror' in urls[0] and 'github.com' in urls[1]
    assert '启动文件来源测速' in capsys.readouterr().out


def test_main_runtime_installs_offline_from_the_fetched_files(tmp_path, monkeypatch):
    """ensure_main_runtime: --no-index with the app's folder, the bundled wheelhouse first."""
    calls = []
    house = tmp_path/'house'
    monkeypatch.setattr(prepare, 'fetch_locked_packages', lambda *a: house)
    def run(command, **kwargs):
        calls.append([str(item) for item in command])
        if '--no-index' in command and fail_offline:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(prepare, 'run', run)
    fail_offline = False
    _run_main_install(tmp_path, monkeypatch)
    install = next(command for command in calls if '--force-reinstall' in command)
    assert '--no-index' in install and install[install.index('--no-index') + 2] == str(house)
    assert install[install.index('--find-links') + 1] == str(tmp_path/'wheelhouse')
    calls.clear()
    fail_offline = True
    _run_main_install(tmp_path, monkeypatch)
    installs = [command for command in calls if '--force-reinstall' in command]
    assert '--no-index' in installs[0] and 'https://pypi.org/simple' in installs[1]


def _run_main_install(tmp_path, monkeypatch):
    from twobyteasr.system import runtime_registry
    root = tmp_path/'resources'
    (root/'packaging/macos').mkdir(parents=True, exist_ok=True)
    for name in ('requirements-cpu.txt', 'requirements-gui.txt', 'constraints-cpu.txt', 'source-wheels.lock.json'):
        (root/'packaging/macos'/name).write_text('owned==1\n')
    (root/'packaging/macos/native-dependencies.lock.json').write_text(json.dumps({'critical_wheel_availability': {}}))
    monkeypatch.setattr(runtime_registry, 'resolve_runtime_python', lambda *a, **k: '')
    monkeypatch.setattr(prepare, 'check_runtime', lambda *a, **k: False)
    monkeypatch.setattr('twobyteasr.system.macos_wheels.verify_wheelhouse', lambda root: tmp_path/'wheelhouse')
    monkeypatch.setattr(prepare, '_bootstrap_interpreter', lambda *a, **k: (tmp_path/'uv', tmp_path/'python3.10'))
    monkeypatch.setattr(prepare, 'download_archive', lambda *a: tmp_path/'pip.whl')
    monkeypatch.setattr(prepare, 'verify_runtime_binaries', lambda *a, **k: None)
    def report(*a, **k):
        raise RuntimeError('stop after the install command')
    monkeypatch.setattr('scripts.macos_dependency_contract.verify_native_wheels', report)
    for path in (tmp_path/'managed').rglob('pip-install.json'):
        path.unlink()
    lock = {'target': 'darwin-arm64', 'uv': {'version': 'fixed'}, 'pip': {'version': 'fixed'},
            'python': {'version': '3.10.19', 'build': 'fixed'}}
    with pytest.raises((RuntimeError, OSError)):
        prepare.ensure_main_runtime(root, tmp_path/'managed', lock, {}, {})
