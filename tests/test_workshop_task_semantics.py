from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.local_models.model_task_metadata import task_for
from twobyteasr.local_models.model_workshop import MODELS, ElideLabel, ModelCard, ModelWorkshopPage, _metric_evidence, model_task_badges, model_workflow

APP = QApplication.instance() or QApplication([])
MODELS_BY_KEY = {model.key: model for model in MODELS}


def test_asr_review_role_remains_transcription_and_aligner_requires_text():
    asr = MODELS_BY_KEY["qwen_local"]
    aligner = MODELS_BY_KEY["qwen_aligner"]
    assert _metric_evidence(asr, "accuracy")["caption"] == "转写准确度"
    assert _metric_evidence(aligner, "accuracy")["caption"] == "对齐精度"
    assert "需要已有文本" in model_task_badges(aligner)
    assert "不能独立转写" in model_workflow(aligner)
    assert "音频 + 已有文本" in model_workflow(aligner)
    assert "说话人" in model_task_badges(MODELS_BY_KEY["moss"])


@pytest.mark.parametrize("task,caption", [("forced_aligner", "对齐精度"), ("diarization", "说话人区分"),
                                        ("text_review", "文本复核能力"), ("translation", "翻译质量")])
def test_new_model_metric_does_not_require_ui_special_case(task, caption):
    model = replace(MODELS[0], key="future_model", model_type=task, asr_capabilities=())
    assert _metric_evidence(model, "accuracy")["caption"] == caption
    assert _metric_evidence(model, "accuracy")["score"] is None


def test_missing_evidence_has_explicit_label_without_empty_track():
    card = ModelCard(MODELS_BY_KEY["omni_asr_llm_7b"])
    assert card.accuracy_bar._track.isHidden()
    assert card.accuracy_bar._word.text() == "暂无可比数据"
    assert "不等同" in card.size_label.toolTip()
    assert "越高越快" in card.speed_bar.toolTip()
    assert "同类任务" in card.accuracy_bar.toolTip()
    card.deleteLater()


def test_detail_scope_matches_alignment_and_english_and_badges_bounded():
    page = ModelWorkshopPage(Path(__file__).resolve().parents[1], {"models": {}})
    for key, scope in (("qwen_aligner", "对齐"), ("canary_qwen", "英语")):
        page._view_model(key)
        assert scope in page.detail_metric_section.text()
        assert "→" in page.detail_workflow.text()
    assert "不支持中文" in page.detail_workflow.text()
    assert page.capability_rows[0]._current_caption == "英语转写准确度"
    for model in MODELS:
        assert 1 <= len(model_task_badges(model)) <= 5
    page.deleteLater()


def test_evidence_label_preserves_updated_text_after_resize():
    label = ElideLabel("读取官方资料")
    label.setText("官方来源：当前模型的可靠依据")
    label.resize(400, 30)
    label.show()
    APP.processEvents()
    assert label.text() == "官方来源：当前模型的可靠依据"
    label.resize(40, 30)
    APP.processEvents()
    assert label.toolTip() == "官方来源：当前模型的可靠依据"
    label.deleteLater()
