"""Curated caption motion: entry, exit and loop presets as deterministic poses.

Every preset is a pure function of progress. Entry/exit poses are baked into
the per-unit keyframes of :mod:`letter_motion`; loops stay analytic (the same
formula lives in ``renderer/src/components/TimedText.tsx``). Qt, ASS and
Remotion only interpret the channels, so all three draw the same motion.

References: visual techniques read (never executed) from the user's Aegisub
template archive (``assets/motion-reference/aegisub-selection.json``) and
common editor text animations (CapCut/剪映, Premiere, DaVinci Resolve). The
"cinema" group recreates generic transition looks (directional motion blur,
zoom blur, white flash, chroma split, stretch); no third-party plug-in code or
assets are used.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from math import cos, exp, pi, radians, sin, tan

STRENGTH = {'low': .72, 'medium': 1., 'high': 1.28}
DIRECTIONS = {'left': (-1., 0.), 'right': (1., 0.), 'up': (0., -1.), 'down': (0., 1.)}
#: Channels a pose may set, with their resting values. Appended after the
#: original sixteen letter-motion channels; renderers read them by name.
REST = {'sx': 1., 'skew': 0., 'flash': 0., 'halo': 0., 'rgb': 0., 'ghost': 0., 'gx': 0., 'gy': 0.,
        'gs': 0., 'shine': -9., 'slice': 0., 'strips': 0., 'door': 0., 'cut': 0., 'caret': 0.}


@dataclass(frozen=True)
class Motion:
    key: str
    stage: str
    label: str
    category: str
    hint: str
    duration: int = 400
    per_char: bool = False
    overlap: float = 1.
    directional: str = ''        # default direction when the preset has one
    order: str = 'forward'
    samples: int = 18
    poster: tuple = (.15, .45, .8)
    legacy: bool = False         # rendered by the original whole-line path


def _m(stage, key, label, category, hint, **kw):
    return Motion(key, stage, label, category, hint, **kw)


ENTRY = [
    _m('entry', 'none', '无', 'basic', '不播放入场动画', legacy=True),
    _m('entry', 'soft_fade', '淡入', 'basic', '柔和地渐显', duration=180, legacy=True),
    _m('entry', 'float_up', '上浮', 'basic', '从下方轻轻浮上来', duration=240, legacy=True),
    _m('entry', 'drop_in', '落下', 'basic', '从上方轻落到位', duration=240, legacy=True),
    _m('entry', 'slide_soft', '滑入', 'basic', '从左侧滑入', duration=240, legacy=True),
    _m('entry', 'blur_reveal', '聚焦', 'basic', '由模糊变清晰', duration=240, legacy=True),
    _m('entry', 'zoom_in', '放大', 'basic', '由小放大到位', duration=380),
    _m('entry', 'zoom_down', '缩小', 'basic', '从大处压回原尺寸', duration=380),
    _m('entry', 'wipe_in', '擦开', 'basic', '从左到右柔边擦出', duration=520, poster=(.3, .55, .8)),
    _m('entry', 'soft_pop', '轻弹', 'bounce', '轻微放大后回落', duration=220, legacy=True),
    _m('entry', 'punch', '冲击', 'bounce', '快速冲出再收住', duration=180, legacy=True),
    _m('entry', 'bounce_lite', '回弹', 'bounce', '弹出后小幅回弹', duration=280, legacy=True),
    _m('entry', 'spring_in', '弹簧', 'bounce', '从无到有，弹簧般晃稳', duration=650, samples=30),
    _m('entry', 'jelly_in', 'Q 弹', 'bounce', '横竖交替挤压，果冻般落定', duration=620, samples=30),
    _m('entry', 'typewriter', '打字机', 'char', '逐字打出，光标跟随', duration=900, per_char=True,
       overlap=.02, samples=2, poster=(.35, .6, .85)),
    _m('entry', 'char_rise', '逐字浮现', 'char', '每个字带一点模糊浮上来', duration=800, per_char=True, overlap=.45),
    _m('entry', 'char_pop', '逐字弹入', 'char', '字一个个弹出并发光', duration=760, per_char=True, overlap=.5, samples=24),
    _m('entry', 'char_wave', '波浪弹入', 'char', '从下方依次跃起，像一道波', duration=820, per_char=True, overlap=.55, samples=24),
    _m('entry', 'char_flip', '逐字翻牌', 'char', '每个字沿横轴翻开', duration=760, per_char=True, overlap=.5),
    _m('entry', 'char_defocus', '失焦聚焦', 'char', '放大的虚字错落收拢成清晰字', duration=900, per_char=True,
       overlap=.7, order='random'),
    _m('entry', 'char_scatter', '随机飞入', 'char', '字从四周飞回原位', duration=900, per_char=True, overlap=.6),
    _m('entry', 'char_stretch', '横拉聚焦', 'char', '横向拉长的虚影收成字', duration=800, per_char=True, overlap=.55),
    _m('entry', 'zoom_blur_in', '推近模糊', 'cinema', '从镜头前冲入，带缩放拖影', duration=420),
    _m('entry', 'push_in', '冲刺推入', 'cinema', '高速推入，留下动态模糊', duration=420, directional='left'),
    _m('entry', 'whip_in', '甩入', 'cinema', '倾斜甩进画面后站直', duration=460, directional='right'),
    _m('entry', 'flash_in', '闪白', 'cinema', '一下曝光闪白，再回到原色', duration=520),
    _m('entry', 'doors_in', '对开合拢', 'cinema', '左右两半合拢，白光褪去', duration=560),
    _m('entry', 'flip_in', '立体翻转', 'cinema', '沿竖轴翻转着落到位', duration=520),
    _m('entry', 'shine_in', '光扫', 'cinema', '显现时一道斜光扫过', duration=760, poster=(.35, .6, .8)),
    _m('entry', 'echo_in', '重影汇聚', 'cinema', '外扩的轮廓重影收拢成字', duration=560),
    _m('entry', 'glitch_in', '故障', 'glitch', '色散与切片抖动后稳定', duration=520, samples=28,
       poster=(.25, .45, .7)),
    _m('entry', 'flicker_in', '信号闪现', 'glitch', '像信号不稳一样闪几下才亮起', duration=560, samples=28,
       poster=(.35, .6, .9)),
    _m('entry', 'slice_in', '切片拼合', 'glitch', '竖向切片错位后拼成整字', duration=520),
]

EXIT = [
    _m('exit', 'none', '无', 'basic', '不播放出场动画', legacy=True),
    _m('exit', 'soft_fade', '淡出', 'basic', '柔和地渐隐', duration=140, legacy=True),
    _m('exit', 'scale', '缩小', 'basic', '缩小并结束', duration=140, legacy=True),
    _m('exit', 'sink_out', '下沉', 'basic', '向下沉并淡出', duration=360),
    _m('exit', 'rise_out', '上飘', 'basic', '向上飘走并淡出', duration=360),
    _m('exit', 'slide_out', '滑出', 'basic', '朝一侧滑出', duration=380, directional='right'),
    _m('exit', 'blur_out', '模糊消散', 'basic', '变模糊后消失', duration=380),
    _m('exit', 'zoom_out', '放大消散', 'basic', '放大并淡出', duration=380),
    _m('exit', 'wipe_out', '擦除', 'basic', '从左到右擦掉', duration=480),
    _m('exit', 'char_fade_out', '逐字消散', 'char', '每个字带模糊依次飘散', duration=700, per_char=True, overlap=.5),
    _m('exit', 'char_drop_out', '逐字下落', 'char', '字依次掉落并轻微翻转', duration=760, per_char=True, overlap=.55),
    _m('exit', 'char_pop_out', '逐字弹散', 'char', '每个字先一弹，再缩小消失', duration=700, per_char=True,
       overlap=.5, samples=24),
    _m('exit', 'typewriter_out', '打字回删', 'char', '从句尾逐字删除', duration=600, per_char=True,
       overlap=.02, order='reverse', samples=2),
    _m('exit', 'shatter_out', '碎裂消散', 'char', '字碎成小片散开', duration=760, per_char=True, overlap=.6),
    _m('exit', 'zoom_blur_out', '推远模糊', 'cinema', '冲向镜头并拖出缩放残影', duration=380),
    _m('exit', 'push_out', '冲刺离场', 'cinema', '加速冲出，留下动态模糊', duration=380, directional='left'),
    _m('exit', 'flash_out', '闪白消失', 'cinema', '闪白一下后消失', duration=420),
    _m('exit', 'stretch_out', '拉伸消失', 'cinema', '横向拉长并虚化', duration=400),
    _m('exit', 'flip_out', '立体翻出', 'cinema', '沿竖轴翻转着离开', duration=420),
    _m('exit', 'glitch_out', '故障消失', 'glitch', '色散抖动中断开消失', duration=480, samples=26),
]

LOOP = [
    _m('loop', 'none', '无', 'soft', '不循环', legacy=True),
    _m('loop', 'loop_breathe', '呼吸', 'soft', '轻轻放大缩小', duration=1200, legacy=True),
    _m('loop', 'loop_float', '漂浮', 'soft', '上下轻浮', duration=1200, legacy=True),
    _m('loop', 'loop_sway', '摇曳', 'soft', '左右轻摆', duration=1200, legacy=True),
    _m('loop', 'loop_swing', '摆动', 'soft', '像钟摆一样轻微转动', duration=1600),
    _m('loop', 'loop_wave', '波浪', 'soft', '字依次起伏，像水波', duration=1400),
    _m('loop', 'loop_heartbeat', '心跳', 'accent', '两下一组的跳动', duration=1100),
    _m('loop', 'loop_bounce', '跳动', 'accent', '字依次跳起', duration=1300),
    _m('loop', 'loop_shake', '抖动', 'accent', '细小的紧张抖动', duration=900),
    _m('loop', 'loop_shine', '扫光', 'light', '一道斜光定时扫过', duration=2200),
    _m('loop', 'loop_halo', '光晕呼吸', 'light', '柔光一明一暗', duration=1600),
    _m('loop', 'loop_flicker', '闪烁', 'light', '偶尔闪一下，像霓虹灯', duration=1500),
    _m('loop', 'loop_glitch', '故障', 'glitch', '每隔一会儿短暂色散错位', duration=1800),
]

STAGE_SPECS = {'entry': ENTRY, 'exit': EXIT, 'loop': LOOP}
SPECS = {(m.stage, m.key): m for stage in STAGE_SPECS.values() for m in stage}
RICH_ENTRY = frozenset(m.key for m in ENTRY if not m.legacy)
RICH_EXIT = frozenset(m.key for m in EXIT if not m.legacy)
RICH_LOOP = frozenset(m.key for m in LOOP if not m.legacy)
#: Loops whose phase travels across units need one unit per character.
PER_CHAR_LOOPS = frozenset({'loop_wave', 'loop_bounce'})

CATEGORIES = {
    'entry': [('basic', '基础'), ('bounce', '弹跳'), ('char', '逐字'), ('cinema', '电影感'), ('glitch', '故障')],
    'exit': [('basic', '基础'), ('char', '逐字'), ('cinema', '电影感'), ('glitch', '故障')],
    'loop': [('soft', '柔和'), ('accent', '强调'), ('light', '光效'), ('glitch', '故障')],
    'words': [('karaoke', '卡拉 OK'), ('beat', '节奏'), ('curated', '精选字效')],
}


def spec(stage, key):
    return SPECS.get((stage, key))


def is_rich(stage, key):
    item = spec(stage, key)
    return bool(item and not item.legacy)


# ---------------------------------------------------------------- easing ----

def _c(v):
    return max(0., min(1., v))


def out_cubic(u):
    return 1-(1-_c(u))**3


def out_quint(u):
    return 1-(1-_c(u))**5


def out_expo(u):
    u = _c(u)
    return 1. if u >= 1 else (1-2**(-10*u))/(1-2**-10)


def out_back(u, s=1.70158):
    u = _c(u)-1
    return 1+(s+1)*u**3+s*u*u


def in_cubic(u):
    return _c(u)**3


def smooth(u):
    u = _c(u)
    return u*u*(3-2*u)


def hash01(i, k=0.):
    v = sin(i*12.9898+k*78.233)*43758.5453
    return v-int(v) if v >= 0 else v-int(v)+1


def _jitter(t, i, k):
    """Deterministic, glitchy -1..1 noise held for ~33 ms steps."""
    step = int(t//33)
    return hash01(step*1.37+i*.71, k)*2-1


# ----------------------------------------------------------------- poses ----

class Ctx:
    """Per-unit context: index, count, position (row fractions / em)."""
    __slots__ = ('i', 'n', 'rel', 'cx', 'a', 'b', 'w', 'k', 'fx', 'fy', 'seed', 'line', 't')

    def __init__(self, **kw):
        for name in self.__slots__:
            setattr(self, name, kw.get(name, 0.))


def _fade(u, rate):
    return _c(u*rate)


def entry_pose(key, u, c):
    """State at entry progress ``u`` (0 = before, 1 = rest)."""
    k = c.k
    e3 = out_cubic(u)
    if key == 'zoom_in':
        return {'scale': 1-.55*k*(1-e3), 'opacity': _fade(u, 1.8), 'blur': .1*(1-e3)}
    if key == 'zoom_down':
        return {'scale': 1+.7*k*(1-e3), 'opacity': _fade(u, 1.6), 'blur': .16*k*(1-e3)}
    if key == 'wipe_in':
        return {'line_reveal': -.2+1.4*smooth(u)}
    if key == 'spring_in':
        s = 0. if u <= 0 else (1. if u >= 1 else 1-exp(-6/k*u)*cos(11*u))
        return {'scale': s, 'opacity': _fade(u, 4)}
    if key == 'jelly_in':
        w = 0. if u >= 1 else exp(-4.5*u)*cos(13*u)
        return {'sx': 1-.38*k*w, 'sy': 1+.38*k*w, 'scale': .75+.25*e3, 'opacity': _fade(u, 5)}
    if key == 'typewriter':
        return {'opacity': float(u > 0)}
    if key == 'char_rise':
        return {'y': .55*k*(1-e3), 'opacity': _fade(u, 1.6), 'blur': .12*(1-e3)}
    if key == 'char_pop':
        return {'scale': max(0., out_back(u, 2.2)), 'opacity': _fade(u, 3), 'halo': .8*sin(pi*_c(u))*(1-_c(u))}
    if key == 'char_wave':
        return {'y': .9*k*(1-out_back(u, 2.)), 'opacity': _fade(u, 2.5)}
    if key == 'char_flip':
        return {'sy': max(.02, cos(radians(92*(1-e3)))), 'scale': .7+.3*e3, 'y': -.18*(1-e3),
                'blur': .1*(1-e3), 'opacity': _fade(u, 2)}
    if key == 'char_defocus':
        return {'scale': 1+1.1*k*(1-e3), 'blur': .28*(1-e3), 'opacity': _fade(u, 1.4)}
    if key == 'char_scatter':
        e = out_quint(u)
        rx, ry, rr = (hash01(c.seed, j)*2-1 for j in (1, 2, 3))
        return {'x': rx*2.4*k*(1-e), 'y': (ry*1.6-.3)*k*(1-e), 'rotation': rr*60*(1-e),
                'blur': .15*(1-e), 'opacity': _fade(u, 1.6), 'scale': .6+.4*e}
    if key == 'char_stretch':
        e = out_expo(u)
        return {'sx': 1+3.2*k*(1-e), 'sy': 1-.3*(1-e), 'blur': .22*(1-e), 'opacity': _fade(u, 2)}
    if key == 'zoom_blur_in':
        e = out_expo(u)
        return {'scale': 1+.9*k*(1-e), 'ghost': .95*(1-e), 'gs': .5*k*(1-e), 'blur': .2*(1-e),
                'opacity': _fade(u, 2.5)}
    if key == 'push_in':
        e = out_expo(u)
        left = 1-e
        return {'x': c.fx*3*k*left, 'y': c.fy*2*k*left, 'ghost': left, 'gx': c.fx*1.4*left,
                'gy': c.fy*1.*left, 'sx': 1+.25*left*abs(c.fx), 'sy': 1+.25*left*abs(c.fy),
                'blur': .05*left, 'opacity': _fade(u, 3)}
    if key == 'whip_in':
        e = out_quint(u)
        left = 1-e
        return {'x': c.fx*3.5*k*left, 'y': c.fy*2.2*k*left, 'skew': -c.fx*28*left, 'ghost': .8*left,
                'gx': c.fx*1.*left, 'gy': c.fy*.8*left, 'blur': .06*left, 'opacity': _fade(u, 3)}
    if key == 'flash_in':
        flash = 0. if u <= 0 else exp(-4.5*u)*(1-exp(-40*u))
        return {'opacity': _fade(u, 6), 'flash': min(1., 1.25*flash), 'halo': .9*flash,
                'scale': 1+.06*k*(1-e3)}
    if key == 'doors_in':
        # Halves slam shut first; the white flash only fires once they meet.
        e = out_cubic(u/.6)
        hit = _c((u-.55)/.45)
        flash = 0. if u < .55 else min(1., (u-.55)/.04)*(1-hit)**2
        return {'door': .9*k*(1-e), 'opacity': _fade(u, 5), 'flash': .85*flash, 'halo': .6*flash,
                'sx': 1+.12*sin(pi*hit)}
    if key == 'flip_in':
        return {'sx': max(.02, cos(radians(90*(1-e3)))), 'scale': 1+.5*k*(1-e3), 'opacity': _fade(u, 2),
                'blur': .08*(1-e3)}
    if key == 'shine_in':
        return {'opacity': out_cubic(_c(u*2.2)), 'y': .2*(1-e3), 'line_shine': -.35+1.7*_c((u-.25)/.75)}
    if key == 'echo_in':
        return {'trail': 1-e3, 'ghost': .7*(1-e3), 'gs': .6*k*(1-e3), 'opacity': _fade(u, 1.5)}
    if key == 'glitch_in':
        amount = (1-_c(u))**1.4
        t = c.t
        visible = u > 0 and (u > .82 or hash01(int(t//33), c.seed+.3) > .3*amount)
        return {'opacity': float(visible), 'rgb': .08*k*amount*(.4+.6*abs(_jitter(t, c.seed, 1))),
                'slice': .3*k*amount*_jitter(t, c.seed, 2), 'x': .1*k*amount*_jitter(t, c.seed, 3)}
    if key == 'flicker_in':
        steps = ((.0, 0.), (.08, .9), (.16, 0.), (.3, .55), (.38, 0.), (.52, 1.), (.6, .35), (.7, 1.))
        level = 0.
        for at, value in steps:
            if u >= at:
                level = value
        return {'opacity': level if u < 1 else 1., 'rgb': .03*k*(1-_c(u)), 'halo': .35*(1-_c(u))*level}
    if key == 'slice_in':
        return {'strips': .7*k*(1-e3), 'blur': .1*(1-e3), 'opacity': _fade(u, 2)}
    return {}


def exit_pose(key, q, c):
    """State at exit progress ``q`` (0 = rest, 1 = gone)."""
    k = c.k
    fade = 1-smooth(q)
    i3 = in_cubic(q)
    if key == 'sink_out':
        return {'y': .5*k*i3, 'opacity': fade}
    if key == 'rise_out':
        return {'y': -.5*k*i3, 'opacity': fade}
    if key == 'slide_out':
        return {'x': c.fx*2.2*k*i3, 'y': c.fy*1.4*k*i3, 'blur': .06*q, 'opacity': fade}
    if key == 'blur_out':
        return {'blur': .3*k*q, 'scale': 1+.08*q, 'opacity': fade}
    if key == 'zoom_out':
        return {'scale': 1+.8*k*i3, 'blur': .18*q, 'opacity': fade}
    if key == 'wipe_out':
        return {'line_cut': -.2+1.4*smooth(q)}
    if key == 'char_fade_out':
        return {'y': -.45*k*q*q, 'blur': .14*q, 'opacity': fade}
    if key == 'char_drop_out':
        rr = hash01(c.seed, 4)*2-1
        return {'y': 1.6*k*q*q, 'rotation': rr*35*q, 'opacity': 1-q**3}
    if key == 'char_pop_out':
        s = 1+.35*k*(q/.15) if q < .15 else 1.35*(1-(q-.15)/.85)**1.6
        return {'scale': max(0., s), 'halo': .7*sin(pi*_c(q/.4)), 'opacity': 1.-_c((q-.55)/.45)}
    if key == 'typewriter_out':
        return {'opacity': float(q <= 0)}
    if key == 'shatter_out':
        return {'scatter': 1.3*k*out_cubic(q), 'opacity': 1-q**1.4, 'rotation': (hash01(c.seed, 5)*2-1)*12*q}
    if key == 'zoom_blur_out':
        return {'scale': 1+1.2*k*i3, 'ghost': .9*_c(q*3)*(1-q), 'gs': -.35*i3, 'blur': .2*q,
                'opacity': 1-q**1.3}
    if key == 'push_out':
        e = (2**(10*q-10)-2**-10)/(1-2**-10) if q > 0 else 0.
        return {'x': c.fx*3*k*e, 'y': c.fy*2*k*e, 'ghost': min(1., q*2), 'gx': -c.fx*1.3*e,
                'gy': -c.fy*e, 'sx': 1+.25*e*abs(c.fx), 'sy': 1+.25*e*abs(c.fy), 'opacity': 1-q**3}
    if key == 'flash_out':
        return {'flash': sin(pi*_c(q/.5))*(q < .5) + (q >= .5)*(1-_c((q-.5)/.5)),
                'halo': .8*sin(pi*_c(q/.6)), 'opacity': 1. if q < .35 else 1-_c((q-.35)/.65)**.5,
                'scale': 1+.06*q}
    if key == 'stretch_out':
        return {'sx': 1+3.5*k*q*q, 'sy': 1-.3*q, 'blur': .25*q, 'opacity': 1-q*q}
    if key == 'flip_out':
        return {'sx': max(.02, cos(radians(90*i3))), 'scale': 1+.4*k*q, 'opacity': 1-q*q}
    if key == 'glitch_out':
        amount = _c(q)**1.2
        t = c.t
        visible = q < 1 and (q < .2 or hash01(int(t//33), c.seed+.7) > .55*amount)
        return {'opacity': float(visible)*(1-q**4), 'rgb': .08*k*amount*(.4+.6*abs(_jitter(t, c.seed, 6))),
                'slice': .3*k*amount*_jitter(t, c.seed, 7), 'x': .1*k*amount*_jitter(t, c.seed, 8)}
    return {}


def loop_apply(state, loop, t):
    """Analytic loops, mirrored line-for-line in TimedText.tsx."""
    start, end = loop['start'], loop['end']
    period = max(120, loop.get('duration', 1200))
    ramp = min(1., max(0., (t-start)/(period*.25)), max(0., (end-t)/(period*.25)))
    if ramp <= 0:
        return state
    kind = loop['type']
    amount = STRENGTH.get(loop.get('strength', 'medium'), 1.)*ramp
    phase = 2*pi*(t-start)/period
    wave = (1-sin(phase+pi/2))/2
    i, a, b = loop.get('i', 0), loop.get('a', 0.), loop.get('b', 1.)
    if kind == 'loop_breathe':
        state['scale'] *= 1+.065*wave*amount
    elif kind == 'loop_float':
        state['y'] -= .18*wave*amount
    elif kind == 'loop_sway':
        state['x'] += .18*sin(phase)*amount
    elif kind == 'loop_swing':
        state['rotation'] += 5*sin(phase)*amount
    elif kind == 'loop_wave':
        state['y'] -= .14*sin(phase-2*pi*.85*(a+b)/2)*amount
    elif kind == 'loop_heartbeat':
        ph = ((t-start)/period) % 1.
        beat = exp(-((ph-.08)/.045)**2)+.65*exp(-((ph-.27)/.045)**2)
        state['scale'] *= 1+.085*beat*amount
    elif kind == 'loop_bounce':
        ph = ((t-start)/period-.6*(a+b)/2) % 1.
        hop = sin(pi*ph/.32) if ph < .32 else 0.
        state['y'] -= .26*hop*hop*amount
    elif kind == 'loop_shake':
        speed = 1200./period
        state['x'] += .045*(sin(t*.0372*speed+i*1.7)+.6*sin(t*.0911*speed+i*.9))*amount
        state['y'] += .04*(sin(t*.0433*speed+i*2.3)+.6*sin(t*.0797*speed+i*.4))*amount
    elif kind == 'loop_shine':
        ph = ((t-start)/period) % 1.
        if ph < .55:
            line = -.35+1.7*ph/.55
            state['shine'] = (line-a)/max(.001, b-a)
    elif kind == 'loop_halo':
        state['halo'] = max(state['halo'], (.3+.5*wave)*amount)
    elif kind == 'loop_flicker':
        ph = ((t-start)/period) % 1.
        dip = 1. if .62 < ph < .66 or .72 < ph < .745 else 0.
        state['opacity'] *= 1-.55*dip*amount
        state['halo'] = max(state['halo'], .25*(1-dip)*amount)
    elif kind == 'loop_glitch':
        ph = ((t-start)/period) % 1.
        if ph < .14:
            burst = sin(pi*ph/.14)*amount
            state['rgb'] += .06*burst
            state['slice'] += .22*burst*(1 if int(t//40) % 2 else -1)
            state['x'] += .05*burst*sin(t*.51)
    return state


# ------------------------------------------------------- unit composition ----

def glyph_em(ch):
    if ch in '\r\n':
        return 0.
    if ch.isspace():
        return .3
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 1.
    if ch.isupper():
        return .64
    if ch.isalnum():
        return .56
    return .34


def char_spans(text):
    """Use the same grapheme boundaries as text selection and saved marks."""
    from .text_marks import boundaries
    edges = boundaries(text)
    return [{'char_start':a,'char_end':b} for a,b in zip(edges,edges[1:])]


def geometry(text, units):
    """Estimated em positions; exact for one-unit rows, close for the rest."""
    rows, start = [], 0
    for row in text.split('\n'):
        rows.append((start, start+len(row)))
        start += len(row)+1
    widths = [glyph_em(ch) for ch in text]
    result = []
    for unit in units:
        a, b = unit['char_start'], unit['char_end']
        row = next(((s, e) for s, e in rows if s <= a <= e), None)
        if row is None or b > row[1]+1:
            # One unit across several rows is drawn row by row about each
            # row's own centre: it needs no position compensation.
            result.append((0., 0., 1., max(.5, sum(widths[a:b]))))
            continue
        total = max(.001, sum(widths[row[0]:row[1]]))
        left = sum(widths[row[0]:a])
        width = sum(widths[a:min(b, row[1])])
        result.append((left+width/2-total/2, left/total, (left+width)/total, max(.001, width)))
    return result


def _visible(text, unit):
    return bool(text[unit['char_start']:unit['char_end']].strip())


def _ordering(order, count, visible):
    ids = [i for i in range(count) if visible[i]]
    if order == 'reverse':
        ids.reverse()
    elif order == 'random':
        ids.sort(key=lambda i: hash01(i, 9.1))
    rank = {i: r for r, i in enumerate(ids)}
    return rank, max(1, len(ids))


def _windows(part, motion, count, rank, slots, duration, budget, at_end):
    total = min(float(part.get('duration', motion.duration)), budget)
    delay = min(float(part.get('delay', 0)), max(0., duration-total))
    if motion.per_char and slots > 1:
        stagger = part.get('stagger')
        window = max(16., total*motion.overlap) if stagger is None else max(16., total-float(stagger)*(slots-1))
        window = min(window, total)
        step = (total-window)/(slots-1)
    else:
        window, step = max(1., total), 0.
    base = (duration-delay-total) if at_end else delay
    return {i: (base+rank[i]*step, window) for i in rank}, total


def compose(plan, units, base_sample):
    """Bake rich entry/exit into units; attach per-unit context for loops.

    ``base_sample(unit, local_ms)`` reads a unit's existing (word-mode)
    pose. Acoustic spans are untouched: every new instant is visual only.
    """
    entry, leave = plan.get('rich_entry') or {}, plan.get('rich_exit') or {}
    text = plan['text']
    offset = plan.get('clock_offset_ms', 0)
    duration = max(1., float(plan.get('original_duration_ms', plan['duration_ms'])))
    count = len(units)
    geo = geometry(text, units)
    visible = [_visible(text, u) for u in units]
    entry_spec = spec('entry', entry.get('type')) if entry else None
    exit_spec = spec('exit', leave.get('type')) if leave else None
    in_budget = duration*.6
    out_budget = duration*.4
    if entry_spec and exit_spec:
        want = float(entry.get('duration', entry_spec.duration))+float(leave.get('duration', exit_spec.duration))
        if want > duration*.9:
            in_budget = min(in_budget, duration*.9*float(entry.get('duration', entry_spec.duration))/want)
            out_budget = min(out_budget, duration*.9-in_budget)
    windows_in = windows_out = {}
    if entry_spec:
        rank, slots = _ordering(entry_spec.order, count, visible)
        windows_in, _ = _windows(entry, entry_spec, count, rank, slots, duration, in_budget, False)
    if exit_spec:
        rank, slots = _ordering(exit_spec.order, count, visible)
        windows_out, _ = _windows(leave, exit_spec, count, rank, slots, duration, out_budget, True)
    def ctx(i, part, motion, t):
        cx, a, b, width = geo[i]
        direction = part.get('direction') or motion.directional or 'left'
        fx, fy = DIRECTIONS.get(direction, (-1., 0.))
        return Ctx(i=i, n=count, cx=cx, a=a, b=b, w=width, k=STRENGTH.get(part.get('strength', 'medium'), 1.),
                   fx=fx, fy=fy, seed=units[i]['char_start']+1, t=t)
    from .letter_motion import CHANNELS
    result = []
    for i, unit in enumerate(units):
        cx, a, b, width = geo[i]
        times = {f[0]+offset for f in unit['frames']} | {0., duration}
        for windows, motion in ((windows_in, entry_spec), (windows_out, exit_spec)):
            if motion and i in windows:
                start, window = windows[i]
                n = max(2, motion.samples if 'glitch' not in motion.key and 'flicker' not in motion.key
                        else int(window/33)+2)
                times.update(start+window*j/n for j in range(n+1))
                times.update((start-.5, start+window+.5))
        caret = []
        if entry_spec and entry_spec.key == 'typewriter' and i in windows_in:
            begin = windows_in[i][0]
            later = sorted(s for s, _ in windows_in.values() if s > begin)
            # The cursor follows the newest glyph and blinks after the last.
            caret = [(begin, later[0])] if later else [(begin+500*j, begin+500*j+260) for j in range(2)]
        if exit_spec and exit_spec.key == 'typewriter_out' and i in windows_out:
            begin = windows_out[i][0]
            earlier = [s for s, _ in windows_out.values() if s < begin]
            caret = [(max(earlier) if earlier else begin-300, begin+1)]
        for on, off in caret:
            times.update((on-.5, on, off-.5, off))
        frames = []
        for t in sorted(x for x in times if 0. <= x <= duration):
            state = base_sample(unit, t-offset)
            for name, rest in REST.items():
                state.setdefault(name, rest)
            if entry_spec and i in windows_in:
                start, window = windows_in[i]
                u = _c((t-start)/window)
                # A finished entrance is exactly the rest pose: decaying
                # curves must not leave a faint tint for the whole cue.
                if u < 1:
                    _merge(state, entry_pose(entry_spec.key, u, ctx(i, entry, entry_spec, t)), cx, a, b, count, entry_spec)
            if exit_spec and i in windows_out:
                start, window = windows_out[i]
                q = _c((t-start)/window)
                if q > 0:
                    _merge(state, exit_pose(exit_spec.key, q, ctx(i, leave, exit_spec, t)), cx, a, b, count, exit_spec)
            if any(on <= t < off for on, off in caret):
                state['caret'] = 1.
            frames.append([round(t-offset, 3), *(round(float(state[k]), 5) for k in CHANNELS)])
        item = {**unit, 'frames': frames, 'a': round(a, 5), 'b': round(b, 5), 'cx': round(cx, 4),
                'sw': round(min(4., .42/max(.2, width)), 5)}
        uses_shards = exit_spec and exit_spec.key == 'shatter_out'
        if uses_shards and 'shards' not in item:
            from .letter_motion import shards
            item['shards'] = shards(i)
        result.append(item)
    return result


def _merge(state, pose, cx, a, b, count, motion):
    """Fold one pose into a state. Line effects keep their shape across units."""
    line = not motion.per_char
    for name, value in pose.items():
        if name == 'line_reveal':
            state['reveal'] = min(state['reveal'], _c((value-a)/max(.001, b-a)) if count > 1 else value)
        elif name == 'line_cut':
            state['cut'] = max(state['cut'], _c((value-a)/max(.001, b-a)) if count > 1 else value)
        elif name == 'line_shine':
            state['shine'] = (value-a)/max(.001, b-a)
        elif name in ('opacity', 'scale', 'sx', 'sy'):
            state[name] *= value
        elif name in ('flash', 'halo', 'ghost', 'trail', 'scatter'):
            state[name] = max(state[name], value)
        elif name == 'door' and line and count > 1:
            state['x'] += (1 if cx >= 0 else -1)*value*2.
        else:
            state[name] += value
    if line and count > 1 and cx:
        stretch = pose.get('scale', 1.)*pose.get('sx', 1.)
        if stretch != 1.:
            state['x'] += cx*(stretch-1)


# ------------------------------------------------- shared drawing geometry ----
# Renderers (Qt, ASS, TimedText.tsx) use these exact numbers.
SLICE_BANDS = ((0., .36, 1.), (.36, .64, -.7), (.64, 1., .55))
STRIP_SHIFTS = (.9, -.65, .8, -.9, .55)
GHOST_ALPHA = (.42, .26, .13)
RGB_COLORS = ('#FF2D55', '#19E6FF')
SHINE_SLANT = .32
WIPE_FEATHER = .08


def wipe_bands(cut, reveal, feather=WIPE_FEATHER):
    """Horizontal (start, end, alpha) bands in unit-width fractions.

    ``None`` means draw unclipped. A soft edge is three hard clips, which ASS
    can express exactly as well.
    """
    if reveal >= 1. and cut <= 0.:
        return None
    lo = cut if cut > 0. else -.5
    hi = reveal if reveal < 1. else 1.5
    if hi <= lo or hi+feather <= 0. or lo-feather >= 1.:
        return []
    bands = [(lo+feather if cut > 0. else lo, hi-feather if reveal < 1. else hi, 1.)]
    if reveal < 1.:
        bands += [(max(lo, hi-feather), hi, .55), (hi, hi+feather, .2)]
    if cut > 0.:
        bands += [(lo, min(hi, lo+feather), .55), (lo-feather, lo, .2)]
    return [(round(a, 5), round(b, 5), alpha) for a, b, alpha in bands if b > a]


def signature_progress(stage, key):
    """Progress at which a preset is most visibly itself, for still posters.

    Score = how far the pose is from rest, weighted by how readable it still
    is. Staggered presets use their designed mid point (several glyphs at
    different stages already tell the story).
    """
    item = spec(stage, key)
    if item is None or item.legacy or stage == 'loop':
        return .45
    if item.per_char:
        return item.poster[1]
    pose = entry_pose if stage == 'entry' else exit_pose
    ctx = Ctx(i=0, n=1, cx=0., a=0., b=1., w=6., k=1., fx=-1. if item.directional != 'right' else 1., fy=0., seed=3, t=0.)
    best, best_u = -1., .45
    for step in range(2, 19):
        u = step/20
        ctx.t = u*item.duration
        s = pose(key, u, ctx)
        opacity = s.get('opacity', 1.)
        if opacity < .35:
            continue
        reveal = s.get('line_reveal', s.get('line_cut', None))
        deviation = (abs(s.get('x', 0))+abs(s.get('y', 0))+2*abs(s.get('scale', 1)-1)+abs(s.get('sx', 1)-1)
                     + abs(s.get('sy', 1)-1)+4*s.get('blur', 0)+s.get('ghost', 0)+8*s.get('rgb', 0)
                     + .8*s.get('flash', 0)+2*abs(s.get('slice', 0))+2*s.get('strips', 0)+2*s.get('door', 0)
                     + abs(s.get('skew', 0))/30+s.get('trail', 0)+.6*s.get('halo', 0)
                     + (.6 if reveal is not None and .25 < reveal < .8 else 0.)
                     + (.6 if -.1 < s.get('line_shine', -9) < 1.1 else 0.))
        score = deviation*opacity**1.5
        if score > best+1e-6:
            best, best_u = score, u
    return best_u
