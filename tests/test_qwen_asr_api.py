import numpy as np

import subtitle_core
from twobyteasr.recognition import asr
from twobyteasr.recognition.asr import call_qwen_asr_api


class FakeResponse:
    status_code = 200
    reason = "OK"

    def json(self):
        return {
            "output": {
                "choices": [
                    {"message": {"content": [{"text": "测试转写。"}]}}
                ]
            }
        }


class FakeRequests:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


class OpenAIResponse:
    status_code = 200
    reason = "OK"

    def json(self):
        return {"text": "云端复核文本。"}


def test_saved_unrelated_asr_deployment_can_use_multimodal_transport():
    requests = FakeRequests()
    endpoint = {
        "provider": "custom",
        "protocol": "dashscope_multimodal",
        "model": "fixture-unrelated-deployment",
        "url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        "api_key": "secret-test-key",
    }
    text = call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32),
        "游戏专名上下文",
        endpoint=endpoint,
        requests_module=requests,
    )
    assert text == "测试转写"
    url, kwargs = requests.calls[0]
    assert url == endpoint["url"]
    assert kwargs["headers"]["Authorization"] == "Bearer secret-test-key"
    body = kwargs["json"]
    assert body["model"] == "fixture-unrelated-deployment"
    assert body["input"]["messages"][0]["content"][0]["text"] == "游戏专名上下文"
    assert body["input"]["messages"][1]["content"][0]["audio"].startswith(
        "data:audio/wav;base64,UklGR"
    )


def test_asr_api_supports_openai_compatible_transcription_protocol():
    requests = FakeRequests()
    requests.post = lambda url, **kwargs: (
        requests.calls.append((url, kwargs)) or OpenAIResponse()
    )
    endpoint = {
        "provider": "groq",
        "protocol": "openai_transcription",
        "model": "whisper-large-v3-turbo",
        "url": "https://api.groq.com/openai/v1/audio/transcriptions",
        "api_key": "groq-secret",
    }

    result = call_qwen_asr_api(
        np.zeros(1600, dtype=np.float32),
        "游戏专名上下文",
        endpoint=endpoint,
        requests_module=requests,
    )

    # 三十五轮：转写协议返回 dict（verbose_json 语义），纯文本在 "text" 里
    assert result["text"] == "云端复核文本"
    assert result["segments"] == []
    _url, kwargs = requests.calls[0]
    assert kwargs["headers"] == {"Authorization": "Bearer groq-secret"}
    assert kwargs["data"]["model"] == "whisper-large-v3-turbo"
    assert kwargs["data"]["prompt"] == "游戏专名上下文"
    assert kwargs["data"]["response_format"] == "verbose_json"
    assert kwargs["files"]["file"][0] == "chunk.wav"
    assert kwargs["files"]["file"][1].startswith(b"RIFF")


def test_qwen_backend_switch_applies_without_process_restart(monkeypatch):
    monkeypatch.setattr(asr, "QWEN_ASR_BACKEND", "local")
    monkeypatch.setattr(asr, "USE_QWEN_ASR_REFERENCE", True)
    monkeypatch.setattr(subtitle_core, "QWEN_ASR_BACKEND", "off")
    monkeypatch.setattr(subtitle_core, "USE_QWEN_ASR_REFERENCE", False)
    assert asr.transcribe_qwen_reference("missing.wav", [], shared_audio=None) == []
