"""三十三轮守护：API key 读写对称（provider-scoped）+ API 转写方案 + 卡数据。

核心根因：保存按 save_api_key_for(provider) 分存，读取全走
resolve_api_key("qwen_asr") 的 legacy 桶 → 切服务商后运行时带别家 key
（HTTP 401）、工坊状态停在 configure（重复弹 key 窗）。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_endpoint_reads_provider_scoped_key(monkeypatch):
    from twobyteasr.providers import llm_config

    calls: list[tuple[str, str]] = []

    def _fake_read(provider, base):
        calls.append((str(provider), str(base)))
        return ("sk-openrouter", "scoped")

    monkeypatch.setattr(llm_config, "read_api_key", _fake_read)
    endpoint = llm_config.qwen_asr_endpoint_from_settings(
        {
            "models": {
                "qwen_asr_api_provider": "openrouter_word",
                "qwen_asr_api_model": "microsoft/mai-transcribe-2",
                "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
            }
        }
    )
    assert endpoint["api_key"] == "sk-openrouter"
    assert calls == [("openrouter_word", "https://openrouter.ai/api/v1/audio/transcriptions")], (
        "运行时必须读 provider-scoped key，不得再走 QWEN_ASR_API_KEY legacy 桶"
    )


def test_model_state_uses_card_provider_key(monkeypatch):
    _app()
    from pathlib import Path

    from twobyteasr.local_models import model_workshop as mw

    saved: dict[str, str] = {"openrouter_word": "sk-or", "dashscope_qwen_audio": "sk-dash"}

    def _fake_read(provider, base):
        return (saved.get(str(provider), ""), "scoped")

    monkeypatch.setattr("twobyteasr.providers.llm_config.read_api_key", _fake_read)
    page = mw.ModelWorkshopPage(
        Path("."),
        {
            "models": {
                "qwen_asr_backend": "off",
                "primary_asr_backend": "api",
                "qwen_asr_api_provider": "openrouter_word",
                "qwen_asr_api_model": "microsoft/mai-transcribe-2",
                "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
            }
        },
    )
    by_key = {m.key: m for m in mw.MODELS}
    assert page._model_state(by_key["mai_transcribe_2_word"], "primary") == "selected"
    assert page._model_state(by_key["qwen_api"], "primary") == "configure"
    # 未存 key 的服务商卡不再误显"已配置"（此前读 legacy 桶全体误报）
    assert page._model_state(by_key["groq_api"], "primary") == "configure"
    page.deleteLater()


def test_api_transcription_plan():
    # 2026-10-22: 「API 转写」 is MOSS Pro, no review pass; 2026-10-23: timed by
    # FireRedASR2 for Chinese and Qwen3 对齐 for other languages.
    from twobyteasr.recognition.recognition_plans import RECOGNITION_PLANS, matching_plan, recognition_plan

    plan = recognition_plan("moss_pro_qwen")
    assert plan.label == "API 转写" and plan.primary == "api" and plan.review == "off"
    assert (plan.timeline, plan.foreign_timeline) == ("local", "qwen_aligner")
    assert matching_plan("api", "qwen_aligner", "off") == "moss_pro_qwen"
    assert "api" not in [p.key for p in RECOGNITION_PLANS]


def test_mai_card_branding():
    from twobyteasr.local_models.model_workshop import MODELS
    from twobyteasr.app.ui import ASR_API_PRESETS

    mai = next(m for m in MODELS if m.key == "mai_transcribe_2_word")
    assert mai.logo_asset is None, "MAI 是微软模型，不得复用 OpenAI logo"
    assert mai.icon_name == "fa5b.microsoft"
    assert ASR_API_PRESETS["openrouter_word"]["model"] == "microsoft/mai-transcribe-2"
    assert ASR_API_PRESETS["azure"]["model"] == "microsoft/mai-transcribe-2"


def test_api_combo_label_shows_provider_and_model(monkeypatch):
    from twobyteasr.providers import llm_config
    from twobyteasr.local_models.model_workshop import _api_combo_label

    monkeypatch.setattr(llm_config, "read_api_key", lambda p, b: ("sk", "scoped"))
    label, ready = _api_combo_label(
        {"qwen_asr_api_provider": "openrouter_word", "qwen_asr_api_model": "microsoft/mai-transcribe-2"}
    )
    # 组合卡窄列：模型 id 用最后一段（完整 id 在 api tab 副标题）
    assert "OpenRouter" in label and "mai-transcribe-2" in label
    assert "microsoft/" not in label
    assert ready is True


def test_persist_uses_scoped_existing_key(monkeypatch):
    from twobyteasr.app.ui import persist_asr_configuration

    class _Legacy:
        RUNTIME_SETTINGS = {"models": {}, "switches": {}}

        @staticmethod
        def configure_runtime_asr(*_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "twobyteasr.app.ui.resolve_api_key", lambda stage: ("", "none")
    )
    read_calls: list[tuple[str, str]] = []

    def _fake_read(provider, base):
        read_calls.append((str(provider), str(base)))
        return ("sk-saved", "scoped")

    from twobyteasr.app import ui as ui_module

    monkeypatch.setattr("twobyteasr.providers.llm_config.read_api_key", _fake_read)
    validated = persist_asr_configuration(
        _Legacy(),
        {
            "primary_asr_backend": "api",
            "qwen_asr_backend": "off",
            "firered_asr_backend": "off",
            "qwen_asr_api_provider": "openrouter_word",
            "qwen_asr_api_protocol": "openai_transcription",
            "qwen_asr_api_model": "microsoft/mai-transcribe-2",
            "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
        },
        qwen_key="",
    )
    assert validated["models"]["qwen_asr_api_provider"] == "openrouter_word"
    assert read_calls and read_calls[0][0] == "openrouter_word", (
        "缺 key 校验必须按当前服务商读 scoped key（空 qwen_key 时沿用已存）"
    )
