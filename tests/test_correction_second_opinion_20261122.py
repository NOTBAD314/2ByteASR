"""2026-11-22: rejected AI term edits get a blind two-order second opinion."""
import json
from types import SimpleNamespace

import subtitle_core  # noqa: F401 - initializes the legacy facade
from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules import correction_verification as cv

SNAPSHOT = SimpleNamespace(timeout_policy=TimeoutPolicy(), thinking_protocol='auto')


def segment(number, text, *edits):
    row = SpeechSegment(number, number, number + 1, text, .9, [])
    row.caption_arbitration = {'terminology_polish': {'rejected_edits': list(edits), 'accepted_edits': []}}
    return row


def edit(text, source, target, rule='catalog_without_local_support'):
    start = text.find(source)
    return {'from': source, 'to': target, 'start': start, 'end': start + len(source), 'rule_id': rule}


def judge(prefer_corrected):
    """A fake model: prefers the version that contains a word in ``prefer_corrected``."""
    calls = []

    def complete(messages, **kwargs):
        items = json.loads(messages[1]['content'])['items']
        calls.append(items)
        answers = []
        for item in items:
            a_good = any(word in item['A'] for word in prefer_corrected)
            b_good = any(word in item['B'] for word in prefer_corrected)
            answers.append(dict(id=item['id'], reason='模拟独立表决', better='A' if a_good and not b_good else 'B'))
        return json.dumps(dict(answers=answers), ensure_ascii=False)
    return SimpleNamespace(complete=complete), calls


def test_a_correction_that_wins_both_orders_only_changes_candidate_metadata():
    rows = [segment(1, '可以直接那个给他手里画好了', edit('可以直接那个给他手里画好了', '手里画', '首领化')),
            segment(2, '他们已经没有魔攻精灵了', edit('他们已经没有魔攻精灵了', '精灵', '降灵'))]
    provider, calls = judge({'首领化', '精灵'})
    assert cv.verify_rejected_edits(rows, SNAPSHOT, provider=provider) == 1
    assert rows[0].text == '可以直接那个给他手里画好了'
    receipt = rows[0].caption_arbitration['terminology_polish']
    assert receipt['rejected_edits'] and not receipt['accepted_edits']
    verdict, = receipt['second_opinion_verdicts']
    assert verdict['decision'] == 'candidate'
    assert len({row['decision'] for row in verdict['votes']}) == 1
    assert rows[1].text == '他们已经没有魔攻精灵了'
    assert len(calls) == 4 and calls[0][0]['A'] == calls[1][0]['B']  # two readings, both orders


def test_position_bias_alone_never_applies_an_edit():
    rows = [segment(1, '这里不加速懂了吗', edit('这里不加速懂了吗', '速懂', '速冻'))]

    def always_b(messages, **kwargs):
        items = json.loads(messages[1]['content'])['items']
        return json.dumps(dict(answers=[dict(id=i['id'], better='B', reason='模拟位置偏差') for i in items]))
    assert cv.verify_rejected_edits(rows, SNAPSHOT, provider=SimpleNamespace(complete=always_b)) == 0
    assert rows[0].text == '这里不加速懂了吗'


def test_interjections_and_other_rules_are_not_sent():
    rows = [segment(1, '我靠太痛了', edit('我靠太痛了', '我靠', '我操', 'local_difference_without_two_sources')),
            segment(2, '我们切圣剑', edit('我们切圣剑', '圣剑', '盛剑', 'confirmed_term_protected')),
            segment(3, '我们切火羽', edit('我们切火羽', '火羽', '水羽', 'unknown_or_mismatched_candidate_id'))]
    provider, calls = judge({'我操', '盛剑'})
    assert cv.verify_rejected_edits(rows, SNAPSHOT, provider=provider) == 0 and not calls


def test_a_failed_request_applies_nothing():
    rows = [segment(1, '就三废三废', edit('就三废三废', '三废', '三费', 'local_difference_without_two_sources'))]

    def broken(messages, **kwargs):
        raise RuntimeError('offline')
    events = []
    assert cv.verify_rejected_edits(rows, SNAPSHOT, provider=SimpleNamespace(complete=broken),
                                    record=lambda name, **data: events.append(name)) == 0
    assert rows[0].text == '就三废三废' and 'correction_second_opinion_failed' in events
