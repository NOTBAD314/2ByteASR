"""A timestamp role only accepts local, executable timing models."""
import os
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from twobyteasr.local_models import model_workshop as workshop

APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parents[1]
BY_KEY = {model.key: model for model in workshop.MODELS}


@pytest.fixture(params=[False, True], ids=["sync", "deferred-async"])
def page(request, monkeypatch):
    from twobyteasr.local_models.model_registry import ModelRegistry
    from twobyteasr.providers import llm_config

    monkeypatch.setattr(ModelRegistry, "installed_keys", lambda self: {"firered_aed", "qwen_aligner"})
    monkeypatch.setattr(workshop, "_readiness_status", lambda key: "PASS")
    monkeypatch.setattr(llm_config, "read_asr_api_key", lambda *args: ("fixture", "test"))
    settings = {"models": {"primary_asr_backend": "api", "firered_asr_backend": "off",
                           "qwen_asr_backend": "api", "qwen_asr_api_provider": "mosi_moss_pro"}}
    controller = workshop.ModelWorkshopPage(ROOT, settings, defer_ui=request.param)
    yield controller
    for _ in range(100):
        if not controller.background_busy():
            break
        QTest.qWait(10)
    controller.close()
    controller.deleteLater()
    APP.processEvents()


def test_cloud_timestamp_capability_does_not_advertise_timeline_role():
    cloud = [model for model in workshop.MODELS if model.api_preset and "TIMESTAMP" in model.asr_capabilities]
    assert cloud  # Includes the reported MOSS Pro and Qwen Audio models.
    for model in cloud:
        assert "timeline" not in workshop._model_roles(model), model.key
        assert "primary" in workshop._model_roles(model), model.key
        assert "TIMESTAMP" in model.asr_capabilities  # Catalog evidence remains true.


def test_local_timing_requires_execution_support_and_preserves_ctc_helper(monkeypatch):
    aligner = BY_KEY["qwen_aligner"]
    for model in (replace(aligner, adapter_bindings=()),
                  replace(aligner, runtime_available=False),
                  replace(aligner, asr_capabilities=("ASR_TEXT",)),
                  replace(aligner, api_preset="future_cloud")):
        assert "timeline" not in workshop._model_roles(model)
    assert "timeline" in workshop._model_roles(aligner)
    assert "timeline" in workshop._model_roles(BY_KEY["ja_ctc_aligner"])


def test_timestamp_picker_excludes_cloud_but_primary_and_catalog_keep_it(page):
    timeline = workshop.ModelPickerPanel(page, "timeline")
    primary = workshop.ModelPickerPanel(page, "primary")
    try:
        assert "cloud" not in timeline.filter_buttons
        assert "本地" in timeline.scope_note.text()
        assert {"qwen_aligner", "firered", "whisper", "paraformer", "ja_ctc_aligner"} <= timeline.cards.keys()
        assert all(not card.model.api_preset for card in timeline.cards.values())
        assert all({"TIMESTAMP", "ALIGNMENT"} & set(card.model.asr_capabilities)
                   for card in timeline.cards.values())
        assert "mosi_moss_pro" in primary.cards
        assert "qwen_cloud_filetrans" in primary.cards
        assert workshop._browser_groups(BY_KEY["mosi_moss_pro"]) == ("primary", "api")
    finally:
        timeline.deleteLater()
        primary.deleteLater()


@pytest.mark.parametrize("entry", ["_select_model", "_perform_action", "_request_model_selection"])
def test_cloud_selection_is_rejected_with_feedback_and_previous_choice_preserved(page, monkeypatch, entry):
    requested, configured, messages = [], [], []
    page.backend_requested.connect(lambda *args: requested.append(args))
    page.api_preset_requested.connect(configured.append)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    before = dict(page.runtime_settings["models"])
    model = BY_KEY["mosi_moss_pro"]
    if entry == "_request_model_selection":
        getattr(page, entry)(model, "configured", role="timeline")
    else:
        getattr(page, entry)(model.key, role="timeline")
    assert not requested and not configured
    assert page.runtime_settings["models"] == before
    assert messages and "本地" in messages[-1]
    assert page._model_state(model, "timeline") == "unsupported_role"
    assert page._action_text(model, "unsupported_role")[1] is False


def test_even_a_cloud_timeline_binding_cannot_enable_cloud_selection(page):
    cloud = replace(BY_KEY["mosi_moss_pro"], adapter_bindings=(("timeline", "api"),))
    assert page._selection_target(cloud, "timeline") is None


def test_local_choice_updates_picker_and_cancels_without_changing_cloud_role(page):
    def apply(role, backend):
        assert role == "firered"
        page.runtime_settings["models"]["firered_asr_backend"] = backend

    page.backend_requested.connect(apply)
    # Wait for the real registry worker to deliver its state in the deferred path.
    for _ in range(100):
        if page._model_state(BY_KEY["qwen_aligner"], "timeline") == "installed":
            break
        QTest.qWait(10)
    timeline = workshop.ModelPickerPanel(page, "timeline")
    try:
        timeline.show()
        QTest.qWait(100)
        card = timeline.cards["qwen_aligner"]
        QTest.mouseClick(card.action, Qt.MouseButton.LeftButton)
        assert page.runtime_settings["models"]["firered_asr_backend"] == "qwen_aligner"
        assert card.property("selected")
        assert "Qwen3" in timeline.current_badge.text()
        QTest.mouseClick(card.action, Qt.MouseButton.LeftButton)
        assert page.runtime_settings["models"]["firered_asr_backend"] == "off"
        assert not card.property("selected")
        assert page.runtime_settings["models"]["primary_asr_backend"] == "api"
    finally:
        timeline.close()
        timeline.deleteLater()
