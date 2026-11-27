"""What keeps 「问问兔白」 alive between moves: swinging parts, squash, gaze and touch faces (2026-11-26).

``BunnyMascot.enable_physics`` gives the mascot one of these. It steps ``bunny_physics.Rig`` along
the body's pose every frame (the pose the puck feeds while she is carried, or her idle swing on the
card), keeps her squash spring, turns her eyes and the head-turn parallax toward the pointer, and
holds the faces touch reactions ask for (eyes shut while patted, a wince, a blush, a flash on the
glasses). Nothing here paints; ``BunnyMascot.paintEvent`` reads it.
"""
from __future__ import annotations

import math
import random

from . import bunny_physics as bp

GLANCE_AFTER_S = 2.5          # the pointer still this long: she looks around by herself
STARTLE_SPEED = 2300.0        # px/s of a pointer rushing past her
STARTLE_GAP_S = 5.0


class BunnyLife:
    def __init__(self):
        self.rig = bp.Rig()
        self.squash = bp.Squash()
        self.carried: bp.Pose | None = None      # her body in window px while the puck has her
        self.gravity = bp.GRAVITY                 # the puck lowers it while she flies
        self.squash_goal = (0.0, None, (0.0, 0.0))
        self.gaze = [0.0, 0.0, 0.0, 0.0]          # x, y, vx, vy in -1..1
        self.gaze_target = (0.0, 0.0)
        self.next_glance = 0.0
        self.cursor = None
        self.cursor_t = 0.0
        self.cursor_moved = -9.0
        self.cursor_speed = 0.0
        self.closed_until = 0.0
        self.open_until = 0.0
        self.talk_until = 0.0
        self.blush = 0.0
        self.blush_until = 0.0
        self.flash_at = -9.0
        self.glare_at = -9.0
        self.patted_until = 0.0
        self.tickled_until = 0.0
        self.lean = 0.0                           # rad, render only (into a patting hand, toward a tug)
        self.lean_target = 0.0
        self.lean_until = 0.0
        self.tugging = False                      # an ear is being pulled: its spring target is the tug's
        self.struggling = False
        self.on_startle = None                    # called when the pointer rushes past her
        self.startle_at = -9.0
        self.next_twitch = 3.0
        self.focus = None                         # 2026-11-26: (x, y) in -1..1 she keeps looking at (her book, a bolt)
        self.last = None
        self.now = 0.0

    # ------------------------------------------------------------ faces
    def face(self, now: float, *, closed: float = 0.0, open_: float = 0.0, talk: float = 0.0,
             blush: float = 0.0, flash: bool = False, glare: bool = False):
        if closed:
            self.closed_until = max(self.closed_until, now + closed)
        if open_:
            self.open_until = max(self.open_until, now + open_)
        if talk:
            self.talk_until = max(self.talk_until, now + talk)
        if blush:
            self.blush, self.blush_until = max(self.blush, blush), now + 1.2
        if flash:
            self.flash_at = now
        if glare:
            self.glare_at = now

    def eyes_closed(self, now: float) -> bool:
        return now < self.closed_until or now < self.patted_until or now < self.tickled_until

    def mouth_open(self, now: float) -> bool:
        if now < self.open_until:
            return True
        if now < self.talk_until or now < self.tickled_until:
            return int(now / .09) % 2 == 0
        return self.struggling and int(now / .18) % 3 == 0

    def blush_now(self, now: float) -> float:
        fading = max(0.0, min(1.0, (self.blush_until - now) / .5)) if now < self.blush_until else 0.0
        return max(self.blush * fading, 1.3 if now < self.patted_until else 0.0)

    def flash(self, now: float) -> float:
        k = (now - self.flash_at) / .6
        return math.sin(math.pi * k) if 0 <= k < 1 else 0.0

    def glare(self, now: float):
        k = (now - self.glare_at) / .5
        return k if 0 <= k < 1 else None

    # ------------------------------------------------------------ parts
    def part(self, name: str) -> bp.PartState:
        return self.rig.parts[name]

    def rebase(self):
        """She jumped between frames (on and off the card): parts keep their swing, not a jolt."""
        self.rig.reset()

    # ------------------------------------------------------------ the frame
    def advance(self, now: float, scale: float, docked_angle: float, face_global=None, cursor=None,
                body_global=None, reach: float = 0.0, docked: bool = True):
        """``face_global``/``body_global`` are her face and body centre on screen, ``cursor`` the pointer."""
        dt = 0.0 if self.last is None else min(0.1, max(0.0, now - self.last))
        self.last = now
        self.now = now
        rig = self.rig
        if self.struggling:
            rig.parts['feet'].target = .28 * math.sin(now * 2 * math.pi * 3)
            rig.parts['paws'].target = -.18 * math.sin(now * 2 * math.pi * 3 + 1)
        elif now < self.tickled_until:
            rig.parts['paws'].target = .12 * math.sin(now * 2 * math.pi * 9)
            rig.parts['feet'].target = .1 * math.sin(now * 2 * math.pi * 7)
        else:
            rig.parts['feet'].target *= .9
            rig.parts['paws'].target *= .9
        if not self.tugging:                           # patted, her ears lie back
            flat = .5 if now < self.patted_until else 0.0
            rig.parts['earL'].target, rig.parts['earR'].target = -flat, flat
        if docked and now > self.next_twitch:          # a single ear flicks now and then
            self.next_twitch = now + random.uniform(3, 7)
            ear = random.choice(('earL', 'earR'))
            rig.parts[ear].spin += (-1 if ear == 'earL' else 1) * random.uniform(5, 9)
        pose = self.carried if self.carried is not None else bp.Pose(0.0, 0.0, docked_angle, scale)
        rig.advance(dt, pose, self.gravity)
        target, axis, pivot = self.squash_goal
        steps = max(1, round(dt / bp.STEP))
        for _ in range(steps if dt else 0):
            self.squash.step(dt / steps, now, target, axis, pivot)
        m = 1 - math.exp(-dt * 10)
        self.lean += ((self.lean_target if now < self.lean_until else 0.0) - self.lean) * m
        self._look(now, dt, face_global, cursor, body_global, reach, docked)

    def _look(self, now, dt, face, cursor, body, reach, docked):
        if cursor is not None:
            if self.cursor is not None and dt > 0:
                moved = math.hypot(cursor[0] - self.cursor[0], cursor[1] - self.cursor[1])
                if moved > 0.5:
                    self.cursor_moved = now
                self.cursor_speed = moved / max(dt, 1e-3)
                if (docked and body is not None and self.on_startle is not None and self.cursor_speed > STARTLE_SPEED
                        and now - self.startle_at > STARTLE_GAP_S):
                    d = math.hypot(cursor[0] - body[0], cursor[1] - body[1])
                    if reach * 1.1 < d < reach * 2.6:
                        self.startle_at = now
                        self.on_startle()
            self.cursor = cursor
        if self.focus is not None:
            self.gaze_target = (max(-1.0, min(1.0, self.focus[0])), max(-1.0, min(1.0, self.focus[1])))
            w = 14.0
        elif face is not None and cursor is not None and (now - self.cursor_moved < GLANCE_AFTER_S or self.carried is not None):
            size = max(60.0, reach * 2.2)
            self.gaze_target = (max(-1.0, min(1.0, (cursor[0] - face[0]) / size)),
                                max(-1.0, min(1.0, (cursor[1] - face[1]) / (size * .85))))
            w = 11.0
        else:
            if now > self.next_glance:
                self.next_glance = now + random.uniform(1.2, 3.2)
                self.gaze_target = (random.uniform(-.8, .8), random.uniform(-.5, .4))
            w = 20.0
        g = self.gaze
        for i in (0, 1):
            g[2 + i] += (w * w * (self.gaze_target[i] - g[i]) - 2 * w * g[2 + i]) * dt
            g[i] += g[2 + i] * dt

    def busy(self, now: float) -> bool:
        """Something is still moving: keep painting."""
        return (self.carried is not None or not self.rig.settled() or not self.squash.resting
                or abs(self.gaze[2]) + abs(self.gaze[3]) > .01 or now < self.lean_until + .5
                or now < self.tickled_until or self.tugging)


__all__ = ['BunnyLife']
