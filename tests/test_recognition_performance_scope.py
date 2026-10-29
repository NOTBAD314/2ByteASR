"""Offline production-path constraints, not a simulated wall-time speed claim."""
import json
import time
from types import SimpleNamespace

import pytest

from tests.test_stage9_cache_and_budget import context
from twobyteasr.glossary import domain_terms
from twobyteasr.subtitle_rules import grouping
from twobyteasr.providers.ai_providers import AIProviderError
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.providers.provider_input_budget import RetryBudget


def cue(i, text, speaker='S01'):
    return SpeechSegment(i, i*2., i*2.+1., text, .9, [], speaker=speaker,
        moss_text=text, firered_text=text, qwen_asr_text=text)


def test_alternating_speakers_share_one_labelled_request_without_crossing(context, monkeypatch):
    _, owner, _ = context
    rows = [cue(1,'这一次他已经拿到了机会','S01'),cue(2,'接下来准备看看对面怎么处理','S02'),cue(3,'我们还需要等待后续的反应','S01')]
    calls = []
    def complete(messages, **kwargs):
        data = json.loads(messages[-1]['content']);calls.append(data)
        assert [x['speaker'] for x in data['segments']] == ['S01','S02','S01']
        assert [x['id'] for x in data['segments']] == [1,2,3]
        assert len(data['protected_source_offsets']) == 2
        # Even a model omitting protected boundaries cannot merge speakers.
        return json.dumps({'boundaries':[data['total_length']]})
    monkeypatch.setattr(grouping,'provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    result = grouping.group_subtitles(rows, provider_snapshot=owner.provider_snapshot)
    assert len(calls) == 1 and result.validated
    for speaker in ('S01','S02'):
        assert ''.join(x.text for x in result if x.speaker == speaker) == ''.join(x.text for x in rows if x.speaker == speaker)


def test_finished_short_locked_turn_uses_explicit_local_origin(context, monkeypatch):
    _, owner, _ = context
    row = cue(1,'好！');row.timing_locked = True
    monkeypatch.setattr(grouping,'provider_for_stage',lambda *a,**k:pytest.fail('no unresolved split decision'))
    result = grouping.group_subtitles([row],provider_snapshot=owner.provider_snapshot)
    assert result.origin == 'local_fast' and result.validated and result[0].text == row.text


def test_short_incomplete_phrase_keeps_intelligent_context(context, monkeypatch):
    _, owner, _ = context
    row = cue(1,'因为');row.timing_locked = True
    calls = []
    def complete(messages, **kwargs):
        data = json.loads(messages[-1]['content']);calls.append(data)
        return json.dumps({'boundaries':[data['total_length']]})
    monkeypatch.setattr(grouping,'provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    assert grouping.group_subtitles([row],provider_snapshot=owner.provider_snapshot).validated
    assert len(calls) == 1


def test_unknown_confidence_and_nonentity_disagreement_do_not_create_web_scope(context):
    row = cue(1,'这里我们正在等待');row.confidence = None;row.firered_text = '这里我们准备等待'
    assert domain_terms.collect_global_term_disputes([row],[],unresolved_only=True) == []
    explicit = domain_terms.collect_global_term_disputes([row],[])
    assert explicit[0]['confidence_state'] == 'unknown' and not explicit[0]['low_confidence']


def test_disabled_optional_search_does_not_resolve_provider(context, monkeypatch):
    _, owner, _ = context;owner.enable_term_search = False
    monkeypatch.setattr(domain_terms,'task_provider_snapshot',lambda *a:pytest.fail('disabled optional search'),raising=False)
    rows = [cue(1,'只读结果')]
    assert domain_terms.run_optional_term_verification(rows,'测试') is rows
    assert owner.terminology_status['status'] == 'disabled'


def test_optional_preparation_consumes_the_same_task_deadline(context, monkeypatch):
    _, owner, _ = context;owner.enable_term_search = True
    monkeypatch.setattr(domain_terms, 'load_glossary', lambda:(time.sleep(.025) or []))
    monkeypatch.setattr(domain_terms, 'load_content_context', lambda *a:'fixture')
    monkeypatch.setattr(domain_terms, 'load_verified_game_terms', lambda:[])
    monkeypatch.setattr(domain_terms, 'collect_stable_moss_term_candidates', lambda *a:[])
    seen = []
    def discover(*args, **kwargs):
        seen.append(kwargs['_retry_budget'].remaining_seconds())
        return domain_terms.TermVerificationResult()
    monkeypatch.setattr(domain_terms, 'discover_global_domain_term_mappings', discover)
    domain_terms.run_optional_term_verification([cue(1, '原文')], 'fixture')
    assert len(seen) == 1 and seen[0] <= domain_terms.OPTIONAL_TERM_SEARCH_SECONDS-.02


def test_total_timeout_never_renews_another_complete_budget(context, monkeypatch):
    _, owner, _ = context
    calls = []
    monkeypatch.setattr(domain_terms,'term_search_capability',lambda *a:dict(available=True,status='ready'))
    def complete(messages, **kwargs):
        calls.append(kwargs['_timeout_policy'])
        raise AIProviderError('partial response has no valid terminal',category='total_timeout')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**k:SimpleNamespace(complete=complete))
    result = domain_terms.discover_global_domain_term_mappings([cue(1,'待核验实体')],'测试',[],[],[],persist=False)
    assert len(calls) == 1 and calls[0].total <= 42
    assert not result.checked_ids and result.failures == {1:'total_timeout'}
    assert owner.terminology_status['retryable'] and owner.terminology_status['unverified_count'] == 1


def test_retry_child_policies_keep_one_absolute_deadline():
    now = [100.]
    budget = RetryBudget(1,total_seconds=45,cleanup_reserve_seconds=3,clock=lambda:now[0])
    policy = SimpleNamespace(connect=10,read_idle=120,total=120,queue=120)
    first=budget.request_policy(policy);now[0]+=30;second=budget.request_policy(policy)
    assert first.deadline_monotonic == second.deadline_monotonic == 142
    assert first.cleanup_deadline_monotonic == second.cleanup_deadline_monotonic == 145
    assert first.total == 42 and second.total == 12
    now[0]+=12
    with pytest.raises(AIProviderError):budget.request_policy(policy)


def test_uninterruptible_source_probe_cannot_hold_frontend_past_budget(monkeypatch):
    monkeypatch.setattr(domain_terms,'_public_https_url',lambda url:(time.sleep(.2) or False))
    budget=RetryBudget(0,total_seconds=.05)
    start=time.monotonic()
    with pytest.raises(AIProviderError) as error:
        domain_terms.verify_term_source_urls('规范词',['https://example.org'],SimpleNamespace(),budget=budget)
    assert time.monotonic()-start < .15 and error.value.category == 'total_timeout'
    assert error.value.cleanup_pending


def test_source_probe_completed_after_deadline_cannot_publish_success(monkeypatch):
    monkeypatch.setattr(domain_terms, '_public_https_url', lambda url:(time.sleep(.025) or False))
    budget = RetryBudget(0, total_seconds=.01)
    with pytest.raises(AIProviderError) as error:
        domain_terms.verify_term_source_urls('规范词', ['https://example.org'], SimpleNamespace(), budget=budget)
    assert error.value.category == 'total_timeout'


def test_mixed_short_turn_refiners_cannot_merge_dangling_speaker_handoff(context, monkeypatch):
    _, owner, _ = context
    rows = [cue(1, '我这一次要准备使用这一个', 'S01'), cue(2, '好', 'S02'),
            cue(3, '非常特殊的技能来完成这次操作', 'S01')]
    def complete(messages, **kwargs):
        body = json.loads(messages[-1]['content'])
        return json.dumps({'boundaries':[body['total_length']]})
    monkeypatch.setattr(grouping, 'provider_for_stage', lambda *a, **k:SimpleNamespace(complete=complete))
    result = grouping.group_subtitles(rows, provider_snapshot=owner.provider_snapshot)
    assert result.validated
    assert [item.text for item in result if item.speaker == 'S02'] == ['好']
    assert ''.join(item.text for item in result if item.speaker == 'S01') == rows[0].text + rows[2].text


def test_optional_absolute_budget_includes_provider_queue_and_cleanup(context):
    import threading
    from twobyteasr.providers.provider_service import ProviderService
    from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
    _, owner, _ = context
    service = ProviderService(workers=1)
    entered = threading.Event()
    def sender(*args, **kwargs):
        entered.set(); time.sleep(.09); return '{}'
    client = service.client_for_stage(owner.provider_snapshot.execution_settings(), 'group', sender=sender)
    first = client.submit([], timeout=.5, _timeout_policy=TimeoutPolicy(.1, .5, .5, 1), request_diagnostics={})
    assert entered.wait(1)
    budget = RetryBudget(0, total_seconds=.05, cleanup_reserve_seconds=.01)
    diagnostics = {}; started = time.monotonic()
    with pytest.raises(AIProviderError) as error:
        client.complete([], timeout=.05, _timeout_policy=budget.request_policy(TimeoutPolicy()),
                        request_diagnostics=diagnostics)
    assert error.value.category == 'queue_timeout' and time.monotonic()-started < .085
    assert diagnostics['cleanup_pending']
    assert first.result(1) == '{}' and service.wait_for_idle(1)


def test_expired_cleanup_does_not_start_another_taskkill_or_wait(monkeypatch):
    import subprocess
    from twobyteasr.system import processes
    waits = []
    class OwnedProcess:
        pid = 123456
        def poll(self):return None
        def kill(self):pass
        def wait(self, timeout):
            waits.append(timeout)
            raise subprocess.TimeoutExpired('owned fixture', timeout)
    monkeypatch.setattr(processes.subprocess, 'run', lambda *a, **k:pytest.fail('cleanup budget already exhausted'))
    assert processes.stop_process_tree(OwnedProcess(), deadline_monotonic=time.monotonic()-1) is False
    assert waits == [0., 0.]


def test_optional_cli_search_requires_actual_terminal_receipt(monkeypatch):
    from twobyteasr.providers.ai_providers import GrokCLIProvider
    provider = GrokCLIProvider(executable='fixture.exe', model='fixture')
    monkeypatch.setattr(provider, '_record_installed_version', lambda *a:None)
    seen = []
    def stream(command, **kwargs):
        seen.append(kwargs['require_terminal_result'])
        raise AIProviderError('partial assistant body without request result', category='provider_protocol_error')
    monkeypatch.setattr(provider, '_run_cli_stream', stream)
    with pytest.raises(AIProviderError) as error:
        provider.complete([{'role':'user','content':'核验待确认专名'}], enable_search=True,
            operation_kind='domain_terms', timeout=.2)
    assert seen == [True] and error.value.category == 'provider_protocol_error'


def test_broker_completion_cannot_erase_adapter_pending_cleanup(monkeypatch):
    import threading
    from twobyteasr.providers.provider_service import AIClient, ProviderRequestHandle
    client = object.__new__(AIClient)
    handle = ProviderRequestHandle('owned-fixture', 'fixture', time.monotonic()-.01)
    handle.timeout_category = 'total_timeout'
    diagnostics = {'cleanup_pending':True}
    def submit(*args, **kwargs):
        threading.Timer(.03, handle._event.set).start()
        return handle
    monkeypatch.setattr(client, 'submit', submit)
    policy = SimpleNamespace(queue=.1, total=.1, cleanup_deadline_monotonic=time.monotonic()+.1)
    with pytest.raises(AIProviderError) as error:
        client.complete([], _timeout_policy=policy, request_diagnostics=diagnostics)
    assert error.value.category == 'total_timeout'
    assert diagnostics['cleanup_pending'] and not diagnostics['cleanup_complete']
