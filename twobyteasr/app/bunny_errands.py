"""兔白 busy with the software's own parts while her dialog box is folded away (2026-11-26).

User (2026-11-26): with the dialog box folded away she should do more — play with the software's
parts and animate with them, so she feels like a real character: really take a wrench to the AI
settings gear, really read the term library's book, play on the page's elements.

Round 2, the same night (user): the first errands were not smooth — she seemed to jump to the
place and jump back; before using a button she must plainly do something with it, so one sees
she took the book out of it; the gear fix looked odd and never landed; a dozen more actions that
really affect the buttons (crooked, shaking); and on the home page she may wander to new places,
but in Subtitle Studio she stays where she is.

So now:

* She moves hop by hop (``Hop``: take-off, a little arc, a squash on landing, ears and feet
  bouncing; about 60 px a hop) or with one jump (``Leap``: crouch, arc, landing) — never a
  sudden glide across the page.
* What she does to a button shows on the button (``design.bunny_button_fx``): it rattles, goes
  crooked, jolts at each hit, squashes under her, swings while she hangs on it, springs back with
  a wobble. Borrowed things fly between the button and her paws (``bunny_overlay``).
* Errands (each a generator of steps): fix_gear, read_book, push, tug, stomp, knock, flick,
  tickle, polish, domino, lift, blow, lean_nap, sit_on, hang_on — and ``wander`` on the home page.

When: with the card folded by the user (or at start), now and then when she rests, the software is
in front, the user has not clicked or typed for a moment and nothing is in the way (a dialog, a
menu, the tutorial, an answer on its way, her dozing). Never in Subtitle Studio. Put down by the
user, she does not wander off for a while; put down gently on a gear, the book, a header button
or a seat she starts the matching errand there. A press on her, a page change or the window
resizing stops an errand where it is; borrowed icons go back and the buttons spring back.

Round 3 (2026-11-27, user): more to do in 模型工坊; in the project library (工程库) she hops from
project to project; in Subtitle Studio's editor she must keep clear of the timeline and other
important places — smaller, strolling about, or asleep at the bottom or top of the subtitle list
or the tool panel — so she seems really there. So the errands depend on where she is
(``context``): home / workshop / hub (the studio's project library) / editor. In the editor she
turns smaller with a little spin (``resize``), then only naps in the corners of the subtitle list
and the tool panel (``nap``), moving between them now and then; never over the timeline or the
picture. Out of the editor she grows back. ``card_hop`` (cards of the library, the workshop's
model cards, the home page's cards) and ``inspect`` (a model card under her magnifier) are new.

Round 4 (2026-11-27, user): waiting ten or twenty seconds before she did anything was too long — she
should be lively from the moment she appears. And the pointer: her eyes already follow it; when it
rushes past over her head she leaps up like a cat to catch it, and when it rests on a button near
her she pounces on that button — often enough that people find out she can. So: the first errand
comes after 2.5–4.5 s and the next every 7–14 s; between them she fidgets every few seconds (a
look round, an ear, a little hop, a step or two); ``_watch`` samples the pointer 30 times a second
(``pounce``). None of this in the studio's editor, where she naps.

Everything here runs on ``self.clock`` (``tick``), the mascot's moves on ``mascot.clock`` — a
review replaces both and renders exact frames (``tmp/bunny-roam-20261126/demo.py``). Nothing is
clicked and nothing is sent to the AI.
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget

FIRST_S = (2.5, 4.5)          # after she appears (or her card folds away), the first errand
GAP_S = (7.0, 14.0)           # between errands
FIDGET_S = (2.2, 4.5)         # between little fidgets while she waits for the next errand
WATCH_MS = 33                 # the pointer is looked at this often while she stands folded
POUNCE_SPEED = 650.0          # px/s of the pointer over her head that makes her leap for it
# 2026-11-27 (user: she jumped every time the pointer crossed her head; it should be now and then):
# a quick pass over her head makes her leap only with POUNCE_CHANCE, and at most every POUNCE_GAP_S;
# the other passes she only notices (ears up, a look).
POUNCE_CHANCE = 0.3
POUNCE_GAP_S = 12.0
POUNCE_REACH = 260.0          # px she can leap from where she stands
POUNCE_DROP = 20.0            # px below where she stands she may land
CATCH_RADIUS = 56.0           # px from her raised paws to the pointer: caught
DANGLE_S = (2.6, 4.2)         # caught, she hangs on the pointer this long
NOTICE_GAP_S = 3.0
SWAT_HOVER_S = 0.6            # the pointer resting this long on a button near her ...
SWAT_CHANCE = 0.35            # ... makes her pounce on it now and then,
SWAT_GAP_S = 18.0             # ... at most this often
MISCHIEF_S = 10.0             # thrown about, she is up to mischief for this long after landing
SWAT_REACH = 300.0            # px from her body to the button
INPUT_QUIET_S = 2.5           # no click, key or wheel this long before she sets off
PLACED_QUIET_S = 120.0        # put down by the user, she does not wander off for this long
WANDER_SHARE = 0.3            # how often (on the home page) it is a walk to a new place
CHECK_MS = 600
FRAME_MS = 16
PACE = 1.0                    # every duration is this many times as long (tests run them fast)
HOP_PX = 62.0                 # one hop's length
HOP_S = 0.30                  # one hop in the air ...
LAND_S = 0.07                 # ... and the moment on the ground before the next
MAX_HOPS = 12
# Points on her rig canvas (bunny_mascot / rig.json).
FEET = (455.0, 668.0)         # under her shoes
SEAT = (458.0, 652.0)         # where she sits on a ledge (her shoes hang over its edge)
RING = (452.0, 14.0)          # the top of her key ring
PAWS = (458.0, 612.0)
BOOK_AT = (458.0, 628.0)      # the book in her paws
PAW_FRONT = (524.0, 612.0)    # the front edge of her right paw
LIFT_TOP = (458.0, 404.0)     # her paws held over her head ('lift')
HEADER_BUTTONS = ('support_button', 'update_button', 'subtitle_studio_button', 'model_workshop_button',
                  'recognition_history_button', 'return_recognition_button', 'ask_bunny_button',
                  'app_settings_button')
# Gears she can mend, in order: the AI card's 「AI 设置」, the home page's 「高级设置」, the header's 「设置」.
GEARS = ('ai_settings_button', 'home_task_settings_button', 'app_settings_button')
SEATS = ('start_button', 'media_frame', 'studio_recent_hero', 'home_process_card', 'add_glossary_button',
         'home_task_settings_button')
HOME_PAGE, STUDIO_PAGE, WORKSHOP_PAGE = '首页', '字幕工作台', '模型工坊'
SMALL_HEIGHT = 96             # her height in the studio's editor (logical px at 100 %)
NAP_S = (22.0, 42.0)          # one nap in a corner of the editor
EDITOR_QUIET_S = 1.0          # in the editor she may go to a corner even while the user works
ONE_BUTTON = ('push', 'tug', 'knock', 'flick', 'tickle', 'polish', 'lift', 'blow', 'lean_nap')


def _say(text: str) -> str:
    from ..i18n import ui_literal
    return ui_literal(text)


def _visible(widget) -> bool:
    try:
        return widget is not None and widget.isVisible() and widget.width() > 4 and widget.height() > 4
    except RuntimeError:
        return False


def _ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


def icon_centre(button, window) -> QPoint:
    """Where a button's icon is drawn (its content is centred: icon, a gap, the text), in window coordinates."""
    size = button.iconSize()
    text = button.text() if hasattr(button, 'text') else ''
    text_w = button.fontMetrics().horizontalAdvance(text) if text else 0
    total = size.width() + (6 if text_w else 0) + text_w
    x = round(button.width() / 2 - total / 2 + size.width() / 2)
    return button.mapTo(window, QPoint(x, button.height() // 2))


# ---------------------------------------------------------------------- steps
class Step:
    seconds = 0.0

    def start(self, now: float):
        self.t0 = now

    def update(self, now: float) -> bool:
        return now - self.t0 >= self.seconds * PACE

    def stop(self):
        pass


class Wait(Step):
    def __init__(self, seconds: float):
        self.seconds = float(seconds)


class Beats(Step):
    """``count`` beats of ``period`` s; ``on_beat(i)`` at ``phase`` of each (the moment a paw lands)."""

    def __init__(self, count: int, period: float, phase: float, on_beat):
        self.count, self.period, self.phase, self.on_beat = int(count), float(period), float(phase), on_beat
        self.fired = 0

    def update(self, now: float) -> bool:
        elapsed = (now - self.t0) / PACE
        while self.fired < self.count and elapsed >= (self.fired + self.phase) * self.period:
            index, self.fired = self.fired, self.fired + 1
            self.on_beat(index)
        return elapsed >= self.count * self.period


class _Move(Step):
    """Shared by Hop and Leap: she is out of 'rest' while moving, and lands softly."""

    def __init__(self, errands, to: QPointF, face: bool = True):
        self.e, self.to, self.face = errands, QPointF(to), face

    def _begin(self):
        puck, mascot = self.e.puck, self.e.mascot
        self.a = QPointF(puck.pos)
        self.b = puck._clamp(QPointF(self.to))
        dx = self.b.x() - self.a.x()
        if self.face and abs(dx) > 6:
            mascot.mirrored = dx < 0
        puck.walking = True
        puck.mode = 'walk'
        puck.timer.stop()
        puck.glide.stop()
        puck.home_timer.stop()
        puck.settle_timer.stop()

    def _place(self, at: QPointF, angle: float = 0.0):
        puck = self.e.puck
        puck._sync_body(at, angle)
        puck._place(at)

    def _land(self, power: float):
        mascot, puck = self.e.mascot, self.e.puck
        life = mascot.life
        if life is not None:
            life.squash.kick(math.pi / 2, power, (0.0, puck.phys.radius()), mascot.clock())

    def _end(self):
        puck, mascot = self.e.puck, self.e.mascot
        self._place(self.b)
        mascot.stretch = 0.0
        puck.walking = False
        if puck.mode == 'walk':
            puck.mode = 'rest'
        puck.carrier.rest()
        return True

    def stop(self):
        puck, mascot = self.e.puck, self.e.mascot
        mascot.stretch = 0.0
        if mascot.current_move == 'trot':
            mascot.stop_move('trot')
        puck.walking = False
        if puck.mode == 'walk':
            puck.mode = 'rest'
            puck.carrier.rest()


class Hop(_Move):
    """Hop by hop from where she is to ``to`` (card-sized top-left, window coordinates)."""

    def __init__(self, errands, to: QPointF, trot: bool = True, face: bool = True, height: float | None = None,
                 hops: int | None = None):
        super().__init__(errands, to, face)
        self.trot, self.height, self.hops = trot, height, hops

    def start(self, now: float):
        super().start(now)
        self._begin()
        from . import ui_zoom
        d = math.hypot(self.b.x() - self.a.x(), self.b.y() - self.a.y())
        unit = ui_zoom.px(HOP_PX)
        self.n = 0 if d < 3 else (self.hops or max(1, min(MAX_HOPS, round(d / unit))))
        leg = d / self.n if self.n else 0.0
        self.air = HOP_S * (.85 + .3 * min(1.6, leg / unit)) * PACE
        self.rest = LAND_S * PACE
        self.h = self.height if self.height is not None else min(64.0, 9 + .3 * leg)
        self.last = -1
        if self.trot and self.n:
            self.e.mascot.play('trot')

    def update(self, now: float) -> bool:
        if not self.n:
            return self._end()
        cycle = self.air + self.rest
        elapsed = now - self.t0
        index = int(elapsed // cycle)
        if index >= self.n:
            self._land(1.6)
            self.e._sfx('plop', volume=.7)
            if self.trot:
                self.e.mascot.stop_move('trot')
            return self._end()
        if index != self.last:
            if self.last >= 0:
                self._land(1.1)
            self.last = index
            self.e._sfx('hop')                    # 2026-11-27: a light "pyon" at every hop
        u = (elapsed - index * cycle) / self.air
        air = min(1.0, u)
        f = .5 - .5 * math.cos(math.pi * air)
        k = (index + f) / self.n
        at = QPointF(self.a.x() + (self.b.x() - self.a.x()) * k, self.a.y() + (self.b.y() - self.a.y()) * k)
        lift = self.h * math.sin(math.pi * air) if u <= 1 else 0.0
        mascot = self.e.mascot
        mascot.stretch = .07 * math.sin(math.pi * air) if u <= 1 else -.09
        direction = 1 if self.b.x() >= self.a.x() else -1
        self._place(QPointF(at.x(), at.y() - lift), .06 * direction * math.sin(math.pi * air) if u <= 1 else 0.0)
        return False


class Chase(_Move):
    """A leap that homes in: ``aim()`` (card-sized top-left, window coordinates) is asked on every
    frame and where she will come down follows it, eased, so she follows the pointer in the air.
    It ends up in the air at the aim (no landing): a Dangle or a Leap down comes after."""

    FOLLOW = 14.0                 # 1/s: how quickly where she is heading follows the aim

    def __init__(self, errands, aim, height: float = 18.0, crouch: float = .12):
        super().__init__(errands, aim(), face=False)
        self.aim, self.height, self.crouch_s = aim, height, crouch

    def start(self, now: float):
        super().start(now)
        self._begin()
        self.goal = QPointF(self.b)
        self.last = now
        d = math.hypot(self.b.x() - self.a.x(), self.b.y() - self.a.y())
        self.crouch = self.crouch_s * PACE
        self.fly = (.36 + min(.3, d / 1400)) * PACE

    def update(self, now: float) -> bool:
        mascot, puck = self.e.mascot, self.e.puck
        dt = max(0.0, min(.05, now - self.last))
        self.last = now
        try:
            wanted = puck._clamp(QPointF(self.aim()))
        except RuntimeError:
            wanted = self.goal
        k = 1 - math.exp(-self.FOLLOW * dt / max(1e-3, PACE))
        self.goal = QPointF(self.goal.x() + (wanted.x() - self.goal.x()) * k,
                            self.goal.y() + (wanted.y() - self.goal.y()) * k)
        elapsed = now - self.t0
        if elapsed < self.crouch:
            mascot.stretch = -.16 * _ease(elapsed / max(1e-6, self.crouch))
            self.b = QPointF(self.goal)
            self._place(self.a)
            return False
        if not getattr(self, 'sprung', False):
            self.sprung = True
            self.e._sfx('pounce')
        u = min(1.0, (elapsed - self.crouch) / self.fly)
        # Where she comes down follows the aim, less and less as she arrives (no snapping at the end).
        self.b = QPointF(self.goal)
        e = u * u * (3 - 2 * u)
        x = self.a.x() + (self.b.x() - self.a.x()) * e
        y = self.a.y() + (self.b.y() - self.a.y()) * e - self.height * 4 * u * (1 - u)
        if abs(self.b.x() - self.a.x()) > 8:
            mascot.mirrored = self.b.x() < self.a.x()
        mascot.stretch = .12 * max(0.0, 1 - 2.5 * u)
        direction = 1 if self.b.x() >= self.a.x() else -1
        self._place(QPointF(x, y), .14 * direction * math.sin(math.pi * u))
        if u >= 1:
            mascot.stretch = 0.0
            return True                   # still in the air, still 'walk': the next step takes over
        return False

    def stop(self):
        super().stop()


class Dangle(Step):
    """Caught the pointer: she hangs from it by her raised paws, swinging as it moves (the same
    physics as being carried), for ``seconds``; then she lets go and drops with the swing she has."""

    def __init__(self, errands, seconds: float):
        self.e, self.seconds = errands, float(seconds)
        self.released = False

    def start(self, now: float):
        super().start(now)
        puck, mascot = self.e.puck, self.e.mascot
        grip = puck.window_point(LIFT_TOP)
        puck.walking = False
        puck.timer.stop()
        puck.phys.grab(LIFT_TOP, (grip.x(), grip.y()), link=False)
        puck.mode = 'held'
        puck.target = self.e._cursor_point()
        puck.history = [(time.perf_counter(), QPointF(puck.phys.pose.x, puck.phys.pose.y))]
        puck.last = time.perf_counter()
        if mascot.life is not None:
            mascot.life.struggling = True       # her feet kick while she hangs
        self.e._sfx('catch')
        puck.timer.start()

    def update(self, now: float) -> bool:
        puck = self.e.puck
        if puck.mode != 'held' or puck.press is not None:
            self.released = True                # the user took her (or something else did)
            return True
        point = self.e._cursor_point()
        if not self.e.window.rect().adjusted(8, 8, -8, -8).contains(point.toPoint()):
            self.stop()                         # the pointer left the window: she cannot follow
            return True
        puck.target = point
        if now - self.t0 >= self.seconds:          # real seconds: how long she hangs on
            self.stop()
            return True
        return False

    def stop(self):
        if self.released:
            return
        self.released = True
        puck, mascot = self.e.puck, self.e.mascot
        if puck.mode != 'held' or puck.press is not None:
            return
        if mascot.life is not None:
            mascot.life.struggling = False
        now = time.perf_counter()
        recent = [(t, p) for t, p in puck.history if now - t <= 0.09] or puck.history[-1:]
        (t0, p0), (t1, p1) = recent[0], puck.history[-1]
        velocity = (p1 - p0) / max(t1 - t0, 0.012) if now - t1 < 0.12 else QPointF()
        speed = math.hypot(velocity.x(), velocity.y())
        if speed > 1400:
            velocity = velocity * (1400 / speed)
        puck.target = None
        puck.shook = puck.phys.release((velocity.x(), velocity.y()))
        puck.started = puck.last = now
        puck.mode = 'fly'
        puck.timer.start()


class Leap(_Move):
    """One jump: a crouch, an arc to ``to``, a landing (``on_land`` runs as she touches down)."""

    def __init__(self, errands, to: QPointF, height: float | None = None, crouch: float = .16, on_land=None,
                 face: bool = True):
        super().__init__(errands, to, face)
        self.height, self.crouch_s, self.on_land = height, crouch, on_land

    def start(self, now: float):
        super().start(now)
        self._begin()
        d = math.hypot(self.b.x() - self.a.x(), self.b.y() - self.a.y())
        self.crouch = self.crouch_s * PACE
        self.fly = (.40 + min(.4, d / 1500)) * PACE
        self.h = (self.height if self.height is not None else 36 + .2 * d) + .5 * abs(self.b.y() - self.a.y())

    def update(self, now: float) -> bool:
        mascot = self.e.mascot
        elapsed = now - self.t0
        if elapsed < self.crouch:
            mascot.stretch = -.16 * _ease(elapsed / max(1e-6, self.crouch))
            self._place(self.a)
            return False
        if not getattr(self, 'sprung', False):
            self.sprung = True
            self.e._sfx('leap')
        u = (elapsed - self.crouch) / self.fly
        if u >= 1:
            self._land(2.2)
            self.e._sfx('land')
            done = self._end()
            if self.on_land is not None:
                self.on_land()
            return done
        x = self.a.x() + (self.b.x() - self.a.x()) * u
        y = self.a.y() + (self.b.y() - self.a.y()) * u - self.h * 4 * u * (1 - u)
        mascot.stretch = .12 * max(0.0, 1 - 2.5 * u) - .04 * max(0.0, u - .8) / .2
        direction = 1 if self.b.x() >= self.a.x() else -1
        self._place(QPointF(x, y), .16 * direction * math.sin(math.pi * u))
        return False


# ---------------------------------------------------------------------- the errands
from .bunny_scenes import HOME_SUGGEST_IDLE_S, LOADING, SCENE_GAP_S, SCENES, SUGGEST_GAP_S, SceneErrands  # noqa: E402


class BunnyErrands(SceneErrands, QObject):
    def __init__(self, chat):
        super().__init__(chat)
        from ..design.bunny_button_fx import ButtonFx
        self.chat = chat
        self.clock = time.perf_counter
        self.manual = False                # a review drives tick() itself
        self.fx = ButtonFx()
        self.overlay = None
        self._gen = None
        self._step = None
        self.name = ''                     # the errand under way ('' when none)
        self.last = ''
        self.home = None                   # where she rests between errands (card-sized top-left)
        self.input_at = 0.0
        self.next_at = time.monotonic() + random.uniform(*FIRST_S)
        from ..design.frame_clock import FrameTimer
        self._frame = FrameTimer(self, FRAME_MS, motion=True)    # the shared beat (frame_clock, 2026-11-27)
        self._frame.timeout.connect(self.tick)
        self._check = QTimer(self)
        self._check.setInterval(CHECK_MS)
        self._check.timeout.connect(self._consider)
        self._check.start()
        self.fidget_at = time.monotonic() + random.uniform(*FIDGET_S)
        self._cursor = None                # (window point, time) of the last pointer sample
        self._hover = None                 # (button, since) the pointer rests on
        self.pounce_at = self.swat_at = -1e9
        self._watcher = QTimer(self)
        self._watcher.setInterval(WATCH_MS)
        self._watcher.timeout.connect(self._watch)
        self._watcher.start()
        try:
            from ..design import app_events
            app_events.listen(self, (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel),
                              self._input)
        except Exception:  # noqa: BLE001 - without it she only waits for her own timer
            pass
        pages = getattr(chat.window_, 'pages', None)
        if pages is not None:
            # The page behind the studio's loading card may change while she sits on the card.
            pages.currentChanged.connect(lambda _index: self.context() == LOADING or self.interrupt())

    # ------------------------------------------------------------ helpers
    @property
    def puck(self):
        return self.chat.puck

    @property
    def mascot(self):
        return self.chat.mascot

    @property
    def window(self):
        return self.chat.window_

    def _input(self, _watched, _event) -> bool:
        self.input_at = time.monotonic()
        return False

    def busy(self) -> bool:
        return self._gen is not None

    def postpone(self, seconds: float | None = None):
        self.next_at = time.monotonic() + (random.uniform(*GAP_S) if seconds is None else seconds)

    def after_landing(self, thrown: bool) -> None:
        """She came down where she was thrown (or dropped from the pointer, or put down gently).
        2026-11-27 (user: after being grabbed and thrown she stayed quiet for a long while; more
        lively and mischievous): a reaction at once, and her next errand soon — for a while after
        a throw that is often a leap for the pointer."""
        now = time.monotonic()
        self.fidget_at = now + random.uniform(1.2, 2.2)
        if not thrown:
            self.postpone(random.uniform(2.5, 5.0))
            return
        self.mischief_until = now + MISCHIEF_S
        self.postpone(random.uniform(1.4, 3.0))
        QTimer.singleShot(260, self._landing_reaction)

    def _landing_reaction(self) -> None:
        puck, mascot = self.puck, self.mascot
        if puck is None or mascot is None or self._gen is not None or puck.mode != 'rest' or puck.press is not None:
            return
        if mascot.current_move == 'dizzy':
            self._line(random.choice(('晕晕的……', '星星在转～')))
            return
        name, words = random.choice((
            ('cheer', ('再来一次！', '好玩！再扔一次～', '呀吼～')),
            ('pout', ('哼，扔我！', '我要报仇！', '你等着～')),
            ('spin', ('转一圈～落地！', '满分落地！')),
            ('ear_flap', ('飞起来啦～', '嘿嘿，没事～')),
        ))
        if not mascot.act(name):
            mascot.play(name)
        self._line(random.choice(words))
        mascot.keep_lively(1.5)

    def _mischief(self):
        """Just thrown: often she goes straight for the pointer (if it is near enough)."""
        if time.monotonic() > getattr(self, 'mischief_until', 0.0) or self.context() in ('editor', LOADING):
            return None
        point = self._cursor_point()
        if not self.window.rect().contains(point.toPoint()):
            return None
        body = self._drawn(self.puck.pos)
        centre = QPointF(body.center())
        if math.hypot(point.x() - centre.x(), point.y() - centre.y()) > POUNCE_REACH + 140 or random.random() > .6:
            return None
        self.pounce_at = time.monotonic()
        return ('pounce', point)

    def _line(self, text: str):
        """A few words in the bubble over her head."""
        if self.puck is not None:
            self.puck.bubble_line(_say(text))

    def _overlay(self):
        if self.overlay is None:
            from .bunny_overlay import FxOverlay
            self.overlay = FxOverlay(self.puck.carrier)
            self.overlay.sound = self._sfx      # 2026-11-27: flights pop, sparkles ring
        return self.overlay

    def _sfx(self, name: str, **options) -> bool:
        """2026-11-27 (user: every action of hers needs a cute sound): ``bunny_sfx`` through her chat."""
        from .bunny_sfx import play
        return play(self.chat, name, **options)

    @staticmethod
    def _s(seconds: float) -> float:
        return seconds * PACE

    def _studio(self):
        built = getattr(self.window, 'built_page', None)
        try:
            return built('studio') if callable(built) else None
        except Exception:  # noqa: BLE001
            return None

    def context(self) -> str:
        """'home', 'workshop', 'hub' (the studio's project library), 'editor' (a project open), one of
        the scenes (bunny_scenes: 'progress', 'result', 'proofread', 'export') or 'other'."""
        scene = self.scene()
        if scene:
            return scene
        page = self.page()
        if page == STUDIO_PAGE:
            studio = self._studio()
            library = getattr(studio, 'project_library_scroll', None) if studio is not None else None
            return 'hub' if _visible(library) else 'editor'
        return {HOME_PAGE: 'home', WORKSHOP_PAGE: 'workshop'}.get(page, 'other')

    def _height_for(self, context: str) -> int:
        from . import ui_zoom
        from .bunny_chat import BunnyChat
        return ui_zoom.px(SMALL_HEIGHT if context == 'editor' else BunnyChat.MASCOT_HEIGHT)

    def _prepare_height(self, height: int):
        """Ask for her pictures at ``height`` ahead, so the change shows no placeholder."""
        mascot = self.mascot
        try:
            mascot._assets.request(int(height), mascot.devicePixelRatioF())
        except Exception:  # noqa: BLE001
            pass

    def _height_ready(self, height: int) -> bool:
        mascot = self.mascot
        try:
            key = mascot._assets.request(int(height), mascot.devicePixelRatioF())
            return mascot._assets.cache.get(key) is not None
        except Exception:  # noqa: BLE001
            return True

    def page(self) -> str:
        from .bunny_chat import current_page
        try:
            return current_page(self.window)
        except RuntimeError:
            return ''

    def _free(self, *, allow_fidget: bool = False) -> bool:
        chat, puck, mascot = self.chat, self.puck, self.mascot
        if puck is None or mascot is None or mascot.reduced_motion:
            return False
        if not chat.collapsed or puck.docked or puck.mode != 'rest' or puck.press is not None:
            return False
        if getattr(chat, 'fold_reason', '') not in ('user', 'start'):
            return False                   # folded only while carried: the card is on its way back
        window = self.window
        try:
            if not window.isVisible() or window.isMinimized():
                return False
        except RuntimeError:
            return False
        app = QApplication.instance()
        if app.applicationState() != Qt.ApplicationState.ApplicationActive:
            return False
        if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
            return False
        touch = getattr(chat, 'touch', None)
        if chat.busy or getattr(chat, '_dozing', False) or (touch is not None and touch.tug is not None):
            return False
        if mascot.held or mascot.entering():
            return False
        if mascot.current_move and not (allow_fidget and mascot.current_move in self.FIDGETS):
            return False
        from .bunny_resident import tour_open
        return not tour_open(window)

    def _consider(self):
        now = time.monotonic()
        context = self.context()
        if context != getattr(self, '_context', None):
            changed = getattr(self, '_context', None) is not None
            self._context = context
            if changed and self._gen is not None and self.name != 'resize':
                self.interrupt()                       # e.g. a project opened under her: those cards are gone
            if context == 'editor':
                self.next_at = min(self.next_at, now + 1.2)   # out of the way soon
                self._prepare_height(self._height_for(context))
            elif context == LOADING:
                self.next_at = min(self.next_at, now + .3)    # over to the loading card soon
        try:
            self.scene_report(context)                 # progress and suggestions, also mid-errand
        except RuntimeError:
            pass
        if self._gen is not None:
            return
        if context == LOADING:
            self.next_at = min(self.next_at, now + .6)        # back onto the card (after a press)
        quiet = EDITOR_QUIET_S if context in ('editor', LOADING) else INPUT_QUIET_S
        if now - self.input_at < quiet or not self._free():
            return
        wanted = self._height_for(context)
        if self.mascot.mascot_height != wanted:
            self.start('resize', wanted)
            return
        if now < self.next_at:
            if context not in ('editor', LOADING) and now >= self.fidget_at:
                self.fidget_at = now + random.uniform(*FIDGET_S)
                self._fidget()
            return
        choice = self.pick()
        if choice is None:
            self.postpone(8.0)
            return
        self.start(*choice)

    # ------------------------------------------------------------ the frame
    def tick(self):
        now = self.clock()
        if self._gen is not None and self.mascot is not None:
            self.mascot.keep_lively(0.4)
        self.fx.step(now)
        overlay = self.overlay
        if overlay is not None:
            overlay.step(now)
            if self.puck is not None:
                self.puck.carrier.set_extra(overlay.bounds() if overlay.busy() else QRect())
        step = self._step
        if step is not None and step.update(now):
            self._step = None
            self._advance(now)
        if (self._gen is None and not self.fx.busy() and not (overlay is not None and overlay.busy())
                and self._frame.isActive()):
            self._frame.stop()

    def _run_frames(self):
        if not self.manual and not self._frame.isActive():
            self._frame.start()

    def _advance(self, now: float):
        while self._gen is not None:
            try:
                command = next(self._gen)
            except StopIteration:
                self._finished()
                return
            except Exception:  # noqa: BLE001 - an errand going wrong never breaks her
                import traceback
                traceback.print_exc()
                self.interrupt()
                return
            step = command if isinstance(command, Step) else Wait(float(command))
            step.start(now)
            if not step.update(now):
                self._step = step
                return
        self._step = None

    def _finished(self):
        finished = self.name
        self._gen = None
        self._step = None
        self.name = ''
        if self.mascot is not None:
            self.mascot.mirrored = False
        if finished == 'resize' and self.context() == 'editor':
            self.postpone(.6)
        elif finished == 'nap':
            self.postpone(random.uniform(4.0, 12.0))
        elif self.context() in SCENES:
            self.postpone(random.uniform(*SCENE_GAP_S))   # pages for waiting: something to watch often
        else:
            self.postpone()

    def interrupt(self, go_home: bool = False):
        """Stop the errand where it is (a press on her, a page change): borrowed icons go back, the
        buttons spring back, what she held goes away. ``go_home`` hops her back afterwards."""
        gen, step = self._gen, self._step
        self._gen = self._step = None
        if step is not None:
            step.stop()
        if gen is not None:
            try:
                gen.close()
            except Exception:  # noqa: BLE001
                pass
        if gen is None and step is None:
            return
        self.name = ''
        self.fx.release()
        self._run_frames()                 # the buttons spring back on their own
        if self.mascot is not None:
            self.mascot.mirrored = False
        self.postpone()
        puck = self.puck
        if go_home and puck is not None and not puck.docked and puck.press is None and self.home is not None:
            self._gen = self._go_home()
            self._advance(self.clock())

    def _go_home(self):
        yield Hop(self, self.home)

    def close(self):
        self.interrupt()
        self.fx.clear()
        self._frame.stop()
        self._check.stop()
        self._watcher.stop()
        if self.overlay is not None:
            self.overlay.clear()
        try:
            from ..design import app_events
            app_events.unlisten(self)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ choosing
    def _rect(self, widget) -> QRect:
        return QRect(widget.mapTo(self.window, QPoint(0, 0)), widget.size())

    def _fits(self, spot: QPointF) -> bool:
        return self.puck.limits().adjusted(-1, -1, 1, 1).contains(spot)

    def _ours(self, widget) -> bool:
        chat, puck = self.chat, self.puck
        try:
            return (chat.isAncestorOf(widget) or widget is chat
                    or (puck is not None and (puck.carrier.isAncestorOf(widget) or widget is puck.carrier)))
        except RuntimeError:
            return True

    def _buttons(self) -> list:
        """The page's buttons she may play with: shown whole, below the header, a usual size, free to wobble."""
        from ..design.bunny_button_fx import usable
        window = self.window
        found = []
        for button in window.findChildren(QAbstractButton):
            try:
                if not (button.isVisible() and button.isEnabled() and usable(button) and button.window() is window):
                    continue
                if self._ours(button) or not (50 <= button.width() <= 360 and 22 <= button.height() <= 72):
                    continue
                if 'danger' in button.objectName():
                    continue                   # 2026-11-27: never plays with 安全取消 and the like
                rect = self._rect(button)
                if rect.top() < 110 or not window.rect().contains(rect):
                    continue
                seen = button.visibleRegion().boundingRect()
                if seen.width() < button.width() * .9 or seen.height() < button.height() * .9:
                    continue
            except RuntimeError:
                continue
            found.append(button)
        return found

    def _side_spot(self, widget, contact):
        """(spot, mirrored) with her front paw (canvas ``contact``) on ``widget``'s near side, or None."""
        rect = self._rect(widget)
        y = rect.center().y()
        here = self.puck.pos
        options = []
        for mirrored, x in ((False, rect.left() + 2), (True, rect.right() - 2)):
            spot = self.puck.spot_for(contact, QPointF(x, y), mirrored=mirrored)
            if self._fits(spot):
                options.append((math.hypot(spot.x() - here.x(), spot.y() - here.y()), spot, mirrored))
        if not options:
            return None
        options.sort(key=lambda row: row[0])
        return options[0][1], options[0][2]

    def _wrench_spot(self, button):
        """(spot, mirrored) that brings her wrench down on ``button``'s icon, or None when she does not fit."""
        from ..design.bunny_props import wrench_jaw
        gear = QPointF(icon_centre(button, self.window))
        jaw = wrench_jaw()
        for mirrored in (False, True):
            spot = self.puck.spot_for(jaw, gear, mirrored=mirrored)
            if self._fits(spot):
                return spot, mirrored
        return None

    def _seat_spot(self, widget, x: float | None = None, point=SEAT):
        rect = self._rect(widget)
        if rect.top() < 150:                       # not up near the header: she would not fit above it
            return None
        if x is None:
            x = rect.center().x() + random.uniform(-.25, .25) * rect.width() if rect.width() > 160 else rect.center().x()
        x = max(rect.left() + 8.0, min(float(x), rect.right() - 8.0))
        spot = self.puck.spot_for(point, QPointF(x, rect.top() + 3))
        return spot if self._fits(spot) else None

    def _header_buttons(self) -> list:
        window = self.window
        buttons = [getattr(window, name, None) for name in HEADER_BUTTONS]
        rows = []
        for button in buttons:
            if not (_visible(button) and button.isEnabled()):
                continue
            rect = self._rect(button)
            spot = self.puck.spot_for(RING, QPointF(rect.center().x(), rect.bottom() - 1))
            if self._fits(spot):
                rows.append((rect.center().x(), button))
        return [button for _x, button in sorted(rows, key=lambda row: row[0])]

    def _row(self, buttons) -> list:
        """Three or more buttons side by side on one line (for the dominoes), or []."""
        rows = {}
        for button in buttons:
            rect = self._rect(button)
            rows.setdefault((round(rect.center().y() / 6), id(button.parentWidget())), []).append((rect.left(), button))
        best = []
        for row in rows.values():
            row.sort(key=lambda item: item[0])
            line = [button for _x, button in row]
            ok = all(self._rect(b).left() - self._rect(a).right() < 48 for a, b in zip(line, line[1:]))
            if ok and len(line) >= 3 and len(line) > len(best):
                best = line
        return best

    def _cards(self) -> list:
        """Cards she can hop between: the project library's, the workshop's model cards, the home page's."""
        context = self.context()
        window = self.window
        if context == 'hub':
            studio = self._studio()
            cards = list(getattr(studio, '_hub_card_widgets', []) or []) if studio is not None else []
        elif context == 'workshop':
            from PySide6.QtWidgets import QFrame
            cards = [w for w in window.findChildren(QFrame) if type(w).__name__ == 'ModelCard']
        elif context == 'home':
            cards = [getattr(window, name, None) for name in ('media_frame', 'studio_recent_hero', 'home_process_card')]
        else:
            cards = self.scene_cards(context)
        found = []
        for card in cards:
            try:
                if not _visible(card) or self._ours(card):
                    continue
                seen = card.visibleRegion().boundingRect()
                if seen.height() < card.height() * .6 or self._seat_spot(card, point=FEET) is None:
                    continue
            except RuntimeError:
                continue
            found.append(card)
        return found

    def candidates(self) -> list:
        """(errand, target) for what is on screen now."""
        from ..design.bunny_moves import KNOCK_PAW
        window = self.window
        found = []
        context = self.context()
        if context in ('editor', LOADING):
            return []
        if context in SCENES:
            found += self.scene_candidates(context)
        elif context == 'home' and time.monotonic() - self.input_at > HOME_SUGGEST_IDLE_S:
            suggestion = self._suggestion('home')
            if suggestion is not None and time.monotonic() - getattr(self, '_suggested_at', -1e9) > SUGGEST_GAP_S:
                found += [('suggest', suggestion)] * 2       # 2026-11-27: she points at the next step
        cards = self._cards()
        if len(cards) >= 2:
            found.append(('card_hop', cards))
        if context == 'workshop' and cards:
            card = random.choice(cards)
            if self._side_spot(card, PAW_FRONT) is not None:
                found.append(('inspect', card))
        gear = next((widget for widget in (getattr(window, name, None) for name in GEARS)
                     if _visible(widget) and self._wrench_spot(widget) is not None), None)
        if gear is not None:
            found.append(('fix_gear', gear))
        book = getattr(window, 'add_glossary_button', None)
        if _visible(book) and self._side_spot(book, self._contact(KNOCK_PAW)) is not None:
            found.append(('read_book', book))
        seats = [getattr(window, name, None) for name in SEATS]
        seats = [widget for widget in seats if _visible(widget) and self._seat_spot(widget) is not None]
        if seats:
            found.append(('sit_on', random.choice(seats)))
        bars = self._header_buttons()
        if len(bars) >= 2:
            found.append(('hang_on', bars))
        buttons = self._buttons()
        row = self._row(buttons)
        if row:
            found.append(('domino', row))
        wide = [b for b in buttons if b.width() >= 110 and self._seat_spot(b, point=FEET) is not None]
        if wide:
            found.append(('stomp', random.choice(wide)))
        random.shuffle(buttons)
        for button in buttons[:4]:
            name = random.choice(ONE_BUTTON)
            if name == 'lift' and (button.width() > 170 or self._lift_spot(button) is None):
                name = 'flick'
            if name != 'lift' and self._side_spot(button, PAW_FRONT) is None:
                continue
            found.append((name, button))
        return found

    def pick(self):
        context = self.context()
        if context == LOADING:
            view = self.loading_view()
            return ('loading_seat', view) if view is not None else None
        if context == 'editor':
            spots = self._safe_spots()
            if not spots:
                return None
            here = self.puck.pos
            near = min(spots, key=lambda spot: math.hypot(spot.x() - here.x(), spot.y() - here.y()))
            placed = time.monotonic() - self.puck.placed_at < PLACED_QUIET_S
            if placed and self._safe_here():
                return ('nap', QPointF(here))      # put there by the user: she naps where she is
            others = [spot for spot in spots if spot is not near]
            spot = random.choice(others) if others and random.random() < .45 and not placed else near
            return ('nap', spot)
        mischief = self._mischief()
        if mischief is not None:
            return mischief
        found = self.candidates()
        if context in ('home', 'workshop', 'hub') and time.monotonic() - self.puck.placed_at > PLACED_QUIET_S:
            if not found or random.random() < WANDER_SHARE:
                spot = self._wander_spot()
                if spot is not None:
                    return ('wander', spot)
        fresh = [item for item in found if item[0] != self.last] or found
        if not fresh:
            return None
        here = self.puck.pos

        def weight(item):
            target = item[1]
            widget = target[0] if isinstance(target, list) else target
            try:
                rect = self._rect(widget)
            except (RuntimeError, AttributeError):
                return 1.0
            return 1.0 / (1.0 + math.hypot(rect.center().x() - here.x(), rect.center().y() - here.y()) / 600)
        return random.choices(fresh, weights=[weight(item) for item in fresh])[0]

    def start(self, name: str, target) -> bool:
        """Begin the errand ``name`` on ``target`` now (False when she cannot)."""
        puck = self.puck
        if puck is None or puck.docked or self._gen is not None:
            return False
        maker = getattr(self, '_' + name, None)
        if maker is None:
            return False
        self.name = self.last = name
        self.home = QPointF(puck.pos)
        self._gen = maker(target)
        self._run_frames()
        self._advance(self.clock())
        return True

    # ------------------------------------------------------------ small pieces the errands share
    def _face(self, mirrored: bool) -> int:
        self.mascot.mirrored = bool(mirrored)
        return -1 if mirrored else 1

    def _focus(self, value):
        life = self.mascot.life
        if life is not None:
            life.focus = value

    @staticmethod
    def _contact(paw):
        from ..design.bunny_props import paw_point
        return paw_point(PAW_FRONT, 'right', paw)

    def _paw_point(self, paw) -> QPointF:
        return self.puck.window_point(self._contact(paw))

    def _knocks(self, widget, count: int, side: int):
        from ..design.bunny_moves import KNOCK_HIT, KNOCK_PAW, KNOCK_S
        self.mascot.play('knock')

        def knock(_index):
            now = self.clock()
            self.fx.kick(widget, pivot=(.5, 1.0), angle=46 * side, x=40 * side)
            self.fx.shake(widget, .18, now, px=1.2, degrees=1.5)
            self._sfx('knock')
            self._overlay().burst('tap', self._paw_point(KNOCK_PAW), now, .3, direction=0.0 if side > 0 else math.pi)
        yield Beats(count, KNOCK_S, KNOCK_HIT, knock)
        self.mascot.stop_move('knock')

    def _approach(self, widget, contact):
        """Hop to ``widget``'s side with her paw at ``contact``; returns the side (+1: it is on her right)."""
        place = self._side_spot(widget, contact)
        if place is None:
            return 0
        spot, mirrored = place
        yield Hop(self, spot)
        return self._face(mirrored)

    def _cleanup(self, *widgets, moves=(), prop=True):
        for widget in widgets:
            if widget is not None:
                self.fx.release(widget)
        for move in moves:
            self.mascot.stop_move(move)
        if prop:
            self.mascot.put_away()
        self._focus(None)
        self.mascot.unstick('zzz')

    # ------------------------------------------------------------ 1. mend the gear
    def _fix_gear(self, button):
        from ..design.bunny_moves import STRIKE_HIT, STRIKE_S
        mascot = self.mascot
        place = self._wrench_spot(button)
        if place is None:
            return
        spot, mirrored = place
        gear = QPointF(icon_centre(button, self.window))
        self._line(random.choice(('我来修修看！', '齿轮好像卡住了？', '交给兔白～')))
        try:
            yield Hop(self, spot)
            side = self._face(mirrored)
            now = self.clock()
            mascot.act('wonder')                       # head tilted at it ...
            self.fx.shake(button, 1.0, now, px=1.8, degrees=4.5)
            self.fx.hold(button, pivot=(.5, 1.0), angle=-6 * side, y=1)   # ... it rattles and hangs crooked
            self._focus((.9 * side, -.1))
            yield 1.2
            self._line('齿轮松了！')
            mascot.hop()
            mascot.hold('wrench')                      # out comes her wrench
            yield .45
            mascot.play('strike')

            def hit(index):
                now = self.clock()
                self._overlay().burst('spark', gear, now, .38, direction=math.pi / 2 * index)
                self._sfx('clank', pitch=1.0 + .05 * (index % 2))
                self.fx.kick(button, pivot=(.5, 1.0), angle=(-80 if index % 2 else 80) * side, y=70, squash=2.6)
                self.fx.spin(button, 300 * side)
                if index == 3:
                    self.fx.release(button)            # the last blow sets it straight
            yield Beats(4, STRIKE_S, STRIKE_HIT, hit)
            mascot.stop_move('strike')
            mascot.put_away('wrench')
            self._focus(None)
            self._overlay().burst('sparkle', QPointF(self._rect(button).center()), self.clock(), 1.0, size=1.3)
            yield .3
            mascot.play('wipe_brow')
            mascot.stick('sweat')
            ready = bool(getattr(self.chat, 'ready', True))
            self._line('修好啦！' if ready or button is not getattr(self.window, 'ai_settings_button', None)
                       else '要填好 Key 才会转哦')
            yield 1.3
        finally:
            self._cleanup(button, moves=('strike', 'wipe_brow'))
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 2. borrow the term library's book
    def _read_book(self, button):
        from ..design.bunny_moves import KNOCK_PAW
        mascot = self.mascot
        taken = False
        self._line(random.choice(('借术语库看看～', '让兔白翻翻这本', '今天学几个新词')))
        try:
            side = yield from self._approach(button, self._contact(KNOCK_PAW))
            if not side:
                return
            yield from self._knocks(button, 2, side)
            self._line('借一下～')
            yield .2
            icon = self.fx.take_icon(button)
            taken = True
            start = QPointF(icon_centre(button, self.window))
            pixmap = icon.pixmap(button.iconSize(), button.devicePixelRatioF())
            self.fx.kick(button, pivot=(.5, 1.0), y=-150, squash=-2.2)     # it pops the book out
            self._overlay().fly(pixmap, start, self.puck.window_point(BOOK_AT), self.clock(), self._s(.55),
                                lift=58, grow=2.4, spin=360 * side)
            yield .55
            mascot.hold('book')
            mascot.play('read')
            self._focus((0.0, .75))
            yield 2.4
            self._focus((.85 * side, .1))             # a look at where it came from
            yield .7
            self._focus((0.0, .75))
            yield 1.8
            self._line(random.choice(('嗯嗯，记住了！', '原来这个词这样写', '又学到了～')))
            yield .6
            mascot.stop_move('read')
            mascot.put_away('book')
            self._focus(None)
            self._overlay().fly(pixmap, self.puck.window_point(BOOK_AT), start, self.clock(), self._s(.5),
                                lift=70, grow=2.0, spin=-360 * side)
            yield .5
            self.fx.give_icon(button)
            taken = False
            self.fx.kick(button, pivot=(.5, 1.0), angle=-70 * side, y=90, squash=2.8)   # caught it
            self._line('还给你～')
            mascot.act('yes')
            yield .9
        finally:
            if taken:
                self.fx.give_icon(button)
            self._cleanup(button, moves=('read', 'knock'))
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 3. push it over (it springs back)
    def _push(self, widget):
        from ..design.bunny_moves import PUSH_PAW
        mascot = self.mascot
        try:
            side = yield from self._approach(widget, self._contact(PUSH_PAW))
            if not side:
                return
            mascot.play('push')
            self._line('嘿——咻！')
            now = self.clock()
            self.fx.hold(widget, pivot=(1.0 if side > 0 else 0.0, 1.0), angle=9 * side, x=7 * side)
            self.fx.shake(widget, 1.7, now, px=.9, degrees=1.2)
            yield 1.8
            mascot.stop_move('push')
            self.fx.release(widget)
            self.fx.kick(widget, angle=-110 * side, x=-90 * side)            # it springs back at her
            mascot.play('tumble')
            here = self.puck.pos
            yield Hop(self, QPointF(here.x() - 40 * side, here.y()), trot=False, face=False, height=16, hops=1)
            self._line('哎呦……')
            yield 1.0
        finally:
            self._cleanup(widget, moves=('push', 'tumble'))
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 4. tug at it (it snaps away)
    def _tug(self, widget):
        from ..design.bunny_moves import PULL_PAW
        mascot = self.mascot
        try:
            side = yield from self._approach(widget, self._contact(PULL_PAW))
            if not side:
                return
            mascot.play('pull')
            self._line('拉、拉不动……')
            now = self.clock()
            self.fx.hold(widget, pivot=(1.0 if side > 0 else 0.0, .5), angle=-4 * side, x=-12 * side)
            self.fx.shake(widget, 1.5, now, px=1.0, degrees=1.0)
            yield 1.6
            mascot.stop_move('pull')
            self.fx.release(widget)
            self.fx.kick(widget, x=170 * side, angle=70 * side)              # it snaps back
            mascot.play('tumble')
            here = self.puck.pos
            yield Leap(self, QPointF(here.x() - 60 * side, here.y()), height=22, crouch=.02, face=False)
            self._line('呜哇！')
            yield 1.0
        finally:
            self._cleanup(widget, moves=('pull', 'tumble'))
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 5. stomp on it like a trampoline
    def _stomp(self, widget):
        mascot = self.mascot
        top = self._seat_spot(widget, point=FEET)
        if top is None:
            return

        def landed(power):
            def hit():
                self.fx.kick(widget, pivot=(.5, 1.0), squash=3.2 * power, y=70 * power,
                             angle=random.choice((-1, 1)) * 30 * power)
                self.fx.hold(widget, pivot=(.5, 1.0), squash=.07, y=2)
            return hit
        try:
            here = self.puck.pos
            if math.hypot(top.x() - here.x(), top.y() - here.y()) > 260:
                yield Hop(self, QPointF(top.x() - 90, top.y() + 40))
            yield Leap(self, top, on_land=landed(1.0))
            self._line('弹弹床～')
            for power in (.8, 1.0):
                yield Leap(self, top, height=30, crouch=.1, on_land=landed(power), face=False)
            mascot.stick('sparkle')
            yield Leap(self, top, height=120, crouch=.18, on_land=landed(1.4), face=False)
            yield .3
            self.fx.release(widget)
            yield Leap(self, self.home, height=50)
        finally:
            self._cleanup(widget, prop=False)
        yield .4

    # ------------------------------------------------------------ 6. knock knock
    def _knock(self, widget):
        from ..design.bunny_moves import KNOCK_PAW
        mascot = self.mascot
        try:
            side = yield from self._approach(widget, self._contact(KNOCK_PAW))
            if not side:
                return
            yield from self._knocks(widget, 3, side)
            self._line('有人在家吗？')
            mascot.act('wonder')
            yield 1.1
            now = self.clock()
            self.fx.shake(widget, .7, now, px=3.2, degrees=6, pivot=(.5, .5))   # it answers!
            self.fx.kick(widget, pivot=(.5, .5), y=-90)
            mascot.act('startled')
            here = self.puck.pos
            yield Hop(self, QPointF(here.x() - 34 * side, here.y()), trot=False, face=False, height=30, hops=1)
            self._line('哇！它动了！')
            yield 1.0
        finally:
            self._cleanup(widget, moves=('knock',))
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 7. flick it round
    def _flick(self, button):
        mascot = self.mascot
        try:
            side = yield from self._approach(button, PAW_FRONT)
            if not side:
                return
            mascot.play('flick')
            yield .2
            self.fx.kick(button, pivot=(.5, .5), angle=560 * side)
            if button.property('_themed_icon'):
                self.fx.spin(button, 600 * side)
            self._overlay().burst('tap', self._paw_point((60.0, -36.0, -20.0, 1.2)), self.clock(), .3,
                                  direction=0.0 if side > 0 else math.pi)
            yield .5
            mascot.act('smirk')
            self._line('嘿嘿，转起来了')
            yield 1.3
        finally:
            self._cleanup(button, moves=('flick',))
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 8. tickle it
    def _tickle(self, button):
        mascot = self.mascot
        try:
            side = yield from self._approach(button, PAW_FRONT)
            if not side:
                return
            mascot.play('tickle')
            now = self.clock()
            self.fx.shake(button, 1.9, now, px=2.6, degrees=7.5, pivot=(.5, .5))
            self._overlay().burst('hearts', QPointF(self._rect(button).center()), now, 1.2)
            yield .6
            self._line('它在笑耶！')
            yield 1.3
            mascot.stop_move('tickle')
            mascot.act('excited')
            yield 1.0
        finally:
            self._cleanup(button, moves=('tickle',))
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 9. polish it
    def _polish(self, button):
        from ..design.bunny_moves import POLISH_S
        mascot = self.mascot
        try:
            side = yield from self._approach(button, PAW_FRONT)
            if not side:
                return
            mascot.hold('cloth')
            yield .3
            mascot.play('polish')
            self._line('擦一擦～')

            def wipe(index):
                self.fx.kick(button, pivot=(.5, 1.0), angle=(26 if index % 2 else -26), x=(20 if index % 2 else -20))
                self._sfx('wipe', pitch=1.0 if index % 2 else 1.08)
            yield Beats(4, POLISH_S, .5, wipe)
            mascot.stop_move('polish')
            mascot.put_away('cloth')
            self._overlay().burst('sparkle', QPointF(self._rect(button).center()), self.clock(), 1.1, size=1.3)
            self._line('亮晶晶～')
            mascot.act('bloom')
            yield 1.4
        finally:
            self._cleanup(button, moves=('polish',))
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 10. dominoes
    def _domino(self, row):
        from ..design.bunny_moves import PUSH_PAW
        mascot = self.mascot
        if len(row) < 3:
            return
        first, last = row[0], row[-1]
        try:
            contact = self._contact(PUSH_PAW)
            left = self.puck.spot_for(contact, QPointF(self._rect(first).left() + 2, self._rect(first).center().y()))
            right = self.puck.spot_for(contact, QPointF(self._rect(last).right() - 2, self._rect(last).center().y()),
                                       mirrored=True)
            if self._fits(left):
                spot, mirrored, line = left, False, row
            elif self._fits(right):
                spot, mirrored, line = right, True, list(reversed(row))
            else:
                return
            yield Hop(self, spot)
            side = self._face(mirrored)
            mascot.play('push')
            yield .45

            def fall(index):
                self.fx.kick(line[index], pivot=(1.0 if side > 0 else 0.0, 1.0), angle=250 * side)
                self._sfx('knock', pitch=1.0 + .07 * index)     # each one falls a little higher
            yield Beats(len(line), .13, 0.0, fall)
            mascot.stop_move('push')
            mascot.act('cheer')
            self._line('倒了倒了～')
            yield 1.4
        finally:
            for button in row:
                self.fx.release(button)
            self._cleanup(moves=('push',), prop=False)
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 11. lift it over her head
    def _lift_spot(self, button):
        rect = self._rect(button)
        spot = self.puck.spot_for(LIFT_TOP, QPointF(rect.center().x(), rect.bottom() + 4))
        return spot if self._fits(spot) else None

    def _lift(self, button):
        mascot = self.mascot
        spot = self._lift_spot(button)
        if spot is None:
            return
        try:
            yield Hop(self, spot)
            self._face(False)
            mascot.play('lift')
            now = self.clock()
            self.fx.hold(button, pivot=(.5, 1.0), y=-24, angle=3)
            self.fx.shake(button, 1.8, now, px=1.6, degrees=2.4)
            self._line('嘿……好重……')
            yield 1.9
            mascot.stop_move('lift')
            self.fx.release(button)
            self.fx.kick(button, pivot=(.5, 1.0), y=320, squash=3.0)          # down it comes
            self.fx.shake(button, .3, self.clock(), px=2.0, degrees=2)
            mascot.play('wipe_brow')
            mascot.stick('sweat')
            yield 1.3
        finally:
            self._cleanup(button, moves=('lift', 'wipe_brow'), prop=False)
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 12. blow the dust off
    def _blow(self, button):
        mascot = self.mascot
        try:
            side = yield from self._approach(button, PAW_FRONT)
            if not side:
                return
            mascot.play('blow')
            yield .75
            now = self.clock()
            rect = self._rect(button)
            self._overlay().burst('dust', QPointF(rect.center()), now, .9, direction=0.0 if side > 0 else math.pi)
            self.fx.shake(button, .5, now, px=1.4, degrees=2.6)
            self.fx.kick(button, pivot=(.5, 1.0), angle=30 * side)
            yield .7
            self._line('呼～干净了')
            yield 1.0
        finally:
            self._cleanup(button, moves=('blow',), prop=False)
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 13. lean on it and doze off
    def _lean_nap(self, widget):
        mascot = self.mascot
        try:
            side = yield from self._approach(widget, PAW_FRONT)
            if not side:
                return
            mascot.play('lean_nap')
            self.fx.hold(widget, pivot=(1.0 if side > 0 else 0.0, 1.0), angle=3.5 * side, x=2.5 * side)
            mascot.stick('zzz')
            yield 3.6
            mascot.unstick('zzz')
            mascot.stop_move('lean_nap')
            self.fx.release(widget)
            self.fx.kick(widget, angle=-60 * side)
            mascot.act('startled')
            self._line('我、我没睡！')
            yield 1.2
        finally:
            self._cleanup(widget, moves=('lean_nap',), prop=False)
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 14. sit on it
    def _sit_on(self, target):
        mascot = self.mascot
        widget, x = target if isinstance(target, tuple) else (target, None)
        spot = self._seat_spot(widget, x)
        if spot is None:
            return
        self._line(random.choice(('坐一下下～', '这里视野不错', '借我坐坐')))
        side = random.choice((-1, 1))

        def sat():
            self.fx.kick(widget, pivot=(.5, 1.0), squash=2.8, y=60, angle=20 * side)
            self.fx.hold(widget, pivot=(.5, 1.0), y=2, angle=1.6 * side, squash=.04)
        try:
            here = self.puck.pos
            if math.hypot(spot.x() - here.x(), spot.y() - here.y()) > 260:
                yield Hop(self, QPointF(spot.x() - 80 * side, spot.y() + 50))
            yield Leap(self, spot, height=40, on_land=sat)
            self._face(side < 0)
            mascot.play('sit')
            self._focus((random.choice((-.7, .7)), .35))
            yield 2.4
            self._focus(None)
            mascot.stick(random.choice(('notes', 'sparkle', 'flower')))
            yield 2.0
            if random.random() < .5:
                mascot.stop_move('sit')
                kind = random.choice(('yawn', 'stretch', 'hmm'))
                mascot.play('yawn') if kind == 'yawn' else mascot.act(kind)
                yield 1.8
                mascot.play('sit')
                yield 1.0
            mascot.stop_move('sit')
            yield Leap(self, self.home, height=46)
            self.fx.release(widget)
            self.fx.kick(widget, pivot=(.5, 1.0), y=-60, squash=-1.5)
        finally:
            self._cleanup(widget, moves=('sit',), prop=False)
        yield .4

    # ------------------------------------------------------------ 15. swing along the header
    def _hang_on(self, buttons):
        mascot = self.mascot
        if not buttons:
            return
        here = self.puck.pos
        start = 0 if abs(self._rect(buttons[0]).center().x() - here.x()) < abs(
            self._rect(buttons[-1]).center().x() - here.x()) else len(buttons) - 1
        order = buttons if start == 0 else list(reversed(buttons))
        order = order[:random.choice((2, 3))]
        held = []

        def ring_spot(button):
            rect = self._rect(button)
            return self.puck.spot_for(RING, QPointF(rect.center().x(), rect.bottom() - 1))

        def grab(button):
            def done():
                button.setDown(True)
                held.append(button)
                self.fx.kick(button, pivot=(.5, 0.0), y=80, squash=-1.6)
                self.fx.hold(button, pivot=(.5, 0.0), y=4)
            return done
        self._line(random.choice(('荡秋千咯～', '抓紧啦！', '嘿！')))
        try:
            first = ring_spot(order[0])
            yield Hop(self, QPointF(first.x(), first.y() + 90))
            for index, button in enumerate(order):
                yield Leap(self, ring_spot(button), height=26 if index else 34, on_land=grab(button))
                previous = order[index - 1] if index else None
                if previous is not None and previous in held:
                    previous.setDown(False)
                    held.remove(previous)
                    self.fx.release(previous)
                    self.fx.kick(previous, pivot=(.5, 0.0), angle=60, y=-70)
                self._face(False)
                mascot.play('hang')

                def swing(beat, button=button):
                    self.fx.kick(button, pivot=(.5, 0.0), angle=(-70 if beat % 2 else 70))
                    self._sfx('swing')
                yield Beats(2, .9, .25, swing)
                if index == 1:
                    self._line('好高～')
                mascot.stop_move('hang')
            last = order[-1]
            for button in list(held):
                button.setDown(False)
                held.remove(button)
                self.fx.release(button)
                self.fx.kick(button, pivot=(.5, 0.0), angle=-50, y=-80)
            land = ring_spot(last)
            yield Leap(self, QPointF(land.x(), land.y() + 100), height=20)
            mascot.act('cheer')
            yield 1.2
        finally:
            for button in held:
                try:
                    button.setDown(False)
                except RuntimeError:
                    pass
                self.fx.release(button)
            self._cleanup(moves=('hang',), prop=False)
        yield Hop(self, self.home)

    # ------------------------------------------------------------ 16. hop from card to card
    def _card_hop(self, cards):
        mascot = self.mascot
        here = self.puck.pos
        chain, left = [], list(cards)
        point = QPointF(here)
        for _ in range(min(len(left), random.choice((3, 4)))):
            card = min(left, key=lambda c: math.hypot(self._rect(c).center().x() - point.x(),
                                                      self._rect(c).center().y() - point.y()) + random.uniform(0, 80))
            left.remove(card)
            chain.append(card)
            point = QPointF(self._rect(card).center())
        standing = []

        def landed(card):
            def done():
                side = random.choice((-1, 1))
                self.fx.kick(card, pivot=(.5, 1.0), squash=2.2, y=50, angle=14 * side)
                self.fx.hold(card, pivot=(.5, 1.0), y=2, squash=.025)
                standing.append(card)
            return done
        self._line(random.choice(('跳过去～', '一、二、三！', '这个工程看看～')))
        index = 0
        try:
            for index, card in enumerate(chain):
                spot = self._seat_spot(card, point=FEET)
                if spot is None:
                    continue
                yield Leap(self, spot, height=46 if index else 56, on_land=landed(card))
                for previous in standing[:-1]:
                    self.fx.release(previous)
                    self.fx.kick(previous, pivot=(.5, 1.0), y=-50, squash=-1.2)
                del standing[:-1]
                if random.random() < .5:
                    mascot.act(random.choice(('wonder', 'hmm', 'yes')))
                yield random.uniform(.5, 1.0)
            if index >= 2:
                self._line(random.choice(('好多工程呀', '跳累了～')))
            yield Leap(self, self.home, height=50)
        finally:
            for card in standing:
                self.fx.release(card)
            self._cleanup(prop=False)
        yield .3

    # ------------------------------------------------------------ 17. a model card under her magnifier
    def _inspect(self, card):
        mascot = self.mascot
        try:
            side = yield from self._approach(card, PAW_FRONT)
            if not side:
                return
            mascot.play('search')
            mascot.stick('magnifier')
            self._focus((.85 * side, .1))
            now = self.clock()
            self.fx.shake(card, 1.2, now, px=.8, degrees=.8)
            yield 2.0
            mascot.unstick('magnifier')
            mascot.stop_move('search')
            self._focus(None)
            self.fx.kick(card, pivot=(.5, 1.0), angle=20 * side)
            mascot.act(random.choice(('idea', 'excited', 'hmm')))
            self._line(random.choice(('这个模型看起来很厉害', '嗯……下载要等一下', '兔白记住它了')))
            yield 1.4
        finally:
            mascot.unstick('magnifier')
            self._cleanup(card, moves=('search',), prop=False)
        yield Hop(self, self.home)

    # ------------------------------------------------------------ studio editor: smaller, in the corners
    def _resize(self, height):
        mascot, puck = self.mascot, self.puck
        self._prepare_height(height)
        waited = 0.0
        while not self._height_ready(height) and waited < 1.5:
            yield .05
            waited += .05
        try:
            mascot.play('spin')
            centre = puck.window_point((458.0, 430.0))
            self._overlay().burst('sparkle', centre, self.clock(), .9, size=1.2)
            yield .45
            puck.set_bunny_height(height)
            self._overlay().burst('sparkle', puck.window_point((458.0, 430.0)), self.clock(), .7)
            yield .55
        finally:
            mascot.stop_move('spin')
        self.home = QPointF(puck.pos)

    def _editor_blockers(self) -> list:
        """The timeline, the picture and the subtitle editor: never cover these."""
        studio = self._studio()
        rects = []
        for name in ('timeline', 'video_overlay_host', 'cue_editor', 'subtitle_edit_dock', 'review_summary_strip'):
            widget = getattr(studio, name, None) if studio is not None else None
            if _visible(widget):
                rects.append(self._rect(widget))
        return rects

    def _drawn(self, spot: QPointF) -> QRect:
        mascot = self.mascot
        rect = mascot.drawn_rect().translated(-round(mascot.room.x()), -round(mascot.room.y()))
        return rect.translated(spot.toPoint())

    def _controls_in(self, panel) -> list:
        """Buttons, tabs, fields and lists of ``panel`` she must not sit on (window rects)."""
        from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit, QSlider, QTabBar
        rects = []
        for widget in panel.findChildren(QWidget):
            if isinstance(widget, (QAbstractButton, QTabBar, QLineEdit, QComboBox, QAbstractSpinBox, QSlider)):
                try:
                    if widget.isVisible() and widget.width() > 4 and not widget.visibleRegion().isEmpty():
                        rects.append(self._rect(widget))
                except RuntimeError:
                    continue
        return rects

    def _safe_spots(self) -> list:
        """Places along the bottom and top of the subtitle list and the tool panel that cover neither the
        timeline, the picture, the subtitle editor nor any button, tab or field of those panels."""
        studio = self._studio()
        if studio is None:
            return []
        mascot = self.mascot
        drawn_w = mascot.docked_size().width() - 2 * mascot.pad_x
        hard = self._editor_blockers()
        found = []
        for name in ('cue_list_panel', 'context_panel'):
            panel = getattr(studio, name, None)
            if not _visible(panel):
                continue
            rect = self._rect(panel)
            soft = self._controls_in(panel)
            # Low along the bottom first (asleep at the bottom of the list), then tucked in at the top.
            anchors = [(k, FEET, rect.bottom() - 4 - 20 * k) for k in range(7)]
            anchors += [(10 + k, RING, rect.top() + 34 + 20 * k) for k in range(5)]
            x = rect.left() + drawn_w * .55
            xs = []
            while x <= rect.right() - drawn_w * .55:
                xs.append(x)
                x += 22
            for rank, point, y in anchors:
                for x in xs:
                    spot = self.puck.spot_for(point, QPointF(x, y))
                    if not self._fits(spot):
                        continue
                    body = self._drawn(spot).adjusted(4, 6, -4, -2)
                    if not rect.contains(body.center()):
                        continue
                    if any(body.intersects(r.adjusted(2, 2, -2, -2)) for r in hard + soft):
                        continue
                    found.append((rank, spot))
        found.sort(key=lambda item: item[0])
        spread = []
        for _rank, spot in found:
            if all(math.hypot(spot.x() - other.x(), spot.y() - other.y()) > 70 for other in spread):
                spread.append(spot)
        return spread[:8]

    def _safe_here(self) -> bool:
        studio = self._studio()
        soft = []
        for name in ('cue_list_panel', 'context_panel'):
            panel = getattr(studio, name, None) if studio is not None else None
            if _visible(panel):
                soft += self._controls_in(panel)
        body = self._drawn(self.puck.pos).adjusted(4, 6, -4, -2)
        return not any(body.intersects(rect.adjusted(2, 2, -2, -2)) for rect in self._editor_blockers() + soft)

    def _nap(self, spot):
        mascot = self.mascot
        try:
            if math.hypot(spot.x() - self.puck.pos.x(), spot.y() - self.puck.pos.y()) > 3:
                yield Hop(self, spot)
            self._face(random.random() < .5)
            mascot.play('curl_nap')
            mascot.stick('zzz')
            self.home = QPointF(self.puck.pos)
            yield random.uniform(*NAP_S)
            mascot.unstick('zzz')
            mascot.stop_move('curl_nap')
            mascot.act('stretch')
            yield 1.6
        finally:
            mascot.unstick('zzz')
            mascot.stop_move('curl_nap')
        self.home = QPointF(self.puck.pos)

    # ------------------------------------------------------------ round 4: fidgets and the pointer
    FIDGETS = ('tilt', 'ears_up', 'one_ear', 'brow_raise', 'nod', 'ear_flap', 'stretch', 'glint')

    def _fidget(self, may_step: bool = True):
        """Something small while she waits: a move of her own, a hop, a glance, or a step or two."""
        mascot, puck = self.mascot, self.puck
        roll = random.random()
        if may_step and roll < .3:
            here = puck.pos
            side = random.choice((-1, 1))
            spot = QPointF(here.x() + side * random.uniform(40, 90), here.y())
            if self._fits(spot):
                self.start('stroll_step', spot)
                return
        if roll < .55:
            mascot.play(random.choice(self.FIDGETS))
        elif roll < .75:
            mascot.hop()
            if random.random() < .4:
                mascot.stick(random.choice(('notes', 'sparkle', 'heart')))
        else:
            life = mascot.life
            if life is not None:                       # a look somewhere and back
                life.gaze_target = (random.uniform(-1, 1), random.uniform(-.6, .4))
                life.next_glance = life.now + 1.4
            mascot.ear_bias = random.choice((-18.0, 18.0))

    def _stroll_step(self, spot):
        yield Hop(self, spot)
        self.home = QPointF(self.puck.pos)

    def _watchable(self) -> bool:
        """Folded, resting and free enough to go for the pointer (a fidget move may be cut short)."""
        return (not self.busy() and self._free(allow_fidget=True)
                and self.context() not in ('editor', LOADING))

    def _head_zone(self):
        mascot, puck = self.mascot, self.puck
        top = puck.window_point((458.0, 90.0))
        face = puck.window_point((458.0, 520.0))
        half = (mascot.docked_size().width() - 2 * mascot.pad_x) * .7
        return QRectF(top.x() - half, top.y() - 150, 2 * half, face.y() - top.y() + 150)

    def _watch(self):
        if not self._watchable():
            self._cursor = None
            self._hover = None
            return
        from PySide6.QtGui import QCursor
        now = time.monotonic()
        point = QPointF(self.window.mapFromGlobal(QCursor.pos()))
        speed = 0.0
        if self._cursor is not None and now > self._cursor[1]:
            last, then = self._cursor
            speed = math.hypot(point.x() - last.x(), point.y() - last.y()) / (now - then)
        self._cursor = (point, now)
        if speed > POUNCE_SPEED and self._head_zone().contains(point):
            if now - self.pounce_at > POUNCE_GAP_S and random.random() < POUNCE_CHANCE:
                self.pounce_at = now
                self.start('pounce', point)
                return
            if now - getattr(self, '_noticed_at', -1e9) > NOTICE_GAP_S:
                self._noticed_at = now          # most passes she only notices it
                if not self.mascot.current_move:
                    self.mascot.play(random.choice(('ears_up', 'ears_up', 'tilt')))
        button = self._button_under(point)
        if button is None:
            self._hover = None
            return
        if self._hover is None or self._hover[0] is not button:
            self._hover = (button, now)
            return
        if now - self._hover[1] >= SWAT_HOVER_S and now - self.swat_at > SWAT_GAP_S and self._reachable(point):
            self._hover = (button, now + 3600)  # this rest on it is decided: once
            if random.random() < SWAT_CHANCE:
                self.swat_at = self.pounce_at = now
                self._hover = None
                self.start('pounce', point)

    def _button_under(self, point: QPointF):
        try:
            widget = self.window.childAt(point.toPoint())
        except RuntimeError:
            return None
        while widget is not None and widget is not self.window:
            if isinstance(widget, QAbstractButton) and not self._ours(widget):
                return widget
            widget = widget.parentWidget()
        return None

    def _reachable(self, point: QPointF) -> bool:
        body = self._drawn(self.puck.pos)
        centre = QPointF(body.center())
        return math.hypot(point.x() - centre.x(), point.y() - centre.y()) <= SWAT_REACH and point.y() < body.bottom()

    def _cursor_point(self) -> QPointF:
        from PySide6.QtGui import QCursor
        return QPointF(self.window.mapFromGlobal(QCursor.pos()))

    def _pounce(self, target):
        """Leap for the pointer like a cat: in the air she keeps homing in on where it is now
        (2026-11-27, user: she used to jump to one fixed spot). Caught, she hangs on it for a few
        seconds, dangling as it moves, then lets go and drops; missed, she lands and sulks."""
        mascot, puck = self.mascot, self.puck
        start = QPointF(puck.pos)
        button = self._button_under(QPointF(target))

        def aim():
            point = self._cursor_point()
            spot = puck.spot_for(LIFT_TOP, point, mirrored=mascot.mirrored)   # her paws, as she faces now
            dx, dy = spot.x() - start.x(), min(POUNCE_DROP, spot.y() - start.y())
            reach = math.hypot(dx, dy)
            if reach > POUNCE_REACH:
                dx, dy = dx * POUNCE_REACH / reach, dy * POUNCE_REACH / reach
            return QPointF(start.x() + dx, start.y() + dy)

        try:
            mascot.stop_move()
            mascot.stick('exclaim')
            first = aim()
            self._face(first.x() < start.x() - 4)
            mascot.play('catch')
            chase = Chase(self, aim, height=18, crouch=.12)
            yield chase
            paws = puck.window_point(LIFT_TOP)
            now_at = self._cursor_point()
            caught = math.hypot(now_at.x() - paws.x(), now_at.y() - paws.y()) < CATCH_RADIUS
            if button is not None:
                self.fx.kick(button, pivot=(.5, 1.0), angle=random.choice((-1, 1)) * 110, y=-60, squash=1.6)
                self._overlay().burst('tap', QPointF(target), self.clock(), .3, direction=-math.pi / 2)
            if caught and self.window.rect().contains(now_at.toPoint()):
                self._overlay().burst('sparkle', paws, self.clock(), .7)
                self._line(random.choice(('抓到了！', '嘿！逮到你了', '喵呜～', '不放手啦～')))
                mascot.stop_move('catch')
                mascot.play('cling')
                yield Dangle(self, random.uniform(*DANGLE_S))
                return                         # let go: she drops, the puck lands her (after_landing)
            if random.random() < .6:
                self._line(random.choice(('欸？跑掉了', '好快！', '下次一定抓到')))
            yield Leap(self, start, height=6, crouch=.0, face=False)
            mascot.stop_move('catch')
            if random.random() < .5:
                mascot.act('pout')
            yield .3
        finally:
            mascot.stop_move('catch')
            mascot.stop_move('cling')

    # ------------------------------------------------------------ wandering on the home page
    def _wander_spot(self):
        window = self.window
        puck = self.puck
        limits = puck.limits()
        start = getattr(window, 'start_button', None)
        bottom = self._rect(start).top() - 4 if _visible(start) else window.height()
        drawn = puck.mascot.docked_size()
        seats = [getattr(window, name, None) for name in SEATS] + self._buttons()[:6]
        seats = [widget for widget in seats if _visible(widget)]
        options = []
        for _ in range(12):
            if seats and random.random() < .5:
                spot = self._seat_spot(random.choice(seats), point=FEET)
            else:
                low, high = max(limits.top(), 150.0 - drawn.height() * .2), min(limits.bottom(), bottom - drawn.height())
                if high <= low:
                    continue
                spot = QPointF(random.uniform(limits.left() + 40, limits.right() - 40), random.uniform(low, high))
            if spot is None or not self._fits(spot):
                continue
            far = math.hypot(spot.x() - puck.pos.x(), spot.y() - puck.pos.y())
            if 120 < far < 700:
                options.append(spot)
        return random.choice(options) if options else None

    def _wander(self, spot):
        mascot = self.mascot
        here = QPointF(self.puck.pos)
        middle = QPointF((here.x() + spot.x()) / 2 + random.uniform(-40, 40), (here.y() + spot.y()) / 2)
        try:
            if random.random() < .5 and self._fits(middle):
                yield Hop(self, middle)
                mascot.play('search')                  # a look round on the way
                yield 1.4
                mascot.stop_move('search')
            yield Hop(self, spot)
            mascot.act(random.choice(('hello', 'stretch', 'hmm', 'yes')))
            yield .8
        finally:
            mascot.stop_move('search')
            self._focus(None)
        self.home = QPointF(self.puck.pos)            # she stays at her new place

    # ------------------------------------------------------------ put down on something
    def landed(self) -> bool:
        """Put down gently with the card folded: on a gear, the book, a header button or a seat she
        gets busy there."""
        puck, mascot = self.puck, self.mascot
        if puck is None or mascot is None or puck.docked or self._gen is not None or mascot.reduced_motion:
            return False
        if getattr(self.chat, 'fold_reason', '') not in ('user', 'start') or self.context() == 'editor':
            return False
        window = self.window
        paws = puck.window_point(PAWS)
        feet = puck.window_point(FEET)
        ring = puck.window_point(RING)
        for name, target in self.candidates():
            if name in ('fix_gear', 'read_book'):
                if self._rect(target).adjusted(-20, -20, 20, 20).contains(paws.toPoint()):
                    return self.start(name, target)
        for button in self._header_buttons():
            if self._rect(button).adjusted(-12, -10, 12, 28).contains(ring.toPoint()):
                return self.start('hang_on', [button])
        under = window.childAt(feet.toPoint() + QPoint(0, 4))
        seats = [getattr(window, name, None) for name in SEATS]
        while under is not None and under is not window:
            if under in seats or isinstance(under, QAbstractButton):
                rect = self._rect(under)
                if abs(feet.y() - rect.top()) < 46 and self._seat_spot(under, feet.x()) is not None:
                    return self.start('sit_on', (under, feet.x()))
                break
            under = under.parentWidget()
        return False


__all__ = ['BunnyErrands', 'Beats', 'Hop', 'Leap', 'Step', 'Wait', 'icon_centre']
