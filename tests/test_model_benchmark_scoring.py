"""模型工坊基准组评分引擎测试（2026-09-18 轮）。

评分规则：同组最佳=100；sqrt 比值换算；越差越低；缺失不计分；
单来源组不上卡；主组唯一；对齐用 AAS 不混 CER；API 无数据不编分。
"""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from twobyteasr.local_models.model_benchmarks import (  # noqa: E402
    DEFAULT_SCENE,
    GROUPS,
    SCENES,
    ReferenceRow,
    assert_primary_groups_unique,
    best_score,
    groups_for,
    groups_for_model,
    score_in_group,
    secondary_record,
)
from twobyteasr.local_models.model_benchmarks import ComparisonGroup  # noqa: E402


BY_ID = {group.group_id: group for group in GROUPS}


# ── 基础不变量 ────────────────────────────────────────────────

def test_primary_group_unique_per_scene_and_kind():
    assert_primary_groups_unique()  # must not raise


def test_all_entries_are_finite_nonnegative_numbers():
    for group in GROUPS:
        for key, value in group.entries.items():
            assert isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
        for row in group.reference_rows:
            assert isinstance(row.value, (int, float)) and math.isfinite(row.value)


def test_groups_carry_sources_and_verification():
    for group in GROUPS:
        assert group.source_url.startswith("http"), group.group_id
        assert group.verified
        assert group.protocol
        assert group.direction in {"lower", "higher"}
        assert group.kind in {"accuracy", "speed"}


# ── 组内评分行为 ─────────────────────────────────────────────

def test_best_in_group_scores_100():
    result = score_in_group(BY_ID["zh_mandarin4_firered"], "firered_llm")
    assert result is not None and result["score"] == 100 and result["exact"] == 100.0


def test_worse_error_rate_never_scores_higher():
    group = BY_ID["zh_mandarin4_firered"]
    ordered = sorted(
        ((key, score_in_group(group, key)) for key in group.entries),
        key=lambda item: item[1]["value"],
    )
    scores = [item[1]["score"] for item in ordered]
    exacts = [item[1]["exact"] for item in ordered]
    assert scores == sorted(scores, reverse=True)
    assert exacts == sorted(exacts, reverse=True)
    assert ordered[0][1]["score"] == 100


def test_sqrt_ratio_values():
    group = BY_ID["zh_mandarin4_firered"]
    assert score_in_group(group, "firered")["score"] == 97  # 100*sqrt(2.89/3.05)
    assert score_in_group(group, "qwen_local")["score"] == 88  # 100*sqrt(2.89/3.76)


def test_higher_is_better_speed_group():
    group = BY_ID["en_openasr_rtfx"]
    assert score_in_group(group, "canary_qwen")["score"] == 100
    assert score_in_group(group, "whisper")["score"] == 69  # 100*sqrt(200.19/418)
    assert score_in_group(group, "glm_asr_nano")["score"] == 59


def test_integer_tie_keeps_exact_order():
    group = BY_ID["zh_dialect19_firered"]
    firered = score_in_group(group, "firered")
    qwen = score_in_group(group, "qwen_local")
    assert firered["score"] == qwen["score"] == 99  # 同分展示
    assert firered["exact"] > qwen["exact"]  # 未取整值仍可稳定排序


def test_external_reference_defines_best():
    # LibriSpeech 组的组内最佳是外部 GPT-4o 1.39，注册模型分数据此下压。
    group = BY_ID["en_librispeech_clean_qwen"]
    result = score_in_group(group, "qwen_local")
    assert result["score"] == 92  # 100*sqrt(1.39/1.63)
    assert all(row.value < group.entries["qwen_local"] for row in group.reference_rows[:2])


# ── 退化与异常值 ─────────────────────────────────────────────

def _synthetic(entries, reference_rows=(), direction="lower", kind="accuracy"):
    return ComparisonGroup(
        group_id="synthetic",
        scene="zh",
        kind=kind,
        label="synthetic",
        label_en="synthetic",
        metric="CER",
        unit="%",
        direction=direction,
        protocol="test",
        source_name="test",
        source_url="https://example.com",
        source_type="official_same_table",
        verified="2026-09-18",
        entries=entries,
        reference_rows=reference_rows,
    )


def test_best_error_rate_zero_degenerates_to_floor():
    group = _synthetic({"a": 0.0, "b": 5.0})
    assert score_in_group(group, "a")["score"] == 100
    assert score_in_group(group, "b")["score"] == 1  # 不造中间分


def test_all_zero_scores_all_100():
    group = _synthetic({"a": 0.0, "b": 0.0})
    assert score_in_group(group, "a")["score"] == 100
    assert score_in_group(group, "b")["score"] == 100


def test_invalid_and_missing_values_never_score():
    group = _synthetic({"a": float("nan"), "b": -1.0, "c": 2.0, "d": None})
    assert score_in_group(group, "a") is None
    assert score_in_group(group, "b") is None
    assert score_in_group(group, "d") is None
    assert score_in_group(group, "c") is not None


def test_single_source_group_is_flagged_solo_and_not_card_scored():
    group = BY_ID["zh_aishell1_sensevoice_paper"]
    result = score_in_group(group, "sensevoice")
    assert result is not None and result["solo"] is False  # 有同表 Whisper 对照
    # 但该组不是主组：卡片评分不取它。
    assert group.card_score is False
    assert best_score("sensevoice", "accuracy", "zh") is None


def test_true_solo_group_without_reference_rows_flags_solo():
    group = _synthetic({"a": 2.0})
    assert score_in_group(group, "a")["solo"] is True


# ── 场景与展示选择 ───────────────────────────────────────────

def test_scene_switch_changes_group_not_scores_of_other_groups():
    assert best_score("moss", "accuracy", "zh") is None  # 中文通用场景无 MOSS 同组
    assert best_score("moss", "accuracy", "zh_long")["score"] == 100
    assert best_score("moss", "accuracy", "en") is None


def test_alignment_scene_uses_aas_never_cer():
    for group in groups_for("align"):
        assert group.metric == "AAS"
        assert "CER" not in group.metric and "WER" not in group.metric
    assert best_score("qwen_aligner", "accuracy", "align")["score"] == 100


def test_english_scene_scores_checkpoint_level_data():
    assert best_score("canary_qwen", "accuracy", "en")["score"] == 100
    assert best_score("whisper", "accuracy", "en")["score"] == 85
    assert best_score("whisper", "speed", "en")["score"] == 69
    # groq 托管同一 turbo checkpoint：准确度随模型转移，速度不互推。
    assert best_score("groq_api", "accuracy", "en")["score"] == 85
    assert best_score("groq_api", "speed", "en") is None


def test_api_models_without_public_data_stay_unscored():
    for key in ("qwen_api", "qwen_audio_asr_flash", "qwen_audio_filetrans",
                "mai_transcribe_2_word", "openai_api", "custom_asr_api"):
        for scene in SCENES:
            assert best_score(key, "accuracy", scene) is None, key
            assert best_score(key, "speed", scene) is None, key


def test_secondary_record_is_display_only():
    group = secondary_record("funasr_nano", "accuracy", "zh")
    assert group is not None and not group.card_score
    assert group.entries["funasr_nano"] == 6.35


def test_no_cross_protocol_merge_on_cards():
    # zh 主组只含 FireRed 同表三家；whisper(turbo)/sensevoice/paraformer 不进主组。
    primary = [g for g in groups_for("zh", "accuracy") if g.card_score]
    assert len(primary) == 1
    entries = set(primary[0].entries)
    assert entries == {"firered_llm", "firered", "qwen_local"}
    # Qwen 官方表与 FireRed 官方表是两个不同 group_id，绝不合并。
    assert "zh_mandarin4_firered" in BY_ID and "zh_ws_net_qwen" in BY_ID


def test_scoring_is_pure_and_offline():
    # 纯数据模块：重复调用结果稳定（搜索/筛选/安装态不可能改变分数）。
    first = best_score("firered", "accuracy", DEFAULT_SCENE)
    second = best_score("firered", "accuracy", DEFAULT_SCENE)
    assert first["score"] == second["score"] == 97
    for group in GROUPS:
        for key in group.entries:
            result = score_in_group(group, key)
            if result is not None:
                assert 1 <= result["score"] <= 100


def test_every_model_group_reference_exists():
    registered = {
        "moss", "firered", "qwen_local", "firered_llm", "glm_asr_nano",
        "canary_qwen", "omni_asr_llm_7b", "sensevoice", "paraformer",
        "whisper", "funasr_nano", "qwen_aligner", "qwen_api",
        "qwen_audio_asr_flash", "groq_api", "openai_api",
        "mai_transcribe_2_word", "qwen_audio_filetrans", "custom_asr_api",
    }
    for group in GROUPS:
        for key in group.entries:
            assert key in registered, f"unknown model key {key} in {group.group_id}"
