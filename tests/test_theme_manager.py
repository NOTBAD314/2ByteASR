"""Application-wide theme engine: tokens, palette, persistence, surfaces.

QSettings is isolated through a temp INI file so the tests never touch the
developer's real registry values.
"""

import re

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

import twobyteasr.design.theme_manager as theme_manager
from twobyteasr.design.main_ui_theme import APP_QSS
from twobyteasr.design.qss_retheme import retheme_qss
from twobyteasr.design.studio_theme import (
    SECONDARY_SURFACE_QSS,
    STUDIO_QSS,
    build_studio_qss,
)
from twobyteasr.design.ui_theme import THEMES, ThemeDefinition, theme_definition

TOKEN_FIELDS = (
    "key label app_background surface surface_elevated panel input_surface "
    "selected timeline media border border_strong text text_secondary "
    "text_muted accent accent_hover accent_pressed accent_soft success "
    "warning warning_soft danger danger_soft shell shell_border focus disabled"
).split()

HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
INTENTIONAL_LITERALS = {"#ffffff", "#f4f5f2"}


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    ini = tmp_path / "2byteasr-settings.ini"
    monkeypatch.setattr(
        theme_manager, "_settings", lambda: QSettings(str(ini), QSettings.Format.IniFormat)
    )
    return ini


def test_theme_tokens_complete_and_valid():
    assert set(THEMES) == {"warm", "plum", "lavender", "slate", "grape", "frost", "obsidian", "midnight",
                           "verdant", "neon", "cinema", "graphite", "sand", "paper", "contrast"}
    for theme in THEMES.values():
        assert isinstance(theme, ThemeDefinition)
        for field in TOKEN_FIELDS:
            value = getattr(theme, field)
            assert isinstance(value, str) and value, (theme.key, field)
        for field in TOKEN_FIELDS[2:]:
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", getattr(theme, field)), (theme.key, field)
        assert QColor(theme.accent).isValid()


def test_retheme_qss_covers_every_theme():
    for key, theme in THEMES.items():
        token_values = {
            value.lower() for value in theme.__dict__.values() if isinstance(value, str)
        } | {theme.text_on_accent.lower(), theme.on_vivid.lower()}  # ink on accent / status fills
        for name, qss in (("studio", STUDIO_QSS), ("secondary", SECONDARY_SURFACE_QSS), ("app", APP_QSS)):
            remapped = retheme_qss(qss, theme)
            leftovers = {
                hexvalue
                for hexvalue in HEX_RE.findall(remapped)
                if hexvalue.lower() not in token_values
                and hexvalue.lower() not in INTENTIONAL_LITERALS
            }
            assert not leftovers, (key, name, leftovers)


def test_theme_key_roundtrip_and_fallback(isolated_settings):
    assert theme_manager.theme_key() == "grape"
    assert theme_manager.save_theme_key("plum") == "plum"
    assert theme_manager.theme_key() == "plum"
    assert theme_manager.save_theme_key("bogus") == "grape"
    assert theme_manager.theme_key() == "grape"
    assert theme_definition("nope").key == "grape"
    assert theme_manager.save_theme_key("warm") == "warm"
    assert theme_manager.theme_key() == "warm"


def test_apply_theme_switches_palette_and_stylesheet(isolated_settings, tmp_path, monkeypatch):
    import twobyteasr.studio.studio_ui as studio_ui
    import twobyteasr.projects.studio_project as studio_project

    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text('{"recent_projects": []}', encoding="utf-8")
    monkeypatch.setattr(studio_ui, "studio_settings_path", lambda: settings)
    monkeypatch.setattr(studio_project, "studio_settings_path", lambda: settings)

    page = studio_ui.SubtitleStudioPage()
    try:
        for key in ("warm", "plum", "lavender", "slate"):
            theme = theme_manager.apply_application_theme(app=app, key=key)
            palette_window = app.palette().color(QPalette.ColorRole.Window)
            assert palette_window == QColor(theme.app_background), key
            assert key in page.styleSheet() or theme.app_background in page.styleSheet(), key
            # The full Studio sheet must follow the theme, including the Hub
            # surfaces that used to be hard-coded plum.
            hub_sheet = build_studio_qss(theme)
            assert theme.app_background in hub_sheet
            assert theme.accent in hub_sheet
            assert theme_manager.theme_key() == key
    finally:
        page.close_page()
        theme_manager.apply_application_theme(app=app, key="warm")
