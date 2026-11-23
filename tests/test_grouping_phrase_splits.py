"""2026-11-22 (user): a 4 h stream, Qwen Audio 3.1 + DeepSeek flash grouping.

1,370 window corrections were logged "improved" while they split phrases no
local check saw. Each fixed an over-long line, so the gate let them through.
The pairs below are that job's own receipts: the cut the AI made, and the cut
a reader expects.
"""
import pytest
import subtitle_core as core
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.grouping_quality import BoundaryQuality
from twobyteasr.subtitle_rules.ai_boundary_policy import (
    HARD_KINDS, break_candidates, inspect, snap_offset_errors)


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


def reasons(parts):
    q = BoundaryQuality(''.join(parts))
    return {x.get('reason') for x in inspect(q, cuts(parts)) if x['kind'] in HARD_KINDS}


@pytest.mark.parametrize('bad,good,reason', [
    (['当时是这样您好您所', '拨打的号码是空号请查证后再拨'], ['当时是这样', '您好您所拨打的号码是空号', '请查证后再拨'],
     'suo_before_verb'),
    (['红包中了会', '有人在两天之内私信你的'], ['红包中了', '会有人在两天之内私信你的'], 'modal_at_line_end'),
    (['在看猫眼应该是住', '在对门的人要搬走了吗'], ['在看猫眼', '应该是住在对门的人要搬走了吗'], 'verb_and_place_split'),
    (['一直联系不上', '你我担心你要是我不是'], ['一直联系不上你', '我担心你要是我不是'], 'object_pronoun_split'),
    (['我跟你爸想去看看', '你你愿不愿意回复'], ['我跟你爸想去看看你', '你愿不愿意回复'], 'object_pronoun_split'),
    (['这里是梦大家', '讨论的时候'], ['这里是梦', '大家讨论的时候'], 'subject_at_line_end'),
    (['然后我挂断了电话记得过了', '段时间有电话打来'], ['然后我挂断了电话', '记得过了段时间有电话打来'], 'measure_opener'),
    (['自己当前杀不', '掉的这个事实'], ['自己当前', '杀不掉的这个事实'], 'potential_complement_split'),
])
def test_phrase_splits_from_the_job_are_hard_issues(bad, good, reason):
    assert reason in reasons(bad)
    assert not reasons(good)


@pytest.mark.parametrize('parts', [
    ['我不会', '你教教我'],              # a negated modal ends its clause
    ['我觉得', '不上班也行'],            # 不 + 上班, not a complement
    ['关于这个', '我这边有一些想法'],     # 这个 then a new clause
    ['后来还是提到了这个', '一直没想通啊'],
    ['欢迎来到北城直播间啊大家', '晚上好'],
])
def test_ordinary_clause_cuts_stay_clean(parts):
    assert not reasons(parts)


def test_determiner_still_waits_for_its_noun():
    assert 'dependent_adjacent_text' in reasons(['想炸单了就跟那个', '代码'])


def test_split_phrase_positions_are_not_offered_as_marks():
    q = BoundaryQuality('一直联系不上你我担心你要是我不是')
    marks = break_candidates(q)
    assert 6 not in marks and 7 in marks      # 联系不上｜你 no, 联系不上你｜我 yes
    q = BoundaryQuality('自己当前杀不掉的这个事实')
    assert 5 not in break_candidates(q) and 6 not in break_candidates(q)


@pytest.mark.parametrize('bad,expected', [
    (['红包中了会', '有人在两天之内私信你的'], ['红包中了', '会有人在两天之内私信你的']),
    (['一直联系不上', '你我担心你要是我不是'], ['一直联系不上你', '我担心你要是我不是']),
    (['我跟你爸想去看看', '你你愿不愿意回复'], ['我跟你爸想去看看你', '你愿不愿意回复']),
])
def test_a_cut_one_word_off_moves_to_the_phrase_edge(bad, expected):
    q = BoundaryQuality(''.join(bad))
    result, moves = snap_offset_errors(q, cuts(bad))
    assert result == cuts(expected) and moves


@pytest.mark.parametrize('bad', [
    ['在看猫眼应该是住', '在对门的人要搬走了吗'],     # not 住在对｜门
    ['但是我们两个也没办法永远陪着', '你如果你愿意的话'],  # not 陪｜着你
])
def test_a_move_never_lands_inside_a_word_or_before_a_particle(bad):
    q = BoundaryQuality(''.join(bad))
    result, _ = snap_offset_errors(q, cuts(bad))
    content = q.index.content
    for edge in result[:-1]:
        assert content[edge] not in '着了的'
        assert all(not t['start'] < edge < t['end'] for t in q.tagged_tokens)


def test_the_retry_gate_rejects_a_length_fix_that_splits_a_phrase():
    # The window had one hard issue (23 characters); the answer had one too.
    text = '当时是这样您好您所拨打的号码是空号请查证后再拨'
    q = BoundaryQuality(text)
    old = [x for x in inspect(q, [q.total]) if x['kind'] in HARD_KINDS]
    new = [x for x in inspect(q, cuts(['当时是这样您好您所', '拨打的号码是空号请查证后再拨'])) if x['kind'] in HARD_KINDS]
    assert len(old) == 1 and len(new) >= len(old)
