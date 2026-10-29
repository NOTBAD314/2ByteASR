"""Regression contracts from real EXE feedback, including high-DPI drag pixels."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from types import SimpleNamespace
import pytest
from PySide6.QtCore import QRect, QSettings, QPoint
from PySide6.QtGui import QImage, QPixmap, QColor
from PySide6.QtWidgets import QApplication, QWidget
from twobyteasr.rendering.studio_live_canvas import AdvancedLiveCanvas
from twobyteasr.design.theme_manager import apply_theme
from twobyteasr.design.studio_theme import create_studio_menu, StudioComboBox
from twobyteasr.design.ui_theme import THEMES


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr('twobyteasr.design.theme_manager._settings', lambda: QSettings(str(tmp_path/'qt.ini'), QSettings.Format.IniFormat))
    yield app


def test_menu_created_before_theme_change_refreshes_on_open(app):
    apply_theme('warm', app)
    parent = QWidget()
    menu = create_studio_menu(parent)
    menu.addAction('继续编辑')
    apply_theme('grape', app)
    menu.popup(QPoint(20, 20))
    app.processEvents()
    assert menu._secondary_theme_key == 'grape'
    assert menu.grab().toImage().pixelColor(8, 8).name() == THEMES['grape'].surface_elevated
    menu.hide(); parent.deleteLater()


def test_editable_combo_updates_native_button_and_editor_palette(app):
    apply_theme('warm', app)
    combo = StudioComboBox()
    combo.setEditable(True)
    combo.addItem('测试字体')
    combo.show()
    apply_theme('grape', app)
    app.processEvents()
    role = combo.palette().ColorRole.Button
    assert combo.palette().color(role).name() == THEMES['grape'].input_surface
    assert combo.lineEdit().palette().color(role).name() == THEMES['grape'].input_surface
    combo.hide(); combo.deleteLater()


def test_temporary_root_releases_theme_sheet_when_adopted(app):
    apply_theme('warm', app)
    combo = StudioComboBox()
    combo.setEditable(True)
    combo.setStyleSheet('QComboBox { min-width: 120px; }')
    combo.ensurePolished()
    assert not getattr(combo, '_theme_root_sheet', None)
    # A control which really becomes a window is themed before first paint;
    # adoption must still release its former root stylesheet.
    combo.show()
    assert getattr(combo, '_theme_root_sheet', None)
    owner = QWidget()
    combo.setParent(owner)
    assert combo.styleSheet() == 'QComboBox { min-width: 120px; }'
    owner.show()
    apply_theme('grape', app)
    app.processEvents()
    assert combo.grab().toImage().pixelColor(40, 8).name() == THEMES['grape'].input_surface
    owner.hide(); owner.deleteLater()


@pytest.mark.parametrize('dpr', [1., 1.75, 2.])
def test_drag_preserves_physical_glyph_size_and_restores_without_reraster(app, dpr):
    owner = QWidget()
    canvas = AdvancedLiveCanvas(owner)
    canvas._base_rect = QRect(0, 0, 200, 100)
    canvas._snapshot = SimpleNamespace(playres_x=200, playres_y=100, position_x=50., position_y=50., font_size=20.)
    image = QImage(round(200*dpr), round(100*dpr), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('transparent'))
    from PySide6.QtGui import QPainter
    painter = QPainter(image); painter.fillRect(QRect(round(45*dpr), round(40*dpr), round(10*dpr), round(10*dpr)), QColor('white')); painter.end()
    image.setDevicePixelRatio(dpr)
    canvas._source = QPixmap.fromImage(image)
    generation = canvas._layer_generation
    canvas.set_transform_preview(dict(position_x=90, position_y=30))
    actual = canvas._display_source.toImage()
    assert actual.pixelColor(round(90*dpr), round(25*dpr)).alpha() == 255
    assert actual.pixelColor(round(50*dpr), round(45*dpr)).alpha() == 0
    assert canvas._layer_generation == generation
    canvas.set_transform_preview({})
    assert canvas._display_source.toImage() == image
    owner.deleteLater()


def test_hidden_canvas_cannot_republish_from_queued_show_or_geometry(app):
    class Surface(QWidget):
        ADVANCED_OVERLAY_ID = 1
        def __init__(self):
            super().__init__()
            self.posts = []
        def publish_compositor_overlay(self, *args, **kwargs):
            self.posts.append(args)
        def remove_compositor_overlay(self, *args, **kwargs):
            self.posts.clear()
    owner = Surface()
    owner.show()
    canvas = AdvancedLiveCanvas(owner)
    canvas._source = QPixmap(40, 20)
    canvas._source.fill(QColor('white'))
    canvas.set_base_geometry(QRect(0, 0, 40, 20))
    canvas.show()  # queues a native publish
    canvas.hide()
    canvas.set_base_geometry(QRect(0, 0, 80, 40))
    app.processEvents()
    assert not owner.posts
    canvas.show()
    app.processEvents()
    assert owner.posts
    owner.hide(); owner.deleteLater()
