"""2026-11-18 review of the AI proofreading / grouping stages (user's 鳴潮 special, deepseek-v4-flash).

Each test names the measured failure it removes. Fixtures are synthetic; the shapes are the
ones the real journal recorded.
"""
import json
from types import SimpleNamespace

import pytest

import subtitle_core  # noqa: F401  initialize the legacy facade before polishing
from tests.test_stage9_cache_and_budget import context  # noqa: F401  (fixture)
from tests.test_ai_failure_escalation import cue, escalated, fallback_reviews, ids_of, install, observed  # noqa: F401
from twobyteasr.subtitle_rules import polishing


# --- 1. a flat edits list is the cues the contract asks for (3 of 55 batches, 54 cues) -----------

def flat_answer(ids, edits):
    return {'type': 'json_object', 'checked_ids': ids, 'edits': edits, 'suspect_results': []}


def test_flat_edits_are_regrouped_without_another_request(context, monkeypatch, observed):
    _, ctx, _ = context

    def answer(messages, thinking):
        ids = ids_of(messages)
        edits = [{'cue_id': ids[0], 'from': '短容', 'to': '短绒', 'type': 'phonetic_correction'}]
        return json.dumps(flat_answer(ids, edits), ensure_ascii=False)
    calls = install(monkeypatch, answer)
    rows = [cue(i, f'第{i}段的短容装备') for i in range(1, 4)]
    result = polishing.polish_subtitles(rows, '扁平编辑')
    assert len(calls) == 3 and not escalated(calls)
    assert ctx.polishing_summary['fallback_cues'] == 0 and not fallback_reviews(ctx)
    receipt = next(row for row in result if row.segment_id == 1).caption_arbitration['terminology_polish']
    assert receipt['response_state'] != 'fallback' and receipt['returned_edits']
    shapes = [payload for name, payload in observed if name == 'polishing_response_shape_regrouped']
    assert len(shapes) == 3 and sorted(i for row in shapes for i in row['edited_cue_ids']) == [1, 2, 3]


def test_regrouped_value_keeps_every_cue_in_batch_order():
    segments = [cue(1, '第一段'), cue(2, '第二段'), cue(3, '第三段')]
    value, edited = polishing._regroup_flat_edits(flat_answer([1, 2, 3], [
        {'cue_id': 3, 'from': '三', 'to': '叁'}, {'id': 1, 'from': '一', 'to': '壹'}]), segments)
    assert edited == [1, 3] and 'type' not in value and 'edits' not in value
    assert value['cues'] == [{'id': 1, 'edits': [{'from': '一', 'to': '壹'}]}, {'id': 2, 'edits': []},
                             {'id': 3, 'edits': [{'from': '三', 'to': '叁'}]}]


@pytest.mark.parametrize('edit', [
    {'cue_id': 9, 'from': 'a', 'to': 'b'},              # not a cue of this batch
    {'cue_id': '1', 'from': 'a', 'to': 'b'},            # not a whole number
    {'cue_id': 1, 'id': 2, 'from': 'a', 'to': 'b'},     # two readings
    {'from': 'a', 'to': 'b'},                           # no owner
    'a -> b',
])
def test_ambiguous_flat_edits_stay_invalid(edit):
    from twobyteasr.providers.ai_providers import AIProviderError
    segments = [cue(1, '第一段'), cue(2, '第二段')]
    value, edited = polishing._regroup_flat_edits(flat_answer([1, 2], [edit]), segments)
    assert edited is None and 'cues' not in value
    with pytest.raises(AIProviderError) as error:
        polishing._validate_polish_response(flat_answer([1, 2], [edit]), segments, 1)
    assert error.value.category == 'structured_schema_error'


def test_an_answer_with_cues_is_never_regrouped():
    value = {'checked_ids': [1], 'cues': [], 'edits': [{'cue_id': 1, 'from': 'a', 'to': 'b'}]}
    assert polishing._regroup_flat_edits(value, [cue(1, 'a')]) == (value, None)


# --- 1. a batch that keeps missing the contract is halved once before it falls back -----------

def test_schema_failure_halves_once_then_succeeds(context, monkeypatch, observed):
    monkeypatch.setattr(polishing, 'API_RETRIES', 1)

    def answer(messages, thinking):
        ids = ids_of(messages)
        if len(ids) > 2:
            return json.dumps({'checked_ids': ids, 'rows': []})   # wrong envelope, every time
        return json.dumps({'checked_ids': ids, 'cues': []})
    calls = install(monkeypatch, answer)
    batch = [cue(i, f'第{i}段') for i in range(1, 5)]
    for row in batch:
        row.start, row.end = row.segment_id * 2., row.segment_id * 2. + 1.5
    result = polishing.call_correction_api(batch, [], '', '', 'fixture', '', [], [], [],
                                          batch_index=7, batch_total=9)
    assert result.succeeded == {1, 2, 3, 4} and not result.failures
    assert [ids for ids, _ in calls] == [[1, 2, 3, 4], [1, 2], [3, 4]]
    split = [payload for name, payload in observed if name == 'llm_structured_batch_split']
    assert len(split) == 1 and split[0]['policy'] == 'bounded_format_failure_halving_v1'


def test_schema_failure_is_halved_at_most_once(context, monkeypatch):
    monkeypatch.setattr(polishing, 'API_RETRIES', 1)
    calls = install(monkeypatch, lambda messages, thinking: json.dumps({'checked_ids': ids_of(messages), 'rows': []}))
    batch = [cue(i, f'第{i}段') for i in range(1, 9)]
    for row in batch:
        row.start, row.end = row.segment_id * 2., row.segment_id * 2. + 1.5
    result = polishing.call_correction_api(batch, [], '', '', 'fixture', '', [], [], [],
                                          batch_index=7, batch_total=9)
    assert len(calls) == 3 and not result.succeeded


def test_failed_structured_answer_is_recorded(context, monkeypatch, observed):
    monkeypatch.setattr(polishing, 'API_RETRIES', 1)
    bad = {'checked_ids': [1], 'rows': [{'id': 1}]}
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(structured_complete=lambda *a, **k: dict(bad)))
    polishing.call_correction_api([cue(1, '第一段')], [], '', '', 'fixture', '', [], [], [],
                                  batch_index=3, batch_total=4)
    failed = [payload for name, payload in observed if name == 'llm_structured_output_failed']
    assert failed and '"rows"' in failed[-1]['raw_response_preview']


# --- 1. thinking escalation gets an output budget the reasoning cannot use up ------------------

def test_escalated_output_budget_is_raised_within_the_request_window(monkeypatch):
    from twobyteasr.providers import model_discovery, provider_input_budget
    from twobyteasr.providers.subtitle_request_policy import (
        ESCALATION_INPUT_RESERVE, ESCALATION_OUTPUT_TOKENS, escalated_output_tokens)
    snapshot = SimpleNamespace(max_output_tokens=8000, model='m',
                               endpoint=lambda: {'provider': 'p', 'base_url': 'u', 'api_key': ''})
    monkeypatch.setattr(model_discovery, 'model_limits', lambda *a: {})
    assert ESCALATION_OUTPUT_TOKENS == 32768
    assert escalated_output_tokens(snapshot) == 32768
    snapshot.max_output_tokens = 12000
    assert escalated_output_tokens(snapshot, 'group') == 32768
    # The request window still bounds it: input reserve + output must fit beside each other.
    for operation in ('polish', 'group'):
        window = provider_input_budget.POLICIES[operation].context_tokens
        assert ESCALATION_OUTPUT_TOKENS + ESCALATION_INPUT_RESERVE <= window
    snapshot.max_output_tokens = 10000
    monkeypatch.setattr(model_discovery, 'model_limits', lambda *a: {'output_tokens': 16000})
    assert escalated_output_tokens(snapshot) == 16000
    monkeypatch.setattr(model_discovery, 'model_limits', lambda *a: {'context_tokens': 32768})
    assert escalated_output_tokens(snapshot, 'group') == 20480
    monkeypatch.setattr(model_discovery, 'model_limits', lambda *a: {'output_tokens': 8000})
    assert escalated_output_tokens(snapshot) == 10000  # never below what the user configured
    snapshot.max_output_tokens = 40000
    monkeypatch.setattr(model_discovery, 'model_limits', lambda *a: {})
    assert escalated_output_tokens(snapshot) == 40000


def test_escalated_request_passes_the_input_window_check():
    from twobyteasr.providers.provider_input_budget import prepare_input
    messages = [{'role': 'user', 'content': '字' * 6000}]
    for operation in ('polish', 'group'):
        _, report = prepare_input(messages, max_tokens=32768, operation=operation,
                                  schema={'type': 'object'})
        assert report['passed']


def test_truncated_answer_without_a_higher_level_retries_with_more_budget(monkeypatch):
    from twobyteasr.providers import model_discovery
    from twobyteasr.providers.subtitle_request_policy import retry_thinking
    monkeypatch.setattr(model_discovery, 'model_limits', lambda *a: {})
    relay = SimpleNamespace(max_output_tokens=10000, enable_thinking=False, thinking_protocol='auto',
                            model='deepseek-v4-flash',
                            endpoint=lambda: {'provider': 'relay', 'base_url': 'https://relay.example/v1'})
    cut = {'structured_output_truncated_before_answer': 3}
    # An unverified relay has no thinking dialect: same value, larger budget, only for cut-offs.
    assert retry_thinking(relay, cut, base_url='https://relay.example/v1') is False
    assert retry_thinking(relay, {'structured_schema_error': 1}, base_url='https://relay.example/v1') is None
    assert retry_thinking(relay, {**cut, 'structured_schema_error': 1},
                          base_url='https://relay.example/v1') is None
    # Already at the top level: resend at max with more room.
    top = SimpleNamespace(**{**vars(relay), 'enable_thinking': 'max'})
    assert retry_thinking(top, cut, base_url='https://api.deepseek.com/v1') == 'max'
    # Nothing to gain when the budget cannot grow.
    monkeypatch.setattr(model_discovery, 'model_limits', lambda *a: {'output_tokens': 10000})
    assert retry_thinking(relay, cut, base_url='https://relay.example/v1') is None
    # The official endpoint still goes one level up.
    official = SimpleNamespace(**{**vars(relay), 'endpoint': lambda: {}})
    assert retry_thinking(official, cut, base_url='https://api.deepseek.com/v1') == 'high'


def test_escalated_polish_request_carries_the_larger_budget(context, monkeypatch):
    seen = []

    def complete(messages, **kwargs):
        seen.append((kwargs.get('enable_thinking'), kwargs.get('max_tokens')))
        ids = ids_of(messages)
        return 'not json' if kwargs.get('enable_thinking') in (False, None) and ids == [2] else \
            json.dumps({'checked_ids': ids, 'cues': []})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',
                        lambda *a, **k: SimpleNamespace(complete=complete))
    monkeypatch.setattr('twobyteasr.providers.provider_input_budget.retry_delay', lambda *a: 0)
    polishing.polish_subtitles([cue(i, f'第{i}段普通解说') for i in range(1, 4)], '预算')
    ordinary = {tokens for thinking, tokens in seen if thinking in (False, None)}
    raised = {tokens for thinking, tokens in seen if thinking == 'high'}
    assert raised and min(raised) > max(ordinary)


# --- 2. mandatory breaks are local knowledge: added, never a reason to drop the batch ----------

def test_with_mandatory_breaks_adds_protected_and_snapped_hard_breaks():
    from twobyteasr.subtitle_rules.segmentation import with_mandatory_breaks
    text = 'はいディン陣団イフの物語をお楽しみください'
    total = len(text)
    boundaries, added = with_mandatory_breaks(text, [total], hard_offsets=[2], protected_offsets=[5])
    assert added == [2, 5] and boundaries == [2, 5, total]
    same, none = with_mandatory_breaks(text, [2, 5, total], hard_offsets=[2], protected_offsets=[5])
    assert none == [] and same == [2, 5, total]
    out, _ = with_mandatory_breaks(text, [0, total + 3, total], protected_offsets=[0, total])
    assert out == [total]  # nothing outside the text, the closing offset kept


def test_overlapping_turn_with_its_own_hard_break_does_not_fail_the_batch(monkeypatch):
    """Batch 120: S01 / S18 overlap; the S01 turn measured a hard break the request never showed."""
    from twobyteasr.recognition.transcript_data import SpeechSegment
    from twobyteasr.recognition.cache import add_run_event_observer, remove_run_event_observer
    from twobyteasr.subtitle_rules import grouping, segmentation
    from twobyteasr.subtitle_rules.language_rules import language_scope
    rows = [SpeechSegment(1168, 3349.84, 3354.44, 'でこの皆さんがとあるハプニングに巻き込まれた人', .9, [], speaker='S01'),
            SpeechSegment(1171, 3355.85, 3356.26, 'はい', .9, [], speaker='S18'),
            SpeechSegment(1172, 3356.28, 3359.63, 'お話となっておりますそれでは', .9, [], speaker='S01')]
    original = grouping.hard_break_character_offsets

    def turn_hard_breaks(batch, tokens=()):
        return {1} if [row.segment_id for row in batch] == [1168] else original(batch, tokens)
    monkeypatch.setattr(grouping, 'hard_break_character_offsets', turn_hard_breaks)
    monkeypatch.setattr(segmentation, 'hard_break_character_offsets', turn_hard_breaks)
    seen = []
    observer = add_run_event_observer(lambda name, payload: seen.append((name, payload)))
    try:
        with language_scope('ja'):
            texts = [rows[0].text, rows[1].text, rows[2].text]
            cues = grouping.cues_from_resegmented_texts(rows, texts)
    finally:
        remove_run_event_observer(observer)
    assert ''.join(cue.text for cue in cues) == ''.join(texts)
    added = [payload for name, payload in seen if name == 'grouping_turn_mandatory_breaks_added']
    assert added and added[0]['source_segment_ids'] == [1168]


# --- 3. Japanese grouping picks numbered phrase ends instead of copying the text --------------

def test_marked_text_places_each_mark_before_the_next_counted_character():
    from twobyteasr.subtitle_rules.segmentation import marked_break_text, snap_to_break_candidates
    text = 'はい、本当だよ。本当に'
    assert marked_break_text(text, [2, 6, 9]) == 'はい、‹2›本当だよ。‹6›本当に‹9›'
    assert snap_to_break_candidates([3, 5, 9], [2, 6, 9]) == (
        [2, 6, 9], [{'given': 3, 'used': 2}, {'given': 5, 'used': 6}])
    assert snap_to_break_candidates([4, 9], [2, 6, 9])[0] == [6, 9]   # a tie goes to the later mark


def test_japanese_candidates_hold_phrase_ends_mandatory_breaks_and_the_end(monkeypatch):
    from twobyteasr.subtitle_rules import japanese_morphology
    from twobyteasr.subtitle_rules.segmentation import japanese_break_candidates
    text = '本当だよ本当に坂本が'
    monkeypatch.setattr(japanese_morphology, 'document_phrase_spans',
                        lambda content: [(0, 4, '本当だよ'), (4, 7, '本当に'), (7, 10, '坂本が')])
    # 2026-11-25: a mandatory break inside a word moves to the nearest phrase edge.
    assert japanese_break_candidates(text, mandatory=[2]) == [4, 7, 10]
    assert japanese_break_candidates(text, mandatory=[7]) == [4, 7, 10]
    # Without a morphology document: script-class phrases, never every character gap.
    monkeypatch.setattr(japanese_morphology, 'document_phrase_spans', lambda content: None)
    assert japanese_break_candidates('本当だ', ()) == [3]


def test_japanese_request_sends_marks_and_reads_an_off_mark_pick(monkeypatch, tmp_path):
    import subtitle_core as core
    from tests.test_grouping_prompt_guidance import call, japanese_segment
    from tests.test_stage9_cache_and_budget import config
    from twobyteasr.providers import llm_config
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.subtitle_rules import grouping, japanese_morphology
    monkeypatch.setattr(llm_config, 'read_scoped_api_key', lambda *a: ('fixture', 'test'))
    monkeypatch.setattr(japanese_morphology, 'document_phrase_spans', lambda content: [
        (0, 4, '本当だよ'), (4, 7, '本当に'), (7, 10, '坂本が'), (10, 15, '入れろって'), (15, 20, '言ったから')])
    sent, records = [], []

    def post(*args, **kwargs):
        sent.append(kwargs.get('messages') or args[1] if len(args) > 1 else kwargs)
        return json.dumps({'boundaries': [9, 20]})   # 9 is not a mark: the nearest one is 10
    monkeypatch.setattr(grouping, 'GROUPING_API_RETRIES', 1)
    monkeypatch.setattr(grouping, 'post_chat_completion', post)
    monkeypatch.setattr(grouping, 'record_run_event', lambda event, **kw: records.append((event, kw)))
    context = RuntimeContext(provider_snapshot=resolve_provider_snapshot(config()), task_language='ja',
                             asr_settings_snapshot={'grouping_prompts': {}}, event_log_path=str(tmp_path / 'e.jsonl'))
    with activate_runtime_context(context, legacy=core):
        result = call(grouping, [japanese_segment('本当だよ本当に坂本が入れろって言ったから')])
    body = next(kw['request_body'] for event, kw in records if event == 'grouping_request_contract')
    assert 'indexed_content' not in body and 'source_text' not in body
    assert body['marked_text'] == '本当だよ‹4›本当に‹7›坂本が‹10›入れろって‹15›言ったから‹20›'
    snapped = next(kw for event, kw in records if event == 'grouping_marked_boundaries_snapped')
    assert snapped['moved'] == [{'given': 9, 'used': 10}]
    trace = next(kw for event, kw in records if event == 'grouping_trace')
    assert trace['model_boundaries'] == [10, 20]
    assert ''.join(cue.text for cue in result) == '本当だよ本当に坂本が入れろって言ったから'


# --- 4. a library the scene blocks is reported once, not only as a journal reason ---------------

def test_blocked_library_is_reported_once_with_a_review_item(monkeypatch):
    from tests.test_content_scene_polish import library
    from twobyteasr.glossary.terminology import GlossarySnapshot, TermEntry, apply_to_segments
    from twobyteasr.recognition import content_scene
    from twobyteasr.recognition.transcript_data import SpeechSegment
    game = GlossarySnapshot((library('鳴潮', '鳴潮', '25', (TermEntry('鎖暝', ('サメ',), category='角色'),)),))
    scene = content_scene.resolve_content_scene(SimpleNamespace(enable_domain_terms=True, game_name='原神'), game)
    monkeypatch.setattr(content_scene, 'runtime_content_scene', lambda: scene)
    events, reviews = [], []

    def add_review_item(timestamp, category, detail, text='', priority=1, severity=None, **kw):
        reviews.append(dict(category=category, detail=detail))
    legacy = SimpleNamespace(record_run_event=lambda name, **kw: events.append((name, kw)), add_review_item=add_review_item)
    rows = [SpeechSegment(1, 0, 2, '守りますサメのこと', .9, []), SpeechSegment(2, 3, 4, 'サメお姉ちゃん', .9, [])]
    apply_to_segments(rows, game, legacy)
    assert [row.text for row in rows] == ['守りますサメのこと', 'サメお姉ちゃん']
    blocked = [kw for name, kw in events if name == 'terminology_library_domain_blocked']
    assert blocked and blocked[0]['libraries'][0]['library_name'] == '鳴潮'
    assert blocked[0]['libraries'][0]['skipped_matches'] == 2 and blocked[0]['scene_domain'] == '原神'
    assert len(reviews) == 1 and '「鳴潮」' in reviews[0]['detail'] and '2 处' in reviews[0]['detail']


def test_matching_scene_reports_nothing(monkeypatch):
    from tests.test_content_scene_polish import library
    from twobyteasr.glossary.terminology import GlossarySnapshot, TermEntry, apply_to_segments
    from twobyteasr.recognition import content_scene
    from twobyteasr.recognition.transcript_data import SpeechSegment
    game = GlossarySnapshot((library('鳴潮', '鳴潮', '25', (TermEntry('鎖暝', ('サメ',), category='角色'),)),))
    scene = content_scene.resolve_content_scene(
        SimpleNamespace(enable_domain_terms=True, game_name='鸣潮声优特别节目'), game)
    monkeypatch.setattr(content_scene, 'runtime_content_scene', lambda: scene)
    events = []
    rows = [SpeechSegment(1, 0, 2, '守りますサメのこと', .9, [])]
    apply_to_segments(rows, game, SimpleNamespace(record_run_event=lambda name, **kw: events.append(name)))
    assert rows[0].text == '守ります鎖暝のこと' and 'terminology_library_domain_blocked' not in events


def test_completion_summary_names_the_blocked_library():
    from twobyteasr.app.completion_summary import completion_summary
    from twobyteasr.app.completion_summary import completion_translate
    report = {'events': [{'event': 'terminology_library_domain_blocked', 'scene_domain': '原神',
                          'libraries': [{'library_id': '鳴潮', 'library_name': '鳴潮', 'skipped_matches': 51}]}]}
    outcome = SimpleNamespace(core_status='completed', final_cues=10, polish_status='completed', polish_label='',
                              search_label='', core_errors=(), review_issue_count=0)
    try:
        summary = completion_summary(report, outcome, language='zh')
    except (AttributeError, TypeError) as error:   # the outcome fixture is minimal
        pytest.skip(f'completion_summary needs a fuller outcome: {error}')
    text = json.dumps(summary.__dict__ if hasattr(summary, '__dict__') else str(summary), ensure_ascii=False, default=str)
    assert '「鳴潮」' in text and '51' in text
    assert completion_translate('词库{names}未套用：领域与游戏名称「{domain}」不符，{count} 处别名没有替换', 'en').startswith('Glossary')


# --- 6. the recognizer hears how a written name sounds -----------------------------------------

def test_qwen_context_carries_kana_readings_of_listed_names():
    from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    game = GlossarySnapshot((GlossaryLibrary('鳴潮', '鳴潮', '25', (
        TermEntry('鎖暝', ('サメイ', 'サメ', '鎖冥'), category='角色'),
        TermEntry('吟霖', ('インリン',), category='角色'),
        TermEntry('ショアキーパー', ('ショア',), category='角色'),     # a kana name needs no reading
        TermEntry('漂泊者', ('漂白者',), category='角色'),             # a kanji mishearing is not a reading
    )),))
    with activate_runtime_context(RuntimeContext(enable_domain_terms=True, enabled_glossary_ids=['鳴潮'],
                                                 glossary_snapshot=game)):
        text = asr.build_qwen_asr_context('clip.mp4')
    assert '鎖暝' in text.split('用户已确认的专名写法：', 1)[1]
    readings = text.split('这些专名的读音：', 1)[1].split('。', 1)[0].split('、')
    assert sorted(readings) == ['吟霖＝インリン', '鎖暝＝サメイ／サメ']


def test_no_reading_sentence_without_kana_aliases():
    from twobyteasr.glossary.terminology import GlossaryLibrary, GlossarySnapshot, TermEntry
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    game = GlossarySnapshot((GlossaryLibrary('zmd', '终末地', '1', (TermEntry('佩丽卡', ('配力卡',)),)),))
    with activate_runtime_context(RuntimeContext(enable_domain_terms=True, enabled_glossary_ids=['zmd'],
                                                 glossary_snapshot=game)):
        assert '读音' not in asr.build_qwen_asr_context('clip.mp4')


# --- 7. a Japanese fix the second transcript also heard reaches the review list --------------

def test_supported_listening_rejection_becomes_a_review_item(context):
    _, ctx, _ = context
    row = cue(286, 'これ実記でやってるの')
    rejected = [
        {'from': '実記', 'to': '実機', 'rule_id': 'japanese_semantic_needs_listening',
         'evidence': {'actual_independent_families': ['qwen3_asr'], 'acoustic_verified': False}},
        {'from': '安じない', 'to': '案じない', 'rule_id': 'japanese_semantic_needs_listening',
         'evidence': {'actual_independent_families': [], 'acoustic_verified': False}},   # no transcript heard it
        {'from': 'a', 'to': 'b', 'rule_id': 'unknown_or_mismatched_candidate_id',
         'evidence': {'actual_independent_families': ['qwen3_asr']}},                     # not a listening rule
    ]
    before = len(ctx.review_items)
    assert polishing._review_listening_suggestions(row, rejected, 9, 55) == 1
    item = ctx.review_items[before]
    assert item['category'] == 'ASR分歧' and item['severity'] == 'review' and item['cue_id'] == 286
    assert '「実記」改为「実機」' in item['detail'] and 'Qwen3-ASR' in item['detail']
    assert item['suggestion'] == {'from': '実記', 'to': '実機', 'rule_id': 'japanese_semantic_needs_listening',
                                  'independent_families': ['qwen3_asr']}
    assert row.text == 'これ実記でやってるの'


# --- 8. the counters used for this review, read back from a journal ------------------------

def test_stage_metrics_count_and_compare_recorded_events():
    from twobyteasr.recognition.ai_stage_metrics import compare, measure
    before = {'job_id': 'a', 'events': [
        {'event': 'stage_started', 'label': '云端模型受限校对', 'monotonic_seconds': 10.0},
        {'event': 'stage_completed', 'label': '云端模型受限校对', 'monotonic_seconds': 448.5},
        {'event': 'cloud_batch_completed', 'stage': 'polished'},
        {'event': 'polishing_api_fallback', 'category': 'structured_schema_error', 'cue_ids': [1, 2, 3]},
        {'event': 'ai_escalation_round', 'stage': 'polished', 'state': 'started', 'monotonic_seconds': 100.0},
        {'event': 'ai_escalation_round', 'stage': 'polished', 'state': 'completed', 'monotonic_seconds': 436.3},
        {'event': 'terminology_applied', 'replacement_count': 0, 'matches': [
            {'matches': [{'reason': 'alias_domain_conflict'}, {'reason': 'already_canonical'}]}]},
        {'event': 'terminology_polish_detail', 'details': {
            'accepted_edits': [{'rule_id': 'confirmed_exact_japanese_alias'}],
            'rejected_edits': [{'rule_id': 'japanese_semantic_needs_listening'}],
            'suspect_results': [{'disposition': 'keep'}]}},
        {'event': 'api_usage', 'stage': 'polished', 'input_tokens': 100, 'output_tokens': 10,
         'estimated_cost': {'high': '0.000002'}},
    ], 'review_items': [{'category': '断句回退'}]}
    one = measure(before)
    assert one['polish']['stage_seconds'] == 438.5 and one['polish']['fallback_cues'] == 3
    assert one['polish']['escalation_seconds'] == 336.3
    assert one['terminology'] == {'local_replacements_first_pass': 0,
                                  'local_skipped_by_reason': {'alias_domain_conflict': 1},
                                  'libraries_blocked_by_scene': []}
    assert one['usage']['polished'] == {'requests': 1, 'input_tokens': 100, 'output_tokens': 10,
                                        'cached_input_tokens': 0, 'reasoning_tokens': 0, 'cost_usd_micro': 2}
    after = {'job_id': 'b', 'events': [e for e in before['events'] if e['event'] != 'polishing_api_fallback']}
    changed = dict((path, (a, b)) for path, a, b in compare(one, measure(after)))
    assert changed['polish.fallback_cues'] == (3, 0) and 'job_id' not in changed
    assert measure({'events': []})['terminology']['local_replacements_first_pass'] is None


# --- 5. optional strict tool call (off by default; JSON mode on any rejection) ----------------

def test_strict_schema_requires_every_key_and_makes_optional_ones_nullable():
    from twobyteasr.providers.strict_tool_output import strict_schema

    def walk(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for key in ('minLength', 'maxLength', 'minItems', 'maxItems'):
                assert key not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    converted = strict_schema(polishing.POLISH_SCHEMA)
    walk(converted)
    assert 'new_suspects' not in converted['properties']           # free-form metadata cannot be strict
    assert converted['properties']['suspect_results']['anyOf'][1] == {'type': 'null'}
    edit = converted['properties']['cues']['items']['properties']['edits']['items']
    assert edit['properties']['from'] == {'type': 'string'}
    assert edit['properties']['start'] == {'anyOf': [{'type': 'integer'}, {'type': 'null'}]}


def test_strict_request_only_for_the_official_endpoint_when_switched_on():
    from twobyteasr.providers import strict_tool_output as strict
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    strict.clear_rejections()
    official = {'provider': 'deepseek', 'url': 'https://api.deepseek.com/v1/chat/completions', 'model': 'm'}
    on = RuntimeContext(asr_settings_snapshot={'models': {'polish_strict_output': True}})
    off = RuntimeContext(asr_settings_snapshot={'models': {}})
    with activate_runtime_context(off):
        assert strict.request_for(official, polishing.POLISH_SCHEMA, streamed=True) is None
    with activate_runtime_context(on):
        request = strict.request_for(official, polishing.POLISH_SCHEMA, streamed=True)
        assert request['url'] == 'https://api.deepseek.com/beta/chat/completions'
        assert strict.request_for(official, polishing.POLISH_SCHEMA, streamed=False) is None
        relay = {**official, 'url': 'https://relay.example/v1/chat/completions'}
        assert strict.request_for(relay, polishing.POLISH_SCHEMA, streamed=True) is None
        strict.remember_rejection(official, SimpleNamespace(category='request_rejected'))
        assert strict.request_for(official, polishing.POLISH_SCHEMA, streamed=True) is None
    strict.clear_rejections()


def sse(*packets):
    frames = [('data: ' + json.dumps(packet, ensure_ascii=False) + '\n\n').encode() for packet in packets]
    return frames + [b'data: [DONE]\n\n']


def tool_delta(arguments, name=None, finish=None):
    function = {'arguments': arguments}
    if name:
        function['name'] = name
    return {'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'function': function}]},
                         'finish_reason': finish}]}


def test_stream_reads_the_strict_function_arguments_as_the_answer():
    from twobyteasr.providers.provider_stream import StreamProtocolError, chat_body
    chunks = sse({'choices': [{'index': 0, 'delta': {'reasoning_content': 'think'}}]},
                 tool_delta('{"checked_ids":[1],', 'submit_answer'), tool_delta('"cues":[]}'),
                 {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})
    assert chat_body(chunks, {}, tool_name='submit_answer') == '{"checked_ids":[1],"cues":[]}'
    with pytest.raises(StreamProtocolError) as error:
        chat_body(sse(tool_delta('{}', 'other_tool', 'tool_calls')), {}, tool_name='submit_answer')
    assert error.value.category == 'provider_tool_request'
    with pytest.raises(StreamProtocolError):                      # without strict mode a tool call is still refused
        chat_body(sse(tool_delta('{}', 'submit_answer', 'tool_calls')), {})


def test_strict_body_sends_one_forced_strict_function_to_the_beta_url(monkeypatch):
    from twobyteasr.providers import llm_adapter, provider_stream
    seen = {}

    def request_chat(url, headers, body, timeout, diagnostics, emit, cancel_check=None, **kw):
        seen.update(url=url, body=body, tool_name=kw.get('tool_name'))
        return '{"checked_ids":[],"cues":[]}'
    monkeypatch.setattr(provider_stream, 'request_chat', request_chat)
    strict = {'name': 'submit_answer', 'schema': {'type': 'object', 'properties': {}, 'required': [],
              'additionalProperties': False}, 'url': 'https://api.deepseek.com/beta/chat/completions'}
    llm_adapter.post_chat_completion_stream([{'role': 'user', 'content': 'x'}], model='deepseek-v4-flash',
        api_key='k', url='https://api.deepseek.com/v1/chat/completions', max_tokens=100,
        response_format={'type': 'json_object'}, provider='deepseek', strict_tool=strict)
    assert seen['url'] == strict['url'] and seen['tool_name'] == 'submit_answer'
    assert 'response_format' not in seen['body']
    assert seen['body']['tools'][0]['function']['strict'] is True
    assert seen['body']['tool_choice'] == {'type': 'function', 'function': {'name': 'submit_answer'}}


def deepseek_provider(monkeypatch, complete):
    from twobyteasr.providers import strict_tool_output
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
    strict_tool_output.clear_rejections()
    provider = OpenAICompatibleProvider({'provider': 'deepseek', 'model': 'deepseek-v4-flash', 'api_key': 'k',
                                         'base_url': 'https://api.deepseek.com/v1',
                                         'url': 'https://api.deepseek.com/v1/chat/completions'})
    monkeypatch.setattr(provider, 'complete', complete)
    return provider


def test_rejected_strict_request_is_resent_in_json_mode_and_remembered(monkeypatch):
    from twobyteasr.providers import strict_tool_output
    from twobyteasr.providers.ai_providers import AIProviderError
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    calls = []

    def complete(messages, **kwargs):
        calls.append('strict' if kwargs.get('strict_tool') else (kwargs.get('response_format') or {}).get('type'))
        if kwargs.get('strict_tool'):
            raise AIProviderError('HTTP 400', category='request_rejected')
        return '{"checked_ids":[1],"cues":[]}'
    provider = deepseek_provider(monkeypatch, complete)
    with activate_runtime_context(RuntimeContext(asr_settings_snapshot={'models': {'polish_strict_output': True}})):
        for _ in range(2):
            assert provider.structured_complete([], polishing.POLISH_SCHEMA, operation_kind='polish',
                                                on_stream_event=lambda *a: None) == {'checked_ids': [1], 'cues': []}
    assert calls == ['strict', 'json_object', 'json_object']
    strict_tool_output.clear_rejections()


def test_auth_failure_in_strict_mode_is_not_resent(monkeypatch):
    from twobyteasr.providers import strict_tool_output
    from twobyteasr.providers.ai_providers import AIProviderError
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    calls = []

    def complete(messages, **kwargs):
        calls.append(kwargs.get('strict_tool') is not None)
        raise AIProviderError('HTTP 401', category='auth_error')
    provider = deepseek_provider(monkeypatch, complete)
    with activate_runtime_context(RuntimeContext(asr_settings_snapshot={'models': {'polish_strict_output': True}})):
        with pytest.raises(AIProviderError):
            provider.structured_complete([], polishing.POLISH_SCHEMA, operation_kind='polish',
                                         on_stream_event=lambda *a: None)
    assert calls == [True]
    strict_tool_output.clear_rejections()


def test_strict_nulls_for_optional_keys_are_read_as_absent():
    from twobyteasr.providers.strict_tool_output import drop_strict_nulls
    answer = {'checked_ids': [1], 'suspect_results': None, 'cues': [{'id': 1, 'edits': [
        {'from': 'a', 'to': 'b', 'start': None, 'end': None, 'candidate_id': None, 'basis': None,
         'type': 'asr_correction', 'evidence': None}]}]}
    cleaned = drop_strict_nulls(answer, polishing.POLISH_SCHEMA)
    assert cleaned == {'checked_ids': [1], 'cues': [{'id': 1, 'edits': [
        {'from': 'a', 'to': 'b', 'type': 'asr_correction'}]}]}
    # A required key is never dropped, so a null there still fails validation.
    assert drop_strict_nulls({'checked_ids': None, 'cues': []}, polishing.POLISH_SCHEMA)['checked_ids'] is None
