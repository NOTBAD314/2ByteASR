# -*- coding: utf-8 -*-
from subtitle_core import (
    MAX_SUBTITLE_CHARS,
    SpeechSegment,
    SubtitleCue,
    build_local_source_cues,
    final_text_conservation_differences,
    normalize_cue_times,
    remove_overlapping_duplicate_segments,
    repair_overlong_cues_from_source,
    validate_final_cues,
)


def test_overlong_grouped_cue_is_restored_from_same_speaker_sources():
    segments = [
        SpeechSegment(1, 33.82, 34.82, "七轮的十", 0.9, [], speaker="S02"),
        SpeechSegment(2, 44.01, 45.13, "不对不对不对", 0.9, [], speaker="S01"),
        SpeechSegment(3, 48.62, 49.82, "六这正常吗", 0.9, [], speaker="S01"),
        SpeechSegment(4, 50.22, 50.62, "来了", 0.9, [], speaker="S02"),
    ]
    cues = [
        SubtitleCue(1, 33.82, 50.62, "七轮的十来了", speaker="S02"),
        SubtitleCue(2, 44.01, 45.13, "不对不对不对", speaker="S01"),
        SubtitleCue(3, 48.62, 49.82, "六这正常吗", speaker="S01"),
    ]

    repaired = repair_overlong_cues_from_source(cues, segments)

    assert [cue.text for cue in repaired if cue.speaker == "S02"] == [
        "七轮的十",
        "来了",
    ]
    assert max(cue.end - cue.start for cue in repaired) <= 5.05
    validate_final_cues(repaired, segments, 60.0)


def test_overlength_single_source_segment_is_locally_split():
    text = "山比不是那个技能是出那个传送带吗然后还会再回到原来的位置"
    segment = SpeechSegment(1, 71.28, 73.98, text, 0.9, [], speaker="S01")
    cue = SubtitleCue(1, 71.28, 73.98, text, speaker="S01")

    repaired = repair_overlong_cues_from_source([cue], [segment])

    assert "".join(item.text for item in repaired) == text
    assert len(repaired) >= 2
    assert max(len(item.text) for item in repaired) <= MAX_SUBTITLE_CHARS
    validate_final_cues(repaired, [segment], 80.0)


def test_real_edited_sample_never_keeps_a_nineteen_character_cue():
    text = "我我紧急大退了一下我看一下我还有没有啊"
    segment = SpeechSegment(1, 58.067, 60.850, text, 0.9, [], speaker="S01")
    cue = SubtitleCue(1, segment.start, segment.end, text, speaker="S01")

    repaired = repair_overlong_cues_from_source([cue], [segment])

    assert "".join(item.text for item in repaired) == text
    assert len(repaired) >= 2
    assert max(len(item.text) for item in repaired) <= MAX_SUBTITLE_CHARS


def test_unmatched_cpu_asr_cue_uses_its_own_timeline_as_final_fallback():
    # SenseVoice/Whisper can produce a cue whose text no longer maps one-to-one
    # to the original coarse source segment after local cleanup.
    segment = SpeechSegment(1, 10.0, 18.0, "原始识别内容与清理后不同", 0.8, [], speaker="S00")
    cue = SubtitleCue(1, 10.0, 17.88, "一种历史的厚重感啊长夜", speaker="S00")

    repaired = repair_overlong_cues_from_source([cue], [segment])

    assert "".join(item.text for item in repaired) == cue.text
    assert len(repaired) >= 2
    assert max(item.end - item.start for item in repaired) <= 5.05
    assert all(item.speaker == "S00" for item in repaired)


def test_short_text_with_long_display_time_is_split_without_losing_text():
    cue = SubtitleCue(1, 20.0, 26.13, "一个护盾的特效看", speaker="S00")

    repaired = repair_overlong_cues_from_source([cue], [])

    assert "".join(item.text for item in repaired) == cue.text
    assert max(item.end - item.start for item in repaired) <= 5.05


def test_local_source_recovery_restores_per_speaker_text_conservation():
    segments = [
        SpeechSegment(1, 0.0, 1.0, "第一句话", 0.9, [], speaker="S01"),
        SpeechSegment(2, 1.0, 2.0, "第二句话", 0.9, [], speaker="S01"),
    ]
    reordered = [
        SubtitleCue(1, 0.0, 1.0, "第二句话", speaker="S01"),
        SubtitleCue(2, 1.0, 2.0, "第一句话", speaker="S01"),
    ]

    differences = final_text_conservation_differences(reordered, segments)
    recovered = build_local_source_cues(segments)

    assert differences and differences[0]["speaker"] == "S01"
    assert final_text_conservation_differences(recovered, segments) == []
    validate_final_cues(recovered, segments, 3.0)


def test_global_text_equality_cannot_hide_a_speaker_track_swap():
    segments = [
        SpeechSegment(1, 0.0, 1.0, "甲", 0.9, [], speaker="S01"),
        SpeechSegment(2, 1.0, 2.0, "乙", 0.9, [], speaker="S02"),
    ]
    swapped = [
        SubtitleCue(1, 0.0, 1.0, "甲", speaker="S02"),
        SubtitleCue(2, 1.0, 2.0, "乙", speaker="S01"),
    ]

    assert "".join(item.text for item in segments) == "".join(item.text for item in swapped)
    differences = final_text_conservation_differences(swapped, segments)
    assert {item["speaker"] for item in differences} == {"S01", "S02"}


def test_same_speaker_overlapping_chunks_keep_source_text_order():
    cues = [
        SubtitleCue(1, 350.78, 354.37, "前一段正文", speaker="S02"),
        # A later source phrase can receive an earlier acoustic anchor when MOSS
        # chunks overlap. cue_id, not the raw start, is the conserved text order.
        SubtitleCue(2, 352.65, 354.02, "后一段正文", speaker="S02"),
        SubtitleCue(3, 354.37, 355.97, "最后正文", speaker="S02"),
    ]

    normalized = normalize_cue_times(cues, 60.0)

    assert [cue.text for cue in normalized] == ["前一段正文", "后一段正文", "最后正文"]
    assert all(
        previous.end <= current.start
        for previous, current in zip(normalized, normalized[1:])
    )


def test_unit_longer_than_a_cue_never_dead_ends_local_repair():
    """2026-10-15 user report (Japanese task, drawn-out moans): one aligned
    unit longer than MAX_SUBTITLE_SECONDS could not form a cue, so its
    position was unreachable. A neighbour exactly PREFERRED_MAX_SUBTITLE_CHARS
    long still linked to it (an infinite total tied and the tie-break preferred
    that length); the chain dead-ended and the whole task failed with
    "Qwen 单条本地修复未覆盖完整原文。". It now takes the existing hard split,
    which keeps every character."""
    from types import SimpleNamespace

    from subtitle_core import MAX_SUBTITLE_SECONDS, PREFERRED_MAX_SUBTITLE_CHARS
    from twobyteasr.subtitle_rules.segmentation import locally_repair_resegmented_cue

    text = "きもちいいですねほんとうにああ" + "あ" + "すごいですね"
    long_index = 15
    units, at = [], 0.0
    for index, char in enumerate(text):
        length = MAX_SUBTITLE_SECONDS + 1.0 if index == long_index else 0.25
        units.append(SimpleNamespace(start=at, end=at + length, text=char))
        at += length + 0.02
    # A piece of exactly the preferred length can end at the long unit.
    assert long_index >= PREFERRED_MAX_SUBTITLE_CHARS

    cues = locally_repair_resegmented_cue(text, units)

    assert "".join(cue.text for cue in cues) == text
    assert all(cue.end > cue.start for cue in cues)
    assert all(previous.end <= current.start for previous, current in zip(cues, cues[1:]))
