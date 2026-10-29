"""Interjection anti-split rules: “哎 呦” must merge back to “哎呦” in final
cues, matching the human-edited references (8月9日.srt)."""

from __future__ import annotations

import pytest

from twobyteasr.subtitle_rules.segmentation import (
    INTERJECTION_MERGES,
    merge_split_interjections,
    merge_split_interjections_in_cues,
    space_separate_interjections,
)


def test_split_interjections_merge():
    # Real cases from the human vs AI reference comparison
    assert merge_split_interjections("哎 呦打不动这这根本就打不动") == "哎呦打不动这这根本就打不动"
    assert merge_split_interjections("哎 呦但是这个龙") == "哎呦但是这个龙"
    assert merge_split_interjections("哎 呦 哎 呦可以吗哎呀") == "哎呦 哎呦可以吗哎呀"


def test_interjections_are_spaced_out():
    # 人工稿观感：每个语气词独立、空格分隔
    assert space_separate_interjections("哎呦 哎呦可以吗哎呀") == "哎呦 哎呦 可以吗 哎呀"
    assert space_separate_interjections("哎呦打不动这这根本就打不动") == "哎呦 打不动这这根本就打不动"
    assert space_separate_interjections("哎呀对嘛 这才对嘛") == "哎呀 对嘛 这才对嘛"
    assert space_separate_interjections("哦豁") == "哦豁"
    assert space_separate_interjections("这都赢啊") == "这都赢啊"  # 单字不处理
    assert space_separate_interjections("ok哎呀") == "ok哎呀"  # 非汉字邻接不处理


def test_cue_pipeline_merges_then_spaces():
    from twobyteasr.recognition.transcript_data import SubtitleCue

    cues = [
        SubtitleCue(cue_id=1, start=0.0, end=1.0, text="哎 呦 哎 呦可以吗哎呀"),
        SubtitleCue(cue_id=2, start=1.0, end=2.0, text="这都赢啊"),
        SubtitleCue(cue_id=3, start=2.0, end=3.0, text="哎 那看能不能比较有默契啊"),
    ]
    merge_split_interjections_in_cues(cues)
    assert cues[0].text == "哎呦 哎呦 可以吗 哎呀"
    assert cues[1].text == "这都赢啊"
    assert cues[2].text == "哎 那看能不能比较有默契啊"


def test_split_interjections_with_punctuation_merge():
    assert merge_split_interjections("哎，呦") == "哎呦"
    assert merge_split_interjections("哎 哟") == "哎哟"
    assert merge_split_interjections("诶 呀") == "诶呀"
    assert merge_split_interjections("哦 豁") == "哦豁"


def test_non_interjection_pairs_stay_untouched():
    # Whitelist only: these must not merge
    assert merge_split_interjections("哎 那看能不能比较有默契啊") == "哎 那看能不能比较有默契啊"
    assert merge_split_interjections("哦 呀") == "哦 呀"
    assert merge_split_interjections("哎 啊") == "哎 啊"
    assert merge_split_interjections("哎呀 对嘛") == "哎呀 对嘛"  # already merged
    assert merge_split_interjections("哦 耶") == "哦 耶"


def test_cue_list_merging_in_place():
    from twobyteasr.recognition.transcript_data import SubtitleCue

    cues = [
        SubtitleCue(cue_id=1, start=0.0, end=1.0, text="哎 呦但是这个龙"),
        SubtitleCue(cue_id=2, start=1.0, end=2.0, text="这都赢啊"),
        SubtitleCue(cue_id=3, start=2.0, end=3.0, text="哎 那看能不能比较有默契啊"),
    ]
    merge_split_interjections_in_cues(cues)
    assert cues[0].text == "哎呦 但是这个龙"
    assert cues[1].text == "这都赢啊"
    assert cues[2].text == "哎 那看能不能比较有默契啊"


def test_merge_table_is_consistent():
    for (first, second), merged in INTERJECTION_MERGES.items():
        assert merged == first + second
        assert merge_split_interjections(f"{first} {second}") == merged
