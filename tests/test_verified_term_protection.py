"""P1-3 回归测试：已核验词保护不变量。

安全不变量：baseline 中已确认的 verified/protected term，candidate 对
term 本体产生删除/插入/替换/重排/部分截断等字符级破坏时，不能因
prefix/suffix/alias 残留命中而视为已核验；只有满足独立 ASR 证据门槛
（≥2 路独立证据，count_independent_asr_supports 语义）才允许接受修改。
"""

import pytest

import subtitle_core  # noqa: F401
from twobyteasr.subtitle_rules.polishing import filter_untrusted_polished_text

BASELINE = "我们进入音乐区域开始演出"
VERIFIED = ["音乐区域"]


def _judge(candidate, alternates, verified=VERIFIED, baseline=BASELINE):
    """filter_untrusted 裁决：放行返回 candidate，拒绝返回 baseline。"""
    return filter_untrusted_polished_text(baseline, candidate, alternates, verified)


# ---------------------------------------------------------------- 12 条主矩阵

def test_delete_first_char_without_evidence_is_rejected():
    """1. 删除首字，无独立证据 → 拒绝。"""
    assert _judge("我们进入乐区域开始演出", ["音乐区域", ""]) == BASELINE


def test_delete_last_char_without_evidence_is_rejected():
    """2. 删除尾字，无独立证据 → 拒绝。"""
    assert _judge("我们进入音乐区开始演出", ["音乐区域", ""]) == BASELINE


def test_delete_middle_char_without_evidence_is_rejected():
    """3. 删除中间字，无独立证据 → 拒绝。"""
    assert _judge("我们进入音区域开始演出", ["音乐区域", ""]) == BASELINE


def test_insert_prefix_char_without_evidence_is_rejected():
    """4. 插入字符，无独立证据 → 拒绝。"""
    assert _judge("我们进入音音乐区域开始演出", ["音乐区域", ""]) == BASELINE


def test_replace_char_without_evidence_is_rejected():
    """5. 替换字符，无独立证据 → 拒绝。"""
    assert _judge("我们进入音乐地区开始演出", ["音乐区域", ""]) == BASELINE


def test_reorder_without_evidence_is_rejected():
    """6. 字符重排，无独立证据 → 拒绝。"""
    assert _judge("我们进入区域音乐开始演出", ["音乐区域", ""]) == BASELINE


def test_unchanged_term_passes():
    """7. 完全未修改 → 正常放行。"""
    assert _judge("我们进入音乐区域开始演出", ["音乐区域", ""]) == "我们进入音乐区域开始演出"


def test_adjacent_edit_keeping_term_intact_passes():
    """8. 编辑在 term 邻近位置、term 本体完整 + 两路独立证据 → 放行。

    普通词替换本身也要求两路独立证据（产品规则），因此 alternates 给两路。
    """
    assert (
        _judge("我们进到音乐区域开始演出", ["进到音乐区域", "进到音乐区域"])
        == "我们进到音乐区域开始演出"
    )


def test_modified_term_with_two_independent_evidences_passes():
    """9. term 被修改 + FireRed-AED 与复核 ASR 两路独立证据支持 → 允许。"""
    assert (
        _judge(
            "我们进入乐区域开始演出",
            ["我们进入乐区域开始", "我们进入乐区域开始"],
        )
        == "我们进入乐区域开始演出"
    )


def test_modified_term_with_firered_plus_alternate_copy_is_rejected():
    """10. term 被修改 + FireRed-AED 与 alternate 副本（1 路独立）→ 拒绝。"""
    assert _judge("我们进入乐区域开始演出", ["我们进入乐区域开始", ""]) == BASELINE


def test_modified_term_with_firered_plus_llm_copy_is_rejected():
    """11. term 被修改 + FireRed-AED 与 FireRed-LLM（1 路独立）→ 拒绝。"""
    assert _judge("我们进入乐区域开始演出", ["我们进入乐区域开始", ""]) == BASELINE


def test_modified_term_with_only_llm_is_rejected():
    """12. 只有 FireRed-LLM 支持（0 路独立）→ 拒绝。"""
    assert _judge("我们进入乐区域开始演出", ["", ""]) == BASELINE


# ---------------------------------------------------------------- 边界

def test_two_character_verified_term_delete_is_rejected():
    """边界：2 字 verified term 被破坏 → 拒绝。"""
    assert (
        _judge(
            "我们进入域开始演出",
            ["区域", ""],
            verified=["区域"],
            baseline="我们进入区域开始演出",
        )
        == "我们进入区域开始演出"
    )


def test_term_at_sentence_start_delete_is_rejected():
    """边界：term 位于句首，删除首字 → 拒绝。"""
    baseline = "音乐区域开始演出"
    assert _judge("乐区域开始演出", ["音乐区域", ""], baseline=baseline) == baseline


def test_term_at_sentence_end_delete_is_rejected():
    """边界：term 位于句尾，删除首字 → 拒绝。"""
    baseline = "我们进入音乐区域"
    assert _judge("我们进入乐区域", ["音乐区域", ""], baseline=baseline) == baseline


def test_two_occurrences_first_broken_is_rejected():
    """边界：term 出现两次、编辑破坏第一处 → 拒绝（不得因第二处完整而放行）。"""
    baseline = "音乐区域和音乐区域"
    candidate = "乐区域和音乐区域"
    assert _judge(candidate, ["音乐区域", ""], baseline=baseline) == baseline


def test_two_occurrences_second_broken_is_rejected():
    """边界：term 出现两次、编辑破坏第二处 → 拒绝。"""
    baseline = "音乐区域和音乐区域"
    candidate = "音乐区域和乐区域"
    assert _judge(candidate, ["音乐区域", ""], baseline=baseline) == baseline


def test_two_occurrences_edit_other_text_passes():
    """边界：term 出现两次、编辑的是无关文本（两路独立证据）、两处都完整 → 放行。"""
    baseline = "音乐区域和音乐区域都不错"
    candidate = "音乐区域和音乐区域都很好"
    assert (
        _judge(candidate, ["都很好", "都很好"], baseline=baseline)
        == candidate
    )


def test_delete_empty_span_coordinate_is_handled():
    """边界：删除型编辑产生 empty span，不得被 suffix alias 命中放行。

    删除"音"后空 span 落在幸存后缀"乐区域"内（P1-3 实测根因场景）。
    """
    assert _judge("我们进入乐区域开始演出", ["音乐区域", ""]) == BASELINE


def test_multi_verified_terms_one_broken_is_rejected():
    """边界：多个 verified term 中一个被破坏 → 拒绝。"""
    baseline = "我们进入音乐区域来到新手村"
    candidate = "我们进入乐区域来到新手村"
    assert (
        _judge(candidate, ["音乐区域", ""], verified=["音乐区域", "新手村"], baseline=baseline)
        == baseline
    )
