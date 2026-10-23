"""Optional search cannot change successful text/ASR artifacts or invent coverage."""
import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_stage9_cache_and_budget import context
from tests.test_terminology_polish_budget import cue
from tests.test_terminology_resolution import facade, confirmed
from twobyteasr.recognition import cache as cache_module
from twobyteasr.glossary import domain_terms
from twobyteasr.subtitle_rules import polishing
from twobyteasr.glossary.terminology import apply_to_segments, snapshot_glossaries
from twobyteasr.recognition.service import RunOptions


def search_provider(context, monkeypatch, responder):
    _, owner, _ = context
    owner.provider_snapshot = replace(owner.provider_snapshot, kind='cli', transport='grok_cli', provider='grok_oauth')
    calls = []
    def complete(messages, **kwargs):
        ids = [row['id'] for row in json.loads(messages[1]['content'])['asr_disputes']]
        calls.append(ids)
        response, evidence = responder(ids)
        if evidence:
            kwargs['request_diagnostics']['search_evidence'] = [
                {'tool': 'web_search', 'tool_use_id': 'test-receipt', 'urls': ['https://example.org/term']}]
        return json.dumps(response)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    monkeypatch.setattr(domain_terms, 'persist_learned_mappings', lambda *a: pytest.fail('empty evidence must not alter a glossary'))
    return owner, calls


def test_unsupported_search_is_one_capability_fact_with_complete_unexecuted_scope(context, monkeypatch):
    _, owner, cache = context
    owner.enable_domain_terms = True
    events = []
    monkeypatch.setattr(domain_terms, 'record_run_event', lambda event, **kw: events.append((event, kw)))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: pytest.fail('unavailable search must not construct an executor'))
    rows = [cue(i, '未核验术语') for i in range(1, 32)]
    result = domain_terms.discover_global_domain_term_mappings(rows, '测试', [], [], [], cache_context=cache)
    assert result.status == 'unsupported' and not result.failures and not result.checked_ids
    summary = owner.terminology_status
    assert summary['unverified_count'] == 31 and summary['unverified_ids'] == list(range(1, 32))
    assert summary['failure_categories'] == {} and not summary['retryable']
    assert summary['local_glossary_available'] and not summary['evidence_verified']
    assert [event for event, _ in events] == ['domain_term_verification_summary', 'domain_term_search_skipped']
    assert not (Path(cache['cache_dir']) / 'term_verification').exists()


def test_search_with_proofreading_off_is_skipped_not_a_failed_task(context, monkeypatch):
    # 2026-10-22 user report: 联网补充核验 on, 文字校对 off -> the task failed
    # after the whole ASR run with "Text AI stage is disabled for this task: polish".
    _, owner, cache = context
    owner.provider_snapshot = None
    owner.provider_snapshots = {}
    owner.asr_settings_snapshot = {'models': {'polish_provider': 'disabled', 'group_provider': 'disabled'},
        'switches': {'enable_ai_polish': False, 'use_ai_grouping': False, 'unified_glm_processing': True}}
    owner.enable_term_search = True
    events = []
    monkeypatch.setattr(domain_terms, 'record_run_event', lambda event, **kw: events.append((event, kw)))
    monkeypatch.setattr(domain_terms, 'load_glossary', lambda: [])
    monkeypatch.setattr(domain_terms, 'load_verified_game_terms', lambda: [])
    monkeypatch.setattr(domain_terms, 'load_content_context', lambda *a: '')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: pytest.fail('no provider without proofreading'))
    rows = [cue(1, '候选术语'), cue(2, '候选术语也在')]
    assert [row.text for row in domain_terms.run_optional_term_verification(rows, '素材', cache)] == ['候选术语', '候选术语也在']
    summary = owner.terminology_status
    assert summary['status'] == 'not_configured' and summary['unverified_ids'] == [1, 2]
    assert '文字校对未开启' in summary['reason'] and not summary['retryable']
    assert [event for event, _ in events] == ['domain_term_verification_summary', 'domain_term_search_skipped']
    assert domain_terms.term_search_capability()['status'] == 'not_configured'


def test_confirmed_local_glossary_works_with_optional_search_disabled(context, monkeypatch):
    core, owner, cache = context
    frozen = snapshot_glossaries(facade([confirmed('Borlin', 'BerLIN')]), ['valorant-id'])
    owner.glossary_snapshot = frozen
    owner.enable_domain_terms = True
    rows = [cue(1, 'Borlin也没有接住')]
    monkeypatch.setattr(domain_terms, 'term_search_capability', lambda *a: pytest.fail('disabled search must not resolve a provider'))
    assert apply_to_segments(rows, frozen)[0].text == 'BerLIN也没有接住'
    assert domain_terms.run_optional_term_verification(rows, '测试', cache)[0].text == 'BerLIN也没有接住'
    assert owner.terminology_status['status'] == 'disabled'
    assert not owner.terminology_status['requested']
    options = RunOptions(enable_domain_terms=True, enabled_glossary_ids=('valorant-id',),
        glossary_snapshot_json=json.dumps(frozen.to_dict()))
    independent = options.create_runtime_context(core)
    assert independent.enable_domain_terms and not independent.enable_term_search


def test_successful_text_cache_is_kept_despite_nested_search_failure(context):
    _, owner, cache = context
    owner.terminology_status = {'status': 'failed', 'failure_categories': {'unsupported_search': 31}}
    owner.polishing_summary = {'success_cues': 31, 'fallback_cues': 0, 'terminology': owner.terminology_status}
    calls = []
    def run():
        calls.append(1)
        return {'usable': '文字完成'}
    assert cache_module.run_cached_stage('polished', cache, run) == {'usable': '文字完成'}
    payload = json.loads((Path(cache['cache_dir']) / 'polished.json').read_text(encoding='utf-8'))
    assert 'terminology_status' not in payload and 'terminology' not in payload['polishing_summary']
    owner.enable_term_search = True
    assert cache_module.run_cached_stage('polished', cache, run) == {'usable': '文字完成'}
    assert calls == [1] and owner.polishing_summary['cached']


def test_optional_search_choice_does_not_invalidate_asr_or_text_identity(context):
    _, owner, _ = context
    initial = {stage: cache_module.cache_stage_signature(stage) for stage in ('polished', 'firered_primary')}
    owner.enable_term_search = True
    owner.terminology_status = {'status': 'failed', 'reason': 'timeout'}
    assert initial == {stage: cache_module.cache_stage_signature(stage) for stage in initial}


def test_no_search_receipt_never_writes_verified_cache(context, monkeypatch):
    owner, calls = search_provider(context, monkeypatch, lambda ids: ({'checked_ids': ids, 'unchecked_ids': [], 'mappings': []}, False))
    _, _, cache = context
    result = domain_terms.discover_global_domain_term_mappings([cue(1, '候选术语')], '测试', [], [], [], cache_context=cache)
    assert result.status == 'failed' and len(calls) == 1 and not result.checked_ids
    assert owner.terminology_status['failure_categories'] == {'search_evidence_missing': 1}
    assert owner.terminology_status['retryable'] and not owner.terminology_status['evidence_verified']
    assert not (Path(cache['cache_dir']) / 'term_verification').exists()


def test_partial_search_cache_retries_only_outstanding_record(context, monkeypatch):
    first = True
    def responder(ids):
        nonlocal first
        checked = [1] if first else ids
        first = False
        return {'checked_ids': checked, 'unchecked_ids': sorted(set(ids) - set(checked)), 'mappings': []}, True
    owner, calls = search_provider(context, monkeypatch, responder)
    _, _, cache = context
    rows = [cue(1, '候选甲'), cue(2, '候选乙')]
    def run():
        return domain_terms.discover_global_domain_term_mappings(rows, '测试', [], [], [], cache_context=cache)
    partial = run()
    assert partial.status == 'partial' and owner.terminology_status['unverified_ids'] == [2]
    complete = run()
    assert complete.status == 'success' and complete.checked_ids == {1, 2}
    assert calls == [[1, 2], [2]]
    assert run().checked_ids == {1, 2} and calls == [[1, 2], [2]]
    assert owner.terminology_status['evidence_verified'] and owner.terminology_status['cached']


def test_explicit_search_retry_uses_only_previous_failed_scope_without_asr_text_or_saving(context, monkeypatch):
    owner, calls = search_provider(context, monkeypatch, lambda ids: ({'checked_ids': ids, 'unchecked_ids': [], 'mappings': []}, True))
    _, _, cache = context
    monkeypatch.setattr(domain_terms, 'load_glossary', lambda: [])
    monkeypatch.setattr(domain_terms, 'load_verified_game_terms', lambda: [])
    monkeypatch.setattr(domain_terms, 'load_content_context', lambda *a: '测试')
    monkeypatch.setattr(domain_terms, 'collect_stable_moss_term_candidates', lambda *a: [])
    monkeypatch.setattr(polishing, 'polish_subtitles', lambda *a: pytest.fail('search retry must not polish'))
    rows = [cue(1, '已核验'), cue(2, '失败术语'), cue(3, '已核验')]
    original = copy.deepcopy(rows)
    result = domain_terms.retry_pending_term_verification(rows, '素材',
        {'verified_ids': [1, 3], 'unverified_ids': [2]}, cache)
    assert result.checked_ids == {2} and calls == [[2]]
    assert [(r.segment_id, r.text) for r in rows] == [(r.segment_id, r.text) for r in original]


def test_real_text_fallback_is_not_stored_even_without_review_marker(context):
    _, owner, cache = context
    owner.polishing_summary = {'success_cues': 0, 'fallback_cues': 1}
    cache_module.run_cached_stage('polished', cache, lambda: {'usable': '原文'})
    assert not (Path(cache['cache_dir']) / 'polished.json').exists()
    value = polishing.PolishBatchResult({1: '原文'}, succeeded=set(), failures={1: 'total_timeout'})
    for _ in range(2):
        cache_module.run_cached_api_batch('polished', cache, {'original': '原文'}, lambda: value)
    assert not list((Path(cache['cache_dir']) / 'api_batches' / 'polished').glob('*.json'))


def test_structured_output_or_advertised_capability_is_not_a_search_executor(context):
    _, owner, _ = context
    snapshot = replace(owner.provider_snapshot, capabilities=('text', 'structured_output', 'web_search'))
    assert domain_terms.term_search_capability(snapshot)['status'] == 'unsupported'
    snapshot = replace(snapshot, kind='cli', transport='codex_cli')
    assert domain_terms.term_search_capability(snapshot)['status'] == 'unsupported'


def test_supported_http_search_without_credentials_is_not_configured(context):
    _, owner, _ = context
    endpoint = owner.provider_snapshot.endpoint()
    endpoint.update(provider='bailian', api_key='')
    snapshot = replace(owner.provider_snapshot, provider='bailian', _endpoint=tuple(endpoint.items()))
    result = domain_terms.term_search_capability(snapshot)
    assert result['status'] == 'not_configured' and not result['available']


def test_cancelled_search_never_writes_late_success(context, monkeypatch):
    from twobyteasr.recognition.service import CancellationToken, CancelledError
    _, owner, cache = context
    owner.cancellation_token = CancellationToken()
    def responder(ids):
        owner.cancellation_token.cancel()
        return {'checked_ids': ids, 'unchecked_ids': [], 'mappings': []}, True
    search_provider(context, monkeypatch, responder)
    with pytest.raises(CancelledError):
        domain_terms.discover_global_domain_term_mappings([cue(1, '取消术语')], '测试', [], [], [], cache_context=cache)
    assert not (Path(cache['cache_dir']) / 'term_verification').exists()


def test_legacy_polish_cache_cannot_restore_a_search_success_claim(context):
    _, owner, cache = context
    cache_module.run_cached_stage('polished', cache, lambda: {'text': '完成'})
    path = Path(cache['cache_dir']) / 'polished.json'
    payload = json.loads(path.read_text(encoding='utf-8'))
    payload.update(terminology_status={'status': 'success', 'verified_count': 99},
        polishing_summary={'success_cues': 1, 'fallback_cues': 0, 'terminology': {'status': 'success'}})
    path.write_text(json.dumps(payload), encoding='utf-8')
    owner.terminology_status.clear()
    assert cache_module.run_cached_stage('polished', cache, lambda: pytest.fail('expected old text-cache hit')) == {'text': '完成'}
    assert owner.terminology_status == {} and 'terminology' not in owner.polishing_summary


def test_failed_text_retry_has_no_queue_or_local_asr_callback_and_preserves_successes(context, monkeypatch):
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition import service
    _, owner, cache = context
    owner.glossary_snapshot = snapshot_glossaries(facade([]), [])
    monkeypatch.setattr(service, 'run_media_queue', lambda *a, **k: pytest.fail('retry started the recognition queue'))
    monkeypatch.setattr(pipeline, 'process_media', lambda *a, **k: pytest.fail('retry restarted the ASR pipeline'))
    monkeypatch.setattr(pipeline, 'transcribe_moss_global', lambda *a, **k: pytest.fail('retry called local MOSS'))
    monkeypatch.setattr(pipeline, 'precompute_moss_batch_cache', lambda *a, **k: pytest.fail('retry called local precompute'))
    monkeypatch.setattr(domain_terms, 'discover_global_domain_term_mappings', lambda *a, **k: pytest.fail('retry started optional search'))
    calls = []
    def complete(messages, **kwargs):
        body = json.loads(messages[1]['content'])
        ids = [row['id'] for row in body['cues']]
        calls.append(ids)
        assert ids == [2]
        assert '已成功甲' in body['context_before'] and '已成功乙' in body['context_after']
        return json.dumps({'checked_ids': ids, 'cues': []})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    rows = [cue(1, '已成功甲'), cue(2, '待重试原文'), cue(3, '已成功乙')]
    original = copy.deepcopy(rows)
    summary = {'success_cues': 2, 'success_ids': [1, 3], 'fallback_cues': 1, 'fallback_ids': [2]}
    result = polishing.retry_failed_polish(rows, '测试素材', summary, cache)
    assert result.succeeded == {2} and not result.failures and calls == [[2]]
    assert polishing.retry_failed_polish(rows, '测试素材', summary, cache).succeeded == {2}
    assert calls == [[2]]
    assert [(r.segment_id, r.text, r.speaker, r.start, r.end) for r in rows] == [
        (r.segment_id, r.text, r.speaker, r.start, r.end) for r in original]


def test_legacy_text_failure_without_proven_scope_does_not_request_all_records(context, monkeypatch):
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: pytest.fail('unknown failures must not request all'))
    with pytest.raises(ValueError, match='失败处理记录范围'):
        polishing.retry_failed_polish([cue(1, '未证实失败')], '测试', {'fallback_cues': 1})
    assert polishing.retry_failed_polish([cue(1, '已完成')], '测试', {'fallback_cues': 0}) == {}


def test_completed_search_step_without_results_is_insufficient_evidence(context, monkeypatch):
    _, owner, cache = context
    owner.provider_snapshot = replace(owner.provider_snapshot, kind='cli', transport='antigravity_cli')
    calls = []
    def complete(messages, **kwargs):
        calls.append(1)
        kwargs['request_diagnostics']['search_evidence'] = [{'tool': 'search_web', 'step_index': 0, 'urls': []}]
        return json.dumps({'checked_ids': [1], 'unchecked_ids': [], 'mappings': []})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    result = domain_terms.discover_global_domain_term_mappings([cue(1, '候选')], '测试', [], [], [], cache_context=cache)
    assert not result.checked_ids and result.status == 'failed' and calls == [1]
    assert owner.terminology_status['failure_categories'] == {'insufficient_evidence': 1}
    assert not (Path(cache['cache_dir']) / 'term_verification').exists()
