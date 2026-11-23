"""AI cuts one or two characters off a word edge (2026-11-22, 崩铁 2-hour job).

The first answer returned the number of the next line's first character
(英雄了各｜位, 阿格尼丝所｜以); window retries, without numbered text, missed
by one or two (持续关｜注). Every miss was a hard failure, the retry answer was
rejected and the range fell back to the ASR sentence: 204 of 1,546 shipped
cues were over 14 characters. The fixture holds three recorded batches.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping import GROUPING_SCHEMA
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
from twobyteasr.subtitle_rules.ai_boundary_policy import (
    inspect, preserve_rejected_windows, select_model_boundary_domain, snap_offset_errors, windows)
from twobyteasr.subtitle_rules.grouping_quality_request import QualityRetryBudget, retry_quality_windows
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/grouping_contract/hsr_offset_misses_20261122.json')
                     .read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def chinese():
    with language_scope('zh'), activate_runtime_context(RuntimeContext(task_language='zh', enable_domain_terms=False),
                                                        legacy=core):
        yield


def quality_of(text, required=()):
    quality = BoundaryQuality(text, max_chars=14, required=set(required))
    select_model_boundary_domain(quality)
    return quality


def cuts(parts):
    out, total = [], 0
    for part in parts:
        total += len(part)
        out.append(total)
    return out


def pieces(quality, boundaries):
    return [quality.index.slice(a, b) for a, b in zip([0, *boundaries[:-1]], boundaries)]


@pytest.mark.parametrize('answer,expected', [
    (['现在我们总算称得上个英雄了各', '位小心怎么会破晓战队'], ['现在我们总算称得上个英雄了', '各位小心怎么会破晓战队']),
    (['艾利欧说过别输给阿格尼丝所', '以这一局必秒他'], ['艾利欧说过别输给阿格尼丝', '所以这一局必秒他']),
    (['解释起来有点复杂我', '们先按原计划'], ['解释起来有点复杂', '我们先按原计划']),
    (['观众朋友们请持续关', '注我们花海的直播间'], ['观众朋友们请持续', '关注我们花海的直播间']),
    (['期待投身其中', '的每一个人都能'], ['期待投身其中的', '每一个人都能']),
])
def test_cut_one_character_off_a_word_moves_to_the_adjacent_edge(answer, expected):
    quality = quality_of(''.join(answer))
    result, moves = snap_offset_errors(quality, cuts(answer))
    assert pieces(quality, result) == expected
    assert len(moves) == 1
    assert not windows(quality, result)


@pytest.mark.parametrize('answer', [
    ['熄灭群星的末王', '敬未到场的业者'],    # 王敬 is only a guessed personal name
    ['这个伤害有点', '低我们换一个'],        # advisory: goes back to the AI
    ['这把比较', '难打我们先撤'],            # a local move would give 比较难｜打
])
def test_weak_or_advisory_damage_keeps_the_model_cut(answer):
    quality = quality_of(''.join(answer))
    assert snap_offset_errors(quality, cuts(answer)) == (cuts(answer), [])


def test_protected_cut_never_moves():
    answer = ['现在我们总算称得上个英雄了各', '位小心怎么会破晓战队']
    quality = quality_of(''.join(answer), required=[14])
    assert snap_offset_errors(quality, cuts(answer)) == (cuts(answer), [])


@pytest.mark.parametrize('parts,reason', [
    (['这个伤害有点', '低我们换一个'], 'degree_predicate'),
    (['这把比较', '难打我们先撤'], 'degree_predicate'),
    (['我这边两发', '暴风雪就能打死'], 'determiner_object_phrase'),
])
def test_degree_and_shot_count_splits_are_sent_back(parts, reason):
    quality = quality_of(''.join(parts))
    issues = inspect(quality, cuts(parts), advisory=True)
    assert {(i['kind'], i.get('reason')) for i in issues} >= {('word_or_dependency_split', reason)}
    assert windows(quality, cuts(parts), advisory=True)
    whole = cuts([''.join(parts)])
    assert not inspect(quality, whole, advisory=True)


def test_retry_answer_one_character_off_is_accepted_after_the_move():
    text = '观众朋友们请持续关注我们花海的直播间'
    quality = quality_of(text)
    events = []

    def complete(messages, **kwargs):
        body = json.loads(messages[-1]['content'])
        # The recorded answer: 观众朋友们请持续关｜注我们花海的直播间.
        return json.dumps({'windows': [{'id': w['id'], 'boundaries': [9, w['total_length']]}
                                       for w in body['windows']]})

    snapshot = resolve_provider_snapshot({'models': {'ai_service': 'custom', 'provider_profiles': {
        'custom': {'base_url': 'http://127.0.0.1:1/v1', 'model': 'offline'}}}})
    result = retry_quality_windows(quality, [quality.total], [quality.total],
        provider=SimpleNamespace(complete=complete), snapshot=snapshot, schema=GROUPING_SCHEMA,
        budget=QualityRetryBudget(), record=lambda name, **data: events.append(dict(event=name, **data)))
    assert pieces(quality, result) == ['观众朋友们请持续', '关注我们花海的直播间']
    retry = [e for e in events if e['event'] == 'grouping_quality_retry'][0]
    assert retry['status'] == 'improved' and retry['candidate_boundaries'] == [9, quality.total]
    assert [e['moves'][0]['final'] for e in events if e['event'] == 'grouping_boundary_snapped'] == [8]


def _replay(batch):
    """Recorded first answer and window answers through the current gate (no network)."""
    quality = quality_of(batch['source_text'], set(batch['hard_break_offsets']) | set(batch['protected_source_offsets']))
    answers = {}
    for row in batch['retries']:
        text = quality.index.slice(row['content_start'], row['content_end'])
        answers.setdefault(text, {})[row['round']] = row['candidate']

    def complete(messages, **kwargs):
        body = json.loads(messages[-1]['content'])
        rows = []
        for window in body['windows']:
            recorded = answers.get(window['source_text'], {})
            found = recorded.get(body['round']) or recorded.get(1)
            if found:
                rows.append({'id': window['id'], 'boundaries': found})
        return json.dumps({'windows': rows})

    snapshot = resolve_provider_snapshot({'models': {'ai_service': 'custom', 'provider_profiles': {
        'custom': {'base_url': 'http://127.0.0.1:1/v1', 'model': 'offline'}}}})
    model, _moves = snap_offset_errors(quality, list(batch['model_boundaries']))
    statuses = {}
    result = retry_quality_windows(quality, model, model, provider=SimpleNamespace(complete=complete),
        snapshot=snapshot, schema=GROUPING_SCHEMA, budget=QualityRetryBudget(seconds=10**6),
        record=lambda *a, **k: None, statuses=statuses)
    final, _receipts = preserve_rejected_windows(quality, result, sorted(set(batch['source_cuts'])),
                                                 statuses=statuses)
    return quality, final


def test_recorded_batches_keep_fewer_overlong_source_sentences():
    shipped = sum(batch['final_over_14'] for batch in FIXTURE['batches'])
    assert shipped == 17
    over = 0
    texts = []
    for batch in FIXTURE['batches']:
        quality, final = _replay(batch)
        assert ''.join(pieces(quality, final)) == batch['source_text']
        over += sum(1 for a, b in zip([0, *final[:-1]], final) if b - a > 14)
        texts.extend(pieces(quality, final))
    assert over <= 8
    for line in ('现在我们总算称得上个英雄了', '各位小心怎么会破晓战队？'):
        assert line in texts
    assert not any(text.endswith(('英雄了各', '阿格尼丝所')) for text in texts)
