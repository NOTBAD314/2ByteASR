"""2026-11-18 regressions from the 兔白字幕教学 job and its hand-corrected SRT.

Text-conserving samples only; the 1→E style text fixes are a separate test.
"""
import json
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
from twobyteasr.subtitle_rules.ai_boundary_policy import inspect, minimal_fallback
from twobyteasr.subtitle_rules.grouping_quality_request import QualityRetryBudget, retry_quality_windows


@pytest.fixture(autouse=True)
def chinese():
    with language_scope('zh'), activate_runtime_context(RuntimeContext(task_language='zh',enable_domain_terms=False),legacy=core):
        yield


def local(text):
    q = BoundaryQuality(text)
    cuts, receipts = minimal_fallback(q, [q.total])
    return q, q.index.pieces(cuts), receipts


def cut_inside(q, cuts_text, phrase):
    start = q.index.content.index(phrase)
    edges, cursor = set(), 0
    for piece in cuts_text:
        cursor += len(piece)
        edges.add(cursor)
    return any(start < edge < start+len(phrase) for edge in edges)


@pytest.mark.parametrize('text,phrase', [
    ('它能够自动听出不同的说话人每人一条字幕轨道', '说话人'),
    ('而按WASD也能快速移动到上一条或下一条字幕', '上一条'),
    ('好接下来是这期的重头戏字幕工作台', '字幕工作台'),
    ('Q和W就是我最常用的两个快捷键', '两个快捷键'),
    ('然后改成真名换个颜色也可以标出谁是主播', '也可以'),
    ('如果帮助到你的话一键三连支持一下我们下期见', '一键三连'),
])
def test_local_fallback_keeps_phrases_whole(text, phrase):
    q, pieces, receipts = local(text)
    assert ''.join(pieces) == text
    assert all(len(p) <= q.max_chars for p in pieces)
    assert not cut_inside(q, pieces, phrase), pieces
    assert receipts and receipts[0]['origin'] == 'local_minimal_fallback'


def test_object_is_not_left_as_a_two_character_tail():
    q, pieces, _ = local('主力转写负责把听到的话做成字幕')
    assert pieces[-1] != '字幕' and all(len(p) > 2 for p in pieces), pieces


def test_gate_sends_first_round_ai_dependency_cuts_back_for_review():
    q = BoundaryQuality('都一直在更新记得在主页检查更新')
    cut = len('都一直在更新记得')
    assert not inspect(q, [cut, q.total])  # not a hard failure
    advisory = inspect(q, [cut, q.total], advisory=True)
    assert any(i['kind'] == 'word_or_dependency_split' and i['start'] == cut for i in advisory)
    # jieba tags 更新 as an adverb, so the corrected cut carries its own
    # advisory flag; the retry accepts an AI answer that adds no risk.
    assert all(i['start'] != cut for i in inspect(q, [len('都一直在更新'), q.total], advisory=True))
    q = BoundaryQuality('如果帮助到你的话一键三连支持一下我们下期见')
    assert any(i['kind'] == 'semantic_boundary' for i in inspect(q, [len('如果帮助到你的话一键'), q.total]))


def test_fallback_receipt_says_why_ai_did_not_fix_the_window():
    q = BoundaryQuality('它能够自动听出不同的说话人每人一条字幕轨道')
    _, receipts = minimal_fallback(q, [q.total], statuses={(0, q.total): 'not_allocated'})
    assert receipts[0]['reason'] == 'retry_budget_not_allocated'
    _, receipts = minimal_fallback(q, [q.total])
    assert receipts[0]['reason'] == 'retry_not_attempted'


def test_all_failed_windows_of_a_batch_share_one_request():
    first, second = '它能够自动听出不同的说话人每人一条字幕轨道', '而按WASD也能快速移动到上一条或下一条字幕'
    q = BoundaryQuality(first+second)
    calls = []

    def complete(messages, **options):
        body = json.loads(messages[1]['content'])
        calls.append(body)
        answers = []
        for window in body['windows']:
            text = window['source_text']
            cut = text.index('每人') if '每人' in text else text.index('到上一条')
            answers.append(dict(id=window['id'], boundaries=[cut, window['total_length']]))
        return json.dumps(dict(windows=answers), ensure_ascii=False)

    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    snapshot = resolve_provider_snapshot({'models':{'ai_service':'custom','provider_profiles':{
        'custom':{'base_url':'http://127.0.0.1:1/v1','model':'offline'}}}})
    statuses, events = {}, []
    result = retry_quality_windows(q, [len(first), q.total], [len(first), q.total],
        provider=SimpleNamespace(complete=complete), snapshot=snapshot, schema={}, budget=QualityRetryBudget(),
        record=lambda name, **data: events.append(dict(event=name, **data)), batch_index=6, statuses=statuses)
    assert len(calls) == 1 and len(calls[0]['windows']) == 2
    assert q.index.pieces(result) == ['它能够自动听出不同的说话人', '每人一条字幕轨道',
                                      '而按WASD也能快速移动', '到上一条或下一条字幕']
    assert set(statuses.values()) == {'improved'}
    assert not inspect(q, result)


def test_window_without_budget_is_recorded_as_not_allocated():
    q = BoundaryQuality('它能够自动听出不同的说话人每人一条字幕轨道')
    statuses, events = {}, []
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    snapshot = resolve_provider_snapshot({'models':{'ai_service':'custom','provider_profiles':{
        'custom':{'base_url':'http://127.0.0.1:1/v1','model':'offline'}}}})
    result = retry_quality_windows(q, [q.total], [q.total], provider=SimpleNamespace(complete=None),
        snapshot=snapshot, schema={}, budget=QualityRetryBudget(requests=0),
        record=lambda name, **data: events.append(dict(event=name, **data)), batch_index=7, statuses=statuses)
    assert result == [q.total] and set(statuses.values()) == {'not_allocated'}
    retry = next(e for e in events if e['event'] == 'grouping_quality_retry')
    assert not retry['request_dispatched'] and retry['budget_refusal'] == 'retry_disabled'


def test_ai_fix_of_clause_taking_verb_is_adopted():
    text = '都一直在更新记得在主页检查更新'
    q = BoundaryQuality(text)
    wrong, right = len('都一直在更新记得'), len('都一直在更新')
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    snapshot = resolve_provider_snapshot({'models':{'ai_service':'custom','provider_profiles':{
        'custom':{'base_url':'http://127.0.0.1:1/v1','model':'offline'}}}})
    reply = lambda messages, **k: json.dumps(dict(windows=[dict(id=1, boundaries=[right, q.total])]))
    statuses = {}
    result = retry_quality_windows(q, [wrong, q.total], [wrong, q.total], provider=SimpleNamespace(complete=reply),
        snapshot=snapshot, schema={}, budget=QualityRetryBudget(), record=lambda *a, **k: None,
        batch_index=8, statuses=statuses)
    assert result == [right, q.total] and set(statuses.values()) == {'improved'}
