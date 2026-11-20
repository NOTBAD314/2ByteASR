"""2026-11-19: targeted AI corrections may not make a window worse.

Before/after pairs are the reported job's own grouping_quality_retry
receipts (18 corrections, every one logged "improved").
"""
import json
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
from twobyteasr.subtitle_rules.grouping_quality_request import (
    QualityRetryBudget, correction_regression, retry_quality_windows)
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot


@pytest.fixture(autouse=True)
def chinese():
    with language_scope('zh'), activate_runtime_context(RuntimeContext(task_language='zh', enable_domain_terms=False),
                                                        legacy=core):
        yield


def cuts(parts):
    out, total = [], 0
    for part in parts:
        total += len(part)
        out.append(total)
    return out


@pytest.mark.parametrize('before,after', [
    (['其他的话都是可以翻了', '一千二之后'], ['其他的话都是可以翻', '了一千二之后']),
    (['还有两个弱兵的', '花衣蝶和'], ['还有两个弱兵', '的花衣蝶和']),
    (['哎', '那不对那不对了', '没事没事'], ['哎', '那不对那不对', '了没事没事']),
    (['火羽是可以把', '风后直接防死的', '单防的'], ['火羽是可以把风后', '直接防死', '的单防的']),
])
def test_particle_opening_a_line_is_a_regression(before, after):
    text = ''.join(before)
    q = BoundaryQuality(text)
    assert correction_regression(q, cuts(before), cuts(after), 0, q.total) == 'new_syntactic_damage'


def test_two_lines_turned_into_five_is_a_regression():
    before = ['但是圣剑一个', '涅河拖拉机直接给你全轴飞了']
    after = ['但是圣剑', '一个涅河', '拖拉机', '直接给你', '全轴飞了']
    q = BoundaryQuality(''.join(before))
    assert correction_regression(q, cuts(before), cuts(after), 0, q.total) == 'over_fragmented'
    # An over-long single line may become two (or three) lines, not four.
    long = '就算晒了我感觉他吃我暴风雪也不赚'
    q = BoundaryQuality(long)
    assert correction_regression(q, [q.total], cuts(['就算晒了', '我感觉他吃我暴风雪也不赚']), 0, q.total) == ''
    assert correction_regression(q, [q.total], cuts(['就算晒了我', '感觉他吃我', '暴风雪', '也不赚']),
                                 0, q.total) == 'over_fragmented'


@pytest.mark.parametrize('before,after', [
    (['我们直接', '乱打吧'], ['我们直接乱打吧']),
    (['这是不是吞', '吞灼烧了'], ['这是不是', '吞吞灼烧了']),
    (['看一下风墙'], ['看一下', '风墙']),
])
def test_merges_and_plain_splits_stay_allowed(before, after):
    q = BoundaryQuality(''.join(before).replace(' ', ''))
    b, a = cuts([p.replace(' ', '') for p in before]), cuts([p.replace(' ', '') for p in after])
    assert correction_regression(q, b, a, 0, q.total) == ''


def test_retry_keeps_the_model_answer_when_the_correction_regresses():
    from twobyteasr.subtitle_rules.grouping import GROUPING_SCHEMA
    text = '其他的话都是可以翻了一千二之后我们看一下'
    q = BoundaryQuality(text)
    original = [15, q.total]  # 15 > 14: a length issue sends the window back
    q.max_chars = 14
    events = []

    def complete(messages, **kwargs):
        windows = json.loads(messages[1]['content'])['windows']
        return json.dumps({'windows': [dict(id=w['id'], boundaries=[9, w['total_length']]) for w in windows]})

    snapshot = resolve_provider_snapshot({'models': {'ai_service': 'custom', 'provider_profiles': {
        'custom': {'base_url': 'http://127.0.0.1:1/v1', 'model': 'offline'}}}})
    result = retry_quality_windows(q, original, original, provider=SimpleNamespace(complete=complete),
        snapshot=snapshot, schema=GROUPING_SCHEMA, budget=QualityRetryBudget(),
        record=lambda name, **data: events.append(dict(event=name, **data)))
    retries = [e for e in events if e['event'] == 'grouping_quality_retry' and e['request_dispatched']]
    assert retries and not any(e['improved'] for e in retries)
    assert {e['reason'] for e in retries} == {'new_syntactic_damage'}
    assert 9 not in result
