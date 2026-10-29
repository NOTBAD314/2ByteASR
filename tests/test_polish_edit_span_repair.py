"""A correction whose character offsets miss its quoted text is relocated, not discarded.

2026-10-28: the user's 20-minute and 1-hour streams lost 6 and 20 cues to
「该条校对结果字段或编辑范围无效」; that check fires only on offsets that do
not match the quoted text or on overlapping edits. Replies are not logged,
so these responses are synthetic.
"""
import subtitle_core  # noqa: F401 - initialize the legacy facade

from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.subtitle_rules import polishing


def segment(text, cue_id=1):
    return SpeechSegment(cue_id, 0., 2., text, .85, [], speaker='API_S01')


def validate(text, *edits):
    quarantined = {}
    value = {'checked_ids': [1], 'cues': [{'id': 1, 'edits': [dict(edit, type='asr_correction') for edit in edits]}]}
    result = polishing._validate_polish_response(value, [segment(text)], 2, quarantined)
    return result, quarantined


def test_locating_the_quoted_text():
    locate = polishing._locate_edit_source
    assert locate('奔铁这边的动态啊', '奔铁', 1) == 0
    assert locate('这这酷猫不太不太适合', '不太', 9) == 6  # nearest of 4 and 6
    assert locate('A这B这C', '这', 2) is None  # equally near both
    assert locate('A这B这C', '这', None) is None
    assert locate('奔铁这边的动态啊', '崩铁', 0) is None
    assert locate('奔铁这边的动态啊', '', 0) is None


def test_misplaced_offsets_keep_the_cue(monkeypatch):
    events = []
    monkeypatch.setattr(polishing, 'record_run_event', lambda event, **data: events.append((event, data)))
    result, quarantined = validate('奔铁这边的动态啊', {'from': '奔铁', 'to': '崩铁', 'start': 1, 'end': 3})
    assert quarantined == {}
    assert result['cues'][0]['edits'][0] == {'from': '奔铁', 'to': '崩铁', 'start': 0, 'end': 2, 'type': 'asr_correction'}
    assert events == [('polishing_edit_span_repaired',
                       {'batch_index': 2, 'cue_id': 1, 'spans': [{'given': [1, 3], 'located': [0, 2]}]})]


def test_unlocatable_or_overlapping_edits_still_fall_back():
    for edits in ([{'from': '崩铁', 'to': '奔铁', 'start': 0, 'end': 2}],
                  [{'from': '这', 'to': '', 'start': 7, 'end': 8}],
                  [{'from': '奔铁这', 'to': '崩铁这', 'start': 0, 'end': 3},
                   {'from': '铁这边', 'to': '铁那边', 'start': 5, 'end': 8}]):
        text = '奔铁这边的动态啊' if '奔铁这' in edits[0]['from'] or '崩铁' in edits[0]['from'] else 'A这B这C'
        result, quarantined = validate(text, *edits)
        assert quarantined == {1: 'semantic_validation'} and result['cues'] == []
