"""Version 2 composable surfaces. Static source + one host MotionSpec clock.

Geometry, material, edge, lettering and choreography are independent axes;
these expand to ordinary authored source and remain editable after expansion.
"""
import html

OPTIONS = {'geometry': ('inset', 'chamfer', 'capsule'),
           'surface': ('print', 'duotone', 'glass'),
           'border': ('registration', 'rails', 'prism'),
           'lettering': ('intaglio', 'offset', 'spectral'),
           'motion': ('stamp', 'relay', 'refract')}


def compose(value):
    from .caption_components import normalize, COLORS
    extra = set(value) - {'version', *OPTIONS, *COLORS, 'fontSize', 'fontFamily', 'emphasis', 'buildMs', 'resolveMs'}
    if extra:
        raise ValueError('不支持的组件参数：' + ','.join(sorted(extra)))
    axes = {}
    for key, choices in OPTIONS.items():
        axes[key] = value.get(key, choices[0])
        if axes[key] not in choices:
            raise ValueError('不支持组件 ' + key + ': ' + str(axes[key]))
    base = dict(version=1, ink='#192B29', paper='#F2E5C7', accent='#B85740', edge='#31554A',
                fontSize=70, buildMs=600, resolveMs=360)
    base.update({k:v for k,v in value.items() if k not in OPTIONS and k != 'version'})
    c = normalize(base)
    markup = ('<div class="cap-layout"><div class="cap-body">'
        '<div class="cap-registration" aria-hidden="true"></div>'
        '<div class="cap-surface" aria-hidden="true"></div>'
        '<div class="cap-pattern" aria-hidden="true"></div>'
        '<div class="cap-top" aria-hidden="true"></div><div class="cap-bottom" aria-hidden="true"></div>'
        '<div class="cap-edge" aria-hidden="true"></div><div class="cap-light" aria-hidden="true"></div>'
        '<div class="cap-type" data-semantic-text="true" data-emphasis="'
        + html.escape('|'.join(c['emphasis']), quote=True) + '">{{words}}</div></div></div>')
    css = '.cap-body{' + ''.join('--cap-'+k+':'+c[k]+';' for k in COLORS) + '}\n' + '''
.cap-layout{position:absolute;left:6%;right:6%;bottom:10%;display:flex;justify-content:center;font-family:var(--wt-font);font-size:var(--wt-size)}
.cap-body{position:relative;width:max-content;max-width:96%;padding:.30em .68em .34em;box-sizing:border-box}
.cap-surface,.cap-registration,.cap-edge{position:absolute;inset:0;border-radius:.10em}
.cap-registration{background:var(--cap-accent);box-shadow:0 .07em .12em #00000050}
.cap-surface{background:var(--cap-paper);box-shadow:inset 0 .025em 0 #FFFFFF99,inset 0 -.04em 0 #00000033}
.cap-pattern{position:absolute;left:.16em;top:.22em;bottom:.22em;width:.23em;opacity:.7;background:repeating-conic-gradient(var(--cap-edge) 0% 25%,transparent 0% 50%) 0 0/.18em .18em}
.cap-edge{border:.035em solid var(--cap-edge);box-shadow:inset 0 0 0 .045em var(--cap-paper),inset 0 0 0 .062em var(--cap-edge)}
.cap-top,.cap-bottom{position:absolute;left:.30em;right:.30em;height:.045em;background:var(--cap-edge);transform-origin:0% 50%}
.cap-top{top:.10em}.cap-bottom{bottom:.10em;transform-origin:100% 50%}
.cap-light{position:absolute;inset:.075em;border-radius:.07em;pointer-events:none;background:linear-gradient(115deg,transparent 30%,#FFFFFF70 45%,transparent 60%);background-size:300% 100%;background-position-x:100%;opacity:0}
.cap-type{position:relative;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);line-height:1.36;letter-spacing:.012em;text-align:center;color:var(--cap-ink)}
.cap-type .wt-w{display:inline-block;white-space:pre}
.cap-type .wt-focus{display:inline-block;max-width:100%;vertical-align:baseline;color:var(--cap-accent);border-bottom:.045em solid var(--cap-accent)}
'''
    css += {'inset':'', 'chamfer': '''
.cap-body{padding:.26em .70em .30em}.cap-surface,.cap-registration{border-radius:0;clip-path:polygon(0% 16%,2% 0%,100% 0%,100% 84%,98% 100%,0% 100%)}
.cap-edge{border-radius:0;border-left-width:.09em;border-right-width:.09em;border-top:0;border-bottom:0;inset:.18em 0;box-shadow:none}
''', 'capsule': '''
.cap-body{padding:.30em .78em .34em}.cap-surface,.cap-registration,.cap-edge{border-radius:.38em .12em .38em .12em}
.cap-pattern{left:.26em;top:.4em;bottom:.4em}
'''}[axes['geometry']]
    css += {'print': '''
.cap-surface{background:radial-gradient(ellipse at 20% 0%,#FFFFFF77,transparent 55%),repeating-linear-gradient(7deg,#1C392509 0 .014em,transparent .014em .065em),var(--cap-paper)}
.cap-registration{inset:.05em -.025em -.045em .025em}
''', 'duotone': '''
.cap-surface{background:linear-gradient(108deg,#FFFFFF15 0% 28%,transparent 28% 73%,#00000029 73%),linear-gradient(180deg,#FFFFFF15,transparent 45%,#00000033),var(--cap-paper)}
.cap-pattern{width:.09em;background:var(--cap-accent);opacity:1}
''', 'glass': '''
.cap-surface{background:linear-gradient(115deg,#FFFFFF22,transparent 33%,#8DE6FF18 55%,#FFFFFF30),linear-gradient(180deg,#152B3BCC,#10222FEB);box-shadow:inset 0 .03em .08em #FFFFFF55,inset 0 -.045em .09em #040F28AA}
.cap-registration{background:linear-gradient(105deg,var(--cap-accent),#CB8CFF,var(--cap-edge));opacity:.7}
.cap-pattern{width:.035em;background:#E1FCFF;opacity:.8}
'''}[axes['surface']]
    css += {'registration':'', 'rails': '''
.cap-top,.cap-bottom{left:-.13em;right:-.13em;height:.08em;box-shadow:0 .025em 0 #FFFFFF66}
.cap-top{top:-.035em;background:var(--cap-accent)}.cap-bottom{bottom:-.035em;background:var(--cap-edge)}
.cap-edge{border-color:var(--cap-edge);box-shadow:inset .025em 0 0 #FFFFFF80,inset -.025em 0 0 #FFFFFF80}
''', 'prism': '''
.cap-edge{border:.018em solid #DFF7FFAA;box-shadow:-.025em -.025em 0 var(--cap-accent),.03em .03em 0 var(--cap-edge),inset 0 .035em .07em #FFFFFF30}
.cap-top,.cap-bottom{height:.025em;left:.40em;right:.40em;background:linear-gradient(90deg,transparent,var(--cap-accent),#FFFFFFDD,var(--cap-edge),transparent)}
'''}[axes['border']]
    css += {'intaglio': '''
.cap-type .wt-w{-webkit-text-stroke:.008em var(--cap-ink);text-shadow:.012em .024em 0 #FFFFFFB0,-.009em -.009em 0 #00000044}
.cap-type .wt-focus .wt-w{-webkit-text-stroke:.008em var(--cap-accent);text-shadow:.018em .018em 0 #FFFFFFAA}
''', 'offset': '''
.cap-type .wt-w{-webkit-text-stroke:.009em #0E1A29;text-shadow:.018em .018em 0 #0E1A29,.037em .044em 0 var(--cap-edge)}
.cap-type .wt-focus{color:var(--cap-ink);border-color:var(--cap-accent)}
.cap-type .wt-focus .wt-w{text-shadow:.024em .035em 0 var(--cap-accent)}
''', 'spectral': '''
.cap-type .wt-w{background:linear-gradient(170deg,#FFFFFF 20%,var(--cap-ink) 55%,#ACD8ED 72%,#FFFFFF 95%);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;filter:drop-shadow(.02em .025em 0 #021C3D);text-shadow:none}
.cap-type .wt-focus{border-color:var(--cap-accent)}.cap-type .wt-focus .wt-w{background-image:linear-gradient(165deg,#FFFFFF,var(--cap-accent) 70%)}
'''}[axes['lettering']]
    tracks = []
    def move(sel,phase,start,end,before,after,ease='power2.out',**kw):
        tracks.append(dict(selector=sel,phase=phase,start=start,end=end,ease=ease,**{'from':before,'to':after},**kw))
    def enter(sel,start,end,before,after,**kw): move(sel,'build',start,end,before,after,**kw)
    def leave(sel,start,end,before,after,**kw): move(sel,'resolve',start,end,before,after,'power2.in',**kw)
    if axes['motion'] == 'stamp':
        enter('.cap-registration',0,.60,dict(x=-14,y=7,opacity=0),dict(x=0,y=0,opacity=1))
        enter('.cap-surface',.06,.66,dict(x=10,y=-5,opacity=0),dict(x=0,y=0,opacity=1))
        enter('.cap-edge',.10,.78,dict(scaleX=1.025,scaleY=1.18,opacity=0),dict(scaleX=1,scaleY=1,opacity=1))
        enter('.cap-type .wt-w',.23,.90,dict(scaleX=1.08,scaleY=1.08,y=-9,opacity=0),dict(scaleX=1,scaleY=1,y=0,opacity=1),stagger=dict(amountMs=95,groupSize=3,order='center'))
    elif axes['motion'] == 'relay':
        enter('.cap-registration',0,.6,dict(x=-32,opacity=0),dict(x=0,opacity=1))
        enter('.cap-surface',.13,.66,dict(scaleX=.94,opacity=0),dict(scaleX=1,opacity=1))
        enter('.cap-edge',.26,.70,dict(scaleY=.7,opacity=0),dict(scaleY=1,opacity=1))
        enter('.cap-type .wt-w',.28,.78,dict(x=23,scaleX=.96,opacity=0),dict(x=-2,scaleX=1,opacity=1),stagger=dict(amountMs=130,groupSize=3,order='forward'))
        enter('.cap-type .wt-w',.78,1,dict(x=-2),dict(x=0))
    else:
        enter('.cap-registration',0,.65,dict(scaleY=.8,opacity=0),dict(scaleY=1,opacity=.7))
        enter('.cap-edge',0,.52,dict(scaleY=.06,opacity=0),dict(scaleY=1,opacity=1))
        enter('.cap-surface',.14,.7,dict(scaleY=.94,opacity=0),dict(scaleY=1,opacity=1))
        enter('.cap-type .wt-w',.26,.94,dict(x=5,scaleX=1.05,opacity=0),dict(x=0,scaleX=1,opacity=1),stagger=dict(amountMs=85,groupSize=2,order='center'))
    enter('.cap-top',0,.60,dict(x=-24,scaleX=.12,opacity=0),dict(x=0,scaleX=1,opacity=1))
    enter('.cap-bottom',.06,.70,dict(x=24,scaleX=.12,opacity=0),dict(x=0,scaleX=1,opacity=1))
    enter('.cap-pattern',.2,.68,dict(opacity=0),dict(opacity=.7))
    enter('.cap-type .wt-focus',.4,.98,dict(scaleY=1.15,opacity=0),dict(scaleY=1,opacity=1),optional=True)
    # One local reflection, driven by cue time; it never washes over the glyphs.
    enter('.cap-light',.28,.58,dict(backgroundPositionX=-400,opacity=0),dict(backgroundPositionX=0,opacity=.48))
    enter('.cap-light',.58,1,dict(backgroundPositionX=0,opacity=.48),dict(backgroundPositionX=400,opacity=0))
    exit_x = -18 if axes['motion']=='relay' else 0
    leave('.cap-type .wt-w',0,.66,dict(x=0,y=0,scaleY=1,opacity=1),dict(x=exit_x,y=3,scaleY=.94,opacity=0),stagger=dict(amountMs=65,groupSize=3,order='reverse'))
    leave('.cap-type .wt-focus',0,.66,dict(opacity=1),dict(opacity=0),optional=True)
    leave('.cap-pattern',.2,.60,dict(opacity=.7),dict(opacity=0))
    leave('.cap-surface',.28,.80,dict(scaleY=1,opacity=1),dict(scaleY=.82,opacity=0))
    leave('.cap-top',.32,.92,dict(x=0,scaleX=1,opacity=1),dict(x=24,scaleX=.12,opacity=0))
    leave('.cap-bottom',.36,.94,dict(x=0,scaleX=1,opacity=1),dict(x=-24,scaleX=.12,opacity=0))
    leave('.cap-edge',.4,.94,dict(scaleY=1,opacity=1),dict(scaleY=.10 if axes['motion']=='refract' else .88,opacity=0))
    leave('.cap-registration',.45,.96,dict(opacity=.7 if axes['motion']=='refract' else 1),dict(opacity=0))
    return dict(cueHtml=markup,cueCss=css,stageHtml='',stageCss='',
        palette=dict(primary=c['accent'],text=c['ink']),
        appearance=dict(fontFamily=c['fontFamily'],fontSize=c['fontSize'],fontWeight=900 if 'Heavy' in c['fontFamily'] else 500 if 'Source Han' in c['fontFamily'] else 400),
        motionSpec=dict(version=2,runtime='gsap',buildMs=c['buildMs'],resolveMs=c['resolveMs'],tracks=tracks))


def examples():
    """Explicit local test compositions, never fallback model outputs."""
    return [dict(version=2),dict(version=2,geometry='chamfer',surface='duotone',border='rails',lettering='offset',motion='relay',
        paper='#152939',ink='#F4F0DF',accent='#EC5754',edge='#4EABDF'),
        dict(version=2,geometry='capsule',surface='glass',border='prism',lettering='spectral',motion='refract',
        ink='#DAF7FF',paper='#1D3745',accent='#99EAE3',edge='#AA8DDD')]
