import json,subprocess
from pathlib import Path
from twobyteasr.providers.codex_cli_provider import CodexCLIProvider


def test_omitted_modalities_follow_installed_cli_protocol(monkeypatch,tmp_path):
    monkeypatch.setattr(CodexCLIProvider,'_discover_executable',lambda self:str(tmp_path/'codex.exe'))
    provider=CodexCLIProvider(model='local-model')
    monkeypatch.setattr(provider,'_verify_capabilities',lambda *a,**kw:{})
    provider._capability_cache[provider.executable]={'image_flag':True}
    def run(command,**kwargs):
        if '--stdio' in command:
            kwargs['on_line']('stdout',json.dumps({'id':2,'result':{'data':[{'model':'local-model'}]}}))
        else:
            assert command[1:4]==['app-server','generate-json-schema','--out']
            Path(command[4],'protocol.json').write_text(json.dumps({'definitions':{'Model':{'properties':{
                'inputModalities':{'default':['text','image']}}}}}),encoding='utf-8')
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(provider,'_run_cli_command',run)
    assert provider.discover_models(refresh=True)==('local-model',)
    assert provider.runtime_capabilities()['vision']


def test_blank_cli_model_survives_settings_api_defaults_without_reading_keys(monkeypatch,tmp_path):
    from twobyteasr.providers.llm_config import activate_ai_service,update_active_profile,endpoint_from_settings
    from twobyteasr.storage.settings import save_runtime_settings
    settings={'models':{},'switches':{'unified_glm_processing':True}}
    activate_ai_service(settings,'codex_cli');update_active_profile(settings,model='')
    saved,_,_=save_runtime_settings(settings,tmp_path)
    monkeypatch.setattr('twobyteasr.providers.llm_config.read_scoped_api_key',lambda *a:(_ for _ in ()).throw(AssertionError('CLI must not read API keys')))
    endpoint=endpoint_from_settings(saved,'polish')
    assert endpoint['model']=='' and endpoint['base_url']=='' and endpoint['api_key']==''
    from twobyteasr.providers.ai_providers import adapter_for_stage
    from twobyteasr.providers.provider_service import ProviderService
    assert adapter_for_stage(saved,'polish').model==''
    key=ProviderService._config_key(saved,'polish',None)
    saved['models']['polish_model']='unrelated-api-default'
    assert ProviderService._config_key(saved,'polish',None)==key
