"""Real registered face tests: requested weight alone did not detect Heavy body text."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase, QFontInfo
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.design import theme_manager
    monkeypatch.setattr(theme_manager, "_settings", lambda: QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    path = Path(__file__).resolve().parents[1] / "assets/fonts/SourceHanSansSC-Heavy.otf"
    font_ids = [QFontDatabase.addApplicationFont(str(p)) for p in (path, path.with_name('SourceHanSansSC-Medium.otf'))]
    assert all(i >= 0 for i in font_ids)
    from twobyteasr.design.typography import application_font
    app.setFont(application_font())
    yield app
    for font_id in font_ids: QFontDatabase.removeApplicationFont(font_id)


def is_heavy(font):
    info = QFontInfo(font)
    # Qt may report the registered typographic family for a fallback while
    # retaining the requested regular weight. The effective weight is the
    # stable assertion; styleName is only a secondary signal for title faces.
    return int(info.weight()) >= 800 or (
        "heavy" in info.styleName().casefold() and int(info.weight()) >= 700
    )


def test_registered_heavy_does_not_become_application_body(app):
    assert app.font().weight() == 500
    assert 'Source Han' in QFontInfo(app.font()).family()
    assert not is_heavy(app.font()), QFontInfo(app.font()).family()


def test_title_and_body_resolve_different_faces_across_theme_switches(app):
    from twobyteasr.design.theme_manager import apply_theme
    root = QWidget()
    layout = QVBoxLayout(root)
    title = QLabel("应用设置")
    title.setProperty("typography", "title")
    body = QLabel("设置新工程的位置，以及工作中自动保存和恢复的方式。")
    body.setObjectName("settingsDescription")
    layout.addWidget(title)
    layout.addWidget(body)
    root.show()
    try:
        for key in ("warm", "slate", "plum", "lavender"):
            apply_theme(key, app)
            app.processEvents()
            assert is_heavy(title.font()), (key, QFontInfo(title.font()).family())
            assert title.font().weight() >= 800
            assert not is_heavy(body.font()), key
            assert body.font().weight() == 500
            assert 'Source Han' in QFontInfo(body.font()).family()
            assert title.font().pixelSize() > body.font().pixelSize()
    finally:
        root.close()


def test_studio_small_section_title_does_not_inherit_page_heavy(app):
    from twobyteasr.design.studio_theme import build_studio_qss
    from twobyteasr.design.ui_theme import theme_definition
    root = QWidget()
    root.setObjectName("subtitleStudio")
    root.setStyleSheet(build_studio_qss(theme_definition("slate")))
    label = QLabel("时间轴", root)
    label.setObjectName("sectionTitle")
    root.show()
    app.processEvents()
    try:
        assert label.font().pixelSize() == 14
        assert not is_heavy(label.font())
        assert label.font().weight() == 600
    finally:
        root.close()


def test_chinese_and_sc_heavy_aliases_are_shared():
    from twobyteasr.caption_style.font_system import SystemFontEntry, resolve_source_han_heavy
    from twobyteasr.design.typography import TITLE_FONT_FAMILIES
    for family in ("Source Han Sans SC Heavy", "思源黑体 Heavy"):
        face = resolve_source_han_heavy((SystemFontEntry(family, ("Regular",)),))
        assert family in TITLE_FONT_FAMILIES
        assert face.source_han and face.weight >= 800
