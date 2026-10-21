from __future__ import annotations

import json
import sys
import threading
import time

import pytest

from twobyteasr.providers.ai_providers import AIProviderError, AITransport, ProviderStatus
from twobyteasr.system.processes import popen_hidden_subprocess
from twobyteasr.providers.provider_service import (
    ProviderHealthState,
    ProviderService,
)
from twobyteasr.system.resource_governor import ResourceGovernor


def _settings(**extra):
    models = {
        "polish_transport": AITransport.ANTIGRAVITY_CLI.value,
        "polish_model": "fixture-model",
    }
    models.update(extra)
    return {"models": models}


class _FakeAdapter:
    provider_id = "fixture"
    model = "fixture-model"

    def __init__(self, *, authenticated=True, failure: str = "", wait_for_cancel: bool = False):
        self.authenticated = authenticated
        self.failure = failure
        self.wait_for_cancel = wait_for_cancel
        self.complete_calls = 0
        self.started = threading.Event()

    def validate(self, **_kwargs):
        return ProviderStatus(True, self.authenticated, "ready" if self.authenticated else "login required")

    def complete(self, _messages, *, cancel_check=None, **_kwargs):
        self.complete_calls += 1
        self.started.set()
        if self.failure:
            raise AIProviderError("fixture failure", category=self.failure)
        if self.wait_for_cancel:
            while cancel_check is not None and not cancel_check():
                time.sleep(0.005)
            if cancel_check is not None and cancel_check():
                raise AIProviderError("cancelled", category="cancelled")
        return "fixture response"

    def structured_complete(self, _messages, _schema, **_kwargs):
        self.complete_calls += 1
        return {"ok": True}


def _service_with(monkeypatch, adapter, **kwargs):
    monkeypatch.setattr(
        "twobyteasr.providers.provider_service.adapter_for_stage",
        lambda *_args, **_named: adapter,
    )
    return ProviderService(governor=ResourceGovernor(), **kwargs)


def test_provider_service_fail_fast_known_unauthenticated(monkeypatch):
    adapter = _FakeAdapter(authenticated=False)
    service = _service_with(monkeypatch, adapter)
    client = service.client_for_stage(_settings(), "polish")
    client.validate(timeout=2.0)  # Establish known auth failure; no implicit CLI probe.
    started = time.monotonic()
    with pytest.raises(AIProviderError, match="登录") as raised:
        client.complete([{"role": "user", "content": "secret"}], timeout=2.0)
    assert raised.value.category == "authentication_required"
    assert time.monotonic() - started < 2.0
    assert adapter.complete_calls == 0
    assert client.health().state is ProviderHealthState.AUTH_REQUIRED


def test_provider_service_cancel_reaches_adapter(monkeypatch):
    adapter = _FakeAdapter(wait_for_cancel=True)
    service = _service_with(monkeypatch, adapter)
    handle = service.submit(
        _settings(), "polish", [{"role": "user", "content": "secret"}], timeout=5.0,
    )
    assert adapter.started.wait(1.0)
    started = time.monotonic()
    handle.cancel()
    with pytest.raises(AIProviderError) as raised:
        handle.result(1.0)
    assert raised.value.category == "cancelled"
    assert time.monotonic() - started < 0.5
    assert service.wait_for_idle(timeout=0.5)


def test_design_http_has_one_counted_request_and_no_hidden_probe_or_retry(monkeypatch):
    adapter=_FakeAdapter(failure='server_error')
    adapter.endpoint=dict(provider='custom',model='fixture',api_key='fixture',url='https://example.invalid/v1/chat/completions',base_url='https://example.invalid/v1')
    adapter.validate=lambda **k:pytest.fail('no hidden paid readiness probe')
    service=_service_with(monkeypatch,adapter)
    client=service.client_for_stage(_settings(polish_transport='openai_compatible'), 'polish')
    with pytest.raises(AIProviderError):client.complete([dict(role='user',content='JSON')],operation_kind='generate',timeout=2)
    assert adapter.complete_calls==1


def test_provider_service_circuit_breaker_and_redacted_telemetry(monkeypatch):
    adapter = _FakeAdapter(failure="connection")
    service = _service_with(
        monkeypatch, adapter, circuit_failures=2, circuit_seconds=30.0,
    )
    client = service.client_for_stage(_settings(), "polish")
    for _ in range(2):
        with pytest.raises(AIProviderError):
            client.complete([{"role": "user", "content": "TOP_SECRET_PROMPT"}], timeout=1.0)
    calls_after_open = adapter.complete_calls
    with pytest.raises(AIProviderError, match="circuit"):
        client.complete([{"role": "user", "content": "TOP_SECRET_PROMPT"}], timeout=1.0)
    assert adapter.complete_calls == calls_after_open
    assert "TOP_SECRET_PROMPT" not in json.dumps(service.telemetry(), ensure_ascii=False)


def test_native_schema_content_failure_does_not_open_provider_circuit(monkeypatch):
    adapter=_FakeAdapter(failure='structured_output_schema')
    service=_service_with(monkeypatch,adapter,circuit_failures=2,circuit_seconds=30)
    client=service.client_for_stage(_settings(),'polish')
    for _ in range(3):
        with pytest.raises(AIProviderError) as caught:
            client.complete([{'role':'user','content':'JSON'}],operation_kind='generate',timeout=1)
        assert caught.value.category=='structured_output_schema'
    assert adapter.complete_calls==3


def test_provider_capability_manifest_is_explicit_and_non_streaming(monkeypatch):
    service = _service_with(monkeypatch, _FakeAdapter())
    client = service.client_for_stage(
        _settings(polish_capabilities=["text", "vision", "reasoning"]), "polish",
    )
    manifest = client.capabilities()
    assert manifest.text and manifest.vision and manifest.reasoning
    assert not manifest.streaming and not manifest.tool_calling
    assert manifest.models == ("fixture-model",)


def test_hidden_process_instrumentation_redacts_sensitive_arguments(tmp_path, monkeypatch):
    log_path = tmp_path / "children.jsonl"
    monkeypatch.setenv("TWOBYTEASR_CHILD_PROCESS_LOG", str(log_path))
    secret = "TOP_SECRET_PROMPT"
    process = popen_hidden_subprocess(
        [sys.executable, "-c", "print('ok')", secret],
        purpose="redaction fixture",
        log_command=[sys.executable, "-c", "print('ok')", "<redacted-prompt>"],
        stdout=-1,
        stderr=-1,
        text=True,
    )
    process.communicate(timeout=5.0)
    payload = log_path.read_text(encoding="utf-8")
    assert secret not in payload
    assert "<redacted-prompt>" in payload
