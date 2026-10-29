"""三十五轮守护：API 转写真实时间戳（verbose_json）+ 文案去 Qwen 化。

用户实录根因：
1. response_format=json 丢掉 MAI-Transcribe-2 的时间戳能力 → 块边界 cue +
   _distributed_words 匀速平铺 → 字幕出现/切换延迟秒级；
2. "Qwen API 短块…/Qwen ASR API 没有…/Qwen3-ASR 局部复核" 等硬编码文案让
   OpenRouter 用户误以为还在跑 Qwen。
"""

import numpy as np
import pytest

import subtitle_core
from twobyteasr.recognition import asr
from twobyteasr.recognition.asr import (
    _api_transcription_rows,
    _extract_transcription_segments,
    _extract_transcription_words,
    call_qwen_asr_api,
)

OPENROUTER_ENDPOINT = {
    "provider": "openrouter_word",
    "protocol": "openai_transcription",
    "model": "microsoft/mai-transcribe-2",
    "url": "https://openrouter.ai/api/v1/audio/transcriptions",
    "api_key": "or-secret",
}


def test_verbose_json_segments_and_words_are_parsed():
    payload = {
        "text": "全句文本。",
        "segments": [
            {
                "id": 0,
                "start": 0.4,
                "end": 2.1,
                "text": "第一句。",
                "avg_logprob": -0.2,
            },
            {"id": 1, "start": 3.0, "end": 4.5, "text": "第二句。", "avg_logprob": -0.5},
        ],
        "words": [
            {"word": "第一", "start": 0.4, "end": 0.8},
            {"word": "句", "start": 0.8, "end": 2.1},
            {"word": "第二", "start": 3.0, "end": 3.4},
            {"word": "句", "start": 3.4, "end": 4.5},
        ],
    }
    segments = _extract_transcription_segments(payload)
    assert [row["text"] for row in segments] == ["第一句", "第二句"]
    assert segments[0]["start"] == pytest.approx(0.4)
    assert segments[0]["confidence"] == pytest.approx(0.8)
    words = _extract_transcription_words(payload)
    assert len(words) == 4
    assert words[0]["text"] == "第一"


def test_transcription_result_offsets_by_chunk_and_keeps_tokens():
    chunk = {"start": 10.0, "end": 35.0, "audio": (np.zeros(1, dtype=np.float32), 16000)}
    result = {
        "text": "全句文本。",
        "segments": [
            {"start": 1.0, "end": 3.0, "text": "句一。", "confidence": 0.9},
            {"start": 40.0, "end": 41.0, "text": "越界段。", "confidence": 0.9},
        ],
        "words": [
            {"start": 1.0, "end": 2.0, "text": "句", "confidence": 0.9},
            {"start": 2.0, "end": 3.0, "text": "一", "confidence": 0.9},
        ],
    }
    rows = _api_transcription_rows(result, chunk)
    # 越界段（相对起点已在块外）被剔除，只保留真段
    assert len(rows) == 1
    row = rows[0]
    assert row["start"] == pytest.approx(11.0)
    assert row["end"] == pytest.approx(13.0)
    assert row["tokens"][0]["start"] == pytest.approx(11.0)
    assert row["tokens"][1]["end"] == pytest.approx(13.0)


def test_transcription_without_segments_falls_back_to_chunk_row():
    chunk = {"start": 5.0, "end": 9.0, "audio": (np.zeros(1, dtype=np.float32), 16000)}
    rows = _api_transcription_rows(
        {"text": "整段文本。", "segments": [], "words": []}, chunk
    )
    assert len(rows) == 1
    assert rows[0]["start"] == pytest.approx(5.0)
    assert rows[0]["end"] == pytest.approx(9.0)
    assert "tokens" not in rows[0]


def test_empty_transcription_result_is_valid_not_failure():
    chunk = {"start": 5.0, "end": 9.0, "audio": (np.zeros(1, dtype=np.float32), 16000)}
    assert _api_transcription_rows(
        {"text": "", "segments": [], "words": []}, chunk
    ) == []


def test_call_uses_verbose_json_and_empty_200_returns_empty_dict():
    captured = {}

    class _Response:
        status_code = 200
        reason = "OK"

        def json(self):
            return {"text": "", "segments": [], "words": []}

    def _fake_post(url, **kwargs):
        captured["data"] = kwargs.get("data")
        return _Response()

    import types

    fake_requests = types.ModuleType("requests")
    fake_requests.post = _fake_post
    result = call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32),
        "",
        endpoint=dict(OPENROUTER_ENDPOINT),
        requests_module=fake_requests,
    )
    assert captured["data"]["response_format"] == "verbose_json"
    assert result == {"text": "", "segments": [], "words": []}


def test_verbose_json_rejection_falls_back_to_plain_json():
    calls = []

    class _RejectVerbose:
        status_code = 400
        reason = "Bad Request"

        def json(self):
            return {"error": {"message": "response_format not supported"}}

    class _PlainJson:
        status_code = 200
        reason = "OK"

        def json(self):
            return {"text": "降级文本。"}

    def _fake_post(url, **kwargs):
        calls.append(kwargs.get("data", {}).get("response_format"))
        return _RejectVerbose() if calls[-1] == "verbose_json" else _PlainJson()

    import types

    fake_requests = types.ModuleType("requests")
    fake_requests.post = _fake_post
    result = call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32),
        "",
        endpoint=dict(OPENROUTER_ENDPOINT),
        requests_module=fake_requests,
    )
    assert calls == ["verbose_json", "json"]
    assert result["text"] == "降级文本"


def _install_endpoint(monkeypatch, endpoint):
    monkeypatch.setattr(
        "twobyteasr.providers.llm_config.qwen_asr_endpoint_from_settings",
        lambda settings: dict(endpoint),
    )
    monkeypatch.setattr(asr, "CLOUD_BATCH_WORKERS", 2)


def test_transcribe_qwen_api_expands_segments_and_names_provider(monkeypatch, capsys):
    _install_endpoint(monkeypatch, OPENROUTER_ENDPOINT)
    chunk_seconds = 3.0
    audio = np.zeros(int(chunk_seconds * 16000), dtype=np.float32)

    def _fake_call(audio_arg, context, *, endpoint=None, requests_module=None):
        # segments 已是 _extract_transcription_segments 的规范化产物
        # （clean_subtitle_text 已去掉句尾标点）。
        return {
            "text": "整块文本",
            "segments": [
                {"start": 0.5, "end": 1.2, "text": "前半", "confidence": 0.9},
                {"start": 1.8, "end": 2.6, "text": "后半", "confidence": 0.85},
            ],
            "words": [],
        }

    monkeypatch.setattr(asr, "call_qwen_asr_api", _fake_call)
    chunks = [
        {"start": 0.0, "end": chunk_seconds, "audio": (audio, 16000)}
    ]
    references = asr._transcribe_qwen_api("audio.wav", chunks)

    assert len(references) == 2
    assert references[0]["start"] == pytest.approx(0.5)
    assert references[0]["end"] == pytest.approx(1.2)
    assert references[0]["text"] == "前半"
    assert references[1]["start"] == pytest.approx(1.8)
    out = capsys.readouterr().out
    assert "OpenRouter · microsoft/mai-transcribe-2" in out
    assert "Qwen" not in out


def test_transcribe_qwen_api_failure_names_provider_and_rate_limit(monkeypatch, capsys):
    _install_endpoint(monkeypatch, OPENROUTER_ENDPOINT)
    audio = np.zeros(16000, dtype=np.float32)

    def _fake_call(audio_arg, context, *, endpoint=None, requests_module=None):
        raise RuntimeError(
            "ASR API 请求失败（HTTP 429 / no-code）：rate limited"
        )

    monkeypatch.setattr(asr, "call_qwen_asr_api", _fake_call)
    monkeypatch.setattr(asr, "time", __import__("types").SimpleNamespace(
        sleep=lambda _seconds: None, perf_counter=lambda: 0.0
    ))
    chunks = [{"start": 0.0, "end": 1.0, "audio": (audio, 16000)}]
    with pytest.raises(RuntimeError) as excinfo:
        asr._transcribe_qwen_api("audio.wav", chunks)
    message = str(excinfo.value)
    assert "OpenRouter · microsoft/mai-transcribe-2" in message
    assert "Qwen" not in message
    assert "限流" in message
    out = capsys.readouterr().out
    assert "Qwen API 短块" not in out
    assert "OpenRouter · microsoft/mai-transcribe-2 短块 1/1 失败" in out


def test_attach_review_completion_log_names_provider(monkeypatch, capsys):
    """api 复核完成日志必须点名服务商（用户实录：被当成还在跑 Qwen）。"""
    from unittest.mock import MagicMock

    import moss_firered_pipeline as pipeline

    legacy = MagicMock()
    legacy.QWEN_ASR_BACKEND = "api"
    legacy.USE_QWEN_ASR_REFERENCE = True
    legacy.QWEN_ASR_TEXT_ALIGNMENT_PAD_SECONDS = 0.5
    legacy.RUNTIME_SETTINGS = {
        "models": {
            "qwen_asr_api_provider": "openrouter_word",
            "qwen_asr_api_model": "microsoft/mai-transcribe-2",
            "qwen_asr_api_protocol": "openai_transcription",
            "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
        }
    }
    pipeline.attach_qwen_review_evidence([], [], legacy)
    out = capsys.readouterr().out
    assert "OpenRouter · microsoft/mai-transcribe-2 复核" in out
    assert "Qwen3-ASR 复核" not in out


def test_pipeline_stage_label_logic_for_api_review(monkeypatch, capsys):
    """复刻 run_qwen_stage 的标签分支：api → 在线 ASR API 文字复核（display）。"""
    from twobyteasr.providers.llm_config import asr_api_display, qwen_asr_endpoint_from_settings

    settings = {
        "models": {
            "qwen_asr_api_provider": "openrouter_word",
            "qwen_asr_api_model": "microsoft/mai-transcribe-2",
            "qwen_asr_api_protocol": "openai_transcription",
            "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
        }
    }
    endpoint = qwen_asr_endpoint_from_settings(settings)
    display = asr_api_display(endpoint)
    assert "OpenRouter" in display
    assert "microsoft/mai-transcribe-2" in display


def test_validate_endpoint_messages_are_provider_scoped():
    from twobyteasr.providers.llm_config import validate_qwen_asr_endpoint

    with pytest.raises(RuntimeError) as excinfo:
        validate_qwen_asr_endpoint(
            {
                "provider": "openrouter_word",
                "protocol": "openai_transcription",
                "model": "microsoft/mai-transcribe-2",
                "url": "https://openrouter.ai/api/v1/audio/transcriptions",
                "api_key": "",
            }
        )
    message = str(excinfo.value)
    assert "Qwen" not in message
    assert "DashScope" not in message
    assert "openrouter" in message
