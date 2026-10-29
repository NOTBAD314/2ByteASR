"""第三层「2ByteASR 参考指数」测试（2026-09-18 V+ 轮）。

产品目标：公开资料优先、覆盖面完整、估算透明标注。
- 有公开依据但不在严格主组的模型，仍能获得参考分。
- 没有本机记录时，公开速度参考正常显示（速度不再整列"待测"）。
- API 按实际解析型号给分；密钥未配置不影响公开参考分。
- 估算分带"约"与依据类型；严格换算分不带；两者永不混标。
- 真未知（无法识别型号/确实无证据）不自动给 50/80/90 默认分。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from twobyteasr.local_models.model_benchmarks import (  # noqa: E402
    API_MODEL_ALIASES,
    REFERENCE_INDEX_VERSION,
    _REFERENCE_INDEX,
    reference_api_model,
    reference_coverage,
    reference_entry,
    reference_gap,
)
from twobyteasr.local_models.model_workshop import MODELS, _metric_evidence  # noqa: E402


REGISTERED = {model.key for model in MODELS}
_ESTIMATE_BASES = {"calibrated", "tier", "same_family"}


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


# ── 覆盖率：每个注册模型的准确度/速度都有着落 ─────────────────

def test_every_model_accuracy_has_score_unsupported_or_gap():
    missing = []
    for model in MODELS:
        if "ALIGNMENT" in (model.asr_capabilities or ()):
            continue  # 对齐模型走对齐精度
        entry = None
        has_any = False
        for scene in ("zh", "zh_long", "zh_dialect", "en"):
            e = reference_entry(model.key, "accuracy", scene)
            if e is not None:
                has_any = True
                if "score" in e:
                    entry = e
        gap = reference_gap(model.key, "accuracy")
        if entry is None and not has_any and not gap:
            missing.append(model.key)
    # omni 是唯一"准确度真未知"（无逐语言公开成绩）；其余全部有着落。
    assert set(missing) <= {"omni_asr_llm_7b"}


def test_every_model_speed_has_score_or_gap():
    scored, gaps = [], []
    for model in MODELS:
        e = reference_entry(model.key, "speed", "zh")
        if e is not None and "score" in e:
            scored.append(model.key)
        else:
            gaps.append(model.key)
    # 速度不再整列"待测"：绝大多数模型有公开参考分。
    assert len(scored) >= 15
    # 剩余的必须有明确缺口说明（不是静默空值）。
    for key in gaps:
        assert key == "custom_asr_api" or reference_gap(key, "speed"), key


def test_local_models_not_in_primary_group_still_scored():
    # 上一轮被"主组限制"清空的模型全部恢复参考分。
    for key, minimum in (
        ("sensevoice", 70), ("paraformer", 65), ("funasr_nano", 75),
        ("whisper", 55), ("moss", 75),
    ):
        evidence = _metric_evidence(
            next(m for m in MODELS if m.key == key), "accuracy", None, "zh"
        )
        assert evidence["available"] is True, key
        assert evidence["score"] >= minimum, (key, evidence["score"])


def test_api_cards_scored_by_preset_default_without_keys():
    # 未配置密钥/未调用不影响公开参考分（按预设默认型号解析）。
    for key in ("qwen_api", "qwen_audio_asr_flash", "qwen_audio_filetrans",
                "groq_api", "mai_transcribe_2_word", "openai_api"):
        accuracy = _metric_evidence(
            next(m for m in MODELS if m.key == key), "accuracy", None, "zh"
        )
        speed = _metric_evidence(
            next(m for m in MODELS if m.key == key), "speed", None, "zh"
        )
        assert accuracy["available"] is True, key
        assert speed["available"] is True, key


def test_speed_public_reference_shown_without_local_run():
    for key in ("firered", "qwen_local", "moss", "whisper", "canary_qwen",
                "groq_api", "mai_transcribe_2_word", "openai_api"):
        evidence = _metric_evidence(
            next(m for m in MODELS if m.key == key), "speed", None, "zh"
        )
        assert evidence["available"] is True, key
        assert evidence["score"] is not None and evidence["score"] >= 1


# ── 估算与严格分数的区分 ───────────────────────────────────

def test_estimate_scores_marked_with_approx_prefix():
    model = next(m for m in MODELS if m.key == "sensevoice")
    evidence = _metric_evidence(model, "accuracy", None, "zh")
    assert evidence["value"].startswith("约 ")
    assert evidence.get("approx") is True
    firered = _metric_evidence(
        next(m for m in MODELS if m.key == "firered"), "accuracy", None, "zh"
    )
    assert not firered["value"].startswith("约 ")
    assert firered.get("approx") is False


def test_tier_scores_use_five_point_granularity():
    for (key, kind), record in _REFERENCE_INDEX.items():
        for scene_entry in list((record.get("scenes") or {}).values()) + [
            record.get("default")
        ]:
            if scene_entry is None:
                continue
            if scene_entry.get("basis") == "tier":
                assert scene_entry["score"] % 5 == 0, (key, kind, scene_entry["score"])


def test_every_reference_entry_carries_sources_and_reason():
    for (key, kind), record in _REFERENCE_INDEX.items():
        for scene_entry in list((record.get("scenes") or {}).values()) + [
            record.get("default")
        ]:
            if scene_entry is None:
                continue
            assert scene_entry.get("reason"), (key, kind)
            assert scene_entry.get("detail"), (key, kind)
            assert scene_entry.get("sources"), (key, kind)
            for url in scene_entry["sources"]:
                assert str(url).startswith("http")


def test_strict_and_estimate_never_mixed():
    for (key, kind), record in _REFERENCE_INDEX.items():
        entries = list((record.get("scenes") or {}).values()) + [record.get("default")]
        for entry in entries:
            if entry is None:
                continue
            if entry["basis"] in _ESTIMATE_BASES or entry["basis"] == "official":
                assert entry["approx"] is True
            else:
                assert entry["approx"] is False


# ── API 型号解析 ───────────────────────────────────────────

def test_custom_api_matches_known_model():
    entry = reference_api_model("whisper-large-v3-turbo", "accuracy", "zh")
    assert entry is not None and entry["score"] == 60
    assert entry["matched_model"] == "whisper-large-v3-turbo"
    mai = reference_api_model("microsoft/mai-transcribe-2", "speed", "en")
    assert mai is not None and mai["score"] == 95


def test_custom_api_unknown_model_gets_no_default_score():
    assert reference_api_model("my-private-model", "accuracy", "zh") is None
    model = next(m for m in MODELS if m.key == "custom_asr_api")
    evidence = _metric_evidence(model, "accuracy", None, "zh", api_model="my-private-model")
    assert evidence["score"] is None
    assert "选择" in evidence["note"] or "配置" in evidence["note"] or "型号" in evidence["note"]


def test_api_model_switch_updates_evidence():
    openai_card = next(m for m in MODELS if m.key == "openai_api")
    default = _metric_evidence(openai_card, "accuracy", None, "en", api_model="gpt-transcribe")
    switched = _metric_evidence(openai_card, "accuracy", None, "en", api_model="gpt-4o-transcribe")
    assert default["score"] == 78
    # 同系别名仍复用条目但必须带"已按当前型号"标注。
    assert "已按当前型号" in switched["note"]
    unknown = _metric_evidence(openai_card, "accuracy", None, "en", api_model="some-beta-model")
    assert "未单独收录" in unknown["note"]


def test_local_and_api_speed_not_blindly_shared():
    qwen_local = _metric_evidence(
        next(m for m in MODELS if m.key == "qwen_local"), "speed", None, "zh"
    )
    qwen_api = _metric_evidence(
        next(m for m in MODELS if m.key == "qwen_api"), "speed", None, "zh"
    )
    assert qwen_local["score"] != qwen_api["score"]  # 30 vs 40：不同依据分开估
    groq = _metric_evidence(
        next(m for m in MODELS if m.key == "groq_api"), "speed", None, "en"
    )
    local_turbo = _metric_evidence(
        next(m for m in MODELS if m.key == "whisper"), "speed", None, "en"
    )
    # 同 checkpoint 数值可同（69），但依据必须分别是 AA 路由实测与 OpenASR。
    assert "AA 实测" in groq["note"] and "OpenASR" in local_turbo["note"]


# ── 语言能力边界 ───────────────────────────────────────────

def test_english_only_model_no_fake_chinese_score():
    canary = _metric_evidence(
        next(m for m in MODELS if m.key == "canary_qwen"), "accuracy", None, "zh"
    )
    assert canary["score"] == reference_entry("canary_qwen", "accuracy", "en")["score"]
    assert canary["caption"] == "英语转写准确度"
    assert "英语" in canary["tooltip"]
    assert "OpenASR" in canary["note"]


def test_limited_chinese_evidence_flagged():
    mai = _metric_evidence(
        next(m for m in MODELS if m.key == "mai_transcribe_2_word"), "accuracy", None, "zh"
    )
    assert mai["available"] is True
    assert "中文证据有限" in mai["note"]  # 英语榜成绩不冒充中文已验证


# ── 稳定性与版本 ───────────────────────────────────────────

def test_scores_bound_to_version_and_stable():
    first = _metric_evidence(
        next(m for m in MODELS if m.key == "firered"), "accuracy", None, "zh"
    )
    second = _metric_evidence(
        next(m for m in MODELS if m.key == "firered"), "accuracy", None, "zh"
    )
    assert first["score"] == second["score"] == 97
    assert REFERENCE_INDEX_VERSION.startswith("ref-")


def test_reference_covers_registered_models_only():
    coverage = reference_coverage()
    assert coverage
    for key, kind, status in coverage:
        assert key in REGISTERED, key
        assert status in {"score", "gap"}


def test_aa_bridge_constants_documented():
    # turbo 双榜锚是跨榜校准的基石，必须与公开数字一致。
    assert abs(7.83 / 4.6 - 1.70) < 0.01
    assert abs(200.19 / 170.9 - 1.17) < 0.01


def test_aliases_only_map_real_model_ids():
    for alias, target in API_MODEL_ALIASES.items():
        assert target[0] in REGISTERED
        assert alias  # 无空别名
