"""Small, versioned authoring vocabulary; output is an ordinary portable theme.

The host expands components once. Preview, Studio and export consume that exact
source, never a second renderer or an autonomous component animation clock.
"""
import html
import math
import re

VERSION='caption-components-10'
OPTIONS={'layout':('compact','centered','editorial'),
         'frame':('double','corners','rules'),
         'lettering':('press','register','gradient'),
         'rhythm':('settle','slide','align')}
COLORS={'ink':'#F7F1DD','paper':'#202822','accent':'#D9CB85','edge':'#858D76'}


def normalize(value):
    if not isinstance(value,dict) or value.get('version')!=1:
        raise ValueError('components需要version=1')
    unknown=set(value)-{'version',*OPTIONS,*COLORS,'fontSize','fontFamily','emphasis','buildMs','resolveMs'}
    if unknown:raise ValueError('不支持的文字组件参数：'+','.join(sorted(unknown)))
    result={'version':1}
    for key,choices in OPTIONS.items():
        selected=value.get(key,choices[0])
        if selected not in choices:raise ValueError('不支持组件'+key+': '+str(selected))
        result[key]=selected
    for key,default in COLORS.items():
        color=value.get(key,default)
        if not isinstance(color,str) or not re.fullmatch('#[0-9A-Fa-f]{6}',color):raise ValueError(key+'需要#RRGGBB')
        result[key]=color
    for key,default,lo,hi in [('fontSize',72,40,100),('buildMs',480,180,650),('resolveMs',280,120,400)]:
        number=value.get(key,default)
        if type(number) not in (int,float) or not math.isfinite(number) or not lo<=number<=hi:raise ValueError(key+'超出组件范围')
        result[key]=number
    from .web_theme_fonts import FONT_FILES
    family=value.get('fontFamily','Source Han Sans SC Heavy')
    if family not in FONT_FILES:raise ValueError('组件字体未打包：'+str(family))
    result['fontFamily']=family
    emphasis=value.get('emphasis',[])
    if not isinstance(emphasis,list) or len(emphasis)>4 or any(not isinstance(t,str) or not 1<=len(t)<=24 or '|' in t for t in emphasis):
        raise ValueError('emphasis需要最多4个真实重点字组')
    result['emphasis']=emphasis
    return result


def compose(value):
    if isinstance(value,dict) and value.get('version')==10:
        from .pixel_motion import readable_noita_motion
        return readable_noita_motion(value)
    if isinstance(value,dict) and value.get('version')==9:
        from .pixel_motion import noita_motion
        return noita_motion(value)
    if isinstance(value,dict) and value.get('version')==8:
        from .caption_noita import compose as noita
        return noita(value)
    if isinstance(value,dict) and value.get('version')==7:
        from .caption_ice import compose as ice
        return ice(value)
    if isinstance(value,dict) and value.get('version')==6:
        from .caption_ice_legacy import compose as ice
        return ice(value)
    if isinstance(value,dict) and value.get('version')==5:
        from .caption_living_motion import compose as living
        return living(value)
    if isinstance(value,dict) and value.get('version')==4:
        from .caption_type_effects import compose as type_effects
        return type_effects(value)
    if isinstance(value,dict) and value.get('version')==3:
        from .caption_card_ui import compose as card_ui
        return card_ui(value)
    if isinstance(value,dict) and value.get('version')==2:
        from .caption_surfaces import compose as surfaces
        return surfaces(value)
    c=normalize(value)
    markup=('<div class="cap-layout"><div class="cap-body">'
        '<div class="cap-surface" aria-hidden="true"></div>'
        '<div class="cap-edge" aria-hidden="true"></div>'
        '<div class="cap-type" data-semantic-text="true" data-emphasis="'
        +html.escape('|'.join(c['emphasis']),quote=True)+'">{{words}}</div></div></div>')
    css='''
.cap-layout{position:absolute;left:5%;right:5%;bottom:10%;display:flex;justify-content:center;font-family:var(--wt-font);font-size:var(--wt-size)}
.cap-body{position:relative;width:max-content;max-width:92%;padding:.17em .42em .21em;box-sizing:border-box}
.cap-surface{position:absolute;inset:0;background:var(--cap-paper);border-radius:.04em;box-shadow:0 .04em .08em #00000055}
.cap-edge{position:absolute;inset:0;border:.018em solid var(--cap-edge);border-radius:.04em}
.cap-type{position:relative;color:var(--cap-ink);font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);line-height:1.3;text-align:center;letter-spacing:.012em}
.cap-type .wt-w{display:inline-block;white-space:pre}
.cap-type .wt-focus{display:inline-block;max-width:100%;vertical-align:baseline;background:var(--cap-accent);color:var(--cap-paper);box-decoration-break:clone;-webkit-box-decoration-break:clone}
'''
    # Local author variables stay static. Only two explicit motion variables
    # are allowed by MotionSpec; no host placement/font variables are exposed.
    css=('.cap-body{--cap-ink:'+c['ink']+';--cap-paper:'+c['paper']+';--cap-accent:'+c['accent']+';--cap-edge:'+c['edge']+'}\n')+css
    css+={'compact':'','centered':'.cap-body{padding:.24em .62em;max-width:78%}',
          'editorial':'.cap-layout{justify-content:flex-start;left:12%;right:8%}.cap-body{padding:.15em .5em .25em}.cap-type{text-align:left}'}[c['layout']]
    css+={'double':'.cap-edge:after{content:"";position:absolute;inset:.055em;border:.01em solid var(--cap-edge);opacity:.55}',
          'corners':'.cap-edge{border-left-width:.075em;border-right-width:.075em;border-top-color:transparent;border-bottom-color:transparent}.cap-surface{border-top:.012em solid var(--cap-edge);border-bottom:.012em solid var(--cap-edge)}',
          'rules':'.cap-edge{border:0;border-top:.022em solid var(--cap-accent);border-bottom:.012em solid var(--cap-edge);inset:-.045em .08em}'}[c['frame']]
    css+={'press':'.cap-type .wt-w{-webkit-text-stroke:.009em var(--cap-ink);text-shadow:0 .023em 0 #000000,0 -.011em 0 #FFFFFF60}.cap-type .wt-focus .wt-w{-webkit-text-stroke:0;text-shadow:0 .014em 0 #FFFFFF55}',
          'register':'.cap-type .wt-w{text-shadow:.018em .025em 0 var(--cap-accent),-.01em -.009em 0 #000000}.cap-type .wt-focus .wt-w{text-shadow:.018em .015em 0 #FFFFFF55}',
          'gradient':'.cap-type .wt-w{background:linear-gradient(165deg,var(--cap-ink) 25%,var(--cap-accent) 100%);background-clip:text;-webkit-background-clip:text;color:transparent;-webkit-text-fill-color:transparent;filter:drop-shadow(0 .023em .008em #000000)}.cap-type .wt-focus .wt-w{background:none;color:var(--cap-paper);-webkit-text-fill-color:var(--cap-paper);filter:none}'}[c['lettering']]
    tracks=[]
    def move(selector,phase,start,end,before,after,ease='power2.out',**extra):
        tracks.append(dict(selector=selector,phase=phase,start=start,end=end,ease=ease,**{'from':before,'to':after},**extra))
    move('.cap-surface','build',0,.68,dict(y=8,scaleY=.78,opacity=0),dict(y=0,scaleY=1,opacity=1))
    move('.cap-edge','build',.08,.8,dict(scaleX=.9,opacity=0),dict(scaleX=1,opacity=1))
    shift={'settle':dict(y=16),'slide':dict(x=-18),'align':dict(y=9,scaleY=.9)}[c['rhythm']]
    resting={key:1 if key.startswith('scale') else 0 for key in shift}
    move('.cap-type .wt-w','build',.18,1,dict(shift,opacity=0),dict(resting,opacity=1),
         stagger=dict(amountMs=140,groupSize=2,order='center' if c['rhythm']=='align' else 'forward'))
    # Optional semantic emphasis disappears harmlessly when a later cue has no match.
    move('.cap-type .wt-focus','build',.35,.95,dict(opacity=0),dict(opacity=1),optional=True)
    move('.cap-type .wt-w','resolve',0,.76,dict(y=0,opacity=1),dict(y=-9,opacity=0),'power2.in',
         stagger=dict(amountMs=60,groupSize=3,order='reverse'))
    move('.cap-type .wt-focus','resolve',0,.76,dict(opacity=1),dict(opacity=0),'power2.in',optional=True)
    move('.cap-edge','resolve',.35,.88,dict(scaleX=1,opacity=1),dict(scaleX=.94,opacity=0),'power2.in')
    move('.cap-surface','resolve',.4,.94,dict(y=0,scaleY=1,opacity=1),dict(y=5,scaleY=.85,opacity=0),'power2.in')
    return dict(cueHtml=markup,cueCss=css,stageHtml='',stageCss='',
        appearance=dict(fontFamily=c['fontFamily'],fontSize=c['fontSize'],fontWeight=900 if 'Heavy' in c['fontFamily'] else 500 if 'Source Han' in c['fontFamily'] else 400),
        palette=dict(primary=c['accent'],text=c['ink']),
        motionSpec=dict(version=2,runtime='gsap',buildMs=c['buildMs'],resolveMs=c['resolveMs'],tracks=tracks))


def capability_text(style=None):
    if style == 'noita':
        from .caption_noita import capability_text as noita_capability
        from .pixel_motion import capability_text as pixel_capability
        return noita_capability()+'\n'+pixel_capability()
    if style == 'ice':
        from .caption_ice import capability_text as ice_capability
        return ice_capability()
    if style == 'balatro':
        from .caption_living_motion import capability_text as card_capability
        return card_capability()
    return '''文字组件 caption-components-2：PARAMETERS.components组合，HTML/CSS/STAGE_CSS留空；宿主一次展开同份源码用于预览/采用/导出。也可完全自创安全HTML/CSS+MotionSpec，二者不可混用；组件不是源码能力上限。
components: {version:2,geometry:inset内嵌|chamfer斜角|capsule弧角,surface:print印刷纹理|duotone分区|glass局部半透,border:registration复合套边|rails上下色轨|prism折射色边,lettering:intaglio压印|offset定向厚度|spectral渐变反射,motion:stamp套色扣合压印|relay色轨交接带动文字|refract轮廓建立反光收齐,fontSize:40..100,fontFamily:打包字体名,ink/paper/accent/edge:#RRGGBB,emphasis:[真实重点字组],buildMs:180..650,resolveMs:120..400}。值只写冒号后的英文ID，不含中文说明。各轴独立组合，版面随实际文本伸缩换行，无关键词仍有完整字面。version:1仅旧基线兼容，不是生成失败的默认退路。
源码能力：静态多层描边/轻压印/双色套印/局部字面渐变、SVG strokeDashoffset边框描线、局部clipPath、受控数值CSS变量--caption-reveal(0..1)/--caption-sheen(0..100)。关键帧使用不重叠的顺序from/to轨道；不支持任意JS回调/任意CSS变量/GSAP插件，不能静默替代。'''
