"""AI only, no half-finished local result (user, 2026-11-22).

The 崩铁 2-hour job left 196 ranges on the ASR sentence: two correction
rounds, one request per batch for 40 batches, and a rejected answer meant the
source sentence. Now the model picks ‹N› marks instead of counting, failing
windows go back for up to four rounds, every batch has a request per round,
and the AI's best answer stands; only a split confirmed term or a lost
protected cut returns to the source boundaries.
"""
import json
from types import SimpleNamespace

import pytest

import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules import polishing
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping import GROUPING_SCHEMA
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
from twobyteasr.subtitle_rules.ai_boundary_policy import (
    blocking_issues, break_candidates, inspect, must_retain_source, place_on_marks,
    preserve_rejected_windows, select_model_boundary_domain)
from twobyteasr.subtitle_rules.grouping_quality_request import (
    MAX_QUALITY_ROUNDS, QualityRetryBudget, retry_quality_windows)
from twobyteasr.subtitle_rules.segmentation import marked_break_text
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot


@pytest.fixture(autouse=True)
def chinese():
    with language_scope('zh'), activate_runtime_context(RuntimeContext(task_language='zh', enable_domain_terms=False),
                                                        legacy=core):
        yield


def quality_of(text, required=()):
    quality = BoundaryQuality(text, max_chars=14, required=set(required))
    select_model_boundary_domain(quality)
    return quality


def pieces(quality, boundaries):
    return [quality.index.slice(a, b) for a, b in zip([0, *boundaries[:-1]], boundaries)]


SNAPSHOT = None


def snapshot():
    global SNAPSHOT
    if SNAPSHOT is None:
        SNAPSHOT = resolve_provider_snapshot({'models': {'ai_service': 'custom', 'provider_profiles': {
            'custom': {'base_url': 'http://127.0.0.1:1/v1', 'model': 'offline'}}}})
    return SNAPSHOT


def test_marks_skip_word_interiors_and_dependent_particles():
    text = '现在我们总算称得上个英雄了各位小心怎么会破晓战队'
    quality = quality_of(text)
    marks = break_candidates(quality)
    content = quality.index.content
    assert content.index('各') in marks               # 英雄了｜各位 is offered
    assert content.index('各') + 1 not in marks       # 各｜位 has no mark
    assert content.index('战') + 1 not in marks       # 战｜队 has no mark
    assert content.index('了') not in marks           # 英雄｜了 has no mark
    assert marks[-1] == quality.total
    marked = marked_break_text(text, [x for x in marks if x < quality.total])
    assert '各位' in marked and '战队' in marked and '了‹13›各' in marked


def test_an_unbreakable_stretch_gets_its_allowed_marks_back():
    text = '中华人民共和国国务院总理'*2
    quality = quality_of(text)
    marks = break_candidates(quality)
    edges = [0, *marks]
    assert all(b - a <= quality.max_chars for a, b in zip(edges, edges[1:]))


def test_a_pick_between_marks_moves_to_the_nearest_mark():
    assert place_on_marks([5, 9, 20], [3, 8, 12, 20], right=20) == ([3, 8, 20], [(5, 3), (9, 8)])
    assert place_on_marks([5, 20], [5, 20], right=20) == ([5, 20], [])


def test_every_batch_gets_a_request_per_round():
    budget = QualityRetryBudget()
    budget.register_batches(range(1, 41))
    assert budget.share() >= MAX_QUALITY_ROUNDS == 4
    for batch in range(1, 41):
        assert all(budget.take(2048, batch_index=f'{batch}.quality-{n}') for n in range(MAX_QUALITY_ROUNDS))


def test_failing_window_goes_back_until_the_ai_gets_it_right():
    text = '不同的是你们的钓饵是一颗微不足道的头颅而他的钓饵则是你们每个人的欲望'
    quality = quality_of(text)
    good = [len('不同的是你们的钓饵'), len('不同的是你们的钓饵是一颗微不足道的头颅'),
            len('不同的是你们的钓饵是一颗微不足道的头颅而他的钓饵'), quality.total]
    calls = []

    def complete(messages, **kwargs):
        body = json.loads(messages[-1]['content'])
        calls.append(body['round'])
        assert all('‹' in window['marked_text'] for window in body['windows'])
        # Two rounds keep the over-long answer, the third splits it well.
        answer = (lambda w: [w['total_length']]) if body['round'] < 3 else (lambda w: good)
        return json.dumps({'windows': [{'id': w['id'], 'boundaries': answer(w)} for w in body['windows']]})

    result = retry_quality_windows(quality, [quality.total], [quality.total],
        provider=SimpleNamespace(complete=complete), snapshot=snapshot(), schema=GROUPING_SCHEMA,
        budget=QualityRetryBudget(), record=lambda *a, **k: None)
    assert calls == [1, 2, 3]
    assert pieces(quality, result) == ['不同的是你们的钓饵', '是一颗微不足道的头颅', '而他的钓饵', '则是你们每个人的欲望']


def test_the_ai_best_answer_stands_instead_of_the_asr_sentence():
    text = '观众朋友们请持续关注我们花海的直播间'
    quality = quality_of(text)
    events = []

    def complete(messages, **kwargs):
        body = json.loads(messages[-1]['content'])
        # Every round: one cut the dictionary doubts, but no line over the limit.
        return json.dumps({'windows': [{'id': w['id'], 'boundaries': [5, w['total_length']]}
                                       for w in body['windows']]})

    statuses = {}
    result = retry_quality_windows(quality, [quality.total], [quality.total],
        provider=SimpleNamespace(complete=complete), snapshot=snapshot(), schema=GROUPING_SCHEMA,
        budget=QualityRetryBudget(), record=lambda name, **data: events.append(dict(event=name, **data)),
        statuses=statuses)
    assert pieces(quality, result) == ['观众朋友们', '请持续关注我们花海的直播间']
    final, receipts = preserve_rejected_windows(quality, result, [quality.total], statuses=statuses,
                                                retain=must_retain_source)
    assert final == result and not receipts
    assert not blocking_issues(inspect(quality, final))


def test_only_a_lost_protected_cut_or_split_term_returns_to_the_source():
    text = '不用防御的感觉真美妙。今天先停，明天继续。'
    quality = quality_of(text, required=[10])
    final, receipts = preserve_rejected_windows(quality, [4, 14, quality.total], [10, quality.total],
                                                retain=must_retain_source)
    assert 10 in final and receipts and receipts[0]['remaining_issues'][0]['kind'] == 'protected_boundary_missing'
    assert must_retain_source(dict(kind='semantic_boundary', start=3, end=3, reason='confirmed_term_split'))
    assert not must_retain_source(dict(kind='semantic_boundary', start=3, end=3, reason='known_word_split'))
    assert not must_retain_source(dict(kind='length', start=0, end=20, length=20))


def test_proofread_quote_one_or_two_characters_off_finds_its_occurrence():
    text = '主要是他最后有个炸糖他不炸糖的话真过了朋友们'
    failures = polishing.CueValidationFailures()
    value = polishing._validate_polish_response({'checked_ids': [212], 'cues': [{'id': 212, 'edits': [
        {'from': '炸糖', 'to': '炸膛', 'start': 6, 'end': 8, 'type': 'asr_correction'},
        {'from': '炸糖', 'to': '炸膛', 'start': 11, 'end': 13, 'type': 'asr_correction'}]}]},
        [SpeechSegment(212, 0., 3., text, .9, [])], 1, failures)
    assert not failures
    assert [(e['start'], e['end']) for e in value['cues'][0]['edits']] == [(8, 10), (12, 14)]


def test_proofread_no_op_suggestion_does_not_drop_the_cue():
    text = '不同的是你们的钓饵是一颗微不足道的头颅而他的钓饵则是你们每个人的欲望'
    failures = polishing.CueValidationFailures()
    value = polishing._validate_polish_response({'checked_ids': [85], 'cues': [{'id': 85, 'edits': [
        {'from': '钓饵', 'to': '钓饵', 'start': 20, 'end': 22, 'type': 'asr_correction'}]}]},
        [SpeechSegment(85, 0., 3., text, .9, [])], 1, failures)
    assert not failures and value['cues'][0]['edits'] == []


@pytest.mark.parametrize('parts,reason', [
    # 2026-11-22 real DeepSeek run: no line over 14, but these seams read badly.
    (['现在终于轮到无敌的', '飞飞狐登场啦'], 'modifier_without_head'),
    (['这多少有些幽默我的', '好学生没成为和我一样的人'], 'modifier_without_head'),
    (['无论有多艰难让我们在这场', '本该给世人带来欢乐'], 'measure_without_noun'),
    (['你们希望唤醒太康上演一出', '漂亮的自取灭亡'], 'measure_without_noun'),
    (['这些都不重要因为', '在受罪付出我早已找到答案'], 'conjunction_at_line_end'),
    (['都不过是被他吞下', '后尚未消化的残渣'], 'localizer_opener'),
    (['如你们所见他', '对这片银河并无恶意'], 'subject_at_line_end'),
    (['后所有的食品将由', '工作人员发放'], 'preposition_at_line_end'),
])
def test_a_line_that_stops_on_a_dependent_word_goes_back_to_the_ai(parts, reason):
    from twobyteasr.subtitle_rules.ai_boundary_policy import dangling_edges, windows, HARD_KINDS
    quality = quality_of(''.join(parts))
    cut = len(parts[0])
    found = [x for x in dangling_edges(quality, [cut, quality.total]) if x['start'] == cut]
    assert [x['reason'] for x in found] == [reason]
    assert 'dangling_edge' not in HARD_KINDS and windows(quality, [cut, quality.total], advisory=True)


@pytest.mark.parametrize('parts', [
    ['我说过幸福的人是不会死的', '这怎么可能'],        # sentence-final 的
    ['相信你会喜欢的', '准备好了吗'],
    ['更早一些更早一些', '应该是好伟大'],             # adverbial 一些
    ['主角这杯敬你', '说说你的推理'],                 # object pronoun
    ['种各样的搭车客从', '不会让我感到无聊'],         # 从不
    ['在清醒的现实中', '让我们转起来'],
    ['整片星空都将为你歌唱啊', '他好爱啊'],
])
def test_complete_line_endings_are_not_flagged(parts):
    from twobyteasr.subtitle_rules.ai_boundary_policy import dangling_edges
    quality = quality_of(''.join(parts))
    assert not dangling_edges(quality, [len(parts[0]), quality.total])


@pytest.mark.parametrize('text,expected', [
    # 2026-11-22: the AI kept these seams after four rounds; the window now
    # carries a rule-scored reference it may adopt (it still decides).
    ('现在终于轮到无敌的飞飞狐登场啦！', ['现在终于轮到', '无敌的飞飞狐登场啦！']),
    ('这多少有些幽默我的好学生没成为和我一样的人', ['这多少有些幽默', '我的好学生没成为和我一样的人']),
    ('艾利欧说过别输给阿格尼丝所以这一局必秒他', ['艾利欧说过别输给阿格尼丝', '所以这一局必秒他']),
    ('虽然没弄清这艘船的动力学构造但照明总算恢复了', ['虽然没弄清这艘船的动力学构造', '但照明总算恢复了']),
])
def test_reference_answer_prefers_natural_seams(text, expected):
    from twobyteasr.subtitle_rules.grouping_quality_request import candidate_answer
    quality = quality_of(text)
    cuts = candidate_answer(quality, [quality.total], 0, quality.total, break_candidates(quality))
    assert pieces(quality, cuts) == expected


def test_window_carries_the_reference_and_a_kept_note_is_not_asked_again():
    text = '现在终于轮到无敌的飞飞狐登场啦！'
    quality = quality_of(text)
    bodies = []

    def complete(messages, **kwargs):
        body = json.loads(messages[-1]['content'])
        bodies.append(body)
        # The AI keeps 无敌的｜飞飞狐 every time.
        return json.dumps({'windows': [{'id': w['id'], 'boundaries': [9, w['total_length']]}
                                       for w in body['windows']]})

    result = retry_quality_windows(quality, [quality.total], [quality.total],
        provider=SimpleNamespace(complete=complete), snapshot=snapshot(), schema=GROUPING_SCHEMA,
        budget=QualityRetryBudget(), record=lambda *a, **k: None)
    assert bodies[0]['windows'][0]['reference_answer']['texts'] == ['现在终于轮到', '无敌的飞飞狐登场啦！']
    # Round 2 shows the new 的｜ note once; the AI keeps its answer; no third ask.
    assert len(bodies) == 2 and pieces(quality, result) == ['现在终于轮到无敌的', '飞飞狐登场啦！']
