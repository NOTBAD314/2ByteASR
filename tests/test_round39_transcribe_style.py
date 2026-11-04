"""三十九轮守护：转写风格（clean|verbatim）+ Qwen-Audio 同步协议修正。

用户指令：加转写风格选项——verbatim 保留「嗯、那个、口误」适合合规/质检，
clean 去语气词适合字幕和纪要；并检查 Qwen-Audio-3.0-ASR 的字级时间戳/说话人
分离接入。

官方文档结论（记入 plan）：
- MAI：Azure Fast Transcription `modelOptions.transcribeStyle`（verbatim|clean，
  官方默认 verbatim → 我们要 clean 必须显式传）；经 OpenRouter
  `provider.options.azure.*` 原样转发。2026-10-25 实测：要放在
  `enhancedMode.modelOptions` 里才生效（顶层 modelOptions 时两种风格结果相同）。
- Qwen-Audio-3.0-ASR-Flash：**同步协议（multimodal/OpenAI 兼容）响应无时间戳
  无 speaker**（asr_options 仅 language/enable_itn）；字级时间戳只在异步
  filetrans（parameters.enable_words，且要求公网 file_url——本地应用不适用）。
  我们请求体里的 enable_lid 是文档外参数 → 删除。
"""

import types

import numpy as np
import pytest
from subtitle_core import SubtitleCue, resolve_isolated_single_character_cues

from twobyteasr.recognition.asr import call_qwen_asr_api

WORD_ENDPOINT = {
    "provider": "openrouter_word",
    "protocol": "openrouter_verbose_json",
    "model": "microsoft/mai-transcribe-2",
    "url": "https://openrouter.ai/api/v1/audio/transcriptions",
    "api_key": "or-secret",
}


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.reason = "OK"
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _fake_requests(responses):
    calls = []

    def _post(url, **kwargs):
        calls.append((url, kwargs))
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        return item() if callable(item) else item

    module = types.ModuleType("requests")
    module.post = _post
    return module, calls


def test_openrouter_body_carries_transcribe_style():
    responses = [_Response(200, {"text": "文。", "segments": [], "words": []})]
    module, calls = _fake_requests(responses)
    endpoint = dict(WORD_ENDPOINT, style="verbatim")
    call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32), "", endpoint=endpoint,
        requests_module=module,
    )
    body = calls[0][1]["json"]
    azure = body["provider"]["options"]["azure"]
    assert azure["enhancedMode"]["modelOptions"]["transcribeStyle"] == "verbatim"
    assert "modelOptions" not in azure   # ignored there (2026-10-25)
    assert azure["diarization"]["enabled"] is True
    assert body["timestamp_granularities"] == ["segment", "word"]


def test_style_defaults_to_clean_explicitly():
    """官方默认是 verbatim；我们要 clean 必须显式传（缺省=clean）。"""
    responses = [_Response(200, {"text": "文", "segments": [], "words": []})]
    module, calls = _fake_requests(responses)
    call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32), "", endpoint=dict(WORD_ENDPOINT),
        requests_module=module,
    )
    body = calls[0][1]["json"]
    assert (
        body["provider"]["options"]["azure"]["enhancedMode"]["modelOptions"]["transcribeStyle"]
        == "clean"
    )


def test_400_ladder_drops_provider_options_last():
    responses = [
        _Response(400, {"error": {"message": "bad"}}),
        _Response(400, {"error": {"message": "bad"}}),
        _Response(400, {"error": {"message": "bad"}}),
        _Response(200, {"text": "兜底文本"}),
    ]
    module, calls = _fake_requests(responses)
    result = call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32), "", endpoint=dict(WORD_ENDPOINT),
        requests_module=module,
    )
    bodies = [kwargs["json"] for _url, kwargs in calls]
    assert len(calls) == 4
    assert bodies[0]["timestamp_granularities"] == ["segment", "word"]
    assert "timestamp_granularities" not in bodies[1]
    assert bodies[1]["response_format"] == "verbose_json"
    assert bodies[2]["response_format"] == "json"
    assert "provider" in bodies[2], "provider 路由项在第三步仍保留"
    assert "provider" not in bodies[3], "最后兜底撤掉 provider 路由项"
    assert result["text"] == "兜底文本"


def test_dashscope_body_has_no_undocumented_enable_lid():
    responses = [
        _Response(200, {"output": {"choices": [{"message": {"content": [{"text": "文本。"}]}}]}})
    ]
    module, calls = _fake_requests(responses)
    endpoint = {
        "provider": "dashscope_qwen_audio",
        "protocol": "dashscope_multimodal",
        "model": "qwen-audio-3.0-asr-flash",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        "api_key": "sk",
    }
    text = call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32), "", endpoint=endpoint,
        requests_module=module,
    )
    assert text == "文本"
    body = calls[0][1]["json"]
    options = body["parameters"]["asr_options"]
    assert "enable_lid" not in options, "enable_lid 是文档外参数（三十九轮清理）"
    assert options["enable_itn"] is True
    assert options["language"] == "zh"


def test_endpoint_from_settings_carries_style():
    from twobyteasr.providers.llm_config import qwen_asr_endpoint_from_settings

    endpoint = qwen_asr_endpoint_from_settings(
        {"models": {"qwen_asr_api_provider": "openrouter_word",
                    "api_transcribe_style": "verbatim"}}
    )
    assert endpoint["style"] == "verbatim"
    default = qwen_asr_endpoint_from_settings({"models": {}})
    assert default["style"] == "clean"


def test_settings_style_validation():
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings

    merged, _warnings = _merge_known_settings(
        DEFAULT_SETTINGS, {"models": {"api_transcribe_style": "verbatim"}}
    )
    assert merged["models"]["api_transcribe_style"] == "verbatim"
    bad, warnings = _merge_known_settings(
        DEFAULT_SETTINGS, {"models": {"api_transcribe_style": "fancy"}}
    )
    assert bad["models"]["api_transcribe_style"] == "clean"
    assert any("api_transcribe_style" in str(item) for item in warnings)


def test_persist_accepts_style():
    from twobyteasr.app.ui import persist_asr_configuration

    class _Legacy:
        RUNTIME_SETTINGS = {"models": {}}

        def configure_runtime_asr(self, models, qwen_asr_key=""):
            self.saved = models

    legacy = _Legacy()
    validated = persist_asr_configuration(
        legacy,
        {
            "primary_asr_backend": "api",
            "qwen_asr_backend": "off",
            "firered_asr_backend": "off",
            "qwen_asr_api_provider": "openrouter_word",
            "qwen_asr_api_protocol": "openrouter_verbose_json",
            "qwen_asr_api_model": "microsoft/mai-transcribe-2",
            "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
            "api_transcribe_style": "verbatim",
        },
        qwen_key="k",
    )
    assert validated["models"]["api_transcribe_style"] == "verbatim"


def test_verbatim_keeps_isolated_filler(monkeypatch):
    import subtitle_core

    cues = [
        SubtitleCue(1, 0.0, 1.0, "前文很长", speaker="S01"),
        SubtitleCue(2, 4.0, 4.4, "嗯", speaker="S01"),
        SubtitleCue(3, 8.0, 9.0, "后文很长", speaker="S01"),
    ]
    settings = {"models": {"api_transcribe_style": "verbatim"}}
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", settings)
    resolved, resolution = resolve_isolated_single_character_cues(cues)
    assert [cue.text for cue in resolved] == ["前文很长", "嗯", "后文很长"]
    assert resolution["kept_ids"] == {2}
    assert not resolution["omitted_ids"], "verbatim 不得省略语气词"


def test_clean_still_omits_isolated_filler(monkeypatch):
    import subtitle_core

    cues = [
        SubtitleCue(1, 0.0, 1.0, "前文很长", speaker="S01"),
        SubtitleCue(2, 4.0, 4.4, "嗯", speaker="S01"),
        SubtitleCue(3, 8.0, 9.0, "后文很长", speaker="S01"),
    ]
    settings = {"models": {"api_transcribe_style": "clean"}}
    monkeypatch.setattr(subtitle_core, "RUNTIME_SETTINGS", settings)
    resolved, resolution = resolve_isolated_single_character_cues(cues)
    assert [cue.text for cue in resolved] == ["前文很长", "后文很长"]
    assert resolution["omitted_ids"] == {2}
