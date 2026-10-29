"""Action and display boundaries; no provider, download, GPU or user profile."""
from __future__ import annotations

import copy
import os
from dataclasses import replace
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QPushButton

import twobyteasr.local_models.model_workshop as workshop
from twobyteasr.runtime_paths import reset_runtime_paths

ROOT = Path(os.environ.get("WORKSHOP_SOURCE_ROOT", str(Path(__file__).resolve().parents[1])))


@pytest.fixture
def page(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(tmp_path))
    monkeypatch.setenv("2BYTEASR_USER_DATA_ROOT", str(tmp_path / "local"))
    monkeypatch.setenv("2BYTEASR_MODEL_ROOT", str(tmp_path / "models"))
    from twobyteasr.test_isolation import install
    install()
    from PySide6 import QtCore
    monkeypatch.setattr(workshop, "QSettings", QtCore.QSettings)
    reset_runtime_paths()
    states = {"vibevoice_1_5b": "installed", "vibevoice_7b": "missing", "diarizen": "installed"}
    monkeypatch.setattr("twobyteasr.recognition.optional_models.readiness", lambda key: states[key])
    monkeypatch.setattr(workshop, "_optional_weights_complete", lambda key, root: states[key] not in {"missing", "partial"})
    model_settings = {"primary_asr_backend": "moss", "firered_asr_backend": "local",
                      "qwen_asr_backend": "local", "speaker_source": "native"}
    view = workshop.ModelWorkshopPage(ROOT, {"models": model_settings})
    view._test_states = states
    yield view
    view.close()
    view.deleteLater()
    app.processEvents()
    reset_runtime_paths()


def _capture_action(monkeypatch, variant, action):
    def execute(dialog):
        dialog.choices[variant].setChecked(True)
        if action is None:
            dialog.reject()
            return QDialog.Rejected
        dialog._accept_action(action)
        return dialog.result()
    monkeypatch.setattr(workshop.ModelVersionDialog, "exec", execute)


@pytest.mark.parametrize("key", ["vibevoice", "diarizen"])
def test_optional_cards_share_action_column_without_persistent_controls(page, key):
    card = page._cards[key]
    reference = page._cards["moss"]
    assert card._row.indexOf(card.action_host) == reference._row.indexOf(reference.action_host)
    assert card._root.indexOf(card.action_host) == -1
    assert card._root.count() == reference._root.count()
    assert card.findChild(QComboBox, "workshopVersionSelector") is None
    assert not hasattr(card, "license_button")
    assert card.metrics_host.isHidden()
    for compact in (True, False):
        card._apply_compact_layout(compact)
        reference._apply_compact_layout(compact)
        assert card.action_host.minimumWidth() == reference.action_host.minimumWidth()
        assert card.action_host.maximumWidth() == reference.action_host.maximumWidth()


@pytest.mark.parametrize("key", ["vibevoice", "diarizen"])
def test_browsing_optional_card_does_not_select_verify_or_grant_consent(page, monkeypatch, key):
    requested = []
    page.backend_requested.connect(lambda *values: requested.append(values))
    monkeypatch.setattr("twobyteasr.recognition.optional_models.confirm_license", lambda *args: pytest.fail("browse requested consent"))
    monkeypatch.setattr(page, "_verify_optional_model", lambda *args: pytest.fail("browse requested verification"))
    before = copy.deepcopy(page.runtime_settings)
    page._select_model(key)
    assert requested == []
    assert page.runtime_settings == before
    assert page.detail_model_key == key


@pytest.mark.parametrize("intent", ["download", "use"])
def test_variant_cancel_preserves_current_model_browse_and_settings(page, monkeypatch, intent):
    stored = workshop.QSettings("2ByteASR", "ModelWorkshop")
    stored.setValue("vibevoice_view_version", "vibevoice_1_5b")
    before = copy.deepcopy(page.runtime_settings)
    requested = []
    page.backend_requested.connect(lambda *values: requested.append(values))
    _capture_action(monkeypatch, "vibevoice_7b", None)
    page._choose_variant_action(page._cards["vibevoice"].model, intent=intent)
    assert page.runtime_settings == before
    assert page._cards["vibevoice"].model.download_key == "vibevoice_1_5b"
    assert stored.value("vibevoice_view_version") == "vibevoice_1_5b"
    assert requested == []


def test_download_only_prepares_explicit_version_and_does_not_select(page, monkeypatch):
    downloaded = []
    requested = []
    before = copy.deepcopy(page.runtime_settings)
    page.backend_requested.connect(lambda *values: requested.append(values))
    monkeypatch.setattr(page, "download_combination", lambda keys, name: downloaded.append(tuple(keys)))
    _capture_action(monkeypatch, "vibevoice_7b", "download")
    page._download(page._cards["vibevoice"].model)
    assert downloaded == [("vibevoice_7b",)]
    assert requested == []
    assert page.runtime_settings == before
    assert page._cards["vibevoice"].model.download_key == "vibevoice_7b"


def test_missing_use_requires_explicit_download_and_installed_download_is_disabled(page):
    dialog = workshop.ModelVersionDialog(page, intent="use")
    assert not dialog.download.isEnabled()
    assert dialog.use.isEnabled()
    dialog.choices["vibevoice_7b"].setChecked(True)
    assert dialog.download.isEnabled()
    assert not dialog.use.isEnabled()
    assert "先下载" in dialog.action_note.text()
    dialog._accept_action("use")
    assert dialog.requested_action is None
    dialog.reject()
    dialog.deleteLater()


def test_use_emits_exact_ready_version_without_touching_other_backends(page, monkeypatch):
    page._test_states["vibevoice_7b"] = "installed"
    requested = []
    page.backend_requested.connect(lambda *values: requested.append(values))
    before = copy.deepcopy(page.runtime_settings)
    _capture_action(monkeypatch, "vibevoice_7b", "use")
    page._perform_action("vibevoice")
    assert requested == [("primary", "vibevoice_7b")]
    assert page.runtime_settings == before


def test_using_current_version_never_disables_it(page, monkeypatch):
    page.runtime_settings["models"]["primary_asr_backend"] = "vibevoice_1_5b"
    requested = []
    page.backend_requested.connect(lambda *values: requested.append(values))
    _capture_action(monkeypatch, "vibevoice_1_5b", "use")
    page._perform_action("vibevoice")
    assert requested == []
    assert page.runtime_settings["models"]["primary_asr_backend"] == "vibevoice_1_5b"


@pytest.mark.parametrize("state", ["inference_pending", "load_failed", "runtime_missing"])
def test_unverified_versions_cannot_be_selected_or_implicitly_retried(page, state):
    page._test_states["vibevoice_7b"] = state
    before = copy.deepcopy(page.runtime_settings)
    dialog = workshop.ModelVersionDialog(page, intent="use")
    dialog.choices["vibevoice_7b"].setChecked(True)
    assert not dialog.download.isEnabled()
    assert dialog.use.property("action") == ("runtime" if state == "runtime_missing" else "verify")
    assert dialog.requested_action is None
    assert page.runtime_settings == before
    dialog.reject()
    dialog.deleteLater()


def test_variants_are_independent_for_uninstall_and_picker_current_display(page):
    page.runtime_settings["models"]["primary_asr_backend"] = "vibevoice_1_5b"
    page._test_states["vibevoice_7b"] = "installed"
    page._view_variant("vibevoice", "vibevoice_7b")
    assert not page._model_is_current(page._cards["vibevoice"].model)
    assert page._model_is_current(replace(page._cards["vibevoice"].model, download_key="vibevoice_1_5b"))
    picker = workshop.ModelPickerPanel(page, "primary")
    assert "1.5B" in picker.current_badge.text()
    assert "7B" not in picker.current_badge.text()
    assert picker.findChild(QComboBox, "workshopVersionSelector") is None
    picker.close()
    picker.deleteLater()


def test_diarizen_explicit_use_preserves_first_consent_path(page, monkeypatch):
    consents = []
    requested = []
    monkeypatch.setattr("twobyteasr.recognition.optional_models.confirm_license", lambda *args: consents.append(args) or True)
    page.backend_requested.connect(lambda *values: requested.append(values))
    page._perform_action("diarizen")
    assert len(consents) == 1
    assert requested == [("speaker", "diarizen")]


@pytest.mark.parametrize("key", ["vibevoice", "diarizen"])
def test_technical_page_maps_optional_identity_skips_empty_sections_and_keeps_license(page, key):
    technical = workshop.ModelTechnicalDialog(page._cards[key].model)
    values = [label.text() for label in technical.findChildren(QLabel, "techInfoValue")]
    assert all(value.strip() and value != "—" for value in values)
    if key == "diarizen":
        assert "说话人" in values[-1]
        assert "ASR" not in values[-1]
    headings = [label.text() for label in technical.findChildren(QLabel, "technicalDetailsHeading")]
    assert "核心能力" in headings
    assert "官方 Benchmark" not in headings
    assert "Benchmark 测试条件" not in headings
    assert "2ByteASR 参考评分及推导" not in headings
    assert len(headings) == len(set(headings))
    assert all(label.text().strip() for label in technical.findChildren(QLabel, "technicalDetailsBody"))
    body = "\n".join(label.text() for label in technical.findChildren(QLabel, "technicalDetailsBody"))
    assert "许可" in body or "MIT" in body or "CC-BY-NC-4.0" in body
    assert any("原文" in button.text() or "许可" in button.text() for button in technical.findChildren(QPushButton))
    technical.close()
    technical.deleteLater()
