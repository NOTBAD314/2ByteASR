from dataclasses import replace
import copy
import pytest
from twobyteasr.providers import llm_config
from twobyteasr.providers.ai_providers import AIProviderError
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
from twobyteasr.providers.provider_service import ProviderService
from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context,local_runtime_context
from twobyteasr.recognition.service import CancellationToken


def test_quota_rejection_blocks_sibling_stages_and_new_task_can_retry(monkeypatch):
    monkeypatch.setattr(llm_config,'read_scoped_api_key',lambda *a,**k:('fixture','test'))
    settings={'models':{'ai_service':'custom','provider_profiles':{'custom':{
        'model':'fixture','base_url':'http://127.0.0.1:1/v1','protocol':'openai_compatible_chat'}}}}
    snap=resolve_provider_snapshot(settings);service=ProviderService(workers=1);calls=[]
    def sender(*a,**kw):
        calls.append(kw['stage'])
        if len(calls)==1:raise AIProviderError('fixture quota',category='quota_exhausted')
        return '{}'
    def run(stage,snapshot=snap):
        return service.client_for_stage(snapshot.execution_settings(),stage,sender=sender).complete(
            [dict(role='user',content='fixture')],stage=stage,_timeout_policy=snapshot.timeout_policy,max_tokens=128)
    root=RuntimeContext(cancellation_token=CancellationToken())
    with activate_runtime_context(root):
        with local_runtime_context(replace(root,root_context=root,shard_id='r001')):
            with pytest.raises(AIProviderError,match='fixture quota'):run('polish')
        with local_runtime_context(replace(root,root_context=root,shard_id='r002')):
            with pytest.raises(AIProviderError,match='停止新请求'):run('group')
            with pytest.raises(AIProviderError,match='停止新请求'):run('translation')
        assert calls==['polish']
        other=copy.deepcopy(settings);other['models']['provider_profiles']['custom']['base_url']='http://127.0.0.1:2/v1'
        assert run('group',resolve_provider_snapshot(other))=='{}'
    with activate_runtime_context(RuntimeContext(cancellation_token=CancellationToken())):
        assert run('polish')=='{}'
    assert calls==['polish','group','polish'] and service.wait_for_idle(1)
