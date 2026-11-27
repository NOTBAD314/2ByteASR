"""Final HTTP bodies, provider evidence, and scoped thinking configuration."""
import json
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
import requests

from twobyteasr.providers import asr_http_transport, llm_adapter, network_policy
from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
from twobyteasr.providers.reasoning_adapter import encode_profile, profile_key, wire_identity


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(tmp_path))
    rows = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            rows.append(body)
            model = body.get("model", "")
            if model == "reject":
                packet = {"error": {"param": "thinking.type", "message": "unsupported thinking.type"}}
                status = 400
            elif self.path.endswith(":generateContent"):
                packet = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "ok"}]}}],
                          "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1, "thoughtsTokenCount": 0}}
                status = 200
            elif self.path.endswith("/messages"):
                packet = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                          "usage": {"input_tokens": 3, "output_tokens": 1,
                                    "output_tokens_details": {"thinking_tokens": 0}}}
                status = 200
            elif self.path.endswith("/responses"):
                packet = {"status": "completed", "output_text": "ok",
                          "usage": {"input_tokens": 3, "output_tokens": 1,
                                    "output_tokens_details": {"reasoning_tokens": 0}}}
                status = 200
            elif body.get("stream"):
                packets = [
                    {"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.encrypted"}]},
                                  "finish_reason": None}]},
                    {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]},
                    {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 5, "reasoning_tokens": 4}},
                ]
                data = "".join(f"data: {json.dumps(part)}\n\n" for part in packets) + "data: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(data.encode())
                return
            else:
                message = {"content": "ok"}
                if model == "leak":
                    message["reasoning_details"] = [{"type": "reasoning.encrypted"}]
                packet = {"choices": [{"message": message, "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 3, "completion_tokens": 5}}
                if model != "unknown":
                    packet["usage"]["completion_tokens_details"] = {"reasoning_tokens": 0}
                status = 200
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(packet).encode())

        def log_message(self, *_):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    original_post = requests.post

    def local_post(url, **kwargs):
        from urllib.parse import urlsplit
        return original_post(f"http://127.0.0.1:{httpd.server_port}{urlsplit(url).path}", **kwargs)

    monkeypatch.setattr(requests, "post", local_post)
    monkeypatch.setattr(network_policy, "post", local_post)
    try:
        yield rows
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(2)


MESSAGES = [{"role": "user", "content": "synthetic-test-cue"}]


def request(base, model, *, mode="off", dialect="auto", protocol="chat", custom=None):
    suffix = {"anthropic": "/messages", "responses": "/responses",
              "gemini": "/models/" + model + ":generateContent"}.get(protocol, "/chat/completions")
    common = dict(model=model, base_url=base, url=base + suffix, api_key="fixture-token",
                  max_tokens=4096, reasoning_profile=encode_profile(mode, dialect, custom or {}))
    if protocol == "stream":
        return llm_adapter.post_chat_completion_stream(MESSAGES, **common, on_stream_event=lambda *_: None)
    if protocol == "anthropic":
        from twobyteasr.providers.anthropic_messages import complete
        body = {key: common[key] for key in ("model", "url", "api_key", "base_url")}
        return complete(body, MESSAGES, max_tokens=4096, timeout=5, reasoning_profile=common["reasoning_profile"])
    if protocol == "responses":
        return llm_adapter.post_responses(MESSAGES, **common, temperature=None)
    if protocol == "gemini":
        return asr_http_transport.complete(MESSAGES, **common, protocol="gemini")
    return llm_adapter.post_chat_completion(MESSAGES, **common)


@pytest.mark.parametrize("base,model,protocol,expected", [
    ("https://api.deepseek.com", "deepseek-flash", "chat", {"thinking": {"type": "disabled"}}),
    ("https://api.deepseek.com", "deepseek-flash", "responses", {"reasoning": {"effort": "none"}}),
    ("https://api.deepseek.com", "deepseek-flash", "anthropic", {"thinking": {"type": "disabled"}}),
    ("https://openrouter.ai/api/v1", "deepseek/deepseek-flash", "chat", {"reasoning": {"enabled": False}}),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.5-flash", "chat", {"enable_thinking": False}),
    ("https://api.openai.com/v1", "gpt-5.1", "chat", {"reasoning_effort": "none"}),
    ("https://api.openai.com/v1", "gpt-5.1", "responses", {"reasoning": {"effort": "none"}}),
    ("https://api.anthropic.com/v1", "claude-sonnet-5-5", "anthropic", {"thinking": {"type": "between_tools"}}),
    ("https://api.anthropic.com/v1", "claude-sonnet-4-6", "anthropic", {"thinking": {"type": "disabled"}}),
    ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "chat", {"reasoning_effort": "none"}),
    ("https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash", "gemini",
     {"generationConfig": {"thinkingConfig": {"thinkingBudget": 0}, "maxOutputTokens": 4096, "temperature": 0.0}}),
])
def test_official_final_http_fields(server, base, model, protocol, expected):
    assert request(base, model, protocol=protocol) == "ok"
    from twobyteasr.providers.reasoning_adapter import THINKING_KEYS
    assert {key: value for key, value in server[-1].items() if key in THINKING_KEYS} == expected
    assert llm_adapter.get_last_llm_response_diagnostics()["thinking_compatibility"] == "reported_zero"


@pytest.mark.parametrize("dialect,expected", [
    ("deepseek", {"thinking": {"type": "disabled"}}),
    ("reasoning_effort", {"reasoning_effort": "none"}),
    ("deepseek_combined", {"thinking": {"type": "disabled"}, "reasoning_effort": "none"}),
])
def test_workbuddy_three_wire_dialects(server, dialect, expected):
    request("https://workbuddy.example.test/v1", "deepseek-v4.1-flash", dialect=dialect)
    assert {key: value for key, value in server[-1].items() if key in {"thinking", "reasoning_effort"}} == expected


def test_default_low_and_high_are_distinct(server):
    base = "https://api.deepseek.com"
    for mode in ("default", "low", "high"):
        request(base, "deepseek-flash", mode=mode)
    assert "thinking" not in server[0] and "reasoning_effort" not in server[0]
    assert [row["reasoning_effort"] for row in server[1:]] == ["low", "high"]


def test_supported_model_reply_with_no_usage_stays_unverified(server):
    request("https://relay.test/v1", "unknown", dialect="deepseek")
    diag = llm_adapter.get_last_llm_response_diagnostics()
    assert diag["reasoning_tokens"] is None
    assert diag["thinking_compatibility"] == "disable_unverified"


def test_visible_and_encrypted_evidence_take_priority_over_reported_zero(server):
    request("https://relay.test/v1", "leak", dialect="deepseek")
    diag = llm_adapter.get_last_llm_response_diagnostics()
    assert diag["reasoning_tokens"] == 0
    assert diag["thinking_compatibility"] == "reasoning_returned_despite_disable"


def test_sse_evidence_is_counted_and_not_in_answer(server):
    assert request("https://relay.test/v1", "test", dialect="deepseek", protocol="stream") == "ok"
    diag = llm_adapter.get_last_llm_response_diagnostics()
    assert diag["reasoning_content_present"] is True
    assert diag["reasoning_tokens"] == 4
    assert diag["thinking_compatibility"] == "reasoning_returned_despite_disable"


def test_rejection_does_not_remove_disable_or_retry(server):
    with pytest.raises(llm_adapter.LLMRequestError) as caught:
        request("https://relay.test/v1", "reject", dialect="deepseek", protocol="stream")
    assert caught.value.category == "reasoning_parameter_incompatible"
    assert caught.value.diagnostics["thinking_compatibility"] == "request_rejected"
    assert len(server) == 1 and server[0]["thinking"] == {"type": "disabled"}


def test_gemini_pro_requires_explicit_low(server):
    base = "https://generativelanguage.googleapis.com/v1beta/openai"
    with pytest.raises(llm_adapter.LLMRequestError) as caught:
        request(base, "gemini-3.1-pro-preview")
    assert caught.value.category == "reasoning_not_supported" and not server
    request(base, "gemini-3.1-pro-preview", mode="low")
    assert server[0]["reasoning_effort"] == "low"


def test_custom_parameters_are_scoped_and_do_not_override_messages(server):
    request("https://relay.test/v1", "work", custom={"reasoning": {"enabled": False}})
    assert server[-1]["reasoning"] == {"enabled": False}
    with pytest.raises(ValueError):
        request("https://relay.test/v1", "work", custom={"messages": []})
    with pytest.raises(llm_adapter.LLMRequestError):
        request("https://relay.test/v1", "work", custom={"reasoning_effort": "low"})


def test_snapshot_fingerprint_and_concurrent_calls_bind_wire_mode(server):
    base = "https://relay.test/v1"
    key = profile_key("custom", base, "model", "openai_compatible_chat")
    settings = {"models": {"group_provider": "custom", "group_model": "model",
                "group_transport": "openai_compatible", "group_base_url": base,
                "group_protocol": "openai_compatible_chat", "group_api_key": "fixture-token",
                "reasoning_profiles": {key: encode_profile("off", "deepseek", {})}}}
    off = resolve_provider_snapshot(settings)
    settings["models"]["reasoning_profiles"][key] = encode_profile("high", "reasoning_effort", {})
    high = resolve_provider_snapshot(settings)
    assert off.fingerprint != high.fingerprint
    assert wire_identity(off.endpoint())["parameters"] == {"thinking": {"type": "disabled"}}
    adapters = [OpenAICompatibleProvider(snapshot.endpoint()) for snapshot in (off, high)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda client: client.complete(MESSAGES), adapters)) == ["ok", "ok"]
    assert any(row.get("thinking") == {"type": "disabled"} for row in server)
    assert any(row.get("reasoning_effort") == "high" for row in server)

