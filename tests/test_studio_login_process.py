"""Login control flow without launching OAuth or changing account storage."""
import io
import os
import subprocess
from types import SimpleNamespace

import pytest

from twobyteasr.system import processes
from twobyteasr.providers.ai_providers import AIProviderError, ProviderStatus, AntigravityCLIProvider
from twobyteasr.providers.codex_cli_provider import CodexCLIProvider


@pytest.mark.skipif(os.name != 'nt', reason='Windows console contract')
def test_visible_child_with_spaces_has_new_console_and_no_hidden_flag(monkeypatch):
    seen = {}
    monkeypatch.setattr(processes, '_record_child_process', lambda *a, **k: None)
    def spawn(command, **kwargs):
        seen.update(command=command, **kwargs)
        return SimpleNamespace(pid=123)
    command = [r'C:\Program Files\Official Codex\codex.exe', 'login']
    processes.popen_hidden_subprocess(command, purpose='fixture', visible_console=True,
        creationflags=subprocess.CREATE_NO_WINDOW, process_factory=spawn)
    assert seen['command'] == command
    assert seen['startupinfo'].wShowWindow == 1
    assert seen['creationflags'] & subprocess.CREATE_NEW_CONSOLE
    assert not seen['creationflags'] & subprocess.CREATE_NO_WINDOW
    assert not seen.get('shell', False)


@pytest.mark.parametrize('logged_in,code', [(True, 0), (False, 1), (True, 1)])
def test_login_progress_follows_creation_and_records_exit(monkeypatch, logged_in, code):
    from twobyteasr.providers import codex_cli_provider as module
    provider = CodexCLIProvider(executable=r'C:\Program Files\Codex\codex.exe')
    events = []
    process = SimpleNamespace(pid=321, stderr=io.StringIO('error Bearer private-value\n'),
        poll=lambda: code, returncode=code)
    def spawn(command, **kwargs):
        assert command == [provider.executable, 'login']
        assert kwargs['visible_console']
        events.append('created')
        return process
    monkeypatch.setattr(module, 'popen_hidden_subprocess', spawn)
    monkeypatch.setattr(provider, 'validate', lambda **kw: ProviderStatus(True, logged_in, 'status'))
    status = provider.login(on_progress=events.append)
    assert events[0] == 'created' and '等待认证' in events[1]
    assert status.authenticated == logged_in
    assert provider.last_invocation_trace['login']['exit_code'] == code
    assert 'private-value' not in str(provider.last_invocation_trace)


def test_spawn_failure_never_claims_window_open(monkeypatch):
    from twobyteasr.providers import codex_cli_provider as module
    provider = CodexCLIProvider(executable='fixture.exe')
    monkeypatch.setattr(module, 'popen_hidden_subprocess', lambda *a, **k: (_ for _ in ()).throw(OSError('denied')))
    progress = []
    with pytest.raises(AIProviderError, match='denied'):
        provider.login(on_progress=progress.append)
    assert not progress
    assert provider.last_invocation_trace['login']['created'] is False


def test_cancelled_before_spawn_does_not_open_oauth():
    provider = CodexCLIProvider(executable='fixture.exe')
    with pytest.raises(AIProviderError, match='取消'):
        provider.login(cancel_check=lambda: True)


def test_agy_hidden_exit_does_not_fall_back_to_console(monkeypatch):
    from twobyteasr.providers import ai_providers as module
    import threading
    provider = AntigravityCLIProvider(executable='fixture-agy.exe')
    no_session = ProviderStatus(True, False, 'not logged in')
    monkeypatch.setattr(provider, 'detect_installation', lambda **k: no_session)
    monkeypatch.setattr(provider, 'validate', lambda **k: no_session)
    process = SimpleNamespace(pid=33, poll=lambda: 1)
    state = {'url': '', 'output': ['failed Bearer hidden-secret'], 'lock': threading.Lock()}
    monkeypatch.setattr(provider, '_start_hidden_login_stream', lambda cmd: (process, state))
    monkeypatch.setattr(provider, '_launch_visible_login', lambda: pytest.fail('visible AGY fallback'))
    monkeypatch.setattr(module, 'stop_process_tree', lambda p: None)
    result = provider.login()
    assert not result.authenticated and 'hidden-secret' not in result.message

@pytest.mark.parametrize('reason',['用户取消','启动失败'])
def test_broker_rechecks_existing_account_after_failed_login(monkeypatch, reason):
    import threading
    from twobyteasr.providers.provider_service import ProviderService,ProviderHealth,ProviderHealthState
    from twobyteasr.providers.ai_providers import AITransport
    adapter=SimpleNamespace(login=lambda **k:(_ for _ in ()).throw(AIProviderError(reason)),
        validate=lambda **k:ProviderStatus(True,True,'ready'))
    runtime=SimpleNamespace(adapter=adapter,login_lock=threading.Lock(),transport=AITransport.CODEX_CLI,
        health=ProviderHealth(ProviderHealthState.READY,'ready',0.))
    service=ProviderService();monkeypatch.setattr(service,'_runtime_for',lambda *a:runtime)
    status=service.login({},'polish',user_initiated=True)
    assert status.authenticated and reason in status.message
    assert runtime.health.state is ProviderHealthState.READY
    assert not runtime.login_lock.locked()

def test_broker_does_not_open_second_login_window(monkeypatch):
    import threading
    from twobyteasr.providers.provider_service import ProviderService,ProviderHealth,ProviderHealthState
    from twobyteasr.providers.ai_providers import AITransport
    entered=threading.Event();release=threading.Event();calls=[]
    def login(**kw):
        calls.append(1);entered.set();release.wait(3)
        return ProviderStatus(True,True,'ready')
    runtime=SimpleNamespace(adapter=SimpleNamespace(login=login),login_lock=threading.Lock(),transport=AITransport.CODEX_CLI,
        health=ProviderHealth(ProviderHealthState.READY,'ready',0.))
    service=ProviderService();monkeypatch.setattr(service,'_runtime_for',lambda *a:runtime)
    thread=threading.Thread(target=lambda:service.login({},'polish',user_initiated=True));thread.start()
    try:
        assert entered.wait(1)
        with pytest.raises(AIProviderError,match='正在等待'):service.login({},'polish',user_initiated=True)
        assert len(calls)==1
    finally:release.set();thread.join(3)
