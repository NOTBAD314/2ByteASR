"""Bounded regression gates for ASR provider identity (no real network/CLI)."""
import copy
import json
from dataclasses import FrozenInstanceError, replace
import pytest

from twobyteasr.providers import llm_config


def config(service="deepseek"):
    return {"models": {"ai_service": service,
        "group_provider": "grok", "group_transport": "grok_cli", "group_model": "stale-cli",
        "polish_transport": "grok_cli", "polish_provider": "grok", "polish_model": "stale-cli",
        "provider_profiles": {"deepseek": {"model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1", "protocol": "openai_compatible_chat"},
                              "grok_account": {"model": "grok-4.6"}}},
        "switches": {"unified_glm_processing": False}}


@pytest.fixture
def snapshot(monkeypatch):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a: ("test-secret", "fixture"))
    return resolve_provider_snapshot(config())


def test_active_profile_overrides_stale_flat_routes_and_is_immutable(snapshot):
    from twobyteasr.providers.ai_providers import adapter_for_stage, OpenAICompatibleProvider
    for stage in ("polish", "group"):
        adapter = adapter_for_stage(snapshot.execution_settings(), stage, sender=lambda *a, **k: "{}")
        assert isinstance(adapter, OpenAICompatibleProvider)
        assert adapter.endpoint["model"] == "deepseek-v4-pro"
        assert adapter.endpoint["provider"] == "deepseek"
    with pytest.raises(FrozenInstanceError):
        snapshot.model = "changed"
    assert "test-secret" not in repr(snapshot)
    assert "test-secret" not in json.dumps(snapshot.public_identity())


def test_only_explicit_cli_selection_constructs_cli(monkeypatch):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from twobyteasr.providers import ai_providers
    calls = []
    monkeypatch.setattr(ai_providers, "GrokCLIProvider", lambda **k: calls.append(k) or k)
    snap = resolve_provider_snapshot(config("grok_account"))
    assert snap.kind == "cli"
    ai_providers.adapter_for_stage(snap.execution_settings(), "group")
    assert calls == [{"model": "grok-4.6"}]


@pytest.mark.parametrize("field,value", [("model", "other"), ("base_url", "https://alternate.example/v1"), ("protocol", "responses")])
def test_profile_changes_invalidate_snapshot(snapshot, monkeypatch, field, value):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    changed = config()
    changed["models"]["provider_profiles"]["deepseek"][field] = value
    other = resolve_provider_snapshot(changed)
    assert other.fingerprint != snapshot.fingerprint
    assert other.cache_identity() != snapshot.cache_identity()


def test_transport_changes_identity(snapshot):
    changed = replace(snapshot, transport="grok_cli", kind="cli")
    assert changed.fingerprint != snapshot.fingerprint


def test_production_rule_versions_are_pinned_in_public_identity_and_cache(snapshot, monkeypatch):
    from twobyteasr.subtitle_rules import number_fidelity
    from twobyteasr.glossary import terminology_retrieval
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot, POLISH_PROMPT_VERSION
    identity = snapshot.public_identity()
    assert identity['numeric_rules'] == number_fidelity.RULE_VERSION
    assert identity['prompt_versions']['polished'] == POLISH_PROMPT_VERSION
    assert identity['terminology_retrieval_rules'] == terminology_retrieval.RULE_VERSION
    original_fingerprint = snapshot.fingerprint
    monkeypatch.setattr(number_fidelity, 'RULE_VERSION', 'fixture-next-numeric-policy')
    monkeypatch.setattr(terminology_retrieval, 'RULE_VERSION', 'fixture-next-recall-policy')
    changed = resolve_provider_snapshot(config())
    assert changed.fingerprint != original_fingerprint
    assert snapshot.fingerprint == original_fingerprint
    assert changed.numeric_rules == 'fixture-next-numeric-policy'
    assert changed.terminology_retrieval_rules == 'fixture-next-recall-policy'


def test_unselected_legacy_cli_is_rejected():
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    with pytest.raises(ValueError, match="explicitly selected"):
        resolve_provider_snapshot(config(""))


def test_custom_profile_ignores_stale_cli_flat_field(monkeypatch):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    monkeypatch.setattr(llm_config,"read_scoped_api_key",lambda *a:('test','fixture'))
    settings=config('custom')
    settings['models']['provider_profiles']['custom']={'base_url':'https://example.com/v1','model':'custom-model','protocol':'openai_compatible_chat'}
    snapshot=resolve_provider_snapshot(settings)
    assert snapshot.kind=='http' and snapshot.transport=='openai_compatible'


def test_endpoint_queries_never_leak_but_affect_identity(monkeypatch):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    monkeypatch.setattr(llm_config, "read_scoped_api_key", lambda *a: ("secret", "fixture"))
    source = config()
    source["models"]["provider_profiles"]["deepseek"]["base_url"] = "https://api.deepseek.com/v1?token=private-query"
    one = resolve_provider_snapshot(source)
    assert "private-query" not in json.dumps(one.public_identity())
    source["models"]["provider_profiles"]["deepseek"]["base_url"] += "2"
    assert resolve_provider_snapshot(source).fingerprint != one.fingerprint


@pytest.mark.parametrize("source,expected", [("timeout", "total_timeout"), ("provider_inactivity_timeout", "read_idle_timeout"),
    ("rate_limit", "rate_limited"), ("server_error", "server_error"), ("cli_exit", "cli_exit"),
    ("structured_empty_response", "empty_response"), ("structured_json_parse_error", "parse_failure"),
    ("response_schema_error", "format_mismatch"), ("text_mutation_rejected", "text_mutation_rejected"),
    ("cancelled", "cancelled"), ("queue_timeout", "queue_timeout")])
def test_error_categories(source, expected):
    from twobyteasr.providers.asr_provider_snapshot import classify_request_error
    from twobyteasr.providers.ai_providers import AIProviderError
    assert classify_request_error(AIProviderError("fixture", category=source)) == expected


def test_requests_timeout_categories():
    import requests
    from twobyteasr.providers.asr_provider_snapshot import classify_request_error
    assert classify_request_error(requests.ConnectTimeout()) == "connect_timeout"
    assert classify_request_error(requests.ReadTimeout()) == "read_idle_timeout"


def test_http_failure_never_constructs_cli(snapshot, monkeypatch):
    from twobyteasr.providers import ai_providers
    def forbidden(**kwargs):
        pytest.fail("HTTP silently switched to CLI")
    monkeypatch.setattr(ai_providers, "GrokCLIProvider", forbidden)
    def failed(*args, **kwargs):
        raise ai_providers.AIProviderError("HTTP failed", category="server_error")
    adapter = ai_providers.adapter_for_stage(snapshot.execution_settings(), "group", sender=failed)
    with pytest.raises(ai_providers.AIProviderError, match="HTTP failed"):
        adapter.complete([], max_tokens=10)


def test_task_snapshot_stays_identical_after_settings_rebind(snapshot):
    from twobyteasr.providers.asr_provider_snapshot import task_provider_snapshot
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    context = RuntimeContext(provider_snapshot=snapshot)
    with activate_runtime_context(context):
        assert task_provider_snapshot("polish") is task_provider_snapshot("group") is snapshot


def test_boundary_text_validator_rejects_mutation_and_accepts_punctuation():
    from twobyteasr.providers.asr_provider_snapshot import validate_grouped_text
    from types import SimpleNamespace as Row
    assert validate_grouped_text([Row(text="你好，世界")], [Row(text="你好，"), Row(text="世界")])
    assert not validate_grouped_text([Row(text="你好，世界")], [Row(text="你好世界")])
    assert not validate_grouped_text([Row(text="你好")], [Row(text="您好")])
