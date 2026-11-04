# -*- coding: utf-8 -*-
"""2026-09-03 识别召回质量轮的守护测试。

三个根因的回归锚点：
1. MOSS 同说话人“长段文本部分包含相邻短段”的重复未被剥除 → 下游同说话人
   cue 碰撞被推成 0.35s 阶梯串（当单实测最高 42.9 字/秒、成段文字重复）。
2. 断句批次 5000 字/45s 超时在 CLI 账号会话传输下连锁熔断（9/13 批次回退）。
3. 识别记录页使用静态 HISTORY_QSS，不随应用主题刷新。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from difflib import SequenceMatcher

import moss_firered_pipeline as pipeline
import subtitle_core as legacy
from subtitle_core import (
    GROUP_API_BATCH_MAX_CHARS,
    GROUP_API_BATCH_MAX_CUES,
    GROUPING_API_TIMEOUT_SECONDS,
    NORMALIZE_MAX_CHARS_PER_SECOND,
    SubtitleCue,
    normalize_cue_times,
)
from twobyteasr.subtitle_rules.correction import split_items_for_api


S03_LONG = (
    "嗯我说一下我的看法吧我个人觉得幽灵它并不是所有队伍都能塞进去的就是我个人认为它是一个控能队的一个偏向于中期的打手也不是终端首先作为终端的话它的这个抗性其实并不太行然后特性的话也不能也并不能增加力度所以说作为终端来说我觉得它是不够格的而且它速度也就是九十五的速度真的是不是很快而且为什么说它必须得进中必须得进控能队而不能进常规的队伍呢？因为常规队伍的话这个你的这个被动的主动权掌握在对方手中对方就大大方方给你摔炮我就不聚能那你就很长时间都不能上场就非常的难受所以说你一定要你的队伍里至少得有那么一两只精灵"
)
S03_SHORTS = [
    (1607.98, 1612.31, "因为常规队伍的话这个你的这个被动的主动权掌握在对方手中"),
    (1612.46, 1617.12, "对方就大大方方给你摔炮我就不聚能那你就很长时间都不能上场就非常的难受"),
    (1617.34, 1623.12, "所以说你一定要你的队伍里至少得有那么一两只精灵我觉得得去限制对方的能耗让对方不得不聚能"),
]

S02_LONG = (
    "也就是说你聚能和使用状态技能是不会掉血的只有攻击才会掉血那不知道会不会给狼王贪婪这个技能啊如果给贪婪的话那狼王在开一个光魂或者失能印记的情况"
)
S02_SHORTS = [
    (159.91, 163.27, "也就是说你聚能和使用状态技能是不会掉血的"),
    (163.28, 164.41, "只有攻击才会掉血"),
    (164.9, 167.8, "那不知道会不会给狼王贪婪这个技能啊"),
    (167.9, 171.4, "如果给贪婪的话那狼王"),
]


def _segments(rows, speaker):
    return [
        {"start": start, "end": end, "speaker": speaker, "text": text}
        for start, end, text in rows
    ]


def _speaker_concat(segments, speaker):
    return "".join(
        legacy.content_only(item["text"])
        for item in segments
        if str(item.get("speaker") or "S00") == speaker
    )


def _longest_self_duplicate(text):
    """返回文本内部重复出现的最长连续子串长度（<10 视为无重复）。"""
    best = 0
    max_len = min(len(text) // 2, 80)
    for length in range(10, max_len + 1):
        seen = set()
        found = False
        for start in range(len(text) - length + 1):
            sub = text[start : start + length]
            if sub in seen:
                found = True
                break
            seen.add(sub)
        if found:
            best = length
        elif best:
            break
    return best


def test_s03_tail_cover_is_stripped_to_unique_prefix():
    segments = _segments(
        [(1582.01, 1620.01, S03_LONG)] + S03_SHORTS, "S03"
    )
    kept = pipeline._drop_redundant_cover_segments(segments, legacy)

    texts = [item["text"] for item in kept]
    # 三个短段原样保留，长段只剩未重复的前缀。
    assert len(kept) == 4
    assert _longest_self_duplicate(_speaker_concat(kept, "S03")) < 10
    long_kept = next(
        item for item in kept if len(legacy.content_only(item["text"])) > 60
    )
    assert long_kept["text"].startswith("嗯我说一下我的看法吧")
    assert "因为常规队伍" not in legacy.content_only(long_kept["text"])
    # 截断点贴到第一个重复短段的句首，不再覆盖短段时间窗。
    assert abs(long_kept["end"] - 1607.98) < 0.01
    for start, end, text in S03_SHORTS:
        assert any(
            item["text"] == text and abs(item["start"] - start) < 0.001
            for item in kept
        )


def test_s02_prefix_cover_pieces_are_stripped():
    segments = _segments(
        [(160.0, 181.21, S02_LONG)] + S02_SHORTS, "S02"
    )
    kept = pipeline._drop_redundant_cover_segments(segments, legacy)

    assert _longest_self_duplicate(_speaker_concat(kept, "S02")) < 10
    long_kept = next(
        item for item in kept if "光魂" in item["text"] or "印记" in item["text"]
    )
    # 长段剥掉与前四个短段重复的头部，只保留独有的尾部内容。
    assert "也就是说你聚能" not in legacy.content_only(long_kept["text"])
    assert "只有攻击才会掉血" not in legacy.content_only(long_kept["text"])
    assert legacy.content_only(long_kept["text"])
    assert long_kept["start"] >= 171.4 - 0.01


def test_identical_duplicate_pair_single_piece_is_dropped():
    text = "配技能的时候都会考虑一个能量规划"
    segments = _segments(
        [(1758.1, 1762.4, text), (1760.0, 1762.4, text)], "S03"
    )
    kept = pipeline._drop_redundant_cover_segments(segments, legacy)
    assert len(kept) == 1
    assert kept[0]["text"] == text


def test_different_text_time_overlap_is_untouched():
    segments = _segments(
        [
            (10.0, 20.0, "这一段讲的是完全不同的内容没有任何重复字句"),
            (15.0, 19.0, "另一个短段讲另一件事"),
        ],
        "S01",
    )
    kept = pipeline._drop_redundant_cover_segments(segments, legacy)
    assert sorted(item["text"] for item in kept) == sorted(
        item["text"] for item in segments
    )


def test_original_caller_dicts_are_not_mutated():
    segments = _segments([(1582.01, 1620.01, S03_LONG)] + S03_SHORTS, "S03")
    snapshot = [dict(item) for item in segments]
    pipeline._drop_redundant_cover_segments(segments, legacy)
    assert [dict(item) for item in segments] == snapshot


def test_normalize_push_respects_reading_rate():
    # 同说话人 10 条字幕共享同一时间戳：normalize 推挤后不得出现
    # “8~15 字只显示 0.35s”的阶梯串（2026-09-03 实测 42.9 字/秒）。
    texts = [
        "因为常规队伍的话",
        "这个你的这个被动的",
        "主动权掌握在对方手中",
        "对方就大大方方给你摔炮",
        "我就不聚能那你就很长时间",
        "都不能上场就非常的难受",
        "所以说你一定要你的队伍",
        "里至少得有那么一两只",
        "精灵我觉得得去限制对方的",
        "能耗让对方不得不聚能",
    ]
    cues = [
        SubtitleCue(index + 1, 1620.0, 1620.0 + 0.2, text, speaker="S03")
        for index, text in enumerate(texts)
    ]
    normalize_cue_times(cues, timeline_fps=60.0)
    for cue in cues:
        duration = cue.end - cue.start
        length = legacy.display_length(cue.text)
        assert duration >= min(
            5.0, length / NORMALIZE_MAX_CHARS_PER_SECOND
        ) - 0.02, f"{cue.text} 仅 {duration:.2f}s"
        assert length / duration <= NORMALIZE_MAX_CHARS_PER_SECOND + 0.5
    # 单条时序仍然单调不重叠。
    ordered = sorted(cues, key=lambda cue: cue.start)
    for previous, current in zip(ordered, ordered[1:]):
        assert previous.end <= current.start + 1e-6


def test_grouping_stage_uses_dedicated_smaller_batches():
    assert GROUP_API_BATCH_MAX_CUES == 10
    assert GROUP_API_BATCH_MAX_CHARS == 1800
    assert GROUPING_API_TIMEOUT_SECONDS >= 120
    # 30 条 80 字的短句按断句上限拆分后，单批不超过 10 条 / 1800 字。
    class _Item:
        def __init__(self, index):
            self.text = f"第{index}条测试字幕" + "字" * 72

    batches = split_items_for_api(
        [_Item(index) for index in range(30)],
        max_cues=GROUP_API_BATCH_MAX_CUES,
        max_chars=GROUP_API_BATCH_MAX_CHARS,
    )
    assert len(batches) >= 3
    for batch in batches:
        assert len(batch) <= GROUP_API_BATCH_MAX_CUES
        assert sum(len(item.text) + 32 for item in batch) <= GROUP_API_BATCH_MAX_CHARS


def test_mid_word_repair_moves_cut_across_breath_gap():
    # 2026-09-03 用户反馈“缺首字挂在上一块末尾”：651.7s 真实案例。
    # 两段间有 0.9s 换气间隙（旧门 >0.75s 直接放弃），词“面对”被 MOSS 原始
    # 段边界切开。挪切点不合并字幕，必须跨换气级间隙修复。
    from twobyteasr.subtitle_rules.segmentation import repair_mid_word_adjacent_cues

    left = SubtitleCue(1, 651.68, 654.60, "就是封住更多的这个你的这个抵抗面", speaker="S02")
    right = SubtitleCue(2, 655.50, 657.40, "对对你必须同时抵抗他俩", speaker="S02")
    # A text-only SRT cannot supply the time of the moved word. This fixture
    # now supplies explicit constructed word anchors; it is not an audio audit.
    from twobyteasr.recognition.transcript_data import SpeechSegment, WordUnit
    text = legacy.content_only(left.text + right.text)
    words = [WordUnit(651.68+i*.17,651.68+(i+1)*.17,char,1) for i,char in enumerate(text)]
    source = SpeechSegment(1,left.start,right.end,text,1,words,speaker='S02')
    repaired = repair_mid_word_adjacent_cues([left, right], [source])

    assert len(repaired) == 2
    joined = legacy.content_only(repaired[0].text) + legacy.content_only(repaired[1].text)
    assert joined == legacy.content_only(
        "就是封住更多的这个你的这个抵抗面对对你必须同时抵抗他俩"
    )
    # “面对”必须完整落在同一条里。
    assert "面对" in legacy.content_only(repaired[0].text) or "面对" in legacy.content_only(
        repaired[1].text
    )
    for cue in repaired:
        assert cue.end - cue.start <= 5.05
        assert cue.end > cue.start


def test_mid_word_repair_untouched_across_long_silence():
    from twobyteasr.subtitle_rules.segmentation import repair_mid_word_adjacent_cues

    left = SubtitleCue(1, 100.0, 103.0, "我这边已经讲完了抵抗面", speaker="S01")
    right = SubtitleCue(2, 108.0, 110.0, "对对你必须同时抵抗", speaker="S01")
    repaired = repair_mid_word_adjacent_cues([left, right])
    assert [cue.text for cue in repaired] == [left.text, right.text]


def test_mid_word_repair_respects_timing_lock():
    from twobyteasr.subtitle_rules.segmentation import repair_mid_word_adjacent_cues

    left = SubtitleCue(
        1, 651.68, 654.60, "就是封住更多的这个你的这个抵抗面",
        timing_locked=True, speaker="S02",
    )
    right = SubtitleCue(2, 654.70, 656.60, "对对你必须同时抵抗他俩", speaker="S02")
    repaired = repair_mid_word_adjacent_cues([left, right])
    assert [cue.text for cue in repaired] == [left.text, right.text]


def test_fallback_group_resplits_long_segments_for_comfort():
    # 本地回退不再保留 13-16 字的 MOSS 原句：单行放不下会被播放器折行。
    from twobyteasr.subtitle_rules.grouping import fallback_group

    text = "然后北极熊教练组的阵容组建部分"
    segment = legacy.SpeechSegment(1, 30.0, 33.2, text, 0.9, [], speaker="S01")
    cues = fallback_group([segment])
    assert len(cues) >= 2
    assert all(legacy.display_length(cue.text) <= 12 for cue in cues)
    assert "".join(legacy.content_only(cue.text) for cue in cues) == legacy.content_only(text)
    for cue in cues:
        assert cue.end > cue.start


def test_fallback_group_keeps_short_utterances_verbatim():
    from twobyteasr.subtitle_rules.grouping import fallback_group

    segment = legacy.SpeechSegment(1, 10.0, 12.0, "到底有哪些值得关注的地方", 0.9, [], speaker="S01")
    cues = fallback_group([segment])
    assert [cue.text for cue in cues] == ["到底有哪些值得关注的地方"]


def test_provider_timeout_does_not_open_circuit(monkeypatch):
    import threading
    import time

    import pytest
    from twobyteasr.providers.ai_providers import AITransport, AIProviderError, ProviderStatus
    from twobyteasr.providers.provider_service import (
        ProviderHealthState,
        ProviderService,
    )
    from twobyteasr.system.resource_governor import ResourceGovernor

    class _TimeoutAdapter:
        provider_id = "fixture"
        model = "fixture-model"

        def validate(self, **_kwargs):
            return ProviderStatus(True, True, "ready")

        def complete(self, _messages, **_kwargs):
            raise AIProviderError("AI CLI 请求超时。", category="timeout")

        def structured_complete(self, _messages, _schema, **_kwargs):
            raise AIProviderError("AI CLI 请求超时。", category="timeout")

    monkeypatch.setattr(
        "twobyteasr.providers.provider_service.adapter_for_stage",
        lambda *_args, **_named: _TimeoutAdapter(),
    )
    service = ProviderService(
        governor=ResourceGovernor(), circuit_failures=2, circuit_seconds=30.0
    )
    settings = {
        "models": {
            "group_transport": AITransport.GROK_CLI.value,
            "group_model": "fixture-model",
        }
    }
    client = service.client_for_stage(settings, "group")
    for _ in range(3):
        with pytest.raises(AIProviderError, match="超时"):
            client.complete([{"role": "user", "content": "x"}], timeout=0.5)
    health = client.health()
    assert health.state is not ProviderHealthState.DEGRADED


def test_history_page_qss_follows_active_theme():
    from PySide6.QtWidgets import QApplication
    from twobyteasr.recognition.recognition_history import build_history_page_qss
    from twobyteasr.design.ui_theme import theme_definition

    QApplication.instance() or QApplication([])
    light = build_history_page_qss(theme_definition("warm"))
    dark = build_history_page_qss(theme_definition("slate"))
    assert light != dark
    # 深色主题下不允许残留任何“暖色浅底”字面量。
    for literal in ("#fffaf2", "#f7f3eb", "#f4f0e7", "#fbefda", "#f6e5e0"):
        assert literal not in dark
