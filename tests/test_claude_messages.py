"""Claude through the Anthropic Messages API on the application's own HTTP layer (2026-10-18).

No network: network_policy.post / get are replaced by recorded fakes.
"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from twobyteasr import anthropic_messages as am
from twobyteasr.provider_stream import StreamProtocolError


def sse(*events):
    lines = []
    for event in events:
        lines.append(f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")
    return "".join(lines).encode("utf-8")


def stream_events(text="你好", stop_reason="end_turn", stop_details=None):
    return [
        {"type": "message_start", "message": {"id": "msg_01", "model": "claude-opus-5-5",
                                              "usage": {"input_tokens": 12, "cache_read_input_tokens": 3}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": ""}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "ping"},
        *({"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": part}} for part in text),
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_details": stop_details},
         "usage": {"output_tokens": 7}},
        {"type": "message_stop"},
    ]


class FakeResponse:
    def __init__(self, status, body, content_type="text/event-stream", headers=None):
        self.status_code = status
        self._body = body
        self.headers = {"Content-Type": content_type, **(headers or {})}

    def iter_content(self, chunk_size=1024):
        for start in range(0, len(self._body), 7):  # small chunks: framing must not depend on them
            yield self._body[start:start + 7]

    def close(self):
        pass


@pytest.fixture
def posted(monkeypatch):
    calls = []

    def install(response):
        def post(url, headers=None, json=None, stream=False, timeout=None):
            calls.append({"url": url, "headers": dict(headers or {}), "body": json})
            return response
        from twobyteasr import network_policy
        monkeypatch.setattr(network_policy, "post", post)
        return calls
    return install


# ------------------------------------------------------------------ catalog / endpoint


def test_claude_is_an_api_key_service_with_the_messages_endpoint(monkeypatch):
    from twobyteasr import llm_config
    spec = llm_config.AI_SERVICE_SPECS["claude"]
    assert spec["label"] == "Claude API" and spec["provider"] == "anthropic"
    assert spec["models"] == ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
    assert spec["model"] == "claude-opus-5-5" and "structured_output" in spec["capabilities"]
    assert llm_config.messages_url("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"
    assert llm_config.messages_url("https://api.anthropic.com/v1/messages") == "https://api.anthropic.com/v1/messages"
    assert llm_config.models_url("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/models"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    settings = {"models": {"ai_service": "claude"}, "switches": {"unified_glm_processing": True}}
    llm_config.activate_ai_service(settings, "claude")
    endpoint = llm_config.endpoint_from_settings(settings, "polish")
    assert endpoint["provider"] == "anthropic" and endpoint["protocol"] == "anthropic_messages"
    assert endpoint["url"] == "https://api.anthropic.com/v1/messages"
    assert endpoint["api_key"] == "sk-ant-test"
    assert llm_config.auth_headers("k", "anthropic") == {"x-api-key": "k", "anthropic-version": "2023-06-01"}
    assert llm_config.auth_headers("k") == {"Authorization": "Bearer k"}


def test_settings_editor_maps_the_anthropic_host_to_claude():
    from twobyteasr.ui import EndpointEditor
    assert EndpointEditor._service_for_settings("openai_compatible", "", "https://api.anthropic.com/v1") == "claude"


# ------------------------------------------------------------------ request shape


def test_messages_convert_system_images_and_trailing_assistant():
    system, messages = am.convert_messages([
        {"role": "system", "content": "你是字幕校对。"},
        {"role": "user", "content": [{"type": "text", "text": "看这张图"},
                                     {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}]},
        {"role": "assistant", "content": "{"},
    ])
    assert system == "你是字幕校对。"
    assert messages[0]["content"][1] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                                     "data": "QUJD"}}
    assert messages[-1] == {"role": "user", "content": "Continue."}  # no assistant prefill on these models


def test_request_body_has_no_sampling_and_falls_back_only_where_offered():
    body = am.request_body("claude-opus-5-5", [{"role": "user", "content": "hi"}], max_tokens=100,
                           json_wanted=True, effort="low")
    assert "temperature" not in body and body["stream"] is True
    assert body["fallbacks"] == "default" and body["output_config"] == {"effort": "low"}
    assert am.JSON_INSTRUCTION in body["system"]
    assert "fallbacks" not in am.request_body("claude-haiku-5-5", [{"role": "user", "content": "hi"}], max_tokens=10)
    headers = am.request_headers("sk-ant-x", "claude-sonnet-5-5")
    assert headers["anthropic-beta"] == am.FALLBACK_BETA and headers["x-api-key"] == "sk-ant-x"
    assert "anthropic-beta" not in am.request_headers("sk-ant-x", "claude-haiku-5-5")
    assert am.output_budget(16) == 2064 and am.output_budget(3500) == 7000 and am.output_budget(50_000) == 64_000


# ------------------------------------------------------------------ stream parsing


def test_stream_text_usage_and_request_id():
    diagnostics, events = {}, []
    text = am.messages_body(iter([sse(*stream_events("字幕"))]), diagnostics, lambda kind, value: events.append(kind))
    assert text == "字幕"
    assert diagnostics["request_id"] == "msg_01" and diagnostics["finish_reason"] == "end_turn"
    assert diagnostics["prompt_tokens"] == 15 and diagnostics["completion_tokens"] == 7
    assert diagnostics["total_tokens"] == 22 and events.count("delta") == 2 and events[-1] == "final"


@pytest.mark.parametrize("stop_reason, category", [("refusal", "provider_refusal"),
                                                   ("max_tokens", "structured_output_truncated"),
                                                   ("tool_use", "provider_tool_request")])
def test_unfinished_answers_are_errors(stop_reason, category):
    with pytest.raises(StreamProtocolError) as caught:
        am.messages_body(iter([sse(*stream_events("x", stop_reason, {"category": "cyber"}))]), {})
    assert caught.value.category == category


def test_stream_error_event_and_cut_stream():
    overload = [stream_events()[0], {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}]
    with pytest.raises(StreamProtocolError) as caught:
        am.messages_body(iter([sse(*overload)]), {})
    assert caught.value.category == "server_error"
    with pytest.raises(StreamProtocolError) as caught:
        am.messages_body(iter([sse(*stream_events()[:-1])]), {})
    assert caught.value.category == "structured_output_truncated"


# ------------------------------------------------------------------ transport


@pytest.mark.parametrize("status, kind, category", [(401, "authentication_error", "auth_error"),
                                                    (402, "billing_error", "quota_exhausted"),
                                                    (404, "not_found_error", "model_not_supported"),
                                                    (529, "overloaded_error", "server_error")])
def test_http_errors_use_the_anthropic_error_type(posted, status, kind, category):
    from twobyteasr.llm_adapter import LLMRequestError
    body = json.dumps({"type": "error", "error": {"type": kind, "message": "nope"}}).encode()
    posted(FakeResponse(status, body, "application/json", {"Retry-After": "7"}))
    endpoint = {"model": "claude-haiku-5-5", "api_key": "sk-ant-x", "url": "https://api.anthropic.com/v1/messages",
                "base_url": "https://api.anthropic.com/v1"}
    with pytest.raises(LLMRequestError) as caught:
        am.complete(endpoint, [{"role": "user", "content": "hi"}], max_tokens=50, timeout=5)
    assert caught.value.category == category
    assert getattr(caught.value, "retry_after_seconds", None) == 7.0


def test_provider_sends_a_messages_request_and_parses_json(posted):
    from twobyteasr.ai_providers import OpenAICompatibleProvider
    calls = posted(FakeResponse(200, sse(*stream_events('{"ok": true, "text": "兔白字幕"}'))))
    endpoint = {"provider": "anthropic", "model": "claude-sonnet-5-5", "protocol": "anthropic_messages",
                "api_key": "sk-ant-x", "url": "https://api.anthropic.com/v1/messages",
                "base_url": "https://api.anthropic.com/v1", "key_source": "test"}
    provider = OpenAICompatibleProvider(endpoint, sender=lambda *a, **k: pytest.fail("OpenAI sender used"))
    value = provider.structured_complete([{"role": "system", "content": "只回 JSON"},
                                          {"role": "user", "content": "测试"}],
                                         {"type": "object"}, max_tokens=80, temperature=0.0, timeout=5,
                                         stage="provider_readiness")
    assert value == {"ok": True, "text": "兔白字幕"}
    call = calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "sk-ant-x" and call["headers"]["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in call["headers"]
    assert call["body"]["model"] == "claude-sonnet-5-5" and "temperature" not in call["body"]
    assert call["body"]["system"].startswith("只回 JSON") and call["body"]["output_config"] == {"effort": "low"}
    assert provider.last_invocation_trace["request_id"] == "msg_01"
    assert provider.last_invocation_trace["reported_usage"]["completion_tokens"] == 7


def test_missing_key_is_said_plainly(posted):
    from twobyteasr.ai_providers import AIProviderError, OpenAICompatibleProvider
    posted(FakeResponse(200, b""))
    provider = OpenAICompatibleProvider({"provider": "anthropic", "model": "claude-opus-5-5",
                                         "protocol": "anthropic_messages", "api_key": "",
                                         "url": "https://api.anthropic.com/v1/messages"})
    with pytest.raises(AIProviderError) as caught:
        provider.complete([{"role": "user", "content": "hi"}], max_tokens=10)
    assert caught.value.category == "auth_config" and "Anthropic Console" in str(caught.value)


def test_model_list_uses_anthropic_headers_and_after_id(monkeypatch):
    from twobyteasr import model_discovery, network_policy
    pages = [{"data": [{"id": "claude-opus-5-5", "max_input_tokens": 1_000_000, "max_tokens": 128_000,
                        "capabilities": {"image_input": {"supported": True}}}],
              "has_more": True, "last_id": "claude-opus-5-5"},
             {"data": [{"id": "claude-haiku-5-5"}], "has_more": False, "last_id": "claude-haiku-5-5"}]
    seen = []

    class Response:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def get(url, headers=None, params=None, timeout=None, allow_redirects=False):
        seen.append((url, dict(headers or {}), dict(params or {})))
        return Response(pages[len(seen) - 1])

    monkeypatch.setattr(network_policy, "get", get)
    result = model_discovery.discover("anthropic", "https://api.anthropic.com/v1", "sk-ant-x", force=True)
    ids = [row["id"] for row in result["records"]]
    assert ids == ["claude-opus-5-5", "claude-haiku-5-5"]
    assert seen[0][0] == "https://api.anthropic.com/v1/models" and seen[0][1]["x-api-key"] == "sk-ant-x"
    assert seen[1][2] == {"after_id": "claude-opus-5-5", "limit": 100}
    first = result["records"][0]
    assert first["input_tokens"] == 1_000_000 and first["output_tokens"] == 128_000
    assert first["input_modalities"] == ["text", "image"]
