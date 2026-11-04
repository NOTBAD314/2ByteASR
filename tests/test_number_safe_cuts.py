"""2026-10-16 (many users: "字幕保真检查未通过" when AI line breaking is off).

The final content check reads numbers caption by caption, and a Chinese numeral
only counts with its context (第 before it, 个/金币 after it). Local line
breaking cut 一万｜金币 or 第｜二阶段, the check saw a number disappear, the
rebuild made the same cut and the whole file failed. The cases below are the
sentences a fuzz of the rebuild caught (tmp/fidelity-ja-probe/fuzz_recover.py).
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import subtitle_core as legacy  # noqa: F401  (loads the core before the timing helpers)
from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.number_fidelity import numeric_event_values, numeric_unsafe_cut_offsets
from twobyteasr.subtitle_rules.segmentation import locally_repair_resegmented_cue
from twobyteasr.subtitle_rules.subtitle_fidelity import recover_final_content
from twobyteasr.subtitle_rules.text_rules import content_exact

CHINESE = [
    '花了三百块一万金币对对对一二三第二阶段一万金币真的很难再来一把',
    '第二阶段花了三百块一万金币那个那个第二阶段一样的再打一次这个东西',
    '打了一百多把这个东西一万金币先别急对对对打了一百多把我们先去打一下十五秒',
    '对对对花了三百块先别急一万金币就是说再来一把好不好打了一百多把一二三',
    '还剩一条命还剩一条命一万金币还剩一条命十一点下播',
    '打了一百多把就是说一万金币冲冲冲花了三百块',
]
JAPANESE = ['きもちいい二十歳になったいくよ一日中きもちいいきもちいいああああ']


def _cut(text, left, right):
    """Content offset of the cut between ``left`` and ``right`` (first occurrence)."""
    source = content_exact(text)
    return source.index(left + right) + len(left)


def _units(text, step=0.18):
    return [SimpleNamespace(start=index * step, end=(index + 1) * step - 0.02, text=char)
            for index, char in enumerate(content_exact(text))]


def _segment(text, step=0.18):
    tokens = [dict(start=1.14 + index * step, end=1.14 + (index + 1) * step - 0.02, text=char, confidence=0.9)
              for index, char in enumerate(text)]
    segment = SpeechSegment(segment_id=1, start=1.14, end=tokens[-1]['end'], text=text, confidence=0.9,
                            words=[], speaker='S00')
    return segment, tokens


def test_cuts_that_change_numbers_are_unsafe():
    text = '这个东西一万金币然后我们第二阶段这个怪有二十个'
    unsafe = numeric_unsafe_cut_offsets(text)
    assert _cut(text, '一万', '金币') in unsafe
    assert _cut(text, '第', '二阶段') in unsafe
    assert _cut(text, '二十', '个') in unsafe
    # Ordinary word boundaries keep every number whole.
    assert _cut(text, '这个东西', '一万') not in unsafe
    assert _cut(text, '金币', '然后') not in unsafe
    assert numeric_unsafe_cut_offsets('') == set() and numeric_unsafe_cut_offsets('好') == set()


@pytest.mark.parametrize('text', CHINESE)
def test_local_repair_keeps_every_number_in_its_cue(text):
    with language_scope('zh'):
        cues = locally_repair_resegmented_cue(text, _units(text))
        assert content_exact(''.join(cue.text for cue in cues)) == content_exact(text)
        assert tuple(v for cue in cues for v in numeric_event_values(cue.text)) == numeric_event_values(text)


def _formatted_segment_without_word_timing():
    """A real no-AI run (2026-10-16): 十连 became 10连 while the segment's words
    were still one span, so every character got the whole 6.4 s segment."""
    from twobyteasr.recognition.transcript_data import WordUnit
    source = '我刚才又抽了十连结果只出了一个五星还是重复的角色有点难受啊！'
    text = '我刚才又抽了10连结果只出了一个五星还是重复的角色有点难受啊！'
    start, step = 31.92, 0.21
    tokens = [dict(start=round(start + index * step, 3), end=round(start + (index + 1) * step, 3), text=char,
                   confidence=0.99) for index, char in enumerate(source[:-1])]
    segment = SpeechSegment(segment_id=5, start=start, end=tokens[-1]['end'], text=text, confidence=0.78,
                            words=[WordUnit(start, tokens[-1]['end'], text, 0.78)], speaker='S01')
    segment.caption_arbitration = {'numeric_formatting': [{
        'version': 'numeric-events-conservative-v2', 'source': source, 'result': text,
        'events': [{'start': 6, 'end': 7, 'source': '十', 'value': '10', 'kind': 'integer', 'output_start': 6,
                    'output_end': 8, 'audio_start': start, 'audio_end': tokens[-1]['end'],
                    'timing': 'segment-only-no-word-alignment'}]}]}
    return segment, tokens


def test_number_formatted_without_word_timing_uses_character_tokens():
    from twobyteasr.subtitle_rules.number_fidelity import mapped_content_timeline
    from twobyteasr.subtitle_rules.segmentation_alignment import segment_content_timeline
    segment, tokens = _formatted_segment_without_word_timing()
    assert mapped_content_timeline(segment) is None
    units = segment_content_timeline(segment, tokens)
    assert len(units) == len(content_exact(segment.text))
    assert max(unit.end - unit.start for unit in units) < 1.0
    with language_scope('zh'):
        cues = recover_final_content([], [], [segment], tokens, legacy)
    assert content_exact(''.join(cue.text for cue in cues)) == content_exact(segment.text)
    assert all(0 < cue.end - cue.start <= 5.05 for cue in cues) and len(cues) <= 4
    assert tuple(v for cue in cues for v in numeric_event_values(cue.text)) == numeric_event_values(segment.text)


@pytest.mark.parametrize('language', ['zh', 'ja'])
@pytest.mark.parametrize('text,start,end', [
    ('两波大人还是太了', 1167.88, 1191.56),
    ('这把我们两波就打完了', 300.0, 332.0),
])
def test_sparse_segment_keeps_a_lone_numeral_with_the_next_character(text, start, end, language):
    """2026-10-23 user log (SenseVoice alone, no word timing; the task was set to
    Japanese): 8 characters over 23.7 s gave each one 2.96 s, so only one fit a
    line. The lone 两 read as 2, every rebuild cut it the same way and the whole
    file failed with 「字幕保真检查未通过：S00 1167.880s」."""
    segment = SpeechSegment(segment_id=30, start=start, end=end, text=text, confidence=0.9,
                            words=[], speaker='S00')
    with language_scope(language):
        cues = recover_final_content([], [], [segment], [], legacy)
    cues.sort(key=lambda cue: cue.start)
    assert content_exact(''.join(cue.text for cue in cues)) == content_exact(text)
    assert tuple(v for cue in cues for v in numeric_event_values(cue.text)) == numeric_event_values(text) == ()
    assert '两波' in [content_exact(cue.text)[:2] for cue in cues]
    assert all(0 < cue.end - cue.start <= 5.05 and start - 0.15 <= cue.start and cue.end <= end + 0.05
               for cue in cues)
    assert all(b.start >= a.end - 0.001 for a, b in zip(cues, cues[1:]))


USER_REPORT = Path(__file__).parent / 'data' / 'sensevoice_zh_sparse_fidelity_20261023.json'


def _user_report_segments(rows):
    return [SpeechSegment(segment_id=row['id'], start=row['start'], end=row['end'], text=row['text'],
                          confidence=0.9, words=[], speaker=row['speaker']) for row in rows]


def _assert_kept(cues, segments):
    cues = sorted(cues, key=lambda cue: cue.start)
    assert content_exact(''.join(cue.text for cue in cues)) == content_exact(''.join(s.text for s in segments))
    assert (tuple(v for cue in cues for v in numeric_event_values(cue.text))
            == tuple(v for s in segments for v in numeric_event_values(s.text)))
    assert max(cue.end - cue.start for cue in cues) <= 5.05
    assert all(b.start >= a.end - 0.001 for a, b in zip(cues, cues[1:]))
    return cues


@pytest.mark.parametrize('language', ['ja', 'zh'])
def test_user_report_final_check_passes(language):
    """The 2026-10-23 log replayed: the check's own input (175 cues) failed at S00 1167.880s."""
    if not USER_REPORT.is_file():
        pytest.skip('private user-report data (tests/data is not part of the public source)')
    report = json.loads(USER_REPORT.read_text(encoding='utf-8'))
    segments = _user_report_segments(report['segments'])
    finalized = [SubtitleCue(0, c['start'], c['end'], c['text'], speaker=c['speaker']) for c in report['final']]
    grouped = [SubtitleCue(0, r['start'], r['end'], r['text']) for r in report['grouped']]
    with language_scope(language):
        cues = _assert_kept(recover_final_content(finalized, grouped, segments, [], legacy), segments)
    assert [(round(c.start, 2), round(c.end, 2), c.text) for c in cues if 1167 < c.start < 1173] == [
        (1167.88, 1172.88, '两波')]


@pytest.mark.parametrize('language', ['ja', 'zh'])
def test_user_report_rebuilds_from_source_after_the_whole_file_overlap_split(language):
    """Rebuilding every turn needs the whole-file rows apart first: 46.92 s overlapped 0.13 s."""
    if not USER_REPORT.is_file():
        pytest.skip('private user-report data (tests/data is not part of the public source)')
    from twobyteasr.recognition.incremental_asr import split_chunk_overlaps
    report = json.loads(USER_REPORT.read_text(encoding='utf-8'))
    rows, seams = split_chunk_overlaps(report['segments'], keys=('start', 'end'), margin=0.02)
    assert seams == 1
    segments = _user_report_segments(rows)
    with language_scope(language):
        _assert_kept(recover_final_content([], [], segments, [], legacy), segments)


@pytest.mark.parametrize('text,language', [(text, 'zh') for text in CHINESE] + [(text, 'ja') for text in JAPANESE])
def test_final_check_rebuild_no_longer_fails(text, language):
    segment, tokens = _segment(text)
    with language_scope(language):
        # Nothing usable from the earlier stages: the check must rebuild from the source.
        cues = recover_final_content([], [], [segment], tokens, legacy)
        assert content_exact(''.join(cue.text for cue in cues)) == content_exact(text)
        assert tuple(v for cue in cues for v in numeric_event_values(cue.text)) == numeric_event_values(text)
