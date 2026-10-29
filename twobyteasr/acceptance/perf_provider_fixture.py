"""Local HTTP fixtures through the real frozen broker; never sends a request.

Only the explicit perf-regression audit installs this private service type.
The application service remains denied, external sockets remain blocked, and
the private service's HTTP boundary accepts only the literal fixture URL.
"""
from __future__ import annotations

import json
import threading
import time

_service_type = None


def install_guards():
    global _service_type
    from ..providers.provider_service import ProviderService
    # Retain the real submit implementation on a private subclass before the
    # normal offline guard denies all application/background service requests.
    _service_type = type('FixtureService', (ProviderService,), {'submit': ProviderService.submit})
    from .blank_project_audit import install_offline_guards
    install_offline_guards()


def run(service_type=None):
    from .studio_acceptance_audit import require
    from ..providers import network_policy
    from ..providers.ai_providers import OpenAICompatibleProvider
    from ..projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from ..subtitle_rules.subtitle_translation import translate
    from ..system.resource_governor import ResourceGovernor

    service_type = service_type or _service_type
    require(service_type is not None, 'Fixture guard must be installed before UI setup')
    project = SubtitleProject(media=StudioMedia(path='fixture.mp4', duration_ms=5000),
        cues=[StudioCue(f'c{i}', i*1000, i*1000+900, text) for i, text in enumerate(
            ['行くぞ！', 'ちょっと待って、まだ準備できてない', 'このボス強すぎる', '回復して！'])])
    project.generation_metadata['language'] = {'code': 'ja'}
    translations = ['走了！', '等一下，我还没准备好', '这个Boss太强了', '快回血！']
    settings = {'models': {'polish_provider': 'custom', 'polish_base_url': 'http://127.0.0.1:18000/v1',
                          'polish_model': 'fixture', 'polish_api_key': 'fixture'}}
    barrier = threading.Barrier(4)
    lock = threading.Lock()
    calls = []
    mode = ['parallel']

    class Response:
        headers = {'Retry-After': '0'}
        text = 'local fixture'
        def __init__(self, status, body=None): self.status_code, self.body = status, body
        def raise_for_status(self):
            if self.status_code == 429:
                import requests
                raise requests.HTTPError('429', response=self)
        def json(self): return self.body

    def post(url, **kwargs):
        require(url == 'http://127.0.0.1:18000/v1/chat/completions', 'Non-fixture URL blocked')
        require(kwargs['json']['model'] == 'fixture', 'Non-fixture model blocked')
        payload = json.loads(kwargs['json']['messages'][-1]['content'])
        ids = payload['output_ids']
        require(len(ids) == 1 and ids[0] in {'c0','c1','c2','c3'}, 'Unexpected fixture payload')
        with lock:
            calls.append(list(ids))
            count = len(calls)
        require(count <= 4 if mode[0] == 'parallel' else count <= 3, 'Fixture call limit exceeded')
        if mode[0] == 'retry' and count == 1:
            return Response(429)
        i = int(ids[0][1:])
        return Response(200, {'choices': [{'message': {'content': json.dumps(
            {'items': [{'id': ids[0], 'translation': translations[i]}]}, ensure_ascii=False)},
            'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100+i, 'completion_tokens': 20, 'total_tokens': 120+i}})

    original_post, complete = network_policy.post, OpenAICompatibleProvider.complete
    def synchronized(self, *args, **kwargs):
        value = complete(self, *args, **kwargs)
        barrier.wait(timeout=10)
        return value
    events = []
    started = time.perf_counter()
    try:
        network_policy.post = post
        OpenAICompatibleProvider.complete = synchronized
        service = service_type(workers=4, governor=ResourceGovernor(background_limit=1))
        result = translate(project, None, service.client_for_stage(settings, 'polish'), target='zh-Hans',
            max_items=1, workers=4, event=events.append, retry_wait=lambda _: True, timeout=15)
        require(list(result.translations) == ['c0','c1','c2','c3'] and not result.failed,
                'Parallel fixture lost or misordered IDs')
        by_batch = {e['batch']: int(e['ids'][0][1:]) for e in events if e['event'] == 'request'}
        receipts = [e for e in events if e['event'] == 'response']
        require(len(receipts) == 4 and len(calls) == 4, 'Four real requests must overlap')
        require(all(e['usage']['prompt_tokens'] == 100+by_batch[e['batch']] for e in receipts),
                'Concurrent usage receipts crossed batches')
        parallel_s = time.perf_counter()-started
        OpenAICompatibleProvider.complete = complete
        mode[0] = 'retry'
        calls.clear()
        retry_service = service_type(circuit_failures=1, governor=ResourceGovernor(background_limit=1))
        result = translate(project, ['c0','c1'], retry_service.client_for_stage(settings, 'polish'),
            target='zh-Hans', max_items=1, workers=1, retry_wait=lambda _: True, timeout=15)
        require(list(result.translations) == ['c0','c1'] and not result.failed,
                'A transient 429 poisoned the broker')
        require(calls == [['c0'],['c0'],['c1']], 'Retry repeated a successful sibling')
        return {'passed': True, 'real_broker_overlap': 4, 'usage_receipts_correct': True,
                'retry_calls': calls, 'parallel_s': parallel_s, 'paid_requests': 0,
                'scope': 'literal local HTTP fixtures through actual packaged broker and translator'}
    finally:
        OpenAICompatibleProvider.complete = complete
        network_policy.post = original_post
