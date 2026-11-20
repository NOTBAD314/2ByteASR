"""Every button gives a little when pressed (2026-11-18).

User (2026-11-18): every button in the app — not only on the home page, also in Subtitle Studio,
the term library and the rest — should have the calm motion they picked (「A 沉穩」), smooth and
comfortable. About 950 buttons are made in a hundred places, so this is not done button by
button: one listener on the shared event hub sees every press of every ``QAbstractButton``.

While a button is held it eases down to ``motion_tokens.PRESS_SCALE`` (big buttons less, so no
edge moves more than a few pixels) on ``PRESS_IN``, and on release it eases back on ``SMALL``.
The scaling is drawn by a ``QGraphicsEffect`` that exists only while the button is moving; at
rest the button has no effect at all, so its normal painting, cost and look are untouched.

Left alone: disabled buttons, buttons that already carry a graphics effect (a shadow or a fade
of their own), buttons with a native window, buttons in popups and menus, buttons with the
dynamic property ``pressMotion`` set to False, and everything under 「减少动态效果」 or with
``TWOBYTEASR_PRESS_MOTION=0``.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QAbstractButton, QApplication, QGraphicsEffect

from .motion_tokens import PRESS_IN, PRESS_SCALE, SMALL

MAX_SHRINK_PX = 8.0        # a wide tile shrinks by at most this much across its longer side
_SUBSTEP = 1 / 480


def enabled() -> bool:
    if os.environ.get('TWOBYTEASR_PRESS_MOTION') == '0':
        return False
    from .ui_motion import reduced_motion
    return not reduced_motion()


def press_scale_for(button) -> float:
    longest = max(1, button.width(), button.height())
    return max(PRESS_SCALE, 1.0 - MAX_SHRINK_PX / longest)


def eligible(button) -> bool:
    if not isinstance(button, QAbstractButton) or not button.isEnabled() or not button.isVisible():
        return False
    if button.property('pressMotion') is False:
        return False
    effect = button.graphicsEffect()
    if effect is not None and not isinstance(effect, PressEffect):
        return False
    if button.testAttribute(Qt.WidgetAttribute.WA_NativeWindow):
        return False
    window = button.window()
    if window is not None and window.windowType() == Qt.WindowType.Popup:
        return False
    return True


class PressEffect(QGraphicsEffect):
    """Draws its button scaled about its centre.

    Never calls ``sourcePixmap()``: in PySide6 6.9.2 that binding crashes the process (access
    violation, reproduced with a bare QPushButton). Scaling the painter and letting Qt draw the
    source through ``drawSource()`` gives the same picture.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scale = 1.0

    def draw(self, painter):
        if abs(self.scale - 1.0) < 1e-4:
            self.drawSource(painter)
            return
        centre = self.sourceBoundingRect(Qt.CoordinateSystem.LogicalCoordinates).center()
        painter.save()
        painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(centre)
        painter.scale(self.scale, self.scale)
        painter.translate(-centre)
        self.drawSource(painter)
        painter.restore()


class _Press:
    __slots__ = ('button', 'effect', 'pos', 'vel', 'target', 'spring', 'destroy_hook')

    def __init__(self, button, effect):
        self.button = button
        self.effect = effect
        self.pos = 1.0
        self.vel = 0.0
        self.target = 1.0
        self.spring = PRESS_IN
        self.destroy_hook = None


class PressMotion(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.setObjectName('pressMotion')
        self._presses: dict[int, _Press] = {}
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._step)
        self._last = time.perf_counter()
        self.last_pressed = None           # (global QRect, perf_counter) of the last pressed button

    # ------------------------------------------------------------------ events
    def on_event(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and isinstance(watched, QAbstractButton):
                # Where the user last pressed: a dialog it opens grows out of this rectangle.
                from PySide6.QtCore import QRect
                self.last_pressed = (QRect(watched.mapToGlobal(watched.rect().topLeft()), watched.size()),
                                     time.perf_counter())
                self.press(watched)
        elif (kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
                or kind in (QEvent.Type.UngrabMouse, QEvent.Type.Hide, QEvent.Type.EnabledChange)):
            if isinstance(watched, QAbstractButton):
                self.release(watched)
        return False                                  # never consumes: the button works as before

    def press(self, button) -> bool:
        if not enabled() or not eligible(button):
            return False
        state = self._state(button)
        if state is None:
            return False
        state.target = press_scale_for(button)
        state.spring = PRESS_IN
        self._run(button)
        return True

    def release(self, button):
        state = self._presses.get(_key(button))
        if state is None:
            return
        state.target = 1.0
        state.spring = SMALL
        self._run(button)

    def _state(self, button) -> _Press | None:
        key = _key(button)
        state = self._presses.get(key)
        if state is not None:
            return state
        effect = PressEffect(button)
        button.setGraphicsEffect(effect)              # the button owns it; removed again at rest
        state = self._presses[key] = _Press(button, effect)
        state.destroy_hook = button.destroyed.connect(lambda *_a: self._presses.pop(key, None))
        return state

    def _run(self, button):
        if not self._timer.isActive():
            self._last = time.perf_counter()
            screen = button.screen()
            rate = screen.refreshRate() if screen is not None else 60.0
            self._timer.start(max(4, int(1000 / max(30.0, min(240.0, rate or 60.0)))))

    # ------------------------------------------------------------------ frames
    def _step(self):
        from shiboken6 import isValid
        now = time.perf_counter()
        dt = min(0.05, max(0.0, now - self._last))
        self._last = now
        for key, state in list(self._presses.items()):
            button = state.button
            if not isValid(button) or not isValid(state.effect) or button.graphicsEffect() is not state.effect:
                if isValid(button):
                    QObject.disconnect(state.destroy_hook)
                self._presses.pop(key, None)
                continue
            stiffness, coefficient = state.spring.constants()
            left = dt
            while left > 0:
                h = min(left, _SUBSTEP)
                state.vel += (-stiffness * (state.pos - state.target) - coefficient * state.vel) * h
                state.pos += state.vel * h
                left -= h
            resting = abs(state.pos - state.target) < 0.0008 and abs(state.vel) < 0.01
            if resting:
                state.pos, state.vel = state.target, 0.0
            state.effect.scale = state.pos
            state.effect.update()
            if resting and state.target == 1.0:
                QObject.disconnect(state.destroy_hook)
                button.setGraphicsEffect(None)        # deletes the effect: plain button again
                self._presses.pop(key, None)
        if not any(abs(s.pos - s.target) > 0 or s.vel for s in self._presses.values()):
            self._timer.stop()

    def moving(self, button=None) -> bool:
        return bool(self._presses) if button is None else _key(button) in self._presses


def _key(widget) -> int:
    from shiboken6 import getCppPointer
    return int(getCppPointer(widget)[0])


def install(app=None) -> PressMotion | None:
    """Give every button in the application its press motion (once)."""
    app = app or QApplication.instance()
    if app is None:
        return None
    existing = getattr(app, '_press_motion', None)
    if existing is not None:
        return existing
    from .app_events import listen
    motion = app._press_motion = PressMotion(app)
    listen(motion, (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                    QEvent.Type.UngrabMouse, QEvent.Type.Hide, QEvent.Type.EnabledChange), motion.on_event)
    return motion


__all__ = ['PressEffect', 'PressMotion', 'eligible', 'enabled', 'install', 'press_scale_for']
