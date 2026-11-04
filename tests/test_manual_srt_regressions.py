from subtitle_core import (
    SpeechSegment,
    SubtitleCue,
    content_exact,
    merge_isolated_two_character_cues,
    protected_source_boundary_offsets,
    repair_dependent_prefix_boundary_offsets,
    repair_mid_word_adjacent_cues,
    refine_resegmented_texts,
    repair_segmenter_word_boundary_offsets,
    semantic_restart_boundary_offsets,
    texts_from_boundary_offsets,
)


def _segment(segment_id, start, end, text):
    return SpeechSegment(
        segment_id,
        start,
        end,
        text,
        0.9,
        [],
        speaker="S01",
    )


def test_one_second_source_pause_is_kept_and_short_name_is_not_remerged():
    segments = [
        _segment(1, 71.28, 72.42, "来吧杰哥"),
        _segment(2, 73.42, 73.82, "山比"),
    ]
    assert len(content_exact("来吧杰哥")) in protected_source_boundary_offsets(
        segments
    )

    cues = [
        SubtitleCue(1, 71.28, 72.42, "来吧杰哥", speaker="S01"),
        SubtitleCue(2, 73.42, 73.82, "山比", speaker="S01"),
    ]
    merged = merge_isolated_two_character_cues(cues)
    assert [cue.text for cue in merged] == ["来吧杰哥", "山比"]


def test_that_then_prefix_moves_to_the_next_complete_clause():
    text = "然后这个有了那就佩佩和小杨二选"
    source = content_exact(text)
    bad = len(content_exact("然后这个有了那就"))
    fixed = repair_dependent_prefix_boundary_offsets(
        [_segment(1, 0.15, 3.51, text)],
        [bad, len(source)],
    )
    assert texts_from_boundary_offsets(
        [_segment(1, 0.15, 3.51, text)], fixed
    ) == ["然后这个有了", "那就佩佩和小杨二选"]


def test_word_fallback_does_not_move_a_natural_boundary_before_look_action():
    cues = [
        SubtitleCue(1, 15.70, 17.14, "再出一个金", speaker="S01"),
        SubtitleCue(2, 17.14, 19.28, "看一下看一下是不是杰哥", speaker="S01"),
    ]
    repaired = repair_mid_word_adjacent_cues(cues)
    assert [cue.text for cue in repaired] == [
        "再出一个金",
        "看一下看一下是不是杰哥",
    ]


def test_complete_feeling_question_moves_the_dangling_you_to_the_question():
    segment = _segment(1, 17.88, 20.12, "我玩刮刮乐亏了100万有感觉吗")
    refined = refine_resegmented_texts(
        [segment],
        ["我玩刮刮乐亏了100万有", "感觉吗"],
    )
    assert refined == ["我玩刮刮乐亏了100万", "有感觉吗"]


def test_ten_second_boarding_phrase_is_never_split_in_the_middle():
    segment = _segment(1, 30.68, 33.84, "十秒内不上舰给你号刮完")
    refined = refine_resegmented_texts(
        [segment],
        ["十秒", "内不上舰", "给你号刮完"],
    )
    assert refined == ["十秒内不上舰", "给你号刮完"]
