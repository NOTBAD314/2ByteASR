import json
import subprocess
from pathlib import Path

import pytest

from twobyteasr.providers.ai_providers import AIProviderError, AITransport, adapter_for_stage
from twobyteasr.providers.codex_cli_provider import CodexCLIProvider
from twobyteasr.providers.llm_config import activate_ai_service, active_service_values, update_active_profile
from twobyteasr.storage.settings import save_runtime_settings, load_runtime_settings


@pytest.fixture
def provider():
    p=CodexCLIProvider(executable='fixture-official-codex.exe',model='verified-test-model')
    p._capability_cache[p.executable]={'version':'test','image_flag':True,'disabled_features':p._disabled_features}
    p.invalidate_status_cache()
    return p


def test_codex_profile_is_independent_from_openai_api_and_roundtrips(tmp_path):
    settings={'models':{}}
    activate_ai_service(settings,'codex_cli',stage='polish')
    update_active_profile(settings,stage='polish',model='verified-test-model')
    saved,_,_=save_runtime_settings(settings,project_root=tmp_path)
    reopened,_,_=load_runtime_settings(project_root=tmp_path)
    assert active_service_values(reopened,stage='polish')['model']=='verified-test-model'
    assert reopened['models']['polish_transport']=='codex_cli'
    assert isinstance(adapter_for_stage(reopened,'polish'),CodexCLIProvider)
    activate_ai_service(reopened,'openai',stage='polish')
    assert active_service_values(reopened,stage='polish')['model']!='verified-test-model'


def test_status_uninstalled_and_logged_out(provider,monkeypatch):
    provider.executable=''
    assert not provider.validate(use_cache=False).available
    provider.executable='fixture-official-codex.exe'
    monkeypatch.setattr(provider,'_run_cli_command',lambda *a,**k:subprocess.CompletedProcess(a[0],1,'','Not logged in'))
    status=provider.validate(use_cache=False)
    assert status.available and not status.authenticated
    assert '未登录' in status.message


def test_session_success_does_not_claim_model_request_success(provider,monkeypatch):
    monkeypatch.setattr(provider,'_run_cli_command',lambda *a,**k:subprocess.CompletedProcess(a[0],0,'','Logged in using ChatGPT'))
    status=provider.validate(use_cache=False)
    assert status.authenticated and '待真实请求验证' in status.message


def test_design_uses_stdin_isolated_readonly_and_native_schema(provider,monkeypatch):
    seen={}
    schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
    def run(command,**kwargs):
        seen.update(command=command,cwd=kwargs['cwd'],prompt=kwargs['input_text'])
        assert command[-1]=='-' and 'SECRET DESIGN PROMPT' not in ' '.join(command)
        assert command[command.index('--sandbox')+1]=='read-only'
        assert command[command.index('--ask-for-approval')+1]=='never'
        assert '--ignore-user-config' in command and '--ignore-rules' in command and '--ephemeral' in command
        for feature in ('shell_tool','unified_exec','multi_agent','plugins','browser_use'):
            assert command[command.index(feature)-1]=='--disable'
        assert Path(kwargs['cwd']).resolve()!=Path.cwd().resolve()
        assert json.loads(Path(command[command.index('--output-schema')+1]).read_text())==schema
        kwargs['on_line']('stdout',json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{"ok":true}'}}))
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(provider,'_run_cli_command',run)
    assert provider.structured_complete([{'role':'user','content':'SECRET DESIGN PROMPT'}],schema)=={'ok':True}
    assert not Path(seen['cwd']).exists()


def test_failure_preserves_safe_reason_and_schema_rejects(provider,monkeypatch):
    def run(command,**kwargs):return subprocess.CompletedProcess(command,1,'','401 not authenticated Bearer REDACT_ME')
    monkeypatch.setattr(provider,'_run_cli_command',run)
    with pytest.raises(AIProviderError) as error:provider.complete([{'role':'user','content':'text'}])
    assert error.value.category=='authentication_required'
    assert 'REDACT_ME' not in str(error.value)
    monkeypatch.setattr(provider,'complete',lambda *a,**k:'{"unexpected":true}')
    with pytest.raises(AIProviderError) as error:
        provider.structured_complete([],{'type':'object','required':['ok']})
    assert error.value.category=='schema_validation'


def test_model_protocol_uses_official_method_and_capabilities(provider,monkeypatch):
    def run(command,**kwargs):
        assert command[1:]==['app-server','--stdio']
        packets=[json.loads(line) for line in kwargs['input_text'].splitlines()]
        assert [x['method'] for x in packets]==['initialize','initialized','model/list']
        kwargs['on_line']('stdout',json.dumps({'id':2,'result':{'data':[{'model':'verified-test-model','inputModalities':['text','image']}]}}))
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(provider,'_run_cli_command',run)
    assert provider.discover_models(refresh=True)==('verified-test-model',)
    assert provider.runtime_capabilities()['vision']
