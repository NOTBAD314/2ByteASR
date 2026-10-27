"""2026-10-10 job 0852f218: all 7 polish batches ended as total_timeout.

The one 120 s request window was shared by the whole task and was spent on
local request building (one full rebuild per cue) before most batches could
send anything. These tests pin the three causes and the audit-log gaps.
"""
import json
import random
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade before polishing
from tests.test_stage9_cache_and_budget import context
from twobyteasr.providers import llm_adapter
from twobyteasr.subtitle_rules import polishing
from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.providers.provider_input_budget import InputBudgetError, pack_items, prepare_input


def ascii_messages(sizes):
    return [{'role': 'user', 'content': 'x' * sum(sizes)}]


def item_by_item_greedy(items, build_messages, *, operation, max_tokens):
    """The packing rule used before 2026-10-10, kept as the reference result."""
    batches, rejected, current = [], [], []
    for item in items:
        trial = [*current, item]
        try:
            prepare_input(build_messages(trial), max_tokens=max_tokens, operation=operation)
        except InputBudgetError:
            if current:
                batches.append(current)
                current = []
            try:
                prepare_input(build_messages([item]), max_tokens=max_tokens, operation=operation)
            except InputBudgetError as exc:
                rejected.append((item, exc.report))
            else:
                current = [item]
        else:
            current = trial
    if current:
        batches.append(current)
    return batches, rejected


def test_fitting_batch_is_built_once_instead_of_once_per_item():
    calls = []
    def build(chunk):
        calls.append(len(chunk))
        return ascii_messages(chunk)
    items = [500] * 33
    batches, rejected = pack_items(items, build, operation='polish', max_tokens=4096)
    assert batches == [items] and not rejected
    assert calls == [33]


def pack_both(items):
    """Return (new result, old result, new built items, old built items)."""
    new_work, old_work = [], []
    def counted(log):
        return lambda chunk: (log.append(len(chunk)), ascii_messages(chunk))[1]
    new = pack_items(items, counted(new_work), operation='polish', max_tokens=4096)
    old = item_by_item_greedy(items, counted(old_work), operation='polish', max_tokens=4096)
    return new, old, sum(new_work), sum(old_work)


def test_searched_packing_matches_the_previous_greedy_result():
    rng = random.Random(20261010)
    for _ in range(80):
        # 'polish' allows about 60 KB of ASCII; some singletons exceed it.
        items = [rng.choice((rng.randint(200, 3000), rng.randint(3000, 30000), 70000))
                 for _ in range(rng.randint(1, 64))]
        new, old, _, _ = pack_both(items)
        assert new[0] == old[0]
        assert [item for item, _ in new[1]] == [item for item, _ in old[1]]


def test_slightly_oversized_batch_is_split_without_quadratic_rebuilding():
    # 64 cues where about 40 fit: the old loop rebuilt every prefix.
    new, old, new_work, old_work = pack_both([1500] * 64)
    assert new[0] == old[0] and [len(x) for x in new[0]] == [39, 25]
    assert new_work * 3 < old_work
    # One oversized cue among normal ones is rejected alone, neighbours kept.
    new, old, new_work, old_work = pack_both([800] * 32 + [70000] + [800] * 31)
    assert new == old or (new[0] == old[0] and len(new[1]) == len(old[1]) == 1)
    assert [len(x) for x in new[0]] == [32, 31] and new_work * 2 < old_work


def cue(i, text):
    return SpeechSegment(segment_id=i, start=i*100., end=i*100.+2, text=text, confidence=.85,
        words=[], speaker='S01', moss_text=text, firered_text=text, qwen_asr_text=text)


def checked(messages, **kwargs):
    ids = [row['id'] for row in json.loads(messages[1]['content'])['cues']]
    return json.dumps({'checked_ids': ids, 'cues': []})


def counted_retrieval(monkeypatch):
    import twobyteasr.glossary.terminology_retrieval as retrieval
    original = retrieval.retrieve_candidates
    builds = []
    def counted(term_snapshot, segments, *args, **kwargs):
        builds.append([segment.text for segment in segments])
        return original(term_snapshot, segments, *args, **kwargs)
    monkeypatch.setattr(retrieval, 'retrieve_candidates', counted)
    return builds


def test_one_batch_request_is_built_once_not_once_per_cue(context, monkeypatch):
    builds = counted_retrieval(monkeypatch)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(complete=checked))
    rows = [SpeechSegment(i, i*2., i*2.+1, f'第{i}句普通解说', .85, [], speaker='S01')
            for i in range(1, 34)]
    result = polishing.call_correction_api(rows, [], '', '', '夹具', '', [], [], [],
                                           batch_index=1, batch_total=1)
    assert result.succeeded == {row.segment_id for row in rows}
    # The budget check and the request share one build (was 33 + 1, then 2).
    assert [len(texts) for texts in builds] == [33]


def test_prepared_request_is_reused_and_rebuilt_when_a_cue_changes(context, monkeypatch):
    builds = counted_retrieval(monkeypatch)
    sent = []
    def complete(messages, **kwargs):
        sent.append(json.loads(messages[1]['content'])['cues'][0]['primary_text'])
        return checked(messages)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(complete=complete))
    rows = [SpeechSegment(1, 0., 1., '原来的文字', .85, [], speaker='S01')]
    polishing.prepare_correction_request(rows, [], '', '', '夹具', '', [], [], [])
    polishing.call_correction_api(rows, [], '', '', '夹具', '', [], [], [])
    assert len(builds) == 1 and sent == ['原来的文字']
    rows[0].text = '改过的文字'
    polishing.call_correction_api(rows, [], '', '', '夹具', '', [], [], [])
    assert len(builds) == 2 and sent[-1] == '改过的文字'


def test_studio_review_prepares_the_next_batch_while_one_is_answered(context, monkeypatch):
    """Each batch's request is ready when the previous answer arrives."""
    import threading as _threading
    from twobyteasr.glossary import studio_glossary_service as service
    builds = counted_retrieval(monkeypatch)
    order = []
    real_prepare = polishing.prepare_correction_request
    def prepare(batch, *args, **kwargs):
        order.append(('prepare', batch[0].segment_id, _threading.current_thread().name.startswith('glossary-review')))
        return real_prepare(batch, *args, **kwargs)
    real_call = polishing.call_correction_api
    def call(batch, *args, **kwargs):
        if kwargs.get('_messages_only'):  # the preparation itself
            return real_call(batch, *args, **kwargs)
        order.append(('send', batch[0].segment_id))
        time.sleep(.3)  # the provider answering
        return polishing.PolishBatchResult({row.segment_id: row.text for row in batch})
    monkeypatch.setattr(polishing, 'prepare_correction_request', prepare)
    monkeypatch.setattr(polishing, 'call_correction_api', call)
    monkeypatch.setattr(polishing, 'correction_batches', lambda rows: [[row] for row in rows])
    import twobyteasr.providers.asr_provider_snapshot as snapshots
    monkeypatch.setattr(snapshots, 'resolve_provider_snapshot', lambda *a, **k: context[1].provider_snapshot)
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    from twobyteasr.glossary.terminology import GlossarySnapshot
    project = SubtitleProject(media=StudioMedia(path='', duration_ms=9000),
        cues=[StudioCue(f'c{i}', i*2000, i*2000+1500, f'第{i}句') for i in range(1, 4)])
    service.preview_glossary_correction(project, ['c1', 'c2', 'c3'], GlossarySnapshot(), {})
    sends = [entry for entry in order if entry[0] == 'send']
    assert [entry[1] for entry in sends] == [1, 2, 3]
    # Batch 1 is prepared in front; batches 2 and 3 on the background thread,
    # each submitted before the previous batch was sent.
    assert order[:3] == [('prepare', 1, False), ('prepare', 2, True), ('send', 1)] or \
        order[:3] == [('prepare', 1, False), ('send', 1), ('prepare', 2, True)]
    assert ('prepare', 3, True) in order and order.index(('prepare', 3, True)) < order.index(('send', 3))


def test_event_redaction_resolves_secrets_once_per_event(context, monkeypatch):
    from twobyteasr.recognition import cache
    calls = []
    def secrets():
        calls.append(1)
        return ('sk-live-secret-123',)
    monkeypatch.setattr(cache, '_runtime_secret_values', secrets)
    payload = {'rows': [{'text': f'第{i}行 sk-live-secret-123'} for i in range(200)], 'note': 'plain'}
    cache.record_run_event('redaction_probe', **payload)
    assert len(calls) == 1
    _, owner, _ = context
    row = [json.loads(line) for line in open(owner.event_log_path, encoding='utf-8')][-1]
    assert row['event'] == 'redaction_probe' and 'sk-live-secret-123' not in json.dumps(row, ensure_ascii=False)
    assert row['rows'][0]['text'] == '第0行 <redacted>'
    assert cache.redact_runtime_secrets('x sk-live-secret-123') == 'x <redacted>'


def test_glossary_snapshot_digest_is_computed_once(monkeypatch):
    from twobyteasr.glossary import terminology
    from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry
    snapshot = GlossarySnapshot((GlossaryLibrary('lib', '词库', 'r1', (TermEntry('骨龙'),)),))
    calls = []
    original = terminology._digest
    monkeypatch.setattr(terminology, '_digest', lambda value: (calls.append(1), original(value))[1])
    first, second = snapshot.digest, snapshot.digest
    assert first == second and len(calls) == 1
    assert GlossarySnapshot.from_dict(snapshot.to_dict()).digest == first


@pytest.mark.parametrize('batches,workers,rounds', [(7, 2, 4), (7, 4, 2), (8, 1, 8), (1, 2, 1), (0, 1, 1)])
def test_task_deadline_has_one_request_window_per_scheduling_round(batches, workers, rounds):
    budget = polishing.correction_task_budget(TimeoutPolicy(total=120.), batches, workers)
    assert budget.remaining_seconds() == pytest.approx(120. * rounds, abs=1.)
    assert budget.remaining == polishing.API_RETRIES - 1


def test_later_parallel_batches_still_get_sent_within_the_task_deadline(context, monkeypatch):
    """Seven batches, two provider slots, each answer 0.3 s, request window 0.58 s.

    With one request window for the whole task even two rounds (0.6 s) cannot
    finish; later batches were refused without sending
    ("共享总时限已用完；没有发送新请求"). Four rounds now get 4 x 0.58 s.
    """
    _, owner, _ = context
    window = .58
    monkeypatch.setattr('twobyteasr.providers.asr_provider_snapshot.task_provider_snapshot',
        lambda *_: replace(owner.provider_snapshot,
                           timeout_policy=TimeoutPolicy(connect=window, read_idle=window, total=window, queue=window)))
    # Warm one-time tokenizer loading so the margin measures scheduling only.
    polishing.call_correction_api([cue(99, '预热')], [], '', '', '夹具', '', [], [], [], _messages_only=True)
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE, 'scheduling_capacity',
                        lambda: {'effective_workers': 2, 'source': 'fixture'})
    monkeypatch.setattr(polishing, 'PARALLEL_CLOUD_BATCHES', True)
    monkeypatch.setattr(polishing, 'CLOUD_BATCH_WORKERS', 4)
    lock, active, peak, sent = threading.Lock(), [0], [0], []
    def complete(messages, **kwargs):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            time.sleep(.3)
            sent.append(kwargs['_timeout_policy'].deadline_monotonic)
            return checked(messages)
        finally:
            with lock:
                active[0] -= 1
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(complete=complete))
    rows = [cue(i, f'第{i}段普通解说') for i in range(1, 8)]
    assert len(polishing.correction_batches(rows)) == 7
    polishing.polish_subtitles(rows, '并行共享时限回归')
    summary = owner.polishing_summary
    assert summary['success_batches'] == 7 and summary['fallback_batches'] == 0
    assert not summary['failure_categories']
    assert len(sent) == 7 and len(set(sent)) == 1  # one absolute deadline, never reset
    assert peak[0] <= 2
    events = [json.loads(line) for line in open(owner.event_log_path, encoding='utf-8')]
    plan = next(row for row in events if row['event'] == 'cloud_batches_parallel')
    assert plan['workers'] == 2 and plan['configured_workers'] == 4
    assert plan['task_budget_seconds'] == pytest.approx(4 * window, abs=.2)


def test_expired_task_marks_request_as_not_handed_to_provider(context, monkeypatch):
    from twobyteasr.providers.provider_input_budget import RetryBudget
    _, owner, _ = context
    monkeypatch.setattr('twobyteasr.providers.asr_provider_snapshot.task_provider_snapshot',
                        lambda *_: owner.provider_snapshot)
    calls = []
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
        lambda *a, **k: SimpleNamespace(complete=lambda *x, **y: calls.append(1)))
    budget = RetryBudget(1, total_seconds=0, cleanup_reserve_seconds=0)
    # Expired before the call: refused before any request is built.
    polishing.call_correction_api([cue(1, '原文')], [], '', '', '夹具', '', [], [], [],
                                  _retry_budget=budget)
    clock = [100.]
    later = RetryBudget(1, total_seconds=1, clock=lambda: clock[0])
    import twobyteasr.glossary.terminology_retrieval as retrieval
    original = retrieval.retrieve_candidates
    def slow_local_preparation(*args, **kwargs):
        clock[0] += 5  # the deadline passes while the request is being built
        return original(*args, **kwargs)
    monkeypatch.setattr(retrieval, 'retrieve_candidates', slow_local_preparation)
    result = polishing.call_correction_api([cue(2, '原文二')], [], '', '', '夹具', '', [], [], [],
                                           _retry_budget=later)
    assert not calls and result.failures == {2: 'total_timeout'}
    events = [json.loads(line) for line in open(owner.event_log_path, encoding='utf-8')]
    request = [row for row in events if row['event'] == 'asr_provider_request']
    assert [row['handed_to_provider'] for row in request] == [False]


def null_candidate_answer(messages, start=0):
    ids = [row['id'] for row in json.loads(messages[1]['content'])['cues']]
    return {'checked_ids': ids, 'cues': [{'id': ids[0], 'edits': [
        {'from': '上风', 'to': '上分', 'start': start, 'end': 2, 'type': 'asr_correction',
         'candidate_id': None, 'basis': None, 'evidence': None}]}], 'suspect_results': []}


@pytest.mark.parametrize('path', ['structured_complete', 'complete'])
def test_null_for_an_optional_candidate_id_does_not_discard_the_batch(context, monkeypatch, path):
    """Live run 2026-10-10 14:02: 3 of 7 DeepSeek answers had candidate_id null."""
    from twobyteasr.providers.provider_input_budget import RetryBudget
    if path == 'structured_complete':
        provider = SimpleNamespace(structured_complete=lambda messages, schema, **k: null_candidate_answer(messages))
    else:
        provider = SimpleNamespace(complete=lambda messages, **k: json.dumps(null_candidate_answer(messages)))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: provider)
    result = polishing.call_correction_api([cue(1, '上风好爽')], [], '', '', '夹具', '', [], [], [],
                                           _retry_budget=RetryBudget(0, total_seconds=30))
    assert result.succeeded == {1} and not result.failures


def test_null_position_is_still_rejected(context, monkeypatch):
    from twobyteasr.providers.provider_input_budget import RetryBudget
    provider = SimpleNamespace(structured_complete=lambda messages, schema, **k:
                               null_candidate_answer(messages, start=None))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: provider)
    result = polishing.call_correction_api([cue(1, '上风好爽')], [], '', '', '夹具', '', [], [], [],
                                           _retry_budget=RetryBudget(0, total_seconds=30))
    assert not result.succeeded and result.failures == {1: 'structured_schema_error'}
    assert polishing._without_null_optional_fields(
        {'suspect_results': [{'suspect_id': 's1', 'disposition': 'keep', 'candidate_id': None,
                              'evidence': None}]}) == {
        'suspect_results': [{'suspect_id': 's1', 'disposition': 'keep', 'evidence': None}]}


def invocation_rows(tmp_path):
    path = tmp_path / 'logs' / 'llm_invocations.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def test_stream_cut_after_http_200_is_not_audited_as_success(monkeypatch, tmp_path):
    from twobyteasr.providers import provider_stream
    monkeypatch.setattr('twobyteasr.runtime_paths.user_data_root', lambda: tmp_path)
    def deadline_after_headers(url, headers, body, timeout, diagnostics, emit, *args, **kwargs):
        diagnostics['http_status'] = 200
        emit('delta', '{"ch')
        raise provider_stream.StreamProtocolError('Provider请求达到总时限', 'provider_total_timeout')
    monkeypatch.setattr(provider_stream, 'request_chat', deadline_after_headers)
    with pytest.raises(llm_adapter.LLMRequestError):
        llm_adapter.post_chat_completion_stream([{'role': 'user', 'content': 'x'}], model='deepseek-v4-pro',
            api_key='fixture', url='https://api.deepseek.com/v1/chat/completions', max_tokens=8,
            provider='deepseek', base_url='https://api.deepseek.com/v1', stage='polished')
    monkeypatch.setattr(provider_stream, 'request_chat', lambda *a, **k: (a[4].update(http_status=200), '{}')[1])
    assert llm_adapter.post_chat_completion_stream([{'role': 'user', 'content': 'x'}], model='deepseek-v4-pro',
        api_key='fixture', url='https://api.deepseek.com/v1/chat/completions', max_tokens=8,
        provider='deepseek', base_url='https://api.deepseek.com/v1', stage='polished') == '{}'
    cut, finished = invocation_rows(tmp_path)
    assert (cut['status_code'], cut['ok'], cut['error']) == (200, False, 'provider_total_timeout')
    assert (finished['status_code'], finished['ok']) == (200, True) and 'error' not in finished


def test_bounded_http_transport_requests_are_audited(monkeypatch, tmp_path):
    from twobyteasr.providers import asr_http_transport
    monkeypatch.setattr('twobyteasr.runtime_paths.user_data_root', lambda: tmp_path)
    def answered(messages, **kwargs):
        kwargs['request_diagnostics']['http_status'] = 200
        return '{"boundaries":[3]}'
    monkeypatch.setattr(asr_http_transport, 'complete', answered)
    diagnostics = {}
    assert llm_adapter.post_chat_completion([{'role': 'user', 'content': 'x'}], model='deepseek-v4-pro',
        api_key='fixture', url='https://api.deepseek.com/v1/chat/completions', max_tokens=8,
        provider='deepseek', base_url='https://api.deepseek.com/v1', stage='grouped',
        request_diagnostics=diagnostics) == '{"boundaries":[3]}'
    def refused(messages, **kwargs):
        raise llm_adapter.LLMRequestError('HTTP Provider缺少凭据。', category='auth_config')
    monkeypatch.setattr(asr_http_transport, 'complete', refused)
    with pytest.raises(llm_adapter.LLMRequestError):
        llm_adapter.post_chat_completion([{'role': 'user', 'content': 'x'}], model='deepseek-v4-pro',
            api_key='fixture', url='https://api.deepseek.com/v1/chat/completions', max_tokens=8,
            provider='deepseek', base_url='https://api.deepseek.com/v1', stage='grouped',
            request_diagnostics={})
    answered_row, refused_row = invocation_rows(tmp_path)
    assert answered_row['stage'] == 'grouped' and answered_row['status_code'] == 200 and answered_row['ok']
    assert (refused_row['status_code'], refused_row['ok'], refused_row['error']) == (None, False, 'auth_config')
    assert diagnostics == {'http_status': 200}
