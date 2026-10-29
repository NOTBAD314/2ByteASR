"""Export fields must fit on first open and keep geometry on theme refresh."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from twobyteasr.exports import studio_export_ui
    from twobyteasr.design import theme_manager
    app = QApplication.instance() or QApplication([])
    ini = lambda *a: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(studio_export_ui, "QSettings", ini)
    monkeypatch.setattr(theme_manager, "_settings", ini)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    from twobyteasr.design.typography import application_font
    app.setFont(application_font())
    theme_manager.apply_theme("warm", app)
    project = SubtitleProject(media=StudioMedia(path=str(tmp_path / "video.mp4"), duration_ms=8000))
    window = studio_export_ui.StudioExportWorkspace(project, str(tmp_path / "preview.ass"))
    window.show()
    yield app, window
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("size", [(1024, 700), (1280, 800)])
def test_export_fields_fit_and_stay_stable_on_retheme(workspace, size):
    app, window = workspace
    window.resize(*size)
    window.subtitle_destination_modes["custom"].setChecked(True)
    window.advanced_button.setChecked(True)
    window.expert_button.setChecked(True)
    app.processEvents()
    assert window.settings_scroll.horizontalScrollBar().maximum() == 0
    for button in (window.queue_button, window.export_button):
        rect = button.rect().translated(button.mapTo(window, QPoint()))
        assert window.rect().contains(rect)
        assert not window.preview_scroll.isAncestorOf(button)
    assert window.preview_scroll.horizontalScrollBar().maximum() == 0
    assert window.quality_value.width() <= 144
    assert window.extension.width() <= 240
    assert window.directory.property("fieldWidth") == "expanding"
    fields = (window.filename, window.directory, window.extension, window.quality_value, window.encoder)
    sizes = [(w.width(), w.height()) for w in fields]
    window.refresh_theme_palette()
    app.processEvents()
    assert [(w.width(), w.height()) for w in fields] == sizes
    assert window.settings_scroll.horizontalScrollBar().maximum() == 0
    from twobyteasr.design.theme_manager import apply_theme
    from twobyteasr.design.ui_theme import THEMES
    for key, theme in THEMES.items():
        apply_theme(key, app)
        window.refresh_theme_palette()
        app.processEvents()
        assert window.export_button.palette().color(QPalette.ColorRole.ButtonText) == QColor(theme.text_on_accent)
        assert window.settings_scroll.horizontalScrollBar().maximum() == 0
    # All preset commands remain reachable after compacting the crowded row.
    assert [a.text() for a in window.preset_menu_button.menu().actions() if not a.isSeparator()] == [
        "保存预设", "另存为…", "删除自定义预设",
    ]
