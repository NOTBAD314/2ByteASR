"""Ice v7: one material volume partitioned into twelve physical pieces.

Original procedural frost artwork; no stock texture, renderer or clock. Each
piece carries the same volume, glyph faces, shell and fractures in the same
coordinates. The prior v6 source is preserved in caption_ice_legacy.py.
"""
import html
from urllib.parse import quote

OPTIONS = {'geometry': ('shelf', 'facet'), 'frost': ('rime', 'snow'),
           'lettering': ('carved', 'clear'), 'motion': ('crystallize', 'lock'),
           'wiggle': ('weak', 'off', 'medium', 'strong')}

# A complete tessellation. Subpixel overlaps prevent antialiased clip seams.
PIECES = (
    '0% 0%,18% 0%,16.1% 31%,19.1% 54%,0% 47%',
    '17.9% 0%,34% 0%,36.1% 28%,32.1% 58%,19% 54%,16% 31%',
    '33.9% 0%,51% 0%,48% 26%,51.1% 49%,32% 58%,36% 28%',
    '50.9% 0%,69% 0%,65% 32%,69.1% 58%,51% 49%,47.9% 26%',
    '68.9% 0%,84% 0%,87.1% 23%,82.1% 48%,69% 58%,64.9% 32%',
    '83.9% 0%,100% 0%,100% 55%,82% 48%,87% 23%',
    '0% 46.9%,19.1% 53.9%,15.1% 78%,18% 100%,0% 100%',
    '19% 53.9%,32.1% 57.9%,36% 83%,33% 100%,17.9% 100%,15% 78%',
    '32% 57.9%,51.1% 48.9%,47% 76%,51% 100%,32.9% 100%,35.9% 83%',
    '51% 48.9%,69.1% 57.9%,65% 80%,68% 100%,50.9% 100%,46.9% 76%',
    '69% 57.9%,82.1% 47.9%,86% 78%,83% 100%,67.9% 100%,64.9% 80%',
    '82% 47.9%,100% 54.9%,100% 100%,82.9% 100%,85.9% 78%',
)


def _frost_texture():
    """One static original frost field, stretched once across the whole slab."""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="180" viewBox="0 0 1000 180" preserveAspectRatio="none">
<defs><filter id="n"><feTurbulence type="fractalNoise" baseFrequency=".026 .16" numOctaves="3" seed="17"/></filter></defs><rect width="1000" height="180" fill="#ffffff" filter="url(#n)" opacity=".19"/>
<g fill="#f6ffff"><path d="M0 0H282L258 13 218 20 206 31 151 25 112 41 74 26 48 38 0 29Z" opacity=".18"/><path d="M560 0H1000V22L954 17 922 40 859 26 830 47 787 19 713 38 686 21 617 34Z" opacity=".16"/><path d="M0 149L59 140 105 156 163 138 186 156 250 142 302 167 374 151 401 180H0Z" opacity=".12"/><path d="M619 180L651 151 681 163 724 140 784 155 826 131 887 145 938 132 1000 146V180Z" opacity=".16"/>
<path d="M105 71L122 50 159 45 191 52 212 77 184 92 165 78 134 93Z" opacity=".19"/><path d="M424 81L448 53 481 51 521 73 505 102 466 90 433 108Z" opacity=".27"/><path d="M731 89L751 62 788 55 821 76 797 107 754 116Z" opacity=".16"/>
<ellipse cx="283" cy="103" rx="5" ry="1.8" opacity=".53"/><ellipse cx="526" cy="121" rx="3" ry="1.2" opacity=".55"/><ellipse cx="897" cy="83" rx="4" ry="1.6" opacity=".47"/><ellipse cx="350" cy="64" rx="2" ry="1" opacity=".7"/></g>
<g fill="none" stroke="#f3ffff" stroke-width=".8" stroke-opacity=".5"><path d="M24 63L72 44 104 54 147 31M49 52L57 68M104 54L117 74M219 164L244 137 280 130 303 105M244 137L226 112M280 130L320 145M405 32L430 44 446 65 486 70M430 44L463 30M598 171L623 145 639 119 669 105M623 145L599 127M845 17L863 39 899 47 918 69M863 39L844 61M966 116L937 121 907 147M937 121L929 99"/><path d="M76 32L121 16M154 38L199 22M328 151L364 134M434 89L470 72M472 105L508 88M686 34L729 15M787 152L816 138M902 32L956 17" stroke-width="2.3" stroke-opacity=".3"/></g></svg>'''
    return 'url("data:image/svg+xml,' + quote(svg.replace('\n', ''), safe='') + '")'


def compose(value):
    from .caption_components import normalize, COLORS
    extra = set(value) - {'version', *OPTIONS, *COLORS, 'fontSize', 'fontFamily',
                          'emphasis', 'buildMs', 'resolveMs', 'wiggleSeed'}
    if extra:
        raise ValueError('不支持的冰材质参数：' + ','.join(sorted(extra)))
    axes = {key: value.get(key, choices[0]) for key, choices in OPTIONS.items()}
    for key, choices in OPTIONS.items():
        if axes[key] not in choices:
            raise ValueError('不支持冰材质 ' + key + ': ' + str(axes[key]))
    seed = value.get('wiggleSeed', 1703)
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('wiggleSeed需要0..2147483647整数')
    params = dict(version=1, ink='#E9F6F7', paper='#496B78', accent='#C8EAED',
                  edge='#183D4C', fontSize=64, buildMs=560, resolveMs=360,
                  fontFamily='Source Han Sans SC Heavy')
    params.update({k: v for k, v in value.items() if k not in OPTIONS and k not in ('version', 'wiggleSeed')})
    c = normalize(params)
    emphasis = html.escape('|'.join(c['emphasis']), quote=True)
    # The semantic surface is the union of all twelve visible glyph slices.
    # Marking just slice zero would misidentify a short centred caption as
    # invisible, because its strokes need not intersect the leftmost slice.
    parts = ['<div class="ice-layout"><div class="ice-wiggle"><div class="ice-shiver"><div class="ice-body" data-semantic-text="true">',
             '<svg class="ice-defs" aria-hidden="true"><defs><filter id="ice-condensation"><feTurbulence type="fractalNoise" baseFrequency=".036 .11" numOctaves="3" seed="29"/><feColorMatrix type="matrix" values="0 0 0 0 .91 0 0 0 0 .97 0 0 0 0 .98 0 0 0 2.7 -.84"/></filter><filter id="ice-glyph-frost"><feTurbulence type="fractalNoise" baseFrequency=".036 .11" numOctaves="3" seed="29"/><feColorMatrix type="matrix" values="0 0 0 0 .94 0 0 0 0 .98 0 0 0 0 .99 0 0 0 2.0 -.83"/><feComposite in2="SourceGraphic" operator="in"/><feBlend in2="SourceGraphic" mode="screen"/></filter></defs></svg>',
             '<div class="ice-measure" aria-hidden="true">{{text}}</div>']
    for i in range(len(PIECES)):
        parts.append(f'<div class="ice-piece ice-piece-{i}">'
                     '<div class="ice-depth" aria-hidden="true"></div>'
                     '<div class="ice-volume" aria-hidden="true"></div>'
                     '<div class="ice-interior" aria-hidden="true"></div>'
                     '<div class="ice-type ice-shadow" aria-hidden="true">{{text}}</div>'
                     '<div class="ice-type ice-bevel" aria-hidden="true">{{text}}</div>'
                     f'<div class="ice-type ice-copy" data-emphasis="{emphasis}">' + '{{text}}</div>'
                     '<div class="ice-frost" aria-hidden="true"></div><div class="ice-shell" aria-hidden="true"></div>'
                     '<svg class="ice-cracks" viewBox="0 0 1000 180" preserveAspectRatio="none" aria-hidden="true">'
                     '<path d="M180 4L160 56 190 97 150 140 180 174M340 4L360 50 320 104 360 149 330 176M510 4L480 47 510 88 470 137 510 176M690 4L650 58 690 104 650 144 680 176M840 4L870 41 820 86 860 140 830 176M12 85L190 97 320 104 510 88 690 104 820 86 987 99"/></svg>'
                     '<div class="ice-rim" aria-hidden="true"></div>'
                     '<div class="ice-reflection" aria-hidden="true"></div></div>')
    parts.append('</div></div></div></div>')
    markup = ''.join(parts)
    texture = _frost_texture()
    css = '''
.ice-layout{position:absolute;left:50%;bottom:11%;transform:translateX(-50%);width:max-content;max-width:86%;font:900 var(--wt-size)/1.22 var(--wt-font);}
.ice-wiggle,.ice-shiver,.ice-body{position:relative;max-width:100%;transform-origin:50% 62%;}
.ice-body{isolation:isolate;--ice-shape:polygon(1% 18%,3% 5%,16% 2%,29% 5%,49% 1%,65% 4%,81% 1.5%,97% 5%,99% 21%,98.8% 77%,96% 91%,80% 94%,63% 90%,48% 95%,28% 92%,4% 95%,.7% 77%);}.ice-defs{position:absolute;width:0;height:0;overflow:hidden;}
.ice-measure,.ice-type{box-sizing:border-box;padding:.43em .66em .48em;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:900;line-height:1.22;letter-spacing:.015em;white-space:pre-wrap;overflow-wrap:anywhere;text-align:center;}
.ice-measure{visibility:hidden;min-width:3.5em;}
.ice-piece{position:absolute;inset:0;isolation:isolate;transform-origin:50% 55%;}
.ice-depth,.ice-volume,.ice-interior,.ice-frost,.ice-shell,.ice-rim{position:absolute;inset:0;clip-path:var(--ice-shape);pointer-events:none;}
.ice-depth{inset:.065em -.01em -.02em;background:linear-gradient(174deg,#e0f2ef 0%,#5e8d9a 14%,var(--ice-edge) 25%,#102d3b 82%,#84b0b7 94%,#224751 100%);}
.ice-volume{background:radial-gradient(ellipse at 23% 21%,#b9dce0bb,transparent 24%),radial-gradient(ellipse at 73% 73%,#8daebc99,transparent 31%),radial-gradient(ellipse at 46% 71%,#c6dddd66,transparent 18%),linear-gradient(169deg,#b7d4d9e8 0%,var(--ice-paper) 22%,var(--ice-edge) 62%,#638795 83%,#91b4bb 95%);box-shadow:inset 0 .07em .08em #f4ffffa2,inset .06em 0 .08em #d3ede64b,inset 0 -.075em .035em #172e3daa;}
.ice-interior{opacity:.33;background-size:100% 100%;background-repeat:no-repeat;mix-blend-mode:screen;}
.ice-type{position:absolute;inset:0;background-origin:border-box;background-size:100% 100%;background-repeat:no-repeat;}
.ice-type [data-caption-text]{background:none;-webkit-text-fill-color:inherit;color:inherit;-webkit-text-stroke:inherit;text-shadow:inherit;}
.ice-shadow{color:#284955;-webkit-text-fill-color:#284955;-webkit-text-stroke:.012em #24404b;transform:translate(-.012em,-.013em);text-shadow:0 0 .021em #12324144;}
.ice-bevel{color:#b1cdce;-webkit-text-fill-color:#b1cdce;-webkit-text-stroke:.007em #a1c4c9;transform:translate(.007em,.012em);text-shadow:none;}
.ice-copy{color:transparent;-webkit-text-fill-color:transparent;-webkit-text-stroke:0;text-shadow:none;background-clip:text;-webkit-background-clip:text;background-blend-mode:normal;filter:url(#ice-glyph-frost);}
.ice-copy [data-caption-text]{text-shadow:none;-webkit-text-stroke:0;-webkit-text-fill-color:transparent;background:none;color:transparent;}
.ice-copy .wt-focus{text-shadow:none;-webkit-text-stroke:.009em var(--ice-accent);}
.ice-frost{background:#efffff;filter:url(#ice-condensation);opacity:.7;mask-image:radial-gradient(ellipse 17% 61% at 18% 18%,#000 10%,transparent 91%),radial-gradient(ellipse 12% 63% at 49% 76%,#000 8%,transparent 90%),radial-gradient(ellipse 14% 64% at 80% 26%,#000 8%,transparent 91%),linear-gradient(#000 0%,transparent 26%,transparent 87%,#000 100%);}
.ice-shell{opacity:.64;background-size:100% 100%;background-repeat:no-repeat;mix-blend-mode:screen;mask-image:radial-gradient(ellipse 14% 77% at 18% 16%,#000 8%,transparent 89%),radial-gradient(ellipse 12% 93% at 48% 75%,#000 9%,transparent 94%),radial-gradient(ellipse 16% 83% at 82% 21%,#000 10%,transparent 92%),linear-gradient(#000 0%,transparent 24%,transparent 80%,#000 100%);}
.ice-cracks{position:absolute;inset:0;width:100%;height:100%;clip-path:var(--ice-shape);fill:none;stroke:#e3f6f4;stroke-width:.5;stroke-opacity:.46;opacity:.34;}
.ice-rim{background:linear-gradient(177deg,#f7ffffdc 0%,#dcf0ef88 7%,transparent 8%,transparent 89%,var(--ice-accent) 90%,#5e8e9c 98%);mask-image:linear-gradient(#000 0%,#000 12%,transparent 13%,transparent 83%,#000 84%),linear-gradient(90deg,#000 0%,transparent 3%,transparent 97%,#000 100%);}
.ice-reflection{position:absolute;left:77.5%;top:9%;width:.3em;height:.035em;background:#ecffff;transform:rotate(-18deg);opacity:.3;box-shadow:0 0 .055em #e6ffff77;}
'''
    css += '.ice-body{--ice-ink:' + c['ink'] + ';--ice-paper:' + c['paper'] + ';--ice-accent:' + c['accent'] + ';--ice-edge:' + c['edge'] + ';}'
    css += '.ice-interior{background-image:' + texture + ';}'
    css += '.ice-copy{background-image:' + texture + ',radial-gradient(ellipse at 17% 19%,#fbffff 0%,transparent 18%),radial-gradient(ellipse at 50% 91%,#effbff 0%,transparent 22%),radial-gradient(ellipse at 80% 23%,#d7eff0 0%,transparent 25%),radial-gradient(ellipse at 33% 61%,#527e91 0%,transparent 22%),radial-gradient(ellipse at 72% 64%,#688f9c 0%,transparent 14%),linear-gradient(167deg,#e9f7f7 2%,var(--ice-ink) 26%,#78a2b1 48%,#b0d2d9 60%,#83aebb 76%,#ddedeb 92%);}'
    css += '.ice-shell{background-image:' + texture + ',radial-gradient(ellipse at 47% 54%,#e1f5f65c,transparent 18%),radial-gradient(ellipse at 17% 24%,#d3edf455,transparent 23%);}'
    for i, polygon in enumerate(PIECES):
        css += f'.ice-piece-{i}' + '{clip-path:polygon(' + polygon + ');}'
    if axes['geometry'] == 'facet':
        css += '.ice-body{--ice-shape:polygon(0% 22%,5% 2%,32% 5%,61% 1%,93% 4%,100% 25%,98% 81%,93% 94%,60% 91%,29% 97%,4% 94%,0% 74%);}'
    if axes['frost'] == 'snow':
        css += '.ice-interior{opacity:.45;}.ice-shell{opacity:.84;}.ice-rim{box-shadow:inset 0 .14em .05em #effafaaf;}'
    if axes['lettering'] == 'clear':
        css += '.ice-copy{background-blend-mode:soft-light,normal;}.ice-bevel{-webkit-text-stroke:.01em #cbe6e9;}'
    tracks = []

    def move(selector, phase, start, end, a, b, ease='power2.out', **kw):
        tracks.append(dict(selector=selector, phase=phase, start=start, end=end,
                           ease=ease, **{'from': a, 'to': b}, **kw))

    move('.ice-body', 'build', 0, .025, dict(opacity=0), dict(opacity=1), 'none')
    move('.ice-body', 'resolve', .97, 1, dict(opacity=1), dict(opacity=0), 'none')
    order = (3, 0, 6, 2, 8, 5, 9, 1, 7, 4, 11, 10)
    for i in range(len(PIECES)):
        sign = -1 if i % 3 == 0 else 1
        delay = order[i] * .014
        distance = 1.35 if axes['motion'] == 'lock' else 1
        # Short cues retain a formed slab and local frost visibility changes;
        # translation/rotation are omitted, not sped into the 160/100ms window.
        move(f'.ice-piece-{i}', 'build', delay, .38 + delay,
             dict(x=sign * (3 + i % 4) * distance, y=(-5 if i < 6 else 6) * distance,
                  rotation=sign * .65),
             dict(x=0, y=0, rotation=0), 'power3.out', minCueMs=1900)
        move(f'.ice-piece-{i}', 'build', delay, .38 + delay,
             dict(opacity=0), dict(opacity=1), 'power3.out')
        # Complete the physical break before the last encoded frame as well
        # as the mathematical cue boundary.  Geometry arrives first; opacity
        # follows, leaving the second half of resolve genuinely transparent.
        move(f'.ice-piece-{i}', 'resolve', .02 + (i % 4) * .015, .40 + (i % 3) * .02,
             dict(x=0, y=0, rotation=0),
             dict(x=sign * (9 + i % 5 * 3), y=9 + i % 6 * 4,
                  rotation=sign * (2 + i % 4)), 'power2.in', minCueMs=1900)
        move(f'.ice-piece-{i}', 'resolve', .10 + (i % 4) * .015, .46 + (i % 3) * .02,
             dict(opacity=1), dict(opacity=0), 'power2.in')
    move('.ice-shell', 'build', .16, .96, dict(opacity=.18), dict(opacity=.84 if axes['frost'] == 'snow' else .64), minCueMs=1900)
    move('.ice-cracks', 'resolve', 0, .26, dict(opacity=.34), dict(opacity=.84), 'power2.in')
    move('.ice-reflection', 'breathe', .33, .42, dict(opacity=.15), dict(opacity=.65), 'sine.inOut', repeat=1, yoyo=True, minCueMs=2600)
    strength = {'off': 0, 'weak': .6, 'medium': 1, 'strong': 1.6}[axes['wiggle']]
    zero = dict(x=0, y=0, rotation=0)
    move('.ice-wiggle', 'breathe', 0, 1, zero, zero, 'none',
         wiggle=dict(amplitudeX=1, amplitudeY=.7, rotation=.1, frequency=2.4,
                     seed=seed, intensity=strength, fadeInMs=180, fadeOutMs=180))
    move('.ice-shiver', 'breathe', .56, .67, zero, zero, 'none', durationMs=180,
         minCueMs=2600, wiggle=dict(amplitudeX=1.7, amplitudeY=.85, rotation=.12,
                                  frequency=17, seed=(seed + 89) % 2147483648,
                                  intensity=strength, fadeInMs=35, fadeOutMs=100))
    return dict(cueHtml=markup, cueCss=css, stageHtml='', stageCss='',
                appearance=dict(fontFamily=c['fontFamily'], fontSize=c['fontSize'],
                                fontWeight=900 if 'Heavy' in c['fontFamily'] else 500),
                palette=dict(primary=c['accent'], text=c['ink']),
                motionSpec=dict(version=2, runtime='gsap', buildMs=c['buildMs'],
                                resolveMs=c['resolveMs'], tracks=tracks))


def capability_text():
    return '''冰封组件 version:7：PARAMETERS.components；HTML/CSS/STAGE_CSS留空，宿主一次展开可编辑HTML/SVG/CSS/MotionSpec，同源用于采用/改字/保存重开/导出。v6仅旧稿兼容。
components:{version:7,geometry:shelf|facet,frost:rime|snow,lettering:carved|clear,motion:crystallize|lock,wiggle:off|weak|medium|strong,wiggleSeed:0..2147483647,fontFamily:打包字体,fontSize:40..100,ink/paper/accent/edge:#RRGGBB,emphasis:[真实重点字组],buildMs:180..650,resolveMs:120..400}。
同空间12片包含厚冰、独立后置字影/倒角、非重复冰霜纹理填字、跨字框的局部前壳与已有裂缝；入场短距刚性归位，阅读低强度整组wiggle/一次短冷颤/局部反射，退场沿相同片组连字与壳一起脱离，无中心展开、拉伸或通栏扫光。短cue减少壳层结晶与冷颤，不借邻句时间；<=700ms直接阅读态。wiggle是2Byte自有MotionSpec扩展，不是HyperFrames API。参数控制实际承载文字的独立wrapper，不覆盖宿主定位；噪声只按cueTime+seed采样，随机seek可复现。
例：{version:7,geometry:"facet",frost:"rime",lettering:"carved",motion:"crystallize",wiggle:"weak",wiggleSeed:1703,fontSize:64}。这些轴独立组合，仍可自创安全HTML/CSS/MotionSpec并自由组合入场/阅读/强调/退场；组件不是所有主题的固定模板。内部冰层合成不等于未知后方游戏视频折射。'''
