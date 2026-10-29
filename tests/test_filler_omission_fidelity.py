"""2026-10-23 (second user: 「字幕保真检查未通过：S00 0.000s」 on 0.8.2).

The single-character pass drops a lone filler (「哦」) that cannot join a
neighbour. The final content check compared every turn with its source, saw
one character missing, rebuilt the whole 425-second turn (the filler came
back) and failed the job when no rebuild fit. The pass now hands over the cues
it dropped, and a turn that differs from its source only by them passes as it
is. Anything else missing still goes through the rebuild.
"""
import json
from pathlib import Path

import pytest

import subtitle_core as legacy
from twobyteasr.recognition.pipeline_runtime import finalize_cues
from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue
from twobyteasr.subtitle_rules.language_rules import language_scope
from twobyteasr.subtitle_rules.number_fidelity import numeric_event_values
from twobyteasr.subtitle_rules.subtitle_fidelity import recover_final_content
from twobyteasr.subtitle_rules.text_rules import content_exact


@pytest.fixture
def events(monkeypatch):
    rows = []
    monkeypatch.setattr(legacy, 'record_run_event', lambda name, **payload: rows.append((name, payload)))
    return rows


def _names(events):
    return [name for name, _payload in events if name.startswith('final_content')]


def _recorded(events):
    return next(payload for name, payload in events if name == 'final_content_recorded_omissions')


def _cue(cue_id, start, end, text):
    return SubtitleCue(cue_id, start, end, text, speaker='S00')


def _text(cues):
    return ''.join(content_exact(cue.text) for cue in sorted(cues, key=lambda cue: (cue.start, cue.end)))


def _turn():
    """「朋友 | 哦 | 原始力量」 like 100.5-114 s of the user's run, the filler dropped."""
    segment = SpeechSegment(1, 0.0, 10.0, '我朋友哦原始力量', 0.9, [], speaker='S00')
    final = [_cue(1, 0.0, 3.5, '我朋友'), _cue(3, 4.8, 9.0, '原始力量')]
    return segment, final, _cue(2, 3.6, 4.6, '哦')


def test_turn_missing_only_the_recorded_filler_passes_as_it_is(events):
    segment, final, filler = _turn()
    with language_scope('zh'):
        out = recover_final_content(final, [], [segment], [], legacy, omitted=[filler])
    assert out is final
    assert _names(events) == ['final_content_recorded_omissions']
    assert _recorded(events)['omitted'] == ['哦'] and _recorded(events)['start'] == 0.0


def test_without_the_record_the_turn_is_rebuilt_and_the_filler_returns(events):
    segment, final, _filler = _turn()
    with language_scope('zh'):
        out = recover_final_content(final, [], [segment], [], legacy)
    assert _names(events) == ['final_content_conservation_recovery']
    assert _text(out) == '我朋友哦原始力量'


@pytest.mark.parametrize('source,final,omitted', [
    # A different character is missing; the recorded filler is still there.
    ('我朋友哦原始力量', [(0.0, 3.5, '朋友哦'), (4.8, 9.0, '原始力量')], [(3.6, 4.6, '哦')]),
    # Two fillers are missing, only one was dropped on purpose.
    ('哦我朋友哦原始力量', [(0.5, 3.5, '我朋友'), (4.8, 9.0, '原始力量')], [(3.6, 4.6, '哦')]),
    # Same character, wrong place: the 哦 at 0 s is gone, the one dropped at 3 s is shown.
    ('哦好的哦走吧', [(0.5, 2.5, '好的'), (3.0, 3.4, '哦'), (4.0, 6.0, '走吧')], [(3.0, 3.4, '哦')]),
    # The text matches once the filler is back, but 20 now reads as 2 | 0.
    ('打了20哦走吧', [(0.0, 2.0, '打了2'), (2.0, 3.0, '0'), (4.0, 6.0, '走吧')], [(3.2, 3.8, '哦')]),
])
def test_anything_beyond_the_recorded_omission_is_still_rebuilt(events, source, final, omitted):
    segment = SpeechSegment(1, 0.0, 10.0, source, 0.9, [], speaker='S00')
    final = [_cue(index, *row) for index, row in enumerate(final, 1)]
    omitted = [_cue(90 + index, *row) for index, row in enumerate(omitted)]
    with language_scope('zh'):
        out = recover_final_content(final, [], [segment], [], legacy, omitted=omitted)
    assert _names(events) == ['final_content_conservation_recovery']
    assert _text(out) == content_exact(source)
    assert (tuple(v for cue in sorted(out, key=lambda c: c.start) for v in numeric_event_values(cue.text))
            == numeric_event_values(source))


def test_finalize_keeps_the_filler_dropped_and_the_turn_as_grouped(events):
    """Real single-character pass and final check: 哦 cannot join (gaps over 0.35 s)."""
    segment = SpeechSegment(1, 0.0, 10.0, '我朋友哦原始力量', 0.9, [], speaker='S00')
    grouped = [_cue(1, 0.0, 3.0, '我朋友'), _cue(2, 3.8, 4.3, '哦'), _cue(3, 5.2, 9.0, '原始力量')]
    with language_scope('zh'):
        out = finalize_cues(grouped, [segment], [], [], 10.0, 30.0, legacy)
    assert [cue.text for cue in out] == ['我朋友', '原始力量']
    assert _names(events) == ['final_content_recorded_omissions']
    assert out[0].end <= 3.8 and out[1].start >= 4.3


def test_rolled_back_pass_records_no_omission(monkeypatch):
    from twobyteasr.subtitle_rules import cue_cleanup

    def broken(cues):
        raise RuntimeError('boom')
    monkeypatch.setattr(cue_cleanup, 'resolve_isolated_single_character_cues', broken)
    monkeypatch.setattr(cue_cleanup, 'record_run_event', lambda *_args, **_kwargs: None)
    cues = [_cue(1, 0.0, 3.0, '我朋友'), _cue(2, 3.8, 4.3, '哦')]
    omitted = []
    out = cue_cleanup.apply_isolated_single_character_rules_safely(cues, omitted=omitted)
    assert [cue.text for cue in out] == ['我朋友', '哦'] and omitted == []


USER_REPORT = Path(__file__).parent / 'data' / 'funasr_nano_filler_omission_20261023.json'


def _user_report(split):
    if not USER_REPORT.is_file():
        pytest.skip('private user-report data (tests/data is not part of the public source)')
    report = json.loads(USER_REPORT.read_text(encoding='utf-8'))
    rows = report['rows']
    if split:
        from twobyteasr.recognition.incremental_asr import split_chunk_overlaps
        rows, seams = split_chunk_overlaps(rows, keys=('start', 'end'), margin=0.02)
        assert seams == 36
    segments = [SpeechSegment(index, row['start'], row['end'], row['text'], 0.9, [], speaker='S00')
                for index, row in enumerate(rows, 1)]
    grouped = [_cue(index, row['start'], row['end'], row['text']) for index, row in enumerate(report['stage8'], 1)]
    if split:
        # Stage 8 lines stay inside their (now shorter) row.
        bounds = [(segment.start, segment.end) for segment in segments]
        for cue in grouped:
            middle = (cue.start + cue.end) / 2
            low, high = min(bounds, key=lambda b: (not b[0] <= middle <= b[1], abs((b[0] + b[1]) / 2 - middle)))
            cue.start, cue.end = max(cue.start, low), min(cue.end, high)
    return report, segments, grouped


@pytest.mark.parametrize('split', [False, True], ids=['rows-as-0.8.2', 'overlaps-split'])
def test_user_report_passes_with_the_filler_dropped(events, split):
    """The log replayed: 0.8.2 failed with S00 0.000s; with the rows split (0.8.3) the
    whole 0-425.5 s turn was rebuilt and 哦 came back."""
    report, segments, grouped = _user_report(split)
    with language_scope('zh'):
        out = finalize_cues(grouped, segments, [], [], report['audio_seconds'], report['fps'], legacy)
    assert _names(events) == ['final_content_recorded_omissions']
    recorded = _recorded(events)
    assert (recorded['start'], recorded['end'], recorded['omitted']) == (0.0, 425.5, ['哦'])
    out.sort(key=lambda cue: cue.start)
    source = ''.join(content_exact(segment.text) for segment in segments)
    assert '我朋友哦原始力量' in source
    assert _text(out) == source.replace('我朋友哦原始力量', '我朋友原始力量', 1)
    assert (tuple(v for cue in out for v in numeric_event_values(cue.text))
            == tuple(v for segment in segments for v in numeric_event_values(segment.text)))
    assert max(cue.end - cue.start for cue in out) <= 5.05
    assert all(b.start >= a.end - 0.001 for a, b in zip(out, out[1:]))
