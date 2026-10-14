# SPDX-License-Identifier: GPL-3.0-only
"""MOSS and FireRed in the Mac model workshop, on the Apple GPU (2026-10-14).

Runs on Windows with the host faked: the plan gates, the workshop state and
routing, and the preparation order (readiness before registration). The real
run on a Mac is the GitHub macOS job.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr import hardware, recognition_choices as choices
from twobyteasr import macos_model_prepare as prepare

APPLE = choices.HostProfile('darwin', 'arm64', False, True, False, True)
INTEL_MAC = choices.HostProfile('darwin', 'x86_64', False, True, False, False)
NO_GPU_PC = choices.HostProfile('win32', 'amd64', False, True, False, False)
GPU_PC = choices.HostProfile('win32', 'amd64', True, True, False, True)
MAC_MODELS = {'moss', 'firered_vad', 'speaker_embedding', 'firered_aed'}


def test_moss_and_firered_are_not_blocked_on_apple_silicon_only():
    for role, backend in (('primary', 'moss'), ('primary', 'firered'), ('timeline', 'local')):
        assert choices.unavailable_on_host(role, backend, APPLE) == ''
        assert choices.unavailable_on_host(role, backend, INTEL_MAC) == '只能在 Apple Silicon Mac 上运行'
        assert choices.unavailable_on_host(role, backend, NO_GPU_PC) == '需要 NVIDIA 显卡'
        assert choices.unavailable_on_host(role, backend, GPU_PC) == ''
    # Other CUDA models keep their limit on a Mac.
    assert choices.unavailable_on_host('primary', 'qwen_local', APPLE) == '需要 NVIDIA 显卡'
    assert choices.unavailable_on_host('primary', 'firered_llm', APPLE) == '需要 NVIDIA 显卡'
    assert choices.unavailable_on_host('review', 'local', APPLE) == '需要 NVIDIA 显卡'


def test_cloud_followups_keep_firered_timeline_on_a_prepared_mac():
    models = {'primary_asr_backend': 'api', 'firered_asr_backend': 'local', 'qwen_asr_backend': 'off'}
    patch, notes = choices.cloud_followups(models, {'firered_aed'}, APPLE)
    assert patch == {} and notes == []
    # Without FireRed prepared the Mac falls back, and says why in Mac terms.
    patch, notes = choices.cloud_followups(models, set(), APPLE)
    assert patch['firered_asr_backend'] == 'off'
    assert 'Apple 芯片 GPU' in notes[0] and 'NVIDIA' not in notes[0]
    patch, _ = choices.cloud_followups(models, {'firered_aed'}, NO_GPU_PC)
    assert patch['firered_asr_backend'] == 'off'


def test_mac_plan_offers_moss_and_firered_when_prepared():
    settings = {'models': {'qwen_asr_api_provider': 'qwen31_filetrans'}}
    options = {o.key: o for o in choices.plan_options(settings, MAC_MODELS, APPLE, {})}
    plan = options['apple_gpu_local']
    assert plan.available and plan.patch == {'primary_asr_backend': 'moss', 'firered_asr_backend': 'local',
                                             'qwen_asr_backend': 'off'}
    missing_runtime = choices.HostProfile('darwin', 'arm64', False, True, False, False)
    plan = {o.key: o for o in choices.plan_options(settings, MAC_MODELS, missing_runtime, {})}['apple_gpu_local']
    assert not plan.available and '模型工坊' in plan.reason
    plan = {o.key: o for o in choices.plan_options(settings, MAC_MODELS, INTEL_MAC, {})}['apple_gpu_local']
    assert not plan.available and 'Intel' in plan.reason
    assert 'apple_gpu_local' not in {o.key for o in choices.plan_options(settings, MAC_MODELS, GPU_PC, {})}


def test_run_disclosure_names_the_apple_gpu_on_a_mac(monkeypatch):
    settings = {'models': {'primary_asr_backend': 'moss', 'firered_asr_backend': 'local', 'qwen_asr_backend': 'off'}}
    monkeypatch.setattr(choices.sys, 'platform', 'darwin')
    info = choices.run_disclosure(settings)
    assert 'MOSS（Apple 芯片 GPU）' in info['local'] and 'Apple 芯片 GPU' in info['timestamps']
    assert info['uploads'] == []
    monkeypatch.setattr(choices.sys, 'platform', 'win32')
    assert 'NVIDIA' in choices.run_disclosure(settings)['timestamps']


@pytest.mark.parametrize('system,machine,expected', [
    ('darwin', 'arm64', []),
    ('darwin', 'x86_64', ['MOSS 主力转写', 'FireRed 字级时间轴']),
    ('win32', 'AMD64', ['MOSS 主力转写', 'FireRed 字级时间轴']),
])
def test_cuda_requirement_skips_moss_and_firered_on_apple_silicon(monkeypatch, system, machine, expected):
    monkeypatch.setattr(hardware.sys, 'platform', system)
    monkeypatch.setattr('platform.machine', lambda: machine)
    settings = {'models': {'primary_asr_backend': 'moss', 'firered_asr_backend': 'local', 'qwen_asr_backend': 'off'}}
    assert hardware.selected_cuda_components(settings) == expected
    # Qwen3-ASR local review still needs CUDA on a Mac.
    settings['models']['qwen_asr_backend'] = 'local'
    assert hardware.selected_cuda_components(settings)[-1] == 'Qwen3-ASR 本地文字复核'


# ----------------------------------------------------------------- workshop


def _darwin(monkeypatch, workshop, machine):
    monkeypatch.setattr(workshop, 'sys', SimpleNamespace(platform='darwin', frozen=True,
                                                         executable='/Applications/2ByteASR.app/Contents/MacOS/2ByteASR'))
    monkeypatch.setattr('platform.machine', lambda: machine)


@pytest.mark.parametrize('key', ['moss', 'firered'])
def test_workshop_cards_are_downloadable_on_apple_silicon_and_named_for_the_gpu(monkeypatch, key):
    from twobyteasr import model_workshop as workshop
    model = next(item for item in workshop.MODELS if item.key == key)
    page = SimpleNamespace(browser_role=model.role, runtime_settings={'models': {}}, _registry=None, _installed=set(),
                           _active_download_dialog=lambda download_key: None, _state_memo=None)
    _darwin(monkeypatch, workshop, 'arm64')
    assert workshop.ModelWorkshopPage._compute_model_state(page, model, model.role) == 'missing'
    assert workshop.model_mode_text(model) == workshop.MAC_GPU_MODE
    # Files present but no prepared runtime: the card offers the repair, not "installed".
    page._installed = set(model.install_keys)
    monkeypatch.setattr('twobyteasr.runtime_registry.resolve_runtime_python', lambda role, register=True: '')
    assert workshop.ModelWorkshopPage._compute_model_state(page, model, model.role) == 'runtime_missing'
    _darwin(monkeypatch, workshop, 'x86_64')
    page._installed = set()
    assert workshop.ModelWorkshopPage._compute_model_state(page, model, model.role) == 'platform_unavailable'
    assert workshop.ModelWorkshopPage._action_text(SimpleNamespace(_removing=set()), model,
                                                   'platform_unavailable') == ('仅限 Apple Silicon Mac', False)
    monkeypatch.setattr(workshop, 'sys', SimpleNamespace(platform='win32'))
    assert workshop.model_mode_text(model) == model.mode


def test_moss_card_prepares_through_the_dedicated_app_child(monkeypatch, tmp_path):
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    from twobyteasr import model_workshop as workshop
    app = QApplication.instance() or QApplication([])
    model = next(item for item in workshop.MODELS if item.key == 'moss')
    _darwin(monkeypatch, workshop, 'arm64')
    # The card sends only its download key (ModelWorkshopPage._download); prepare_local adds the rest.
    dialog = workshop.ModelDownloadDialog(tmp_path / '只读 资源', model, download_keys=(model.download_key,))
    assert dialog.start_button.property('platformPrepare') == 'mac-gpu'
    calls = {}
    dialog.process = SimpleNamespace(
        state=lambda: QProcess.ProcessState.NotRunning,
        setProcessEnvironment=lambda env: calls.update(environment=env),
        setWorkingDirectory=lambda cwd: calls.update(cwd=cwd),
        start=lambda program, args: calls.update(program=program, args=args),
        waitForStarted=lambda timeout: True)
    dialog.start_button.click()
    assert calls['program'] == workshop.sys.executable
    assert calls['args'][0] == '--macos-prepare-local'
    assert calls['args'][calls['args'].index('--keys') + 1] == 'moss'
    assert calls['environment'].value('_PYI_RESET_ENVIRONMENT') == '1'
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_intel_mac_never_starts_a_moss_download(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication
    from twobyteasr import model_workshop as workshop
    app = QApplication.instance() or QApplication([])
    model = next(item for item in workshop.MODELS if item.key == 'firered')
    _darwin(monkeypatch, workshop, 'x86_64')
    dialog = workshop.ModelDownloadDialog(tmp_path, model, download_keys=model.install_keys)
    started = []
    dialog._start_macos_local = lambda: started.append('local')
    errors = []
    dialog._finish_with_error = errors.append
    dialog.start()
    assert started == [] and 'Apple 芯片' in str(errors[0])
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


# ----------------------------------------------------------------- preparation


def _fake_root(tmp_path):
    root = tmp_path / '资源 应用'
    source = root / prepare.MOSS_SOURCE
    (source / 'app').mkdir(parents=True)
    (source / '__init__.py').write_text('from .transcript_parser import parse_transcript\n', encoding='utf8')
    (source / 'app/server.py').write_text('# demo web server\n', encoding='utf8')
    (source / '__pycache__').mkdir()
    (source / '__pycache__/stale.cpython-312.pyc').write_bytes(b'stale')
    (root / 'packaging/macos').mkdir(parents=True)
    (root / 'packaging/macos/requirements-moss.txt').write_text('owned==1 --hash=sha256:' + 'a' * 64 + '\n')
    lock = {'target': 'darwin-arm64', 'uv': {'version': 'fixed', 'member': 'uv/uv'}, 'pip': {'version': 'fixed'},
            'python': {'version': '3.10.19', 'build': 'fixed'}, 'python312': {'version': '3.12.13', 'build': 'fixed'}}
    (root / 'packaging/macos/bootstrap.lock.json').write_text(json.dumps(lock))
    return root


def test_moss_source_is_copied_whole_without_bytecode_and_reused_when_unchanged(tmp_path):
    root = _fake_root(tmp_path)
    runtime = tmp_path / 'runtime'
    digest = prepare.install_moss_source(root, runtime)
    target = runtime / prepare.MOSS_SITE_PACKAGES / 'moss_transcribe_diarize'
    assert (target / '__init__.py').is_file() and not (target / '__pycache__').exists()
    marker = target / 'marker'
    marker.write_text('kept while unchanged')
    assert prepare.install_moss_source(root, runtime) == digest and marker.exists()
    (root / prepare.MOSS_SOURCE / '__init__.py').write_text('# updated build\n', encoding='utf8')
    assert prepare.install_moss_source(root, runtime) != digest
    assert not marker.exists() and (target / '__init__.py').read_text(encoding='utf8') == '# updated build\n'


def test_moss_runtime_never_reuses_or_writes_into_a_foreign_environment(tmp_path, monkeypatch):
    from twobyteasr import runtime_registry
    root = _fake_root(tmp_path)
    managed = tmp_path / 'profile/runtimes'
    foreign = tmp_path / 'developer-venv/bin/python'
    foreign.parent.mkdir(parents=True)
    foreign.write_text('developer interpreter')
    monkeypatch.setattr(runtime_registry, 'resolve_runtime_python', lambda *a, **k: str(foreign))
    monkeypatch.setattr(prepare, 'check_moss_runtime', lambda *a, **k: True)
    built = []
    def bootstrap(managed_root, lock, environment, *, python='python'):
        built.append(python)
        raise RuntimeError('stop after choosing to build')
    monkeypatch.setattr(prepare, '_bootstrap_interpreter', bootstrap)
    with pytest.raises(RuntimeError, match='stop after'):
        prepare.ensure_moss_runtime(root, managed, json.loads((root / 'packaging/macos/bootstrap.lock.json').read_text()),
                                    {}, {'phase': 'preparing'})
    assert built == ['python312']
    assert not (tmp_path / 'developer-venv/lib').exists()


@pytest.fixture
def mac_prepare(tmp_path, monkeypatch):
    from twobyteasr import runtime_paths, runtime_registry, repository_download, model_integrity
    root = _fake_root(tmp_path)
    monkeypatch.setattr(prepare, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(prepare.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(prepare, 'physical_memory_bytes', lambda: 16 * 10**9)
    monkeypatch.setattr(runtime_paths, 'user_data_root', lambda: tmp_path / 'profile')
    events = []
    monkeypatch.setattr(runtime_registry, 'register_runtime', lambda role, python, **k: events.append(('register', role)))
    monkeypatch.setattr(prepare, 'ensure_main_runtime', lambda *a, **k: (events.append(('main', k.get('models'))),
                                                                          tmp_path / 'main/bin/python')[1])
    monkeypatch.setattr(prepare, 'ensure_moss_runtime', lambda *a, **k: (events.append(('moss',)),
                                                                          tmp_path / 'moss/bin/python')[1])
    monkeypatch.setattr(model_integrity, 'locked_model', lambda key, root=None: {'path': 'models/' + key})
    monkeypatch.setattr(model_integrity, 'verify_model_files', lambda key, destination, root=None: events.append(('verify', key)))
    monkeypatch.setattr(repository_download, 'download_model', lambda **k: events.append(('download', k['model_key'])))
    commands = []
    def run(command, *, cwd, environment):
        commands.append((list(map(str, command)), dict(environment)))
        key = str(command[command.index('--model') + 1])
        events.append(('ready', key))
        if key == state['fail']:
            raise RuntimeError('readiness failed for ' + key)
    state = {'fail': ''}
    monkeypatch.setattr(prepare, 'run', run)
    return SimpleNamespace(root=root, models=tmp_path / '模型 目录', events=events, commands=commands, state=state)


def test_local_preparation_registers_only_after_every_model_ran(mac_prepare):
    keys = ['moss', 'firered_vad', 'speaker_embedding', 'firered_aed']
    prepare.prepare_local(mac_prepare.root, models=mac_prepare.models, source='HF_OFFICIAL', keys=keys)
    events = mac_prepare.events
    assert events[0] == ('main', tuple(keys)) and events[1] == ('moss',)
    ready = [event[1] for event in events if event[0] == 'ready']
    assert ready == ['firered_vad', 'speaker_embedding', 'firered_aed', 'moss']   # small models first
    assert events[-2:] == [('register', 'main'), ('register', 'moss')]
    assert max(i for i, e in enumerate(events) if e[0] == 'ready') < events.index(('register', 'main'))
    command, environment = mac_prepare.commands[-1]
    assert command[-1] == '--force' and command[2].endswith('validate_prepared_model.py')
    assert environment['TWOBYTEASR_MOSS_PYTHON'].endswith(str(Path('moss/bin/python')))
    assert environment['TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY'] == '1'
    assert '2BYTEASR_CPU_ONLY' not in environment
    assert Path(environment['2BYTEASR_MODEL_ROOT']) == mac_prepare.models.resolve()


def test_failed_readiness_keeps_previous_registration(mac_prepare, capsys):
    mac_prepare.state['fail'] = 'moss'
    with pytest.raises(RuntimeError, match='readiness failed'):
        prepare.prepare_local(mac_prepare.root, models=mac_prepare.models, source='AUTO',
                              keys=['moss', 'firered_vad', 'speaker_embedding'])
    assert not [e for e in mac_prepare.events if e[0] == 'register']
    assert '"phase": "model_loading"' in capsys.readouterr().out


def test_moss_card_brings_its_vad_and_speaker_models(mac_prepare):
    prepare.prepare_local(mac_prepare.root, models=mac_prepare.models, source='AUTO', keys=['moss'])
    assert [e[1] for e in mac_prepare.events if e[0] == 'download'] == ['moss', 'firered_vad', 'speaker_embedding']
    assert [e[1] for e in mac_prepare.events if e[0] == 'ready'] == ['firered_vad', 'speaker_embedding', 'moss']


def test_firered_alone_needs_no_moss_runtime(mac_prepare):
    prepare.prepare_local(mac_prepare.root, models=mac_prepare.models, source='AUTO', keys=['firered_aed'])
    assert ('moss',) not in mac_prepare.events
    assert [e for e in mac_prepare.events if e[0] == 'register'] == [('register', 'main')]
    assert 'TWOBYTEASR_MOSS_PYTHON' not in mac_prepare.commands[-1][1]


def test_local_preparation_refuses_unknown_keys_and_other_hosts(mac_prepare, monkeypatch):
    with pytest.raises(ValueError):
        prepare.prepare_local(mac_prepare.root, models=mac_prepare.models, source='AUTO', keys=['qwen_asr'])
    monkeypatch.setattr(prepare.platform, 'machine', lambda: 'x86_64')
    with pytest.raises(RuntimeError, match='Apple 芯片'):
        prepare.prepare_local(mac_prepare.root, models=mac_prepare.models, source='AUTO', keys=['moss'])


def test_packaged_moss_requirements_are_hash_pinned_like_windows():
    root = Path(__file__).resolve().parents[1]
    text = (root / 'packaging/macos/requirements-moss.txt').read_text(encoding='utf8')
    pins = {}
    for line in text.splitlines():
        if line and not line.startswith((' ', '#', '-')):
            name, _, version = line.split()[0].partition('==')
            pins[name] = version
    assert pins['torch'] == '2.11.0' and pins['torchaudio'] == '2.11.0' and pins['transformers'] == '5.14.1'
    assert not {'fastapi', 'uvicorn', 'pydantic'} & set(pins)
    windows = json.loads((root / 'scripts/runtime_package_hashes.json').read_text(encoding='utf8'))
    windows = {name: item['version'] for name, item in windows['environments']['moss|3.12.13|cpu']['packages'].items()}
    for name, version in pins.items():
        if name in windows and name not in {'torch', 'torchaudio'}:
            assert windows[name] == version, name
    blocks = [block for block in text.split('\n') if block and not block.startswith((' ', '#'))]
    assert all('\\' in block for block in blocks if '==' in block)   # every pin is followed by hashes
    lock = json.loads((root / 'packaging/macos/bootstrap.lock.json').read_text(encoding='utf8'))
    assert lock['python312']['version'] == '3.12.13' and len(lock['python312']['sha256']) == 64


def test_moss_uses_bfloat16_on_the_apple_gpu(monkeypatch):
    import moss_worker
    fake = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False),
                           backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
                           device=lambda name: name, bfloat16='bf16', float32='fp32')
    monkeypatch.setattr(moss_worker.sys, 'platform', 'darwin')
    assert moss_worker.resolve_device(fake, 'auto') == ('mps', 'mps', 'bf16')
    assert moss_worker.resolve_device(fake, 'cpu') == ('cpu', 'cpu', 'fp32')
    monkeypatch.setattr(moss_worker.sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='CUDA'):
        moss_worker.resolve_device(fake, 'auto')


def test_bootstrap_archive_falls_back_to_a_mirror_with_the_same_bytes(tmp_path, monkeypatch):
    import hashlib
    data = b'locked archive bytes'
    spec = dict(sha256=hashlib.sha256(data).hexdigest(), url='https://github.com/x/archive.tar.gz')
    attempts = []
    def fetch(url, pending, context):
        attempts.append(url)
        if 'github.com' in url:
            raise ConnectionError('refused')
        if 'slow' in url:
            raise TimeoutError('too slow')
        pending.write_bytes(b'tampered' if 'bad' in url else data)   # a wrong file must not be accepted
    monkeypatch.setattr(prepare, '_bootstrap_urls', lambda url: [url, 'https://slow.invalid/a', 'https://bad.invalid/a',
                                                                 'https://good.invalid/a'])
    monkeypatch.setattr(prepare, '_fetch', fetch)
    monkeypatch.setattr(prepare, 'emit', lambda *a, **k: None)
    path = prepare.download_archive(spec, tmp_path / 'cache')
    assert path.read_bytes() == data
    assert [a.split('/')[2] for a in attempts] == ['github.com', 'slow.invalid', 'bad.invalid', 'good.invalid']
    assert not list((tmp_path / 'cache').rglob('*.pending'))


def test_hashed_pip_install_tries_the_next_index_only_on_failure(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setattr(prepare, '_pip_index_urls', lambda: ['https://pypi.org/simple', 'https://mirror.invalid/simple'])
    seen = []
    def run(command, *, cwd, environment):
        seen.append(command[-1])
        if 'pypi.org' in command[-1]:
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(prepare, 'run', run)
    prepare.run_hashed_pip_install(['python', '-m', 'pip', 'install', '--require-hashes', '-r', 'r.txt'],
                                   cwd=tmp_path, environment={})
    assert seen == ['https://pypi.org/simple', 'https://mirror.invalid/simple']
    with pytest.raises(AssertionError):
        prepare.run_hashed_pip_install(['python', '-m', 'pip', 'install', '-r', 'r.txt'], cwd=tmp_path, environment={})


def test_moss_runtime_check_does_not_import_speechbrain(tmp_path, monkeypatch):
    # speechbrain 1.0.3 calls torchaudio.list_audio_backends (gone in 2.11) on import; the app
    # patches it before use and moss_worker never imports it. The first Mac run failed here.
    python = tmp_path / 'bin/python'
    python.parent.mkdir()
    python.write_text('interpreter')
    seen = {}
    def run(command, **kwargs):
        seen['probe'] = command[-1]
        return SimpleNamespace(returncode=0, stdout='{"python": "3.12.13", "mps": true}', stderr='')
    monkeypatch.setattr(prepare.subprocess, 'run', run)
    assert prepare.check_moss_runtime(python, tmp_path)
    assert 'speechbrain' not in seen['probe'] and 'moss_transcribe_diarize' in seen['probe']


def test_firered_feature_wrapper_does_not_read_the_shadowed_args():
    # Inside TimedFeatures.__call__(self, *args) the name ``args`` is the call's tuple, not argparse.
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'firered_aed_worker.py').read_text(encoding='utf8'))
    wrapper = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == 'TimedFeatures')
    call = next(node for node in wrapper.body if isinstance(node, ast.FunctionDef) and node.name == '__call__')
    reads = [node for node in ast.walk(call) if isinstance(node, ast.Attribute)
             and isinstance(node.value, ast.Name) and node.value.id == 'args']
    assert reads == []


@pytest.mark.parametrize('apple,mps,expect_errors', [(True, True, []), (True, False, []), (False, True, ['cuda'])])
def test_moss_runtime_probe_checks_the_apple_gpu_on_a_mac(monkeypatch, apple, mps, expect_errors):
    # The queue preflight refused MOSS on the Mac: "torch.version.cuda is None" (2026-10-14 run).
    import sys
    from twobyteasr import environment_probe as probe
    fake_torch = SimpleNamespace(
        __version__='2.11.0', version=SimpleNamespace(cuda=None),
        cuda=SimpleNamespace(is_available=lambda: False, device_count=lambda: 0),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
        zeros=lambda size, device: SimpleNamespace(device=device, is_cuda=False))
    monkeypatch.setitem(sys.modules, 'torch', fake_torch)
    monkeypatch.setattr(probe, '_apple_silicon', lambda: apple)
    result = {'errors': [], 'cuda': {}}
    if apple:
        probe._apple_gpu_probe(result, 'moss')
        assert result['mps'] == ({'available': True, 'tensor_test_passed': True} if mps else {'available': False})
    else:
        probe._strict_cuda_probe(result, 'moss')
    assert [kind for kind in expect_errors if any(kind in error.lower() for error in result['errors'])] == expect_errors
    assert bool(result['errors']) == bool(expect_errors)


def test_moss_role_uses_the_apple_gpu_probe_on_apple_silicon(monkeypatch):
    from twobyteasr import environment_probe as probe
    calls = []
    monkeypatch.setattr(probe, '_apple_silicon', lambda: True)
    monkeypatch.setattr(probe, '_apple_gpu_probe', lambda result, label: calls.append(('apple', label)))
    monkeypatch.setattr(probe, '_strict_cuda_probe', lambda result, label: calls.append(('cuda', label)))
    probe.run('moss', {'python': '3.12', 'torch': '2.11.0', 'packages': {}})
    assert calls == [('apple', 'moss')]
    monkeypatch.setattr(probe, '_apple_silicon', lambda: False)
    calls.clear()
    probe.run('moss', {'python': '3.12', 'torch': '2.11.0', 'packages': {}})
    assert calls == [('cuda', 'moss')]


@pytest.mark.parametrize('model_id,platform_name,ready', [('firered', 'darwin', True), ('qwen3-asr', 'darwin', False),
                                                          ('firered', 'win32', False)])
def test_firered_stage_probe_is_ready_on_a_mac_without_cuda(monkeypatch, model_id, platform_name, ready):
    # The first in-app Mac run skipped FireRed: "environment_not_ready:probe_failed" (no CUDA).
    from twobyteasr import asr
    payload = {'imports': ['torch', 'fireredasr2s.fireredasr2'], 'cuda_available': False, 'error': '',
               'platform': platform_name, 'mps_available': platform_name == 'darwin'}
    monkeypatch.setattr(asr.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='__2BYTEASR_MODEL_PROBE__' + json.dumps(payload), stderr=''))
    details = asr._spawn_model_runtime_probe({'model_id': model_id}, 'python', '', 'fireredasr2s.fireredasr2')
    assert details['ready'] is ready
    assert details['mps_available'] is (platform_name == 'darwin')
