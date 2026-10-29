"""Real pipes exercise first-byte latency, cancellation and shared health identity."""
import copy
import json
import subprocess
import sys
import threading
import time

import pytest

@pytest.fixture(autouse=True)
def isolated_cli_logs(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    monkeypatch.setenv('APPDATA',str(tmp_path/'roaming'))

from twobyteasr.providers.ai_providers import AIProviderError, AntigravityCLIProvider, CLIProvider, ProviderStatus
from twobyteasr.providers.llm_config import activate_ai_service, update_active_profile, cache_service_models, service_model_catalog
from twobyteasr.providers.provider_service import ProviderService


def test_real_first_byte_precedes_exit_and_redacts_failure():
    provider = CLIProvider(executable=sys.executable)
    command = [sys.executable, '-u', '-c', "import sys,time; print('ready',flush=True); time.sleep(.3); print('Bearer abcSECRETdef',file=sys.stderr); sys.exit(7)"]
    result = provider._run_cli_command(command, purpose='model request', timeout=3)
    assert result.returncode == 7
    times = provider.last_timings
    assert times['process_seconds'] - times['first_stdout_seconds'] > .2
    trace = json.dumps(provider.last_invocation_trace)
    assert 'abcSECRETdef' not in trace
    assert provider.last_invocation_trace['request_id']
    assert times['first_stderr_seconds'] is not None


def test_real_silent_process_cancels_without_waiting_for_timeout():
    provider = CLIProvider(executable=sys.executable)
    cancel = threading.Event()
    timer = threading.Timer(.15, cancel.set)
    timer.start()
    began = time.perf_counter()
    with pytest.raises(AIProviderError) as error:
        provider._run_cli_command([sys.executable, '-c', 'import time;time.sleep(30)'],
            purpose='models', timeout=20, cancel_check=cancel.is_set)
    assert error.value.category == 'cancelled'
    assert time.perf_counter() - began < 2
    assert provider._active_process is None
    assert provider.last_invocation_trace['exit_code'] is not None


def test_streaming_first_byte_and_stderr_use_same_diagnostics():
    provider = AntigravityCLIProvider(executable=sys.executable, model='test-high')
    payload = json.dumps({'event':'result','result':{'response':'{"ok":true}'}})
    events = []
    command = [sys.executable, '-u', '-c', f"import time,sys;print('Bearer ABCsecret',file=sys.stderr,flush=True);time.sleep(.25);print({payload!r},flush=True);time.sleep(20)"]
    text = provider._run_cli_stream(command,purpose='streaming request',timeout=3,on_stream_event=lambda *args:events.append(args))
    assert text == '{"ok":true}'
    assert provider.last_timings['first_stdout_seconds']-provider.last_timings['first_stderr_seconds'] > .15
    assert provider.last_timings['response_complete']
    assert 'ABCsecret' not in json.dumps(events)
    assert provider.last_invocation_trace['stderr']


def test_shared_runtime_ignores_ui_options_and_keeps_model_identity(monkeypatch):
    settings = {'models': {}, 'switches': {'unified_glm_processing': True}}
    activate_ai_service(settings,'antigravity',stage='polish')
    update_active_profile(settings,stage='polish',model='gemini-3.8-flash-high')
    calls = []
    class Adapter(AntigravityCLIProvider):
        def validate(self, **kwargs):
            calls.append(kwargs)
            return ProviderStatus(True,True,'real High response',())
        def complete(self,*args,**kwargs):return 'ok'
    monkeypatch.setattr('twobyteasr.providers.provider_service.adapter_for_stage',lambda *_a,**_k:Adapter(model='gemini-3.8-flash-high',executable='fixture'))
    broker = ProviderService()
    home = broker.client_for_stage(settings,'polish')
    home.validate(timeout=20,use_cache=False)
    other = copy.deepcopy(settings); other['ui']={'panel':'studio'}
    studio = broker.client_for_stage(other,'polish')
    assert studio.validate().authenticated
    assert studio.last_timings['cache_hit']
    assert len(calls)==1 and calls[0]['timeout']==20
    group = broker.client_for_stage(other,'group')
    assert group.validate().authenticated
    assert group.last_timings['cache_hit']
    assert len(calls)==1
    update_active_profile(other,stage='polish',model='gemini-3.8-flash-medium')
    assert broker._config_key(other,'polish',None)!=broker._config_key(settings,'polish',None)


def test_catalogue_failure_does_not_invalidate_high_readiness(monkeypatch):
    provider = AntigravityCLIProvider(model='gemini-3.8-flash-high',executable='fixture-agy')
    provider._store_status(ProviderStatus(True,True,'High OK',()))
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired('agy models',20)
    monkeypatch.setattr(provider,'_run_cli_command',timeout)
    with pytest.raises(AIProviderError) as error:provider.discover_models(refresh=True)
    assert error.value.category=='model_discovery'
    assert provider.validate().authenticated
    medium = AntigravityCLIProvider(model='gemini-3.8-flash-medium',executable='fixture-agy')
    assert medium._cached_status() is None
    cache_service_models('antigravity',('gemini-3.8-flash-medium',))
    settings={'models':{}}
    activate_ai_service(settings,'antigravity',stage='polish')
    update_active_profile(settings,stage='polish',model='gemini-3.8-flash-high')
    assert 'gemini-3.8-flash-high' in service_model_catalog(settings,'antigravity')
