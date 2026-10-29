"""One cleanup merge that breaks the source contract no longer discards all AI grouping.

2026-10-28: in each of the user's three runs (20-minute and two 1-hour streams)
the AI batches passed the contract, then one of ~10 lone-character or
two-character merges joined rows across another speaker's turn, and Stage 9
replaced the whole file's AI grouping with the local fallback
(grouping_postprocess_rejected). Replays of the runs keep the AI grouping and
drop only that merge.
"""
import copy

import subtitle_core  # noqa: F401 - initialize the legacy facade
from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue
from twobyteasr.subtitle_rules import grouping


def rows():
    return [SpeechSegment(1, 0.0, 2.0, "我们先看一下这个", .9, [], speaker="S00"),
            SpeechSegment(2, 2.05, 2.6, "好的", .9, [], speaker="S01"),
            SpeechSegment(3, 2.7, 2.95, "你", .9, [], speaker="S00"),
            SpeechSegment(4, 6.0, 8.0, "然后我们再看下一个", .9, [], speaker="S00"),
            SpeechSegment(5, 8.05, 8.3, "吧", .9, [], speaker="S00")]


def ai_cues():
    return [SubtitleCue(1, 0.0, 2.0, "我们先看一下这个", speaker="S00"),
            SubtitleCue(2, 2.05, 2.6, "好的", speaker="S01"),
            SubtitleCue(3, 2.7, 2.95, "你", speaker="S00"),
            SubtitleCue(4, 6.0, 8.0, "然后我们再看下一个", speaker="S00"),
            SubtitleCue(5, 8.05, 8.3, "吧", speaker="S00")]


def merge_both_lone_characters(cues):
    """Stands in for a cleanup pass: merges each lone character into the
    previous line of the same speaker, regardless of rows in between."""
    out = []
    for cue in cues:
        previous = next((item for item in reversed(out) if item.speaker == cue.speaker), None)
        if previous is not None and len(cue.text) == 1:
            previous.text += cue.text
            previous.end = cue.end
            continue
        out.append(cue)
    return out


def test_only_the_merge_across_another_speakers_turn_is_dropped(monkeypatch):
    events = []
    monkeypatch.setattr(grouping, "record_run_event", lambda name, **data: events.append((name, data)))
    segments = rows()
    assert grouping._restore_grouped_source(segments, ai_cues())
    assert not grouping._restore_grouped_source(segments, merge_both_lone_characters(ai_cues()))
    kept = grouping._contract_safe_pass("merge", merge_both_lone_characters, ai_cues(), segments)
    assert [cue.text for cue in kept] == ["我们先看一下这个", "好的", "你", "然后我们再看下一个吧"]
    assert grouping._restore_grouped_source(segments, copy.deepcopy(kept))
    assert events == [("grouping_postprocess_partial", {"step": "merge", "change_units": 2, "kept": 1,
                                                         "dropped": 1, "reason": "source_contract"})]


def test_a_pass_that_keeps_the_contract_is_applied_whole(monkeypatch):
    monkeypatch.setattr(grouping, "record_run_event", lambda *args, **kwargs: None)
    segments = [segment for segment in rows() if segment.speaker == "S00" and segment.segment_id >= 4]
    cues = [cue for cue in ai_cues() if cue.cue_id >= 4]
    kept = grouping._contract_safe_pass("merge", merge_both_lone_characters, cues, segments)
    assert [cue.text for cue in kept] == ["然后我们再看下一个吧"]
