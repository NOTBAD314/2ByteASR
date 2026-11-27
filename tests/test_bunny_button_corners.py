"""A button 兔白 wobbles keeps its rounded corners (2026-11-27).

User (2026-11-27): every time she plays with a button it turns from rounded to square corners.
The wobble draws the button onto its own picture; drawSource() did that with QWidget::render()'s
default flags, and DrawWindowBackground filled the whole rectangle with the palette's window colour.
"""
from __future__ import annotations


def test_a_wobbling_button_keeps_its_rounded_corners():
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QPushButton, QWidget
    from twobyteasr.design.bunny_button_fx import WobbleEffect
    app = QApplication.instance() or QApplication([])
    card = QWidget()
    card.setStyleSheet('QWidget { background: #2050a0; }'
                       'QPushButton { background: #c03060; border: none; border-radius: 16px; color: white; }')
    card.resize(300, 160)
    button = QPushButton('开始', card)
    button.setGeometry(60, 50, 180, 48)
    card.show()
    app.processEvents()
    effect = WobbleEffect(button, 20)
    button.setGeometry(60, 50, 180, 48)
    button.setGraphicsEffect(effect)
    effect.x = 0.6                     # moving (not resting): drawn through its own picture
    effect.update()
    app.processEvents()
    picture = card.grab().toImage()
    ratio = picture.devicePixelRatio()
    corner = QColor(picture.pixel(round((60 + 2) * ratio), round((50 + 2) * ratio)))
    middle = QColor(picture.pixel(round(150 * ratio), round(74 * ratio)))
    assert middle.red() > 150 and middle.blue() < 140, middle.name()          # the button itself
    assert corner.blue() > 130 and corner.red() < 90, corner.name()           # the card shows at the corner
    button.setGraphicsEffect(None)
    card.close()
    card.deleteLater()
    app.processEvents()
