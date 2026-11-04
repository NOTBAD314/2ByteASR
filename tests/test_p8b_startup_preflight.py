"""P8B startup model prompts consume unified ModelRegistry health."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from twobyteasr.local_models.model_registry import ModelHealth, ModelRecord, ModelRegistry
from twobyteasr.app.ui import required_recognition_model_keys, startup_model_preflight


def _record(key: str, health: ModelHealth) -> ModelRecord:
    return ModelRecord(
        model_id=key,
        version="test",
        installation_path=Path("models") / key,
        source="test",
        expected_files=("model.bin",),
        health=health,
        size_bytes=1,
        expected_bytes=1,
        runtime_environment=".venv-main",
        compatible=health is not ModelHealth.INCOMPATIBLE,
    )


def _registry(**health: ModelHealth) -> ModelRegistry:
    return ModelRegistry(
        install_root=Path("."),
        model_root=Path("models"),
        records={key: _record(key, value) for key, value in health.items()},
    )


def test_quality_plan_requires_only_its_selected_models():
    values = {
        "models": {
            "primary_asr_backend": "moss",
            "firered_asr_backend": "local",
            "qwen_asr_backend": "local",
        }
    }
    assert required_recognition_model_keys(values) == (
        "firered_aed",
        "firered_vad",
        "moss",
        "qwen_asr",
        "speaker_embedding",
    )


def test_installed_quality_plan_never_prompts_even_without_legacy_marker():
    values = {
        "models": {
            "primary_asr_backend": "moss",
            "firered_asr_backend": "local",
            "qwen_asr_backend": "local",
        }
    }
    registry = _registry(
        moss=ModelHealth.INSTALLED,
        firered_vad=ModelHealth.INSTALLED,
        speaker_embedding=ModelHealth.INSTALLED,
        firered_aed=ModelHealth.INSTALLED,
        qwen_asr=ModelHealth.INSTALLED,
    )
    result = startup_model_preflight(values, registry=registry)
    assert result.installed_count == 5
    assert result.missing_keys == ()
    assert result.corrupt_keys == ()
    assert result.should_prompt is False


def test_required_missing_partial_corrupt_or_incompatible_model_prompts():
    values = {
        "primary_asr_backend": "moss",
        "firered_asr_backend": "local",
        "qwen_asr_backend": "local",
    }
    registry = _registry(
        moss=ModelHealth.INSTALLED,
        firered_vad=ModelHealth.PARTIAL,
        speaker_embedding=ModelHealth.INSTALLED,
        firered_aed=ModelHealth.CORRUPT,
        qwen_asr=ModelHealth.INCOMPATIBLE,
    )
    result = startup_model_preflight(values, registry=registry)
    assert result.missing_keys == ("firered_vad",)
    assert result.corrupt_keys == ("firered_aed", "qwen_asr")
    assert result.should_prompt is True


def test_unselected_missing_catalog_models_do_not_prompt():
    values = {
        "models": {
            "primary_asr_backend": "api",
            "firered_asr_backend": "off",
            "qwen_asr_backend": "off",
        }
    }
    result = startup_model_preflight(values, registry=_registry())
    assert result.required_keys == ()
    assert result.should_prompt is False


def test_startup_skips_dialog_when_registry_preflight_is_healthy(monkeypatch):
    from twobyteasr.app import ui

    healthy = ui.StartupModelPreflight(5, ("moss",), (), ())
    monkeypatch.delenv("TWOBYTEASR_SKIP_FIRST_RUN_WIZARD", raising=False)
    monkeypatch.setattr(ui, "startup_model_preflight", lambda _settings: healthy)

    class UnexpectedDialog:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("healthy registry must not open model setup")

    monkeypatch.setattr(ui, "GuidedSetupDialog", UnexpectedDialog)
    parent = SimpleNamespace(
        legacy=SimpleNamespace(RUNTIME_SETTINGS={"models": {}}),
    )
    ui._run_first_run_wizard(parent)
