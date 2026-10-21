from types import SimpleNamespace
import pytest
from twobyteasr.providers import model_discovery as discovery
from twobyteasr.providers.llm_config import models_url, resolved_service_values, update_active_profile, activate_ai_service


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda:payload)


@pytest.fixture(autouse=True)
def clear():
    discovery._cache.clear()


def test_ids_metadata_and_account_isolation(monkeypatch):
    calls=[]
    def get(url, **kw):
        calls.append((url,kw))
        return response({'data':[{'id':'vendor/New-Alias','context_length':65536,'input_modalities':['text','image']}]})
    monkeypatch.setattr('requests.get',get)
    value=discovery.discover('custom','https://relay.example/custom/','one')
    assert value['records'][0]['id']=='vendor/New-Alias'
    assert calls[0][0]=='https://relay.example/custom/models'
    assert calls[0][1]['allow_redirects'] is False
    assert discovery.cached('custom','https://relay.example/custom','two') is None
    assert discovery.cached('custom','https://other.example/custom','one') is None
    assert discovery.model_limits('custom','https://relay.example/custom','one','unknown')=={}
    assert discovery.model_limits('custom','https://relay.example/custom','one','vendor/New-Alias')['context_tokens']==65536


@pytest.mark.parametrize('status,category',[(401,'unauthorized'),(403,'forbidden'),(404,'unsupported'),(429,'rate_limited'),(302,'redirect')])
def test_failures_preserve_prior_cache(monkeypatch,status,category):
    discovery.remember('xai','https://relay.example/v1','k',[{'id':'prior'}])
    monkeypatch.setattr('requests.get',lambda *a,**k:response({},status))
    with pytest.raises(discovery.DiscoveryError) as error:
        discovery.discover('xai','https://relay.example/v1','k',force=True)
    assert category in error.value.category
    assert discovery.cached('xai','https://relay.example/v1','k')['records']==[{'id':'prior'}]


def test_pagination_and_cross_host_key_protection(monkeypatch):
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        return response({'data':[{'id':'first'}],'next':'https://other.example/models'})
    monkeypatch.setattr('requests.get',get)
    with pytest.raises(discovery.DiscoveryError,match='另一主机'):
        discovery.discover('custom','https://relay.example/v1','k')
    assert len(calls)==1
    monkeypatch.setattr('requests.get',lambda *a,**kw:response({'data':[{'id':'second'}]} if kw['params'] else
        {'data':[{'id':'first'}],'has_more':True,'last_id':'first'}))
    assert [r['id'] for r in discovery.discover('custom','https://relay.example/v1','k')['records']]==['first','second']


def test_empty_unknown_capabilities_and_selected_id(monkeypatch):
    monkeypatch.setattr('requests.get',lambda *a,**k:response([]))
    with pytest.raises(discovery.DiscoveryError,match='空模型'):
        discovery.discover('xai','https://relay.example/v1','k')
    records=discovery._records(['vision-name-is-not-evidence'],'fixture')
    assert records[0]['input_modalities'] is None and records[0]['context_tokens'] is None
    settings={'models':{}}
    activate_ai_service(settings,'xai')
    update_active_profile(settings,model='prefix/grok-4.7-alias',base_url='https://relay.example/v1')
    assert resolved_service_values(settings,'xai')['model']=='prefix/grok-4.7-alias'
    assert models_url('https://relay.example/v1/v1/')=='https://relay.example/v1/models'
