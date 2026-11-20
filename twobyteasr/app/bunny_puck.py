"""兔白 off the chat card: picked up, thrown, bouncing off the window, drifting to a place (2026-11-14).

User (2026-11-14): in 「问问兔白」 she should be draggable like the tutorial bunny — thrown, she
bounces off the window's edges (a glow where she hits, a little squash) — and she should float
over to the place she is talking about or working on.

The physics are the tutorial's (``home_tour.GuidedTour``: no gravity, DVD-logo bounces that
slowly run out of speed, the same constants), on a small window that carries only the bunny, so
the rest of the app keeps every click. Positions are in main-window coordinates; she stays inside
the window. When she has settled (or finished at a place) she floats back beside the card.

On Windows the main window's pages are a native child window, so the carrier and the edge glow
are frameless tool windows above it (like the chat card and the tutorial); elsewhere children.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

# The tutorial's feel (home_tour.GuidedTour).
FOLLOW = 26.0              # 1/s: how tightly she follows the pointer while held
RESTITUTION = 0.88         # speed kept after an edge
DRAG = 0.32                # 1/s between edges
STOP_DRAG = 3.0            # 1/s once slow: she eases to a stop
HIT_SPEED = 240.0          # px/s into an edge that gives feedback
MAX_THROW = 3800.0
MAX_FLIGHT_S = 14.0
FLASH_MS = 180
SHAKE_MS = 160
REST_BEFORE_HOME_MS = 1600   # settled after a throw: a moment, then back to the card
DRIFT_MS = 650


def _tool_flags(input_too: bool):
    flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
    if not input_too:
        flags |= Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput
    return flags


class _Carrier(QWidget):
    """A clear layer over the whole main window that 兔白 moves about in (2026-11-15, second round).

    The first carrier was a window the bunny's size, moved on every frame. The user still saw her
    cut down to one corner while carried, and her card a beat behind. Like the tutorial's overlay
    (``home_tour.GuidedTour``), this layer stays put over the window and only the bunny moves
    inside it; its mask is her rectangle, so every other click goes to what is under it.
    """

    # 2026-11-18 (user: while she moves she stutters or vanishes for a moment): the mask used to be
    # her exact rectangle, set again on every frame. On Windows that is a SetWindowRgn per frame,
    # applied at once while her new picture is painted a little later, so for a frame the window
    # showed only the region where she no longer was — she blinked out. Now, while she moves, the
    # mask is a roomy box that always holds both where she was and where she is, and is changed
    # only when she leaves it; once she rests it shrinks back to her rectangle.
    MOVE_ROOM = 64

    def __init__(self, window, floating: bool):
        super().__init__(window, _tool_flags(True) | Qt.WindowType.WindowDoesNotAcceptFocus if floating
                         else Qt.WindowType.Widget)
        self.setObjectName('bunnyCarrier')
        self.window_ = window
        self.floating = floating
        self._held = QRect()
        self._mask_rect = QRect()
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        if floating:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.hide()

    def cover(self):
        """Lie exactly over the main window's inside."""
        window = self.window_
        if self.floating:
            from . import floating_anchor
            floating_anchor.cover_window(self, window)      # in physical pixels (2026-11-19)
        elif self.geometry() != window.rect():
            self.setGeometry(window.rect())

    def _set_mask_rect(self, rect: QRect):
        from PySide6.QtGui import QRegion
        if rect != self._mask_rect:
            self._mask_rect = QRect(rect)
            self.setMask(QRegion(rect))

    def hold(self, mascot, at: QPoint, moving: bool = False):
        """Her widget's top-left at ``at`` (window coordinates); only near her do clicks stop here."""
        rect = QRect(at, mascot.size())
        previous, self._held = self._held, rect
        mascot.move(at)
        if not moving or previous.isNull():
            self._set_mask_rect(rect)
        elif not self._mask_rect.contains(rect):
            room = self.MOVE_ROOM
            self._set_mask_rect(rect.adjusted(-room, -room, room, room).united(previous))

    def rest(self):
        """She stopped: clicks stop only on her own rectangle again."""
        if not self._held.isNull():
            self._set_mask_rect(self._held)


class _EdgeGlow(QWidget):
    """The glow where she hits an edge; never takes a click."""

    def __init__(self, window, floating: bool, color: str):
        super().__init__(window, _tool_flags(False) if floating else Qt.WindowType.Widget)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if floating:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.color = QColor(color)
        self.flash = None              # (x, y, power, started, side) in window coordinates
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def show_hit(self, x: float, y: float, power: float, side: str, window_rect: QRect, floating: bool, window):
        self.flash = (x, y, power, time.perf_counter(), side)
        if floating:
            from . import floating_anchor
            floating_anchor.cover_window(self, window)
        else:
            self.setGeometry(window_rect)
        self.show()
        if floating:
            floating_anchor.cover_window(self, window)      # its native window exists only from here
        self.raise_()
        self._timer.start()

    def _tick(self):
        if self.flash is None or (time.perf_counter() - self.flash[3]) * 1000 > FLASH_MS:
            self.flash = None
            self._timer.stop()
            self.hide()
            return
        self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        if self.flash is None:
            return
        x, y, power, started, side = self.flash
        k = (time.perf_counter() - started) * 1000 / FLASH_MS
        if k >= 1:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        glow = QColor(self.color)
        gradient = QRadialGradient(QPointF(x, y), 130)
        glow.setAlphaF(max(0.0, min(1.0, 0.9 * power * (1 - k))))
        gradient.setColorAt(0.0, glow)
        glow.setAlphaF(0.0)
        gradient.setColorAt(0.72, glow)
        painter.translate(x, y)
        painter.scale(1.0, 50 / 130) if side in ('top', 'bottom') else painter.scale(50 / 130, 1.0)
        painter.translate(-x, -y)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(x, y), 130, 130)


class BunnyPuck:
    """Owns 兔白 while she is off the card: dragging, flying, bouncing, drifting, coming home."""

    def __init__(self, chat):
        self.chat = chat
        self.window = chat.window_
        self.mascot = chat.mascot
        self.floating = chat.floating
        self.carrier = _Carrier(self.window, self.floating)
        self.glow = _EdgeGlow(self.window, self.floating, chat.theme.accent)
        self.docked = True
        self.pos = QPointF()            # her top-left in window coordinates while off the card
        self.velocity = QPointF()
        self.target = None              # where the pointer wants her while held
        self.history = []
        self.press = None
        self.started = 0.0
        self.last = time.perf_counter()
        self.timer = QTimer(self.carrier)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._step)
        self.home_timer = QTimer(self.carrier)
        self.home_timer.setSingleShot(True)
        self.home_timer.timeout.connect(self.go_home)
        self.glide = QVariantAnimation(self.carrier)
        self.glide.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.glide.valueChanged.connect(self._glide_step)
        self.glide.finished.connect(self._glide_done)
        self._glide_path = None
        self._glide_then = None
        self._last_impact = 0.0
        self.shake = QVariantAnimation(self.carrier)
        self.shake.setStartValue(0.0)
        self.shake.setEndValue(1.0)
        self.shake.setDuration(SHAKE_MS)
        self.shake.valueChanged.connect(self._shake_step)
        self.shake.finished.connect(lambda: self._set_impact(QPointF()))
        if self.floating:
            self.carrier.winId()       # its native window now, not on the first pick-up (a hitch)
        self._shake_dir = QPointF()
        self._shake_power = 0.0
        # 2026-11-15 (user): picked up and thrown, her chat card comes along instead of staying
        # behind in its corner. ``card_at`` is where the card's bunny place is heading (window
        # coordinates); None while she is not carried (drifting to a place keeps the card still).
        self.card_at = None

    # ------------------------------------------------------------ where things are
    def home_point(self) -> QPointF:
        """Her place beside the card, in window coordinates."""
        chat = self.chat
        return QPointF(chat._home_rect().topLeft() + chat.mascot_slot)

    def limits(self) -> QRectF:
        """Where her widget's top-left may go: the drawn bunny (not its margins) stays inside the window."""
        mascot = self.mascot
        bottom = round(mascot.mascot_height * 0.06)
        m = 4
        top = m - mascot.pad_top
        return QRectF(m - mascot.pad_x, top, self.window.width() - mascot.width() + 2 * mascot.pad_x - 2 * m,
                      self.window.height() - mascot.height() + bottom - m - top)

    def _clamp(self, at: QPointF) -> QPointF:
        limits = self.limits()
        return QPointF(max(limits.left(), min(at.x(), limits.right())), max(limits.top(), min(at.y(), limits.bottom())))

    def _place(self, at: QPointF):
        self.pos = QPointF(at)
        if self.mascot is None:
            return
        self.carrier.cover()
        if not self.docked:
            # 2026-11-15 (user): carried, her card comes along in the same frame (it used to ease
            # after her and lagged a beat); then she moves inside the clear layer. Moving the card
            # puts the layer back in front of it (BunnyChat.place); a still card cannot bury her,
            # so the layer is no longer raised on every frame (2026-11-18: a z-order change per
            # frame on top of the move).
            if self.card_at is not None:
                self.card_at = QPointF(at)
                self.chat.follow_bunny(self.card_at)
            self.carrier.hold(self.mascot, at.toPoint(), moving=self._moving())

    def _moving(self) -> bool:
        return self.timer.isActive() or self.glide.state() == QVariantAnimation.State.Running

    # ------------------------------------------------------------ on and off the card
    def undock(self):
        if not self.docked or self.mascot is None:
            return
        self.home_timer.stop()
        start = self.home_point()
        self.docked = False
        self.chat.mascot_docked = False
        # 2026-11-18: the layer is shown (already masked to her place) before she moves onto it,
        # and its native window exists since the chat opened, so there is no gap where she is on
        # neither the card nor the layer.
        self.carrier.cover()
        self.carrier.hold(self.mascot, start.toPoint())
        self.carrier.show()
        self.carrier.raise_()
        self.mascot.setParent(self.carrier)
        self.mascot.show()
        self._place(start)

    def dock(self):
        """Back beside the card, right away."""
        self.timer.stop()
        self.glide.stop()
        self.home_timer.stop()
        self.card_at = None
        if self.docked or self.mascot is None:
            return
        if self.press is not None:
            self.mascot.releaseMouse()
            self.press = None
        self.mascot.stretch = 0.0
        self.mascot.setParent(self.chat)
        self.mascot.show()
        self.mascot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.docked = True
        self.chat.mascot_docked = True
        self.carrier.hide()
        self.chat.relayout()

    def go_home(self):
        """Float back beside the card, then dock."""
        if self.docked:
            return
        self.card_at = None                        # the card waits where it is; she floats to it
        self.glide_to(self.home_point(), then=self.dock, clamp=False)

    # ------------------------------------------------------------ the pointer
    def mouse(self, event) -> bool:
        """The mascot's mouse events (from the chat's event filter); True when used."""
        from PySide6.QtCore import QEvent
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            # 2026-11-19: the pointer in window coordinates, read in physical pixels (floating_anchor):
            # with screens at different scales the event's own position jumped as she crossed an edge.
            from . import floating_anchor
            pointer = floating_anchor.Pointer(self.window, self.mascot, event)
            point = pointer.at(event)
            caught = not self.docked and (self.timer.isActive() or self.glide.state() == QVariantAnimation.State.Running)
            self.timer.stop()
            self.glide.stop()
            self.home_timer.stop()
            self.press = dict(start=point, grab=QPointF(event.position()), moved=caught, pointer=pointer)
            if caught:
                self._hold(point)
            return True
        if kind == QEvent.Type.MouseMove and self.press is not None:
            point = self.press['pointer'].at(event)
            if not self.press['moved']:
                delta = point - self.press['start']
                if abs(delta.x()) + abs(delta.y()) < 4:
                    return True
                self.press['moved'] = True
                self._hold(point)
            self.target = point - self.press['grab']
            return True
        if kind == QEvent.Type.MouseButtonRelease and self.press is not None:
            press, self.press = self.press, None
            if not press['moved']:
                if self.docked:
                    self.chat.poke()
                else:
                    self.carrier.rest()
                    self.chat.poke()
                    self.home_timer.start(REST_BEFORE_HOME_MS)
                return True
            self._throw()
            return True
        return False

    def _hold(self, point: QPointF):
        if self.card_at is None:
            self.card_at = self.home_point()
        self.undock()
        self.mascot.play('struggle')                # A17: little feet kicking while she dangles
        self.hard_hits = 0
        self.mascot.grabMouse()                    # the press's hold, kept across the reparenting
        self.mascot.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.history = [(time.perf_counter(), QPointF(self.pos))]
        self.target = QPointF(point) - self.press['grab']       # ``point`` is in window coordinates
        self.velocity = QPointF()
        self.last = time.perf_counter()
        self.timer.start()

    def _throw(self):
        from ..design.ui_motion import reduced_motion
        self.mascot.releaseMouse()
        self.mascot.stop_move('struggle')
        self.mascot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.target = None
        now = time.perf_counter()
        recent = [(t, p) for t, p in self.history if now - t <= 0.09] or self.history[-1:]
        (t0, p0), (t1, p1) = recent[0], self.history[-1]
        velocity = (p1 - p0) / max(t1 - t0, 0.012) if now - t1 < 0.12 else QPointF()
        speed = math.hypot(velocity.x(), velocity.y())
        if speed > MAX_THROW:
            velocity *= MAX_THROW / speed
        self.velocity = QPointF() if reduced_motion() else velocity
        self.started = now
        self.last = now
        self.timer.start()

    # ------------------------------------------------------------ flying
    def _step(self):
        mascot = self.mascot
        if self.docked or mascot is None or not self.carrier.isVisible() or self.window.isMinimized():
            self.timer.stop()
            return
        now = time.perf_counter()
        dt = min(0.04, max(0.001, now - self.last))
        self.last = now
        if self.target is not None:                # held
            previous = QPointF(self.pos)
            self._place(self._clamp(previous + (self.target - previous) * (1 - math.exp(-dt * FOLLOW))))
            self.velocity = (self.pos - previous) / dt
            self.history = [(t, p) for t, p in self.history if now - t < 0.14] + [(now, QPointF(self.pos))]
            speed = math.hypot(self.velocity.x(), self.velocity.y())
            self._relax(0.1 + min(0.08, speed / 20000), dt)
            return
        limits = self.limits()
        steps = max(1, math.ceil(dt / 0.008))
        h = dt / steps
        v, at = QPointF(self.velocity), QPointF(self.pos)
        hits = []
        for _ in range(steps):
            speed = math.hypot(v.x(), v.y())
            v *= math.exp(-(DRAG if speed > 160 else STOP_DRAG) * h)
            at += v * h
            if at.x() < limits.left() or at.x() > limits.right():
                hits.append(('left' if at.x() < limits.left() else 'right', abs(v.x())))
                at.setX(max(limits.left(), min(at.x(), limits.right())))
                v.setX(-v.x() * RESTITUTION)
            if at.y() < limits.top() or at.y() > limits.bottom():
                hits.append(('top' if at.y() < limits.top() else 'bottom', abs(v.y())))
                at.setY(max(limits.top(), min(at.y(), limits.bottom())))
                v.setY(-v.y() * RESTITUTION)
        self.velocity = v
        self._place(at)
        for side, speed in sorted(hits, key=lambda hit: hit[1], reverse=True)[:1]:
            if speed >= HIT_SPEED:
                power = max(0.3, min(1.0, speed / 2200.0))
                self.hard_hits = getattr(self, 'hard_hits', 0) + (1 if power > 0.45 else 0)
                mascot.stretch = -0.22 * power if side in ('top', 'bottom') else 0.15 * power
                self._edge_hit(side, power)
        self._relax(0.0, dt)
        if math.hypot(v.x(), v.y()) < 8 or now - self.started > MAX_FLIGHT_S:
            self.velocity = QPointF()
            mascot.stretch = 0.0
            mascot.update()
            self.timer.stop()
            self.carrier.rest()
            if getattr(self, 'hard_hits', 0) >= 3:      # A11: thrown about too hard, she is dizzy
                mascot.act('dizzy')
            self.hard_hits = 0
            self.home_timer.start(REST_BEFORE_HOME_MS)

    def _relax(self, target: float, dt: float):
        mascot = self.mascot
        mascot.stretch += (target - mascot.stretch) * (1 - math.exp(-dt * 14))
        if abs(mascot.stretch) < 0.002 and not target:
            mascot.stretch = 0.0
        mascot.update()

    def _edge_hit(self, side: str, power: float):
        mascot = self.mascot
        rect = QRectF(self.pos, QPointF(self.pos) + QPointF(mascot.width(), mascot.height()))
        if side in ('top', 'bottom'):
            x, y = rect.center().x(), (0.0 if side == 'top' else float(self.window.height()))
        else:
            x = 0.0 if side == 'left' else float(self.window.width())
            y = rect.top() + mascot.pad_top + (rect.height() - mascot.pad_top) / 2
        self.glow.show_hit(x, y, power, side, self.window.rect(), self.floating, self.window)
        self.carrier.raise_()
        self.chat._spoke('呜', 'surprised')
        now = time.perf_counter()
        if now - self._last_impact > 0.18 and self.shake.state() != QVariantAnimation.State.Running:
            self._last_impact = now
            self._shake_power = power
            self._shake_dir = {'left': QPointF(-1, 0), 'right': QPointF(1, 0), 'top': QPointF(0, -1),
                               'bottom': QPointF(0, 1)}[side]
            self.shake.start()

    def _shake_step(self, value):
        value = float(value)
        if value < 0.22:
            kick = math.sin(value / 0.22 * math.pi / 2)
        elif value < 0.6:
            kick = 1 - 1.25 * (0.5 - 0.5 * math.cos((value - 0.22) / 0.38 * math.pi))
        else:
            kick = -0.25 * (1 - (0.5 - 0.5 * math.cos((value - 0.6) / 0.4 * math.pi)))
        self._set_impact(self._shake_dir * ((1.5 + 1.5 * self._shake_power) * kick))

    def _set_impact(self, offset: QPointF):
        if self.mascot is not None:
            self.mascot.impact_offset = QPointF(offset)
            self.mascot.update()

    # ------------------------------------------------------------ drifting to a place
    def spot_beside(self, widget) -> QPointF | None:
        """A place next to ``widget`` where the drawn bunny fits inside the window, in window coordinates.

        Near the top (the top bar's buttons sit side by side) she floats just below the control;
        elsewhere beside it, right if there is room, else left; above as the last choice.
        """
        if widget is None or self.mascot is None:
            return None
        from .bunny_chat import reveal_widget
        reveal_widget(widget)
        rect = QRect(widget.mapTo(self.window, QPoint(0, 0)), widget.size())
        mascot = self.mascot
        drawn_w = mascot.width() - 2 * mascot.pad_x
        drawn_h = mascot.height() - mascot.pad_top
        gap = 6

        def at(left, top):         # the drawn bunny's top-left -> the widget's top-left
            return QPointF(left - mascot.pad_x, top - mascot.pad_top)
        middle_y = rect.center().y() - drawn_h / 2
        middle_x = rect.center().x() - drawn_w / 2
        below = at(middle_x, rect.bottom() + gap)
        right = at(rect.right() + gap, middle_y)
        left = at(rect.left() - gap - drawn_w, middle_y)
        above = at(middle_x, rect.top() - gap - drawn_h)
        order = (below, right, left, above) if rect.center().y() < self.window.height() / 3 else (right, left, below, above)
        limits = self.limits()
        card = QRectF(self.chat._home_rect())          # never behind her own chat card
        fits = [spot for spot in order if limits.contains(spot)]
        for spot in fits:
            if not card.intersects(QRectF(spot.x() + mascot.pad_x, spot.y() + mascot.pad_top, drawn_w, drawn_h)):
                return spot
        return fits[0] if fits else self._clamp(order[0])

    def drift_to(self, widget, then=None) -> bool:
        """Float over beside ``widget``; ``then`` runs on arrival. False when there is nowhere to go."""
        spot = self.spot_beside(widget)
        if spot is None:
            return False
        self.timer.stop()
        self.home_timer.stop()
        self.card_at = None                        # going to show a place: the card stays put
        self.undock()
        self.glide_to(spot, then=then)
        return True

    def glide_to(self, point: QPointF, then=None, clamp: bool = True):
        from ..design.ui_motion import reduced_motion
        end = self._clamp(point) if clamp else QPointF(point)
        self._glide_path = (QPointF(self.pos), end)
        self._glide_then = then
        self.glide.stop()
        distance = math.hypot(end.x() - self.pos.x(), end.y() - self.pos.y())
        self.glide.setDuration(1 if reduced_motion() else int(max(280, min(DRIFT_MS * 1.6, DRIFT_MS * distance / 700))))
        self.glide.setStartValue(0.0)
        self.glide.setEndValue(1.0)
        self.glide.start()

    def _glide_step(self, value):
        if self._glide_path is None:
            return
        start, end = self._glide_path
        k = float(value)
        lift = math.sin(k * math.pi) * min(60.0, math.hypot(end.x() - start.x(), end.y() - start.y()) * 0.15)
        self._place(QPointF(start.x() + (end.x() - start.x()) * k, start.y() + (end.y() - start.y()) * k - lift))
        if self.mascot is not None:
            self.mascot.stretch = 0.06 * math.sin(k * math.pi)
            self.mascot.update()

    def _glide_done(self):
        then, self._glide_then = self._glide_then, None
        self.carrier.rest()
        if self.mascot is not None:
            self.mascot.stretch = 0.0
            self.mascot.update()
        if then is not None:
            then()

    def close(self):
        self.timer.stop()
        self.glide.stop()
        self.home_timer.stop()
        self.shake.stop()
        if self.press is not None and self.mascot is not None:
            self.mascot.releaseMouse()
        self.glow.hide()
        self.carrier.hide()
        self.glow.deleteLater()
        self.carrier.deleteLater()


__all__ = ['BunnyPuck']
