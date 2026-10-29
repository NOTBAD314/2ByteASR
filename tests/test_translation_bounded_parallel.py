"""Real overlap, bounded admission, failure isolation and deterministic identity."""
import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from tests.test_subtitle_translation import make_project, FakeProvider, run


def test_four_requests_really_overlap_and_merge_in_timeline_order():
    barrier = threading.Barrier(4)
    class Provider(FakeProvider):
        def structured_complete(self, messages, schema, **kwargs):
            payload = json.loads(messages[-1]['content'])
            barrier.wait(timeout=5)
            return self.translate_all(payload, 0)
    result = run(make_project(), Provider(), max_items=3, workers=4)
    assert list(result.translations) == [f'c{i}' for i in range(10)]
    assert result.requests == 4 and not result.failed and not result.pending


def test_cancel_admits_no_additional_batches_and_retains_successes():
    cancelled = threading.Event()
    lock = threading.Lock()
    entered = []
    barrier = threading.Barrier(4)
    class Provider(FakeProvider):
        def structured_complete(self, messages, schema, **kwargs):
            payload = json.loads(messages[-1]['content'])
            with lock:
                entered.append(payload['output_ids'])
            barrier.wait(timeout=5)
            cancelled.set()
            return self.translate_all(payload,0)
    result = run(make_project(), Provider(), max_items=1, workers=4,cancel_check=cancelled.is_set)
    assert len(entered)==4
    assert result.cancelled and len(result.translations)==4 and len(result.pending)==6


def test_retry_only_failed_ids_with_parallel_siblings():
    seen=Counter();lock=threading.Lock()
    class Provider(FakeProvider):
        def structured_complete(self,messages,schema,**kwargs):
            payload=json.loads(messages[-1]['content'])
            with lock:
                seen.update(payload['output_ids'])
                first=seen['c1']==1
            answer=self.translate_all(payload,0)
            if first:
                answer['items']=[i for i in answer['items'] if i['id']!='c1']
            return answer
    result=run(make_project(),Provider(),max_items=3,workers=4)
    assert len(result.translations)==10 and not result.failed
    assert seen['c1']==2 and all(n==1 for i,n in seen.items() if i!='c1')


def test_clients_own_their_receipt_and_share_service():
    from twobyteasr.providers.provider_service import ProviderService
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    client=ProviderService().client_for_stage(DEFAULT_SETTINGS,'polish')
    other=client.concurrent_client()
    client._last_request_trace={'request_id':'first'}
    other._last_request_trace={'request_id':'second'}
    assert client._service is other._service
    assert client.invocation_trace()['request_id']=='first'
    assert other.invocation_trace()['request_id']=='second'


def test_ai_network_slots_are_independent_of_cpu_limit_and_interactive_gate_is_one():
    from twobyteasr.system.resource_governor import ResourceGovernor,ResourceKind
    governor=ResourceGovernor(background_limit=1)
    barrier=threading.Barrier(4)
    def work():
        with governor.lease(ResourceKind.AI) as allowed:
            assert allowed
            barrier.wait(timeout=5)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(work) for _ in range(4)]
        for f in futures:f.result()
    governor.set_playback(True)
    with governor.lease(ResourceKind.AI):
        assert governor.should_yield(ResourceKind.AI)
    assert not governor.should_yield(ResourceKind.AI)


def test_parallel_http_usage_belongs_to_the_matching_batch(monkeypatch):
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
    from twobyteasr.providers.provider_service import ProviderService
    from tests.test_subtitle_translation import JA
    barrier=threading.Barrier(4)
    class Response:
        status_code=200;headers={};text=''
        def __init__(self,body):self.body=body
        def raise_for_status(self):pass
        def json(self):return self.body
    def post(url,**kwargs):
        payload=json.loads(kwargs['json']['messages'][-1]['content'])
        i=int(payload['output_ids'][0][1:])
        return Response({'choices':[{'message':{'content':json.dumps(FakeProvider.translate_all(payload,0))},'finish_reason':'stop'}],
                         'usage':{'prompt_tokens':100+i,'completion_tokens':20,'total_tokens':120+i}})
    monkeypatch.setattr('twobyteasr.providers.network_policy.post',post)
    complete=OpenAICompatibleProvider.complete
    def synchronized(self,*args,**kwargs):
        value=complete(self,*args,**kwargs)
        barrier.wait(timeout=5)  # Every adapter has assigned its usage before any broker copies it.
        return value
    monkeypatch.setattr(OpenAICompatibleProvider,'complete',synchronized)
    settings={'models':{'polish_provider':'custom','polish_base_url':'http://127.0.0.1:18000/v1',
                        'polish_model':'fixture','polish_api_key':'fixture'}}
    events=[];service=ProviderService(workers=4)
    result=run(make_project(JA[:4]),service.client_for_stage(settings,'polish'),max_items=1,workers=4,event=events.append)
    assert len(result.translations)==4
    by_batch={e['batch']:int(e['ids'][0][1:]) for e in events if e['event']=='request'}
    for event in events:
        if event['event']=='response':assert event['usage']['prompt_tokens']==100+by_batch[event['batch']]


def test_rate_limit_retry_recovers_without_poisoning_sibling_batches(monkeypatch):
    from twobyteasr.providers.provider_service import ProviderService
    from tests.test_subtitle_translation import JA
    calls=[]
    class Response:
        headers={'Retry-After':'0'};text='rate limited'
        def __init__(self,status,body=None):self.status_code=status;self.body=body
        def raise_for_status(self):
            if self.status_code==429:
                import requests
                raise requests.HTTPError('429',response=self)
        def json(self):return self.body
    def post(url,**kwargs):
        payload=json.loads(kwargs['json']['messages'][-1]['content']);calls.append(payload['output_ids'])
        if len(calls)==1:return Response(429)
        return Response(200,{'choices':[{'message':{'content':json.dumps(FakeProvider.translate_all(payload,0))},'finish_reason':'stop'}]})
    monkeypatch.setattr('twobyteasr.providers.network_policy.post',post)
    settings={'models':{'polish_provider':'custom','polish_base_url':'http://127.0.0.1:18000/v1',
                        'polish_model':'fixture','polish_api_key':'fixture'}}
    service=ProviderService(circuit_failures=1)
    result=run(make_project(JA[:2]),service.client_for_stage(settings,'polish'),max_items=1,workers=1)
    assert list(result.translations)==['c0','c1'] and not result.failed
    assert calls==[['c0'],['c0'],['c1']]
