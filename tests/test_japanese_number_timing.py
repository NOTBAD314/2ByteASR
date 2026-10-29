"""2026-10-16 (user: 87 s Japanese ``jianz.mp4`` failed with "本地修复的文字与时间单元不一致").

The AI proofreading finish step formatted Chinese numerals in a Japanese task
(一万→10000, and 十分 "enough" →10分). Rebuilding character timing after that
counted only kanji and ASCII, so the kana got no time (47 characters, 22 times);
AI line breaking fell back and the final local re-cut of the long line failed.
The lines below are the user's three formatted lines from their job log.
"""
import pytest

import subtitle_core as legacy  # noqa: F401  (loads the core before the timing helpers)
from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
from twobyteasr.subtitle_rules.number_fidelity import format_segment
from twobyteasr.subtitle_rules.segmentation_alignment import segment_content_timeline
from twobyteasr.subtitle_rules.text_rules import content_only, display_length
from twobyteasr.subtitle_rules.timing import build_local_source_cues
from tests.test_stage9_cache_and_budget import context  # noqa: F401  (fixture)

USER_LINES = [
    'いやいや一万倍一万倍はいいよ 一万になったらなんかビリビリで唯一の日本Vになる',
    '十分 十分いただいてるからこれ 六千っていうだけでも本当に十分どころか',
    'なんでなんでそんな申し訳ない気持ちになってるのって そんなことないよ 見てくれるだけ十分だし',
]


def _segment(text, step=0.1):
    words, time = [], 1.0
    for char in text:
        if content_only(char):
            words.append(WordUnit(time, time + step, char, 0.9))
            time += step
    return SpeechSegment(1, 1.0, time, text, 0.9, words, speaker='S01')


# Line 3's only number was 十分 "enough". Since the 十分 adverb rule (also
# 2026-10-16) it is not formatted, so only lines 1-2 take the mapped path.
@pytest.mark.parametrize('text', USER_LINES[:2])
def test_formatted_japanese_line_keeps_one_time_per_character(text):
    segment = _segment(text)
    format_segment(segment, source_text=text, protected_terms=())
    assert segment.caption_arbitration.get('numeric_formatting')  # the mapped path is taken
    units = segment_content_timeline(segment, ())
    assert len(units) == display_length(segment.text)
    assert all(a.start <= b.start for a, b in zip(units, units[1:]))
    cues = build_local_source_cues([segment])
    assert content_only(''.join(cue.text for cue in cues)) == content_only(segment.text)


def test_enough_shifen_line_is_not_formatted():
    segment = _segment(USER_LINES[2])
    format_segment(segment, source_text=USER_LINES[2], protected_terms=())
    assert segment.text == USER_LINES[2]
    assert not segment.caption_arbitration.get('numeric_formatting')


def _polish_unchanged(monkeypatch, segment):
    from twobyteasr.subtitle_rules import polishing

    def checked_output(*args, **kwargs):
        result = polishing.PolishBatchResult({1: segment.text}, succeeded={1})
        result.details = {1: {'validated_text': segment.text, 'accepted_edits': [], 'rejected_edits': []}}
        return result

    monkeypatch.setattr(polishing, 'call_correction_api', checked_output)
    return polishing.polish_subtitles([segment], '日语数字回归')[0]


@pytest.mark.parametrize('text', USER_LINES)
def test_japanese_proofreading_finish_keeps_spoken_numbers(context, monkeypatch, text):  # noqa: F811
    _, ctx, _ = context
    ctx.task_language = 'ja'
    row = _polish_unchanged(monkeypatch, _segment(text))
    assert row.text == row.final_text == text
    assert not row.caption_arbitration.get('numeric_formatting')
    assert len(segment_content_timeline(row, ())) == display_length(row.text)


# Same lines unconverted (the user turned number formatting off and got
# "字幕保真检查未通过：S01 0.570s"), with their spans from the job log. 一万倍 (and,
# before the 十分 rule, 十分) still read as numbers; 0.7.3 rebuilt line 1 as いいよ｜一万になったら, which
# loses the 一万 after the space, and the whole file failed.
UNCONVERTED = [
    (USER_LINES[0], 0.570, 7.830),
    (USER_LINES[1], 35.720, 42.360),
    (USER_LINES[2], 62.220, 67.410),
]


@pytest.mark.parametrize('text,start,end', UNCONVERTED)
def test_unconverted_user_lines_pass_the_final_check_rebuild(text, start, end):
    from twobyteasr.subtitle_rules.language_rules import language_scope
    from twobyteasr.subtitle_rules.subtitle_fidelity import recover_final_content
    chars = [char for char in text if content_only(char)]
    step = (end - start) / len(chars)
    tokens = [dict(start=start + index * step, end=start + (index + 1) * step - 0.01, text=char, confidence=0.9)
              for index, char in enumerate(chars)]
    segment = SpeechSegment(1, start, end, text, 0.9, [], speaker='S01')
    with language_scope('ja'):
        cues = recover_final_content([], [], [segment], tokens, legacy)
    assert content_only(''.join(cue.text for cue in cues)) == content_only(text)


def test_chinese_proofreading_finish_still_formats_numbers(context, monkeypatch):  # noqa: F811
    _, ctx, _ = context
    ctx.task_language = 'zh'
    row = _polish_unchanged(monkeypatch, _segment('花了三百块一万金币'))
    assert row.text == '花了300块10000金币'
    assert row.caption_arbitration.get('numeric_formatting')
