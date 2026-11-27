"""兔白's moves and stickers: what the keychain bunny can act out (2026-11-14).

User (2026-11-14): give the bunny many cute motions and expression stickers so she can show how
she feels in fun ways — every idea of the A (motions with the existing layers), B (stickers drawn
in code) and C (reacting to the app) lists. D (new eyes, mouths, hands) needs the user's own art;
``BunnyMascot`` already swaps in a layer whose role is ``"<role>:<expression>"`` once it exists.

Everything here is pure maths over the rig's own canvas (900 x 888, pivots from rig.json):

* ``MOVES``: name -> ``Move(seconds, pose)``. ``pose(k, t)`` returns a ``Pose`` for progress
  ``k`` (0..1; looping moves get the time in the loop) — layer turns and shifts, the whole body's
  shift, turn (about the feet), squash and stretch, a spin about the key ring, blush strength,
  forced eyes/mouth, a forced glare sweep.
* ``STICKERS``: name -> ``Sticker(seconds, draw)``; ``draw(painter, k, s)`` paints in canvas units
  scaled by ``s`` around her head (hearts, 💢, sweat, ?, !, sparkles, notes, Zzz, a bulb, tears,
  flowers, confetti, a thinking bubble, dizzy stars, a magnifier, a wrench).
* ``ACTS``: the named reactions the chat and the AI use — a move plus a sticker.

No widgets here; ``bunny_mascot.BunnyMascot.play`` / ``stick`` run them.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

# Canvas points (rig.json): the feet, the key ring, the face, the top of the head.
FEET = (455.0, 650.0)
RING = (452.0, 12.0)
FACE = (458.0, 520.0)
HEAD_TOP = (458.0, 150.0)


@dataclass
class Pose:
    dx: float = 0.0                 # whole body, canvas units
    dy: float = 0.0
    turn: float = 0.0               # degrees about the feet
    sx: float = 1.0                 # squash / stretch about the feet
    sy: float = 1.0
    spin: float = 0.0               # degrees about the key ring
    mirror: bool = False            # faces the other way (turned away)
    layer_turn: dict = field(default_factory=dict)    # layer name -> degrees about its pivot
    layer_shift: dict = field(default_factory=dict)   # layer name -> (dx, dy)
    blush: float = 1.0              # 1 normal; 2 twice as red
    blush_scale: float = 1.0        # the blush drawn larger (shy)
    lens_flash: float = 0.0         # 0..1 a bright star flashing on the glasses
    paws: dict = field(default_factory=dict)   # 'left'/'right' -> (dx, dy, turn): the paws apart
    fog: float = 0.0                # 0..1 misted glasses
    eyes_closed: bool | None = None
    mouth_open: bool | None = None
    glare: float | None = None      # force the glasses' glare sweep to this progress (0..1)
    base: bool = True               # keep the mood's own idle motion underneath
    hang: float = 0.0               # degrees about the key ring (dangling from a control, 2026-11-26)


@dataclass(frozen=True)
class Move:
    seconds: float
    pose: Callable
    loop: bool = False
    title: str = ''


def ease(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3 - 2 * k)


def window(k: float, a: float, b: float, c: float, d: float) -> float:
    """0 before a, eases up to 1 by b, holds, eases back to 0 between c and d."""
    if k <= a or k >= d:
        return 0.0
    if k < b:
        return ease((k - a) / max(1e-6, b - a))
    if k <= c:
        return 1.0
    return 1.0 - ease((k - c) / max(1e-6, d - c))


def hops(k: float, count: int, height: float) -> float:
    return -abs(math.sin(k * count * math.pi)) * height


def _ears(left: float, right: float) -> dict:
    return {'左耳': left, '右耳': right}


# ------------------------------------------------------------------ A: motions
def _tilt(k, t):          # A1 歪头疑惑
    w = window(k, 0, .2, .8, 1)
    return Pose(turn=10 * w, layer_turn=_ears(-4 * w, 26 * w))


def _ears_up(k, t):       # A2 耳朵竖直抖一抖
    w = window(k, 0, .08, .75, 1)
    quiver = 3 * math.sin(t * 2 * math.pi * 14) * w
    return Pose(sy=1 + .05 * w, sx=1 - .02 * w, layer_turn=_ears(4.5 * w + quiver, -5 * w - quiver), base=False)


def _ear_flap(k, t):      # A3 耳朵拍拍飞
    w = window(k, 0, .06, .9, 1)
    flap = 24 * math.sin(t * 2 * math.pi * 7) * w
    return Pose(dy=hops(k, 3, 46) * w, layer_turn=_ears(-flap, flap), base=False)


def _one_ear(k, t):       # A4 单耳半折
    w = window(k, 0, .15, .8, 1)
    return Pose(turn=-4 * w, layer_turn={'右耳': 38 * w})


def _push_glasses(k, t):  # A5 推眼镜
    slide = window(k, 0, .25, .45, .62)
    hands = window(k, .3, .45, .62, .8)
    return Pose(layer_shift={'眼镜': (0, 18 * slide), '反光': (0, 18 * slide), '双手': (0, -62 * hands)},
                glare=(k - .6) / .3 if .6 <= k <= .9 else None)


def _glint(k, t):         # A6 镜片一闪 (review: too faint) — the glasses hop, a big star flashes, she pops
    flash = math.sin(min(1.0, k / .55) * math.pi) if k < .55 else 0.0
    pop = window(k, 0, .12, .3, .5)
    return Pose(glare=min(1.0, k * 1.8), lens_flash=flash, sy=1 + .06 * pop, sx=1 - .03 * pop, dy=-18 * pop,
                layer_shift={'眼镜': (0, -10 * pop), '反光': (0, -10 * pop), '眉毛': (0, -16 * pop)},
                layer_turn=_ears(8 * pop, -8 * pop))


def _shy(k, t):           # A7 脸红缩缩 (review: too faint) — red cheeks, paws to face, turns aside, shrinks
    w = window(k, 0, .18, .82, 1)
    wobble = math.sin(t * 2 * math.pi * 1.2) * w
    return Pose(sx=1 - .12 * w, sy=1 - .1 * w, dy=22 * w, dx=-18 * w, turn=-10 * w + 3 * wobble, blush=1 + 2.6 * w,
                blush_scale=1 + .35 * w, eyes_closed=w > .35, layer_turn=_ears(-34 * w, 30 * w),
                paws={'left': (-58 * w, -48 * w, 0, 1 + .4 * w), 'right': (56 * w, -48 * w, 0, 1 + .4 * w)}, layer_shift={'眉毛': (0, 10 * w)})


def _cheer(k, t):         # A8 举手欢呼 (review: not happy enough) — big jumps, paws high, eyes squeezed happy
    w = window(k, 0, .06, .9, 1)
    phase = (k * 3) % 1.0
    air = math.sin(phase * math.pi)
    land = max(0.0, 1 - phase / .12) if k > .05 else 0.0
    flap = 22 * math.sin(t * 2 * math.pi * 8) * w
    return Pose(dy=-78 * air * w, sy=1 + .08 * air * w - .14 * land * w, sx=1 - .05 * air * w + .1 * land * w,
                turn=6 * math.sin(k * 3 * math.pi) * w, eyes_closed=w > .2, mouth_open=w > .2, blush=1 + 1.2 * w,
                paws={'left': (-212 * w, -130 * w + 14 * flap / 22, -30 * w, 1 + .8 * w), 'right': (212 * w, -130 * w - 14 * flap / 22, 30 * w, 1 + .8 * w)},
                layer_turn=_ears(-flap - 10 * w, flap + 10 * w), base=False)


def _wave(k, t):          # A9 挥手 (review: both paws at once is not a wave) — one paw up, waving
    w = window(k, 0, .12, .85, 1)
    swing = math.sin(t * 2 * math.pi * 3.2) * w
    return Pose(paws={'right': (204 * w + 10 * swing, -70 * w - 18 * abs(swing), 34 * swing, 1 + .9 * w)}, turn=-5 * w + 3 * swing,
                layer_turn=_ears(-6 * w, 14 * w + 8 * swing), mouth_open=w > .3 and swing > 0)


def _spin(k, t):          # A10 转一圈（绕身体中间，不会转出画面）
    return Pose(spin=360 * ease(k), base=False, dy=hops(k, 1, 30))


def _dizzy(k, t):         # A11 头晕
    decay = 1 - k
    return Pose(turn=9 * math.sin(t * 2 * math.pi * 1.4) * decay, dx=6 * math.sin(t * 2 * math.pi * .7) * decay,
                eyes_closed=True, layer_turn=_ears(-10 * decay, 12 * decay), base=False)


def _tremble(k, t):       # A12 发抖
    w = window(k, 0, .05, .9, 1)
    return Pose(dx=5 * math.sin(t * 2 * math.pi * 23) * w, sx=1 - .04 * w, sy=1 - .04 * w,
                layer_turn=_ears(-34 * w, 34 * w), base=False)


def _slump(k, t):         # A13 沮丧下沉 (approved with tears) — ears down, sinking, sighing
    w = window(k, 0, .2, .85, 1)
    return Pose(dy=36 * w, sy=1 - .06 * w, turn=-4 * w + 2.5 * math.sin(t * 2 * math.pi * .5) * w, eyes_closed=w > .4,
                layer_turn=_ears(-40 * w, 38 * w), layer_shift={'眉毛': (0, 14 * w)}, base=False)


def _nod(k, t):           # A14 点头
    bob = max(0.0, math.sin(k * 2 * math.pi * 2)) * (1 - .4 * k)
    return Pose(dy=30 * bob, sy=1 - .08 * bob, layer_turn=_ears(10 * bob, -10 * bob))


def _shake(k, t):         # A14 摇头
    swing = math.sin(k * 2 * math.pi * 2.5) * (1 - .5 * k)
    return Pose(turn=15 * swing, dx=10 * swing, layer_turn=_ears(-14 * swing, -14 * swing))


def _stretch(k, t):       # A15 伸懒腰
    up = window(k, 0, .35, .55, .7)
    down = window(k, .62, .72, .8, 1)
    return Pose(sx=1 - .14 * up + .1 * down, sy=1 + .24 * up - .12 * down,
                paws={'left': (-205 * up, -170 * up, -25 * up, 1 + .6 * up), 'right': (205 * up, -170 * up, 25 * up, 1 + .6 * up)},
                eyes_closed=up > .4, mouth_open=.3 < up < .9, base=False)


def _doze(k, t):          # A16 打瞌睡 (loops)
    dip = max(0.0, math.sin(t * 2 * math.pi / 3.2)) ** 3
    return Pose(eyes_closed=True, dy=10 * dip, turn=-5 * dip, layer_turn=_ears(-8, 8), base=False)


def _wake(k, t):          # A16 吓醒
    w = window(k, 0, .05, .5, 1)
    return Pose(dy=hops(k, 1, 50), layer_turn=_ears(5 * w, -5 * w), sy=1 + .06 * w, base=False)


def _struggle(k, t):      # A17 被提着挣扎 (loops)
    kick = math.sin(t * 2 * math.pi * 5)
    return Pose(layer_turn=_ears(-18 * kick, 18 * kick), layer_shift={'脚': (8 * kick, -6 * abs(kick)),
                                                                     '双手': (-6 * kick, -14)},
                turn=3 * kick, base=False)


def _dance(k, t):         # A18 跳舞
    w = window(k, 0, .06, .92, 1)
    beat = math.sin(t * 2 * math.pi * 1.6)
    return Pose(dx=12 * beat * w, turn=6 * beat * w, dy=-abs(math.cos(t * 2 * math.pi * 1.6)) * 14 * w,
                layer_turn={**_ears(10 * beat * w, 10 * beat * w), '左发': 5 * beat * w, '右发': 5 * beat * w,
                            '头饰': 8 * beat * w}, base=False)


def _pout(k, t):          # A19 假生气皱眉
    w = window(k, 0, .12, .85, 1)
    puff = 1 + .02 * math.sin(t * 2 * math.pi * 3) * w
    return Pose(sx=(1 + .08 * w) * puff, sy=1 - .04 * w, layer_shift={'眉毛': (0, 24 * w)},
                layer_turn=_ears(-12 * w, 12 * w), turn=-6 * w, dx=-10 * w)


def _brow_raise(k, t):    # A20 挑眉
    w = window(k, 0, .15, .75, 1)
    wiggle = max(0.0, math.sin((k - .2) * 2 * math.pi * 2)) if .2 < k < .7 else 0.0
    return Pose(layer_shift={'眉毛': (0, -40 * w - 12 * wiggle)}, turn=-6 * w, dx=-8 * w,
                layer_turn=_ears(10 * w, -4 * w))


def _peek(k, t):          # A21 探头 (review: redone) — she rises from below the edge, peeks, then pops up
    if k < .3:                                   # ears, then the top of her head, rise into view
        dy = 540 - 260 * ease(k / .3)
    elif k < .62:                                # her eyes just above the edge: a look left and right
        dy = 280 - 70 * ease((k - .3) / .1)
    elif k < .8:                                 # pop! all the way up
        dy = 210 * (1 - ease((k - .62) / .18)) - 60 * math.sin(min(1.0, (k - .62) / .18) * math.pi)
    else:
        dy = 0.0
    look = math.sin((k - .4) / .22 * 2 * math.pi) if .4 < k < .62 else 0.0
    ears = 20 * math.sin(t * 2 * math.pi * 4) if .62 < k < .95 else 0.0
    return Pose(dy=dy, turn=8 * look, dx=14 * look, layer_turn=_ears(-ears, ears), base=False)


# ------------------------------------------------------------------ C: with the app
def _search(k, t):        # C1 查资料：左右张望 (loops)
    look = math.sin(t * 2 * math.pi * .7)
    return Pose(turn=12 * look, dx=24 * look, layer_turn=_ears(-14 * look, 14 * look),
                paws={'right': (12, -70, 10 * look)})


def _push(k, t):          # C2 帮我做：往控件推一下
    w = window(k, 0, .2, .35, .7)
    return Pose(dx=-62 * w, turn=-14 * w, sx=1 - .08 * w, paws={'left': (-40 * w, -40 * w, -20 * w), 'right': (-30 * w, -36 * w, -10 * w)},
                eyes_closed=.2 < k < .5, base=False)


def _think(k, t):         # C4 等回答：抱着钥匙圈晃 (loops)
    sway = math.sin(t * 2 * math.pi * .6)
    return Pose(turn=8 * sway, dx=8 * sway, paws={'left': (8, -70, 0), 'right': (-8, -70, 0)},
                layer_turn=_ears(-10 + 6 * sway, 10 + 6 * sway), layer_shift={'眉毛': (0, -10)})


def _fog(k, t):           # C5 眼镜起雾，擦一擦
    mist = window(k, 0, .15, .55, .9)
    wipe = window(k, .45, .55, .75, .85)
    return Pose(fog=mist, layer_shift={'双手': (16 * math.sin(t * 2 * math.pi * 4) * wipe, -64 * wipe)},
                eyes_closed=.2 < k < .5)


def _yawn(k, t):          # C10 打哈欠
    w = window(k, 0, .25, .7, 1)
    return Pose(mouth_open=.2 < k < .75, eyes_closed=.25 < k < .8, sy=1 + .06 * w, sx=1 - .03 * w,
                layer_shift={'双手': (0, -30 * w)}, layer_turn=_ears(-8 * w, 8 * w))


def _turn_away(k, t):     # C8 哼，转过去
    w = window(k, 0, .12, .85, 1)
    return Pose(mirror=w > .5, turn=-6 * w, sx=1 + .04 * w, layer_shift={'眉毛': (0, 8 * w)})


def _apology(k, t):       # 沮丧/道歉 (review: not dejected enough) — a deep bow, eyes squeezed shut, ears flopping
    bow = window(k, 0, .25, .75, 1)
    sob = math.sin(t * 2 * math.pi * 1.6) * bow
    return Pose(dy=60 * bow, sy=1 - .14 * bow, sx=1 + .05 * bow, turn=2 * sob, eyes_closed=bow > .2,
                layer_turn=_ears(-48 * bow + 4 * sob, 46 * bow - 4 * sob), layer_shift={'眉毛': (0, 18 * bow)},
                paws={'left': (14 * bow, -30 * bow, 0), 'right': (-14 * bow, -30 * bow, 0)}, base=False)


def _beam(k, t):          # 开心小花 (review: not happy enough) — a happy bouncing sway, eyes smiling
    w = window(k, 0, .1, .88, 1)
    bounce = abs(math.sin(t * 2 * math.pi * 1.8))
    sway = math.sin(t * 2 * math.pi * .9)
    return Pose(dy=-46 * bounce * w, turn=9 * sway * w, sy=1 + .05 * bounce * w, eyes_closed=w > .25, blush=1 + 1.4 * w,
                layer_turn=_ears(8 * sway * w - 6 * w, 8 * sway * w + 6 * w), mouth_open=w > .3 and bounce > .6,
                paws={'left': (-190 * w, -70 * w + 20 * bounce * w, -18 * sway * w, 1 + .5 * w),
                      'right': (190 * w, -70 * w + 20 * bounce * w, -18 * sway * w, 1 + .5 * w)}, base=False)


def _heart_hands(k, t):   # 比心 — paws together held up in front, a little sway (no longer the same as 害羞)
    w = window(k, 0, .15, .85, 1)
    sway = math.sin(t * 2 * math.pi * 1.1) * w
    return Pose(paws={'left': (26 * w, -26 * w, 30 * w, 1 + .5 * w), 'right': (-26 * w, -26 * w, -30 * w, 1 + .5 * w)}, turn=6 * sway, dx=8 * sway,
                blush=1 + 1.2 * w, eyes_closed=w > .4, layer_turn=_ears(-8 * w + 6 * sway, 8 * w + 6 * sway))


# ------------------------------------------------------------------ D: busy with the app's own parts
# 2026-11-26 (user): with her dialog box folded away she should get up to things with the software
# itself — mend the AI settings gear with a wrench, read the term library's book, sit and play on
# its parts (``app/bunny_errands.py``). The props she holds are drawn by ``bunny_props``.
# Where a paw is at the moment it touches something (bunny_errands places her by these), and when.
STRIKE_S, STRIKE_HIT = 0.95, 0.52          # the wrench comes down on the gear at this part of the loop
STRIKE_PAW = (34.0, -44.0, 0.0, 1.25)      # the right paw (and the wrench in it) at that moment
KNOCK_S, KNOCK_HIT = 0.46, 0.30
KNOCK_PAW = (58.0, -40.0, -22.0, 1.15)
PUSH_PAW = (62.0, -34.0, 12.0, 1.15)
PULL_PAW = (46.0, -30.0, -8.0, 1.15)
POLISH_S = 0.6
TICKLE_S = 0.26


def _strike(k, t):        # 抡起扳手敲下去：举起 → 加速砸下 → 碰到时弹一下 → 放松（loops）
    if k < .40:                                  # wind up: the wrench goes up and back over her shoulder
        u = ease(k / .40)
        turn, lift, body = -58 * u, -12 * u, -4 * u
    elif k < STRIKE_HIT:                         # the swing, faster and faster
        u = (k - .40) / (STRIKE_HIT - .40)
        turn, lift, body = -58 * (1 - u * u), -12 * (1 - u * u), -4 + 10 * u * u
    elif k < .64:                                # the hit: it bounces back a little
        u = (k - STRIKE_HIT) / (.64 - STRIKE_HIT)
        turn, lift, body = -9 * math.sin(math.pi * u), 0.0, 6 * (1 - u)
    else:
        turn = lift = body = 0.0
    hit = max(0.0, 1 - abs(k - STRIKE_HIT) / .06)
    return Pose(turn=body, dx=6 + 6 * hit, dy=4 * hit, sy=1 - .05 * hit, sx=1 + .03 * hit,
                paws={'right': (STRIKE_PAW[0], STRIKE_PAW[1] + lift, turn, STRIKE_PAW[3]), 'left': (8, -26, 10, 1.1)},
                layer_turn=_ears(-8 - 16 * hit, 10 + 16 * hit), layer_shift={'眉毛': (0, 12)},
                eyes_closed=hit > .5, base=False)


def _knock(k, t):         # 敲敲：前爪朝按钮敲（loops）
    hit = max(0.0, math.sin(k * 2 * math.pi)) ** 3
    back = max(0.0, -math.sin(k * 2 * math.pi))
    paw = (KNOCK_PAW[0] - 26 * (1 - hit), KNOCK_PAW[1] - 10 * back, KNOCK_PAW[2] * hit, KNOCK_PAW[3])
    return Pose(turn=4 * hit, dx=4 * hit, paws={'right': paw}, layer_turn=_ears(-4 * hit, 6 + 6 * hit), base=False)


def _push(k, t):          # 用力推：身体前倾，两爪顶着，抖（loops）
    strain = math.sin(t * 2 * math.pi * 11) * 2
    return Pose(turn=13, dx=16 + strain, dy=4, sx=1.04, sy=.96, eyes_closed=True,
                paws={'right': PUSH_PAW, 'left': (PUSH_PAW[0] + 8, PUSH_PAW[1] + 4, PUSH_PAW[2] + 6, 1.15)},
                layer_turn=_ears(-30, 26 + strain), layer_shift={'眉毛': (0, 16)}, base=False)


def _pull(k, t):          # 往后拉：身体后仰，两爪抓着，抖（loops）
    strain = math.sin(t * 2 * math.pi * 10) * 2
    return Pose(turn=-14, dx=-10 + strain, sx=1.03, sy=.97, eyes_closed=True,
                paws={'right': PULL_PAW, 'left': (PULL_PAW[0] + 6, PULL_PAW[1] + 4, 0, 1.15)},
                layer_turn=_ears(-36, 34 + strain), layer_shift={'眉毛': (0, 16)}, base=False)


def _tumble(k, t):        # 一屁股坐倒，又爬起来
    w = window(k, 0, .12, .62, 1)
    return Pose(turn=-26 * w, dx=-20 * w, dy=30 * w, sy=1 - .1 * w, sx=1 + .05 * w, eyes_closed=w > .3,
                layer_turn=_ears(-44 * w, 40 * w), paws={'left': (-30 * w, -50 * w, -20 * w), 'right': (30 * w, -60 * w, 20 * w)},
                base=False)


def _lift(k, t):          # 举起来：两爪举过头，摇摇晃晃（loops）
    wob = math.sin(t * 2 * math.pi * 3.5)
    return Pose(sy=.93, sx=1.04, turn=3 * wob, dx=3 * wob, eyes_closed=True,
                paws={'left': (-24, -196 + 4 * wob, -14, 1.2), 'right': (24, -196 - 4 * wob, 14, 1.2)},
                layer_turn=_ears(-30, 30), layer_shift={'眉毛': (0, 16)}, base=False)


def _flick(k, t):         # 弹一下：爪子快速一弹
    hit = math.sin(min(1.0, k / .4) * math.pi) if k < .4 else 0.0
    return Pose(turn=5 * hit, paws={'right': (40 + 30 * hit, -36, -30 * hit, 1.2)}, layer_turn=_ears(0, 10 * hit))


def _tickle(k, t):        # 挠痒痒：两爪快速抓挠（loops）
    a = math.sin(k * 2 * math.pi)
    b = math.sin(k * 2 * math.pi + 1.6)
    return Pose(turn=6, dx=8, mouth_open=True, eyes_closed=True, blush=1.8,
                paws={'right': (52 + 10 * a, -40 + 12 * b, 20 * a, 1.15), 'left': (60 + 10 * b, -30 + 12 * a, 20 * b, 1.15)},
                layer_turn=_ears(-10 + 6 * a, 12 + 6 * b), base=False)


def _polish(k, t):        # 用布擦：右爪画圈（loops）
    a = k * 2 * math.pi
    return Pose(turn=4 + 2 * math.sin(a), dx=6, paws={'right': (44 + 16 * math.cos(a), -40 + 12 * math.sin(a), 10 * math.sin(a), 1.2)},
                layer_turn=_ears(-4 + 4 * math.sin(a), 6 + 4 * math.sin(a)))


def _blow(k, t):          # 鼓起脸吹一口气
    puff = window(k, 0, .3, .5, .6)
    blow = window(k, .5, .58, .85, 1)
    return Pose(sx=1 + .07 * puff, sy=1 - .02 * puff, turn=6 * blow, dx=8 * blow, blush=1 + puff, mouth_open=blow > .3,
                eyes_closed=puff > .5, layer_turn=_ears(6 * blow, -6 * blow))


def _lean_nap(k, t):      # 靠着打盹（loops）
    dip = max(0.0, math.sin(t * 2 * math.pi / 3.2)) ** 3
    return Pose(turn=10, dx=12, dy=6 * dip, eyes_closed=True, layer_turn=_ears(-12, 10), paws={'right': (40, -20, 20)},
                base=False)


def _wipe_brow(k, t):     # 擦擦汗
    w = window(k, 0, .25, .7, 1)
    swipe = math.sin(k * 2 * math.pi * 2) * w
    return Pose(paws={'right': (-16 + 30 * swipe, -150 * w, -20, 1.2)}, turn=-3 * w, eyes_closed=.3 < k < .7,
                layer_turn=_ears(-6 * w, 6 * w))


def _catch(k, t):         # 像猫一样扑上去抓光标：两爪高举乱抓，嘴巴张开（loops）
    a = math.sin(t * 2 * math.pi * 6)
    return Pose(sy=1.06, sx=.96, mouth_open=True, blush=1.4,
                paws={'left': (-22, -206 + 10 * a, -14 + 12 * a, 1.25), 'right': (22, -214 - 10 * a, 14 - 12 * a, 1.25)},
                layer_turn=_ears(10 + 6 * a, -10 + 6 * a), layer_shift={'眉毛': (0, -14)}, base=False)


def _curl_nap(k, t):      # 缩成一团睡（loops: slow breathing, a nod now and then）
    breath = math.sin(k * 2 * math.pi)
    nod = max(0.0, math.sin(t * 2 * math.pi / 5.3)) ** 4
    return Pose(sy=.92 + .015 * breath, sx=1.05 - .01 * breath, dy=14 + 8 * nod, turn=7 + 4 * nod, eyes_closed=True,
                layer_turn=_ears(-26 - 4 * breath, 22 + 4 * breath), paws={'left': (18, -8, 20, 1.05), 'right': (-18, -8, -20, 1.05)},
                layer_shift={'脚': (0, -8)}, blush=1.3, base=False)


def _trot(k, t):          # 一跳一跳往前走（loops: one loop a hop）
    a = math.sin(k * 2 * math.pi)
    return Pose(layer_turn={**_ears(-8 + 8 * a, 8 + 8 * a), '脚': 18 * a},
                paws={'left': (-6, -10 - 8 * a, -10 * a), 'right': (6, -10 + 8 * a, 10 * a)}, base=False)


def _read(k, t):          # 捧着书看（loops: a slow nod as she reads down the page）
    nod = math.sin(k * 2 * math.pi)
    return Pose(dy=8 + 4 * nod, turn=-2 + 1.5 * nod, layer_turn=_ears(-8 + 3 * nod, 8 - 3 * nod),
                paws={'left': (34, -34, 18, 1.2), 'right': (-34, -34, -18, 1.2)},
                layer_shift={'眉毛': (0, 6)}, base=False)


def _sit(k, t):           # 坐在上面晃脚（loops）
    kick = math.sin(k * 2 * math.pi)
    look = math.sin(k * 2 * math.pi / 2 + .6)
    return Pose(sy=.95, sx=1.03, dy=10, turn=2.5 * look, layer_turn={**_ears(-4 + 6 * look, 4 + 6 * look), '脚': 14 * kick},
                layer_shift={'脚': (0, -10 - 4 * abs(kick))}, paws={'left': (-10, -6, -8), 'right': (10, -6, 8)}, base=False)


def _cling(k, t):         # 抓住光标挂着：两爪举高抓紧，脚乱蹬，开心地张嘴（loops）
    kick = math.sin(t * 2 * math.pi * 3.2)
    wiggle = math.sin(t * 2 * math.pi * 1.1)
    return Pose(sy=1.04, sx=.97, mouth_open=abs(wiggle) > .7, blush=1.5,
                paws={'left': (-16, -210, -8, 1.2), 'right': (16, -212, 8, 1.2)},
                layer_turn={**_ears(14 + 6 * wiggle, -14 + 6 * wiggle), '脚': 14 * kick},
                layer_shift={'眉毛': (0, -10)}, base=False)


def _hang(k, t):          # 挂在按钮下面荡（loops: she swings from her key ring, feet kicking）
    swing = math.sin(k * 2 * math.pi)
    kick = math.sin(k * 2 * math.pi * 2 + .4)
    return Pose(hang=11 * swing, layer_turn={**_ears(-10 * swing - 6, -10 * swing + 6), '脚': 10 * kick},
                layer_shift={'双手': (0, -18)}, mouth_open=abs(swing) > .92, base=False)


MOVES = {
    'tilt': Move(1.6, _tilt, title='歪头疑惑'),
    'ears_up': Move(1.0, _ears_up, title='耳朵竖直抖一抖'),
    'ear_flap': Move(1.5, _ear_flap, title='耳朵拍拍飞'),
    'one_ear': Move(1.8, _one_ear, title='单耳半折'),
    'push_glasses': Move(1.4, _push_glasses, title='推眼镜'),
    'glint': Move(0.7, _glint, title='镜片一闪'),
    'shy': Move(2.0, _shy, title='脸红缩缩'),
    'cheer': Move(1.8, _cheer, title='跳起来欢呼'),
    'wave': Move(1.8, _wave, title='单手挥挥'),
    'spin': Move(1.0, _spin, title='钥匙圈转一圈'),
    'dizzy': Move(2.4, _dizzy, title='头晕'),
    'tremble': Move(1.4, _tremble, title='发抖'),
    'slump': Move(2.2, _slump, title='沮丧下沉'),
    'nod': Move(1.0, _nod, title='点头'),
    'shake': Move(1.0, _shake, title='摇头'),
    'stretch': Move(1.6, _stretch, title='伸懒腰'),
    'doze': Move(3.2, _doze, loop=True, title='打瞌睡'),
    'wake': Move(0.6, _wake, title='吓醒'),
    'struggle': Move(0.4, _struggle, loop=True, title='被提着挣扎'),
    'dance': Move(3.2, _dance, title='跳舞'),
    'pout': Move(1.6, _pout, title='假生气皱眉'),
    'brow_raise': Move(1.3, _brow_raise, title='挑眉'),
    'peek': Move(2.2, _peek, title='从下面探头'),
    'search': Move(2.0, _search, loop=True, title='查资料张望'),
    'push': Move(0.8, _push, title='帮你按一下'),
    'think': Move(2.0, _think, loop=True, title='抱着钥匙圈想'),
    'fog': Move(2.2, _fog, title='眼镜起雾擦一擦'),
    'yawn': Move(1.8, _yawn, title='打哈欠'),
    'turn_away': Move(2.4, _turn_away, title='哼，转过去'),
    'apology': Move(2.4, _apology, title='鞠躬道歉'),
    'beam': Move(2.2, _beam, title='开心晃晃'),
    'heart_hands': Move(2.0, _heart_hands, title='比心'),
    'strike': Move(STRIKE_S, _strike, loop=True, title='抡起扳手敲'),
    'knock': Move(KNOCK_S, _knock, loop=True, title='敲敲'),
    'push': Move(0.7, _push, loop=True, title='用力推'),
    'pull': Move(0.7, _pull, loop=True, title='往后拉'),
    'tumble': Move(1.1, _tumble, title='一屁股坐倒'),
    'lift': Move(0.6, _lift, loop=True, title='举起来'),
    'flick': Move(0.5, _flick, title='弹一下'),
    'tickle': Move(TICKLE_S, _tickle, loop=True, title='挠痒痒'),
    'polish': Move(POLISH_S, _polish, loop=True, title='用布擦'),
    'blow': Move(1.4, _blow, title='吹一口气'),
    'lean_nap': Move(3.2, _lean_nap, loop=True, title='靠着打盹'),
    'wipe_brow': Move(1.2, _wipe_brow, title='擦擦汗'),
    'trot': Move(0.36, _trot, loop=True, title='一跳一跳走'),
    'curl_nap': Move(3.0, _curl_nap, loop=True, title='缩成一团睡'),
    'catch': Move(0.3, _catch, loop=True, title='扑上去抓'),
    'read': Move(2.6, _read, loop=True, title='捧着书看'),
    'sit': Move(2.0, _sit, loop=True, title='坐着晃脚'),
    'hang': Move(1.8, _hang, loop=True, title='挂着荡秋千'),
    'cling': Move(1.0, _cling, loop=True, title='抓住光标挂着'),
}


# ------------------------------------------------------------------ B: stickers
PINK, RED, BLUE, GOLD, GREEN, PURPLE, INK = '#ff6f9e', '#e8473f', '#5fb2ff', '#ffc531', '#58c98a', '#a07cc8', '#4a3a33'


def _fade(k: float, start: float = .7) -> float:
    return 1.0 if k < start else max(0.0, 1 - (k - start) / (1 - start))


def _pop(k: float) -> float:
    """0 -> overshoot -> 1 within the first fifth."""
    if k >= .2:
        return 1.0
    x = k / .2
    return 1 + 2.7 * (x - 1) ** 3 + 1.7 * (x - 1) ** 2


def _color(name, alpha=1.0):
    from PySide6.QtGui import QColor
    color = QColor(name)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


def _heart_path(cx, cy, size):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath(QPointF(cx, cy + size * .35))
    path.cubicTo(cx - size * 1.1, cy - size * .35, cx - size * .45, cy - size * 1.05, cx, cy - size * .45)
    path.cubicTo(cx + size * .45, cy - size * 1.05, cx + size * 1.1, cy - size * .35, cx, cy + size * .35)
    return path


def _sticker_font(size):
    """The bundled 猫啃什锦黑, so ? ! Z look the same on every machine (no missing-glyph boxes)."""
    from PySide6.QtGui import QFont
    try:
        from .loading_font import loading_font
        font = loading_font()
    except Exception:  # noqa: BLE001
        font = QFont()
    font.setPixelSize(max(1, round(size)))
    font.setBold(True)
    return font


def _text(painter, x, y, text, size, color, bold=True):
    """``text`` centred on (x, y) as an outlined shape: white edge, coloured fill."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QFontMetricsF, QPainterPath, QPen
    font = _sticker_font(size)
    metrics = QFontMetricsF(font)
    path = QPainterPath()
    path.addText(QPointF(x - metrics.horizontalAdvance(text) / 2, y + (metrics.ascent() - metrics.descent()) / 2),
                 font, text)
    alpha = color.alphaF()
    painter.setPen(QPen(_color('#ffffff', alpha), max(1.0, size / 14)))
    painter.setBrush(color)
    painter.drawPath(path)


def _note_path(cx, cy, size, double=False):
    """A music note: a tilted head, a stem and a flag (or two heads and a beam)."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPainterPath, QTransform
    path = QPainterPath()
    heads = ((cx - size * .55, cy + size * .5), (cx + size * .45, cy + size * .3)) if double else ((cx, cy + size * .5),)
    for hx, hy in heads:
        head = QPainterPath()
        head.addEllipse(QRectF(-size * .32, -size * .22, size * .64, size * .44))
        path.addPath(QTransform().translate(hx, hy).rotate(-20).map(head))
        path.addRect(QRectF(hx + size * .22, hy - size * 1.1, size * .1, size * 1.1))
    if double:
        beam = QPainterPath(QPointF(heads[0][0] + size * .22, heads[0][1] - size * 1.1))
        beam.lineTo(QPointF(heads[1][0] + size * .32, heads[1][1] - size * 1.1))
        beam.lineTo(QPointF(heads[1][0] + size * .32, heads[1][1] - size * .85))
        beam.lineTo(QPointF(heads[0][0] + size * .22, heads[0][1] - size * .85))
        beam.closeSubpath()
        path.addPath(beam)
    else:
        hx, hy = heads[0]
        flag = QPainterPath(QPointF(hx + size * .32, hy - size * 1.1))
        flag.cubicTo(hx + size * .7, hy - size * .9, hx + size * .75, hy - size * .5, hx + size * .55, hy - size * .3)
        flag.cubicTo(hx + size * .6, hy - size * .6, hx + size * .45, hy - size * .75, hx + size * .32, hy - size * .8)
        path.addPath(flag)
    return path


def _star_path(cx, cy, r):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    path = QPainterPath()
    for i in range(10):
        radius = r if i % 2 == 0 else r * .45
        a = math.radians(-90 + i * 36)
        point = QPointF(cx + math.cos(a) * radius, cy + math.sin(a) * radius)
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    return path


def _outline(painter, path, fill, alpha, width_s):
    from PySide6.QtGui import QPen
    painter.setPen(QPen(_color('#ffffff', alpha), width_s))
    painter.setBrush(_color(fill, alpha))
    painter.drawPath(path)


def _hearts(painter, k, s):
    for i, (x, delay) in enumerate(((620, 0), (690, .18), (560, .34))):
        local = max(0.0, min(1.0, (k - delay) / .7))
        if local <= 0:
            continue
        y = 260 - 220 * local
        size = (34 + 8 * i) * _pop(local)
        _outline(painter, _heart_path((x + 10 * math.sin(local * 6)) * s, y * s, size * s), PINK, _fade(local, .6), 3 * s)


def _anger(painter, k, s):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPen
    size = 48 * _pop(k) * (1 + .08 * math.sin(k * 40))
    cx, cy = 650 * s, 210 * s
    painter.setPen(QPen(_color(RED, _fade(k)), 9 * s))
    for angle in (0, 90, 180, 270):
        path = QPainterPath()
        a = math.radians(angle + 45)
        ox, oy = math.cos(a) * size * s * .55, math.sin(a) * size * s * .55
        path.moveTo(QPointF(cx + ox + math.cos(a + 1.2) * size * s * .4, cy + oy + math.sin(a + 1.2) * size * s * .4))
        path.quadTo(QPointF(cx + ox * .3, cy + oy * .3), QPointF(cx + ox + math.cos(a - 1.2) * size * s * .4,
                                                               cy + oy + math.sin(a - 1.2) * size * s * .4))
        painter.drawPath(path)


def _sweat(painter, k, s):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    y = (240 + 70 * ease(k)) * s
    x, size = 640 * s, 36 * s * _pop(k)
    path = QPainterPath(QPointF(x, y - size * 1.4))
    path.cubicTo(x + size * 1.1, y - size * .1, x + size * .8, y + size, x, y + size)
    path.cubicTo(x - size * .8, y + size, x - size * 1.1, y - size * .1, x, y - size * 1.4)
    _outline(painter, path, BLUE, _fade(k), 3 * s)


def _mark(text, color):
    def draw(painter, k, s):              # review: bigger and more obvious
        size = 210 * _pop(k)
        y = (150 - 26 * math.sin(min(1.0, k * 3) * math.pi)) * s
        tilt = 12 * math.sin(min(1.0, k * 4) * math.pi) * (1 - k)
        painter.save()
        painter.translate(640 * s, y)
        painter.rotate(tilt)
        _text(painter, 0, 0, text, size * s, _color(color, _fade(k, .78)))
        painter.restore()
    return draw


def _sparkles(painter, k, s):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    for i, (x, y, delay) in enumerate(((640, 200, 0), (300, 250, .15), (700, 330, .3), (560, 120, .45))):
        local = max(0.0, min(1.0, (k - delay) / .5))
        if not 0 < local < 1:
            continue
        r = 22 * s * math.sin(local * math.pi)
        cx, cy = x * s, y * s
        path = QPainterPath(QPointF(cx, cy - r))
        for px, py in ((cx + r * .25, cy - r * .25), (cx + r, cy), (cx + r * .25, cy + r * .25), (cx, cy + r),
                       (cx - r * .25, cy + r * .25), (cx - r, cy), (cx - r * .25, cy - r * .25), (cx, cy - r)):
            path.lineTo(QPointF(px, py))
        _outline(painter, path, GOLD, 1.0, 2 * s)


def _notes(painter, k, s):
    for i, (x, delay, double) in enumerate(((650, 0, False), (290, .25, True), (705, .5, False))):
        local = max(0.0, min(1.0, (k - delay) / .55))
        if not 0 < local < 1:
            continue
        path = _note_path((x + 14 * math.sin(local * 7)) * s, (300 - 200 * local) * s, 56 * s, double)
        _outline(painter, path, PURPLE, _fade(local, .5), 3 * s)


def _zzz(painter, k, s):
    phase = k % 1.0
    for i in range(3):
        local = (phase + i / 3) % 1.0
        _text(painter, (620 + 50 * local + 20 * i) * s, (240 - 170 * local) * s, 'Z', (46 + 18 * i) * s,
              _color(BLUE, math.sin(local * math.pi)))


def _bulb(painter, k, s):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPen
    size = 46 * _pop(k) * s
    cx, cy = 660 * s, 150 * s
    alpha = _fade(k)
    glow = .5 + .5 * math.sin(k * 20)
    painter.setPen(QPen(_color(GOLD, alpha * glow), 5 * s))
    for angle in range(-150, -20, 32):
        a = math.radians(angle)
        painter.drawLine(QPointF(cx + math.cos(a) * size * 1.3, cy + math.sin(a) * size * 1.3),
                         QPointF(cx + math.cos(a) * size * 1.8, cy + math.sin(a) * size * 1.8))
    painter.setPen(QPen(_color('#ffffff', alpha), 3 * s))
    painter.setBrush(_color(GOLD, alpha))
    painter.drawEllipse(QPointF(cx, cy), size, size)
    painter.setBrush(_color('#9a8a7a', alpha))
    painter.drawRoundedRect(QRectF(cx - size * .45, cy + size * .8, size * .9, size * .55), 4 * s, 4 * s)


def _tears(painter, k, s):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    for side, x in ((-1, 345), (1, 575)):
        for i in range(2):
            local = (k * 2 + i * .5) % 1.0
            y = (560 + 90 * local) * s
            size = 12 * s
            cx = (x + side * 12 * local) * s
            path = QPainterPath(QPointF(cx, y - size * 1.4))
            path.cubicTo(cx + size, y, cx + size * .7, y + size, cx, y + size)
            path.cubicTo(cx - size * .7, y + size, cx - size, y, cx, y - size * 1.4)
            _outline(painter, path, BLUE, math.sin(local * math.pi), 2 * s)


def _flowers(painter, k, s):
    from PySide6.QtCore import QPointF
    for i, (x, y, delay) in enumerate(((300, 230, 0), (640, 190, .15), (690, 320, .3))):
        local = max(0.0, min(1.0, (k - delay) / .6))
        if local <= 0:
            continue
        r = 22 * _pop(local) * s
        alpha = _fade(local, .6)
        cx, cy = x * s, (y - 30 * local) * s
        painter.setPen(_color('#ffffff', alpha))
        painter.setBrush(_color('#ffb3cf', alpha))
        for p in range(5):
            a = math.radians(p * 72 + local * 90)
            painter.drawEllipse(QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r), r * .75, r * .75)
        painter.setBrush(_color(GOLD, alpha))
        painter.drawEllipse(QPointF(cx, cy), r * .55, r * .55)


def _confetti(painter, k, s):
    from PySide6.QtCore import QRectF
    rng = random.Random(7)
    painter.setPen(_color('#ffffff', 0))
    for _i in range(18):
        x0, vx = rng.uniform(260, 660), rng.uniform(-140, 140)
        vy = rng.uniform(-420, -260)
        color = rng.choice((PINK, GOLD, BLUE, GREEN, PURPLE))
        t = k * 1.2
        x, y = x0 + vx * t, 300 + vy * t + 520 * t * t
        painter.save()
        painter.translate(x * s, y * s)
        painter.rotate(rng.uniform(0, 360) + k * 700)
        painter.setBrush(_color(color, _fade(k, .6)))
        painter.drawRect(QRectF(-7 * s, -4 * s, 14 * s, 8 * s))
        painter.restore()


def _dots(painter, k, s):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen
    painter.setPen(QPen(_color('#ffffff', .95), 3 * s))
    painter.setBrush(_color('#fffaf2', .95))
    painter.drawEllipse(QPointF(660 * s, 150 * s), 62 * s, 44 * s)
    painter.drawEllipse(QPointF(610 * s, 215 * s), 12 * s, 12 * s)
    painter.drawEllipse(QPointF(590 * s, 245 * s), 7 * s, 7 * s)
    painter.setPen(_color(INK, 0))
    for i in range(3):
        lift = 6 * max(0.0, math.sin((k * 3 - i * .25) * 2 * math.pi))
        painter.setBrush(_color(INK, .75))
        painter.drawEllipse(QPointF((630 + 30 * i) * s, (150 - lift) * s), 7 * s, 7 * s)


def _stars(painter, k, s):
    for i in range(3):
        a = k * 2 * math.pi * 1.5 + i * 2 * math.pi / 3
        x, y = 458 + math.cos(a) * 200, 230 + math.sin(a) * 50
        _outline(painter, _star_path(x * s, y * s, 30 * s), GOLD, .55 + .45 * math.sin(a), 2.5 * s)


def _magnifier(painter, k, s):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen
    x = 660 + 40 * math.sin(k * 2 * math.pi)
    cx, cy, r = x * s, 330 * s, 50 * s
    painter.setPen(QPen(_color(INK, .9), 9 * s))
    painter.drawLine(QPointF(cx + r * .7, cy + r * .7), QPointF(cx + r * 1.6, cy + r * 1.6))
    painter.setPen(QPen(_color('#7a5a48', 1), 6 * s))
    painter.setBrush(_color('#d8f0ff', .55))
    painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.setPen(QPen(_color('#ffffff', .9), 4 * s))
    painter.drawArc(round(cx - r * .6), round(cy - r * .6), round(r * 1.2), round(r * 1.2), 100 * 16, 60 * 16)


def _wrench(painter, k, s):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QPen
    painter.save()
    painter.translate(660 * s, 220 * s)
    painter.rotate(-30 + 25 * math.sin(k * 2 * math.pi * 3))
    painter.setPen(QPen(_color('#ffffff', 1), 3 * s))
    painter.setBrush(_color('#8a9bb0', _fade(k)))
    painter.drawRoundedRect(QRectF(-8 * s, -10 * s, 16 * s, 80 * s), 6 * s, 6 * s)
    painter.drawEllipse(QPointF(0, -18 * s), 22 * s, 22 * s)
    painter.setBrush(_color('#fffaf2', 1))
    painter.drawRect(QRectF(-7 * s, -44 * s, 14 * s, 24 * s))
    painter.restore()


def _gloom(painter, k, s):              # 沮丧: the manga gloom lines over her head (not a mocking sweat drop)
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPen
    alpha = window(k, 0, .15, .8, 1)
    for i in range(7):
        x = 300 + i * 52
        length = 120 + 50 * ((i * 37) % 3)
        drop = 26 * math.sin(k * 2 * math.pi + i)
        painter.setPen(QPen(_color('#6b7fb8', .75 * alpha), 7 * s))
        painter.drawLine(QPointF(x * s, (130 + drop) * s), QPointF(x * s, (130 + length + drop) * s))
    cloud = _color('#8e9bc4', .85 * alpha)
    painter.setPen(QPen(_color('#ffffff', alpha), 3 * s))
    painter.setBrush(cloud)
    for cx, cy, r in ((380, 110, 46), (450, 92, 58), (530, 110, 46), (450, 126, 50)):
        painter.drawEllipse(QPointF(cx * s, cy * s), r * s, r * .7 * s)


def _big_heart(painter, k, s):          # 比心: one big heart that pops out between her paws and floats up
    local = min(1.0, k / .8)
    size = 70 * _pop(local) * (1 + .06 * math.sin(k * 16))
    _outline(painter, _heart_path(458 * s, (520 - 300 * ease(local)) * s, size * s), PINK, _fade(local, .7), 5 * s)


@dataclass(frozen=True)
class Sticker:
    seconds: float
    draw: Callable
    loop: bool = False
    title: str = ''


STICKERS = {
    'heart': Sticker(1.6, _hearts, title='爱心往上飘'),
    'anger': Sticker(1.4, _anger, title='💢 生气符号'),
    'sweat': Sticker(1.6, _sweat, title='冒汗一滴'),
    'question': Sticker(1.6, _mark('?', PURPLE), title='问号'),
    'exclaim': Sticker(1.2, _mark('!', RED), title='惊叹号'),
    'sparkle': Sticker(1.2, _sparkles, title='闪亮亮'),
    'notes': Sticker(2.2, _notes, title='音符'),
    'zzz': Sticker(2.4, _zzz, loop=True, title='Zzz'),
    'bulb': Sticker(1.6, _bulb, title='灯泡（有主意）'),
    'tears': Sticker(2.0, _tears, title='泪滴'),
    'flower': Sticker(1.8, _flowers, title='小花'),
    'confetti': Sticker(1.6, _confetti, title='彩带'),
    'dots': Sticker(1.6, _dots, loop=True, title='思考泡泡'),
    'stars': Sticker(1.6, _stars, loop=True, title='头晕星星'),
    'magnifier': Sticker(2.0, _magnifier, loop=True, title='放大镜'),
    'wrench': Sticker(1.4, _wrench, title='小扳手'),
    'gloom': Sticker(2.4, _gloom, title='阴影线'),
    'big_heart': Sticker(1.8, _big_heart, title='一颗大爱心'),
}


# ------------------------------------------------------------------ named reactions
@dataclass(frozen=True)
class Act:
    move: str = ''
    sticker: str = ''
    title: str = ''
    when: str = ''               # for the AI: when this fits


ACTS = {
    'wonder': Act('tilt', 'question', '歪头疑惑', '没听懂、在想、好奇'),
    'startled': Act('ears_up', 'exclaim', '吓一跳', '惊讶、真的假的'),
    'excited': Act('ear_flap', 'sparkle', '兴奋', '超开心、好消息'),
    'smirk': Act('one_ear', '', '坏笑', '逗人、开玩笑'),
    'serious': Act('push_glasses', 'sparkle', '认真讲解', '开始认真讲一件事'),
    'idea': Act('glint', 'bulb', '有主意了', '想到办法'),
    'shy': Act('shy', 'heart', '害羞', '被夸、不好意思'),
    'cheer': Act('cheer', 'confetti', '欢呼', '事情办成了'),
    'hello': Act('wave', '', '挥手', '打招呼、说再见'),
    'spin': Act('spin', 'sparkle', '开心转圈', '开心到转圈'),
    'dizzy': Act('dizzy', 'stars', '头晕', '晕了、被绕晕'),
    'scared': Act('tremble', 'sweat', '发抖', '害怕、紧张'),
    'sorry': Act('apology', 'gloom', '沮丧', '道歉、出错、做不到'),
    'yes': Act('nod', '', '点头', '同意、对'),
    'no': Act('shake', '', '摇头', '不对、不是这样'),
    'stretch': Act('stretch', '', '伸懒腰', '放松、累了'),
    'sleepy': Act('yawn', 'zzz', '困了', '困、晚了'),
    'dance': Act('dance', 'notes', '跳舞', '聊音乐、心情很好'),
    'pout': Act('pout', 'anger', '假生气', '被逗、被戳'),
    'hmm': Act('brow_raise', '', '挑眉', '意味深长、嗯哼'),
    'peek': Act('peek', '', '探头', '打招呼、提醒'),
    'love': Act('heart_hands', 'big_heart', '比心', '喜欢、感谢'),
    'cry': Act('slump', 'tears', '哭哭', '很难过、被感动'),
    'bloom': Act('beam', 'flower', '开心小花', '温柔地安慰、鼓励'),
    'hmph': Act('turn_away', 'anger', '哼', '假装不理人'),
}


def act_for_ai() -> str:
    return '、'.join(f'{name}={act.title}（{act.when}）' for name, act in ACTS.items())


__all__ = ['ACTS', 'Act', 'MOVES', 'Move', 'Pose', 'STICKERS', 'Sticker', 'act_for_ai', 'ease', 'window']
