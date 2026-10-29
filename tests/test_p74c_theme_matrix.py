"""P7.4C theme matrix: overlays, popovers, sheets, and message boxes follow
the active theme in every supported theme instead of hard-coded warm cream."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from twobyteasr.design.main_ui_theme import APP_QSS
from twobyteasr.design.qss_retheme import retheme_qss
from twobyteasr.design.ui_theme import THEMES, theme_definition


def _app():
    return QApplication.instance() or QApplication([])


def test_p74c_drag_overlay_uses_theme_scrim_in_all_themes(monkeypatch):
    _app()
    from twobyteasr.app import home_widgets
    from twobyteasr.app.ui import DropOverlay

    for key in THEMES:
        theme = theme_definition(key)
        monkeypatch.setattr(home_widgets, "theme_key", lambda: key)
        overlay = DropOverlay()
        assert theme.overlay_scrim in overlay.styleSheet(), key
        overlay.deleteLater()


def test_p74c_help_popover_qss_follows_theme_tokens():
    from twobyteasr.app.ui import api_help_popover_qss

    for key in THEMES:
        theme = theme_definition(key)
        qss = api_help_popover_qss(theme)
        assert theme.surface in qss, key
        assert theme.accent in qss, key
        if key != "warm":
            # Non-warm themes must not leak the warm cream literals.
            assert "#fffefa" not in qss and "#d9d0bf" not in qss, key


def test_p74c_app_qss_message_box_and_endpoint_follow_theme():
    assert "rgba(255, 253, 248" not in APP_QSS
    for key in THEMES:
        theme = theme_definition(key)
        qss = retheme_qss(APP_QSS, theme)
        # The QMessageBox surface rides the mapped app-background token.
        assert theme.app_background in qss, key


def test_p74c_glossary_sheets_use_theme_tokens():
    from twobyteasr.glossary import main_ui_glossary as glossary

    source = Path(glossary.__file__).read_text(encoding="utf-8")
    assert "rgba(47,44,38,90)" not in source
    assert source.count("_sheet_theme()") >= 6
