"""426, executable identity and UI status regression; no account/network calls."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from twobyteasr.providers.ai_providers import AIProviderError, GrokCLIProvider, ProviderStatus
from twobyteasr.providers.provider_service import ProviderService, ProviderHealthState


def upgrade_envelope(received="1.0.5", minimum="1.0.13"):
    inner = {"message": f"API error (status 426 Upgrade Required): Your Grok CLI version ({received}) is outdated. Please update to version {minimum} or later via `grok update` or the installation documentation.", "http_status": 426}
    return json.dumps({"type": "error", "message": "Internal error: " + json.dumps(inner), "access_token": "SECRET_TOKEN_123"})


def test_nested_upgrade_error_has_dynamic_versions_and_redacted_details():
    from twobyteasr.providers.provider_diagnostics import cli_failure
    failure = cli_failure(upgrade_envelope("2.4.1", "2.5.8"))
    assert failure["category"] == "upgrade_required"
    assert failure["received_version"] == "2.4.1"
    assert failure["minimum_version"] == "2.5.8"
    assert "2.5.8" in failure["message"] and "请更新后重试" in failure["message"]
    assert "SECRET_TOKEN_123" not in str(failure)


@pytest.mark.parametrize("exit_code", [0, 1])
def test_nonstream_nested_426_is_never_accepted_as_model_text(monkeypatch, exit_code):
    provider = GrokCLIProvider(executable="fixture-grok.exe", model="grok-fixture")
    monkeypatch.setattr(provider, "_run_cli_command", lambda command, **kw: subprocess.CompletedProcess(command, exit_code, upgrade_envelope(), ""))
    with pytest.raises(AIProviderError) as caught:
        provider._complete_cli_command([provider.executable, "--cwd", "."], 5, False, None, None, {})
    assert caught.value.category == "upgrade_required"
    assert "1.0.5" in str(caught.value) and "1.0.13" in str(caught.value)


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_stream_426_stops_process_on_first_terminal_event(monkeypatch, channel):
    provider = GrokCLIProvider(executable="fixture-grok.exe", model="grok-fixture")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        kwargs["on_line"](channel, upgrade_envelope())
        assert kwargs["stop_when"]() is True
        return subprocess.CompletedProcess(command, 1, "", "")
    monkeypatch.setattr(provider, "_run_cli_command", run)
    with pytest.raises(AIProviderError) as caught:
        provider._run_cli_stream([provider.executable], purpose="fixture", timeout=5)
    assert caught.value.category == "upgrade_required" and len(calls) == 1


def test_models_success_is_auth_evidence_not_a_connection_test(monkeypatch):
    provider = GrokCLIProvider(executable="fixture-grok.exe")
    def run(command, **kw):
        return subprocess.CompletedProcess(command, 0, "grok 1.0.5" if "--version" in command else "* grok-fixture", "")
    monkeypatch.setattr(provider, "_run_cli_command", run)
    status = provider.validate(use_cache=False)
    assert status.authenticated and status.request_succeeded is None
    assert status.auth_evidence == "model_catalog"
    assert ProviderService._health_from_status(status) is ProviderHealthState.UNKNOWN


def test_upgrade_status_is_not_auth_required():
    status = ProviderStatus(True, False, "Grok CLI 版本过旧", category="upgrade_required", request_succeeded=False)
    assert ProviderService._health_from_status(status) is ProviderHealthState.UPGRADE_REQUIRED


def test_cached_executable_replaced_invalidates_healthy_status(tmp_path, monkeypatch):
    executable = tmp_path / "grok.exe"
    executable.write_bytes(b"old")
    provider = GrokCLIProvider(executable=str(executable))
    provider._store_status(ProviderStatus(True, True, "fixture old READY"))
    executable.write_bytes(b"new-binary-size")
    assert provider._cached_status() is None


def test_update_preview_target_is_same_cli_used_for_login_and_requests(tmp_path, monkeypatch):
    executable = tmp_path / ".grok" / "bin" / "grok.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture")
    provider = GrokCLIProvider(executable=str(executable))
    monkeypatch.setattr(provider, "_run_cli_command", lambda command, **kw: subprocess.CompletedProcess(command, 0, "Usage: grok update [OPTIONS]\n--check", ""))
    plan = provider.cli_update_plan()
    assert plan["executable"] == str(executable.resolve())
    assert plan["command"] == [str(executable.resolve()), "update"]
    assert provider._login_command()[0] == plan["executable"]


def test_failed_connection_clears_previous_ready_and_shows_version_path(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app.ui import EndpointEditor
    app = QApplication.instance() or QApplication([])
    editor = EndpointEditor("fixture", "#996699", "polish", {"models": {"ai_service": "grok_account", "polish_model": "grok-fixture"}})
    editor.account_status.setText("Grok Account：已登录/连接正常")
    editor._tester = SimpleNamespace(diagnostics={"executable": "C:/fixture/grok.exe", "cli_version": "1.0.5", "auth_evidence": "model_catalog", "request_succeeded": False, "category": "upgrade_required", "last_tested_at": "2026-10-03T12:00:00+08:00"})
    editor._connection_finished(False, "Grok CLI 版本过旧，要求至少 1.0.13")
    assert "连接正常" not in editor.account_status.text()
    assert "1.0.5" in editor.cli_status.text() and "C:/fixture/grok.exe" in editor.cli_status.text()
    assert editor.update_cli_button.isVisibleTo(editor.cli_page)
    editor.deleteLater()
    app.processEvents()


def test_unified_summary_uses_authoritative_group_editor_and_saved_switches(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    from twobyteasr.app.ui import EndpointEditor, MainWindow
    from twobyteasr.providers import endpoint_editor_ui
    monkeypatch.setattr(ui, 'read_api_key', lambda *a, **k: ('', 'fixture'))
    monkeypatch.setattr(endpoint_editor_ui, 'read_api_key', lambda *a, **k: ('', 'fixture'))
    app = QApplication.instance() or QApplication([])
    saved = {"models": {"ai_service": "grok_account", "polish_model": "grok-fixture", "group_model": "deepseek-fixture"},
             "switches": {"unified_glm_processing": True}}
    polish = EndpointEditor("fixture", "#996699", "polish", saved)
    group = EndpointEditor("fixture", "#996699", "group", saved)
    group.service.setCurrentIndex(group.service.findData('deepseek'))
    summaries = []
    window = SimpleNamespace(polish_editor=polish, group_editor=group,
        legacy=SimpleNamespace(RUNTIME_SETTINGS=saved), unified_glm=SimpleNamespace(isChecked=lambda: True),
        ai_grouping=SimpleNamespace(isChecked=lambda: True), ai_polish=SimpleNamespace(isChecked=lambda: True),
        share_key=SimpleNamespace(isChecked=lambda: False),
        ai_panel=SimpleNamespace(set_summary=summaries.append))
    MainWindow._refresh_ai_summary(window)
    assert 'Grok Account' in summaries[-1].split('未保存草稿')[0]
    assert 'DeepSeek' in summaries[-1].split('未保存草稿')[1]
    assert '已保存' in summaries[-1]
    window.ai_polish = SimpleNamespace(isChecked=lambda: False)
    MainWindow._refresh_ai_summary(window)
    assert '未保存草稿' in summaries[-1]
    assert 'Grok Account' in summaries[-1].split('未保存草稿')[0]
    polish.deleteLater()
    group.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('stage,unified', [('polish', False), ('group', False), ('polish', True)])
def test_effective_summary_identity_reuses_role_snapshot_over_active_service(monkeypatch, stage, unified):
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a, **k: ('', 'fixture'))
    settings = {'models': {'ai_service': 'grok_account',
        'polish_provider': 'grok_oauth', 'polish_transport': 'grok_cli',
        'polish_model': 'grok-role', 'polish_base_url': '', 'polish_protocol': 'auto',
        'group_provider': 'deepseek', 'group_transport': 'openai_compatible',
        'group_model': 'deepseek-role', 'group_base_url': 'https://api.deepseek.com/v1',
        'group_protocol': 'chat_completions'}, 'switches': {'unified_glm_processing': unified}}
    snapshot = resolve_provider_snapshot(settings, stage=stage)
    identity = llm_config.effective_ai_identity(settings, stage)
    assert (identity['provider'], identity['model'], identity['transport'], identity['service']) == (
        snapshot.provider, snapshot.model, snapshot.transport, snapshot.profile_id)
    task_settings = snapshot.execution_settings()
    task_settings['models']['ai_service'] = 'grok_account'
    assert llm_config.effective_ai_identity(task_settings, stage) == identity


@pytest.mark.parametrize('unified', [False, True])
def test_draft_summary_is_exact_dry_run_persist_identity_before_and_after_save(monkeypatch, unified):
    import copy
    from twobyteasr.app import ui
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    monkeypatch.setattr(ui, 'read_api_key', lambda *a, **k: ('', 'fixture'))
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a, **k: ('', 'fixture'))
    monkeypatch.setattr(ui, 'GLOBAL_PROVIDER_REGISTRY', SimpleNamespace(bind=lambda *a: None))
    saved = {'models': {'ai_service': 'grok_account', 'polish_model': 'grok-saved'},
             'switches': {'unified_glm_processing': True, 'enable_ai_polish': True, 'use_ai_grouping': True}}
    legacy = SimpleNamespace(RUNTIME_SETTINGS=saved)
    writes = []
    def configure(models, **kw):
        writes.append(models)
        updated = copy.deepcopy(legacy.RUNTIME_SETTINGS)
        updated.setdefault('models', {}).update(models)
        updated['switches'].update({key: kw[key] for key in ('unified_glm_processing', 'enable_ai_polish', 'use_ai_grouping')})
        legacy.RUNTIME_SETTINGS = updated
    legacy.configure_runtime_llms = configure
    p = {'service': 'grok_account', 'provider': 'grok_oauth', 'transport': 'grok_cli',
         'model': 'grok-draft', 'base_url': '', 'protocol': 'auto', 'key': ''}
    g = {'service': 'deepseek', 'provider': 'deepseek', 'transport': 'openai_compatible',
         'model': 'deepseek-draft', 'base_url': 'https://api.deepseek.com/v1', 'protocol': 'chat_completions', 'key': ''}
    window = SimpleNamespace(legacy=legacy, polish_editor=SimpleNamespace(values=lambda: p),
        group_editor=SimpleNamespace(values=lambda: g), unified_glm=SimpleNamespace(isChecked=lambda: unified),
        ai_polish=SimpleNamespace(isChecked=lambda: True), ai_grouping=SimpleNamespace(isChecked=lambda: True),
        share_key=SimpleNamespace(isChecked=lambda: False), ai_panel=SimpleNamespace(set_summary=lambda text: summaries.append(text)))
    summaries = []
    before = copy.deepcopy(saved)
    ui.MainWindow._refresh_ai_summary(window)
    draft = summaries[-1].split('未保存草稿：')[1].split(' · 真实连接需单独测试')[0]
    assert legacy.RUNTIME_SETTINGS == before and writes == []
    if unified:
        assert 'deepseek-draft' in draft and 'grok-draft' not in draft
    else:
        assert 'deepseek-draft' in draft and 'grok-draft' in draft
    ui.persist_ai_configuration(legacy, p, g, unified=unified, share_key=False, require_ready=False)
    ui.MainWindow._refresh_ai_summary(window)
    assert '未保存草稿' not in summaries[-1]
    assert summaries[-1].split('已保存：')[1].split(' · 真实连接需单独测试')[0] == draft
    for stage in ('polish', 'group'):
        actual = resolve_provider_snapshot(legacy.RUNTIME_SETTINGS, stage=stage)
        assert actual.model in draft


def test_broker_upgrade_is_terminal_not_retry_or_auth_failure(monkeypatch):
    from twobyteasr.providers import provider_service
    from twobyteasr.providers.provider_diagnostics import cli_failure
    provider = GrokCLIProvider(executable='fixture-grok.exe', model='grok-fixture')
    calls = []
    def complete(*args, **kwargs):
        calls.append(1)
        provider._fail_cli(cli_failure(upgrade_envelope()))
    monkeypatch.setattr(provider, 'complete', complete)
    monkeypatch.setattr(provider_service, 'adapter_for_stage', lambda *a, **k: provider)
    service = ProviderService(workers=1)
    client = service.client_for_stage({'models': {'ai_service': 'grok_account', 'polish_model': 'grok-fixture'}}, 'polish')
    for _ in range(2):
        with pytest.raises(AIProviderError) as caught:
            client.complete([{'role': 'user', 'content': 'fixture'}], timeout=2)
        assert caught.value.category == 'upgrade_required'
    assert len(calls) == 1
    assert client.cached_health().state is ProviderHealthState.UPGRADE_REQUIRED
    assert service.wait_for_idle(2)
    assert all(row.get('retry_count', 0) == 0 for row in service.telemetry())


def test_update_rechecks_version_and_minimal_request_without_changing_credentials(tmp_path, monkeypatch):
    executable = tmp_path / '.grok' / 'bin' / 'grok.exe'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'old')
    provider = GrokCLIProvider(executable=str(executable))
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[-1] == '--help':
            return subprocess.CompletedProcess(command, 0, 'Usage: grok update [OPTIONS]\n--check', '')
        if command[-1] == 'update':
            executable.write_bytes(b'updated-native-binary')
            return subprocess.CompletedProcess(command, 0, 'updated', '')
        assert command[-1] == '--version'
        return subprocess.CompletedProcess(command, 0, 'grok 2.5.8', '')
    monkeypatch.setattr(provider, '_run_cli_command', run)
    provider._store_status(ProviderStatus(True, True, 'old READY'))
    plan = provider.cli_update_plan()
    with pytest.raises(AIProviderError) as missing_confirm:
        provider.update_cli(plan)
    assert missing_confirm.value.category == 'explicit_update_required'
    requests = []
    def request(messages, **kwargs):
        requests.append((messages, kwargs))
        provider._record_request_success()
        return '2ByteASR_OK'
    monkeypatch.setattr(provider, 'complete', request)
    status = provider.update_cli(plan, user_confirmed=True)
    assert status.request_succeeded is True and '2.5.8' in provider.cli_version
    assert provider._cached_status() is None
    assert len(requests) == 1 and requests[0][0][0]['content'] == 'Return exactly: 2ByteASR_OK'
    assert not any('login' in command or 'logout' in command for command in calls)


def test_broker_update_keeps_fresh_test_but_expires_other_models_old_status(monkeypatch):
    from twobyteasr.providers import provider_service
    monkeypatch.setattr(provider_service, 'adapter_for_stage', lambda settings, stage, **kw:
                        GrokCLIProvider(executable='fixture-grok.exe', model=settings['models']['polish_model']))
    service = ProviderService(workers=1)
    current = service.client_for_stage({'models': {'ai_service': 'grok_account', 'polish_model': 'grok-fixture-A'}}, 'polish')
    other = service.client_for_stage({'models': {'ai_service': 'grok_account', 'polish_model': 'grok-fixture-B'}}, 'polish')
    a = service._runtime_for(current._settings, 'polish', None)
    b = service._runtime_for(other._settings, 'polish', None)
    b.adapter.failure_category = 'upgrade_required'
    b.adapter.last_cli_failure = {'minimum_version': 'old-minimum'}
    b.adapter.cli_version = 'old-version'
    status = ProviderStatus(True, True, 'new real test passed', request_succeeded=True,
                            auth_evidence='successful_model_request', diagnostics={'cli_version': '2.5.8'})
    monkeypatch.setattr(a.adapter, 'update_cli', lambda *args, **kw: status)
    assert current.update_cli({}, user_confirmed=True).request_succeeded is True
    assert current.cached_health().state is ProviderHealthState.READY
    assert other.cached_health().state is ProviderHealthState.UNKNOWN
    assert b.adapter.failure_category == '' and b.adapter.cli_version == '' and b.adapter.last_cli_failure == {}


def test_cli_update_refuses_running_request_by_actual_provider_id(monkeypatch):
    import time
    from twobyteasr.providers import provider_service
    from twobyteasr.providers.provider_service import ProviderRequestHandle
    provider = GrokCLIProvider(executable='fixture-grok.exe', model='grok-fixture')
    monkeypatch.setattr(provider_service, 'adapter_for_stage', lambda *a, **k: provider)
    service = ProviderService(workers=1)
    client = service.client_for_stage({'models': {'ai_service': 'grok_account', 'polish_model': 'grok-fixture'}}, 'polish')
    calls = []
    monkeypatch.setattr(provider, 'update_cli', lambda *a, **k: calls.append(1) or ProviderStatus(True, True, 'fixture'))
    service._handles['active'] = ProviderRequestHandle('active', 'grok_oauth', time.monotonic() + 10)
    with pytest.raises(AIProviderError) as caught:
        client.update_cli({}, user_confirmed=True)
    assert caught.value.category == 'provider_busy' and calls == []
    service._handles.clear()


@pytest.mark.parametrize('update_fails', [False, True])
def test_update_reservation_blocks_new_request_and_login_until_finally(monkeypatch, update_fails):
    import threading
    from twobyteasr.providers import provider_service
    provider = GrokCLIProvider(executable='fixture-grok.exe', model='grok-fixture')
    monkeypatch.setattr(provider_service, 'adapter_for_stage', lambda *a, **k: provider)
    service = ProviderService(workers=1)
    settings = {'models': {'ai_service': 'grok_account', 'polish_model': 'grok-fixture'}}
    client = service.client_for_stage(settings, 'polish')
    entered, release = threading.Event(), threading.Event()
    login_calls = []
    monkeypatch.setattr(provider, 'login', lambda **kw: login_calls.append(1) or ProviderStatus(True, True, 'fixture'))
    def update(*a, **kw):
        entered.set()
        assert release.wait(3)
        if update_fails:
            raise AIProviderError('fixture update failed', category='cli_update_failed')
        return ProviderStatus(True, True, 'fixture updated', request_succeeded=True)
    monkeypatch.setattr(provider, 'update_cli', update)
    outcomes = []
    def worker():
        try:
            outcomes.append(client.update_cli({}, user_confirmed=True))
        except AIProviderError as exc:
            outcomes.append(exc.category)
    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(2)
    try:
        for action in (lambda: client.submit([{'role': 'user', 'content': 'fixture'}]),
                       lambda: client.login(user_initiated=True),
                       lambda: client.health(refresh=True),
                       lambda: client.discover_models(refresh=True),
                       lambda: client.cli_update_plan(),
                       lambda: client.update_cli({}, user_confirmed=True)):
            with pytest.raises(AIProviderError) as caught:
                action()
            assert caught.value.category == 'provider_busy'
        assert login_calls == [] and not service._handles
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert service._updating_transports == set()
    assert client.login(user_initiated=True).authenticated and login_calls == [1]


@pytest.mark.parametrize('operation', ['health', 'discover', 'preview'])
def test_active_cli_probe_or_preview_blocks_update_and_releases_on_completion(monkeypatch, operation):
    import threading
    from twobyteasr.providers import provider_service
    provider = GrokCLIProvider(executable='fixture-grok.exe', model='grok-fixture')
    monkeypatch.setattr(provider_service, 'adapter_for_stage', lambda *a, **k: provider)
    service = ProviderService(workers=1)
    settings = {'models': {'ai_service': 'grok_account', 'polish_model': 'grok-fixture'}}
    client = service.client_for_stage(settings, 'polish')
    entered, release = threading.Event(), threading.Event()
    def blocked(result):
        entered.set()
        assert release.wait(3)
        return result
    monkeypatch.setattr(provider, 'refresh_executable', lambda: None)
    monkeypatch.setattr(provider, 'validate', lambda **kw: blocked(ProviderStatus(True, True, 'fixture')))
    monkeypatch.setattr(provider, 'discover_models', lambda **kw: blocked(('grok-fixture',)))
    monkeypatch.setattr(provider, 'cli_update_plan', lambda: blocked({'fixture': True}))
    updates = []
    monkeypatch.setattr(provider, 'update_cli', lambda *a, **k: updates.append(1) or ProviderStatus(True, True, 'fixture'))
    action = {'health': lambda: client.health(refresh=True), 'discover': lambda: client.discover_models(refresh=True),
              'preview': client.cli_update_plan}[operation]
    outcomes = []
    def run():
        try:
            outcomes.append(action())
        except BaseException as exc:
            outcomes.append(exc)
    thread = threading.Thread(target=run)
    thread.start()
    assert entered.wait(2)
    try:
        with pytest.raises(AIProviderError) as caught:
            client.update_cli({}, user_confirmed=True)
        assert caught.value.category == 'provider_busy' and updates == []
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive() and len(outcomes) == 1 and not isinstance(outcomes[0], BaseException)
    assert client.update_cli({}, user_confirmed=True).authenticated and updates == [1]
