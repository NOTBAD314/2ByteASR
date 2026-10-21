"""三十七轮守护：OpenRouter 字级时间戳通道（用户主动选择）。

用户诉求：MAI 本身有字级时间戳——按 OpenRouter 官方 STT 文档的 JSON
input_audio 格式请求（verbose_json + timestamp_granularities=[segment,word]，
MAI-Transcribe-2 路由 Azure 可开 diarization）；FireRedVAD 作切块与静音兜底；
**不换默认**，用户在设置/密钥窗选择「OpenRouter·字级」后才启用。
"""

import base64
import json
import types

import numpy as np
import pytest

from twobyteasr.recognition import asr
from twobyteasr.recognition.asr import _api_transcription_rows, call_qwen_asr_api

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
        self.reason = "OK" if status_code == 200 else "Bad Request"
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


def test_openrouter_word_request_shape():
    responses = [
        _Response(200, {
            "text": "全句。",
            "segments": [{"id": 0, "start": 0.1, "end": 1.0, "text": "全句。"}],
            "words": [{"word": "全", "start": 0.1, "end": 0.5},
                      {"word": "句", "start": 0.5, "end": 1.0}],
        })
    ]
    module, calls = _fake_requests(responses)
    result = call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32), "", endpoint=dict(WORD_ENDPOINT),
        requests_module=module,
    )
    url, kwargs = calls[0]
    assert url == WORD_ENDPOINT["url"]
    assert kwargs["headers"]["Authorization"] == "Bearer or-secret"
    assert "files" not in kwargs, "JSON 通道不使用 multipart"
    body = kwargs["json"]
    assert body["model"] == "microsoft/mai-transcribe-2"
    assert body["response_format"] == "verbose_json"
    assert body["timestamp_granularities"] == ["segment", "word"]
    assert body["provider"]["options"]["azure"]["diarization"]["enabled"] is True
    assert body["input_audio"]["format"] == "wav"
    decoded = base64.b64decode(body["input_audio"]["data"])
    assert decoded[:4] == b"RIFF"
    # 字级 words 解析直通
    assert [w["text"] for w in result["words"]] == ["全", "句"]
    assert result["words"][0]["start"] == pytest.approx(0.1)


def test_openrouter_word_400_ladder_drops_granularities_then_verbose():
    responses = [
        _Response(400, {"error": {"message": "granularities unsupported"}}),
        _Response(400, {"error": {"message": "verbose unsupported"}}),
        _Response(200, {"text": "降级文本。"}),
    ]
    module, calls = _fake_requests(responses)
    result = call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32), "", endpoint=dict(WORD_ENDPOINT),
        requests_module=module,
    )
    bodies = [kwargs["json"] for _url, kwargs in calls]
    assert len(calls) == 3
    assert bodies[0]["timestamp_granularities"] == ["segment", "word"]
    assert "timestamp_granularities" not in bodies[1]
    assert bodies[1]["response_format"] == "verbose_json"
    assert bodies[2]["response_format"] == "json"
    assert result["text"] == "降级文本"


def test_word_rows_carry_absolute_token_times():
    chunk = {"start": 10.0, "end": 14.0, "audio": (np.zeros(1, dtype=np.float32), 16000)}
    result = {
        "text": "两词",
        "segments": [{"start": 0.5, "end": 1.5, "text": "两词", "confidence": 0.9}],
        "words": [
            {"word": "两", "start": 0.5, "end": 1.0},
            {"word": "词", "start": 1.0, "end": 1.5},
        ],
    }
    rows = _api_transcription_rows(result, chunk)
    tokens = rows[0]["tokens"]
    assert tokens[0]["start"] == pytest.approx(10.5)
    assert tokens[0]["end"] == pytest.approx(11.0)
    assert tokens[1]["start"] == pytest.approx(11.0)
    assert tokens[1]["end"] == pytest.approx(11.5)
    assert tokens[0]["text"] == "两"


def test_endpoint_validation_accepts_openrouter_verbose_protocol():
    from twobyteasr.providers.llm_config import validate_qwen_asr_endpoint

    validate_qwen_asr_endpoint(dict(WORD_ENDPOINT))  # 不抛即通过
    with pytest.raises(RuntimeError):
        validate_qwen_asr_endpoint({
            "provider": "openrouter_word",
            "protocol": "bogus_protocol",
            "model": "m",
            "url": "https://openrouter.ai/api/v1/audio/transcriptions",
            "api_key": "k",
        })


def test_persist_accepts_openrouter_word_provider():
    from twobyteasr.app.ui import ASR_API_PRESETS, persist_asr_configuration

    assert "openrouter_word" in ASR_API_PRESETS
    assert (
        ASR_API_PRESETS["openrouter_word"]["protocol"] == "openrouter_verbose_json"
    )

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
        },
        qwen_key="k",
    )
    assert validated["models"]["qwen_asr_api_provider"] == "openrouter_word"


def test_settings_loader_keeps_openrouter_verbose_protocol():
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings

    normalized, _warnings = _merge_known_settings(
        DEFAULT_SETTINGS,
        {
            "models": {
                "qwen_asr_api_protocol": "openrouter_verbose_json",
                "qwen_asr_api_provider": "openrouter_word",
            },
        },
    )
    assert (
        normalized["models"]["qwen_asr_api_protocol"] == "openrouter_verbose_json"
    )
    assert normalized["models"]["qwen_asr_api_provider"] == "openrouter_word"


def test_workshop_card_registered():
    from twobyteasr.local_models.model_benchmarks import best_score
    from twobyteasr.local_models.model_workshop import MODELS

    card = next(
        (m for m in MODELS if m.key == "mai_transcribe_2_word"), None
    )
    assert card is not None, "工坊必须有字级通道卡片"
    assert card.api_preset == "openrouter_word"
    assert card.role == "api"
    # 2026-09-18 轮：MAI-Transcribe-2 没有公开可核实的横评数据，
    # 不允许任何占位分数——所有场景都不计分。
    for scene in ("zh", "zh_long", "zh_dialect", "en", "align"):
        assert best_score("mai_transcribe_2_word", "accuracy", scene) is None
        assert best_score("mai_transcribe_2_word", "speed", scene) is None


def test_transcribe_rows_use_word_tokens_for_real_timing(monkeypatch):
    """端到端：字级响应 → 行 tokens → build_alternate_primary_segments 真字时。"""
    import moss_firered_pipeline as pipeline
    from unittest.mock import MagicMock

    audio = np.zeros(int(4.0 * 16000), dtype=np.float32)

    def _fake_call(audio_arg, context, *, endpoint=None, requests_module=None):
        return {
            "text": "五字文本",
            "segments": [
                {"start": 0.2, "end": 3.8, "text": "五字文本", "confidence": 0.9}
            ],
            "words": [
                {"word": "五", "start": 0.2, "end": 0.8},
                {"word": "字", "start": 0.8, "end": 1.6},
                {"word": "文", "start": 1.6, "end": 2.4},
                {"word": "本", "start": 2.4, "end": 3.8},
            ],
        }

    monkeypatch.setattr(asr, "call_qwen_asr_api", _fake_call)
    rows = asr._transcribe_qwen_api(
        "audio.wav",
        [{"start": 0.0, "end": 4.0, "audio": (audio, 16000)}],
    )
    assert rows[0]["tokens"], "字级响应必须产出 tokens"

    import subtitle_core as legacy
    segments = pipeline.build_alternate_primary_segments(rows, [], legacy, "api")
    words = segments[0].words
    # 真字级时间：每个字自己的 start/end，而非匀速平摊（匀速时 4 字在 3.6s
    # 内每字恰 0.9s——此处首字 0.2-0.8、末字 2.4-3.8 明显不等宽）
    assert words[0].start == pytest.approx(0.2)
    assert words[-1].end == pytest.approx(3.8)
    durations = [w.end - w.start for w in words]
    assert max(durations) - min(durations) > 0.5, "字时长应不等宽（真实语速）"
