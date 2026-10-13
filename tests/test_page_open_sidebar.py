"""Shared sidebar geometry and cheaper page switches (2026-10-12)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget  # noqa: E402

from twobyteasr import ui_zoom  # noqa: E402
from twobyteasr.ui_navigation import SIDEBAR_WIDTH, WorkspaceNavigation, WorkspaceSidebar  # noqa: E402

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def isolated_model_registry(tmp_path, monkeypatch):
    from twobyteasr.runtime_paths import MODEL_ROOT_ENV, USER_DATA_ENV, reset_runtime_paths
    monkeypatch.setenv("TWOBYTEASR_TEST_ROOT", str(tmp_path))
    monkeypatch.setenv(MODEL_ROOT_ENV, str(tmp_path / "models"))
    monkeypatch.setenv(USER_DATA_ENV, str(tmp_path / "local"))
    reset_runtime_paths()
    yield
    reset_runtime_paths()


def _app():
    return QApplication.instance() or QApplication([])


def _pages(tmp_path):
    from twobyteasr.model_workshop import ModelWorkshopPage
    from twobyteasr.recognition_history import RecognitionHistoryPage
    from twobyteasr.ui import TermLibraryPage

    owner = QWidget()
    workshop = ModelWorkshopPage(ROOT, {"models": {}})
    history = RecognitionHistoryPage(tmp_path / "reports", index_path=tmp_path / "index.json")
    terms = TermLibraryPage(owner)
    terms.setParent(None)  # measured as its own window, like the other two pages
    return owner, {"workshop": workshop, "history": history, "terms": terms}


def _geometry(page):
    nav = page.findChild(WorkspaceNavigation)
    sidebar = nav.parentWidget()
    layout = page.layout()
    content = next(layout.itemAt(index).widget() for index in range(layout.count())
                   if layout.itemAt(index).widget() not in (None, sidebar))
    return {
        "sidebar_x": sidebar.mapTo(page, QPoint(0, 0)).x(), "sidebar_w": sidebar.width(),
        "nav": nav.mapTo(page, QPoint(0, 0)).toTuple(), "nav_w": nav.width(),
        "content_left": content.mapTo(page, QPoint(0, 0)).x(),
        "items": [(button.width(), button.height(), button.font().pixelSize(), button.font().pointSizeF(),
                   button.iconSize().toTuple()) for button in nav.buttons.values()],
    }


@pytest.mark.parametrize("percent", [100, 125])
def test_workshop_history_and_terms_share_identical_sidebar_geometry(tmp_path, monkeypatch, percent):
    app = _app()
    monkeypatch.setitem(ui_zoom._state, "percent", percent)
    monkeypatch.setitem(ui_zoom._state, "touched", percent != 100)
    owner, pages = _pages(tmp_path)
    try:
        geometries = {}
        for name, page in pages.items():
            ui_zoom.apply_to(page)
            page.resize(1500, 900)
            page.show()
            app.processEvents()
            geometries[name] = _geometry(page)
        first = geometries["workshop"]
        assert first["sidebar_w"] == ui_zoom.px(SIDEBAR_WIDTH)
        for name, geometry in geometries.items():
            assert geometry == first, (name, geometry, first)
        assert first["items"][0][1] == ui_zoom.px(42) or percent == 100 and first["items"][0][1] == 42
        # Workshop sections word-wrap inside the fixed column.
        workshop = pages["workshop"]
        workshop.combo_title.setText("一个非常非常长的自定义方案名称 · 自定义方案")
        app.processEvents()
        assert workshop.sidebar.width() == first["sidebar_w"]
    finally:
        for page in pages.values():
            page.close()
            page.deleteLater()
        owner.deleteLater()
        app.processEvents()


def test_nav_style_is_owned_by_the_navigation_not_the_page_sheet():
    app = _app()
    host = QWidget()
    # A page sheet like the workshop's control rules (border + compact height).
    host.setStyleSheet("QPushButton#workspaceNav { border: 3px solid red; min-height: 28px;"
                       " max-height: 28px; padding: 0 4px; font-size: 19px; }")
    layout = QVBoxLayout(host)
    sidebar = WorkspaceSidebar("history", object_name="probeSidebar")
    layout.addWidget(sidebar)
    host.resize(600, 600)
    host.show()
    app.processEvents()
    plain = WorkspaceSidebar("history", object_name="plainSidebar")
    plain.resize(400, 600)
    plain.show()
    app.processEvents()
    try:
        styled = [button.height() for button in sidebar.navigation.buttons.values()]
        reference = [button.height() for button in plain.navigation.buttons.values()]
        assert styled == reference == [42] * 4
        assert sidebar.width() == plain.width() == SIDEBAR_WIDTH
    finally:
        host.close()
        plain.close()
        host.deleteLater()
        plain.deleteLater()


def test_page_switch_zoom_pass_runs_only_for_changes(monkeypatch):
    app = _app()
    monkeypatch.setitem(ui_zoom._state, "percent", 110)
    monkeypatch.setitem(ui_zoom._state, "touched", True)
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(QLabel("a"))
    assert ui_zoom.apply_to_changed(page) > 0
    assert ui_zoom.apply_to_changed(page) == 0
    added = QPushButton("b")
    added.setMinimumWidth(100)
    layout.addWidget(added)
    assert ui_zoom.apply_to_changed(page) > 0
    assert added.minimumWidth() == 110
    monkeypatch.setitem(ui_zoom._state, "percent", 125)
    assert ui_zoom.apply_to_changed(page) > 0
    assert added.minimumWidth() == 125
    page.deleteLater()
    app.processEvents()


def test_language_pass_skips_unchanged_widgets_and_rechecks_changed_text(monkeypatch):
    from twobyteasr import i18n
    from twobyteasr.i18n_widgets import apply
    app = _app()
    monkeypatch.setitem(i18n._TRANSLATIONS["en"], "模型工坊", "Model workshop")
    monkeypatch.setitem(i18n._TRANSLATIONS["en"], "识别记录", "Recognition history")
    root = QWidget()
    layout = QVBoxLayout(root)

    class Counting(QLabel):
        writes = 0

        def setText(self, text):
            Counting.writes += 1
            super().setText(text)
    label = Counting("模型工坊")
    layout.addWidget(label)
    apply(root, "en")
    assert label.text() == "Model workshop"
    writes = Counting.writes
    apply(root, "en")
    assert Counting.writes == writes  # unchanged: skipped
    label.setText("识别记录")  # a producer replaced the text without binding it
    apply(root, "en")
    assert label.text() == "Recognition history"
    apply(root, "zh")
    assert label.text() == "识别记录"
    root.deleteLater()
    app.processEvents()


def test_language_minimum_width_is_not_scaled_twice_by_the_zoom(monkeypatch):
    from twobyteasr.i18n_widgets import apply
    app = _app()
    monkeypatch.setitem(ui_zoom._state, "percent", 110)
    monkeypatch.setitem(ui_zoom._state, "touched", True)
    root = QWidget()
    layout = QVBoxLayout(root)
    button = QPushButton("模型工坊")
    layout.addWidget(button)
    ui_zoom.apply_to(root)
    apply(root, "zh")
    fitted = button.minimumWidth()
    ui_zoom.apply_to(root)
    assert button.minimumWidth() == fitted
    apply(root, "zh")
    ui_zoom.apply_to(root)
    assert button.minimumWidth() == fitted
    root.deleteLater()
    app.processEvents()


def test_settle_layout_walks_only_the_visible_tree(monkeypatch):
    from twobyteasr import ui_motion
    app = _app()
    root = QWidget()
    layout = QVBoxLayout(root)
    shown = QWidget()
    QVBoxLayout(shown).addWidget(QLabel("visible"))
    hidden = QWidget()
    hidden_layout = QVBoxLayout(hidden)
    for _ in range(50):
        hidden_layout.addWidget(QLabel("hidden"))
    layout.addWidget(shown)
    layout.addWidget(hidden)
    hidden.hide()
    root.show()
    app.processEvents()
    visited = []
    original = ui_motion.QCoreApplication.sendPostedEvents
    monkeypatch.setattr(ui_motion.QCoreApplication, "sendPostedEvents",
                        lambda widget, kind: (visited.append(widget), original(widget, kind))[1])
    ui_motion.settle_layout(root)
    assert hidden not in visited and shown in visited and len(visited) < 10
    root.close()
    root.deleteLater()
    app.processEvents()
