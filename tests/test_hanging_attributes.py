# -*- coding: utf-8 -*-
from subtitle_core import (
    SpeechSegment,
    SubtitleCue,
    merge_hanging_attribute_cues,
    repair_hanging_attribute_boundary_offsets,
    should_merge_hanging_attribute,
    texts_from_boundary_offsets,
)


def test_merge_money_startup_funds():
    batch = [SpeechSegment(1, 0.0, 2.5, "我们有300万的启动资金啊", 0.9, [], speaker="S01")]
    offsets = repair_hanging_attribute_boundary_offsets(batch, [8, 13])
    assert offsets == [13]
    assert texts_from_boundary_offsets(batch, offsets) == ["我们有300万的启动资金啊"]


def test_merge_or_resplit_coral_field():
    batch = [
        SpeechSegment(1, 8.4, 10.8, "那我们就直接进入一个珊瑚场啊", 0.9, [], speaker="S01")
    ]
    offsets = repair_hanging_attribute_boundary_offsets(batch, [10, 14])
    texts = texts_from_boundary_offsets(batch, offsets)
    assert texts in (
        ["那我们就直接进入一个珊瑚场啊"],
        ["那我们就直接进入", "一个珊瑚场啊"],
    )


def test_do_not_merge_new_action_after_de():
    assert not should_merge_hanging_attribute("哦这都是要钱的", "买最下面的吗")
    batch = [SpeechSegment(1, 0.0, 3.0, "哦这都是要钱的买最下面的吗", 0.9, [], speaker="S01")]
    offsets = repair_hanging_attribute_boundary_offsets(batch, [7, 13])
    assert 7 in offsets


def test_final_cue_merge_hanging_tails():
    cues = merge_hanging_attribute_cues(
        [
            SubtitleCue(1, 0.0, 1.3, "我们有300万的", speaker="S01"),
            SubtitleCue(2, 1.3, 2.5, "启动资金啊", speaker="S01"),
            SubtitleCue(3, 8.4, 9.7, "那我们就直接进入一个", speaker="S01"),
            SubtitleCue(4, 9.7, 10.8, "珊瑚场啊", speaker="S01"),
        ]
    )
    texts = [cue.text for cue in cues]
    assert "我们有300万的启动资金啊" in texts
    assert any("珊瑚场" in text and "进入" in text for text in texts)
