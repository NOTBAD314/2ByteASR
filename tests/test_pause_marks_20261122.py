"""2026-11-22 (user): natural spaces/commas inside subtitles, and clause seams for line breaking.

Paid reruns of the reported 1 h stream (DeepSeek v4 flash) showed the model
punctuates these sentences well; the grouping then cuts at its commas.
"""
import json
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules import pause_marks as pm


@pytest.fixture(autouse=True)
def chinese():
    with language_scope('zh'), activate_runtime_context(RuntimeContext(task_language='zh', enable_domain_terms=False),
                                                        legacy=core):
        yield


def test_punctuation_becomes_pause_spaces_and_text_is_unchanged():
    text = '估计这把不能靠阿布了得靠那个迪莫了'
    offsets = pm.pauses_from_punctuated(text, '估计这把不能靠阿布了，得靠那个迪莫了。')
    assert offsets == [10]
    spaced, chosen = pm.apply_pauses(text, offsets)
    assert spaced == '估计这把不能靠阿布了 得靠那个迪莫了' and chosen == [10]
    # A changed character, digit or letter rejects the answer.
    assert pm.pauses_from_punctuated(text, '估计这把不能靠阿布，得靠那个迪莫') is None


def test_no_pause_inside_words_numbers_or_before_particles():
    text = '其实就该 150 走的真的'
    marks = pm.candidate_marks(text)
    spaced, _ = pm.apply_pauses(text, list(range(1, 12)), marks)
    assert spaced.replace(' ', '') == text.replace(' ', '')
    assert '15 0' not in spaced and '1 50' not in spaced
    assert all(not spaced[i:].startswith(' 的') for i in range(len(spaced)))


def fake_provider(answers, split_answers=None):
    calls = []

    def complete(messages, **kwargs):
        rows = json.loads(messages[1]['content'])['lines']
        calls.append((messages[0]['content'], rows))
        table = split_answers if messages[0]['content'] == pm.SPLIT_SYSTEM else answers
        return json.dumps(dict(lines=[dict(id=r['id'], text=(table or {}).get(r['text'], r['text'])) for r in rows]),
                          ensure_ascii=False)
    return SimpleNamespace(complete=complete), calls


def test_long_stretches_get_a_second_request_for_a_break():
    from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
    snapshot = SimpleNamespace(timeout_policy=TimeoutPolicy(), thinking_protocol='auto')
    first = '啊点了个筛管出来我们来对比一下啊'
    long = '我觉得可能是第一把赢的太顺利了啊'
    provider, calls = fake_provider({first: '啊，点了个筛管出来，我们来对比一下啊'},
                                    {long: '我觉得可能是第一把，赢的太顺利了啊'})
    rows = [SpeechSegment(1, 0, 3, first, .9, []), SpeechSegment(2, 3, 6, long, .9, []),
            SpeechSegment(3, 6, 7, '好的', .9, [])]
    events = []
    result = pm.mark_pause_spaces(rows, snapshot, provider=provider,
                                  record=lambda name, **data: events.append(dict(event=name, **data)))
    assert [r.text for r in result] == ['啊 点了个筛管出来 我们来对比一下啊', '我觉得可能是第一把 赢的太顺利了啊', '好的']
    assert len(calls) == 2 and calls[1][0] == pm.SPLIT_SYSTEM and [r['text'] for r in calls[1][1]] == [long]
    assert events[-1]['long_stretches'] == 1 and events[-1]['split_pauses'] == 1
    assert rows[0].text == first  # the input segments are not modified


def test_a_failed_request_leaves_sentences_as_they_were():
    from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
    snapshot = SimpleNamespace(timeout_policy=TimeoutPolicy(), thinking_protocol='auto')

    calls = []

    def broken(messages, **kwargs):
        calls.append(messages)
        raise RuntimeError('offline')
    rows = [SpeechSegment(1, 0, 3, '我觉得可能是第一把赢的太顺利了啊', .9, [])]
    result = pm.mark_pause_spaces(rows, snapshot, provider=SimpleNamespace(complete=broken))
    assert [r.text for r in result] == [rows[0].text]
    assert len(calls) == 1


def test_line_breaking_prefers_marked_pauses_and_avoids_dangling_words():
    from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
    from twobyteasr.subtitle_rules.grouping_quality_request import candidate_answer
    from twobyteasr.subtitle_rules.ai_boundary_policy import (break_candidates, select_model_boundary_domain,
                                                              dangling_edges)
    q = BoundaryQuality('我们一定是比他快 我们一定是先手')
    select_model_boundary_domain(q)
    answer = candidate_answer(q, [q.total], 0, q.total, break_candidates(q))
    assert q.index.pieces(answer) == ['我们一定是比他快 ', '我们一定是先手']
    for text, cut in [('因为这边他不管是开buff也好', 9), ('阿布现在是80级', 5), ('除非他带了一个什么防防御技能', 7),
                      ('他打死之后我们没人', 3), ('我觉得可能是第一把赢的太顺利了', 5)]:
        q = BoundaryQuality(text)
        assert [x['edge'] if 'edge' in x else x['start'] for x in dangling_edges(q, [cut, q.total])] == [cut], text


def test_a_full_width_comma_between_numbers_is_a_legal_cut():
    from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
    from twobyteasr.subtitle_rules.ai_boundary_policy import select_model_boundary_domain, unsplittable_lengths, inspect
    q = BoundaryQuality('87249，8724987249')
    select_model_boundary_domain(q)
    assert 5 in q.allowed
    assert not unsplittable_lengths(q, [x for x in inspect(q, [q.total]) if x['kind'] == 'length'])
    # 1,000 and 3.14 stay whole.
    q = BoundaryQuality('一共1,000个和3.14')
    select_model_boundary_domain(q)
    assert not {4, 5, 6} & set(q.allowed)
