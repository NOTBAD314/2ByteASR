"""换 AI 服务后模型下拉只列新服务的模型（2026-10-18 已知问题）。

以前在「AI 智能断句设置」里从阿里云百炼换成 Claude API / xAI / DeepSeek / Gemini，
模型框的值立刻换成新服务的默认模型，点开下拉却仍是百炼的 qwen3.7-…，要按「刷新模型」
才更新；选了旧选项会把别家的模型名写进这个服务。换服务时选项要直接来自新服务的
``service_model_catalog``，而且不联网。
"""
from __future__ import annotations

import copy
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

SWITCHED = ("claude", "xai", "deepseek", "gemini", "openai", "antigravity", "grok_account", "custom", "bailian")


@pytest.fixture()
def editor_factory(monkeypatch):
    """Editors without stored keys, model discovery or connection workers."""
    app = QApplication.instance() or QApplication([])
    from twobyteasr import ui as endpoint_editor_ui  # flat daily: EndpointEditor still lives in ui.py

    for module in ("twobyteasr.ui",):
        monkeypatch.setattr(f"{module}.resolve_api_key", lambda stage: ("", "未配置"))
        monkeypatch.setattr(f"{module}.read_api_key", lambda _provider, _base_url="": ("", "未配置"))
    monkeypatch.setattr("twobyteasr.llm_config.read_api_key",
                        lambda _provider, _base_url="": ("", "未配置"))

    def no_network(*_args, **_kwargs):
        raise AssertionError("switching services must not start model discovery")

    monkeypatch.setattr(endpoint_editor_ui, "ProviderModelDiscoveryWorker", no_network)
    created = []

    def make(settings, stage="group"):
        editor = endpoint_editor_ui.EndpointEditor("全文断句模型", "#2f8fef", stage, settings)
        created.append(editor)
        return editor

    yield make
    for editor in created:
        editor.deleteLater()
    app.processEvents()


def _settings(service="bailian", profiles=None):
    import subtitle_core as legacy

    settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    models = settings.setdefault("models", {})
    models["ai_service"] = service
    models["provider_profiles"] = copy.deepcopy(profiles or {})
    for prefix in ("polish", "group"):
        models[f"{prefix}_model"] = ""
        models[f"{prefix}_base_url"] = ""
    return settings


def _items(combo):
    return [combo.itemText(index) for index in range(combo.count())]


def _popup_items(combo):
    """What opening the dropdown shows: the project popup rebuilds from the combo."""
    combo._popup.rebuild()
    listing = combo._popup.listing
    return [listing.item(row).text() for row in range(listing.count())]


def _choose(editor, service_id):
    index = editor.service.findData(service_id)
    assert index >= 0, service_id
    editor.service.setCurrentIndex(index)


def test_switching_service_lists_only_the_new_service_catalog(editor_factory):
    from twobyteasr.llm_config import resolved_service_values, service_model_catalog

    settings = _settings("bailian")
    editor = editor_factory(settings)
    assert editor.service.currentData() == "bailian"
    assert _items(editor.model) == list(service_model_catalog(settings, "bailian"))

    for service_id in SWITCHED:
        _choose(editor, service_id)
        expected = list(service_model_catalog(settings, service_id))
        chosen = resolved_service_values(settings, service_id)["model"]
        assert _items(editor.model) == expected, service_id
        assert _popup_items(editor.model) == expected, service_id
        assert editor.model.currentText() == chosen, service_id
        if service_id != "bailian":
            assert not any(item.startswith("qwen") for item in _items(editor.model)), service_id
    assert not editor._model_discovery_timer.isActive()


def test_switching_to_claude_shows_the_three_claude_models(editor_factory):
    settings = _settings("bailian")
    editor = editor_factory(settings)
    _choose(editor, "claude")
    assert _popup_items(editor.model) == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
    assert editor.model.currentText() == "claude-opus-5-5"
    assert editor.values()["model"] == "claude-opus-5-5"


def test_saved_custom_model_stays_selectable_after_switching_back(editor_factory):
    profiles = {"xai": {"base_url": "https://api.x.ai/v1", "model": "grok-4.7-preview-local", "protocol": "auto"}}
    settings = _settings("bailian", profiles)
    editor = editor_factory(settings)
    _choose(editor, "xai")
    items = _items(editor.model)
    assert items[0] == "grok-4.7-preview-local"
    assert {"grok-4.7", "grok-4.3"} <= set(items)
    assert editor.model.currentText() == "grok-4.7-preview-local"
    _choose(editor, "claude")
    assert "grok-4.7-preview-local" not in _items(editor.model)
    _choose(editor, "xai")
    assert editor.model.currentText() == "grok-4.7-preview-local"


def test_cli_service_without_default_model_shows_placeholder(editor_factory):
    settings = _settings("bailian")
    editor = editor_factory(settings)
    _choose(editor, "grok_account")
    assert _items(editor.model) == []
    assert editor.model.currentText() == ""
    _choose(editor, "antigravity")
    assert _items(editor.model) == ["gemini-3.8-flash-high", "gemini-3.7-flash-high"]
    assert editor.model.currentText() == ""  # empty = the CLI's own default model


def test_switching_does_not_offer_a_retired_model(editor_factory):
    profiles = {"deepseek": {"base_url": "https://api.deepseek.com/v1",
                             "model": "deepseek-v4-flash-vision-exp", "protocol": "auto"}}
    settings = _settings("bailian", profiles)
    editor = editor_factory(settings)
    _choose(editor, "deepseek")
    assert editor.model.findText("deepseek-v4-flash-vision-exp") < 0
    assert editor.model.currentText() == "deepseek-v4-flash"
    assert not editor.model_warning.isHidden()
    assert "deepseek-v4-flash-vision-exp" in editor.model_warning.text()


def test_profile_restore_replaces_the_list_without_signals(editor_factory):
    from twobyteasr.llm_config import service_model_catalog

    settings = _settings("bailian")
    editor = editor_factory(settings)
    changes = []
    editor.model.currentTextChanged.connect(changes.append)
    values = dict(editor.values(), service="claude", transport="openai_compatible", provider="anthropic",
                  model="claude-sonnet-5-5", base_url="https://api.anthropic.com/v1")
    editor.restore_profile_values(values, settings)
    assert _items(editor.model) == list(service_model_catalog(settings, "claude"))
    assert editor.model.currentText() == "claude-sonnet-5-5"
    assert changes == []
    # The signal block ends with the restore: later picks reach the editor again.
    editor.model.setCurrentText("claude-haiku-5-5")
    assert changes == ["claude-haiku-5-5"]
