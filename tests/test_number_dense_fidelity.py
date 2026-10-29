"""2026-10-28 (Mac user, 98.5-minute cloze lecture full of numbers): the whole
file failed with 「字幕保真检查未通过：S00 4096.460s」.

The final check read numbers line by line, and a Chinese numeral only counts
with its context (到/第 before it, 个/分 after it). A line that ran across two
recognition segments - 「看到」 at the end of one, 「十九题」 at the start of the
next - read 19 where the segments read nothing, so the check called the turn
changed although no character moved and no number was cut. The rebuild that
followed then failed on timing alone: lines padded to the 0.35 s minimum ran
into the next one, and the character-share fallback gave sparse lines over 5 s.
"""
import random
from types import SimpleNamespace

import pytest

import subtitle_core as legacy
from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.number_fidelity import (cues_read_source_numbers, cuts_inside_numbers,
                                                       numeric_event_values)
from twobyteasr.subtitle_rules.subtitle_fidelity import recover_final_content
from twobyteasr.subtitle_rules.text_rules import clean_subtitle_text, content_exact


def _segment(segment_id, start, text, step=0.2, speaker='S00'):
    end = start + len(content_exact(text)) * step
    return SpeechSegment(segment_id=segment_id, start=start, end=round(end, 3), text=text, confidence=0.9,
                         words=[], speaker=speaker)


def _cue(start, end, text, speaker='S00'):
    return SubtitleCue(0, start, end, text, speaker=speaker)


class _Events:
    def __init__(self):
        self.rows = []

    def __call__(self, name, **fields):
        self.rows.append((name, fields))

    def named(self, name):
        return [fields for event, fields in self.rows if event == name]


@pytest.fixture
def events(monkeypatch):
    recorder = _Events()
    monkeypatch.setattr(legacy, 'record_run_event', recorder)
    return recorder


def test_a_line_across_two_segments_that_reads_a_number_is_kept(events):
    first = _segment(1, 10.0, '好我们接下来看到')
    second = _segment(2, first.end + 0.1, '十九题这个空选什么')
    # Neither segment reads a number on its own; 「看到十九题」 reads 19.
    assert numeric_event_values(first.text) + numeric_event_values(second.text) == ()
    assert numeric_event_values('看到十九题') == ('19',)
    finalized = [_cue(10.0, 11.2, '好我们接下来'), _cue(11.2, second.start + 0.6, '看到十九题'),
                 _cue(second.start + 0.6, second.end, '这个空选什么')]
    with language_scope('zh'):
        result = recover_final_content(finalized, list(finalized), [first, second], [], legacy)
    assert result == finalized
    assert [c.text for c in result] == ['好我们接下来', '看到十九题', '这个空选什么']
    assert not events.named('final_content_conservation_recovery')
    assert events.named('final_content_number_context_only')[0]['actual_numbers'] == ('19',)


def test_a_line_that_cuts_a_number_in_two_is_still_rebuilt(events):
    segment = _segment(1, 10.0, '我们一共有二十五个空')
    finalized = [_cue(10.0, 11.4, '我们一共有二十'), _cue(11.4, segment.end, '五个空')]
    assert cuts_inside_numbers([segment], finalized)
    with language_scope('zh'):
        result = recover_final_content(finalized, list(finalized), [segment], [], legacy)
    assert any('二十五' in c.text for c in result)
    assert events.named('final_content_conservation_recovery')


@pytest.mark.parametrize('left,right', [
    ('我们一共有二十', '五个空'), ('比分是2', '0'), ('涨了百分', '之二十'), ('涨了百分之', '二十'),
    ('比例是二比', '三'), ('五点', '三十分开始'), ('来了十', '几个人'), ('分数是1.', '5分'),
])
def test_cuts_inside_numbers(left, right):
    segment = _segment(1, 0.0, left + right)
    cues = [_cue(0, 1, left), _cue(1, 2, right)]
    assert cuts_inside_numbers([segment], cues)


@pytest.mark.parametrize('left,right', [
    ('这个东西一万', '金币'), ('我们看到', '十九题'), ('我们', '两波'), ('还剩', '一条命'), ('第', '二阶段'),
])
def test_cuts_beside_numbers(left, right):
    segment = _segment(1, 0.0, left + right)
    assert not cuts_inside_numbers([segment], [_cue(0, 1, left), _cue(1, 2, right)])


@pytest.mark.parametrize('texts,lines,kept', [
    # 看到 | 十九题 across two segments: the joined passage reads 19, so may the line.
    (('好我们接下来看到', '十九题这个空选什么'), ('好我们接下来', '看到十九题', '这个空选什么'), True),
    # The same cut inside one segment loses a number the passage reads.
    (('我们看第十九题',), ('我们看第', '十九题'), False),
    (('这个东西一万金币',), ('这个东西一万', '金币'), False),
    # A lone 两 reads 2 where the passage reads no number (2026-10-23).
    (('这把我们两波就打完了',), ('这把我们', '两', '波就打完了'), False),
    # Two numbers of two segments glued into one line read as one number
    # (packaged SenseVoice run, 2026-10-28: 1112134 | 50% -> 111213450%).
    (('都选A前总后分1112134', '50%的同学选错了'), ('都选A', '前总后分111213450%的同学', '选错了'), False),
    (('一共有二十', '五个空'), ('一共有二十五个空',), False),
    # A segment edge the line keeps reads as the segment does.
    (('他说二十', '二十地数'), ('他说二十', '二十地数'), True),
    (('他说二十', '二十地数'), ('他说', '二十二十地数'), True),
])
def test_lines_read_the_numbers_of_the_passage(texts, lines, kept):
    segments, start = [], 0.0
    for index, text in enumerate(texts):
        segments.append(_segment(index + 1, start, text))
        start = segments[-1].end + 0.1
    cues = [_cue(index, index + 1, text) for index, text in enumerate(lines)]
    assert cues_read_source_numbers(segments, cues) is kept


def test_a_segment_edge_is_never_inside_a_number():
    first, second = _segment(1, 0.0, '他说二十'), _segment(2, 1.0, '二十地数')
    assert not cuts_inside_numbers([first, second], [_cue(0, 1, '他说二十'), _cue(1, 2, '二十地数')])


def test_rebuild_with_only_timing_problems_shortens_lines_instead_of_failing(events, monkeypatch):
    """The local rebuild's lines are right, but one runs 0.06 s into the next and
    the other lasts 6.2 s; spreading by character share gives 6.3 s."""
    first = _segment(1, 100.0, '这道题我们选A然后')
    second = _segment(2, first.end + 0.05, '看到十九题我们选B', step=0.7)
    # 十｜九 really cuts a number, so the turn has to be rebuilt.
    finalized = [_cue(first.start, first.end, '这道题我们选A然后'), _cue(second.start, second.start + 2.1, '看到十'),
                 _cue(second.start + 2.1, second.end, '九题我们选B')]

    def rebuild(source, tokens):
        return [_cue(first.start, first.end + 0.11, '这道题我们选A然后'),
                _cue(second.start, second.start + 6.2, '看到十九题我们选B')]

    monkeypatch.setattr(legacy, 'build_local_source_cues', rebuild)
    with language_scope('zh'):
        result = sorted(recover_final_content(finalized, list(finalized), [first, second], [], legacy),
                        key=lambda c: c.start)
    assert [c.text for c in result] == ['这道题我们选A然后', '看到十九题我们选B']
    assert result[0].end == pytest.approx(second.start)
    assert result[1].start == pytest.approx(second.start)
    assert result[1].end - result[1].start <= 5.0 + 1e-9


# A seeded slice of tmp/number-fidelity-20261028/probe/fuzz_final_check.py:
# number-dense lecture turns with sparse timing, a few characters the aligner
# stretched over a pause and some segments without character evidence. Before
# the fix 24 of 150 such turns failed the whole file; seeds 7, 9, 10 and 13 did.
PHRASES = [
    '第十九题', '一个', '两个', '十八十九二十', '二零一五年', '英一', '一一的孩子', '选A', '三十分',
    '百分之五十', '四十个', '一千', '九十', '第一段第二句', '十个空', '五一', '十九', '一二三四五',
    '前总后分', '我们来看', '这道题', '对吧', '然后呢', '所以', '答案是', '到', '加', '等于', '第',
    '还剩', '一共', '个', '题', '分', '那么', '大家注意', '二十', '二十一', '十一十二', '一下',
    '这个', '就是说', '其实', '同学们', '因为', '一点', '十年', '三四个', '两三', '第二十题',
    '七八', '十五', '一共二十个空', '每个空零点五分', '一百', '一十', '二十二十', '九', '一',
    '第10题', '15分', '1', '10', '40个', '30', '看到', '11', '12', '13', '14', '十九十', '一一十九',
]


def _lecture_turn(seed):
    rng = random.Random(seed)
    segments, tokens, t = [], [], 4096.46
    for index in range(rng.randint(2, 6)):
        text = ''
        length = rng.randint(6, 90)
        while len(content_exact(text)) < length:
            text += rng.choice(PHRASES)
        step, rows, tt = rng.uniform(0.12, 0.30), [], t
        for char in content_exact(text):
            duration = step * rng.uniform(0.6, 1.4)
            if rng.random() < 0.03:
                tt += rng.uniform(0.3, 1.5)
            if rng.random() < 0.02:
                duration = rng.uniform(4.0, 8.0)
            rows.append(dict(start=round(tt, 3), end=round(tt + duration * 0.9, 3), text=char, confidence=0.9))
            tt += duration
        segments.append(SpeechSegment(segment_id=index + 1, start=rows[0]['start'], end=rows[-1]['end'],
                                      text=text, confidence=0.9, words=[], speaker='S00'))
        if not rng.random() < 0.15:
            tokens.extend(rows)
        t = tt + rng.uniform(0.05, 1.5)
    # Cloud line breaking cuts through the joined turn, ignoring segment edges.
    chars = [(row['text'], row['start'], row['end']) for row in tokens]
    cues, i = [], 0
    while i < len(chars):
        piece = chars[i:i + min(len(chars) - i, rng.randint(4, 14))]
        while len(piece) > 1 and piece[-1][2] - piece[0][1] > 5.0:
            piece = piece[:-1]
        cues.append(_cue(piece[0][1], piece[-1][2], clean_subtitle_text(''.join(c for c, _, _ in piece))))
        i += len(piece)
    return segments, tokens, cues


def _assert_safe(cues, segments, *, rebuilt):
    cues = sorted(cues, key=lambda c: (c.start, c.end))
    assert content_exact(''.join(c.text for c in cues)) == content_exact(''.join(s.text for s in segments))
    same_reading = (tuple(v for c in cues for v in numeric_event_values(c.text))
                    == tuple(v for s in segments for v in numeric_event_values(s.text)))
    if rebuilt:
        assert not cuts_inside_numbers(segments, cues)
    # Earlier lines may keep a cut inside a numeral run only where every line
    # still reads the source's numbers (as before 2026-10-28).
    assert same_reading or cues_read_source_numbers(segments, cues)
    assert all(0 < c.end - c.start <= 5.05 and legacy.display_length(c.text) <= 16 for c in cues)
    assert all(b.start >= a.end - 0.001 for a, b in zip(cues, cues[1:]))
    assert segments[0].start - 0.15 <= cues[0].start and cues[-1].end <= max(s.end for s in segments) + 0.05


@pytest.mark.parametrize('seed', [7, 9, 10, 13, 0, 1, 2, 3])
def test_number_dense_lecture_turns_never_fail_the_file(seed):
    segments, tokens, cues = _lecture_turn(seed)
    with language_scope('zh'):
        _assert_safe(recover_final_content([], [], segments, tokens, legacy), segments, rebuilt=True)
        _assert_safe(recover_final_content(cues, list(cues), segments, tokens, legacy), segments, rebuilt=False)
