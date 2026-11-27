"""兔白 off the chat card: picked up, thrown, landing, drifting to a place (2026-11-14, 2026-11-26).

User (2026-11-14): in 「问问兔白」 she should be draggable like the tutorial bunny — thrown, she
bounces off the window's edges (a glow where she hits, a little squash) — and she should float
over to the place she is talking about or working on.

2026-11-26 (user picked draft B 真实布偶, ``design/bunny_physics.py``): held anywhere she hangs
from that point and swings with the hand, upside down when held by a foot, in two links when
held by the key ring; thrown, gravity brings her down to the window's bottom, she bounces and
rolls, hops upright if she ended upside down, rests a moment and floats back beside the card.
Taps and hovers on her parts go to ``BunnyChat.touch`` (``app/bunny_touch.py``).

2026-11-26 (user, later): picked up, her card folds away (``BunnyChat.collapse``) so the user can
play with her; she stays where she lands with a small bubble over her head
(``app/bunny_head_bubble.py``), and a click on it brings the card back beside her.

2026-11-26 (user, later): the software opens with only the big 兔白, her card folded away; one
click on her opens it, and its own fold button folds it again without sending her away. Folded,
she rests where she is and now and then gets busy with the page's parts (``app/bunny_errands.py``);
put down on one of them she starts there. Only a card folded by carrying her comes back by itself.
While she rests, only her drawn body (not her roomy turning box) takes clicks.

On Windows the main window's pages are a native child window, so the carrier and the edge glow
are frameless tool windows above it (like the chat card and the tutorial); elsewhere children.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

FLASH_MS = 180
SHAKE_MS = 160
HIT_SPEED = 240.0            # px/s into an edge that gives feedback
REST_BEFORE_HOME_MS = 1200   # settled after a throw: a moment, then back to the card
# 2026-11-26 (user: a click picked her up, she always fell to the bottom and righted herself
# before the chat could go on, and any small move folded the card away):
GRAB_SLOP = 8                # a press that wobbles this little is a click, not a pick-up
FOLD_AFTER_PX = 180          # carried further than this from where she was picked up: the card folds away
PLACE_SPEED = 420.0          # let go slower than this (px/s) she is put down, not thrown: she stays there
SETTLE_MS = 2000             # put down (or landed) with the card folded: this long, then it comes back beside her
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
        self._mascot = None              # whose drawn body the resting mask follows
        self.bubble = None               # HeadBubble while her card is folded away
        self.place_bubble = None         # the puck's way of putting it over her head
        self.extra = QRect()             # what flies about her (bunny_overlay) also takes the layer
        self._resting = False            # the mask is her resting rectangle (rest()), not a moving box
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

    def _with_bubble(self, rect: QRect) -> QRect:
        bubble = self.bubble
        if bubble is not None and not bubble.isHidden() and not rect.isNull():
            rect = rect.united(bubble.geometry())
        if not self.extra.isNull() and not rect.isNull():
            rect = rect.united(self.extra)
        return rect

    def set_extra(self, rect: QRect):
        """Things flying about her (a book on its way to her paws, sparks) are drawn here too."""
        rect = QRect(rect)
        if rect == self.extra:
            return
        self.extra = rect
        if rect.isNull():
            return                       # the next rest() or move shrinks the mask again
        target = self._with_bubble(self._held)
        if not self._mask_rect.contains(target):
            self._set_mask_rect(self._mask_rect.united(target) if not self._mask_rect.isNull() else target)

    def bubble_changed(self):
        """The bubble was shown or resized: over her head again, and clicks on it must reach it."""
        if self.place_bubble is not None:
            self.place_bubble()
        target = self._with_bubble(self._held)
        if not target.isNull() and not self._mask_rect.contains(target):
            self._set_mask_rect(self._mask_rect.united(target) if not self._mask_rect.isNull() else target)

    def hold(self, mascot, at: QPoint, moving: bool = False):
        """Her widget's top-left at ``at`` (window coordinates); only near her do clicks stop here."""
        rect = QRect(at, mascot.size())
        if self._mascot is not mascot:
            mascot.on_animating = self._animating_changed
        self._mascot = mascot
        self._resting = False
        previous, self._held = self._held, rect
        mascot.move(at)
        target = self._with_bubble(rect)
        if not moving or previous.isNull():
            self._set_mask_rect(target)
        elif not self._mask_rect.contains(target):
            room = self.MOVE_ROOM
            self._set_mask_rect(target.adjusted(-room, -room, room, room).united(self._with_bubble(previous)))

    def _resting_rect(self) -> QRect:
        """Her drawn body (and what she holds) where she rests; her whole roomy box while she acts
        (a move, a sticker or a prop reaches past her standing body: 2026-11-27, it was cut off)."""
        mascot = self._mascot
        drawn = getattr(mascot, 'drawn_rect', None)
        if drawn is None or self._held.isNull():
            return self._held
        try:
            if mascot.animating():
                return QRect(self._held)
            return drawn().translated(self._held.topLeft()).intersected(self._held)
        except (RuntimeError, AttributeError):
            return self._held

    def _animating_changed(self, _animating: bool):
        if self._resting:
            self.rest()

    def rest(self):
        """She stopped: clicks stop only on her own body (and her bubble) again, so the controls
        around her stay usable (2026-11-26: she now rests out on the page by default)."""
        if not self._held.isNull():
            self._resting = True
            self._set_mask_rect(self._with_bubble(self._resting_rect()))


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
        from ..design.frame_clock import FrameTimer
        self._timer = FrameTimer(self, 16)
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
    """Owns 兔白 while she is off the card: held, flying, landing, righting, drifting, coming home.

    ``pos`` is where her card-sized box's top-left would be (window coordinates), as before: the
    card follows it, ``spot_beside`` and ``follow_bunny`` work in it. Her body (``phys.pose``) is
    her centre of mass, ``pos + com_off``; her widget is a roomy square ``mascot.room`` up and left.
    """

    def __init__(self, chat):
        from ..design.bunny_physics import BodyPhysics
        self.chat = chat
        self.window = chat.window_
        self.mascot = chat.mascot
        self.floating = chat.floating
        self.carrier = _Carrier(self.window, self.floating)
        self.carrier.place_bubble = self._place_bubble
        self.glow = _EdgeGlow(self.window, self.floating, chat.theme.accent)
        self.docked = True
        self.mode = 'docked'            # docked, held, fly, floor, rest, glide, walk (bunny_errands)
        self.walking = False            # bunny_errands moves her hop by hop
        self.placed_at = -1e9           # when the user last put her down (she then stays put a while)
        self.pos = QPointF()            # her card-sized top-left in window coordinates while off the card
        self.phys = BodyPhysics(self.mascot.scale if self.mascot is not None else 0.25)
        self.target = None              # where the pointer wants her while held
        self.history = []
        self.press = None
        self.started = 0.0
        self.last = time.perf_counter()
        self.hard_hits = 0
        self.shook = False
        from ..design.frame_clock import FrameTimer
        self.timer = FrameTimer(self.carrier, 16, motion=True)   # her body moves on the beat her picture is drawn
        self.timer.timeout.connect(self._step)
        self.home_timer = QTimer(self.carrier)
        self.home_timer.setSingleShot(True)
        self.home_timer.timeout.connect(self.go_home)
        self.floor_timer = QTimer(self.carrier)          # lying on the floor: crouch, then hop upright
        self.floor_timer.setSingleShot(True)
        self.floor_timer.timeout.connect(self._floor_beat)
        self.settle_timer = QTimer(self.carrier)         # put down with the card folded: the card comes back
        self.settle_timer.setSingleShot(True)
        self.settle_timer.timeout.connect(self._settled)
        self._floor_stage = 0
        self.glide = QVariantAnimation(self.carrier)
        self.glide.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.glide.valueChanged.connect(self._glide_step)
        self.glide.finished.connect(self._glide_done)
        self._glide_path = None
        self._glide_then = None
        self._glide_turn = 0.0
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
    @property
    def com_off(self) -> QPointF:
        return self.mascot.docked_com() if self.mascot is not None else QPointF()

    @property
    def velocity(self) -> QPointF:
        return QPointF(self.phys.vx, self.phys.vy)

    @velocity.setter
    def velocity(self, value: QPointF):
        """A throw from outside (the acceptance audit): she flies with this speed."""
        self.phys.vx, self.phys.vy = value.x(), value.y()
        self.phys.flight_s = 0.0
        self.phys.on_floor = False
        self.mode = 'fly'

    def home_point(self) -> QPointF:
        """Her place beside the card, in window coordinates."""
        chat = self.chat
        return QPointF(chat._home_rect().topLeft() + chat.mascot_slot)

    def limits(self) -> QRectF:
        """Where her card-sized top-left may go: the drawn bunny (not its margins) stays inside the window."""
        mascot = self.mascot
        size = mascot.docked_size()
        bottom = round(mascot.mascot_height * 0.06)
        m = 4
        top = m - mascot.pad_top
        return QRectF(m - mascot.pad_x, top, self.window.width() - size.width() + 2 * mascot.pad_x - 2 * m,
                      self.window.height() - size.height() + bottom - m - top)

    def _clamp(self, at: QPointF) -> QPointF:
        limits = self.limits()
        return QPointF(max(limits.left(), min(at.x(), limits.right())), max(limits.top(), min(at.y(), limits.bottom())))

    def _bounds(self) -> tuple:
        return 0.0, 0.0, float(self.window.width()), float(self.window.height())

    def window_point(self, rig_xy) -> QPointF:
        """Where the rig canvas point ``rig_xy`` is drawn now (upright, as she rests), in window coordinates."""
        mascot = self.mascot
        s = mascot.scale
        x, y = rig_xy
        if mascot.mirrored:
            x = 2 * mascot.MIRROR_X - x
        return QPointF(self.pos.x() + mascot.pad_x + (x - mascot.trim[0]) * s,
                       self.pos.y() + mascot.pad_top + (y - mascot.trim[1]) * s)

    def spot_for(self, rig_xy, at: QPointF, mirrored: bool = False) -> QPointF:
        """Her card-sized top-left that puts the rig canvas point ``rig_xy`` (upright) on ``at`` (window coordinates)."""
        mascot = self.mascot
        s = mascot.scale
        x, y = rig_xy
        if mirrored:
            x = 2 * mascot.MIRROR_X - x
        return QPointF(at.x() - mascot.pad_x - (x - mascot.trim[0]) * s, at.y() - mascot.pad_top - (y - mascot.trim[1]) * s)

    def _errands(self):
        return getattr(self.chat, 'errands', None)

    FEET = (455.0, 668.0)                    # rig canvas, under her shoes

    def set_bunny_height(self, height: int) -> bool:
        """2026-11-27 (user): smaller in Subtitle Studio. Her new size stands where her shoes were."""
        mascot = self.mascot
        height = int(height)
        if mascot is None or mascot.mascot_height == height:
            return False
        feet = None if self.docked else self.window_point(self.FEET)
        mascot.set_mascot_height(height)
        self.phys.pose.scale = mascot.scale
        if mascot.life is not None:
            mascot.life.rebase()
        if self.docked:
            self.chat.relayout()
            return True
        self.pos = self._clamp(self.spot_for(self.FEET, feet))
        self._sync_body(self.pos, 0.0)
        self.carrier.hold(mascot, (self.pos - mascot.room).toPoint())
        self._place(self.pos)
        self.carrier.rest()
        return True

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
            self._place_bubble()
            self.carrier.hold(self.mascot, (at - self.mascot.room).toPoint(), moving=self._moving())
            life = self.mascot.life
            if life is not None:
                from ..design.bunny_physics import Pose
                pose = self.phys.pose
                life.carried = Pose(pose.x, pose.y, pose.angle, pose.scale)
            self.mascot.update()

    # ------------------------------------------------------------ the bubble over her head
    def _bubble(self):
        bubble = self.carrier.bubble
        if bubble is None:
            from .bunny_head_bubble import HeadBubble
            bubble = HeadBubble(self.carrier, self.chat.theme, getattr(self.chat, 'family', ''))
            bubble.clicked.connect(self.chat.expand)
            self.carrier.bubble = bubble
        bubble.dots_when_idle = getattr(self.chat, 'fold_reason', 'carry') in ('carry', '')
        return bubble

    def bubble_line(self, text: str):
        """A few words over her head while the card is folded (keeps a waiting dot)."""
        bubble = self._bubble()
        bubble.raise_()
        bubble.show_line(text)
        self.carrier.bubble_changed()

    def note_bubble(self, lines, answer: bool):
        """She said ``lines`` while the card is folded: a short one shows, a longer one leaves a dot."""
        bubble = self._bubble()
        bubble.raise_()
        bubble.note(lines, answer)
        self.carrier.bubble_changed()

    def show_bubble(self, shown: bool):
        """Her card folded away (shown) or back (hidden): the little bubble over her head."""
        bubble = self.carrier.bubble
        if shown:
            bubble = self._bubble()
            bubble.reset()
            bubble.show()
            bubble.raise_()
        elif bubble is not None:
            bubble.reset()
            bubble.hide()
        self.carrier.bubble_changed()
        if not shown:
            self.carrier.rest()

    def _place_bubble(self):
        """Just above her ears, a little to the right, from where her body is now; inside the window."""
        bubble = self.carrier.bubble
        mascot = self.mascot
        if bubble is None or bubble.isHidden() or mascot is None:
            return
        size = mascot.docked_size()
        drawn_w = size.width() - 2 * mascot.pad_x
        pose = self.phys.pose
        head_top = pose.y - (self.com_off.y() - mascot.pad_top)
        size = bubble.sizeHint()
        x = pose.x + drawn_w * 0.12 - 9
        y = head_top - size.height() + 6
        x = max(2.0, min(x, self.window.width() - size.width() - 2.0))
        y = max(2.0, min(y, self.window.height() - size.height() - 2.0))
        bubble.setGeometry(round(x), round(y), size.width(), size.height())

    def _moving(self) -> bool:
        return self.walking or self.timer.isActive() or self.glide.state() == QVariantAnimation.State.Running

    def _sync_body(self, at: QPointF, angle: float | None = None):
        """Her body follows ``at`` (a card-sized top-left), e.g. while gliding."""
        pose, com = self.phys.pose, self.com_off
        pose.x, pose.y = at.x() + com.x(), at.y() + com.y()
        if angle is not None:
            pose.angle = angle

    # ------------------------------------------------------------ on and off the card
    def undock(self):
        if not self.docked or self.mascot is None:
            return
        self.home_timer.stop()
        start = self.home_point()
        self.docked = False
        self.chat.mascot_docked = False
        self.mascot.set_roomy(True)
        self.phys.pose.scale = self.mascot.scale
        self.phys.vx = self.phys.vy = self.phys.spin = 0.0
        self._sync_body(start, 0.0)
        if self.mascot.life is not None:
            self.mascot.life.rebase()
        # 2026-11-18: the layer is shown (already masked to her place) before she moves onto it,
        # and its native window exists since the chat opened, so there is no gap where she is on
        # neither the card nor the layer.
        self.carrier.cover()
        self.carrier.hold(self.mascot, (start - self.mascot.room).toPoint())
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
        self.floor_timer.stop()
        self.settle_timer.stop()
        self.card_at = None
        if self.docked or self.mascot is None:
            return
        if self.chat.collapsed:                    # never into a card that is folded away
            self.chat.expand(dock=False)
        if self.press is not None:
            self.mascot.releaseMouse()
            self.press = None
        self.mode = 'docked'
        self.mascot.stretch = 0.0
        life = self.mascot.life
        if life is not None:
            life.carried = None
            life.struggling = False
            life.squash_goal = (0.0, None, (0.0, 0.0))
            life.rebase()
        self.mascot.set_roomy(False)
        self.mascot.setParent(self.chat)
        self.mascot.show()
        self.mascot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.docked = True
        self.chat.mascot_docked = True
        self.carrier.hide()
        self.chat.relayout()

    def go_home(self):
        """Float back beside the card, then dock. While the card is folded away she stays put."""
        if self.docked or self.chat.collapsed:
            return
        self.card_at = None                        # the card waits where it is; she floats to it
        self.glide_to(self.home_point(), then=self.dock, clamp=False)

    # ------------------------------------------------------------ the pointer
    def _touch(self):
        return getattr(self.chat, 'touch', None)

    def mouse(self, event) -> bool:
        """The mascot's mouse events (from the chat's event filter); True when used."""
        from PySide6.QtCore import QEvent
        from ..design.bunny_physics import region_at
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            # 2026-11-19: the pointer in window coordinates, read in physical pixels (floating_anchor):
            # with screens at different scales the event's own position jumped as she crossed an edge.
            from . import floating_anchor
            pointer = floating_anchor.Pointer(self.window, self.mascot, event)
            point = pointer.at(event)
            local = self.mascot.rig_point(QPointF(event.position()))
            region = region_at(*local)
            caught = not self.docked and self.mode in ('fly', 'glide', 'walk')
            errands = self._errands()
            if errands is not None and errands.busy():
                errands.interrupt()                # busy with a part of the page: she drops it for the user
            if region is None and not caught:
                if not self.docked:
                    return True                    # the clear corners of her roomy box
                region = 'face'
            self.timer.stop()
            self.glide.stop()
            self.home_timer.stop()
            self.floor_timer.stop()
            self.settle_timer.stop()
            touch = self._touch()
            if region in ('earL', 'earR') and not caught and touch is not None:
                self.press = dict(start=point, grab=local, region=region, moved=False, pointer=pointer, tug=True)
                touch.start_tug(region, QPointF(event.position()))
                return True
            self.press = dict(start=point, grab=local, region=region, moved=caught, pointer=pointer, tug=False)
            if caught:
                self._hold(point)
            return True
        if kind == QEvent.Type.MouseMove and self.press is not None:
            point = self.press['pointer'].at(event)
            if self.press['tug']:
                tip = self._touch().update_tug(QPointF(event.position()))
                if tip is None:
                    return True
                self.press.update(tug=False, moved=True, grab=tip, region='ear')   # pulled too far: held by the ear
                self._hold(point)
                return True
            if not self.press['moved']:
                delta = point - self.press['start']
                if abs(delta.x()) + abs(delta.y()) < GRAB_SLOP:
                    return True
                self.press['moved'] = True
                self._hold(point)
            self.target = point
            return True
        if kind == QEvent.Type.MouseButtonRelease and self.press is not None:
            press, self.press = self.press, None
            if press['tug']:
                self._touch().end_tug()
                return True
            if not press['moved']:
                if self.chat.collapsed:
                    # 2026-11-26 (user): folded away, one click on her opens the dialog box beside her.
                    self.mascot.hop()
                    self.carrier.rest()
                    self.chat.expand()
                    return True
                touch = self._touch()
                if touch is not None:
                    touch.click(press['region'])
                else:
                    self.chat.poke()
                if not self.docked:
                    self.carrier.rest()
                    self.home_timer.start(REST_BEFORE_HOME_MS)
                return True
            self._throw()
            return True
        return False

    def _hold(self, point: QPointF):
        # 2026-11-26 (user): picked up, her card comes along while she is moved a little; carried
        # further (FOLD_AFTER_PX, see _step) it folds away, and the bubble over her head or putting
        # her down brings it back where she is (BunnyChat.expand).
        self.card_at = None
        self.undock()
        if not self.chat.collapsed:
            self.card_at = QPointF(self.pos)
        life = self.mascot.life
        if life is not None:
            life.struggling = True
        else:
            self.mascot.play('struggle')            # A17: little feet kicking while she dangles
        self.hard_hits = 0
        self.mascot.grabMouse()                    # the press's hold, kept across the reparenting
        self.mascot.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.phys.grab(self.press['grab'], (point.x(), point.y()), link=self.press['region'] == 'ring')
        self.mode = 'held'
        self._sfx('catch' if self.press['region'] == 'ring' else 'grab')   # by her ring the keychain rings
        self.history = [(time.perf_counter(), QPointF(self.phys.pose.x, self.phys.pose.y))]
        self.target = QPointF(point)                               # ``point`` is in window coordinates
        self.last = time.perf_counter()
        touch = self._touch()
        if touch is not None:
            touch.picked_up(self.press['region'] == 'ring')
        self.timer.start()

    def _throw(self):
        from ..design.ui_motion import reduced_motion
        self.mascot.releaseMouse()
        self.mascot.stop_move('struggle')
        if self.mascot.life is not None:
            self.mascot.life.struggling = False
        self.mascot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.target = None
        # 2026-11-26: the card stays where she was let go. With gravity she always ends at the
        # window's bottom; carrying her is still how the user places the card, so it does not fall too.
        carried = self.card_at is not None
        self.card_at = None
        now = time.perf_counter()
        recent = [(t, p) for t, p in self.history if now - t <= 0.09] or self.history[-1:]
        (t0, p0), (t1, p1) = recent[0], self.history[-1]
        velocity = (p1 - p0) / max(t1 - t0, 0.012) if now - t1 < 0.12 else QPointF()
        if reduced_motion():
            velocity = QPointF()
        if math.hypot(velocity.x(), velocity.y()) < PLACE_SPEED:
            self.placed_at = time.monotonic()
            self._put_down(carried)
            return
        self.shook = self.phys.release((velocity.x(), velocity.y()))
        self.started = now
        self.last = now
        if reduced_motion():
            self._rest()
            return
        self.mode = 'fly'
        self._sfx('whee')
        self.timer.start()

    # ------------------------------------------------------------ held and flying
    def _step(self):
        from ..design.bunny_physics import GRAVITY, GRAVITY_FLY, IMPACT_SQUASH, STEP, squash_target
        mascot = self.mascot
        if self.docked or mascot is None or not self.carrier.isVisible() or self.window.isMinimized():
            self.timer.stop()
            return
        now = time.perf_counter()
        dt = min(0.04, max(0.001, now - self.last))
        self.last = now
        steps = max(1, math.ceil(dt / STEP))
        h = dt / steps
        bounds = self._bounds()
        phys = self.phys
        hits = []
        if self.mode == 'held' and self.target is not None:
            for _ in range(steps):
                phys.step_held(h, (self.target.x(), self.target.y()), bounds)
        elif self.mode == 'fly':
            for _ in range(steps):
                hits += phys.step_fly(h, bounds)
                if phys.stopped():
                    break
        else:
            self.timer.stop()
            return
        life = mascot.life
        hand = phys.hold.hand if phys.hold is not None else None
        if life is not None:
            life.squash_goal = squash_target(self.mode, phys.vx, phys.vy, hand, phys.pose)
            life.gravity = GRAVITY_FLY if self.mode == 'fly' else GRAVITY
        com = self.com_off
        self._place(QPointF(phys.pose.x - com.x(), phys.pose.y - com.y()))
        if self.mode == 'held':
            self._fold_if_far()
            self.history = [(t, p) for t, p in self.history if now - t < 0.14] + [(now, QPointF(phys.pose.x, phys.pose.y))]
            touch = self._touch()
            if touch is not None:
                touch.while_held(phys)
            return
        for side, speed, x, y in sorted(hits, key=lambda hit: hit[1], reverse=True)[:1]:
            if speed >= HIT_SPEED:
                power = max(0.3, min(1.0, speed / 2200.0))
                self.hard_hits += 1 if power > 0.45 else 0
                if life is not None:
                    axis = 0.0 if side in ('left', 'right') else math.pi / 2
                    life.squash.kick(axis, IMPACT_SQUASH * power * 14, (x - phys.pose.x, y - phys.pose.y), mascot.clock())
                else:
                    mascot.stretch = -0.22 * power if side in ('top', 'bottom') else 0.15 * power
                self._edge_hit(side, power)
        if phys.stopped():
            self._landed()

    def _fold_if_far(self):
        """Carried far from where she was picked up, her card folds away; a small move keeps it."""
        if self.card_at is None or self.press is None or self.target is None:
            return
        from . import ui_zoom
        moved = self.target - self.press['start']
        if math.hypot(moved.x(), moved.y()) > ui_zoom.px(FOLD_AFTER_PX):
            self.card_at = None
            self.chat.collapse()

    def _put_down(self, carried: bool):
        """Let go gently: she stays where she was put, upright, instead of falling to the bottom.
        Her card came along: she steps back onto it. It was folded away: it comes back beside her
        after a moment (SETTLE_MS)."""
        self.phys.release((0.0, 0.0))
        self.phys.vx = self.phys.vy = self.phys.spin = 0.0
        self._sfx('plop')
        self.shook = False
        self.hard_hits = 0
        life = self.mascot.life
        if life is not None:
            from ..design.bunny_physics import GRAVITY
            life.squash_goal = (0.0, None, (0.0, 0.0))
            life.gravity = GRAVITY
        self.glide_to(self.pos, then=self.go_home if carried else self._stay_here)

    def _stay_here(self):
        self.mode = 'rest'
        self.carrier.rest()
        if self.chat.collapsed:
            self._folded_rest(put_down=True)
        else:
            self.home_timer.start(REST_BEFORE_HOME_MS)

    def _folded_rest(self, put_down: bool = False):
        """Put down or landed with the card folded: put down on a gear, the book or a seat she gets busy
        there; a card folded only because she was carried comes back after a moment."""
        errands = self._errands()
        if put_down and errands is not None and errands.landed():
            return
        if errands is not None:
            errands.after_landing(thrown=not put_down)
        if getattr(self.chat, 'fold_reason', 'carry') == 'carry':
            self.settle_timer.start(SETTLE_MS)

    def _settled(self):
        """She has stayed put a moment: her card comes back beside her, where she is."""
        if self.docked or not self.chat.collapsed or self.mode not in ('rest', 'docked') or self.press is not None:
            return
        if getattr(self.chat, 'fold_reason', 'carry') != 'carry':
            return                                 # folded by the user (or at start): it stays folded
        errands = self._errands()
        if errands is not None and errands.busy():
            return
        self.chat.expand()

    def _sfx(self, name: str, **options) -> None:
        """2026-11-27: a sound for what just happened to her (bunny_sfx; silent when muted)."""
        from .bunny_sfx import play
        play(self.chat, name, **options)

    def _landed(self):
        self.timer.stop()
        self._sfx('land')
        phys = self.phys
        if phys.righting:
            phys.righting = False
            self._rest()
        elif phys.lying() and phys.flight_s <= 14:
            self.mode = 'floor'
            self._floor_stage = 0
            self.floor_timer.start(450)
        else:
            self._rest()

    def _floor_beat(self):
        """Lying on the floor: a crouch first, then the hop that turns her upright."""
        life = self.mascot.life if self.mascot is not None else None
        if self.mode != 'floor':
            return
        if self._floor_stage == 0:
            self._floor_stage = 1
            if life is not None:
                life.squash.kick(math.pi / 2, 2.2, (0.0, self.phys.radius()), self.mascot.clock())
            self.floor_timer.start(160)
            return
        self.phys.hop_upright()
        self._sfx('hop')
        self.mode = 'fly'
        self.last = time.perf_counter()
        touch = self._touch()
        if touch is not None:
            touch.hopping_up()
        self.timer.start()

    def _rest(self):
        self.mode = 'rest'
        self.phys.vx = self.phys.vy = self.phys.spin = 0.0
        self.carrier.rest()
        life = self.mascot.life
        if life is not None:
            from ..design.bunny_physics import GRAVITY
            life.squash_goal = (0.0, None, (0.0, 0.0))
            life.gravity = GRAVITY
        self.mascot.stretch = 0.0
        self.mascot.update()
        if self.hard_hits >= 3 or self.shook:       # A11: thrown about or shaken too hard, she is dizzy
            self.mascot.act('dizzy')
        self.hard_hits = 0
        self.shook = False
        if self.chat.collapsed:
            self._folded_rest()                      # 2026-11-26: landed, busy there or the card comes back
        else:
            self.home_timer.start(REST_BEFORE_HOME_MS)

    def _edge_hit(self, side: str, power: float):
        mascot = self.mascot
        com = QPointF(self.phys.pose.x, self.phys.pose.y)
        if side in ('top', 'bottom'):
            x, y = com.x(), (0.0 if side == 'top' else float(self.window.height()))
        else:
            x, y = (0.0 if side == 'left' else float(self.window.width())), com.y()
        self.glow.show_hit(x, y, power, side, self.window.rect(), self.floating, self.window)
        self._sfx('bonk', volume=.55 + .45 * power)
        self.carrier.raise_()
        self.chat._spoke('呜', 'surprised')
        now = time.perf_counter()
        if mascot.life is None and now - self._last_impact > 0.18 and self.shake.state() != QVariantAnimation.State.Running:
            self._last_impact = now
            self._shake_power = power
            self._shake_dir = {'left': QPointF(-1, 0), 'right': QPointF(1, 0), 'top': QPointF(0, -1),
                               'bottom': QPointF(0, 1)}[side]
            self.shake.start()
        touch = self._touch()
        if touch is not None:
            touch.bumped(power)

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
        size = mascot.docked_size()
        drawn_w = size.width() - 2 * mascot.pad_x
        drawn_h = size.height() - mascot.pad_top
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
        self.floor_timer.stop()
        self.card_at = None                        # going to show a place: the card stays put
        self.undock()
        self.glide_to(spot, then=then)
        return True

    def glide_to(self, point: QPointF, then=None, clamp: bool = True):
        from ..design.bunny_physics import wrap
        from ..design.ui_motion import reduced_motion
        end = self._clamp(point) if clamp else QPointF(point)
        self._glide_path = (QPointF(self.pos), end)
        self._glide_then = then
        self._glide_turn = wrap(self.phys.pose.angle)
        self.mode = 'glide'
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
        at = QPointF(start.x() + (end.x() - start.x()) * k, start.y() + (end.y() - start.y()) * k - lift)
        self._sync_body(at, self._glide_turn * (1 - k))
        self._place(at)
        if self.mascot is not None and self.mascot.life is None:
            self.mascot.stretch = 0.06 * math.sin(k * math.pi)
            self.mascot.update()

    def _glide_done(self):
        then, self._glide_then = self._glide_then, None
        self.mode = 'rest'
        self.phys.pose.angle = 0.0
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
        self.settle_timer.stop()
        self.floor_timer.stop()
        self.shake.stop()
        if self.press is not None and self.mascot is not None:
            self.mascot.releaseMouse()
        self.glow.hide()
        self.carrier.hide()
        self.glow.deleteLater()
        self.carrier.deleteLater()


__all__ = ['BunnyPuck']
