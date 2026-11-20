"""Every button gives a little when pressed (2026-11-18, the calm feel 「A 沉穩」)."""
from __future__ import annotations

import inspect
import time

import pytest


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from twobyteasr.design.press_motion import install
    install(app)
    return app


def _pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.004)


def _mouse(widget, kind):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    centre = QPointF(widget.width() / 2, widget.height() / 2)
    QApplication.sendEvent(widget, QMouseEvent(kind, centre, QPointF(widget.mapToGlobal(centre.toPoint())),
                                               Qt.MouseButton.LeftButton,
                                               Qt.MouseButton.LeftButton if kind.name.endswith('Press') else Qt.MouseButton.NoButton,
                                               Qt.KeyboardModifier.NoModifier))


def test_a_press_eases_down_and_the_release_eases_back_to_a_plain_button(app):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.design.press_motion import PressEffect, press_scale_for
    button = QPushButton('保存')
    button.resize(120, 36)
    button.show()
    clicks = []
    button.clicked.connect(lambda: clicks.append(1))
    _mouse(button, QEvent.Type.MouseButtonPress)
    scales = []
    end = time.time() + 0.3
    while time.time() < end:
        app.processEvents()
        effect = button.graphicsEffect()
        scales.append(effect.scale if isinstance(effect, PressEffect) else 1.0)
        time.sleep(0.004)
    assert min(scales) == pytest.approx(press_scale_for(button), abs=0.002)
    assert scales == sorted(scales, reverse=True)                  # straight down, no bounce
    _mouse(button, QEvent.Type.MouseButtonRelease)
    _pump(app, 0.6)
    assert button.graphicsEffect() is None                         # back to a plain button
    assert clicks == [1]                                           # the click still happens
    button.deleteLater()


def test_big_buttons_move_only_a_few_pixels(app):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.design.motion_tokens import PRESS_SCALE
    from twobyteasr.design.press_motion import MAX_SHRINK_PX, press_scale_for
    small, wide = QPushButton('x'), QPushButton('开始生成字幕')
    small.resize(30, 30)
    wide.resize(600, 56)
    assert press_scale_for(small) == PRESS_SCALE
    assert (1 - press_scale_for(wide)) * 600 <= MAX_SHRINK_PX + 0.01


def test_buttons_with_their_own_effect_or_disabled_are_left_alone(app):
    from PySide6.QtWidgets import QGraphicsOpacityEffect, QPushButton
    from twobyteasr.design.press_motion import eligible
    shaded = QPushButton('a')
    shaded.setGraphicsEffect(QGraphicsOpacityEffect(shaded))
    disabled = QPushButton('b')
    disabled.setEnabled(False)
    opted = QPushButton('c')
    opted.setProperty('pressMotion', False)
    plain = QPushButton('d')
    for button in (shaded, disabled, opted, plain):
        button.show()
    assert not eligible(shaded) and not eligible(disabled) and not eligible(opted)
    assert eligible(plain)
    assert not app._press_motion.press(shaded)
    assert isinstance(shaded.graphicsEffect(), QGraphicsOpacityEffect)   # its own effect stays
    for button in (shaded, disabled, opted, plain):
        button.deleteLater()


def test_reduced_motion_turns_it_off(app, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    monkeypatch.setenv('TWOBYTEASR_PRESS_MOTION', '0')
    button = QPushButton('x')
    button.show()
    assert not app._press_motion.press(button)
    assert button.graphicsEffect() is None
    button.deleteLater()


def test_the_effect_never_calls_source_pixmap():
    """PySide6 6.9.2: QGraphicsEffect.sourcePixmap() crashes the process (access violation)."""
    from twobyteasr.design import press_motion
    source = inspect.getsource(press_motion.PressEffect.draw)
    assert 'sourcePixmap' not in source and 'drawSource' in source


def test_a_pressed_button_renders(app):
    from PySide6.QtWidgets import QPushButton
    from twobyteasr.design.press_motion import PressEffect
    button = QPushButton('渲染')
    button.resize(140, 40)
    effect = PressEffect(button)
    effect.scale = 0.9
    button.setGraphicsEffect(effect)
    button.show()
    image = button.grab().toImage()
    assert not image.isNull() and image.width() == 140
    button.deleteLater()


def test_the_real_app_turns_it_on_at_startup():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'quick_start.py').read_text('utf-8')
    assert 'install_press_motion(app)' in source
