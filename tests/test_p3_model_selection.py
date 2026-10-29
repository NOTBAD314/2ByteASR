from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.local_models import model_workshop as workshop
from twobyteasr.local_models.model_workshop import ModelPickerPanel, ModelWorkshopPage


ROOT = Path(__file__).resolve().parents[1]


def _app():
    return QApplication.instance() or QApplication([])


def _runtime_settings(primary="moss"):
    return {
        "models": {
            "primary_asr_backend": primary,
            "firered_asr_backend": "off",
            "qwen_asr_backend": "off",
        }
    }


def _wire_backend_updates(page, settings):
    def apply(role, value):
        key = {
            "primary": "primary_asr_backend",
            "firered": "firered_asr_backend",
            "qwen": "qwen_asr_backend",
        }[role]
        settings["models"][key] = value

    page.backend_requested.connect(apply)


def _installed_models(monkeypatch):
    installed = {"moss", "firered_vad", "speaker_embedding", "firered_aed"}
    monkeypatch.setattr(workshop, "installed_model_keys", lambda _root: set(installed))
    monkeypatch.setattr(
        "twobyteasr.system.environment.fast_preflight",
        lambda _stage: SimpleNamespace(ok=True),
    )
    return installed


def test_recommended_card_uses_badge_only_and_selected_state_is_separate(monkeypatch):
    _app()
    _installed_models(monkeypatch)
    page = ModelWorkshopPage(ROOT, _runtime_settings())

    moss = page._cards["moss"]
    firered = page._cards["firered"]
    assert moss.property("recommended") is True
    assert moss.property("selected") is True
    assert firered.property("recommended") is True
    assert firered.property("selected") is False
    assert moss.recommendation_badge.text() == "★ 2ByteASR 推荐"
    assert firered.recommendation_badge.text() == "★ 2ByteASR 推荐"
    assert 'QFrame#workshopModelCard[recommended="true"] {' not in page.styleSheet()
    assert 'QFrame#workshopModelCard[selected="true"] {' in page.styleSheet()
    assert 'border: 2px solid #64875b;' in page.styleSheet()
    page.deleteLater()


def test_clicking_selected_model_turns_role_off_without_uninstalling(monkeypatch):
    _app()
    installed = _installed_models(monkeypatch)
    settings = _runtime_settings()
    page = ModelWorkshopPage(ROOT, settings)
    _wire_backend_updates(page, settings)

    requested = []
    page.backend_requested.connect(lambda role, value: requested.append((role, value)))
    page._select_model("moss")

    assert requested[-1] == ("primary", "none")
    assert settings["models"]["primary_asr_backend"] == "none"
    assert page._cards["moss"].property("selected") is False
    assert installed <= page._installed
    page.deleteLater()


def test_clicking_installed_model_switches_runtime_and_picker_stays_in_sync(monkeypatch):
    _app()
    _installed_models(monkeypatch)
    settings = _runtime_settings()
    page = ModelWorkshopPage(ROOT, settings)
    _wire_backend_updates(page, settings)
    picker = ModelPickerPanel(page, "primary")

    picker._select("firered")

    assert settings["models"]["primary_asr_backend"] == "firered"
    assert page._cards["moss"].property("selected") is False
    assert page._cards["firered"].property("selected") is True
    assert picker.cards["moss"].property("selected") is False
    assert picker.cards["firered"].property("selected") is True
    assert picker.current_badge.text().endswith("FireRedASR2-AED")
    picker.deleteLater()
    page.deleteLater()


def test_workshop_browser_role_survives_fifty_role_model_updates(monkeypatch):
    app = _app()
    installed = {
        "moss",
        "firered_vad",
        "speaker_embedding",
        "firered_aed",
        "qwen_asr",
        "sensevoice",
    }
    monkeypatch.setattr(
        workshop,
        "installed_model_keys",
        lambda _root: set(installed),
    )
    monkeypatch.setattr(
        "twobyteasr.system.environment.fast_preflight",
        lambda _stage: SimpleNamespace(ok=True),
    )
    settings = _runtime_settings()
    page = ModelWorkshopPage(ROOT, settings)
    _wire_backend_updates(page, settings)
    pickers = {
        role: ModelPickerPanel(page, role)
        for role in ("primary", "timeline", "review")
    }

    sequence = (
        ("primary", "moss"),
        ("primary", "firered"),
        ("timeline", "firered"),
        ("review", "qwen_local"),
        ("review", "sensevoice"),
    )
    for index in range(50):
        role, key = sequence[index % len(sequence)]
        page._set_role(role)
        page._perform_action(key)
        app.processEvents()

        assert page.browser_role == role
        checked = page.tab_group.checkedButton()
        assert checked is not None
        assert checked.property("role") == role
        for model_key, card in page._cards.items():
            expected = role in workshop._browser_groups(card.model)
            assert card.isHidden() is not expected, (index, role, model_key)

    page._set_role("primary")
    pickers["review"]._select("qwen_local")
    app.processEvents()
    assert page.browser_role == "primary"
    assert page.tab_group.checkedButton().property("role") == "primary"

    for picker in pickers.values():
        picker.deleteLater()
    page.deleteLater()
    app.processEvents()
