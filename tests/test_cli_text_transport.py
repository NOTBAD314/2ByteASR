"""Production CLI boundary: payload fidelity, launch budgets and ownership."""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from twobyteasr.providers.ai_providers import AIProviderError, CLIProvider, GrokCLIProvider, AntigravityCLIProvider
from twobyteasr.providers.provider_input_budget import windows_argv_units


@pytest.mark.parametrize('length', [29999, 30000, 30001, 30509, 33636])
def test_grok_complete_long_text_uses_file_without_changing_body(monkeypatch, tmp_path, length):
    monkeypatch.setattr('tempfile.tempdir', str(tmp_path))
    provider = GrokCLIProvider(executable='grok.exe', model='grok-4.6')
    marker = '中文😀 "反斜杠\\"\n'
    body = marker + 'x' * (length - len(marker))
    paths = []
    def execute(command, *args):
        path = Path(command[command.index('--prompt-file') + 1])
        paths.append(path)
        assert path.read_text('utf8') == '[USER]\n' + body
        assert body not in command and windows_argv_units(command) < 8000
        return '{"received":true}'
    monkeypatch.setattr(provider, '_complete_cli_command', execute)
    assert provider.complete([dict(role='user', content=body)]) == '{"received":true}'
    assert paths and all(not p.exists() for p in paths)


def test_even_short_business_text_is_not_passed_as_argv(monkeypatch, tmp_path):
    monkeypatch.setattr('tempfile.tempdir', str(tmp_path))
    provider = GrokCLIProvider(executable='grok.exe')
    def execute(command, *args):
        assert '-p' not in command
        return '{}'
    monkeypatch.setattr(provider, '_complete_cli_command', execute)
    provider.complete([dict(role='user', content='校对这句')])


def test_agy_uses_official_single_ndjson_user_event(monkeypatch, tmp_path):
    monkeypatch.setattr('tempfile.tempdir', str(tmp_path))
    provider = AntigravityCLIProvider(executable='agy.exe', model='gemini-3.7-flash-high')
    body = '正文中文😀 "\\\n' * 1000
    def execute(command, seconds, streaming, cancel, callback, kwargs):
        assert '-p' not in command and body not in command
        assert command[command.index('--input-format') + 1] == 'stream-json'
        assert streaming
        packet = json.loads(kwargs['_input_text'])
        assert packet['event']=='user'
        content=packet['message']['content']
        assert content.startswith('This is a pure structured completion request.')
        assert content.endswith('[USER]\n'+body)
        assert content.count(body)==1
        return '{}'
    monkeypatch.setattr(provider, '_complete_cli_command', execute)
    provider.complete([dict(role='user', content=body)])


def test_short_source_with_escaped_argv_overflow_is_stopped_before_spawn(monkeypatch):
    provider = CLIProvider(executable=sys.executable)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.popen_hidden_subprocess',
                        lambda *a, **k: pytest.fail('unsafe CreateProcess attempted'))
    with pytest.raises(AIProviderError) as caught:
        provider._run_cli_command([sys.executable, '"' * 18000], purpose='test request', timeout=1)
    assert caught.value.category == 'request_too_large'


def test_agy_thinking_delta_is_never_final_body():
    state = {'text':'', 'thinking':'', 'final':None}
    CLIProvider._consume_cli_stream_line(json.dumps({'event':'step_update', 'step_update':{
        'step_type':'thinking', 'state':'ACTIVE', 'text_delta':'不能当作正文'}}), state, lambda *a: None)
    assert not state['text'] and not state['final']


def test_headless_tool_denial_is_terminal_without_relaxing_permissions(monkeypatch,tmp_path):
    monkeypatch.setattr('twobyteasr.projects.studio_project.studio_data_root',lambda:tmp_path)
    provider=AntigravityCLIProvider(executable='agy.exe')
    def run(command,**kwargs):
        kwargs['on_line']('stderr','jetski: no output produced — command permission was auto-denied.\n')
        assert kwargs['stop_when']()
        return subprocess.CompletedProcess(command,0,'','auto-denied')
    monkeypatch.setattr(provider,'_run_cli_command',run)
    with pytest.raises(AIProviderError) as caught:
        provider._run_cli_stream(['agy.exe'],purpose='test',timeout=360)
    assert caught.value.category=='permission_denied'


def test_cli_requests_have_independent_process_and_diagnostic_state():
    provider = GrokCLIProvider(executable='grok.exe', model='grok-4.6')
    with ThreadPoolExecutor(4) as pool:
        children = list(pool.map(lambda _: provider.fork_request(), range(4)))
    assert len({id(x.last_timings) for x in children}) == 4
    assert len({id(x._active_process_lock) for x in children}) == 4
    assert all(x.model == provider.model and x.executable == provider.executable for x in children)


def test_winerror206_from_createprocess_is_deterministic(monkeypatch):
    provider = CLIProvider(executable=sys.executable)
    def fail(*a, **k):
        exc = OSError('synthetic CreateProcess length failure')
        exc.winerror = 206
        raise exc
    monkeypatch.setattr('twobyteasr.providers.ai_providers.popen_hidden_subprocess', fail)
    with pytest.raises(AIProviderError) as caught:
        provider._run_cli_command([sys.executable, '-V'], purpose='test request', timeout=1)
    assert caught.value.category == 'transport_length'
    assert provider.last_timings['failure_stage'] == 'process_start'


@pytest.mark.skipif(sys.platform != 'win32',reason='Windows process-job contract')
def test_exited_cli_cannot_leave_descendant_holding_input_resources(tmp_path):
    import psutil
    worker=tmp_path/'owned.py'
    worker.write_text("import subprocess,sys\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(45)'])\nprint(p.pid,flush=True)\n",encoding='utf8')
    provider=CLIProvider(executable=sys.executable)
    result=provider._run_cli_command([sys.executable,str(worker)],purpose='owned descendant fixture',timeout=4)
    assert not psutil.pid_exists(int(result.stdout.strip()))
    assert provider.last_timings['cleanup_complete']


def test_four_real_processes_do_not_share_payloads_or_sessions(monkeypatch,tmp_path):
    import time
    monkeypatch.setattr('tempfile.tempdir',str(tmp_path))
    worker=tmp_path/'fixture_cli.py'
    worker.write_text("import json,sys,time\nfrom pathlib import Path\na=sys.argv\np=Path(a[a.index('--prompt-file')+1])\ntime.sleep(.08)\nprint(json.dumps({'response':json.dumps({'body':p.read_text('utf8'),'session':a[a.index('--session-id')+1]})}))\n",encoding='utf8')
    base=GrokCLIProvider(executable=sys.executable,model='fixture')
    monkeypatch.setattr(base,'_request_command',lambda prompt,schema,stream=False:
        [sys.executable,str(worker),'-p',prompt,'--cwd',str(tmp_path)])
    bodies=[f'批次{i} 中文😀 引号" 路径\\\n'+'x'*30509 for i in range(4)]
    def run(body):
        provider=base.fork_request()
        return json.loads(provider.complete([dict(role='user',content=body)],timeout=5))
    with ThreadPoolExecutor(4) as pool:
        responses=list(pool.map(run,bodies))
    assert [x['body'] for x in responses]==['[USER]\n'+x for x in bodies]
    assert len({x['session'] for x in responses})==4
    assert not list(tmp_path.glob('2b-*/p.txt'))


@pytest.mark.parametrize('cancel', [True,False])
def test_real_cli_cancel_or_timeout_cleans_owned_request(monkeypatch,tmp_path,cancel):
    import time
    monkeypatch.setattr('tempfile.tempdir',str(tmp_path))
    worker=tmp_path/'slow_cli.py'
    worker.write_text('import time\ntime.sleep(45)\n',encoding='utf8')
    provider=GrokCLIProvider(executable=sys.executable)
    monkeypatch.setattr(provider,'_request_command',lambda prompt,schema,stream=False:
        [sys.executable,str(worker),'-p',prompt,'--cwd',str(tmp_path)])
    began=time.monotonic()
    with pytest.raises(AIProviderError) as caught:
        provider.complete([dict(role='user',content='中文'*1000)],timeout=.3 if not cancel else 4,
            cancel_check=(lambda:time.monotonic()-began>.3) if cancel else None)
    assert caught.value.category==('cancelled' if cancel else 'timeout')
    assert time.monotonic()-began<5
    assert not list(tmp_path.glob('2b-*/p.txt'))
