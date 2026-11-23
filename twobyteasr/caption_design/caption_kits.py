"""Version 11 design kits: an art-directed visual vocabulary for AI 设计.

The model acts as art director: it picks a kit (a whole composition archetype,
not a recoloured plate), a palette, a typeface, the emphasis words taken from
the real caption, a text choreography and an energy level. The host expands
that choice once into an ordinary portable theme (static HTML/CSS plus a
MotionSpec v2), so preview, Studio and the Remotion export read the same
source. Caption text is never written here: only ``{{words}}`` is placed.

Every length is in ``em`` of the caption size, so a kit keeps its proportions
at 540p, 1080p and 4K. Motion distances are 1080-reference pixels derived
from the font size, as MotionSpec requires.
"""
import html
import math
import re

VERSION = 'caption-kits-1'
KITS = ('variety', 'neon', 'ink', 'editorial', 'pixel', 'hud', 'sticker', 'cinema', 'comic', 'chrome', 'glass')
MOTIONS = ('native', 'pop', 'rise', 'type', 'drop', 'fade')
ENERGIES = ('calm', 'lively', 'punchy')
COLOR_KEYS = ('ink', 'base', 'accent', 'accent2')
_OUTLINED = ('chrome',)  # kits whose gradient lettering is outlined by a copy underneath
KAI = '楷体'
FONT_STACKS = {KAI: '"KaiTi", "STKaiti", "DFKai-SB", "Source Han Sans SC Medium"'}

# name, one-line look (shown to the model), default palette, default face, size, tilt
_SPEC = {
    'variety': ('综艺花字：无底板，厚描边粗圆字+白色外圈+彩色硬投影，重点词放大换色并垫爆炸贴，角上有漫符短线',
                ('#FFFFFF', '#1B1340', '#FFD23F', '#FF4F8B'), 'ZCOOL KuaiLe', 76, -2),
    'neon': ('霓虹灯牌：无实底，发光灯管字+暗色柔光晕，两段转角灯管围边，重点词换第二种灯色',
             ('#FFF4FB', '#12051F', '#FF3D9A', '#32E6FF'), 'ZCOOL QingKe HuangYou', 78, 0),
    'ink': ('水墨题字：一笔飞白墨带托字，淡墨衬笔，朱砂印章压角，重点词加朱红着重号',
            ('#F6F1E4', '#15130F', '#D8402F', '#8C8472'), KAI, 72, 0),
    'editorial': ('杂志大字：无底板，重字+竖向色条+细线与方块标记，重点词放大成标题色，遮罩上滑揭示',
                  ('#FFFFFF', '#0E0E10', '#FF5A36', '#FFFFFF'), 'Source Han Sans SC Heavy', 70, 0),
    'pixel': ('像素对话框：缺角像素边框+抖动底纹+闪烁光标，点阵字逐字打出，重点词换金色',
              ('#FFFFFF', '#1A1C2C', '#FFCD75', '#41A6F6'), 'Cubic 11', 62, 0),
    'hud': ('科幻HUD：切角暗色面板+扫描线+发光边条和角标，文字带轻微色散，重点词做反色斜切标签，故障切片入场',
            ('#F2FBFF', '#08121C', '#19E3FF', '#FF2E88'), 'Source Han Sans SC Heavy', 66, 0),
    'sticker': ('手帐贴纸：米白模切贴纸微微倾斜，两段和纸胶带，深色手写感字，重点词是荧光笔涂抹',
                ('#2B2622', '#FFF6E0', '#FFD84A', '#FF7A59'), 'ZCOOL KuaiLe', 68, -2),
    'cinema': ('电影字幕：无底板，宽字距细腻字+上下金色发丝线和菱形标，重点词金色渐变，从中间展开',
               ('#FBF7EE', '#000000', '#E8C27A', '#FFFFFF'), 'Source Han Sans SC Medium', 60, 0),
    'comic': ('漫画爆炸框：锯齿爆炸形色块+网点+黑色硬投影，斜体粗字，重点词红色放大，砸入后震一下',
              ('#111111', '#FFE94A', '#FF3B30', '#FFFFFF'), 'Smiley Sans', 74, -3),
    'chrome': ('千禧镀铬：无底板，天空到地平线的金属渐变字+双色描边，四角星闪光与渐变底线',
               ('#FFFFFF', '#2A0A5E', '#FF5BD1', '#5BE9FF'), 'ZCOOL QingKe HuangYou', 80, 0),
    'glass': ('玻璃胶囊：圆角半透明深色胶囊+渐变描边与高光，状态光点，干净细字，重点词渐变色',
              ('#FFFFFF', '#101826', '#7CE3FF', '#B79CFF'), 'Source Han Sans SC Medium', 60, 0),
}


def _rgba(color, alpha):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f'rgba({r},{g},{b},{alpha:g})'


def _ring(radius, color, steps=16, dx=0., dy=0.):
    """A crisp outline as stacked text shadows; it never covers the fill."""
    return ','.join(f'{dx + radius * math.cos(2 * math.pi * i / steps):.4f}em '
                    f'{dy + radius * math.sin(2 * math.pi * i / steps):.4f}em 0 {color}' for i in range(steps))


def _dilate(radius, color):
    """Grow the painted shape by one flat band. Text shadows cannot do this over a stroke:
    Chromium repaints them with the fill pass and they would cover the stroke."""
    # Each shadow also shadows the previous ones, so two passes on each axis make a full band.
    return ' '.join(f'drop-shadow({x}em {y}em 0 {color})' for x, y in
                    ((radius, 0), ('-' + radius, 0), (0, radius), (0, '-' + radius)))


def _burst(spikes=12, inner=.72):
    points = []
    for i in range(spikes * 2):
        radius = 1. if i % 2 == 0 else inner
        angle = math.pi * i / spikes - math.pi / 2
        points.append(f'{50 + 50 * radius * math.cos(angle):.1f}% {50 + 50 * radius * math.sin(angle):.1f}%')
    return 'polygon(' + ','.join(points) + ')'


def _jagged(top=13, side=3, depth_x=2.2, depth_y=13.):
    """A comic panel outline: shallow teeth along every edge, in percent."""
    points = []
    for i in range(top * 2 + 1):
        points.append((100 * i / (top * 2), depth_y if i % 2 else 0))
    for i in range(1, side * 2):
        points.append((100 - (depth_x if i % 2 else 0), 100 * i / (side * 2)))
    for i in range(top * 2 + 1):
        points.append((100 - 100 * i / (top * 2), 100 - (depth_y if i % 2 else 0)))
    for i in range(1, side * 2):
        points.append(((depth_x if i % 2 else 0), 100 - 100 * i / (side * 2)))
    return 'polygon(' + ','.join(f'{x:.1f}% {y:.1f}%' for x, y in points) + ')'


def normalize(value):
    """Only the kit itself is mandatory.

    Everything else is art direction on top of a designed default: an unknown
    key, an unbundled face or a number outside its range falls back to that
    default (numbers are clamped) instead of costing the user a second model
    call. Nothing here can change caption text: emphasis only names phrases,
    and the host marks them where the real line contains them.
    """
    if not isinstance(value, dict) or value.get('version') != 11:
        raise ValueError('设计套件需要version=11')
    kit = value.get('kit')
    if kit not in KITS:
        raise ValueError('不支持的设计套件kit: ' + str(kit))
    _, colors, face, size, tilt = _SPEC[kit]
    palette = value.get('palette') if isinstance(value.get('palette'), dict) else {}
    result = dict(version=11, kit=kit, palette={})
    for key, default in zip(COLOR_KEYS, colors):
        color = palette.get(key)
        result['palette'][key] = (color if isinstance(color, str) and re.fullmatch('#[0-9A-Fa-f]{6}', color)
                                  else default).upper()
    from .web_theme_fonts import FONT_FILES
    family = value.get('fontFamily')
    result['fontFamily'] = family if family in FONT_FILES or family in FONT_STACKS else face
    for key, default, low, high in (('fontSize', size, 40, 110), ('tilt', tilt, -6, 6),
                                     ('buildMs', 620, 200, 800), ('resolveMs', 320, 120, 500)):
        number = value.get(key, default)
        if type(number) not in (int, float) or not math.isfinite(number):
            number = default
        result[key] = min(high, max(low, number))
    result['motion'] = value.get('motion') if value.get('motion') in MOTIONS else 'native'
    result['energy'] = value.get('energy') if value.get('energy') in ENERGIES else 'lively'
    emphasis = value.get('emphasis') if isinstance(value.get('emphasis'), list) else []
    result['emphasis'] = [t.strip() for t in emphasis
                          if isinstance(t, str) and 1 <= len(t.strip()) <= 24 and '|' not in t][:4]
    return result


# --- static composition -----------------------------------------------------------------------

# The layout spans the whole frame on purpose. The host treats any positioned ancestor
# with a resolved height as a text well and shrinks the caption to fit it; a bottom-anchored
# box is only one line tall when measured, so a line with a manual break came out tiny.
_BASE_CSS = '''
.kit-layout{position:absolute;inset:0;box-sizing:border-box;padding:0 5% calc(7.6 * var(--wt-u));display:flex;justify-content:center;align-items:flex-end;font-family:var(--wt-font);font-size:var(--wt-size)}
.kit-tilt{position:relative;max-width:86%}
.kit-shake,.kit-body{position:relative}
.kit-body{width:max-content;max-width:100%;box-sizing:border-box}
.cap-type{position:relative;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);line-height:1.34;text-align:center;color:var(--k-ink)}
.cap-type .wt-w{display:inline-block;white-space:pre}
.cap-type .wt-focus{display:inline-block;position:relative;max-width:100%;vertical-align:baseline}
.kit-deco{position:absolute;pointer-events:none}
'''


def _static(kit, p, size):
    """Return (back markup, front markup, css) for one kit."""
    ink, base, accent, accent2 = (p[k] for k in COLOR_KEYS)
    deco = lambda name: f'<div class="kit-deco kit-{name}" aria-hidden="true"></div>'
    if kit == 'variety':
        back = deco('tick-a') + deco('tick-b')
        css = f'''
.kit-body{{padding:.12em .5em .16em}}
.cap-type{{letter-spacing:.08em;paint-order:stroke fill;-webkit-text-stroke:.03em {ink};filter:{_dilate('.058', base)} {_dilate('.022', '#FFFFFF')} drop-shadow(.06em .085em 0 {accent2})}}
.cap-type .wt-focus{{font-size:1.3em;color:{accent};-webkit-text-stroke:0 transparent;text-shadow:{_ring(.07, base, 18)};margin:0 .26em;transform:rotate(-3deg)}}
.cap-type .wt-focus::before{{content:"";position:absolute;z-index:-1;left:-.22em;right:-.22em;top:-.02em;bottom:-.04em;background:{accent2};clip-path:{_burst(14, .8)};opacity:.96}}
.kit-tick-a,.kit-tick-b{{width:.9em;height:.9em;background:
 linear-gradient({accent},{accent}) 50% 0/.11em .42em no-repeat,
 linear-gradient({accent},{accent}) 0 62%/.4em .11em no-repeat,
 linear-gradient({accent2},{accent2}) 12% 14%/.11em .3em no-repeat;filter:drop-shadow(0 0 .02em {base}) drop-shadow(.03em .04em 0 {base})}}
.kit-tick-a{{left:-.5em;top:-.55em;transform:rotate(-38deg)}}
.kit-tick-b{{right:-.5em;bottom:-.5em;transform:rotate(142deg)}}
'''
        return back, '', css
    if kit == 'neon':
        back = deco('haze') + deco('tube-a') + deco('tube-b')
        glow = lambda c: f'0 0 .035em #FFFFFF,0 0 .1em {c},0 0 .24em {c},0 0 .5em {_rgba(c, .8)},0 0 1em {_rgba(c, .5)}'
        css = f'''
.kit-body{{padding:.2em .7em .24em}}
.kit-haze{{inset:-.55em -1.5em;background:radial-gradient(closest-side,{_rgba(base, .84)},{_rgba(base, .62)} 58%,{_rgba(base, 0)})}}
.cap-type{{letter-spacing:.06em;text-shadow:{glow(accent)}}}
.cap-type .wt-focus{{color:#FFFFFF;text-shadow:{glow(accent2)}}}
.kit-tube-a,.kit-tube-b{{width:1.5em;height:62%;border:.05em solid #FFFFFF;box-shadow:0 0 .08em {accent2},0 0 .26em {accent2},0 0 .6em {_rgba(accent2, .6)},inset 0 0 .08em {accent2},inset 0 0 .26em {accent2}}}
.kit-tube-a{{left:0;top:0;border-right:0;border-bottom:0;border-radius:.32em 0 0 0}}
.kit-tube-b{{right:0;bottom:0;border-left:0;border-top:0;border-radius:0 0 .32em 0}}
'''
        return back, '', css
    if kit == 'ink':
        svg = lambda cls, path, fill, seed, scale: (
            f'<svg class="kit-deco {cls}" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">'
            f'<defs><filter id="{cls}-f" x="-6%" y="-40%" width="112%" height="180%">'
            f'<feTurbulence type="fractalNoise" baseFrequency="0.035 0.5" numOctaves="3" seed="{seed}" result="n"/>'
            f'<feDisplacementMap in="SourceGraphic" in2="n" scale="{scale}" xChannelSelector="R" yChannelSelector="G"/>'
            f'</filter></defs><path d="{path}" fill="{fill}" filter="url(#{cls}-f)"/></svg>')
        back = (svg('kit-wash', 'M5,34 C24,22 62,30 96,20 L98,80 C66,90 32,80 6,90 Z', accent2, 3, 16)
                + svg('kit-brush', 'M1,24 C22,12 58,20 97,10 C99,34 99,62 98,86 C70,94 30,84 3,92 C1,70 2,46 1,24 Z', base, 11, 12))
        front = ('<svg class="kit-deco kit-seal" viewBox="0 0 40 40" aria-hidden="true">'
                 f'<rect x="3" y="3" width="34" height="34" rx="5" fill="{accent}"/>'
                 # Water ripples, deliberately not a readable character: a kit never adds words.
                 '<path d="M9,14 q5.5,-6 11,0 t11,0 M9,21 q5.5,-6 11,0 t11,0 M9,28 q5.5,-6 11,0 t11,0" fill="none" stroke="#FFF3E2" stroke-width="2.6" stroke-linecap="round"/>'
                 '</svg>')
        css = f'''
.kit-body{{padding:.24em 1.05em .28em .8em}}
.kit-brush{{left:0;top:0;width:100%;height:100%;overflow:visible}}
.kit-wash{{left:-3%;top:10%;width:108%;height:104%;overflow:visible;opacity:.5}}
.cap-type{{letter-spacing:.06em;text-shadow:0 .02em .05em {_rgba(base, .9)}}}
.cap-type .wt-focus{{color:#FFE7B0}}
.cap-type .wt-focus .wt-w{{position:relative}}
.cap-type .wt-focus .wt-w::after{{content:"";position:absolute;left:50%;bottom:-.1em;width:.11em;height:.11em;margin-left:-.055em;border-radius:50%;background:{accent}}}
.kit-seal{{right:-.3em;bottom:-.22em;width:.62em;height:.62em;transform:rotate(5deg);filter:drop-shadow(0 .02em .04em {_rgba(base, .5)})}}
'''
        return back, front, css
    if kit == 'editorial':
        back = deco('bar') + deco('rule') + deco('mark')
        css = f'''
.kit-body{{padding:.22em .1em .06em .5em}}
.cap-type{{text-align:left;letter-spacing:.01em;line-height:1.24;paint-order:stroke fill;-webkit-text-stroke:.05em {_rgba(base, .92)};text-shadow:0 .045em 0 {_rgba(base, .7)},0 .1em .26em {_rgba(base, .6)}}}
.cap-type .wt-focus{{font-size:1.42em;line-height:1;color:{accent};letter-spacing:0}}
.kit-bar{{left:.1em;top:.3em;bottom:.12em;width:.11em;background:{accent};box-shadow:0 .03em .1em {_rgba(base, .6)}}}
.kit-rule{{left:.5em;right:.1em;top:.06em;height:max(.02em,1.5px);background:{_rgba(accent2, .9)};box-shadow:0 .02em .06em {_rgba(base, .7)}}}
.kit-mark{{right:.1em;top:-.06em;width:.26em;height:.26em;background:{accent};box-shadow:0 .02em .06em {_rgba(base, .6)}}}
'''
        return back, '', css
    if kit == 'pixel':
        px = .075
        ring = lambda n, c: f'0 {-n * px:g}em 0 0 {c},0 {n * px:g}em 0 0 {c},{-n * px:g}em 0 0 0 {c},{n * px:g}em 0 0 0 {c}'
        back = deco('box') + deco('dither') + deco('cursor')
        css = f'''
.kit-body{{padding:.34em .78em .4em}}
.kit-box{{inset:0;background:{base};box-shadow:{ring(1, ink)},{ring(2, base)},{px * 1.5:g}em {px * 3.5:g}em 0 0 {_rgba('#000000', .45)},inset 0 {px:g}em 0 0 {_rgba(accent2, .55)},inset 0 {-px:g}em 0 0 {_rgba('#000000', .4)}}}
.kit-dither{{left:0;right:0;bottom:0;height:{px * 4:g}em;background:repeating-conic-gradient({_rgba(accent2, .5)} 0% 25%,transparent 0% 50%) 0 0/{px * 2:g}em {px * 2:g}em}}
.cap-type{{letter-spacing:.04em;line-height:1.4;text-shadow:{px * .8:g}em {px * .8:g}em 0 #000000}}
.cap-type .wt-focus{{color:{accent}}}
.kit-cursor{{right:{px * 4:g}em;bottom:{px * 2.4:g}em;width:0;height:0;border-left:{px * 1.6:g}em solid transparent;border-right:{px * 1.6:g}em solid transparent;border-top:{px * 2:g}em solid {accent}}}
'''
        return back, '', css
    if kit == 'hud':
        cut = 'polygon(.42em 0,100% 0,100% calc(100% - .42em),calc(100% - .42em) 100%,0 100%,0 .42em)'
        back = deco('panel') + deco('scan') + deco('edge') + deco('corner-a') + deco('corner-b') + deco('ticks') + deco('chip')
        css = f'''
.kit-body{{padding:.3em .95em .34em 1em}}
.kit-panel{{inset:0;clip-path:{cut};background:repeating-linear-gradient(0deg,{_rgba(accent, .09)} 0 .028em,transparent .028em .1em),linear-gradient(100deg,{_rgba(base, .93)},{_rgba(base, .8)} 60%,{_rgba(accent2, .26)})}}
.kit-scan{{inset:0;clip-path:{cut};background:linear-gradient(100deg,transparent 42%,{_rgba(accent, .34)} 50%,transparent 58%) 0 0/260% 100% no-repeat;background-position-x:140%}}
.kit-edge{{left:.42em;top:0;bottom:.42em;width:.1em;margin-left:-.42em;background:{accent};box-shadow:0 0 .12em {accent},0 0 .34em {_rgba(accent, .7)}}}
.kit-corner-a,.kit-corner-b{{width:.7em;height:.42em;border:.055em solid {accent}}}
.kit-corner-a{{right:-.16em;top:-.16em;border-left:0;border-bottom:0}}
.kit-corner-b{{left:.5em;bottom:-.16em;border-right:0;border-top:0;border-color:{accent2}}}
.kit-ticks{{left:.46em;top:-.2em;width:1.5em;height:.08em;background:repeating-linear-gradient(90deg,{accent} 0 .14em,transparent .14em .22em)}}
.kit-chip{{right:.5em;bottom:-.1em;width:.9em;height:.1em;background:{accent2};box-shadow:0 0 .14em {_rgba(accent2, .8)}}}
.cap-type{{letter-spacing:.045em;text-shadow:-.024em 0 0 {_rgba(accent2, .9)},.024em 0 0 {_rgba(accent, .9)},0 .04em .1em {_rgba(base, .9)}}}
.cap-type .wt-focus{{color:{base};text-shadow:none;padding:0 .2em;margin:0 .06em}}
.cap-type .wt-focus::before{{content:"";position:absolute;z-index:-1;inset:.1em 0 .08em;background:{accent};clip-path:polygon(.16em 0,100% 0,calc(100% - .16em) 100%,0 100%);box-shadow:0 0 .2em {accent}}}
'''
        return back, '', css
    if kit == 'sticker':
        tape = (f'repeating-linear-gradient(90deg,{_rgba(accent2, .9)} 0 .11em,{_rgba(accent2, .62)} .11em .22em)')
        teeth = 'polygon(0 0,100% 0,96% 25%,100% 50%,96% 75%,100% 100%,0 100%,4% 75%,0 50%,4% 25%)'
        back = deco('paper') + deco('tape-a') + deco('tape-b')
        css = f'''
.kit-body{{padding:.3em .8em .34em}}
.kit-paper{{inset:0;border-radius:.1em;background:repeating-linear-gradient(0deg,{_rgba(ink, .07)} 0 max(.014em,1px),transparent max(.014em,1px) .46em) 0 .2em,linear-gradient(170deg,#FFFFFF66,transparent 45%),{base};box-shadow:0 0 0 .075em #FFFFFF,0 .1em 0 .075em {_rgba('#000000', .16)},0 .22em .42em .04em {_rgba('#000000', .38)}}}
.kit-tape-a,.kit-tape-b{{width:1.5em;height:.4em;background:{tape};clip-path:{teeth};opacity:.94}}
.kit-tape-a{{left:-.62em;top:-.12em;transform:rotate(-34deg)}}
.kit-tape-b{{right:-.58em;bottom:-.1em;transform:rotate(-30deg)}}
.cap-type{{letter-spacing:.03em}}
.cap-type .wt-focus{{font-size:1.14em;padding:0 .08em;background:linear-gradient(178deg,transparent 46%,{accent} 46%,{accent} 90%,transparent 90%)}}
'''
        return back, '', css
    if kit == 'cinema':
        back = deco('veil') + deco('rule-a') + deco('rule-b') + deco('gem')
        line = f'linear-gradient(90deg,{_rgba(accent, 0)},{accent} 18%,{accent} 82%,{_rgba(accent, 0)})'
        css = f'''
.kit-body{{padding:.34em .6em .34em}}
.kit-veil{{inset:-.3em -2em;background:radial-gradient(closest-side,{_rgba(base, .6)},{_rgba(base, .38)} 55%,{_rgba(base, 0)})}}
.cap-type{{letter-spacing:.16em;padding-left:.16em;text-shadow:0 .04em .1em {_rgba(base, .95)},0 0 .4em {_rgba(base, .7)}}}
.cap-type .wt-focus{{text-shadow:none;filter:drop-shadow(0 .04em .07em {_rgba(base, .95)})}}
.cap-type .wt-focus .wt-w{{background:linear-gradient(180deg,#FFF6DC 12%,{accent} 55%,#A97A34 96%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.kit-rule-a,.kit-rule-b{{left:0;right:0;height:max(.024em,1.5px);background:{line}}}
.kit-rule-a{{top:.06em}}.kit-rule-b{{bottom:.06em}}
.kit-gem{{left:50%;top:.06em;width:.15em;height:.15em;margin:-.066em 0 0 -.075em;background:{accent};transform:rotate(45deg);box-shadow:0 0 .12em {_rgba(accent, .8)}}}
'''
        return back, '', css
    if kit == 'comic':
        shape = _jagged()
        back = deco('shadow') + deco('rim') + deco('panel') + deco('zap')
        css = f'''
.kit-body{{padding:.34em .95em .38em}}
.kit-shadow,.kit-rim,.kit-panel{{clip-path:{shape}}}
.kit-shadow{{inset:0;transform:translate(.1em,.13em);background:{ink}}}
.kit-rim{{inset:-.06em -.07em;background:{ink}}}
.kit-panel{{inset:0;background:radial-gradient(circle,{_rgba(accent, .5)} 0 .034em,transparent .04em) 0 0/.15em .15em,linear-gradient(180deg,{accent2} 0%,{base} 34%,{base} 100%)}}
.kit-zap{{right:-.42em;top:-.5em;width:.8em;height:.8em;background:{accent};clip-path:polygon(40% 0,62% 34%,100% 30%,70% 58%,84% 100%,48% 72%,10% 96%,28% 56%,0 34%,36% 36%);filter:drop-shadow(.03em .04em 0 {ink})}}
.cap-type{{letter-spacing:.03em;text-shadow:{_ring(.05, accent2, 12)},.08em .1em 0 {_rgba(ink, .28)}}}
.cap-type .wt-focus{{font-size:1.26em;line-height:1;color:{accent};margin:0 .06em;transform:rotate(-3deg);text-shadow:{_ring(.06, '#FFFFFF', 14)},.09em .11em 0 {ink}}}
'''
        return back, '', css
    if kit == 'chrome':
        star = 'polygon(50% 0,58% 42%,100% 50%,58% 58%,50% 100%,42% 58%,0 50%,42% 42%)'
        back = deco('line') + deco('star-a') + deco('star-b') + deco('star-c')
        css = f'''
.kit-body{{padding:.1em .5em .26em}}
.cap-type{{letter-spacing:.09em}}
.kit-stack{{display:grid}}
.kit-stack>.cap-type{{grid-area:1/1}}
.cap-under{{color:{base};paint-order:stroke fill;-webkit-text-stroke:.13em {base}}}
.cap-cast{{color:{accent};-webkit-text-stroke-color:{accent};transform:translate(.05em,.075em)}}
.cap-main .wt-w{{background:linear-gradient(180deg,#FFFFFF 4%,{accent2} 34%,#FFFFFF 49%,{base} 51%,{accent} 82%,#FFFFFF 100%) 0 0/100% 100%;-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
.cap-type .wt-focus{{font-size:1.2em;line-height:1}}
.cap-main .wt-focus .wt-w{{background-image:linear-gradient(180deg,#FFFFFF 4%,#FFE98A 34%,#FFFFFF 49%,#7A2B00 51%,#FFB02E 82%,#FFFFFF 100%)}}
.kit-line{{left:.3em;right:.3em;bottom:.02em;height:.07em;border-radius:.04em;background:linear-gradient(90deg,{_rgba(accent, 0)},{accent} 22%,#FFFFFF 50%,{accent2} 78%,{_rgba(accent2, 0)});box-shadow:0 0 .14em {_rgba(accent, .8)}}}
.kit-star-a,.kit-star-b,.kit-star-c{{background:#FFFFFF;clip-path:{star}}}
.kit-star-a{{left:-.36em;top:-.3em;width:.62em;height:.62em}}
.kit-star-b{{right:-.3em;top:.02em;width:.4em;height:.4em}}
.kit-star-c{{right:.5em;bottom:-.26em;width:.3em;height:.3em;background:{accent2}}}
'''
        return back, '', css
    back = deco('pill') + deco('sheen') + deco('orb')
    css = f'''
.kit-body{{padding:.3em 1em .34em 1.24em}}
.kit-pill{{inset:0;border-radius:.62em;background:linear-gradient(135deg,rgba(255,255,255,.26),rgba(255,255,255,.07) 38%,{_rgba(base, .5)}),{_rgba(base, .66)};box-shadow:inset 0 .03em 0 rgba(255,255,255,.45),inset 0 -.05em .1em {_rgba('#000000', .35)},0 .16em .42em {_rgba('#000000', .4)}}}
.kit-pill::before{{content:"";position:absolute;inset:0;padding:max(.035em,1.5px);border-radius:inherit;background:linear-gradient(135deg,{accent},rgba(255,255,255,.25) 42%,{accent2});-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude}}
.kit-sheen{{inset:0;border-radius:.62em;background:linear-gradient(105deg,transparent 40%,rgba(255,255,255,.3) 50%,transparent 60%) 0 0/260% 100% no-repeat;background-position-x:140%}}
.kit-orb{{left:.5em;top:50%;width:.24em;height:.24em;margin-top:-.12em;border-radius:50%;background:radial-gradient(circle at 35% 30%,#FFFFFF,{accent} 45%,{accent2});box-shadow:0 0 .16em {accent},0 0 .4em {_rgba(accent, .6)}}}
.cap-type{{letter-spacing:.04em;text-shadow:0 .03em .08em {_rgba('#000000', .55)}}}
.cap-type .wt-focus{{text-shadow:none;filter:drop-shadow(0 .03em .05em {_rgba('#000000', .5)})}}
.cap-type .wt-focus .wt-w{{background:linear-gradient(120deg,{accent},{accent2});-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
'''
    return back, '', css


# --- choreography -----------------------------------------------------------------------------

def _tracks(c):
    """One deterministic timeline. Every kit moves its real text in and out."""
    kit, size, energy = c['kit'], c['fontSize'], c['energy']
    gain = {'calm': .6, 'lively': 1., 'punchy': 1.35}[energy]
    em = lambda n: round(n * size * gain, 2)
    rows = []

    def add(selector, phase, start, end, before, after, ease, **extra):
        rows.append(dict(selector=selector, phase=phase, start=start, end=end, ease=ease,
                         **{'from': before, 'to': after}, **extra))
    enter = lambda sel, a, b, f, t, ease='power3.out', **kw: add(sel, 'build', a, b, f, t, ease, **kw)
    leave = lambda sel, a, b, f, t, ease='power2.in', **kw: add(sel, 'resolve', a, b, f, t, ease, **kw)
    hold = lambda sel, f, t, ms, ease='sine.inOut', **kw: add(sel, 'breathe', 0, 1, f, t, ease, sustain=True,
                                                             durationMs=ms, minCueMs=1600, **kw)
    chars = '.cap-type .wt-w'
    forward = dict(amountMs=170, groupSize=1, order='forward')
    center = dict(amountMs=150, groupSize=1, order='center')
    motion = c['motion']
    native = motion == 'native'
    text_start = .2

    # Ornaments first: the frame, band or lights arrive, then the words land in it.
    if kit == 'variety':
        enter('.kit-tick-a', .55, 1, dict(scaleX=0, scaleY=0, opacity=0), dict(scaleX=1, scaleY=1, opacity=1), 'back.out(1.7)')
        enter('.kit-tick-b', .62, 1, dict(scaleX=0, scaleY=0, opacity=0), dict(scaleX=1, scaleY=1, opacity=1), 'back.out(1.7)')
        leave('.kit-tick-a', 0, .5, dict(scaleX=1, scaleY=1, opacity=1), dict(scaleX=0, scaleY=0, opacity=0))
        leave('.kit-tick-b', 0, .5, dict(scaleX=1, scaleY=1, opacity=1), dict(scaleX=0, scaleY=0, opacity=0))
        text_start = 0
        if native: motion = 'pop'
    elif kit == 'neon':
        enter('.kit-haze', 0, .5, dict(opacity=0), dict(opacity=1), 'power1.out')
        for name, at in (('.kit-tube-a', 0), ('.kit-tube-b', .12)):
            enter(name, at, at + .1, dict(opacity=0), dict(opacity=1), 'steps(2)')
            enter(name, at + .1, at + .18, dict(opacity=1), dict(opacity=.2), 'steps(2)')
            enter(name, at + .18, at + .34, dict(opacity=.2), dict(opacity=1), 'steps(3)')
            leave(name, .3, .8, dict(opacity=1), dict(opacity=0), 'steps(4)')
        leave('.kit-haze', .4, 1, dict(opacity=1), dict(opacity=0))
        if energy != 'calm':
            hold('.kit-tube-b', dict(opacity=1), dict(opacity=.62), 1900, 'steps(6)', yoyo=True)
        if native: motion = 'flicker'
    elif kit == 'ink':
        wipe_in = (dict(clipPath='inset(-40% 100% -40% -6%)'), dict(clipPath='inset(-40% -6% -40% -6%)'))
        wipe_out = (dict(clipPath='inset(-40% -6% -40% -6%)'), dict(clipPath='inset(-40% -6% -40% 100%)'))
        enter('.kit-wash', 0, .5, *wipe_in, 'power2.out')
        enter('.kit-brush', .08, .62, *wipe_in, 'power2.inOut')
        enter('.kit-seal', .72, 1, dict(scaleX=1.7, scaleY=1.7, opacity=0), dict(scaleX=1, scaleY=1, opacity=1), 'power3.in')
        leave('.kit-seal', 0, .4, dict(opacity=1), dict(opacity=0))
        leave('.kit-brush', .2, .9, *wipe_out, 'power2.in')
        leave('.kit-wash', .3, 1, *wipe_out, 'power2.in')
        text_start = .34
        if native: motion = 'rise'
    elif kit == 'editorial':
        enter('.kit-bar', 0, .45, dict(scaleY=0, transformOrigin='50% 0%'), dict(scaleY=1, transformOrigin='50% 0%'), 'expo.out')
        enter('.kit-rule', .1, .7, dict(scaleX=0, transformOrigin='0% 50%'), dict(scaleX=1, transformOrigin='0% 50%'), 'expo.out')
        enter('.kit-mark', .5, .85, dict(scaleX=0, scaleY=0, rotation=-90), dict(scaleX=1, scaleY=1, rotation=0), 'back.out(1.7)')
        leave('.kit-mark', 0, .4, dict(scaleX=1, scaleY=1), dict(scaleX=0, scaleY=0))
        leave('.kit-rule', .1, .7, dict(scaleX=1, transformOrigin='100% 50%'), dict(scaleX=0, transformOrigin='100% 50%'))
        leave('.kit-bar', .3, .95, dict(scaleY=1, transformOrigin='50% 100%'), dict(scaleY=0, transformOrigin='50% 100%'))
        if native: motion = 'mask'
    elif kit == 'pixel':
        box = ('.kit-box', '.kit-dither')
        for name in box:
            enter(name, 0, .3, dict(scaleY=.12, opacity=0), dict(scaleY=1, opacity=1), 'steps(4)')
            leave(name, .45, .95, dict(scaleY=1, opacity=1), dict(scaleY=.12, opacity=0), 'steps(4)')
        enter('.kit-cursor', .85, 1, dict(opacity=0), dict(opacity=1), 'steps(2)')
        leave('.kit-cursor', 0, .2, dict(opacity=1), dict(opacity=0), 'steps(2)')
        hold('.kit-cursor', dict(y=0), dict(y=em(.07) / gain), 520, 'steps(2)', yoyo=True)
        text_start = .28
        if native: motion = 'type'
    elif kit == 'hud':
        open_ = (dict(clipPath='inset(50% 0% 50% 0%)', opacity=0), dict(clipPath='inset(0% 0% 0% 0%)', opacity=1))
        enter('.kit-panel', 0, .42, *open_, 'expo.out')
        enter('.kit-edge', 0, .35, dict(scaleY=0, opacity=0), dict(scaleY=1, opacity=1), 'expo.out')
        for name, at, dx in (('.kit-corner-a', .25, 26), ('.kit-corner-b', .3, -26), ('.kit-ticks', .35, -18), ('.kit-chip', .4, 18)):
            enter(name, at, at + .4, dict(x=dx, opacity=0), dict(x=0, opacity=1), 'power3.out')
            leave(name, 0, .5, dict(x=0, opacity=1), dict(x=dx, opacity=0))
        enter('.kit-shake', .3, .42, dict(x=-em(.3)), dict(x=em(.16)), 'steps(3)')
        enter('.kit-shake', .42, .56, dict(x=em(.16)), dict(x=0), 'steps(2)')
        hold('.kit-scan', dict(backgroundPositionX=round(size * 9)), dict(backgroundPositionX=-round(size * 9)), 2800, 'none')
        leave('.kit-shake', 0, .22, dict(x=0), dict(x=em(.22)), 'steps(2)')
        leave('.kit-edge', .3, .9, dict(scaleY=1, opacity=1), dict(scaleY=0, opacity=0))
        leave('.kit-panel', .3, .95, dict(clipPath='inset(0% 0% 0% 0%)', opacity=1), dict(clipPath='inset(50% 0% 50% 0%)', opacity=0), 'expo.in')
        if native: motion = 'glitch'
    elif kit == 'sticker':
        enter('.kit-body', 0, .62, dict(scaleX=1.32, scaleY=1.32, rotation=7, opacity=0),
              dict(scaleX=1, scaleY=1, rotation=0, opacity=1), 'back.out(1.7)')
        enter('.kit-tape-a', .5, .86, dict(scaleX=0, opacity=0), dict(scaleX=1, opacity=1), 'power3.out')
        enter('.kit-tape-b', .6, .96, dict(scaleX=0, opacity=0), dict(scaleX=1, opacity=1), 'power3.out')
        leave('.kit-body', .1, .95, dict(y=0, rotation=0, opacity=1), dict(y=-em(.5), rotation=-7, opacity=0))
        if native: motion = 'fade'
    elif kit == 'cinema':
        enter('.kit-veil', 0, .6, dict(opacity=0), dict(opacity=1), 'power1.out')
        for name in ('.kit-rule-a', '.kit-rule-b'):
            enter(name, 0, .75, dict(scaleX=0, opacity=0), dict(scaleX=1, opacity=1), 'expo.out')
            leave(name, .2, .95, dict(scaleX=1, opacity=1), dict(scaleX=0, opacity=0), 'power3.in')
        enter('.kit-gem', .3, .9, dict(scaleX=0, scaleY=0), dict(scaleX=1, scaleY=1), 'back.out(1.7)')
        leave('.kit-gem', 0, .4, dict(scaleX=1, scaleY=1), dict(scaleX=0, scaleY=0))
        leave('.kit-veil', .3, 1, dict(opacity=1), dict(opacity=0))
        if native: motion = 'unfold'
    elif kit == 'comic':
        enter('.kit-body', 0, .34, dict(scaleX=2.1, scaleY=2.1, opacity=0), dict(scaleX=1, scaleY=1, opacity=1), 'power4.in')
        enter('.kit-zap', .4, .8, dict(scaleX=0, scaleY=0, rotation=-50), dict(scaleX=1, scaleY=1, rotation=0), 'back.out(1.7)')
        rows.append(dict(selector='.kit-shake', phase='breathe', start=0, end=1, ease='none', durationMs=320, minCueMs=1200,
                         **{'from': dict(x=0, y=0, rotation=0), 'to': dict(x=0, y=0, rotation=0)},
                         wiggle=dict(amplitudeX=round(9 * gain, 1), amplitudeY=round(7 * gain, 1), rotation=round(.9 * gain, 2),
                                     frequency=26, seed=11, intensity=1, fadeInMs=0, fadeOutMs=240)))
        leave('.kit-body', .05, .95, dict(scaleX=1, scaleY=1, rotation=0, opacity=1), dict(scaleX=.6, scaleY=.6, rotation=9, opacity=0), 'back.in')
        if native: motion = 'fade'
    elif kit == 'chrome':
        enter('.kit-line', .1, .7, dict(scaleX=0, opacity=0), dict(scaleX=1, opacity=1), 'expo.out')
        leave('.kit-line', .2, .9, dict(scaleX=1, opacity=1), dict(scaleX=0, opacity=0))
        for i, name in enumerate(('.kit-star-a', '.kit-star-b', '.kit-star-c')):
            enter(name, .5 + i * .1, .8 + i * .1, dict(scaleX=0, scaleY=0, rotation=-90), dict(scaleX=1, scaleY=1, rotation=0), 'back.out(1.7)')
            leave(name, i * .08, .5 + i * .08, dict(scaleX=1, scaleY=1), dict(scaleX=0, scaleY=0))
            if energy != 'calm':
                hold(name, dict(opacity=1), dict(opacity=.35), 900 + i * 340, 'sine.inOut', yoyo=True)
        if native: motion = 'drop'
    else:
        enter('.kit-body', 0, .7, dict(y=em(.42), scaleX=.94, scaleY=.94, opacity=0), dict(y=0, scaleX=1, scaleY=1, opacity=1), 'power3.out')
        enter('.kit-orb', .4, .9, dict(scaleX=0, scaleY=0), dict(scaleX=1, scaleY=1), 'back.out(1.7)')
        enter('.kit-sheen', .45, 1, dict(backgroundPositionX=round(size * 9)), dict(backgroundPositionX=-round(size * 9)), 'power1.inOut')
        leave('.kit-body', .1, .95, dict(y=0, opacity=1), dict(y=-em(.3), opacity=0))
        if energy != 'calm':
            hold('.kit-orb', dict(opacity=1), dict(opacity=.45), 1400, 'sine.inOut', yoyo=True)
        if native: motion = 'fade'

    # The words. Each choreography binds the real characters to build and resolve.
    a = text_start
    if motion == 'pop':
        enter(chars, a, 1, dict(scaleX=.2, scaleY=.2, y=em(.3), rotation=-14, opacity=0),
              dict(scaleX=1, scaleY=1, y=0, rotation=0, opacity=1), 'back.out(1.7)', stagger=dict(forward, amountMs=220))
        leave(chars, 0, .8, dict(scaleX=1, scaleY=1, opacity=1), dict(scaleX=.4, scaleY=.4, opacity=0), 'back.in', stagger=dict(amountMs=90, groupSize=1, order='reverse'))
    elif motion == 'rise':
        enter(chars, a, 1, dict(y=em(.34), opacity=0), dict(y=0, opacity=1), 'power3.out', stagger=forward)
        leave(chars, 0, .7, dict(y=0, opacity=1), dict(y=-em(.2), opacity=0), stagger=dict(amountMs=80, groupSize=2, order='forward'))
    elif motion == 'type':
        enter(chars, a, 1, dict(opacity=0), dict(opacity=1), 'steps(2)', stagger=dict(amountMs=240, groupSize=1, order='forward'))
        leave(chars, 0, .5, dict(opacity=1), dict(opacity=0), 'steps(2)', stagger=dict(amountMs=80, groupSize=2, order='reverse'))
    elif motion == 'drop':
        enter(chars, a, 1, dict(y=-em(.8), rotation=-12, opacity=0), dict(y=0, rotation=0, opacity=1), 'bounce.out', stagger=dict(forward, amountMs=200))
        leave(chars, 0, .8, dict(y=0, opacity=1), dict(y=em(.5), opacity=0), stagger=dict(amountMs=90, groupSize=1, order='forward'))
    elif motion == 'flicker':
        enter(chars, a, .8, dict(opacity=0), dict(opacity=1), 'steps(3)', stagger=dict(amountMs=200, groupSize=2, order='center'))
        enter('.cap-type', .8, .88, dict(opacity=1), dict(opacity=.35), 'steps(2)')
        enter('.cap-type', .88, 1, dict(opacity=.35), dict(opacity=1), 'steps(2)')
        leave('.cap-type', 0, .3, dict(opacity=1), dict(opacity=.3), 'steps(3)')
        leave(chars, .3, .9, dict(opacity=1), dict(opacity=0), 'steps(2)', stagger=dict(amountMs=60, groupSize=2, order='reverse'))
    elif motion == 'mask':
        enter('.cap-type', a, .9, dict(clipPath='inset(100% -10% -10% -10%)'), dict(clipPath='inset(-10% -10% -10% -10%)'), 'expo.out')
        enter(chars, a, 1, dict(y=em(.7), opacity=0), dict(y=0, opacity=1), 'expo.out', stagger=dict(forward, amountMs=120))
        leave(chars, 0, .8, dict(y=0, opacity=1), dict(y=-em(.5), opacity=0), 'expo.in', stagger=dict(amountMs=70, groupSize=2, order='forward'))
    elif motion == 'glitch':
        enter(chars, a, .85, dict(x=em(.3), opacity=0), dict(x=0, opacity=1), 'steps(3)', stagger=center)
        leave(chars, .1, .7, dict(opacity=1), dict(opacity=0), 'steps(2)', stagger=dict(amountMs=60, groupSize=3, order='center'))
    elif motion == 'unfold':
        enter(chars, .15, 1, dict(y=em(.14), scaleX=1.18, opacity=0), dict(y=0, scaleX=1, opacity=1), 'sine.out', stagger=dict(center, amountMs=230))
        leave(chars, 0, .75, dict(scaleX=1, opacity=1), dict(scaleX=1.12, opacity=0), 'sine.in', stagger=dict(amountMs=90, groupSize=1, order='center'))
    else:
        enter(chars, max(a, .2), .95, dict(y=em(.12), opacity=0), dict(y=0, opacity=1), 'power2.out', stagger=dict(forward, amountMs=120))
        leave(chars, 0, .55, dict(opacity=1), dict(opacity=0), stagger=dict(amountMs=50, groupSize=3, order='forward'))

    # The emphasis lands a beat after its sentence; it may be absent on other lines.
    focus = '.cap-type .wt-focus'
    # Its own backing (burst, chip, marker stroke) must not sit there empty before the word.
    if kit in ('variety', 'comic', 'chrome', 'editorial'):
        enter(focus, .4, 1, dict(scaleX=1.5, scaleY=1.5, opacity=0), dict(scaleX=1, scaleY=1, opacity=1), 'back.out(1.7)', optional=True)
    else:
        enter(focus, .4, 1, dict(opacity=0), dict(opacity=1), 'power2.out', optional=True)
    leave(focus, .1, .7, dict(opacity=1), dict(opacity=0), optional=True)
    if energy != 'calm' and kit in ('variety', 'comic', 'sticker'):
        hold(focus, dict(scaleX=1, scaleY=1), dict(scaleX=1.06, scaleY=1.06), 620, 'sine.inOut', yoyo=True, optional=True)
    if energy == 'punchy' and kit not in ('comic', 'cinema', 'ink'):
        rows.append(dict(selector='.kit-shake', phase='breathe', start=0, end=1, ease='none', minCueMs=1600,
                         **{'from': dict(x=0, y=0, rotation=0), 'to': dict(x=0, y=0, rotation=0)},
                         wiggle=dict(amplitudeX=1.4, amplitudeY=1.1, rotation=.28, frequency=2.2, seed=5, intensity=1,
                                     fadeInMs=200, fadeOutMs=200)))
    return rows


def compose(value):
    c = normalize(value)
    back, front, kit_css = _static(c['kit'], c['palette'], c['fontSize'])
    emphasis = html.escape('|'.join(c['emphasis']), quote=True)
    words = f'<div class="cap-type cap-main" data-semantic-text="true" data-emphasis="{emphasis}">{{{{words}}}}</div>'
    if c['kit'] in _OUTLINED:
        # A gradient fill cannot carry a stroke, and a chain of filters on it is slow and
        # did not rasterize the same in preview and export. An exact copy underneath does:
        # it shares the class, so layout, emphasis and every motion track stay in step.
        copy = lambda extra: (f'<div class="cap-type cap-under{extra}" aria-hidden="true" data-emphasis="{emphasis}">'
                              '{{words}}</div>')
        words = '<div class="kit-stack">' + copy(' cap-cast') + copy('') + words + '</div>'
    markup = (f'<div class="kit-layout kit-{c["kit"]}"><div class="kit-tilt"><div class="kit-shake"><div class="kit-body">'
              + back + words + front + '</div></div></div></div>')
    css = _BASE_CSS + ('.kit-layout{' + ''.join(f'--k-{k}:{c["palette"][k]};' for k in COLOR_KEYS) + '}\n'
                       + (f'.kit-tilt{{transform:rotate({c["tilt"]:g}deg)}}\n' if c['tilt'] else '')) + kit_css
    family = c['fontFamily']
    weight = 900 if 'Heavy' in family else 500 if 'Source Han' in family else 400
    return dict(cueHtml=markup, cueCss=css, stageHtml='', stageCss='',
                appearance=dict(fontFamily=FONT_STACKS.get(family, family), fontSize=c['fontSize'], fontWeight=weight),
                palette=dict(primary=c['palette']['accent'], secondary=c['palette']['accent2'],
                             accent=c['palette']['accent'], background=c['palette']['base'], text=c['palette']['ink']),
                motionSpec=dict(version=2, runtime='gsap', buildMs=c['buildMs'], resolveMs=c['resolveMs'], tracks=_tracks(c)))


def capability_text():
    kits = '\n'.join(f'- {name}：{_SPEC[name][0]}（默认字体 {_SPEC[name][2]}）' for name in KITS)
    return f'''设计套件 {VERSION}（components.version=11）。你是美术指导：先决定这句字幕在这个主题下应该长成哪一种东西，再定色、定字、定重点、定动作；宿主把选择展开成同一份主题源码，预览、采用与导出完全一致。
components: {{version:11,kit:套件ID,palette:{{ink:文字色,base:底/描边深色,accent:主强调色,accent2:第二强调色}},fontFamily:打包字体名或"{KAI}",fontSize:40..110,emphasis:[真实字幕里的重点字组],motion:{'|'.join(MOTIONS)},energy:{'|'.join(ENERGIES)},tilt:-6..6,buildMs:200..800,resolveMs:120..500}}。只有version和kit必填，其余不写就用该套件设计好的默认值。
套件（每个都是不同的构图，不是同一块底板换颜色）：
{kits}
选择方法：
1. 三个候选必须用三个不同的kit，并且气质拉开（例如一个无底板的字面设计、一个有器物感的框体、一个克制干净的）。只换颜色不算不同方案。
2. palette按用户主题重新配色：四色要有明确分工，ink与base必须高反差；accent是画面里最抢眼的颜色，用量最少；不要四个颜色都高饱和。主题有公认配色时用它的配色。
3. emphasis只能摘录字幕原文里连续出现的字，选情绪或信息最重的1至2组（每组2至4字），不要选助词，不要改字、加字。
4. motion写native使用套件自带的招牌进退场；也可换成pop逐字弹出、rise上浮、type打字、drop掉落回弹、fade淡入。energy：calm克制，lively有呼吸，punchy带冲击和微颤。
5. tilt只给贴纸、花字、漫画这类俏皮风格，正式或电影感写0。'''


def examples():
    """Explicit local compositions for tests and review sheets, never a silent fallback."""
    return [dict(version=11, kit=kit) for kit in KITS]
