"""What 兔白 does to the software's buttons: they tilt, jolt, squash, sway and shake (2026-11-26).

User (2026-11-26, after the first round of her errands): her actions must really affect the
buttons — they should go crooked and vibrate — and the interaction with the button must be plain
before she does anything with it, so one can see she took the book out of it or hit the gear.

``WobbleEffect`` is a ``QGraphicsEffect`` that draws its widget turned about a pivot, shifted and
squashed (like ``press_motion.PressEffect``, only through ``drawSource``: ``sourcePixmap`` crashes
PySide6 6.9). It exists only while the widget moves; at rest the widget is plain again. Widgets
that already carry an effect of their own (a shadow, a fade, a press in progress) are left alone.

``ButtonFx`` keeps a spring per channel and widget — angle (degrees), x and y (px), squash and a
door-like ``open`` about the pivot — and is stepped by the caller's clock (``step(now)``) so a
review can render exact frames. ``kick`` adds speed (a hit), ``hold`` sets where a channel rests
(her weight on it), ``release`` lets everything spring back, ``shake`` vibrates for a while, and
``spin``/``take_icon``/``give_icon`` turn, borrow and return a button's themed icon. These springs
are deliberately bouncy: the wobble is what the user asked to see. Nothing here clicks anything.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QGraphicsEffect

CHANNELS = ('angle', 'x', 'y', 'squash', 'open')
STIFFNESS = {'angle': 210.0, 'x': 260.0, 'y': 300.0, 'squash': 420.0, 'open': 120.0}
DAMPING = {'angle': 7.5, 'x': 9.0, 'y': 10.0, 'squash': 12.0, 'open': 14.0}
LIMIT = {'angle': 28.0, 'x': 34.0, 'y': 30.0, 'squash': .35, 'open': .8}
SUBSTEP = 1 / 480
SPIN_FRICTION = 3.2          # 1/s: how fast a kicked gear slows down


class WobbleEffect(QGraphicsEffect):
    """Draws its widget turned about ``pivot`` (fractions of its rect), shifted and squashed."""

    def __init__(self, parent=None, margin: float = 24.0):
        super().__init__(parent)
        self.angle = self.x = self.y = self.squash = self.open = 0.0
        self.pivot = (0.5, 1.0)
        self.margin = float(margin)
        self._inner = False

    def boundingRectFor(self, rect):  # noqa: N802 - Qt override: room for the turned corners
        m = self.margin
        return QRectF(rect).adjusted(-m, -m, m, m)

    def resting(self) -> bool:
        return (abs(self.angle) < .02 and abs(self.x) < .05 and abs(self.y) < .05 and abs(self.squash) < .002
                and abs(self.open) < .002)

    def draw(self, painter):
        if self.resting() or self._inner:
            self.drawSource(painter)
            return
        # drawSource() on the painter Qt hands us draws the widget straight back in place and ignores
        # the painter's transform; drawn onto a painter of our own it is rendered through it. So: the
        # widget onto a pixmap first (live: a turning icon shows), then the pixmap turned and shifted.
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPainter, QPixmap, QRegion
        from PySide6.QtWidgets import QWidget
        rect = self.sourceBoundingRect(Qt.CoordinateSystem.LogicalCoordinates)
        device = painter.device()
        ratio = float(device.devicePixelRatioF()) if hasattr(device, 'devicePixelRatioF') else 1.0
        picture = QPixmap(max(1, round(rect.width() * ratio)), max(1, round(rect.height() * ratio)))
        picture.setDevicePixelRatio(ratio)
        picture.fill(Qt.GlobalColor.transparent)
        inner = QPainter(picture)
        inner.translate(-rect.topLeft())
        self._inner = True
        try:
            # 2026-11-27 (user: every button she touches turns from rounded to square corners):
            # drawSource() onto our own painter is QWidget::render() with its default flags, and
            # DrawWindowBackground fills the whole rect with the palette's window colour behind the
            # rounded style. Rendered with DrawChildren only, the corners stay see-through.
            widget = self.parent()
            if isinstance(widget, QWidget):
                widget.render(inner, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
            else:
                self.drawSource(inner)
        finally:
            self._inner = False
            inner.end()
        px = rect.left() + rect.width() * self.pivot[0]
        py = rect.top() + rect.height() * self.pivot[1]
        painter.save()
        painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.translate(px + self.x, py + self.y)
        painter.rotate(self.angle)
        sx = (1 + .55 * self.squash) * (1 - .78 * max(0.0, self.open))
        sy = 1 - self.squash
        painter.scale(max(.05, sx), max(.05, sy))
        painter.translate(-px, -py)
        painter.drawPixmap(rect.topLeft(), picture)
        if self.open > .02:                          # a door swung away from us is darker
            from PySide6.QtGui import QColor
            shade = QColor(0, 0, 0)
            shade.setAlphaF(min(.45, self.open * .5))
            painter.fillRect(rect, shade)
        painter.restore()


class _Wobble:
    __slots__ = ('widget', 'effect', 'pos', 'vel', 'target', 'shake_until', 'shake_px', 'shake_deg', 'shake_from',
                 'held')

    def __init__(self, widget, effect):
        self.widget = widget
        self.effect = effect
        self.pos = dict.fromkeys(CHANNELS, 0.0)
        self.vel = dict.fromkeys(CHANNELS, 0.0)
        self.target = dict.fromkeys(CHANNELS, 0.0)
        self.shake_until = self.shake_from = 0.0
        self.shake_px = self.shake_deg = 0.0
        self.held = False


class _Spin:
    __slots__ = ('button', 'icon', 'angle', 'speed', 'last')

    def __init__(self, button, icon):
        self.button, self.icon = button, icon
        self.angle = self.speed = 0.0
        self.last = None


def themed_icon_of(button):
    """The button's own themed icon (``install_themed_icon``), or what it shows now."""
    from .themed_icons import themed_icon
    spec = button.property('_themed_icon')
    return themed_icon(spec[0], spec[1]) if isinstance(spec, tuple) else button.icon()


def restore_icon(button) -> None:
    from .themed_icons import refresh_widget_icons
    try:
        if isinstance(button.property('_themed_icon'), tuple):
            refresh_widget_icons(button)
    except RuntimeError:
        pass


def usable(widget) -> bool:
    """Free to wobble: shown, not a native window, and no graphics effect of anyone else's."""
    try:
        if widget is None or not widget.isVisible():
            return False
        effect = widget.graphicsEffect()
        if effect is not None and not isinstance(effect, WobbleEffect):
            return False
        return not widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    except RuntimeError:
        return False


class ButtonFx:
    def __init__(self):
        self._wobbles: dict[int, _Wobble] = {}
        self._spins: dict[int, _Spin] = {}
        self._taken: dict[int, object] = {}
        self._last = None

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _key(widget) -> int:
        from shiboken6 import getCppPointer
        return int(getCppPointer(widget)[0])

    def _wobble(self, widget, pivot=None):
        if not usable(widget):
            return None
        key = self._key(widget)
        state = self._wobbles.get(key)
        if state is None or state.widget.graphicsEffect() is not state.effect:
            margin = 18 + .32 * max(widget.width(), widget.height())
            effect = WobbleEffect(widget, margin)
            widget.setGraphicsEffect(effect)
            state = self._wobbles[key] = _Wobble(widget, effect)
        if pivot is not None:
            state.effect.pivot = (float(pivot[0]), float(pivot[1]))
        return state

    def busy(self) -> bool:
        return bool(self._wobbles) or bool(self._spins)

    def moving(self, widget) -> bool:
        try:
            return self._key(widget) in self._wobbles
        except Exception:  # noqa: BLE001
            return False

    def offset(self, widget):
        """(angle, x, y, squash) the widget is drawn with now."""
        state = self._wobbles.get(self._key(widget)) if widget is not None else None
        if state is None:
            return (0.0, 0.0, 0.0, 0.0)
        return (state.pos['angle'], state.pos['x'], state.pos['y'], state.pos['squash'])

    # ------------------------------------------------------------ what she does to it
    def kick(self, widget, pivot=None, **speeds) -> bool:
        """A hit: each named channel (angle, x, y, squash, open) gets this much speed (units per second)."""
        state = self._wobble(widget, pivot)
        if state is None:
            return False
        for name, speed in speeds.items():
            state.vel[name] += float(speed)
        return True

    def hold(self, widget, pivot=None, **targets) -> bool:
        """Her weight on it: each named channel rests at this value until ``release``."""
        state = self._wobble(widget, pivot)
        if state is None:
            return False
        for name, value in targets.items():
            state.target[name] = max(-LIMIT[name], min(LIMIT[name], float(value)))
        state.held = True
        return True

    def release(self, widget=None) -> None:
        for state in list(self._wobbles.values()):
            if widget is None or state.widget is widget:
                state.target = dict.fromkeys(CHANNELS, 0.0)
                state.held = False

    def shake(self, widget, seconds: float, now: float, px: float = 2.0, degrees: float = 3.0, pivot=None) -> bool:
        state = self._wobble(widget, pivot)
        if state is None:
            return False
        state.shake_from = now
        state.shake_until = max(state.shake_until, now + seconds)
        state.shake_px, state.shake_deg = float(px), float(degrees)
        return True

    def spin(self, button, degrees_per_s: float) -> None:
        """Kick the button's icon round (a gear she cranks); it slows down by itself."""
        key = self._key(button)
        spin = self._spins.get(key)
        if spin is None:
            spin = self._spins[key] = _Spin(button, themed_icon_of(button))
        spin.speed += float(degrees_per_s)

    def take_icon(self, button):
        """Borrow the icon (the book she takes out): the button shows none until ``give_icon``."""
        from PySide6.QtGui import QIcon
        key = self._key(button)
        icon = themed_icon_of(button)
        self._taken[key] = button
        self._spins.pop(key, None)
        button.setIcon(QIcon())
        return icon

    def give_icon(self, button) -> None:
        self._taken.pop(self._key(button), None)
        restore_icon(button)

    # ------------------------------------------------------------ frames
    def step(self, now: float) -> None:
        from shiboken6 import isValid
        dt = 0.0 if self._last is None else min(.05, max(0.0, now - self._last))
        self._last = now
        for key, state in list(self._wobbles.items()):
            widget, effect = state.widget, state.effect
            if not isValid(widget) or not isValid(effect) or widget.graphicsEffect() is not effect:
                self._wobbles.pop(key, None)
                continue
            left = dt
            while left > 1e-9:
                h = min(left, SUBSTEP)
                for name in CHANNELS:
                    k, c = STIFFNESS[name], DAMPING[name]
                    state.vel[name] += (-k * (state.pos[name] - state.target[name]) - c * state.vel[name]) * h
                    state.pos[name] += state.vel[name] * h
                    state.pos[name] = max(-LIMIT[name] * 1.4, min(LIMIT[name] * 1.4, state.pos[name]))
                left -= h
            jitter_deg = jitter_px = 0.0
            if now < state.shake_until:
                fade = min(1.0, (state.shake_until - now) / .25)
                t = now - state.shake_from
                jitter_deg = state.shake_deg * fade * math.sin(t * 2 * math.pi * 23)
                jitter_px = state.shake_px * fade * math.sin(t * 2 * math.pi * 29 + 1.3)
            effect.angle = state.pos['angle'] + jitter_deg
            effect.x = state.pos['x'] + jitter_px
            effect.y = state.pos['y']
            effect.squash = state.pos['squash']
            effect.open = state.pos['open']
            effect.update()
            resting = (not state.held and now >= state.shake_until
                       and all(abs(state.pos[n]) < (.02 if n == 'angle' else .004 if n in ('squash', 'open') else .05)
                               and abs(state.vel[n]) < .2 for n in CHANNELS))
            if resting:
                widget.setGraphicsEffect(None)          # plain again
                self._wobbles.pop(key, None)
        for key, spin in list(self._spins.items()):
            button = spin.button
            if not isValid(button):
                self._spins.pop(key, None)
                continue
            spin.angle = (spin.angle + spin.speed * dt) % 360
            spin.speed *= math.exp(-SPIN_FRICTION * dt)
            if abs(spin.speed) < 4:
                self._spins.pop(key, None)
                restore_icon(button)
                continue
            _set_turned_icon(button, spin.icon, spin.angle)

    def clear(self) -> None:
        """Everything back at once (an errand stopped)."""
        from shiboken6 import isValid
        for state in self._wobbles.values():
            if isValid(state.widget) and state.widget.graphicsEffect() is state.effect:
                state.widget.setGraphicsEffect(None)
        for spin in self._spins.values():
            if isValid(spin.button):
                restore_icon(spin.button)
        for button in self._taken.values():
            if isValid(button):
                restore_icon(button)
        self._wobbles.clear()
        self._spins.clear()
        self._taken.clear()


def _set_turned_icon(button, icon, angle: float) -> None:
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    size = button.iconSize()
    ratio = button.devicePixelRatioF()
    base = icon.pixmap(size, ratio)
    out = QPixmap(base.size())
    out.setDevicePixelRatio(base.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    w, h = size.width(), size.height()
    painter.translate(w / 2, h / 2)
    painter.rotate(angle)
    painter.translate(-w / 2, -h / 2)
    painter.drawPixmap(0, 0, base)
    painter.end()
    button.setIcon(QIcon(out))


__all__ = ['ButtonFx', 'WobbleEffect', 'restore_icon', 'themed_icon_of', 'usable']
