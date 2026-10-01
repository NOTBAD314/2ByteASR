"""Process/login simulations also executable inside the frozen audit.

No real login command, account write, logout or browser flow is performed.
"""
def login_control_checks():
    import io
    import subprocess
    import threading
    from types import SimpleNamespace
    from unittest.mock import patch
    from . import processes, codex_cli_provider
    from .ai_providers import AIProviderError, AITransport, ProviderStatus
    from .provider_service import ProviderService, ProviderHealth, ProviderHealthState

    checks = {}
    seen = {}
    def spawn(command, **kwargs):
        seen.update(command=command, **kwargs)
        return SimpleNamespace(pid=1)
    official = [r'C:\Program Files\Official Codex\codex.exe', 'login']
    with patch.object(processes, '_record_child_process'):
        processes.popen_hidden_subprocess(official, purpose='isolated login simulation',
            visible_console=True, process_factory=spawn)
        checks['login-visible-official-arguments'] = (seen['command'] == official and
            seen['creationflags'] & subprocess.CREATE_NEW_CONSOLE != 0 and
            seen['creationflags'] & subprocess.CREATE_NO_WINDOW == 0 and
            seen['startupinfo'].wShowWindow == 1 and not seen.get('shell', False))
        seen.clear()
        processes.popen_hidden_subprocess([r'C:\Program Files\AGY\agy.exe'],
            purpose='isolated AGY simulation', process_factory=spawn)
        checks['agy-bare-hidden-arguments'] = (len(seen['command']) == 1 and
            seen['creationflags'] & subprocess.CREATE_NO_WINDOW != 0 and not seen.get('shell', False))
    provider = codex_cli_provider.CodexCLIProvider(executable=official[0])
    for authenticated, code in ((True, 0), (False, 1), (True, 1)):
        events = []
        def created(*args, **kwargs):
            events.append('created')
            return SimpleNamespace(pid=1, stderr=io.StringIO('Bearer fixture-secret\n'),
                                   poll=lambda: code, returncode=code)
        with patch.object(codex_cli_provider, 'popen_hidden_subprocess', created), \
             patch.object(provider, 'validate', return_value=ProviderStatus(True, authenticated, 'fixture')):
            result = provider.login(on_progress=events.append)
        checks[f'login-session-{authenticated}-exit-{code}'] = (result.authenticated == authenticated and
            events[0] == 'created' and len(events) > 1 and 'fixture-secret' not in str(provider.last_invocation_trace))
    events = []
    with patch.object(codex_cli_provider, 'popen_hidden_subprocess', side_effect=OSError('fixture denied')):
        try: provider.login(on_progress=events.append)
        except AIProviderError: checks['login-failed-no-false-progress'] = not events
    with patch.object(codex_cli_provider, 'popen_hidden_subprocess') as fake:
        try: provider.login(cancel_check=lambda: True)
        except AIProviderError: checks['login-cancel-before-spawn'] = not fake.called
    for reason in ('用户取消', '启动失败'):
        adapter = SimpleNamespace(login=lambda **k: (_ for _ in ()).throw(AIProviderError(reason)),
            validate=lambda **k: ProviderStatus(True, True, 'ready'))
        runtime = SimpleNamespace(adapter=adapter, login_lock=threading.Lock(), transport=AITransport.CODEX_CLI,
            health=ProviderHealth(ProviderHealthState.READY, 'ready', 0.))
        service = ProviderService()
        with patch.object(service, '_runtime_for', return_value=runtime):
            result = service.login({}, 'polish',user_initiated=True)
            checks[f'login-preserves-session-{reason}'] = result.authenticated and not runtime.login_lock.locked()
            runtime.login_lock.acquire()
            try:
                service.login({}, 'polish',user_initiated=True)
            except AIProviderError:
                checks['login-reentry-rejected'] = True
            finally:
                runtime.login_lock.release()
    return checks
