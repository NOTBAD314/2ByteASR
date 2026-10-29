"""Optional AI must have no credential/client/request side effects when off."""
import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from twobyteasr.recognition.text_ai_plan import text_ai_plan, bind_text_ai_snapshots
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.providers.llm_config import validate_endpoint, endpoint_requires_key


@pytest.mark.parametrize('old_models', [{}, {'polish_model':'old', 'ai_service':'deepseek'}])
def test_off_task_never_resolves_a_provider(old_models):
    settings = {'models':old_models, 'switches':{'enable_ai_polish':False,'use_ai_grouping':False}}
    context = RuntimeContext(asr_settings_snapshot=settings)
    def forbidden(*a, **k):
        pytest.fail('Disabled stage resolved credentials or provider')
    assert bind_text_ai_snapshots(context, settings, resolver=forbidden).roles == ()
    assert context.provider_snapshots == {} and context.provider_snapshot is None
    import moss_firered_pipeline as pipeline
    with activate_runtime_context(context):
        events=[]
        pipeline._preflight_cloud_stages(SimpleNamespace(RUNTIME_SETTINGS=settings, record_run_event=lambda *a,**k:events.append((a,k))))
    assert [e[1]['stage'] for e in events] == ['polish','group']


def test_enabled_roles_are_frozen_independently_and_analysis_has_none():
    settings={'switches':{'enable_ai_polish':True,'use_ai_grouping':False}}
    seen=[]; context=RuntimeContext()
    bind_text_ai_snapshots(context,settings,resolver=lambda s,stage:seen.append(stage) or stage)
    assert seen == ['polish'] and context.provider_snapshot is None
    assert text_ai_plan({},purpose='analysis').roles == ()
    assert text_ai_plan({}).roles == ('polish','group')  # legacy behavior


def test_persistence_and_profile_restart_preserve_explicit_off(tmp_path,monkeypatch):
    from twobyteasr.app import ui
    from twobyteasr.providers import llm_config
    from twobyteasr.recognition.recognition_profiles import ProjectProfileStore,normalize_llm_config
    from twobyteasr.storage.settings import DEFAULT_SETTINGS,save_runtime_settings,load_runtime_settings
    endpoint=dict(service='deepseek',provider='deepseek',transport='openai_compatible',model='stale',base_url='',protocol='auto')
    forbidden=lambda *a,**k:pytest.fail('Disabled form requested credentials')
    monkeypatch.setattr(ui,'read_api_key',forbidden);monkeypatch.setattr(ui,'resolve_api_key',forbidden)
    legacy=SimpleNamespace(RUNTIME_SETTINGS=copy.deepcopy(DEFAULT_SETTINGS))
    values=ui.persist_ai_configuration(legacy,endpoint,endpoint,unified=False,share_key=False,
        use_ai_grouping=False,enable_ai_polish=False,require_ready=True,dry_run=True)
    assert values['missing_keys'] == ()
    snapshot=normalize_llm_config(dict(polish=endpoint,group=endpoint,unified=False,use_ai_grouping=False,enable_ai_polish=False))
    store=ProjectProfileStore(tmp_path/'profiles.json');p=store.create('offline')
    store.update(p.id,llm_enabled=False,llm_config=snapshot)
    reopened=ProjectProfileStore(tmp_path/'profiles.json').get(p.id)
    assert reopened.llm_config['enable_ai_polish'] is False
    settings=copy.deepcopy(DEFAULT_SETTINGS);settings['switches'].update(enable_ai_polish=False,use_ai_grouping=False)
    # Actual persistence boundary, inside the temporary project/config root.
    saved,path,warnings=save_runtime_settings(settings,project_root=tmp_path)
    loaded=load_runtime_settings(project_root=tmp_path)[0]
    assert text_ai_plan(loaded).roles == ()


@pytest.mark.parametrize('language,expected', [('zh','字幕校对'),('en','API key'),('ja','API キー')])
def test_missing_key_names_enabled_stage_and_provider_in_three_languages(monkeypatch,language,expected):
    from twobyteasr import i18n
    monkeypatch.setattr(i18n,'_CURRENT_LANGUAGE_CACHE',language)
    with pytest.raises(RuntimeError) as info:
        validate_endpoint(dict(provider='deepseek',model='deepseek-chat',base_url='https://api.deepseek.com/v1'), '字幕校对模型')
    assert expected in str(info.value) and 'deepseek' in str(info.value)


@pytest.mark.parametrize('provider,url,required', [('custom','http://127.0.0.1:1234/v1',False),('custom','http://localhost:1234/v1',False),('deepseek','http://localhost:1234/v1',True),('custom','https://example.org/v1',True)])
def test_no_auth_is_only_explicit_local_custom(provider,url,required):
    assert endpoint_requires_key(dict(provider=provider,base_url=url)) is required


@pytest.fixture
def local_server():
    state={'status':200,'body':{'choices':[{'message':{'content':'{"edits":[]}'}}]},'auth':None}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state['auth']=self.headers.get('Authorization')
            state['request']=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(state['status']);self.end_headers()
            self.wfile.write(json.dumps(state['body']).encode() if not isinstance(state['body'],bytes) else state['body'])
        def log_message(self,*a): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1',state
    server.shutdown();server.server_close();thread.join()


def request_local(url,diagnostics=None):
    from twobyteasr.providers.asr_http_transport import complete
    return complete([{'role':'user','content':'原创测试'}],model='local-test',api_key='',url=url+'/chat/completions',
        base_url=url,provider='custom',max_tokens=64,timeout=(1,2),request_diagnostics=diagnostics)


def test_legitimate_no_auth_service_really_sends_without_authorization(local_server):
    url,state=local_server
    validate_endpoint(dict(provider='custom',model='local-test',base_url=url,api_key=''),'字幕校对模型')
    assert json.loads(request_local(url)) == {'edits':[]}
    assert state['auth'] is None and state['request']['model'] == 'local-test'


@pytest.mark.parametrize('status,category', [(401,'auth_error'),(403,'auth_error'),(429,'rate_limited'),(404,'configuration_error'),(500,'server_error')])
def test_actual_transport_classifies_http_failure(local_server,status,category):
    from twobyteasr.providers.llm_adapter import LLMRequestError
    url,state=local_server;state['status']=status
    with pytest.raises(LLMRequestError) as info: request_local(url)
    assert info.value.category == category


def test_actual_transport_rejects_unparseable_response(local_server):
    from twobyteasr.providers.llm_adapter import LLMRequestError
    url,state=local_server;state['body']=b'not-json'
    with pytest.raises(LLMRequestError) as info: request_local(url)
    assert info.value.category == 'parse_failure'


def test_network_and_tls_error_categories():
    import requests
    from twobyteasr.providers.asr_provider_snapshot import classify_request_error
    assert classify_request_error(requests.ConnectTimeout()) == 'connect_timeout'
    assert classify_request_error(requests.ReadTimeout()) == 'read_idle_timeout'
    assert classify_request_error(requests.ConnectionError()) == 'connection_error'
    assert classify_request_error(requests.exceptions.SSLError()) == 'tls_error'


@pytest.mark.parametrize('code,category',[('model_not_found','model_not_supported'),('unsupported_parameter','unsupported_parameters'),('content_policy_violation','provider_refusal')])
def test_model_protocol_and_explicit_refusal_are_distinct(local_server,code,category):
    from twobyteasr.providers.llm_adapter import LLMRequestError
    url,state=local_server;state.update(status=400,body={'error':{'code':code}})
    with pytest.raises(LLMRequestError) as info: request_local(url)
    assert info.value.category==category


def test_translation_and_search_freeze_service_without_enabling_polish():
    settings={'switches':{'enable_ai_polish':False,'use_ai_grouping':False}}
    for options in ({'subtitle_output':'bilingual'},{'enable_term_search':True}):
        context=RuntimeContext(**options);seen=[]
        plan=bind_text_ai_snapshots(context,settings,resolver=lambda s,stage:seen.append(stage) or 'frozen-polish')
        assert not plan.polish and not plan.group
        assert seen==['polish'] and context.provider_snapshots['polish']=='frozen-polish'
        assert context.provider_snapshot is None


def test_late_translation_uses_the_task_service_snapshot(monkeypatch):
    from twobyteasr.subtitle_rules.recognition_translation import translate_runtime_cues
    from twobyteasr.providers import ai_providers,asr_provider_snapshot
    captured=[]
    class Captured(Exception):pass
    frozen=SimpleNamespace(execution_settings=lambda:{'owned':'original-task'})
    context=RuntimeContext(subtitle_output='bilingual',task_language='en',translation_script='zh-Hans',
                           provider_snapshots={'polish':frozen})
    def provider(settings,role,**kwargs):
        captured.append((settings,role));raise Captured()
    monkeypatch.setattr(ai_providers,'provider_for_stage',provider)
    monkeypatch.setattr(asr_provider_snapshot,'resolve_provider_snapshot',lambda *a,**k:pytest.fail('late translation re-resolved mutable credentials'))
    with pytest.raises(Captured):
        translate_runtime_cues([SimpleNamespace(start=0,end=1,text='hello',speaker='S01')],context,
                               SimpleNamespace(RUNTIME_SETTINGS={'owned':'later-save'},record_run_event=lambda *a,**k:None))
    assert captured==[({'owned':'original-task'},'polish')]


def test_translation_snapshot_does_not_enable_optional_term_ai():
    from twobyteasr.providers.asr_provider_snapshot import task_role_enabled
    settings={'switches':{'enable_ai_polish':False,'use_ai_grouping':False}}
    context=RuntimeContext(subtitle_output='bilingual',asr_settings_snapshot=settings)
    bind_text_ai_snapshots(context,settings,resolver=lambda *a,**k:object())
    with activate_runtime_context(context):
        assert not task_role_enabled('polish')
        context.enable_term_search=True
        assert task_role_enabled('polish')
