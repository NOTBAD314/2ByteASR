"""Focused regressions for the P10 GUI performance shortcuts."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QSize
from PySide6.QtWidgets import QApplication, QPushButton, QStackedWidget, QWidget

import twobyteasr.app.ui as ui
from twobyteasr.local_models.model_workshop import MODELS, ModelCard, ModelWorkshopPage


ROOT = Path(__file__).resolve().parents[1]


def _app():
    return QApplication.instance() or QApplication([])


class _SizeProbe(QWidget):
    def __init__(self):
        super().__init__()
        self.adjust_calls = 0
        self.hint_calls = 0

    def adjustSize(self):
        self.adjust_calls += 1
        return super().adjustSize()

    def sizeHint(self):
        self.hint_calls += 1
        return QSize(640, 480)


class _DynamicPropertyCounter(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, _obj, event):
        if event.type() == QEvent.Type.DynamicPropertyChange:
            self.count += 1
        return False


def test_explicit_modal_size_skips_hint_walk_and_retained_content_stays_parented():
    app = _app()
    parent = QWidget()
    parent.resize(1280, 800)
    host = ui.ModalHost(parent)
    host.resize_to_parent()
    probe = _SizeProbe()

    host.show_content(probe, size=(760, 560), retain_content=True)
    assert probe.adjust_calls == 0
    explicit_hint_calls = probe.hint_calls
    app.processEvents()

    host.hide_content()
    assert probe.parentWidget() is host.body
    assert probe.isHidden()

    fallback_probe = _SizeProbe()
    host.show_content(fallback_probe)
    assert fallback_probe.adjust_calls == 1
    assert fallback_probe.hint_calls > explicit_hint_calls
    host.hide_content()
    assert fallback_probe.parentWidget() is None

    parent.close()
    app.processEvents()


def test_technical_dialog_cache_reuses_the_same_widget_tree(monkeypatch):
    app = _app()
    language = {"value": "zh"}
    monkeypatch.setattr(ui, "current_language", lambda: language["value"])
    monkeypatch.setattr(
        "twobyteasr.local_models.model_workshop.current_language",
        lambda: language["value"],
    )
    parent = QWidget()
    parent.resize(1280, 800)
    parent._modal_host = ui.ModalHost(parent)
    parent._modal_host.resize_to_parent()
    page = ModelWorkshopPage(ROOT, {"models": {}}, parent)
    page.detail_model_key = "moss"

    page._show_technical_details()
    cache_key = ("moss", "primary")
    first = page._technical_cache[cache_key]
    assert first._rendered_language == "zh"
    parent._modal_host.hide_content()
    language["value"] = "en"
    page._show_technical_details()
    second = page._technical_cache[cache_key]

    assert second is first
    assert second._rendered_language == "en"
    assert second.parentWidget() is parent._modal_host.body
    assert len(page._technical_cache) == 1

    parent._modal_host.hide_content()
    page.deleteLater()
    parent.close()
    app.processEvents()


def test_unchanged_model_card_state_does_not_emit_property_changes():
    app = _app()
    model = next(item for item in MODELS if item.key == "moss")
    card = ModelCard(model)
    counter = _DynamicPropertyCounter()
    for widget in (card, card.monogram, card.state_badge):
        widget.installEventFilter(counter)

    card.set_selected(True)
    card.set_state_badge("已安装", "ready")
    app.processEvents()
    first_count = counter.count

    card.set_selected(True)
    card.set_state_badge("已安装", "ready")
    app.processEvents()
    assert counter.count == first_count

    card.deleteLater()
    app.processEvents()


def test_page_language_walk_runs_once_per_page_and_language(monkeypatch):
    _app()
    pages = QStackedWidget()
    workshop = QWidget()
    terms = QWidget()
    history = QWidget()
    for page in (workshop, terms, history):
        pages.addWidget(page)
    calls = []
    monkeypatch.setattr(ui, "apply_ui_language", lambda page, language: calls.append((page, language)))
    owner = SimpleNamespace(
        app_header=SimpleNamespace(setVisible=lambda _visible: None),
        content_layout=SimpleNamespace(setContentsMargins=lambda *_:None,setSpacing=lambda *_:None),
        studio_page=QWidget(),
        subtitle_studio_button=QPushButton(),
        pages=pages,
        workshop_page=workshop,
        term_library_page=terms,
        history_page=history,
        settings_scroll=QWidget(),
        model_workshop_button=QPushButton(),
        return_recognition_button=QPushButton(),
        _ui_language="zh",
        _update_bottom_bar_visibility=lambda _index: None,
    )

    ui.MainWindow._page_changed(owner, 0)
    ui.MainWindow._page_changed(owner, 0)
    ui.MainWindow._page_changed(owner, 1)
    ui.MainWindow._page_changed(owner, 1)
    assert calls == [(workshop, "zh"), (terms, "zh")]

    owner._ui_language = "en"
    ui.MainWindow._page_changed(owner, 0)
    ui.MainWindow._page_changed(owner, 0)
    assert calls[-1] == (workshop, "en")
    assert calls.count((workshop, "en")) == 1

    pages.deleteLater()
