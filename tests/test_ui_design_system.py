"""Regression checks for the shared warm desktop design system."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget  # noqa: E402

from twobyteasr import ui_theme  # noqa: E402
from twobyteasr.model_workshop import (  # noqa: E402
    ModelPickerPanel,
    ModelWorkshopPage,
    WORKSHOP_TOKENS,
)
from twobyteasr.ui import APP_QSS, MainWindow  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def _app():
    return QApplication.instance() or QApplication([])


def test_shared_palette_drives_workshop_and_has_no_button_gradients():
    assert WORKSHOP_TOKENS["green"] == ui_theme.GREEN
    assert WORKSHOP_TOKENS["page"] == ui_theme.BACKGROUND
    assert WORKSHOP_TOKENS["border"] == ui_theme.BORDER
    assert "qlineargradient" not in APP_QSS
    assert "qradialgradient" not in APP_QSS


def test_main_shell_fits_compact_desktop_density():
    _app()
    import subtitle_core as legacy

    win = MainWindow([], legacy, object(), None)
    win.resize(1366, 768)
    win.show()
    QApplication.processEvents()
    assert win.settings_surface.height() >= win.settings_surface.minimumHeight()
    assert all(card.minimumHeight() == 228 for card in win.recognition_plan.cards.values())
    assert all(card.height() >= 228 for card in win.recognition_plan.cards.values())
    assert all(tile.minimumHeight() == 88 for tile in win.setting_tiles.values())
    assert win.bottom_bar.isVisible()
    win.close()


def test_workshop_wide_density_uses_reference_proportions():
    _app()
    page = ModelWorkshopPage(ROOT, {"models": {}})
    page.resize(1440,900);page.show();_app().processEvents()
    widths=(page.sidebar.width(),page.detail.width())
    page.apply_density(True);_app().processEvents()
    assert (page.sidebar.width(),page.detail.width()) == widths
    assert all(card.minimumHeight() == 176 for card in page._cards.values())
    # 2026-10-12: the sidebar is the column shared with Recognition History and
    # Term Library (one fixed width, zoom-scaled); the list and detail flex.
    from twobyteasr.ui_navigation import SIDEBAR_WIDTH
    from twobyteasr.ui_zoom import px
    assert page.sidebar.minimumWidth() == page.sidebar.maximumWidth() == px(SIDEBAR_WIDTH)
    assert page.detail.minimumWidth() < page.detail.maximumWidth()
    page.deleteLater()


def test_model_scroll_surfaces_do_not_override_card_and_pill_qss():
    _app()
    page = ModelWorkshopPage(ROOT, {"models": {}})
    picker = ModelPickerPanel(page, "primary")

    for surface in (page, picker):
        scroll = surface.findChild(QScrollArea, "workshopScroll")
        host = surface.findChild(QWidget, "workshopScrollHost")
        assert scroll is not None
        assert host is not None
        assert scroll.viewport().styleSheet() == ""
        assert host.styleSheet() == ""

    assert all(card.styleSheet() == "" for card in page._cards.values())
    assert all(card.styleSheet() == "" for card in picker.cards.values())
    assert picker.current_badge.text()
    assert all(card.state_badge.text() for card in picker.cards.values())
    assert all(card.action.text() for card in picker.cards.values())
    assert all(card.minimumHeight() >= 140 for card in picker.cards.values())
    picker.deleteLater()
    page.deleteLater()
