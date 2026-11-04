"""2026-11-03 Fill editor redesign (plan B "调色工作台")."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from twobyteasr.caption_style.studio_fill_editors import FillEditorDialog
from twobyteasr.design.fill_picker import AngleDial, ColorWheel, PillAlphaSlider, SwatchButton


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _linear(*colors: str, angle: float = 0.0) -> dict:
    count = max(1, len(colors) - 1)
    return {"type": "linear-gradient", "angle": angle,
            "stops": [{"color": value, "position": index / count} for index, value in enumerate(colors)]}


def _shown(dialog: FillEditorDialog) -> FillEditorDialog:
    dialog.show()
    for _ in range(3):
        _app().processEvents()
    return dialog


def test_dialog_is_frameless_rounded_modal_with_ok_cancel():
    _app()
    dialog = FillEditorDialog("#FFFF4DA3")
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert dialog.isModal()
    box = dialog.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.StandardButton.Ok).objectName() == "fillPrimary"
    assert box.button(QDialogButtonBox.StandardButton.Cancel).objectName() == "fillGhost"
    assert dialog.mode_combo.currentIndex() == 0
    dialog.deleteLater()


def test_palette_has_only_common_recent_gradient_and_follows_mode():
    _app()
    dialog = _shown(FillEditorDialog("#FFFFFFFF"))
    assert set(dialog._palette_tabs) == {"common", "recent", "gradient"}
    assert dialog._palette == "common" and dialog._palette_tabs["gradient"].isHidden()
    assert not dialog._gradient_card.isVisible()
    dialog.mode_combo.setCurrentIndex(1)
    _app().processEvents()
    assert dialog._gradient_card.isVisible() and dialog._angle_host.isVisible()
    assert dialog._palette == "gradient"
    presets = [button for button in dialog._swatches if button.stops]
    assert len(presets) == len(FillEditorDialog.GRADIENT_PRESETS)
    presets[4].click()
    assert [s["color"].upper() for s in dialog.value()["stops"]] == ["#FF00F0FF", "#FFFF00E5", "#FFFFE45E"]
    dialog.mode_combo.setCurrentIndex(2)
    _app().processEvents()
    assert dialog._gradient_card.isVisible() and not dialog._angle_host.isVisible()
    assert dialog.value()["type"] == "radial-gradient"
    dialog.mode_combo.setCurrentIndex(0)
    _app().processEvents()
    assert dialog._palette == "common"
    assert dialog.value().upper() == "#FFFFFFFF"
    dialog.close()


def test_common_swatch_sets_color_and_marks_selected():
    _app()
    dialog = _shown(FillEditorDialog("#FF112233"))
    yellow = next(b for b in dialog._swatches if b.color.name().upper() == "#FFE45E")
    yellow.click()
    assert dialog.picker.color().name().upper() == "#FFE45E"
    assert yellow.selected
    assert sum(b.selected for b in dialog._swatches) == 1
    dialog.close()


def test_drag_stop_off_rail_removes_it_but_keeps_two():
    _app()
    dialog = _shown(FillEditorDialog(_linear("#FFFF0000", "#FF00FF00", "#FF0000FF")))
    bar = dialog.gradient.bar
    strip = dialog.gradient._strip_rect()
    middle = QPoint(strip.left() + strip.width() // 2, strip.center().y())
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=middle)
    QTest.mouseMove(bar, middle + QPoint(0, 80))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=middle + QPoint(0, 80))
    assert len(dialog.gradient._stops) == 2
    left = QPoint(strip.left(), strip.center().y())
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=left)
    QTest.mouseMove(bar, left + QPoint(0, 80))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=left + QPoint(0, 80))
    assert len(dialog.gradient._stops) == 2
    dialog.close()


def test_selected_stop_edits_through_picker_and_previous_restores():
    _app()
    dialog = _shown(FillEditorDialog(_linear("#FFFFFFFF", "#80D2FF20")))
    dialog._select_gradient_stop(1)
    assert dialog.picker.color().alpha() == 0x80
    assert "色点 2" in dialog.picker.hex_caption.text()
    dialog.picker.alpha_slider.alphaChanged.emit(255)
    assert QColor(dialog.gradient._selected.color).alpha() == 255
    dialog.picker.plate.previousClicked.emit()
    assert QColor(dialog.gradient._selected.color).alpha() == 0x80
    dialog.close()


def test_hue_ring_alpha_strip_and_angle_dial_mapping():
    _app()
    wheel = ColorWheel()
    hues = []
    wheel.hueChanged.connect(hues.append)
    center = wheel.width() // 2
    mid = int(wheel._outer() - wheel.BAND / 2)
    QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=QPoint(center, center - mid))
    QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=QPoint(center + mid, center))
    assert abs(hues[0]) < 2 or abs(hues[0] - 360) < 2
    assert abs(hues[1] - 90) < 2
    before = len(hues)
    QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))  # outside the band
    assert len(hues) == before

    strip = PillAlphaSlider()
    strip.resize(200, 30)
    values = []
    strip.alphaChanged.connect(values.append)
    strip._apply(QPointF(0, 15))
    strip._apply(QPointF(200, 15))
    assert values == [0, 255]

    dial = AngleDial()
    angles = []
    dial.angleChanged.connect(angles.append)
    QTest.mouseClick(dial, Qt.MouseButton.LeftButton, pos=QPoint(19, 2))
    QTest.mouseClick(dial, Qt.MouseButton.LeftButton, pos=QPoint(36, 19))
    assert angles == [90.0, 0.0]


def test_angle_dial_drives_gradient_angle_and_chips():
    _app()
    dialog = _shown(FillEditorDialog(_linear("#FFFF0000", "#FF0000FF")))
    dialog.angle_dial.angleChanged.emit(45.0)
    assert dialog.value()["angle"] == 45.0
    assert [chip.isChecked() for chip in dialog._angle_chips] == [False, True, False]
    assert "45°" in dialog.preview._desc
    dialog.close()


def test_save_current_goes_to_recent_tab():
    _app()
    FillEditorDialog.recent_colors[:] = []
    dialog = _shown(FillEditorDialog("#FF7C5CFF"))
    dialog.save_button.click()
    assert dialog._palette == "recent"
    colors = [b.color.name(QColor.NameFormat.HexArgb).upper() for b in dialog._swatches if not b.add]
    assert colors == ["#FF7C5CFF"]
    assert any(isinstance(b, SwatchButton) and b.add for b in dialog._swatches)
    dialog.close()
    FillEditorDialog.recent_colors[:] = []


def test_hex_entry_keeps_alpha_and_rejects_partial():
    _app()
    dialog = _shown(FillEditorDialog("#80FF4DA3"))
    picker = dialog.picker
    picker.hex_edit.setText("#12")
    assert picker.color().name(QColor.NameFormat.HexArgb).upper() == "#80FF4DA3"
    picker.hex_edit.setText("#123456")
    assert picker.color().name(QColor.NameFormat.HexArgb).upper() == "#80123456"
    picker.hsb_spins[0].setValue(200)
    assert abs(picker.color().hsvHue() - 200) <= 1
    dialog.close()
