"""P8C-R3 provider profile isolation, secret resolution and invocation audit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from twobyteasr.providers import llm_config
from twobyteasr.providers.llm_config import (
    ACTIVE_SERVICE_KEY,
    AI_SERVICE_SPECS,
    PROFILES_KEY,
    activate_ai_service,
    active_service_values,
    endpoint_from_settings,
    get_active_service,
    models_url,
    normalize_base_url,
    read_api_key,
    resolved_service_values,
    update_active_profile,
)
from twobyteasr.storage.settings import load_runtime_settings, save_runtime_settings


def _settings(models=None, **switches) -> dict:
    return {
        "models": dict(models or {}),
        "switches": {"unified_glm_processing": False, **switches},
    }


# ---------------------------------------------------------------- settings 序列化


def test_settings_roundtrip_preserves_profiles(tmp_path):
    settings = _settings({
        "ai_service": "deepseek",
        "provider_profiles": {
            "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "protocol": "auto"},
            "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.7-flash-high", "protocol": "auto"},
        },
        "polish_provider": "deepseek",
        "polish_model": "deepseek-chat",
        "polish_base_url": "https://api.deepseek.com/v1",
    })
    validated, path, _warnings = save_runtime_settings(settings, tmp_path)
    loaded, _path2, warnings2 = load_runtime_settings(tmp_path)
    assert loaded["models"][ACTIVE_SERVICE_KEY] == "deepseek"
    assert loaded["models"][PROFILES_KEY]["gemini"]["model"] == "gemini-3.7-flash-high"
    assert loaded["models"][PROFILES_KEY]["deepseek"]["base_url"] == "https://api.deepseek.com/v1"
    assert not [w for w in warnings2 if "provider_profiles" in w or "ai_service" in w]


def test_settings_reject_non_object_profiles(tmp_path):
    settings = _settings({
        "provider_profiles": "not-a-dict",
        "polish_provider": "deepseek",
        "polish_model": "deepseek-chat",
        "polish_base_url": "https://api.deepseek.com/v1",
    })
    loaded, _p, warnings = load_runtime_settings(tmp_path)
    validated, _p2, _w2 = save_runtime_settings(settings, tmp_path)
    assert validated["models"][PROFILES_KEY] == {}
    assert any("provider_profiles" in w for w in warnings) is False


# ---------------------------------------------------------------- 原子切换


def test_activate_ai_service_switches_every_field_atomically():
    settings = _settings({
        "polish_provider": "gemini",
        "polish_model": "gemini-3.7-flash-high",
        "polish_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "polish_transport": "openai_compatible",
    })
    values = activate_ai_service(settings, "deepseek", stage="polish", unified=False)
    models = settings["models"]
    assert values["base_url"] == "https://api.deepseek.com/v1"
    assert models["polish_provider"] == "deepseek"
    assert models["polish_base_url"] == "https://api.deepseek.com/v1"
    assert models["polish_model"] == AI_SERVICE_SPECS["deepseek"]["model"]
    assert models["polish_transport"] == "openai_compatible"
    assert models[ACTIVE_SERVICE_KEY] == "deepseek"
    # No google/gemini residue may survive the switch.
    assert "gemini" not in json.dumps({k: v for k, v in models.items() if k.startswith("polish_")})


def test_profiles_keep_per_provider_model_selections():
    settings = _settings({})
    activate_ai_service(settings, "deepseek", stage="polish", unified=False)
    update_active_profile(settings, stage="polish", model="deepseek-chat-v4", unified=False)
    activate_ai_service(settings, "gemini", stage="polish", unified=False)
    update_active_profile(settings, stage="polish", model="gemini-3.7-flash-high", unified=False)
    # Switch back: deepseek profile must still own its model and endpoint.
    activate_ai_service(settings, "deepseek", stage="polish", unified=False)
    values = active_service_values(settings)
    assert values["model"] == "deepseek-chat-v4"
    assert values["base_url"] == "https://api.deepseek.com/v1"
    activate_ai_service(settings, "gemini", stage="polish", unified=False)
    assert active_service_values(settings)["model"] == "gemini-3.7-flash-high"


def test_unified_mode_mirrors_group_fields():
    settings = _settings(unified_glm_processing=True)
    activate_ai_service(settings, "deepseek", stage="polish")
    assert settings["models"]["group_provider"] == "deepseek"
    assert settings["models"]["group_base_url"] == "https://api.deepseek.com/v1"


def test_endpoint_from_settings_follows_activation():
    settings = _settings({})
    activate_ai_service(settings, "deepseek", stage="polish", unified=False)
    endpoint = endpoint_from_settings(settings, "polish")
    assert endpoint["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert endpoint["provider"] == "deepseek"


# ---------------------------------------------------------------- 混合状态自愈


def test_legacy_mixed_state_heals_to_spec_endpoint():
    # Historic bug state: provider=deepseek persisted together with the
    # Google base URL and a gemini model.
    settings = _settings({
        "polish_provider": "deepseek",
        "polish_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "polish_model": "gemini-3.7-flash-high",
    })
    values = active_service_values(settings)
    assert values["service"] == "deepseek"
    assert values["base_url"] == "https://api.deepseek.com/v1"
    assert values["model"] == AI_SERVICE_SPECS["deepseek"]["model"]


def test_genuine_custom_base_for_known_provider_is_kept():
    settings = _settings({
        "polish_provider": "deepseek",
        "polish_base_url": "https://deepseek-proxy.example.com/v1",
        "polish_model": "deepseek-chat",
    })
    values = active_service_values(settings)
    assert values["base_url"] == "https://deepseek-proxy.example.com/v1"


# ---------------------------------------------------------------- 密钥解析


def test_canonical_host_fallback_finds_key_saved_under_provider_host(monkeypatch):
    payload = {"schema": 2, "API__deepseek__api.deepseek.com": "sk-canonical"}
    monkeypatch.setattr(llm_config, "_read_secrets", lambda: dict(payload))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # Requested base is a different endpoint of the SAME provider.
    key, source = read_api_key("deepseek", "https://deepseek-proxy.example.com/v1")
    assert key == "sk-canonical"
    assert "api.deepseek.com" in source


def test_scoped_key_never_crosses_providers(monkeypatch):
    payload = {"schema": 2, "API__gemini__generativelanguage.googleapis.com": "sk-google"}
    monkeypatch.setattr(llm_config, "_read_secrets", lambda: dict(payload))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    key, _source = read_api_key("deepseek", "https://api.deepseek.com/v1")
    assert key == ""


def test_env_standard_name_wins_for_provider(monkeypatch):
    monkeypatch.setattr(llm_config, "_read_secrets", lambda: {"schema": 2})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    key, source = read_api_key("deepseek", "https://api.deepseek.com/v1")
    assert key == "sk-env"
    assert "DEEPSEEK_API_KEY" in source


# ---------------------------------------------------------------- 模型发现 URL


def test_models_url_handles_gemini_openai_mount():
    gemini = AI_SERVICE_SPECS["gemini"]["base_url"]
    assert models_url(gemini) == normalize_base_url(gemini) + "/models"
    assert models_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1/models"
    assert models_url("https://example.com") == "https://example.com/v1/models"


# ---------------------------------------------------------------- invocation 审计


def test_record_llm_invocation_writes_row_without_key(tmp_path, monkeypatch):
    from twobyteasr.providers import llm_adapter

    logs = tmp_path / "logs"
    monkeypatch.setattr(
        llm_adapter, "user_data_root", lambda: tmp_path, raising=False
    )
    import twobyteasr.runtime_paths as runtime_paths

    monkeypatch.setattr(runtime_paths, "user_data_root", lambda: tmp_path)
    llm_adapter.record_llm_invocation(
        stage="polish",
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        url="https://api.deepseek.com/v1/chat/completions",
        key_source="环境变量 DEEPSEEK_API_KEY",
        key_present=True,
        status_code=200,
        duration_ms=123.4,
    )
    rows = [json.loads(line) for line in (logs / "llm_invocations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["provider"] == "deepseek"
    assert rows[-1]["endpoint"] == "https://api.deepseek.com/v1/chat/completions"
    assert rows[-1]["ok"] is True
    assert rows[-1]["auth_source"] == "环境变量 DEEPSEEK_API_KEY"
    blob = (logs / "llm_invocations.jsonl").read_text(encoding="utf-8")
    assert "sk-" not in blob
