"""Version 12: application-owned motion templates for AI 设计.

A template is a whole effect caption designed and reviewed by hand (the
round-2 drafts the user picked, 2026-11-20). The model only chooses one and a
few bounded parameters. This module expands the template's static HTML/CSS;
``renderer/src/webThemeTemplates.js`` adds the movement to the cue's single
paused GSAP timeline, so the LIVE preview and the Remotion export run the same
code at the same cue time. Caption text is only ``{{words}}``.
"""
import html
import math
import re

VERSION = 'caption-templates-1'
INTENSITIES = ('calm', 'normal', 'heavy')

_DESC = {
    'vhs-signal': ('訊號干擾：錄影帶播放畫面。白色細外框的半透明黑框，四角是像素字 ▶PLAY、時間碼、頻道；'
                   '字有紅藍色彩溢出，框底一條磁頭雜訊，重點詞反白。入場雪花一閃、框垂直跳格、逐字打出、追蹤雜訊帶掃過；'
                   '出場像倒帶一樣撕裂消失。克制、乾淨、有設計感，適合大多數實況與吐槽。'),
    'hud-lock': ('戰術鎖定：石墨黑半透明框、白色細線與四個瞄準角、上方灰色等寬小字（頻道、REC、時間碼）、下方訊號格；'
                 '只有一個強調色，用在鎖定的重點詞和 REC 燈。入場逐格開機閃爍、框線從中間畫開、瞄準角飛入咬合、'
                 '字被方塊碼逐字解碼；重點詞被鎖定框住變成強調色；出場像螢幕關機縮成一點。適合緊張、競技、射擊、科幻。'),
}
_DEFAULTS = {'vhs-signal': dict(ink='#FBFBF6', base='#000000', accent='#F4F4EE', fontFamily='Source Han Sans SC Heavy', fontSize=64),
             'hud-lock': dict(ink='#F5F5F2', base='#0E0F11', accent='#FFB020', fontFamily='Source Han Sans SC Heavy', fontSize=62)}
# Decoration faces ride in the appearance stack so preview and export both load
# them; the caption font comes first and covers every caption glyph.
_EXTRA_FONTS = {'vhs-signal': ('Cubic 11',), 'hud-lock': ('JetBrains Mono',)}


def template_ids():
    return tuple(_DESC)


def validate_template(value):
    """The MotionSpec ``template`` block; the runtime trusts only this shape."""
    if not isinstance(value, dict) or set(value) - {'id', 'params'}:
        raise ValueError('motionSpec.template 只接受 id 与 params')
    if value.get('id') not in _DESC:
        raise ValueError('motionSpec.template.id 不是已上架的动态模板：' + str(value.get('id')))
    params = value.get('params', {})
    if not isinstance(params, dict) or set(params) - {'seed', 'intensity'}:
        raise ValueError('motionSpec.template.params 只接受 seed 与 intensity')
    seed = params.get('seed', 0)
    if type(seed) is not int or not 0 <= seed <= 999999:
        raise ValueError('motionSpec.template.params.seed 需要 0..999999 的整数')
    if params.get('intensity', 'normal') not in INTENSITIES:
        raise ValueError('motionSpec.template.params.intensity 只能是 ' + '/'.join(INTENSITIES))
    return {'id': value['id'], 'params': {'seed': seed, 'intensity': params.get('intensity', 'normal')}}


def _color(value, default):
    return (value if isinstance(value, str) and re.fullmatch('#[0-9A-Fa-f]{6}', value) else default).upper()


def _rgba(color, alpha):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f'rgba({r},{g},{b},{alpha:g})'


def normalize(value):
    """Like the kits: only the template is required; loose values fall back to the design."""
    if not isinstance(value, dict) or value.get('version') != 12:
        raise ValueError('动态模板需要version=12')
    template = value.get('template')
    if template not in _DESC:
        raise ValueError('不支持的动态模板：' + str(template))
    d = _DEFAULTS[template]
    palette = value.get('palette') if isinstance(value.get('palette'), dict) else {}
    from .web_theme_fonts import FONT_FILES
    family = value.get('fontFamily') if value.get('fontFamily') in FONT_FILES else d['fontFamily']
    size = value.get('fontSize', d['fontSize'])
    size = d['fontSize'] if type(size) not in (int, float) or not math.isfinite(size) else min(96, max(44, size))
    seed = value.get('seed')
    emphasis = value.get('emphasis') if isinstance(value.get('emphasis'), list) else []
    return dict(version=12, template=template,
                palette={k: _color(palette.get(k), d[k]) for k in ('ink', 'base', 'accent')},
                fontFamily=family, fontSize=size,
                intensity=value.get('intensity') if value.get('intensity') in INTENSITIES else 'normal',
                seed=seed if type(seed) is int and 0 <= seed <= 999999 else 0,
                emphasis=[t.strip() for t in emphasis if isinstance(t, str) and 1 <= len(t.strip()) <= 24 and '|' not in t][:4])


def _vhs(c):
    p = c['palette']
    emphasis = html.escape('|'.join(c['emphasis']), quote=True)
    markup = ('<div class="vhs-layout"><div class="vhs-g">'
              '<div class="vhs-box" aria-hidden="true"></div>'
              '<div class="vhs-osd vhs-play" aria-hidden="true">▶ PLAY</div>'
              '<div class="vhs-osd vhs-tc" aria-hidden="true">SP 0:12:41</div>'
              '<div class="vhs-osd vhs-ch" aria-hidden="true">CH 03</div>'
              f'<div class="vhs-type" data-semantic-text="true" data-emphasis="{emphasis}">{{{{words}}}}</div>'
              '<div class="vhs-head" aria-hidden="true"></div></div></div>')
    css = f'''
.vhs-layout{{position:absolute;inset:0;box-sizing:border-box;padding:0 6% calc(9 * var(--wt-u));display:flex;justify-content:center;align-items:flex-end;font-family:var(--wt-font);font-size:var(--wt-size)}}
.vhs-g{{position:relative;max-width:86%;min-width:8.6em;padding:.38em .9em .44em;box-sizing:border-box}}
.vhs-box{{position:absolute;inset:0;background:{_rgba(p['base'], .66)};box-shadow:inset 0 0 0 .047em {p['accent']}}}
.vhs-type{{position:relative;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);line-height:1.32;letter-spacing:.06em;text-align:center;color:{p['ink']};
  text-shadow:calc(var(--vhs-ca, .045em) * -1) 0 0 rgba(255,31,75,.8),var(--vhs-ca, .045em) 0 0 rgba(24,225,255,.8),0 0 .03em rgba(255,255,255,.45);filter:blur(.0055em)}}
.vhs-type .wt-w{{display:inline-block;white-space:pre}}
.vhs-type .wt-focus{{display:inline-block;background:{p['accent']};color:#0B0B0B;text-shadow:none;padding:0 .14em;margin:0 .06em}}
.vhs-type .wt-focus .wt-w{{text-shadow:none}}
.vhs-osd{{position:absolute;font-family:"Cubic 11",monospace;font-size:.53em;line-height:1;color:#FFFFFF;letter-spacing:.06em;white-space:nowrap;
  text-shadow:.09em 0 0 #000,-.09em 0 0 #000,0 .09em 0 #000,0 -.09em 0 #000,-.06em 0 0 rgba(255,32,80,.67),.06em 0 0 rgba(32,224,255,.67)}}
.vhs-play{{left:0;bottom:calc(100% + .3em)}}
.vhs-tc{{right:0;bottom:calc(100% + .3em)}}
.vhs-ch{{left:0;top:calc(100% + .4em)}}
.vhs-head{{position:absolute;left:.1em;right:.1em;bottom:.16em;height:.08em;opacity:.6;background:repeating-linear-gradient(90deg,#FFFFFF 0 .05em,transparent .05em .14em)}}
.vhs-snow,.vhs-band{{position:absolute;left:0;right:0;opacity:0;mix-blend-mode:screen;overflow:hidden;pointer-events:none}}
.vhs-snow{{top:0;bottom:0}}
.vhs-band{{top:0;height:.4em}}
.vhs-snow svg,.vhs-band svg{{display:block;width:100%;height:100%}}
'''
    return markup, css


def _hud(c):
    p = c['palette']
    emphasis = html.escape('|'.join(c['emphasis']), quote=True)
    br = ''.join(f'<div class="hud-br {v} {h}" aria-hidden="true"></div>' for v in ('t', 'b') for h in ('l', 'r'))
    markup = ('<div class="hud-layout"><div class="hud-g">'
              '<div class="hud-plate" aria-hidden="true"></div>'
              '<div class="hud-rule hud-rule-t" aria-hidden="true"><i class="l"></i><i class="r"></i></div>'
              '<div class="hud-rule hud-rule-b" aria-hidden="true"><i class="l"></i><i class="r"></i></div>' + br +
              '<div class="hud-head" aria-hidden="true"><span class="hud-ring"></span><span class="hud-label">SUB-FEED // CH 01</span>'
              '<span class="hud-rec"><i></i>REC <b class="hud-tc">00:12:41:00</b></span></div>'
              f'<div class="hud-type" data-semantic-text="true" data-emphasis="{emphasis}">{{{{words}}}}</div>'
              '<div class="hud-foot" aria-hidden="true"><span>SIG</span><span class="hud-seg">' + '<i></i>' * 24 +
              '</span><span><b class="hud-sig">-42.6</b> dB</span></div>'
              '<div class="hud-cur" aria-hidden="true"></div></div></div>')
    mono = '"JetBrains Mono","Consolas","Menlo","Cascadia Mono",monospace'  # bundled first; system mono if it is missing
    css = f'''
.hud-layout{{position:absolute;inset:0;box-sizing:border-box;padding:0 6% calc(8 * var(--wt-u));display:flex;justify-content:center;align-items:flex-end;font-family:var(--wt-font);font-size:var(--wt-size)}}
.hud-g{{position:relative;max-width:86%;min-width:10em;padding:.2em 1.15em .22em;box-sizing:border-box;display:flex;flex-direction:column;align-items:stretch;--hud-accent:{p['accent']};--hud-dim:#6F757E}}
.hud-plate{{position:absolute;inset:0;background:linear-gradient(180deg,{_rgba(p['base'], .78)},{_rgba(p['base'], .7)})}}
.hud-plate::before{{content:"";position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(255,255,255,.045) 0 1px,transparent 1px 3px)}}
.hud-rule{{position:absolute;left:0;right:0;height:max(1px,.022em)}}
.hud-rule-t{{top:0}}.hud-rule-b{{bottom:0}}
.hud-rule i{{position:absolute;top:0;bottom:0;width:50%;background:rgba(255,255,255,.82)}}
.hud-rule i.l{{left:0;transform-origin:100% 50%}}.hud-rule i.r{{right:0;transform-origin:0% 50%}}
.hud-br{{position:absolute;width:.4em;height:.4em;border:0 solid rgba(255,255,255,.9)}}
.hud-br.t{{top:-.2em}}.hud-br.b{{bottom:-.2em}}.hud-br.l{{left:-.2em;border-left-width:max(2px,.04em)}}.hud-br.r{{right:-.2em;border-right-width:max(2px,.04em)}}
.hud-br.t{{border-top-width:max(2px,.04em)}}.hud-br.b{{border-bottom-width:max(2px,.04em)}}
.hud-head,.hud-foot{{position:relative;display:flex;align-items:center;gap:.6em;font-family:{mono};font-size:.23em;letter-spacing:.22em;color:#8A9099;white-space:nowrap;line-height:1}}
.hud-head{{padding:.9em 0 .7em;border-bottom:1px solid rgba(255,255,255,.12)}}
.hud-foot{{padding:.7em 0 .9em;border-top:1px solid rgba(255,255,255,.12)}}
.hud-head b,.hud-foot b{{font-weight:400;color:#D9DCE1}}
.hud-label{{flex:1}}
.hud-rec i{{display:inline-block;width:.7em;height:.7em;border-radius:50%;background:{p['accent']};margin-right:.6em;vertical-align:-.05em}}
.hud-ring{{width:1.3em;height:1.3em;border-radius:50%;border:.16em dotted rgba(255,255,255,.8);box-sizing:border-box}}
.hud-seg{{flex:1;display:flex;gap:.25em}}
.hud-seg i{{flex:1;height:.5em;background:rgba(255,255,255,.12)}}
.hud-seg i.on{{background:rgba(255,255,255,.85)}}
.hud-type{{position:relative;padding:.12em 0 .14em;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);line-height:1.32;letter-spacing:.05em;text-align:center;color:{p['ink']};text-shadow:0 .03em .12em rgba(0,0,0,.55)}}
.hud-type .wt-w{{display:inline-block;white-space:pre}}
.hud-type .wt-focus{{display:inline-block;padding:0 .1em;text-shadow:0 0 .25em {_rgba(p['accent'], .45)}}}
.hud-cur{{position:absolute;left:0;top:0;width:.42em;height:1.05em;background:rgba(255,255,255,.9);opacity:0}}
.hud-mk{{position:absolute;border:0 solid {p['accent']};opacity:0}}
.hud-tag{{position:absolute;font-family:{mono};font-size:.2em;letter-spacing:.2em;color:#0B0B0B;background:{p['accent']};padding:.15em .5em .1em;transform:translateY(-120%);opacity:0}}
'''
    return markup, css


_BUILDERS = {'vhs-signal': _vhs, 'hud-lock': _hud}


def compose(value):
    c = normalize(value)
    markup, css = _BUILDERS[c['template']](c)
    family = c['fontFamily']
    stack = ', '.join(f'"{name}"' for name in (family, *_EXTRA_FONTS[c['template']]))
    return dict(cueHtml=markup, cueCss=css, stageHtml='', stageCss='',
                appearance=dict(fontFamily=stack, fontSize=c['fontSize'],
                                fontWeight=900 if 'Heavy' in family else 500 if 'Source Han' in family else 400),
                palette=dict(primary=c['palette']['accent'], accent=c['palette']['accent'],
                             background=c['palette']['base'], text=c['palette']['ink']),
                motionSpec=dict(version=2, runtime='gsap', buildMs=0, resolveMs=0, tracks=[],
                                template=dict(id=c['template'], params=dict(seed=c['seed'], intensity=c['intensity']))))


def capability_text():
    rows = '\n'.join(f'- {name}：{_DESC[name]}' for name in _DESC)
    return f'''动态模板 {VERSION}（components.version=12）：手工设计并经用户认可的整套特效字幕，入场/阅读期/出场与故障效果都已编排好。优先使用。
components: {{version:12,template:模板ID,emphasis:[字幕原文里的重点字组],intensity:{'|'.join(INTENSITIES)},seed:0..999999,palette:{{ink:文字色,base:框底色,accent:框线与反白色}},fontFamily:打包字体名,fontSize:44..96}}。只有version和template必填；配色不写就是模板原本的设计，改色时保持克制，不要换成霓虹或蓝青色大底。
模板：
{rows}
三个候选里至少两个用动态模板；可以重复同一个模板，但要在 intensity、重点词或配色上明显不同。设计套件只在模板明显不合题材时作为第三个候选。'''
