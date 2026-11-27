"""Touching 「问问兔白」: what each part of her does when tapped, rubbed or pulled (2026-11-26).

User (2026-11-26): far more and richer interactions, like a character that reacts to everything,
not plain Live2D. From the drafts (``tmp/bunny-physics-drafts-20261126/``), on top of picking her
up (``bunny_puck``):

* rub the top of her head (the pointer going back and forth, no button): she is patted — ears lie
  back, eyes shut, cheeks pink, hearts, she leans into the hand;
* pull an ear: it stretches toward the pointer and she winces; let go and it springs back; pull too
  far and she is lifted by that ear;
* tap a cheek: it squashes, she blushes; three taps in a row and she pouts;
* tap the glasses: they hop and flash; the paws: a high five; the key ring: it spins round;
* wiggle the pointer fast over her paws or face: she is tickled;
* shaken while held, she is dizzy after; the pointer rushing past her makes her jump.

The head and face keep the old tap (``BunnyChat.poke``: a hop and a line or a tip). Her short
lines go through the chat box like a poke's, and only when the chat has nothing else to say.
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QTimer

PAT_TURNS = 3                 # direction changes of a rub within TURN_WINDOW_S that make a pat
TICKLE_TURNS = 5
TURN_WINDOW_S = 1.4
TICKLE_SPEED = 450.0          # px/s of the pointer over her paws or face
PAT_HOLD_S = 0.5              # the pat goes on this long after the pointer stops
HEART_EVERY_S = 1.6
CHEEK_TAPS = 3                # taps within CHEEK_WINDOW_S that make her pout
CHEEK_WINDOW_S = 2.5
LINE_GAP_S = 1.0              # at most one touch line this often
EAR_PULL_LIFT = 1.4           # an ear pulled this many ear-lengths past its own lifts her by it


class _Rub:
    """Direction changes of the pointer moving across her (a rub, a tickle)."""

    def __init__(self):
        self.last_x = None
        self.direction = 0
        self.travel = 0.0
        self.turns = []

    def feed(self, x: float, now: float, min_travel: float) -> int:
        if self.last_x is not None:
            dx = x - self.last_x
            if abs(dx) >= .5:
                sign = 1 if dx > 0 else -1
                if sign != self.direction:
                    if abs(self.travel) > min_travel:
                        self.turns.append(now)
                    self.direction, self.travel = sign, 0.0
                self.travel += dx
        self.last_x = x
        self.turns = [t for t in self.turns if now - t < TURN_WINDOW_S]
        return len(self.turns)

    def reset(self):
        self.last_x, self.direction, self.travel, self.turns = None, 0, 0.0, []


class BunnyTouch:
    def __init__(self, chat):
        self.chat = chat
        self.pat = _Rub()
        self.tickle = _Rub()
        self.patting = False
        self.heart_at = -9.0
        self.cheek_taps = []
        self.line_at = -9.0
        self.tug = None                # (ear id, moved, said)
        self.hover_at = None           # (x, now) of the last hover move, for its speed
        self.flip_said = False
        self.shake_said = False

    # ------------------------------------------------------------ helpers
    @property
    def mascot(self):
        return self.chat.mascot

    @property
    def life(self):
        mascot = self.mascot
        return mascot.life if mascot is not None else None

    def _now(self) -> float:
        return self.mascot.clock()

    def _free(self) -> bool:
        chat = self.chat
        return not (chat.busy or chat.typer.running or chat._pending)

    def _line(self, text: str, mood: str, chance: float = 1.0):
        """A short line of hers in the chat box (only when it has nothing else going on)."""
        from . import bunny_persona
        now = self._now()
        if random.random() > chance or now - self.line_at < LINE_GAP_S:
            return
        self.line_at = now
        if not self._free():
            self.chat._spoke('喵', 'surprised')
            return
        self.chat._asked = False
        self.chat.say(bunny_persona.BunnyReply(lines=[text], mood=mood))

    def _sfx(self, name: str) -> None:
        from .bunny_sfx import play
        play(self.chat, name)

    def _at_rest(self) -> bool:
        puck = self.chat.puck
        return puck is None or puck.docked or puck.mode == 'rest'

    # ------------------------------------------------------------ taps
    def click(self, region: str | None):
        life, mascot = self.life, self.mascot
        if life is None:
            self.chat.poke()
            return
        now = self._now()
        if region == 'ring':
            life.part('ring').spin += random.choice((-1, 1)) * 26
            self._sfx('catch')                     # 2026-11-27: the keychain rings
            mascot.stick('sparkle')
            self._line('叮铃叮铃～', 'happy', .6)
        elif region == 'glasses':
            life.part('glasses').lift_v -= 420
            life.face(now, flash=True, glare=True)
            self._sfx('sparkle')
            self._line('看清楚了！', 'excited', .7)
        elif region in ('cheekL', 'cheekR'):
            side = -1 if region == 'cheekL' else 1
            cheek = mascot.rig_to_widget(368 if side < 0 else 548, 578) - mascot.com_point()
            life.squash.kick(life.carried.angle if life.carried is not None else 0.0, 2.6,
                             (cheek.x(), cheek.y()), now)
            life.lean_target, life.lean_until = -side * .12, now + .35
            life.face(now, blush=1.6, open_=.22)
            self._sfx('pop')                       # a boop on the cheek
            self.cheek_taps = [t for t in self.cheek_taps if now - t < CHEEK_WINDOW_S] + [now]
            if len(self.cheek_taps) >= CHEEK_TAPS:
                self.cheek_taps = []
                mascot.act('pout')
                self._line('哼！不准再戳脸了', 'teasing')
            else:
                self._line(random.choice(('噗！', '唔……', '脸、脸颊！')), 'shy', .7)
        elif region == 'paws':
            life.part('paws').lift_v -= 520
            mascot.hop()
            mascot.stick('sparkle')
            self._line('耶！击掌！', 'excited')
        elif region in ('earL', 'earR'):
            life.part(region).spin += (-1 if region == 'earL' else 1) * 10
            self._sfx('pip')
            self._line('耳朵好敏感……', 'shy', .7)
        else:
            self.chat.poke()

    # ------------------------------------------------------------ an ear pulled
    def start_tug(self, ear: str, point: QPointF):
        life = self.life
        if life is None:
            return
        self.tug = [ear, False, False]
        life.tugging = True
        state = life.part(ear)
        state.k_mul, state.limit_mul = 5.0, 1.25

    def update_tug(self, point: QPointF):
        """The pointer at ``point`` (her widget's coordinates) pulls the ear; the ear's tip (a rig
        point) when she should now be lifted by it, else None."""
        from ..design.bunny_physics import PART_BY_ID, wrap
        life, mascot = self.life, self.mascot
        if life is None or self.tug is None:
            return None
        ear = self.tug[0]
        part, state = PART_BY_ID[ear], life.part(ear)
        pivot = mascot.rig_to_widget(*part.pivot)
        vx, vy = point.x() - pivot.x(), point.y() - pivot.y()
        reach = part.length * mascot.scale
        distance = math.hypot(vx, vy)
        if distance > 3:
            self.tug[1] = True
        state.target = max(-1.3, min(1.3, wrap(math.atan2(vy, vx) - part.angle)))
        over = max(0.0, distance - reach)
        state.stretch_target = max(0.0, min(.42, over / reach * .6))
        now = self._now()
        pull = min(1.0, over / (reach * EAR_PULL_LIFT))
        life.lean_target, life.lean_until = max(-.3, min(.3, vx / 240)) * pull, now + .3
        if over > reach * .2:
            life.face(now, closed=.15, open_=.15)
            if not self.tug[2]:
                self.tug[2] = True
                mascot.stick('sweat')
                self._line('痛痛痛——耳朵不行！', 'surprised')
        if over > reach * EAR_PULL_LIFT:
            self._end_tug_state()
            self._line('耳朵要断了啦！', 'scared')
            return part.tip
        return None

    def _end_tug_state(self):
        life = self.life
        if self.tug is None or life is None:
            self.tug = None
            return
        state = life.part(self.tug[0])
        state.target, state.k_mul, state.limit_mul, state.stretch_target = 0.0, 1.0, 1.0, 0.0
        life.tugging = False
        life.lean_until = 0.0
        self.tug = None

    def end_tug(self):
        tug = self.tug
        self._end_tug_state()
        if tug is None:
            return
        ear, moved, said = tug
        if not moved:
            self.click(ear)
        elif said:
            QTimer.singleShot(250, lambda: self._line('哼……', 'teasing'))

    # ------------------------------------------------------------ hovering
    def hover(self, event):
        """The pointer moving over her with no button: rubs and tickles."""
        from ..design.bunny_physics import HEAD, region_at
        life, mascot = self.life, self.mascot
        if life is None or not self._at_rest():
            return
        now = self._now()
        point = QPointF(event.position())
        region = region_at(*mascot.rig_point(point))
        speed = 0.0
        if self.hover_at is not None and now > self.hover_at[1]:
            speed = abs(point.x() - self.hover_at[0]) / max(1e-3, now - self.hover_at[1])
        self.hover_at = (point.x(), now)
        if region == 'head':
            if self.pat.feed(point.x(), now, 8) >= PAT_TURNS or now < life.patted_until:
                if now >= life.patted_until:
                    self._sfx('pat')
                    self._line(random.choice(('嘿嘿……', '再摸一下下', '好舒服～')), 'shy')
                life.patted_until = now + PAT_HOLD_S
                head = mascot.rig_to_widget(*HEAD)
                life.lean_target = max(-1.0, min(1.0, (point.x() - head.x()) / 40)) * .1
                life.lean_until = life.patted_until
                if now - self.heart_at > HEART_EVERY_S:
                    self.heart_at = now
                    mascot.stick('heart')
        else:
            self.pat.reset()
        if region in ('paws', 'face'):
            turns = self.tickle.feed(point.x(), now, 6)
            if (speed > TICKLE_SPEED and turns >= TICKLE_TURNS) or now < life.tickled_until:
                if now >= life.tickled_until:
                    self._sfx('giggle')
                    mascot.stick('notes')
                    self._line('哈哈哈好痒！不要啦～', 'happy')
                    life.tickled_until = now + 1.8
                else:
                    life.tickled_until = max(life.tickled_until, now + .3)
        else:
            self.tickle.reset()

    def leave(self):
        self.pat.reset()
        self.tickle.reset()
        self.hover_at = None

    # ------------------------------------------------------------ the puck's moments
    def picked_up(self, by_ring: bool):
        self.flip_said = self.shake_said = False
        lines = ('被挂起来了～', '叮铃叮铃', '要去哪里？') if by_ring else ('哇啊——', '放、放我下来！', '咦咦？')
        self._line(random.choice(lines), 'surprised', .5)

    def while_held(self, phys):
        from ..design.bunny_physics import wrap
        if not self.flip_said and abs(wrap(phys.pose.angle)) > 2.3:
            self.flip_said = True
            self._line('头朝下了啦！', 'surprised')
        if not self.shake_said and phys.hold is not None and phys.hold.shook:
            self.shake_said = True
            self._line('不要摇了啦～', 'scared')

    def hopping_up(self):
        self._line('嘿咻！', 'happy', .5)

    def bumped(self, power: float):
        if power > .6:
            self._line(random.choice(('呜哇！', '痛……', '呀！')), 'surprised', .5)

    def startle(self):
        """The pointer rushed past her on the card."""
        mascot = self.mascot
        if mascot is None or not self._at_rest() or not self._free():
            return
        mascot.act('startled')
        mascot.hop()
        self.chat._spoke('呀', 'surprised')


__all__ = ['BunnyTouch']
