# -*- coding: utf-8 -*-
from subtitle_core import SubtitleCue, merge_isolated_two_character_cues


def _texts(cues):
    return [cue.text for cue in cues]


def test_real_eagle_hall_two_character_cues_attach_naturally():
    cues = merge_isolated_two_character_cues(
        [
            SubtitleCue(1, 20.58, 22.95, "来自昨日的前线记者", speaker="S01"),
            SubtitleCue(2, 22.95, 23.75, "阿明", speaker="S01"),
            SubtitleCue(3, 23.75, 25.18, "他于7月28日", speaker="S01"),
            SubtitleCue(4, 43.72, 45.75, "辞去前线记者职位", speaker="S02"),
            SubtitleCue(5, 47.98, 48.70, "并且", speaker="S02"),
            SubtitleCue(6, 49.53, 50.87, "全心全力训练", speaker="S02"),
        ]
    )
    assert _texts(cues) == [
        "来自昨日的前线记者阿明",
        "他于7月28日",
        "辞去前线记者职位",
        "并且全心全力训练",
    ]


def test_short_reply_and_vocative_attach_to_following_same_speaker_line():
    cues = merge_isolated_two_character_cues(
        [
            SubtitleCue(1, 57.05, 58.98, "现在醒了吗 该上班了", speaker="S01"),
            SubtitleCue(2, 58.85, 59.38, "好的", speaker="S02"),
            SubtitleCue(3, 59.38, 60.82, "接下来由机甲梦碎的", speaker="S02"),
            SubtitleCue(4, 125.15, 126.40, "这又是什么地方", speaker="S01"),
            SubtitleCue(5, 127.58, 128.42, "朋友", speaker="S02"),
            SubtitleCue(6, 128.42, 129.27, "在漫漫人生道路", speaker="S02"),
            SubtitleCue(7, 240.52, 242.12, "接下来是不是要去", speaker="S01"),
            SubtitleCue(8, 242.12, 242.55, "没错", speaker="S02"),
            SubtitleCue(9, 242.55, 243.90, "接下来就带大家去看一下", speaker="S02"),
        ]
    )
    assert _texts(cues) == [
        "现在醒了吗 该上班了",
        "好的 接下来由机甲梦碎的",
        "这又是什么地方",
        "朋友 在漫漫人生道路",
        "接下来是不是要去",
        "没错 接下来就带大家去看一下",
    ]


def test_two_character_cue_does_not_cross_speaker_interruption_or_limits():
    cues = merge_isolated_two_character_cues(
        [
            SubtitleCue(1, 0.0, 1.0, "上一句", speaker="S01"),
            SubtitleCue(2, 0.9, 1.2, "插话", speaker="S02"),
            SubtitleCue(3, 1.2, 1.5, "但是", speaker="S01"),
            SubtitleCue(4, 1.4, 1.8, "又插话", speaker="S02"),
            SubtitleCue(5, 1.8, 2.4, "后一句", speaker="S01"),
            SubtitleCue(6, 10.0, 10.4, "好的", speaker="S01"),
            SubtitleCue(7, 12.0, 13.0, "停顿后一句", speaker="S01"),
        ]
    )
    assert _texts(cues) == [
        "上一句", "插话", "但是", "又插话", "后一句", "好的", "停顿后一句"
    ]
