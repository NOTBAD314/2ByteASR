"""兔白 as a real plush: a pendulum from wherever she is held, gravity, and parts that swing (2026-11-26).

User (2026-11-26): 「问问兔白」 should be far more interactive; picked up she should sway with the
size of the motion and move with real physics, like a character you play with, not plain Live2D.
Of three drafts (``tmp/bunny-physics-drafts-20261126/``) they picked **B 真实布偶**, then asked for
its feel to sit between B and **C Q弹麻糬** (C's stretch, bounce and floppy ears, a little less):

* held anywhere, she hangs from that point: a rigid pendulum about the grab point, centre of mass
  in the middle of her head. The hand's acceleration drives the swing, so a bigger swing of the
  hand swings her more; held by a foot she hangs upside down. Held by the key ring she is a
  two-link pendulum (the ring swings first, her body a beat later).
* let go, gravity takes her: she lands on the window's bottom, bounces, rolls, and when she has
  stopped upside down she crouches and hops upright (``BodyPhysics``).
* every loose part (ears, hair, bangs, sideburns, back hair, hair clip, key ring, paws, feet) is a
  damped spring pendulum on its own pivot, driven by the real acceleration of that pivot and by
  gravity (``Rig``): follow-through and overlapping action, as Live2D's multi-step pendulums and
  Spine's physics constraints do it.
* she stretches along her speed and squashes against what she hits, keeping her volume (``Squash``).

Pure maths, no widgets. Positions are in window pixels (y down, angles clockwise in radians); rig
points are on the rig's 900 x 888 canvas (``assets/mascot/bunny/rig.json``) and ``scale`` is pixels
per canvas unit. These are the character's physical constants, not interface tweens: the
no-overshoot rule of ``motion_tokens`` is for UI transitions, and the swing and bounce here are
what the user asked for.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Rig canvas points (rig.json and the layers' alpha bounds).
COM = (458.0, 432.0)          # centre of mass: the middle of her head
FEET = (455.0, 650.0)
RING_TOP = (452.0, 44.0)      # where a finger goes through the key ring
HOOK = (452.6, 218.0)         # where the ring hangs on her head
FACE = (458.0, 525.0)
HEAD = (458.0, 250.0)
COLL_R = 255.0                # her round body for walls and floor (canvas units; her hair is 561 wide)
GYRATION = 150.0              # radius of gyration about the centre of mass (canvas units)
ROOM_R = 470.0                # every drawn pixel lies within this of the centre of mass, with squash room

STEP = 1 / 240                # the simulation's fixed step (s)

# Between drafts B 真实布偶 and C Q弹麻糬 (user, 2026-11-26: "B and C in between; C is fun too, just a
# little less of it"): about 60 % of the way from B toward C.
GRAVITY = 2400.0              # px/s² while she hangs or sits (the parts feel this)
GRAVITY_FLY = 1700.0          # px/s² once thrown: a little floaty, so she sails and bounces
HAND_FOLLOW = 46.0            # 1/s: the hand point follows the pointer (critically damped)
SWING_DAMPING = 0.95          # 1/s on the swing
INERTIA = 0.84                # how much of the hand's acceleration reaches her (Spine's "inertia")
SOFT_LIMIT = 1.9              # rad from hanging: beyond it the air gets thick (no endless loops)
LINK_W, LINK_Z = 20.0, 0.38   # the key ring between finger and head
LINK_LIMIT = 1.2              # rad the ring may bend against her head
RESTITUTION = 0.56
AIR_DRAG = 0.065              # 1/s
AIR_SPIN = 0.27               # 1/s on her spin in the air
ROLL_K = 0.4                  # I / (m R²): how readily a push turns into rolling
ROLL_DRAG = 2.0               # 1/s rolling along the floor
RIGHT_K = 34.0                # the twist that turns her upright during the righting hop
HIT_SPEED = 240.0             # px/s into an edge that gives feedback
MAX_THROW = 3800.0
MAX_FLIGHT_S = 14.0
PART_DAMPING = 0.75           # ears and hair keep swinging a little longer than B
PART_GAIN = 1.18
STRETCH = 0.23                # stretch along her speed at 3500 px/s
HANG_SAG = 0.035              # held, she sags a little toward the floor like soft mochi
SQUASH_K, SQUASH_Z = 270.0, 0.30
IMPACT_SQUASH = 0.37
SHAKE_SPEED = 650.0           # px/s of the hand that counts toward a shake
SHAKE_FLIPS = 5               # direction changes within SHAKE_WINDOW_S: she gets dizzy
SHAKE_WINDOW_S = 1.2

# Head-turn parallax (Live2D AngleX/Y): near layers move more than far ones.
DEPTH = {'后发': -.55, '左耳': -.3, '右耳': -.3, '身体': .05, '脚': .05, '6脸': .35, '眉毛': .85, '闭嘴': .8,
         '张嘴': .8, '眼睛': .95, '闭眼': .9, '底色': -.2, '睫毛': .95, '鬓角左': .45, '鬓角右': .45, '左发': .5,
         '右发': .5, '刘海': .7, '双手': .25, '高光': .55, '头饰': .55, '眼镜': 1.0, '反光': 1.0, '腮红': .75,
         '17钥匙': -.35, '反光2': -.35}
GAZE_SHIFT = (18.0, 10.0)     # canvas units at depth 1, looking fully sideways / up or down


def wrap(angle: float) -> float:
    angle = (angle + math.pi) % (2 * math.pi)
    return angle - math.pi


def rot(x: float, y: float, angle: float) -> tuple[float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return x * c - y * s, x * s + y * c


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


@dataclass(frozen=True)
class Part:
    """A loose part: its layers turn about ``pivot``; ``tip`` gives its length and rest direction."""
    id: str
    layers: tuple
    pivot: tuple
    tip: tuple
    k: float                  # 1/s² spring back to its drawn pose
    z: float                  # damping ratio
    limit: float              # rad either way
    gain: float = 1.0         # 0: no swing (only lifts)

    @property
    def length(self) -> float:
        return math.hypot(self.tip[0] - self.pivot[0], self.tip[1] - self.pivot[1])

    @property
    def direction(self) -> tuple[float, float]:
        n = self.length
        return (self.tip[0] - self.pivot[0]) / n, (self.tip[1] - self.pivot[1]) / n

    @property
    def angle(self) -> float:
        return math.atan2(self.tip[1] - self.pivot[1], self.tip[0] - self.pivot[0])


PARTS = (
    Part('earL', ('左耳',), (346.6, 256.4), (302, 92), 170, .26, 1.15),
    Part('earR', ('右耳',), (573.2, 264.1), (616, 92), 170, .26, 1.15),
    Part('ring', ('17钥匙', '反光2'), (452.6, 218), (452, 44), 115, .14, math.pi),
    Part('hairL', ('左发',), (414.8, 262), (300, 490), 120, .38, .12, .7),
    Part('hairR', ('右发',), (566, 300), (650, 500), 120, .38, .12, .7),
    Part('bangs', ('刘海',), (458, 288), (460, 515), 150, .42, .08, .6),
    Part('sideL', ('鬓角左',), (300, 388), (288, 610), 95, .32, .2, .9),
    Part('sideR', ('鬓角右',), (612, 384), (628, 610), 95, .32, .2, .9),
    Part('back', ('后发',), (459, 250), (459, 665), 170, .5, .05, .5),
    Part('clip', ('头饰',), (338, 382), (336, 458), 130, .3, .3, .8),
    Part('feet', ('脚',), (456, 622), (456, 667), 210, .32, .35, .8),
    Part('paws', ('双手',), (458.5, 598), (458, 632), 230, .32, .25, .8),
    Part('glasses', ('眼镜', '反光'), (458, 548), (458, 560), 400, .6, .05, 0.0),
)
PART_BY_ID = {part.id: part for part in PARTS}
LAYER_PART = {name: part for part in PARTS for name in part.layers}


@dataclass
class PartState:
    angle: float = 0.0        # rad, relative to her body
    spin: float = 0.0         # rad/s
    target: float = 0.0       # where the spring pulls (a tug, flattened ears)
    k_mul: float = 1.0
    limit_mul: float = 1.0
    lift: float = 0.0         # canvas units along y (glasses pushed up, paws raised)
    lift_v: float = 0.0
    lift_target: float = 0.0
    stretch: float = 0.0      # along the part (an ear pulled long)
    stretch_v: float = 0.0
    stretch_target: float = 0.0
    ready: bool = False
    x: float = 0.0            # the pivot's last place, speed and filtered acceleration (px)
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    ax: float = 0.0
    ay: float = 0.0


@dataclass
class Pose:
    """Where her body is: centre of mass (px), angle (rad, clockwise), px per canvas unit."""
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    scale: float = 0.25

    def world(self, lx: float, ly: float) -> tuple[float, float]:
        dx, dy = rot((lx - COM[0]) * self.scale, (ly - COM[1]) * self.scale, self.angle)
        return self.x + dx, self.y + dy


@dataclass
class Squash:
    """Volume-keeping squash and stretch: ``e`` along ``axis`` (rad), about ``pivot`` (px from her centre)."""
    e: float = 0.0
    v: float = 0.0
    axis: float = math.pi / 2
    pivot: tuple = (0.0, 0.0)
    impact_at: float = -9.0

    def kick(self, axis: float, speed: float, pivot: tuple, now: float):
        self.axis, self.pivot, self.impact_at = axis, pivot, now
        self.v -= speed

    def step(self, h: float, now: float, target: float, axis: float | None, pivot: tuple):
        if axis is not None and now - self.impact_at > .22:
            m = 1 - math.exp(-h * 14)                    # ease the axis (axes are the same every π)
            cx, sy = math.cos(2 * self.axis), math.sin(2 * self.axis)
            self.axis = math.atan2(sy + (math.sin(2 * axis) - sy) * m, cx + (math.cos(2 * axis) - cx) * m) / 2
        if now - self.impact_at > .25:
            m = 1 - math.exp(-h * 10)
            self.pivot = (self.pivot[0] + (pivot[0] - self.pivot[0]) * m, self.pivot[1] + (pivot[1] - self.pivot[1]) * m)
        c = 2 * SQUASH_Z * math.sqrt(SQUASH_K)
        self.v += (SQUASH_K * (target - self.e) - c * self.v) * h
        self.e = clamp(self.e + self.v * h, -.45, .6)

    @property
    def resting(self) -> bool:
        return abs(self.e) < 1e-3 and abs(self.v) < 1e-2


class Rig:
    """The loose parts, stepped along a sequence of body poses."""

    def __init__(self):
        self.parts = {part.id: PartState() for part in PARTS}
        self.pose = None              # the last pose stepped to
        self._spin = 0.0              # the body's own angular speed and filtered acceleration
        self._alpha = 0.0
        self.ring_link = None         # (angle, spin) of the key ring while she hangs from it

    def reset(self):
        for state in self.parts.values():
            state.ready = False
        self.pose = None

    def advance(self, dt: float, pose: Pose, gravity: float = GRAVITY):
        """Step from the last pose to ``pose`` over ``dt`` seconds, in fixed steps."""
        if self.pose is None:
            self.pose = Pose(pose.x, pose.y, pose.angle, pose.scale)
            return
        if dt <= 0:
            return
        dt = min(dt, 0.1)                 # a stall (a hidden window) is not a fling
        start = self.pose
        steps = max(1, min(48, round(dt / STEP)))
        h = dt / steps
        turn = wrap(pose.angle - start.angle)
        for i in range(1, steps + 1):
            k = i / steps
            here = Pose(start.x + (pose.x - start.x) * k, start.y + (pose.y - start.y) * k,
                        start.angle + turn * k, pose.scale)
            self._step(h, here, gravity)
        self.pose = Pose(pose.x, pose.y, pose.angle, pose.scale)

    def _step(self, h: float, pose: Pose, gravity: float):
        previous = self.pose
        spin = wrap(pose.angle - previous.angle) / h if previous is not None else 0.0
        self._alpha += (clamp((spin - self._spin) / h, -3000, 3000) - self._alpha) * .35
        self._spin = spin
        self.pose = pose
        for part in PARTS:
            state = self.parts[part.id]
            x, y = pose.world(*part.pivot)
            if not state.ready:
                state.x, state.y, state.vx, state.vy, state.ax, state.ay = x, y, 0.0, 0.0, 0.0, 0.0
                state.ready = True
            vx, vy = (x - state.x) / h, (y - state.y) / h
            ax, ay = (vx - state.vx) / h, (vy - state.vy) / h
            state.x, state.y, state.vx, state.vy = x, y, vx, vy
            state.ax += (clamp(ax, -8e4, 8e4) - state.ax) * .35
            state.ay += (clamp(ay, -8e4, 8e4) - state.ay) * .35
            state.lift_v += (380 * (state.lift_target - state.lift) - 2 * .3 * math.sqrt(380) * state.lift_v) * h
            state.lift += state.lift_v * h
            state.stretch_v += (260 * (state.stretch_target - state.stretch)
                                - 2 * .32 * math.sqrt(260) * state.stretch_v) * h
            state.stretch = clamp(state.stretch + state.stretch_v * h, -.1, .5)
            if part.gain == 0:
                continue
            if part.id == 'ring' and self.ring_link is not None:
                state.angle, state.spin = wrap(self.ring_link[0] - pose.angle), self.ring_link[1] - spin
                continue
            d0x, d0y = part.direction
            dx, dy = rot(d0x, d0y, pose.angle + state.angle)
            tx, ty = -dy, dx
            fx, fy = -state.ax, gravity - state.ay
            reach = part.length * pose.scale
            # The drawn pose already holds up against gravity: only the change from it drives.
            drive = ((fx * tx + fy * ty) - gravity * d0x) / reach
            k = part.k * state.k_mul
            c = 2 * part.z * PART_DAMPING * math.sqrt(k)
            off = wrap(state.angle - state.target) if part.id == 'ring' else state.angle - state.target
            accel = part.gain * PART_GAIN * (drive - self._alpha) - k * off - c * state.spin
            state.spin = clamp(state.spin + accel * h, -60, 60)
            state.angle += state.spin * h
            if part.id == 'ring':
                state.angle = wrap(state.angle)
            else:
                limit = part.limit * state.limit_mul
                if state.angle > limit:
                    state.angle, state.spin = limit, (state.spin * -.3 if state.spin > 0 else state.spin)
                elif state.angle < -limit:
                    state.angle, state.spin = -limit, (state.spin * -.3 if state.spin < 0 else state.spin)

    def settled(self) -> bool:
        return all(abs(s.spin) < .02 and abs(s.angle - s.target) < .01 and abs(s.lift_v) < .5
                   and abs(s.stretch_v) < .01 for s in self.parts.values())


@dataclass
class Hold:
    link: bool                     # hanging from the key ring
    grab: tuple                    # canvas point she hangs from (the ring's hook when ``link``)
    hand: list                     # [x, y, vx, vy] of the hand point (px)
    offset: tuple = (0.0, 0.0)     # the ring slides onto the finger: pointer - ring top at the start
    offset_k: float = 1.0
    psi: float = 0.0               # the ring's angle and spin (link)
    psi_v: float = 0.0
    pivot: tuple = (0.0, 0.0)      # the pivot's last place, speed, filtered acceleration
    pivot_v: tuple = (0.0, 0.0)
    pivot_a: tuple = (0.0, 0.0)
    flips: list = field(default_factory=list)
    last_sign: int = 0
    shook: bool = False


class BodyPhysics:
    """Her body: held (a pendulum from the grab point), flying with gravity, rolling, righting."""

    def __init__(self, scale: float):
        self.pose = Pose(scale=scale)
        self.vx = self.vy = 0.0
        self.spin = 0.0
        self.hold: Hold | None = None
        self.flight_s = 0.0
        self.on_floor = False
        self.righting = False
        self.now = 0.0

    # ------------------------------------------------------------ held
    def grab(self, local: tuple, world: tuple, link: bool):
        """Picked up at canvas point ``local``, which is at window point ``world`` (the pointer)."""
        pose = self.pose
        if link:
            top = pose.world(*RING_TOP)
            hook = pose.world(*HOOK)
            self.hold = Hold(True, HOOK, [top[0], top[1], self.vx, self.vy],
                             offset=(world[0] - top[0], world[1] - top[1]), offset_k=0.0,
                             psi=pose.angle, psi_v=self.spin, pivot=hook, pivot_v=(self.vx, self.vy))
        else:
            self.hold = Hold(False, (local[0], local[1]), [world[0], world[1], self.vx, self.vy],
                             pivot=(world[0], world[1]), pivot_v=(self.vx, self.vy))
        self.righting = False

    def hanging_angle(self) -> float:
        """The angle she hangs at, still, from the current grab point."""
        gx, gy = self.hold.grab
        return math.pi / 2 - math.atan2(COM[1] - gy, COM[0] - gx)

    def step_held(self, h: float, target: tuple, bounds: tuple):
        self.now += h
        hold, pose = self.hold, self.pose
        left, top, right, bottom = bounds
        tx, ty = clamp(target[0], left + 8, right - 8), clamp(target[1], top + 8, bottom - 8)
        if hold.offset_k < 1:
            hold.offset_k = min(1.0, hold.offset_k + h / .22)
            rest = 1 - _smooth(hold.offset_k)
            tx, ty = tx - hold.offset[0] * rest, ty - hold.offset[1] * rest
        hand, w = hold.hand, HAND_FOLLOW
        ax = w * w * (tx - hand[0]) - 2 * w * hand[2]
        ay = w * w * (ty - hand[1]) - 2 * w * hand[3]
        hand[2] += ax * h
        hand[3] += ay * h
        hand[0] += hand[2] * h
        hand[1] += hand[3] * h
        s = pose.scale
        if hold.link:
            now_angle = math.atan2(pose.y - hand[1], pose.x - hand[0])
            rest_angle = math.atan2(COM[1] - RING_TOP[1], COM[0] - RING_TOP[0])
            hold.psi_v += (LINK_W * LINK_W * wrap(now_angle - rest_angle - hold.psi) - 2 * LINK_Z * LINK_W * hold.psi_v) * h
            hold.psi += hold.psi_v * h
            bend = wrap(hold.psi - pose.angle)
            if abs(bend) > LINK_LIMIT:
                hold.psi, hold.psi_v = pose.angle + math.copysign(LINK_LIMIT, bend), self.spin
            vx, vy = rot((HOOK[0] - RING_TOP[0]) * s, (HOOK[1] - RING_TOP[1]) * s, hold.psi)
            pivot = (hand[0] + vx, hand[1] + vy)
        else:
            pivot = (hand[0], hand[1])
        pvx, pvy = (pivot[0] - hold.pivot[0]) / h, (pivot[1] - hold.pivot[1]) / h
        pax = hold.pivot_a[0] + (clamp((pvx - hold.pivot_v[0]) / h, -6e4, 6e4) - hold.pivot_a[0]) * .5
        pay = hold.pivot_a[1] + (clamp((pvy - hold.pivot_v[1]) / h, -6e4, 6e4) - hold.pivot_a[1]) * .5
        hold.pivot, hold.pivot_v, hold.pivot_a = pivot, (pvx, pvy), (pax, pay)
        gx, gy = hold.grab
        rx, ry = rot((COM[0] - gx) * s, (COM[1] - gy) * s, pose.angle)
        fx, fy = -pax * INERTIA, GRAVITY - pay * INERTIA
        over = max(0.0, abs(wrap(pose.angle - self.hanging_angle())) - SOFT_LIMIT)
        accel = (rx * fy - ry * fx) / ((GYRATION * s) ** 2 + rx * rx + ry * ry) \
            - SWING_DAMPING * (1 + over * over * 12) * self.spin
        self.spin = clamp(self.spin + accel * h, -40, 40)
        pose.angle += self.spin * h
        rx, ry = rot((COM[0] - gx) * s, (COM[1] - gy) * s, pose.angle)
        x, y = pivot[0] + rx, pivot[1] + ry
        self.vx, self.vy = (x - pose.x) / h, (y - pose.y) / h
        pose.x, pose.y = x, y
        sign = (hand[2] > 0) - (hand[2] < 0)
        if abs(hand[2]) > SHAKE_SPEED and sign != hold.last_sign:
            if hold.last_sign:
                hold.flips.append(self.now)
            hold.last_sign = sign
        hold.flips = [t for t in hold.flips if self.now - t < SHAKE_WINDOW_S]
        if len(hold.flips) >= SHAKE_FLIPS:
            hold.shook = True

    def release(self, velocity: tuple) -> bool:
        """Let go with ``velocity`` (px/s); True when she was shaken hard first."""
        vx, vy = velocity
        speed = math.hypot(vx, vy)
        if speed > MAX_THROW:
            vx, vy = vx * MAX_THROW / speed, vy * MAX_THROW / speed
        shook = self.hold is not None and self.hold.shook
        self.vx, self.vy = vx, vy
        self.hold = None
        self.flight_s = 0.0
        self.on_floor = False
        return shook

    # ------------------------------------------------------------ flying
    def step_fly(self, h: float, bounds: tuple) -> list:
        """One step in the air or on the floor; the edges she hit as (side, speed, x, y)."""
        self.now += h
        self.flight_s += h
        pose = self.pose
        self.vy += GRAVITY_FLY * h
        f = math.exp(-AIR_DRAG * h)
        self.vx *= f
        self.vy *= f
        self.spin *= math.exp(-AIR_SPIN * h)
        if self.righting:
            self.spin += (-RIGHT_K * wrap(pose.angle) - 2 * .8 * math.sqrt(RIGHT_K) * self.spin) * h
        pose.x += self.vx * h
        pose.y += self.vy * h
        pose.angle += self.spin * h
        return self._collide(bounds)

    def radius(self) -> float:
        return COLL_R * self.pose.scale

    def _collide(self, bounds: tuple) -> list:
        left, top, right, bottom = bounds
        pose, r, k = self.pose, self.radius(), ROLL_K
        hits = []
        self.on_floor = False
        if pose.y > bottom - r:
            pose.y = bottom - r
            if self.vy > 0:
                speed = self.vy
                hits.append(('bottom', speed, pose.x, bottom))
                self.vy = -speed * RESTITUTION
                if abs(self.vy) < 90:
                    self.vy = 0.0
                j = (self.vx - self.spin * r) / (1 + 1 / k) * (.7 if speed > 300 else 1)
                self.vx -= j
                self.spin += j / (k * r)
            self.on_floor = True
        if pose.x > right - r:
            pose.x = right - r
            if self.vx > 0:
                hits.append(('right', self.vx, right, pose.y))
                self.vx = -self.vx * RESTITUTION
                j = (self.vy + self.spin * r) / (1 + 1 / k) * .6
                self.vy -= j
                self.spin -= j / (k * r)
        if pose.x < left + r:
            pose.x = left + r
            if self.vx < 0:
                hits.append(('left', -self.vx, left, pose.y))
                self.vx = -self.vx * RESTITUTION
                j = (self.vy - self.spin * r) / (1 + 1 / k) * .6
                self.vy -= j
                self.spin += j / (k * r)
        ceiling = top + r * 1.3                     # her ears reach higher than her round body
        if pose.y < ceiling:
            pose.y = ceiling
            if self.vy < 0:
                hits.append(('top', -self.vy, pose.x, top))
                self.vy = -self.vy * RESTITUTION
                j = (self.vx + self.spin * r) / (1 + 1 / k) * .6
                self.vx -= j
                self.spin -= j / (k * r)
        if self.on_floor:                            # rolling: the contact point does not slide
            j = (self.vx - self.spin * r) / (1 + 1 / k)
            self.vx -= j
            self.vx *= math.exp(-ROLL_DRAG * STEP)
            self.spin = self.vx / r
        return hits

    def stopped(self) -> bool:
        """At rest on the floor (or flying too long)."""
        return self.flight_s > MAX_FLIGHT_S or (
            self.on_floor and abs(self.vx) < 14 and abs(self.vy) < 1 and abs(self.spin) < .7)

    def lying(self) -> bool:
        return abs(wrap(self.pose.angle)) > .22

    def hop_upright(self):
        """From the floor, a hop that turns her upright by the time she lands."""
        r = self.radius()
        vy = math.sqrt(2 * GRAVITY_FLY * r * 1.1)
        self.vx, self.vy = 0.0, -vy
        self.spin = -wrap(self.pose.angle) / (2 * vy / GRAVITY_FLY)
        self.righting = True
        self.flight_s = 0.0
        self.on_floor = False


def _in_ellipse(x, y, cx, cy, rx, ry) -> bool:
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1


def region_at(x: float, y: float) -> str | None:
    """The part of her at canvas point (x, y): ring, earL/earR, glasses, cheekL/cheekR, paws, head, face."""
    if 384 <= x <= 533 and 30 <= y <= 235 and not (y > 205 and abs(x - 452) > 45):
        return 'ring'
    if _in_ellipse(x, y, 316, 182, 74, 108):
        return 'earL'
    if _in_ellipse(x, y, 600, 182, 74, 108):
        return 'earR'
    if 331 <= x <= 586 and 520 <= y <= 562:
        return 'glasses'
    if _in_ellipse(x, y, 368, 578, 56, 30):
        return 'cheekL'
    if _in_ellipse(x, y, 548, 578, 56, 30):
        return 'cheekR'
    if 388 <= x <= 528 and 590 <= y <= 674:
        return 'paws'
    if _in_ellipse(x, y, 458, 432, 288, 252):
        return 'head' if y < 450 else 'face'
    return None


def _smooth(k: float) -> float:
    k = clamp(k, 0.0, 1.0)
    return k * k * (3 - 2 * k)


def squash_target(mode: str, vx: float, vy: float, hand: tuple | None, pose: Pose):
    """(stretch, axis or None, pivot from her centre) for her squash spring this step."""
    speed = math.hypot(vx, vy)
    if mode == 'held' and hand is not None:
        # Fast: stretched along her speed. Slow: she sags a little away from the hand (soft mochi).
        axis = math.atan2(vy, vx) if speed > 300 else math.atan2(pose.y - hand[1], pose.x - hand[0])
        return HANG_SAG + STRETCH * min(1.0, speed / 3500), axis, (hand[0] - pose.x, hand[1] - pose.y)
    if mode == 'fly':
        return STRETCH * .6 * min(1.0, speed / 4500), (math.atan2(vy, vx) if speed > 60 else None), (0.0, 0.0)
    return 0.0, None, (0.0, 0.0)


__all__ = ['BodyPhysics', 'COLL_R', 'COM', 'DEPTH', 'FACE', 'FEET', 'GAZE_SHIFT', 'GRAVITY', 'GRAVITY_FLY', 'HEAD',
           'HOOK', 'Hold',
           'IMPACT_SQUASH', 'LAYER_PART', 'PARTS', 'PART_BY_ID', 'Part', 'PartState', 'Pose', 'RING_TOP', 'ROOM_R', 'Rig',
           'STEP', 'Squash', 'region_at', 'squash_target', 'wrap']
