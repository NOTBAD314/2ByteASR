# -*- coding: utf-8 -*-
from subtitle_core import (
    SpeechSegment,
    SubtitleCue,
    WordUnit,
    content_exact,
    chinese_word_spans,
    locally_repair_resegmented_cue,
    repair_mid_word_adjacent_cues,
    repair_segmenter_word_boundary_offsets,
    semantically_awkward_boundary,
    texts_from_boundary_offsets,
)


def _units(text):
    units = []
    cursor = 0.0
    for char in content_exact(text):
        units.append(WordUnit(cursor, cursor + 0.12, char, 1.0))
        cursor += 0.12
    return units


def test_local_repair_hard_fallback_never_discards_file_when_units_are_sparse():
    text = "\u4e00\u4e8c\u4e09\u56db"
    units = [
        WordUnit(index * 6.0, (index + 1) * 6.0, char, 1.0)
        for index, char in enumerate(text)
    ]

    cues = locally_repair_resegmented_cue(text, units)

    assert "".join(cue.text for cue in cues) == text
    assert all(0 < cue.end - cue.start <= 5.05 for cue in cues)


def test_local_repair_prefers_complete_phrases_within_soft_max():
    cases = {
        "那我们就直接进入一个珊瑚场啊": [
            ["那我们就直接进入一个珊瑚场啊"],
            ["那我们就直接进入", "一个珊瑚场啊"],
        ],
        "这就是八件藏品的轮廓啊出价": [
            ["这就是八件藏品的轮廓啊出价"],
            ["这就是八件藏品的", "轮廓啊出价"],
            ["这就是八件藏品的轮廓", "啊出价"],
            ["这就是八件藏品的轮廓啊", "出价"],
        ],
        "我们有300万的启动资金啊": [
            ["我们有300万的启动资金啊"],
            ["我们有300万的", "启动资金啊"],
        ],
    }
    for text, accepted in cases.items():
        out = [cue.text for cue in locally_repair_resegmented_cue(text, _units(text))]
        assert out in accepted, (text, out)


def test_midword_adjacent_prefers_complete_left_word():
    cues = repair_mid_word_adjacent_cues(
        [
            SubtitleCue(1, 8.41, 9.42, "那我们就直接进", speaker="S01"),
            SubtitleCue(2, 9.42, 10.62, "入一个珊瑚场啊", speaker="S01"),
        ]
    )
    assert [cue.text for cue in cues] == ["那我们就直接进入", "一个珊瑚场啊"]


def test_midword_repair_never_crosses_a_long_gap_or_interruption():
    cues = repair_mid_word_adjacent_cues(
        [
            SubtitleCue(1, 33.82, 34.82, "七轮的十", speaker="S02"),
            SubtitleCue(2, 50.22, 50.62, "来了", speaker="S02"),
        ]
    )
    assert [cue.text for cue in cues] == ["七轮的十", "来了"]
    assert [(cue.start, cue.end) for cue in cues] == [
        (33.82, 34.82),
        (50.22, 50.62),
    ]


def test_number_unit_is_atomic_span():
    spans = chinese_word_spans("我们有300万的启动资金啊")
    assert any(word == "300万" for _s, _e, word in spans)


def test_long_de_left_is_allowed_boundary_but_short_completion_should_merge_elsewhere():
    text = "这就是八件藏品的轮廓啊出价"
    # after 藏品的：旧规则允许，但短中心语更宜合并（由 hanging 逻辑处理）
    assert semantically_awkward_boundary(text, 8) is False
    assert semantically_awkward_boundary(text, 7) is True
    assert semantically_awkward_boundary("我的轮廓", 2) is True


def test_segmenter_moves_enter_to_word_end():
    batch = [SpeechSegment(1, 0, 2, "那我们就直接进入一个珊瑚场啊", 0.9, [], speaker="S01")]
    offsets = repair_segmenter_word_boundary_offsets(batch, [7, 14])
    texts = texts_from_boundary_offsets(batch, offsets)
    assert texts == ["那我们就直接进入", "一个珊瑚场啊"]
