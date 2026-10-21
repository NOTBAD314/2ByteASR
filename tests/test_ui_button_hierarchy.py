"""Exercise effective Qt cascade, including legacy IDs and local Studio sheets."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QToolButton, QWidget

from twobyteasr.design.presentation import button_role
from twobyteasr.design.theme_manager import apply_theme
from twobyteasr.design.ui_theme import THEMES


@pytest.fixture
def app(tmp_path, monkeypatch):
    instance = QApplication.instance() or QApplication([])
    from twobyteasr.design import theme_manager
    monkeypatch.setattr(theme_manager, "_settings", lambda: QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat))
    return instance


def test_explicit_size_survives_legacy_id_and_theme_switch(app):
    root = QWidget()
    row = QHBoxLayout(root)
    primary = button_role(QPushButton("开始生成字幕"), "primary", size="large")
    primary.setObjectName("primary")
    secondary = button_role(QPushButton("字幕工作台"), "secondary")
    secondary.setObjectName("studioFooterButton")
    tool = button_role(QToolButton(), "toolbar", size="compact")
    tool.setText("工具")
    tool.setObjectName("studioTool")
    for button in (primary, secondary, tool):
        row.addWidget(button)
    root.show()
    try:
        for key in THEMES:
            apply_theme(key, app)
            app.processEvents()
            assert primary.font().pixelSize() >= 15, key
            # 2026-10-07 weight rule: primary is the single 600 emphasis.
            assert primary.font().weight() >= 600, key
            assert primary.height() >= 48, key
            assert primary.height() > secondary.height() > tool.height(), key
            assert tool.height() <= 32, key
    finally:
        root.close()


def test_project_action_foreground_matches_icon_in_local_studio_sheet(app):
    from twobyteasr.design.studio_theme import build_studio_qss
    from twobyteasr.design.themed_icons import icon_role_color
    root = QWidget()
    row = QHBoxLayout(root)
    button = button_role(QPushButton("打开工程"), "primary")
    button.setObjectName("projectCardOpen")
    button.setCheckable(True)
    row.addWidget(button)
    root.show()
    try:
        for theme in THEMES.values():
            root.setStyleSheet(build_studio_qss(theme))
            for checked in (False, True):
                button.setChecked(checked)
                app.processEvents()
                expected = QColor(icon_role_color("on_accent", theme))
                assert button.palette().color(QPalette.ColorRole.ButtonText) == expected, (theme.key, checked)
    finally:
        root.close()
