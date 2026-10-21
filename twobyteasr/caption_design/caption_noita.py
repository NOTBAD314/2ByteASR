"""Original alchemical pixel captions; expanded once into the existing source contract.

No game assets, shaders, text clones, procedural runtime or second clock.
"""
import html
import math
import re

VERSION = 'noita-caption-1'
DIRECTIONS = ('tablet', 'scroll', 'reaction', 'warning')


def is_noita(prompt):
    return bool(re.search(r'(?<![a-z])noita(?![a-z])|诺伊塔|諾伊塔', str(prompt), re.I))


def normalize(value):
    allowed = {'version', 'direction', 'fontSize', 'fontFamily', 'emphasis', 'ink', 'paper', 'accent', 'edge', 'buildMs', 'resolveMs'}
    if not isinstance(value, dict) or value.get('version') != 8 or set(value) - allowed:
        raise ValueError('Noita组件需要version=8及已公布参数')
    c = dict(version=8, direction='reaction', fontSize=66, fontFamily='Cubic 11',
             emphasis=[], ink='#F4EBCB', paper='#211F1B', accent='#B8CF72', edge='#9D8551', buildMs=300, resolveMs=240)
    c.update(value)
    if c['direction'] not in DIRECTIONS:
        raise ValueError('Noita方向需要tablet/scroll/reaction/warning')
    for key, low, high in [('fontSize', 44, 88), ('buildMs', 150, 450), ('resolveMs', 120, 320)]:
        n = c[key]
        if type(n) not in (float, int) or not math.isfinite(n) or not low <= n <= high:
            raise ValueError('Noita参数超范围：' + key)
    from .web_theme_fonts import FONT_FILES
    if c['fontFamily'] not in FONT_FILES:
        raise ValueError('Noita字体必须已打包')
    for key in ('ink', 'paper', 'accent', 'edge'):
        if not isinstance(c[key], str) or not re.fullmatch('#[0-9a-fA-F]{6}', c[key]):
            raise ValueError('Noita颜色需要#RRGGBB')
    if not isinstance(c['emphasis'], list) or len(c['emphasis']) > 4 or any(not isinstance(t, str) or not 1 <= len(t) <= 24 or '|' in t for t in c['emphasis']):
        raise ValueError('Noita重点词需要最多4个短文本')
    return c


def _svg(content, box='0 0 32 40', cls=''):
    return f'<svg class="{cls}" viewBox="{box}" aria-hidden="true">{content}</svg>'


def compose(value):
    c = normalize(value)
    # Original grid drawing: chipped stopper, glass shoulder, sediment and meniscus.
    flask = _svg('''<path fill="#121711" d="M11 1h10v3h2v10h3v4h3v17h-3v3H6v-3H3V18h3v-4h5z"/>
<path fill="#92815A" d="M11 1h10v4H11z"/><path fill="#D1B875" d="M12 1h7v1h-7z"/>
<path fill="#7D9986" d="M11 5h3v11H8v5H6v12h3v2h14v-2h3V21h-2v-5h-6V5h3v9h3v4h3v17h-3v2H7v-2H4V18h3v-4h4z"/>
<path fill="#283C31" d="M14 6h4v12h5v5H9v-5h5z"/>
<g class="nt-liquid"><path fill="var(--nt-accent)" d="M8 24h5v-2h7v2h4v9H8z"/><path fill="#607344" d="M8 30h16v3H8z"/><path fill="#E4EAAF" d="M9 24h4v2H9zM17 23h3v1h-3z"/></g>
<path fill="#D0D9B2" d="M8 19h2v4H8zM8 27h1v4H8z"/><path fill="#594C31" d="M10 36h13v2H10z"/>''', cls='nt-flask')
    sigil = _svg('''<path fill="none" stroke="var(--nt-edge)" stroke-width="2" d="M16 5v4h6v5h5v12h-5v5H10v-5H5V14h5V9h6M5 20h22M16 9v22"/>
<path fill="var(--nt-accent)" d="M13 16h6v8h-6zM15 2h2v3h-2zM1 19h3v2H1zM28 19h3v2h-3z"/>''', cls='nt-sigil')
    # The repeat is geometry baked by the author, not animated noise or copied runes.
    runes = _svg(''.join(f'<path fill="none" stroke="#AD965A" stroke-width="1" d="M{x} 9V2h5v4h-5m2 0v5m9-9v8h5V6h-5"/>' for x in (2, 29, 56, 83)), '0 0 110 13', 'nt-runes')
    motes = ''.join(f'<i class="nt-mote nt-mote-{i}" aria-hidden="true"></i>' for i in range(6))
    markup = ('<div class="nt-layout"><div class="nt-body nt-' + c['direction'] + '">'
              '<div class="nt-read"><div class="nt-surface" aria-hidden="true"></div>'
              '<div class="nt-seam" aria-hidden="true"></div>'
              '<div class="nt-grain" aria-hidden="true"></div><div class="nt-chips" aria-hidden="true"></div>'
              '<div class="nt-script" aria-hidden="true">' + runes + '</div>'
              '<div class="nt-copy" data-semantic-text="true" data-emphasis="' + html.escape('|'.join(c['emphasis']), quote=True) + '">{{words}}</div></div>'
              '<div class="nt-reagent">' + flask + '</div><div class="nt-seal">' + sigil + '</div>'
              '<div class="nt-charge" aria-hidden="true"></div><div class="nt-dust">' + motes + '</div></div></div>')
    css = '.nt-body{--nt-ink:' + c['ink'] + ';--nt-paper:' + c['paper'] + ';--nt-accent:' + c['accent'] + ';--nt-edge:' + c['edge'] + '}\n'
    css += '''/* noita-caption-1: optional detail tiers never change the reading surface */
.nt-layout{position:absolute;left:7%;right:7%;bottom:10%;display:flex;justify-content:center;font-family:var(--wt-font);font-size:var(--wt-size)}
.nt-body{position:relative;max-width:100%;width:max-content;padding:0 .14em .1em;isolation:isolate}
.nt-read{position:relative;padding:.39em 1.13em .32em 1.22em;min-width:5.4em;box-sizing:border-box}
.nt-surface{position:absolute;inset:0;background:var(--nt-paper);clip-path:polygon(0 12px,8px 12px,8px 4px,24px 4px,24px 0,calc(100% - 16px) 0,calc(100% - 16px) 8px,100% 8px,100% calc(100% - 12px),calc(100% - 8px) calc(100% - 12px),calc(100% - 8px) 100%,12px 100%,12px calc(100% - 4px),0 calc(100% - 4px));box-shadow:inset 0 4px #807148,inset 0 8px #3F392A,inset 0 -6px #090C0B,inset 0 -10px #494233}
.nt-seam{position:absolute;inset:12px 12px 12px;border-top:2px solid #494733;border-bottom:2px solid #554E34;border-left:4px solid #0C100C;border-right:4px solid #0C100C}
.nt-seam:before,.nt-seam:after{content:"";position:absolute;width:.36em;height:4px;top:0;background:var(--nt-edge);box-shadow:0 6px #292B21,0 -6px #171A15}
.nt-seam:before{left:2px}.nt-seam:after{right:2px;top:auto;bottom:0}
.nt-grain{position:absolute;left:15%;right:12%;top:12px;height:4px;color:#73623F;box-shadow:11px 0 currentColor,80px 4px #393828,-25px 6px #504631;opacity:.5;background:repeating-linear-gradient(90deg,transparent 0 31px,#655639 31px 35px,transparent 35px 87px);background-size:127px 4px}
.nt-script{position:absolute;left:1.3em;top:7px;width:1.7em;height:.2em;color:var(--nt-edge);opacity:.72}
.nt-runes{display:block;width:100%;height:100%;fill:none;stroke:currentColor;stroke-width:1;shape-rendering:crispEdges}
.nt-copy{position:relative;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);line-height:1.22;letter-spacing:0;text-align:center;color:var(--nt-ink);-webkit-text-fill-color:var(--nt-ink);text-shadow:2px 0 #0A100C,-2px 0 #0A100C,0 2px #0A100C,0 -2px #0A100C,2px 4px #070B08;overflow-wrap:anywhere}
.nt-copy .wt-w{display:inline-block;white-space:pre}.nt-copy .wt-focus{display:inline;color:var(--nt-accent);-webkit-text-fill-color:var(--nt-accent)}
.nt-reagent{position:absolute;left:.16em;top:50%;width:.83em;height:1.05em;margin-top:-.54em}
.nt-flask,.nt-sigil{display:block;width:100%;height:100%;overflow:visible;shape-rendering:crispEdges}
.nt-seal{position:absolute;right:.19em;top:50%;width:.7em;height:.87em;margin-top:-.44em}
.nt-charge{position:absolute;left:1.38em;right:1.02em;bottom:7px;height:3px;background:var(--nt-accent);box-shadow:0 3px #4A5634;transform-origin:0% 50%}
.nt-dust{position:absolute;inset:0;pointer-events:none}
.nt-mote{position:absolute;width:4px;height:4px;background:var(--nt-accent);box-shadow:0 4px #526039;left:8%;top:5%}
.nt-mote-1{left:18%;top:-8%;background:#DCC17B}.nt-mote-2{left:36%;top:0}.nt-mote-3{left:76%;top:2%;background:#D99351}.nt-mote-4{left:89%;top:12%}.nt-mote-5{left:95%;top:70%;background:#DCB477}
.nt-tablet .nt-read{padding-top:.52em;padding-bottom:.43em}.nt-tablet .nt-surface{background:#292B26;box-shadow:inset 0 8px #676650,inset 0 14px #393D32,inset 0 -12px #0C100D,inset 8px 0 #414635}
.nt-tablet .nt-reagent{display:none}.nt-tablet .nt-script{width:2.8em}.nt-tablet .nt-seal{right:auto;left:.25em;width:.8em}
.nt-scroll .nt-read{padding:.37em .8em .34em}.nt-scroll .nt-surface{background:#A69469;box-shadow:inset 0 6px #D0BC86,inset 0 -8px #61503A,inset 8px 0 #574A36,inset -8px 0 #574A36}
.nt-scroll .nt-copy{color:#211E18;-webkit-text-fill-color:#211E18;text-shadow:0 2px #C1AD7C}.nt-scroll .nt-copy .wt-focus{color:#6B3024;-webkit-text-fill-color:#6B3024}
.nt-scroll .nt-reagent{left:-.35em;top:30%;width:.65em;transform:rotate(-12deg)}.nt-scroll .nt-seal{right:-.28em;top:72%;width:.57em;height:.66em;background:#513E2A}.nt-scroll .nt-charge{background:#664930}
.nt-warning .nt-surface{background:#251F19;box-shadow:inset 0 4px #855134,inset 0 -6px #100E0C,inset 8px 0 #654028}
.nt-warning .nt-read{padding-left:1.2em;padding-right:.55em}.nt-warning .nt-reagent{display:none}.nt-warning .nt-seal{left:.24em;right:auto;color:#D69A58}.nt-warning .nt-script{left:auto;right:.65em;width:1.4em}.nt-warning .nt-charge{background:#CE8B4C}
.nt-reaction .nt-read{padding-top:.47em;padding-bottom:.34em}
.nt-reaction .nt-surface{clip-path:polygon(0 22px,8px 22px,8px 10px,24px 10px,24px 2px,10% 2px,10% 6px,28% 6px,28% 0,63% 0,63% 4px,calc(100% - 24px) 4px,calc(100% - 24px) 14px,100% 14px,100% calc(100% - 16px),calc(100% - 10px) calc(100% - 16px),calc(100% - 10px) calc(100% - 6px),84% calc(100% - 6px),84% 100%,68% 100%,68% calc(100% - 4px),22% calc(100% - 4px),22% 100%,14px 100%,14px calc(100% - 10px),0 calc(100% - 10px));box-shadow:inset 0 4px #766242,inset 0 9px #423824,inset 0 -8px #0D100C,inset 0 -12px #4C452F}
.nt-reaction .nt-seam{border-left:0;border-right:0;border-top:0;inset:16px 22px 16px}
.nt-reaction .nt-script{left:1.34em;top:12px;width:2.1em;height:.23em;color:#B19A63;opacity:1}
.nt-reaction .nt-reagent{left:.12em;width:.92em;height:1.18em;margin-top:-.57em}
.nt-reaction .nt-seal{right:.08em;width:.83em;height:1.02em;margin-top:-.49em;background:#171C15;box-shadow:4px 0 #494632,-4px 0 #494632,0 4px #121710,0 -4px #6A633E}
.nt-chips{position:absolute;left:.26em;right:.22em;top:8px;height:4px;background:repeating-linear-gradient(90deg,#635235 0 9px,transparent 9px 41px,#877342 41px 46px,transparent 46px 93px);opacity:.8}
.nt-reaction .nt-charge{left:1.34em;right:1.25em;bottom:12px;height:3px;box-shadow:none}
'''
    tracks = []
    def move(selector, phase, start, end, before, after, **extra):
        tracks.append(dict(selector=selector, phase=phase, start=start, end=end, ease='steps(5)', **{'from':before, 'to':after}, **extra))
    # The substrate is summoned from its top inscription, never expanded centrally.
    move('.nt-read', 'build', 0, .68, dict(clipPath='inset(0% 0% 100% 0%)', opacity=0), dict(clipPath='inset(0% 0% 0% 0%)', opacity=1))
    move('.nt-copy', 'build', .12, .72, dict(opacity=0), dict(opacity=1))
    move('.nt-reagent', 'build', 0, .6, dict(y=-6, opacity=0), dict(y=0, opacity=1))
    move('.nt-seal', 'build', .08, .8, dict(opacity=0, scaleX=.8, scaleY=.8), dict(opacity=1, scaleX=1, scaleY=1))
    move('.nt-charge', 'build', .05, .9, dict(scaleX=0, opacity=0), dict(scaleX=1, opacity=.55))
    move('.nt-script', 'breathe', 0, 1, dict(opacity=.48), dict(opacity=.85), durationMs=1700, sustain=True, yoyo=True)
    move('.nt-liquid', 'breathe', .08, .95, dict(y=0), dict(y=-1), durationMs=2100, sustain=True, yoyo=True)
    for i in range(3):
        move(f'.nt-mote-{i}', 'build', .05+i*.09, .84+i*.05, dict(y=8, opacity=0), dict(y=-8-i*3, opacity=.75))
        move(f'.nt-mote-{i}', 'breathe', 0, .15, dict(opacity=.75), dict(opacity=0), durationMs=450)
    for i in range(3, 6):
        move(f'.nt-mote-{i}', 'breathe', (i-3)*.14, 1, dict(y=4, opacity=0), dict(y=-10, opacity=.6), durationMs=1900+i*120, sustain=True, yoyo=True, minCueMs=2200)
    move('.nt-read', 'resolve', 0, .72, dict(clipPath='inset(0% 0% 0% 0%)', opacity=1), dict(clipPath='inset(100% 0% 0% 0%)', opacity=0))
    move('.nt-reagent', 'resolve', .12, .65, dict(y=0, opacity=1), dict(y=5, opacity=0))
    move('.nt-seal', 'resolve', 0, .62, dict(opacity=1, scaleX=1, scaleY=1), dict(opacity=0, scaleX=.5, scaleY=.5))
    move('.nt-charge', 'resolve', 0, .7, dict(scaleX=1, opacity=.55), dict(scaleX=0, opacity=0))
    move('.nt-dust', 'resolve', 0, .68, dict(clipPath='inset(0% 0% 0% 0%)'), dict(clipPath='inset(100% 0% 0% 0%)'))
    return dict(cueHtml=markup, cueCss=css, stageHtml='', stageCss='',
                appearance=dict(fontFamily=c['fontFamily'], fontSize=c['fontSize'], fontWeight=400 if c['fontFamily']=='Cubic 11' else 900),
                palette=dict(primary=c['accent'], text=c['ink']),
                motionSpec=dict(version=2, runtime='gsap', buildMs=c['buildMs'], resolveMs=c['resolveMs'], tracks=tracks))


def capability_text():
    return '''Noita原创像素炼金组件version:8；沿用HTML+MotionSpec2，非官方资源。参数direction=tablet/scroll/reaction/warning，fontFamily默认Cubic 11（已打包），fontSize=44..88默认66，emphasis最多4真实短词；ink/paper/accent/edge=#RRGGBB；buildMs=150..450默认300，resolveMs=120..320默认240。示例{"version":8,"direction":"reaction","fontSize":66,"emphasis":["法杖"]}。独立一层实心正文、阶梯暗底、原创药瓶沉淀/刻符/火星；召唤点亮→正文稳定与局部低频反应→封印回收。reaction日常长短句首选，tablet厚石碑、scroll焦纸、warning危险铭牌有不同结构/材料。可以改颜色/字/时间/重点，编译源码可继续编辑，不导入游戏贴图。不要为像素感加SVG噪声/玻璃滤镜或复制多套正文。'''
