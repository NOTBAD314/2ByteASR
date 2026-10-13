# SPDX-License-Identifier: GPL-3.0-only
import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from twobyteasr import llm_config
from twobyteasr import macos_model_prepare as prepare


@pytest.fixture
def session_store(monkeypatch, tmp_path):
    # The session-only tests must not inherit the developer's authorized keys.
    for name in tuple(os.environ):
        if name.endswith('_API_KEY'):
            monkeypatch.delenv(name)
    monkeypatch.setattr(llm_config, 'session_credentials_enabled', lambda: True)
    monkeypatch.setattr(llm_config, 'secrets_path', lambda: tmp_path / 'profile/secrets.dat')
    llm_config.clear_session_secrets()
    yield tmp_path
    llm_config.clear_session_secrets()


def test_session_credentials_keep_provider_scope_and_never_create_disk_payload(session_store):
    llm_config.save_api_key_for('deepseek', 'https://api.deepseek.com/v1', 'fixture-session-secret')
    assert llm_config.read_api_key('deepseek', 'https://api.deepseek.com/v1')[0] == 'fixture-session-secret'
    assert llm_config.read_api_key('custom', 'https://different.invalid/v1')[0] == ''
    assert list(session_store.rglob('*')) == []
    llm_config.delete_api_key_for('deepseek', 'https://api.deepseek.com/v1')
    assert llm_config.read_api_key('deepseek', 'https://api.deepseek.com/v1')[0] == ''


def test_session_credentials_do_not_migrate_existing_plaintext_and_clear_on_session_end(session_store):
    path = llm_config.secrets_path()
    path.parent.mkdir()
    legacy = path.with_name('secrets.json')
    legacy.write_text(json.dumps({'DASHSCOPE_API_KEY': 'fixture-old-key'}))
    original = legacy.read_bytes()
    assert llm_config.resolve_api_key('polish')[0] == ''
    llm_config.save_api_keys(polish_key='fixture-ephemeral-key')
    assert llm_config.resolve_api_key('polish')[0] == 'fixture-ephemeral-key'
    llm_config.clear_session_secrets()
    assert llm_config.resolve_api_key('polish')[0] == ''
    assert legacy.read_bytes() == original
    assert not path.exists()
    assert 'session only' in llm_config.credential_storage_notice('en')


@pytest.mark.parametrize('name,link', [('../escape', ''), ('link', '../../escape')])
def test_bootstrap_archive_rejects_escape_before_extracting(tmp_path, name, link):
    archive = tmp_path / 'unsafe.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        member = tarfile.TarInfo(name)
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = link
        bundle.addfile(member, io.BytesIO(b''))
    with pytest.raises(ValueError, match='escapes'):
        prepare.extract_archive(archive, tmp_path / 'owned')
    assert not (tmp_path / 'escape').exists()


def test_bootstrap_cache_is_verified_again_without_network(tmp_path, monkeypatch):
    data = b'owned archive fixture'
    digest = hashlib.sha256(data).hexdigest()
    archive = tmp_path / (digest + '.tar.gz')
    archive.write_bytes(data)
    monkeypatch.setattr(prepare.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('verified cache must be reused'))
    assert prepare.download_archive(dict(sha256=digest, url='https://unused.invalid/archive'), tmp_path) == archive


def test_failed_native_dependency_probe_never_changes_runtime_registration(tmp_path, monkeypatch):
    from twobyteasr import runtime_paths, runtime_registry
    root = tmp_path / '资源 应用'
    (root / 'packaging/macos').mkdir(parents=True)
    lock = {'target': 'darwin-arm64', 'uv': {'version': 'fixed', 'member': 'uv/uv'}, 'pip': {'version': 'fixed'},
            'python': {'version': '3.10.19', 'build': 'fixed'}}
    (root / 'packaging/macos/bootstrap.lock.json').write_text(json.dumps(lock))
    for name in ('requirements-cpu.txt', 'requirements-gui.txt'):
        (root / 'packaging/macos' / name).write_text('owned==1\n')
    (root / 'packaging/macos/native-dependencies.lock.json').write_text(json.dumps({'critical_wheel_availability': {}}))
    monkeypatch.setattr(prepare, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(prepare.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(runtime_paths, 'user_data_root', lambda: tmp_path / 'profile')
    monkeypatch.setattr(runtime_registry, 'resolve_runtime_python', lambda *a, **k: '')
    registrations = []
    monkeypatch.setattr(runtime_registry, 'register_runtime', lambda *a, **k: registrations.append(a))
    monkeypatch.setattr(prepare, 'download_archive', lambda *a: tmp_path / 'archive')
    def extract(_archive, target):
        file = target / ('uv/uv' if 'tools' in target.parts else 'python/bin/python3.10')
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('owned binary fixture')
    monkeypatch.setattr(prepare, 'extract_archive', extract)
    def run(command, **_kwargs):
        if '--report' in command:
            report = Path(command[command.index('--report') + 1])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({'install': []}))
    monkeypatch.setattr(prepare, 'run', run)
    monkeypatch.setattr(prepare, 'check_runtime', lambda *a, **k: False)
    with pytest.raises(RuntimeError, match='previous registration was preserved'):
        prepare.prepare(root, models=tmp_path / 'models', source='HF_OFFICIAL')
    assert registrations == []
    assert list((tmp_path / 'profile').rglob('managed-runtime.json')) == []


def test_small_cpu_probe_cannot_reuse_runtime_without_matching_wheel_report(tmp_path, monkeypatch):
    root = tmp_path / 'resources'
    (root / 'packaging/macos').mkdir(parents=True)
    native = root / 'packaging/macos/native-dependencies.lock.json'
    native.write_text(json.dumps({'critical_wheel_availability': {'torch': {
        'version': '2.11.0', 'arm64_cp310_or_universal': [{'sha256': 'a' * 64, 'filename': 'owned.whl'}]}}}))
    runtime = tmp_path / 'runtime'
    python = runtime / 'bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('owned interpreter fixture')
    report = runtime / 'install.json'
    report.write_text(json.dumps({'install': [{'metadata': {'name': 'torch', 'version': '2.11.0'},
        'download_info': {'archive_info': {'hashes': {'sha256': 'b' * 64}}}}]}))
    (runtime / 'mac-native-wheels.json').write_text(json.dumps({'lock_sha256': prepare.sha256(native), 'install_report': str(report)}))
    monkeypatch.setattr(prepare.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"python":"3.10.19"}'))
    assert not prepare.check_runtime(python, root)


def test_macos_model_state_finishes_background_runtime_check(monkeypatch):
    from twobyteasr import model_workshop as workshop, environment
    model = next(item for item in workshop.MODELS if item.download_key == 'sensevoice')
    monkeypatch.setattr(workshop, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(environment, 'fast_preflight', lambda role: None)
    monkeypatch.setattr(environment, 'preflight', lambda role: environment.PreflightResult(role='main', ok=True))
    page = SimpleNamespace(browser_role='primary', runtime_settings={'models': {'primary_asr_backend': 'sensevoice'}},
                           _active_download_dialog=lambda key: None, _registry=None, _installed={'sensevoice'},
                           _mac_cpu_probe_result=None, _mac_cpu_probe_running=False, _state_memo=None)
    page._compute_model_state = lambda item, role: workshop.ModelWorkshopPage._compute_model_state(page, item, role)
    def finish(result):
        page._mac_cpu_probe_result = result
        page._mac_cpu_probe_running = False
    page.mac_cpu_runtime_checked = SimpleNamespace(emit=finish)
    monkeypatch.setattr(workshop.threading, 'Thread', lambda *, target, **kwargs: SimpleNamespace(start=target))
    assert workshop.ModelWorkshopPage._model_state(page, model) == 'checking'
    assert workshop.ModelWorkshopPage._model_state(page, model) == 'selected'


def test_frozen_gui_cpu_preparation_uses_dedicated_app_child_and_writable_cwd(monkeypatch, tmp_path):
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    from twobyteasr import model_workshop as workshop
    app = QApplication.instance() or QApplication([])
    model = next(item for item in workshop.MODELS if item.download_key == 'sensevoice')
    monkeypatch.setattr(workshop, 'sys', SimpleNamespace(platform='darwin', frozen=True, executable=str(tmp_path / '移动 应用.app/Contents/MacOS/2ByteASR')))
    dialog = workshop.ModelDownloadDialog(tmp_path / '只读 资源', model)
    calls = {}
    dialog.process = SimpleNamespace(
        state=lambda: QProcess.ProcessState.NotRunning,
        setProcessEnvironment=lambda env: calls.update(environment=env),
        setWorkingDirectory=lambda cwd: calls.update(cwd=cwd),
        start=lambda program, args: calls.update(program=program, args=args),
        waitForStarted=lambda timeout: True)
    dialog.start_button.click()
    assert calls['program'] == workshop.sys.executable
    assert calls['args'][0] == '--macos-prepare-cpu'
    assert 'pip' not in calls['args'] and 'bash' not in calls['args']
    assert calls['cwd'] != str(dialog.root)
    assert calls['environment'].value('_PYI_RESET_ENVIRONMENT') == '1'
    assert not dialog._finished_ok
    dialog.close()
    app.processEvents()


def test_macos_unsupported_model_detail_constructs_without_startup_keyerror(monkeypatch,tmp_path):
    from PySide6.QtWidgets import QApplication
    from twobyteasr import model_workshop as workshop
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(workshop,'sys',SimpleNamespace(platform='darwin'))
    page=workshop.ModelWorkshopPage(tmp_path,{'models':{'primary_asr_backend':'sensevoice','qwen_asr_backend':'off'}})
    unavailable=next(m for m in workshop.MODELS if m.download_key and m.download_key!='sensevoice')
    page._view_model(unavailable.key)
    assert page._model_state(unavailable)=='platform_unavailable'
    assert page.detail_badge.text()
    assert page._action_text(unavailable,'platform_unavailable')[1] is False
    page.close();app.processEvents()


def test_mac_replace_without_qt_binding_avoids_command_hide(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QKeySequence
    from twobyteasr import studio_shortcuts
    app=QApplication.instance() or QApplication([])
    import sys
    monkeypatch.setattr(sys,'platform','darwin')
    original=QKeySequence.keyBindings
    monkeypatch.setattr(QKeySequence,'keyBindings',lambda key:[] if key==QKeySequence.Replace else original(key))
    defaults=studio_shortcuts.studio_default_shortcuts()
    assert defaults['find_replace']=='Ctrl+Alt+F'
    assert defaults['save']==original(QKeySequence.Save)[0].toString(QKeySequence.PortableText)
