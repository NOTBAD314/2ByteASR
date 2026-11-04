"""Focused regressions for Workshop Detail and Technical Info hierarchy."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QScrollArea, QWidget  # noqa: E402

from twobyteasr.local_models.model_workshop import (  # noqa: E402
    MODELS,
    ModelTechnicalDialog,
    ModelWorkshopPage,
)


ROOT = Path(__file__).resolve().parents[1]


def _app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("key", ["moss", "firered", "qwen_local"])
def test_workshop_detail_keeps_width_and_reading_order(key):
    _app()
    page = ModelWorkshopPage(ROOT, {"models": {}})
    page.detail_model_key = key
    page._refresh_detail()

    assert page.detail.minimumWidth() == 340
    assert page.detail.maximumWidth() == 380
    detail_layout = page.detail.layout()
    assert detail_layout.indexOf(page.detail_title) < detail_layout.indexOf(page.detail_description)
    assert detail_layout.indexOf(page.detail_description) < detail_layout.indexOf(page.install_size_card)
    assert detail_layout.indexOf(page.install_size_card) < detail_layout.indexOf(page.detail_rec_note)
    assert page.detail_rec_note.text() == "★ 2ByteASR 推荐"
    assert page.detail_rec_reason.wordWrap()
    assert page.detail_rec_reason.text()

    model = page._cards[key].model
    size_number = "".join(ch for ch in model.size if ch.isdigit() or ch == ".")
    assert size_number in page.install_size_card.text()
    assert size_number not in page.detail_install.text()
    page.deleteLater()


@pytest.mark.parametrize("key", ["moss", "firered", "qwen_local"])
def test_technical_info_uses_one_clean_hierarchy_for_primary_models(key):
    app = _app()
    model = next(item for item in MODELS if item.key == key)
    technical = ModelTechnicalDialog(model)
    technical.resize(710, 650)
    technical.show()
    app.processEvents()

    panel = technical.findChild(QFrame, "technicalDetailsPanel")
    assert panel.layout().contentsMargins().left() == 26
    assert panel.layout().contentsMargins().right() == 26
    assert len(technical.findChildren(QFrame, "techInfoCard")) == 4
    assert all(label.wordWrap() for label in technical.findChildren(QLabel, "techInfoValue"))

    headings = [label.text() for label in technical.findChildren(QLabel, "technicalDetailsHeading")]
    assert headings[:8] == [
        "基础信息",
        "在 2ByteASR 中的职责",
        "核心能力",
        "支持语言与方言",
        "官方 Benchmark",
        "Benchmark 测试条件",
        "技术原理",
        "优势",
    ]
    assert "局限" in headings
    assert "硬件 / Runtime" in headings
    assert "2ByteASR 评价" in headings
    assert "官方资源" in headings
    assert "官方信息" not in headings
    assert "来源" not in headings
    assert "资源需求" not in headings

    bodies = technical.findChildren(QLabel, "technicalDetailsBody")
    assert bodies and all(label.wordWrap() for label in bodies)
    benchmark_text = " ".join(
        label.text() for label in technical.findChildren(QLabel, "technicalBenchmarkCell")
    )
    expected = {
        "moss": ("14.84%", "15.83%"),
        "firered": ("3.05%", "11.67%"),
        "qwen_local": ("1.63%", "2.41%"),
    }
    assert all(value in benchmark_text for value in expected[key])
    assert "Table 5" not in benchmark_text
    body_text = " ".join(label.text() for label in bodies)
    assert "评测口径：" in body_text
    assert "指标方向：越低越好" in body_text
    assert "资料版本：" in body_text

    fact_values = technical.findChildren(QLabel, "technicalFactValue")
    assert len(fact_values) >= 4
    assert all(label.wordWrap() for label in fact_values)
    benchmark_links = technical.findChildren(QLabel, "technicalLink")
    assert benchmark_links
    assert "查看完整官方 Benchmark" in benchmark_links[0].text()

    scroll = technical.findChild(QScrollArea, "technicalDetailsScroll")
    host = technical.findChild(QWidget, "technicalDetailsScrollHost")
    assert scroll.viewport().styleSheet() == ""
    assert host.styleSheet() == ""
    assert technical.findChild(QFrame, "technicalEvaluation") is not None
    technical.close()
    technical.deleteLater()


def test_benchmark_filter_requires_a_concrete_value_not_a_reference_number():
    assert ModelTechnicalDialog._has_concrete_benchmark_value("4.23%")
    assert ModelTechnicalDialog._has_concrete_benchmark_value("0.15 RTF")
    assert not ModelTechnicalDialog._has_concrete_benchmark_value(
        "参见 MOSS-Audio Technical Report Table 5"
    )
    assert not ModelTechnicalDialog._has_concrete_benchmark_value(
        "公开 Mandarin ASR benchmarks 新 SOTA"
    )


@pytest.mark.parametrize(
    "key",
    [
        "moss",
        "firered",
        "qwen_local",
        "qwen_api",
        "groq_api",
        "openai_api",
        "custom_asr_api",
        "sensevoice",
        "paraformer",
        "whisper",
        "qwen_aligner",
        "funasr_nano",
        "firered_llm",
        "glm_asr_nano",
        "canary_qwen",
        "omni_asr_llm_7b",
    ],
)
def test_every_workshop_model_has_complete_technical_metadata(key):
    from twobyteasr.local_models.model_evaluation_metadata import get_profile

    profile = get_profile(key)
    assert profile["responsibility"]
    assert profile["principles"]
    assert profile["strengths"]
    assert profile["limits"]
    assert profile["resources"]
    assert profile["condition"]
    official = profile["official"]
    for field in (
        "developer",
        "params",
        "languages",
        "architecture",
        "dialects",
        "audio_type",
        "license",
        "runtime",
        "language_summary",
        "code_switching",
        "singing_support",
        "language_source",
    ):
        assert official[field]
    assert isinstance(official["languages_fully_enumerated"], bool)
    for benchmark in profile["benchmarks"]:
        for field in (
            "metric",
            "value",
            "dataset",
            "condition",
            "hardware",
            "direction",
            "source_updated",
            "source",
            "runtime",
            "batch_concurrency",
            "source_url",
            "source_version",
            "comparison_group",
        ):
            assert field in benchmark
    assert profile["local_benchmark"] == {
        "status": "not_run",
        "gpu": "",
        "cpu": "",
        "runtime": "",
        "audio_length_seconds": None,
        "inference_seconds": None,
        "realtime_factor": None,
    }


@pytest.mark.parametrize("model", MODELS, ids=lambda model: model.key)
def test_every_workshop_model_has_fully_english_technical_metadata(model):
    from twobyteasr.local_models.model_evaluation_metadata import get_profile

    def strings(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from strings(item)
        elif isinstance(value, str):
            yield value

    profile = get_profile(model.key, "en")
    han = [
        text for text in strings(profile)
        if any("\u4e00" <= char <= "\u9fff" for char in text)
    ]
    assert han == []


def test_workshop_metrics_use_verified_group_scores_with_official_evidence():
    """2026-09-18 轮：占位参考指数退役，卡片分数来自核实基准组。"""
    from twobyteasr.local_models.model_evaluation_metadata import get_profile
    from twobyteasr.local_models.model_workshop import _metric_evidence

    firered = next(item for item in MODELS if item.key == "firered")
    firered_llm = next(item for item in MODELS if item.key == "firered_llm")
    qwen = next(item for item in MODELS if item.key == "qwen_local")
    aligner = next(item for item in MODELS if item.key == "qwen_aligner")

    accuracy = _metric_evidence(firered, "accuracy")
    assert accuracy["available"] is True
    assert accuracy["value"] == "97"
    assert str(accuracy["note"]).startswith("FireRed 官方同表 · 普通话 4 集均值 CER 3.05%")
    assert accuracy["score"] == int(accuracy["value"])
    assert "不是识别正确率" in str(accuracy["tooltip"])
    assert "来源" in str(accuracy["tooltip"])
    assert "accuracy" not in get_profile("firered").get("twobyte", {})
    assert "speed" not in get_profile("firered").get("twobyte", {})

    assert _metric_evidence(firered_llm, "accuracy", "primary")["score"] == 100
    assert _metric_evidence(qwen, "accuracy", "review")["score"] == 88
    assert _metric_evidence(firered, "accuracy", "timeline")["score"] == 97

    speed = _metric_evidence(qwen, "speed", "review")
    assert speed["available"] is True  # 2026-09-18 V+：公开资料速度参考分默认显示
    assert speed["score"] == 30 and speed["value"] == "约 30"  # 估算分带“约”
    assert "估算" in str(speed["note"]) or "同级类推" in str(speed["note"])

    align_evidence = _metric_evidence(aligner, "accuracy", "timeline")
    assert align_evidence["caption"] == "对齐精度"
    assert "AAS" in str(align_evidence["note"])  # 对齐精度不与 CER/WER 混算
    assert align_evidence["score"] == 100

    # API 有明确型号 → 公开参考分；未配置密钥不影响（预设默认型号解析）。
    api_model = next(item for item in MODELS if item.key == "qwen_api")
    api_evidence = _metric_evidence(api_model, "accuracy")
    assert api_evidence["available"] is True and api_evidence["score"] == 85
    assert "同系" in str(api_evidence["note"])
    # 英语专用模型在中文场景明确“不支持”，不硬给中文分。
    canary = next(item for item in MODELS if item.key == "canary_qwen")
    canary_evidence = _metric_evidence(canary, "accuracy")
    assert canary_evidence["score"] == 78
    assert canary_evidence["caption"] == "英语转写准确度"
    # 真未知：不自动给 50/80/90 默认分。
    omni = next(item for item in MODELS if item.key == "omni_asr_llm_7b")
    omni_evidence = _metric_evidence(omni, "accuracy")
    assert omni_evidence["score"] is None and omni_evidence["note"]
