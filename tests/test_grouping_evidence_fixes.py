"""AI segmentation: keep the model's sound boundaries and measured timing.

2026-10-10, job 0852f218 replayed with the same input and model: the model
answered 叠上 | 任任泽 and kept 这这次就学学聪明了影袭影袭影袭… whole. Local
post-processing then moved 任 across a 0.83 s pause (叠上任 | 任泽) and cut the
repeated call at a uniform estimate (影袭影袭 | 影袭…, 170.992 s), because the
timing-locked turn rejected FireRed's 隐袭 as evidence for 影袭.
"""
from __future__ import annotations

import subtitle_core as core
from twobyteasr.recognition.transcript_data import SpeechSegment, SubtitleCue, WordUnit
from twobyteasr.subtitle_rules.segmentation import inside_repeat_run, locally_repair_resegmented_cue, repair_mid_word_adjacent_cues
from twobyteasr.subtitle_rules.segmentation_alignment import alignment_key, segment_content_timeline


def _uniform(start, end, text):
    step = (end - start) / len(text)
    return [WordUnit(start + i * step, start + (i + 1) * step, char, .78) for i, char in enumerate(text)]


def test_an_asr_boundary_with_a_real_pause_is_not_moved_into_a_word():
    left_text, right_text = "对这个这个印记必须要把龙威叠上", "任任泽就切那个什么翼龙"
    segments = [SpeechSegment(17, 45.08, 47.28, left_text, .78, _uniform(45.08, 47.28, left_text), speaker="S02"),
                SpeechSegment(18, 48.11, 50.01, right_text, .78, _uniform(48.11, 50.01, right_text), speaker="S02")]
    cues = [SubtitleCue(1, 45.10, 47.28, left_text, speaker="S02"), SubtitleCue(2, 48.11, 50.01, right_text, speaker="S02")]
    repaired = repair_mid_word_adjacent_cues(cues, segments, [])
    assert [(c.text, c.start, c.end) for c in repaired] == [(left_text, 45.10, 47.28), (right_text, 48.11, 50.01)]


def test_a_repeated_call_is_not_cut_in_the_middle():
    text = "这这次就学学聪明了影袭影袭影袭这次学聪明了伤害一样"
    assert inside_repeat_run(text, 11) and inside_repeat_run(text, 13) and not inside_repeat_run(text, 15)
    cues = locally_repair_resegmented_cue(text, _uniform(168.75, 173.06, text))
    assert [cue.text for cue in cues] == ["这这次就学学聪明了影袭影袭影袭", "这次学聪明了伤害一样"]


def test_near_homophone_firered_words_anchor_a_locked_turn():
    assert alignment_key("影") == alignment_key("隐") and alignment_key("知") == alignment_key("资")
    assert alignment_key("了") != alignment_key("的")
    text = "这这次就学学聪明了影袭影袭影袭这次学聪明了伤害一样"
    heard = [("话", 168.58, 168.82), ("这", 168.82, 168.94), ("这", 168.94, 169.06), ("次", 169.06, 169.18),
             ("就", 169.18, 169.30), ("学", 169.30, 169.46), ("学", 169.46, 169.70), ("聪", 169.70, 169.82),
             ("明", 169.82, 169.98), ("的", 169.98, 170.458), ("隐", 170.458, 170.98), ("袭", 170.98, 171.14),
             ("隐", 171.14, 171.26), ("袭", 171.26, 171.42), ("隐", 171.42, 171.54), ("袭", 171.54, 171.70),
             ("这", 171.70, 171.78), ("次", 171.78, 171.98), ("学", 171.98, 172.14), ("聪", 172.14, 172.26),
             ("明", 172.26, 172.46), ("哦", 172.46, 172.62), ("对", 172.62, 172.82), ("先", 172.82, 172.98),
             ("打", 172.98, 173.14)]
    tokens = [{"text": t, "start": a, "end": b, "confidence": .85} for t, a, b in heard]
    segment = SpeechSegment(53, 168.58, 173.06, text, .78, _uniform(168.752, 173.06, text), speaker="S02",
                            timing_locked=True)
    timeline = segment_content_timeline(segment, tokens)
    assert len(timeline) == len(text)
    assert round(timeline[0].start, 2) == 168.82            # measured 这, not the estimate 168.75
    assert round(timeline[14].end, 2) == 171.70             # third 影袭 ends where FireRed heard it
    assert round(timeline[15].start, 2) == 171.70
