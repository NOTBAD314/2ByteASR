"""2026-11-22: AI subtitle editor pass, kept only when a blind two-order judge prefers it."""
import json
from types import SimpleNamespace

import pytest
import subtitle_core as core
from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
from twobyteasr.subtitle_rules import grouping_editor as ed

SNAPSHOT = SimpleNamespace(timeout_policy=TimeoutPolicy(), thinking_protocol='auto')


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


def test_preferences_round_trip_and_separate_grouping_cache(tmp_path):
    from twobyteasr.recognition.cache import cache_stage_signature
    from twobyteasr.recognition.run_context import get_runtime_context
    from twobyteasr.recognition.streaming_recognition import grouping_rule_identity
    from twobyteasr.storage.settings import load_runtime_settings, save_runtime_settings

    context = get_runtime_context()
    settings, _, _ = load_runtime_settings(tmp_path)
    context.asr_settings_snapshot = settings
    assert not ed.enabled(context)
    assert settings["switches"]["background_lyrics"] is True
    previous = cache_stage_signature("grouped")
    partial = grouping_rule_identity(core, context)

    settings["switches"].update(grouping_ai_editor=True, background_lyrics=False)
    save_runtime_settings(settings, tmp_path)
    context.asr_settings_snapshot, _, _ = load_runtime_settings(tmp_path)
    assert ed.enabled(context)
    assert context.asr_settings_snapshot["switches"]["background_lyrics"] is False
    assert cache_stage_signature("grouped") != previous
    assert grouping_rule_identity(core, context) != partial


def provider(edit, judge_first='B', judge_second='A'):
    calls = []

    def complete(messages, **kwargs):
        body = json.loads(messages[1]['content'])
        calls.append('editor' if 'groups' in body else 'judge')
        if 'groups' in body:
            return json.dumps(dict(groups=[dict(id=g['id'], lines=edit(g['lines'])) for g in body['groups']]),
                              ensure_ascii=False)
        # The second judge call shows the pair in the other order.
        answer = judge_first if calls.count('judge') % 2 else judge_second
        return json.dumps(dict(answers=[dict(id=p['id'], better=answer) for p in body['pairs']]))
    return SimpleNamespace(complete=complete), calls


def test_a_judged_improvement_is_kept():
    parts = ['我们已经是超速全场了他', '只有80速啊']
    q = BoundaryQuality(''.join(parts))
    fixed = ['我们已经是超速全场了', '他只有80速啊']
    prov, _ = provider(lambda lines: fixed)
    result = ed.edit_lines(q, cuts(parts), provider=prov, snapshot=SNAPSHOT, rounds=1)
    assert q.index.pieces(result) == fixed


def test_a_change_the_judge_does_not_prefer_both_ways_is_dropped():
    parts = ['我也没看懂他为什么要等价交换']
    q = BoundaryQuality(''.join(parts))
    prov, _ = provider(lambda lines: ['我也没看懂他为什么', '要等价交换'], judge_first='B', judge_second='B')
    assert ed.edit_lines(q, cuts(parts), provider=prov, snapshot=SNAPSHOT, rounds=1) == [q.total]


def test_changed_text_or_an_overlong_line_is_rejected_before_judging():
    parts = ['好那这里我们还地刺去', '阻止他回能还是聚盐呢']
    q = BoundaryQuality(''.join(parts))
    prov, calls = provider(lambda lines: ['好那这里我们还地刺去阻止他回能', '还是聚盐呢'])
    assert ed.edit_lines(q, cuts(parts), provider=prov, snapshot=SNAPSHOT, rounds=1) == cuts(parts)
    prov, calls = provider(lambda lines: ['好那这里我们还地刺去', '阻止他回能还是盐呢'])
    assert ed.edit_lines(q, cuts(parts), provider=prov, snapshot=SNAPSHOT, rounds=1) == cuts(parts)
    assert len(calls) == 1  # no judge request for rejected proposals


def test_protected_cuts_are_group_edges_and_never_move():
    q = BoundaryQuality('好的我们走吧你先上', required={5})
    seen = []

    def edit(lines):
        seen.append(list(lines))
        return [''.join(lines)]
    prov, _ = provider(edit)
    result = ed.edit_lines(q, [5, q.total], provider=prov, snapshot=SNAPSHOT, rounds=1)
    assert 5 in result and all(''.join(g) in ('好的我们走', '吧你先上') for g in seen)


def test_a_failed_request_keeps_the_lines():
    def broken(messages, **kwargs):
        raise RuntimeError('offline')
    q = BoundaryQuality('我们已经是超速全场了他只有80速啊')
    events = []
    assert ed.edit_lines(q, [11, q.total], provider=SimpleNamespace(complete=broken), snapshot=SNAPSHOT,
                         record=lambda name, **data: events.append(name)) == [11, q.total]
    assert 'grouping_editor_failed' in events
