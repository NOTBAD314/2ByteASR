"""三十二轮守护：模型工坊在线 API 分组 + 两个新 API 预设。

- 「在线 API」tab 必须显示全部 API 卡（原先 _model_roles 永不产生 "api"，
  tab 永远空白，API 卡反而混进主力转写/文字复核）。
- 当前 openrouter_word/azure/qwen31_filetrans 预设通过协议白名单；
  azure_transcription 走 api-key 头（非 Bearer）。
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.recognition.asr import call_qwen_asr_api
from twobyteasr.providers.llm_config import validate_qwen_asr_endpoint
from twobyteasr.local_models.model_workshop import (
    MODELS,
    _browser_groups,
    _model_roles,
    model_is_online,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_api_tab_shows_all_online_models():
    by_key = {model.key: model for model in MODELS}
    api_tab = {key for key in by_key if "api" in _browser_groups(by_key[key])}
    online = {model.key for model in MODELS if model_is_online(model)}
    assert api_tab == online, f"API tab 与在线模型集不一致：{api_tab ^ online}"
    assert {"groq_api", "openai_api", "custom_asr_api",
            "mai_latest", "qwen31_filetrans"} <= api_tab
    assert not {"qwen_api", "mai_transcribe_2_word", "qwen_audio_asr_flash", "qwen31_flash", "qwen_filetrans"} & api_tab


def test_role_tabs_exclude_online_cards():
    by_key = {model.key: model for model in MODELS}
    for role in ("primary", "timeline", "review"):
        members = {key for key in by_key if role in _browser_groups(by_key[key])}
        assert not (members & {m.key for m in MODELS if model_is_online(m)}), (
            f"{role} tab 混入在线 API 卡：{members & {m.key for m in MODELS if model_is_online(m)}}"
        )


def test_role_picker_still_offers_api_models():
    by_key = {model.key: model for model in MODELS}
    # picker 用 _model_roles（能力语义）：API 卡仍可被选为主力/复核
    # （三十八轮：旧 multipart 卡删除，OpenRouter 只剩字级通道卡）
    assert "primary" in _model_roles(by_key["mai_latest"])
    assert "primary" in _model_roles(by_key["qwen31_filetrans"])


def test_new_api_presets_registered():
    from twobyteasr.app.ui import ASR_API_PRESETS

    assert ASR_API_PRESETS["openrouter_word"]["url"].startswith("https://openrouter.ai/")
    assert ASR_API_PRESETS["openrouter_word"]["protocol"] == "openrouter_verbose_json"
    assert "openrouter" not in ASR_API_PRESETS, "旧 multipart 通道已删除（三十八轮）"
    assert ASR_API_PRESETS["azure"]["protocol"] == "azure_transcription"
    assert ASR_API_PRESETS["qwen31_filetrans"]["model"] == "qwen-audio-3.1-asr-flash-filetrans"
    assert ASR_API_PRESETS["qwen31_filetrans"]["protocol"] == "dashscope_filetrans"
    assert ASR_API_PRESETS["openrouter_word"]["model"] == "microsoft/mai-transcribe-2"  # 2026-10-25: no MAI 2.1 exists.
    assert "dashscope_qwen_audio" not in ASR_API_PRESETS
    assert "dashscope" not in ASR_API_PRESETS
    by_key = {model.key: model for model in MODELS}
    assert by_key["mai_latest"].api_preset == "openrouter_word"
    assert by_key["qwen31_filetrans"].api_preset == "qwen31_filetrans"


def test_azure_protocol_passes_whitelists():
    validate_qwen_asr_endpoint(
        {
            "provider": "azure",
            "protocol": "azure_transcription",
            "model": "deployment",
            "url": "https://example.openai.azure.com/openai/deployments/mai/audio/transcriptions?api-version=2025-01-01",
            "api_key": "k",
        }
    )
    from twobyteasr.app.ui import persist_asr_configuration

    class _Legacy:
        RUNTIME_SETTINGS = {"models": {}, "switches": {}}

        @staticmethod
        def configure_runtime_asr(*_args, **_kwargs):
            return None

    validated = persist_asr_configuration(
        _Legacy(),
        {
            "primary_asr_backend": "api",
            "qwen_asr_backend": "off",
            "firered_asr_backend": "off",
            "qwen_asr_api_provider": "azure",
            "qwen_asr_api_protocol": "azure_transcription",
            "qwen_asr_api_model": "mai-transcribe-2",
            "qwen_asr_api_url": "https://example.openai.azure.com/openai/deployments/mai/audio/transcriptions?api-version=2025-01-01",
        },
        qwen_key="k",
    )
    assert validated["models"]["qwen_asr_api_provider"] == "azure"


def test_azure_transcription_uses_api_key_header(monkeypatch):
    captured: dict = {}

    class _Response:
        status_code = 200

        def json(self):
            return {"text": "Azure 说的话"}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _Response()

    import types

    fake_requests = types.ModuleType("requests")
    fake_requests.post = _fake_post
    monkeypatch.setattr(
        "twobyteasr.providers.llm_config.qwen_asr_endpoint_from_settings",
        lambda settings: {
            "provider": "azure",
            "protocol": "azure_transcription",
            "model": "mai-transcribe-2",
            "url": "https://example.openai.azure.com/openai/deployments/mai/audio/transcriptions?api-version=2025-01-01",
            "api_key": "secret",
            "key_source": "test",
        },
    )
    import numpy as np

    audio = np.zeros(16000, dtype=np.float32)
    result = call_qwen_asr_api(audio, "", requests_module=fake_requests)
    assert result["text"] == "Azure 说的话"
    headers = captured["kwargs"]["headers"]
    assert headers.get("api-key") == "secret"
    assert "Authorization" not in headers
    assert "model" not in captured["kwargs"]["data"], "Azure 分支不发送 model 字段（部署名在 URL）"
    assert captured["kwargs"]["data"]["response_format"] == "verbose_json"
