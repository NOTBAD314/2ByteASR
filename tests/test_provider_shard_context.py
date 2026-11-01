from dataclasses import replace
from types import SimpleNamespace

from twobyteasr.providers.ai_providers import AITransport
from twobyteasr.providers.provider_service import ProviderService
from twobyteasr.recognition.run_context import RuntimeContext,activate_runtime_context,local_runtime_context,get_runtime_context


def test_admission_and_transport_use_the_same_shard_owner(monkeypatch):
    service=ProviderService(workers=1)
    runtime=SimpleNamespace(key='fixture',stage='group',transport=AITransport.OPENAI_COMPATIBLE,
        adapter=SimpleNamespace(endpoint={'base_url':'https://api.deepseek.com/v1','api_key':'fixture'}))
    monkeypatch.setattr(service,'_runtime_for',lambda *a,**k:runtime)
    seen=[]
    def execute(request):
        seen.append(get_runtime_context().shard_id)
        assert not request.external_cancel()
        return {'owner':get_runtime_context().shard_id}
    monkeypatch.setattr(service,'_execute',execute)
    root=RuntimeContext()
    child=replace(root,root_context=root,shard_id='r001')
    with activate_runtime_context(root),local_runtime_context(child):
        handle=service.submit({},'group',[{'role':'user','content':'fixture'}],timeout=2,
            cancel_check=lambda:get_runtime_context() is not child)
        assert handle.result(3)=={'owner':'r001'}
    assert seen==['r001'] and service.wait_for_idle(1)
