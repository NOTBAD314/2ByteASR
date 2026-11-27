"""Targeted format/truncation retries preserve the configured reasoning mode."""
import json
from types import SimpleNamespace

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade before polishing
from tests.test_stage9_cache_and_budget import context  # noqa: F401  (fixture)
from twobyteasr.providers.subtitle_request_policy import (escalated_thinking, escalation_cue_limit,
                                                          escalation_enabled, thinking_control)
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules import polishing


# --- thinking levels -----------------------------------------------------------------------------

@pytest.mark.parametrize('enabled,protocol,url,endpoint_protocol,expected', [
    (False, 'deepseek', '', '', 'high'),
    (True, 'deepseek', '', '', 'max'),
    ('high', 'deepseek', '', '', 'max'),
    ('low', 'reasoning_effort', '', '', 'high'),
    ('max', 'reasoning_effort', '', '', None),
    (False, 'auto', 'https://api.deepseek.com/v1', '', 'high'),
    (False, 'auto', 'https://dashscope.aliyuncs.com/compatible-mode/v1', '', True),
    (True, 'enable_thinking', '', '', None),
    (False, 'auto', 'https://relay.example/v1', '', None),
    (False, 'auto', 'https://api.anthropic.com', 'anthropic_messages', 'high'),
    (True, 'auto', 'https://api.anthropic.com', 'anthropic_messages', 'max'),
])
def test_one_level_up_per_protocol(enabled, protocol, url, endpoint_protocol, expected):
    assert escalated_thinking(enabled, protocol, base_url=url, endpoint_protocol=endpoint_protocol) == expected


def test_escalated_value_is_a_real_wire_parameter():
    controls, mode, _ = thinking_control('deepseek', 'https://api.deepseek.com/v1', 'max', 'deepseek')
    assert controls == {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'max'} and mode == 'max'
    assert thinking_control('x', 'https://relay.example/v1', 'high', 'auto')[0] == {}


def test_switch_defaults_on_and_limit_has_a_floor():
    assert escalation_enabled({}, 'polish') and escalation_enabled({'models': {}}, 'group')
    assert not escalation_enabled({'models': {'polish_escalate_on_failure': False}}, 'polish')
    # unified processing reads the group switch for proofreading too
    assert not escalation_enabled({'models': {'group_escalate_on_failure': False},
                                   'switches': {'unified_glm_processing': True}}, 'polish')
    assert escalation_cue_limit(4) == 10 and escalation_cue_limit(100) == 30


def test_editor_switch_is_saved_per_stage(monkeypatch):
    import copy
    from twobyteasr.app import ui
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    monkeypatch.setattr(ui, 'read_api_key', lambda provider, base_url='': ('sk-test', 'test'))
    monkeypatch.setattr(ui, 'resolve_api_key', lambda stage: ('', ''))
    deepseek = dict(service='deepseek', provider='deepseek', transport='openai_compatible', model='deepseek-chat',
                    base_url='https://api.deepseek.com/v1', protocol='auto')
    legacy = SimpleNamespace(RUNTIME_SETTINGS=copy.deepcopy(DEFAULT_SETTINGS))
    assert legacy.RUNTIME_SETTINGS['models']['polish_escalate_on_failure'] is True
    values = ui.persist_ai_configuration(legacy, dict(deepseek, escalate_on_failure=False), dict(deepseek),
                                         unified=False, share_key=False, require_ready=False, dry_run=True)
    assert values['models']['polish_escalate_on_failure'] is False
    assert values['models']['group_escalate_on_failure'] is True


def test_anthropic_named_depth_becomes_effort(monkeypatch):
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
    seen = {}
    monkeypatch.setattr('twobyteasr.providers.anthropic_messages.complete',
                        lambda endpoint, messages, **kw: seen.update(kw) or 'ok')
    client = SimpleNamespace(endpoint={}, provider_id='anthropic', model='claude', last_timings={},
                             _DESIGN_OPERATIONS=OpenAICompatibleProvider._DESIGN_OPERATIONS)
    for thinking in ('max', 'high', False, True):
        OpenAICompatibleProvider._complete_anthropic(client, [], max_tokens=10, timeout=1, cancel_check=None,
            stage='polished', operation=None, json_wanted=True, on_stream_event=None, enable_thinking=thinking)
        assert 'effort' not in seen and seen['enable_thinking'] == thinking


# --- proofreading --------------------------------------------------------------------------------

def cue(i, text):
    return SpeechSegment(segment_id=i, start=i*100., end=i*100.+2, text=text, confidence=.85,
        words=[], speaker='S01', moss_text=text, firered_text=text, qwen_asr_text=text)


def ids_of(messages):
    return [row['id'] for row in json.loads(messages[1]['content'])['cues']]


def checked(messages):
    return json.dumps({'checked_ids': ids_of(messages), 'cues': []})


def install(monkeypatch, answer):
    calls = []

    def complete(messages, **kwargs):
        calls.append((ids_of(messages), kwargs.get('enable_thinking'), kwargs.get('max_tokens')))
        return answer(messages, kwargs.get('max_tokens', 0) > 10000)
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(complete=complete))
    monkeypatch.setattr('twobyteasr.providers.provider_input_budget.retry_delay', lambda *a: 0)
    return calls


def escalated(calls):
    return [ids for ids, _, max_tokens in calls if max_tokens and max_tokens > 10000]


@pytest.fixture
def observed(monkeypatch):
    from twobyteasr.recognition.cache import add_run_event_observer, remove_run_event_observer
    seen = []
    observer = add_run_event_observer(lambda name, payload: seen.append((name, payload)))
    yield seen
    remove_run_event_observer(observer)


def fallback_reviews(ctx, category='校对回退'):
    return [item for item in ctx.review_items if item.get('category') == category]


def test_bad_json_batch_is_rescued_without_extra_thinking(context, monkeypatch, observed):
    _, ctx, _ = context
    calls = install(monkeypatch, lambda messages, thinking:
                    checked(messages) if thinking or ids_of(messages) != [2] else 'not json')
    rows = [cue(i, f'第{i}段普通解说') for i in range(1, 4)]
    result = polishing.polish_subtitles(rows, '提高思考重试')
    assert escalated(calls) == [[2]]
    assert all(thinking is False for _, thinking, _ in calls)
    summary = ctx.polishing_summary
    assert summary['fallback_cues'] == 0 and summary['fallback_batches'] == 0
    receipt = next(row for row in result if row.segment_id == 2).caption_arbitration['terminology_polish']
    assert receipt['escalation'] == {'thinking': False, 'outcome': 'succeeded', 'category': ''}
    assert receipt['response_state'] != 'fallback'
    assert not fallback_reviews(ctx)
    done = [payload for name, payload in observed if name == 'ai_escalation_round' and payload.get('state') == 'completed']
    assert done and done[-1]['succeeded_cues'] == 1 and done[-1]['resolved_batches'] == [2]


def test_second_failure_keeps_original_text_and_one_warning(context, monkeypatch):
    _, ctx, _ = context
    calls = install(monkeypatch, lambda messages, thinking:
                    'not json' if ids_of(messages) == [2] else checked(messages))
    rows = [cue(i, f'第{i}段普通解说') for i in range(1, 4)]
    result = polishing.polish_subtitles(rows, '提高思考仍失败')
    assert escalated(calls) == [[2]]  # exactly one extra request, no retry inside the escalation round
    assert ctx.polishing_summary['fallback_ids'] == [2]
    receipt = next(row for row in result if row.segment_id == 2).caption_arbitration['terminology_polish']
    assert receipt['response_state'] == 'fallback' and receipt['escalation']['outcome'] == 'failed'
    assert next(row for row in result if row.segment_id == 2).text == '第2段普通解说'
    assert len(fallback_reviews(ctx)) == 1


def test_semantic_rejection_is_not_resent(context, monkeypatch):
    _, ctx, _ = context
    wrong_receipt = json.dumps({'checked_ids': [999], 'cues': []})
    calls = install(monkeypatch, lambda messages, thinking:
                    wrong_receipt if ids_of(messages) == [2] else checked(messages))
    polishing.polish_subtitles([cue(i, f'第{i}段普通解说') for i in range(1, 4)], '语义拒绝')
    assert not escalated(calls) and ctx.polishing_summary['fallback_ids'] == [2]


def test_switch_off_sends_nothing_extra(context, monkeypatch, observed):
    core, ctx, _ = context
    models = core.RUNTIME_SETTINGS.setdefault('models', {})
    # unified processing reads the group switch, so both are turned off
    monkeypatch.setitem(models, 'polish_escalate_on_failure', False)
    monkeypatch.setitem(models, 'group_escalate_on_failure', False)
    calls = install(monkeypatch, lambda messages, thinking:
                    'not json' if ids_of(messages) == [2] else checked(messages))
    result = polishing.polish_subtitles([cue(i, f'第{i}段普通解说') for i in range(1, 4)], '开关关闭')
    assert not escalated(calls) and ctx.polishing_summary['fallback_ids'] == [2]
    assert 'escalation' not in next(row for row in result if row.segment_id == 2).caption_arbitration['terminology_polish']
    assert [payload['skipped_reason'] for name, payload in observed if name == 'ai_escalation_round'] == ['disabled']


def test_too_many_failures_point_at_the_service(context, monkeypatch, observed):
    _, ctx, _ = context
    calls = install(monkeypatch, lambda messages, thinking: 'not json')
    polishing.polish_subtitles([cue(i, f'第{i}段普通解说') for i in range(1, 13)], '大量失败')
    assert not escalated(calls) and ctx.polishing_summary['fallback_cues'] == 12
    assert [payload['skipped_reason'] for name, payload in observed if name == 'ai_escalation_round'] == ['too_many_failures']


def test_unknown_relay_gets_no_guessed_parameter(context, monkeypatch, observed):
    from dataclasses import replace
    _, ctx, _ = context
    relay = replace(ctx.provider_snapshot, _endpoint=tuple({**dict(ctx.provider_snapshot._endpoint),
                                                           'base_url': 'https://relay.example/v1'}.items()))
    monkeypatch.setattr('twobyteasr.providers.asr_provider_snapshot.task_provider_snapshot', lambda *_: relay)
    calls = install(monkeypatch, lambda messages, thinking:
                    'not json' if ids_of(messages) == [2] else checked(messages))
    polishing.polish_subtitles([cue(i, f'第{i}段普通解说') for i in range(1, 4)], '未知中转')
    assert not escalated(calls)
    assert [payload['skipped_reason'] for name, payload in observed if name == 'ai_escalation_round'] == ['no_higher_thinking_level']


def test_escalated_cache_entry_is_separate(context, monkeypatch):
    _, ctx, cache = context
    calls = install(monkeypatch, lambda messages, thinking:
                    checked(messages) if thinking or ids_of(messages) != [2] else 'not json')
    polishing.polish_subtitles([cue(i, f'第{i}段普通解说') for i in range(1, 4)], '缓存', cache_context=cache)
    first = len(escalated(calls))
    ctx.review_items.clear()
    polishing.polish_subtitles([cue(i, f'第{i}段普通解说') for i in range(1, 4)], '缓存', cache_context=cache)
    assert first == 1 and len(escalated(calls)) == 1  # the rescued answer came back from its own cache entry
    assert ctx.polishing_summary['fallback_cues'] == 0


# --- cue_id read as id (2026-11-17 user's Roco stream: 125 of 284 cues lost to this) -------------

def test_cue_id_field_is_read_as_id_without_another_request(context, monkeypatch, observed):
    _, ctx, _ = context

    def answer(messages, thinking):
        ids = ids_of(messages)
        # The real answer shape: an echoed "type", rows named cue_id, one row still named id.
        rows = [{'cue_id': ids[0], 'edits': [{'from': '短容', 'to': '短绒', 'type': 'phonetic_correction'}]}]
        if len(ids) > 1:
            rows.append({'id': ids[1], 'edits': []})
        return json.dumps({'type': 'json_object', 'checked_ids': ids, 'cues': rows}, ensure_ascii=False)
    calls = install(monkeypatch, answer)
    rows = [cue(i, f'第{i}段的短容装备') for i in range(1, 4)]
    result = polishing.polish_subtitles(rows, '字段别名')
    assert len(calls) == 3 and not escalated(calls)
    assert ctx.polishing_summary['fallback_cues'] == 0 and not fallback_reviews(ctx)
    receipt = next(row for row in result if row.segment_id == 1).caption_arbitration['terminology_polish']
    assert receipt['response_state'] != 'fallback' and receipt['returned_edits']
    alias = [payload for name, payload in observed if name == 'polishing_response_field_alias']
    assert sorted(i for payload in alias for i in payload['cue_ids']) == [1, 2, 3]


@pytest.mark.parametrize('row', [
    {'id': 1, 'cue_id': 2, 'edits': []},        # two different readings
    {'cue_id': 9, 'edits': []},                 # not a cue of this batch
    {'cue_id': '1', 'edits': []},               # not a whole number
])
def test_ambiguous_cue_id_stays_invalid(row):
    """Never read as an id: the batch fails, or (with a usable id) only that cue is quarantined."""
    from twobyteasr.providers.ai_providers import AIProviderError
    segments = [cue(1, '第一段'), cue(2, '第二段')]
    quarantined = polishing.CueValidationFailures()
    try:
        value = polishing._validate_polish_response({'checked_ids': [1, 2], 'cues': [row]}, segments, 1, quarantined)
    except AIProviderError as error:
        assert error.category in {'structured_schema_error', 'coverage_mismatch'}
    else:
        assert 1 in quarantined and all('cue_id' not in item for item in value['cues'] if item.get('id') != 1)


def test_matching_id_and_cue_id_is_one_reading():
    value, aliased = polishing._alias_cue_id_fields(
        {'checked_ids': [1], 'cues': [{'id': 1, 'cue_id': 1, 'edits': []}]}, [cue(1, '第一段')])
    assert value['cues'] == [{'id': 1, 'edits': []}] and aliased == [1]


# --- grouping ------------------------------------------------------------------------------------

def test_grouping_batch_rescued_with_same_mode_drops_fallback_warning(context, monkeypatch, observed):
    from twobyteasr.providers.asr_provider_snapshot import GroupedBatchResult
    from twobyteasr.subtitle_rules import grouping
    _, ctx, _ = context
    calls = []

    def fake(batch, **kw):
        result = grouping.conservative_ai_fallback(batch, kw.get('firered_tokens', ()), kw.get('speech_regions', ()))
        if not grouping._restore_grouped_source(batch, result):
            result = [grouping.individual_cue(segment) for segment in batch]
        thinking = kw['provider_snapshot'].enable_thinking
        calls.append(([row.segment_id for row in batch], thinking))
        if len(calls) > 1:
            return GroupedBatchResult(result, origin='ai', validated=True)
        kw['batch_diagnostics']['fallback_reason'] = 'parse_failure'
        grouping.add_review_item(batch[0].start, '断句回退', 'fixture', batch[0].text, priority=3, severity='warning')
        return GroupedBatchResult(result, origin='fallback')
    monkeypatch.setattr(grouping, 'call_grouping_api', fake)
    monkeypatch.setattr(ctx, 'task_language', 'zh')
    rows = [SpeechSegment(i, i*2., i*2.+2, f'这一波第{i}次团战我们继续看看双方怎么处理', .9, [], speaker='S01')
            for i in range(1, 5)]
    result = grouping.group_subtitles(rows, use_ai=True, provider_snapshot=ctx.provider_snapshot)
    assert [thinking for _, thinking in calls] == [False, False, False]
    assert sorted(i for ids, _ in calls[1:] for i in ids) == [1, 2, 3, 4]
    assert not fallback_reviews(ctx, '断句回退')
    assert ''.join(cue.text for cue in result) == ''.join(row.text for row in rows)
    done = [payload for name, payload in observed if name == 'ai_escalation_round' and payload.get('state') == 'completed']
    assert done[-1]['resolved_batches'] == [1] and done[-1]['remaining_fallback_batches'] == 0


def test_grouping_text_rewrite_is_not_resent(context, monkeypatch):
    from twobyteasr.providers.asr_provider_snapshot import GroupedBatchResult
    from twobyteasr.subtitle_rules import grouping
    _, ctx, _ = context
    calls = []

    def fake(batch, **kw):
        calls.append(kw['provider_snapshot'].enable_thinking)
        kw['batch_diagnostics']['fallback_reason'] = 'text_mutation_rejected'
        return GroupedBatchResult([grouping.individual_cue(segment) for segment in batch], origin='fallback')
    monkeypatch.setattr(grouping, 'call_grouping_api', fake)
    monkeypatch.setattr(ctx, 'task_language', 'zh')
    rows = [SpeechSegment(i, i*2., i*2.+2, f'这一波第{i}次团战我们继续看看双方怎么处理', .9, [], speaker='S01')
            for i in range(1, 5)]
    grouping.group_subtitles(rows, use_ai=True, provider_snapshot=ctx.provider_snapshot)
    assert calls == [False]


# --- workbench AI segmentation -------------------------------------------------------------------

def test_workbench_refine_retries_bad_format_with_same_mode(monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue
    from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
    calls = []

    def complete(messages, **kw):
        calls.append(kw.get('enable_thinking'))
        if len(calls) > 1:
            return json.dumps({'results': [{'cue_id': 'a', 'action': 'keep'}]})
        return 'not json at all'
    provider = SimpleNamespace(complete=complete, provider_id='deepseek', model='deepseek-v4-pro',
                               endpoint={'base_url': 'https://api.deepseek.com/v1', 'protocol': 'openai_compatible_chat'})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: provider)
    outcome = refine_cues_with_llm([StudioCue('a', 0, 1000, '当前句')], runtime_settings={'models': {'x': 1}})
    assert len(calls) >= 2 and all(thinking is False for thinking in calls)
    assert [a.cue_id for a in outcome.actions] == ['a']
    assert outcome.results['a']['status'] == 'validated'
    assert 'escalation' not in outcome.results['a']


def test_workbench_refine_unknown_relay_is_unchanged(monkeypatch):
    from twobyteasr.projects.studio_project import StudioCue
    from twobyteasr.subtitle_rules.sentence_refine import refine_cues_with_llm
    calls = []
    provider = SimpleNamespace(complete=lambda messages, **kw: calls.append(kw.get('enable_thinking')) or 'bad',
                               provider_id='relay', model='m', endpoint={'base_url': 'https://relay.example/v1'})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: provider)
    outcome = refine_cues_with_llm([StudioCue('a', 0, 1000, '当前句')], runtime_settings={'models': {'x': 1}})
    assert 'high' not in calls and outcome.escalation.get('skipped_reason') == 'no_higher_thinking_level'
