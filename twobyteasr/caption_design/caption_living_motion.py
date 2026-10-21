"""V5 game UI motion: one cue clock, real cadence, bounded reading life.

This is a versioned expansion, never a migration of an adopted artwork.
"""
import copy

PRESETS = {
    'crt': dict(entrance='CRT通电：亮线展开、屏框捕获、正文锁定、标签扣合',
                reading='缓慢扫描、低频颗粒流动、面板微浮动',
                exit='标签先退、文字失活、屏幕压线熄灭'),
    'score': dict(entrance='奖励弹窗：底板扣合、倍率翻入、筹码后锁',
                  reading='局部倍率轻弹、颗粒呼吸、弹窗微动',
                  exit='倍率先收、正文归档、计分板侧向收束'),
    'foil': dict(entrance='稀有封签：套封翻出、银墨点亮、贴签扣住',
                 reading='局部foil循环扫光、封签微浮动',
                 exit='贴签先抽、字与板一起翻合封存'),
}


def transition_tracks(style):
    """Video-transition grammar, scaled to the caption's own frame.

    The panel layers wipe independently; readable text is never duplicated.
    Motion is declarative and can be combined with any V5 glyph material.
    """
    tracks=[]
    def move(sel,phase,start,end,before,after,ease='power2.out',**kw):
        tracks.append(dict(selector=sel,phase=phase,start=start,end=end,ease=ease,
                           **{'from':before,'to':after},**kw))
    def enter(sel,start,end,a,b,**kw):move(sel,'build',start,end,a,b,**kw)
    def leave(sel,start,end,a,b,**kw):move(sel,'resolve',start,end,a,b,ease='power2.in',**kw)
    opened='inset(0% 0% 0% 0%)';line='inset(49% 0% 49% 0%)';point='inset(49% 49% 49% 49%)'
    enter('.bui-assembly',0,.035,dict(opacity=0),dict(opacity=1),ease='none')
    leave('.bui-assembly',.94,.98,dict(opacity=1),dict(opacity=0))
    if style=='crt':
        # Bright horizontal carrier first, screen expansion second. Distortion
        # locks before reading begins; shutdown reverses the signal sequence.
        enter('.bui-backing',0,.23,dict(clipPath=point),dict(clipPath=line),ease='expo.out')
        enter('.bui-backing',.23,.67,dict(clipPath=line),dict(clipPath=opened))
        enter('.bui-shell',.13,.64,dict(clipPath=line,x=-6),dict(clipPath=opened,x=0),ease='steps(6)')
        enter('.bui-copy',.28,.83,dict(clipPath=line,x=5,opacity=0),dict(clipPath=opened,x=0,opacity=1),ease='steps(5)')
        leave('.bui-copy',.08,.55,dict(clipPath=opened,opacity=1),dict(clipPath=line,opacity=0))
        leave('.bui-shell',.30,.80,dict(clipPath=opened,x=0),dict(clipPath=line,x=0))
        leave('.bui-shell',.80,.95,dict(clipPath=line),dict(clipPath=point))
        leave('.bui-backing',.34,.93,dict(clipPath=opened),dict(clipPath=point))
    elif style=='score':
        enter('.bui-backing',0,.50,dict(clipPath='inset(0% 49% 0% 49%)'),dict(clipPath=opened),ease='expo.out')
        enter('.bui-shell',.06,.66,dict(y=-24,scaleX=.88,scaleY=1.15,opacity=0),dict(y=0,scaleX=1,scaleY=1,opacity=1),ease='back.out(1.7)')
        enter('.bui-copy',.25,.82,dict(clipPath='inset(0% 0% 100% 0%)',y=-8),dict(clipPath=opened,y=0))
        leave('.bui-copy',.12,.59,dict(clipPath=opened,y=0),dict(clipPath='inset(100% 0% 0% 0%)',y=6))
        leave('.bui-shell',.35,.91,dict(clipPath=opened,x=0),dict(clipPath='inset(0% 0% 0% 100%)',x=20))
        leave('.bui-backing',.45,.96,dict(clipPath=opened),dict(clipPath='inset(0% 100% 0% 0%)'))
    else:
        # Opposing panel masks recall split transitions and a physical sleeve.
        enter('.bui-backing',0,.59,dict(clipPath='inset(0% 100% 0% 0%)',x=-14),dict(clipPath=opened,x=0),ease='expo.out')
        enter('.bui-shell',.09,.72,dict(clipPath='inset(0% 0% 0% 100%)',x=18),dict(clipPath=opened,x=0),ease='expo.out')
        enter('.bui-copy',.27,.85,dict(clipPath='inset(0% 50% 0% 50%)',y=6),dict(clipPath=opened,y=0))
        leave('.bui-copy',.12,.63,dict(clipPath=opened,y=0),dict(clipPath='inset(0% 50% 0% 50%)',y=4))
        leave('.bui-shell',.33,.91,dict(clipPath=opened,x=0),dict(clipPath='inset(0% 100% 0% 0%)',x=-18))
        leave('.bui-backing',.43,.96,dict(clipPath=opened,x=0),dict(clipPath='inset(0% 0% 0% 100%)',x=14))
    enter('.bui-copy .wt-focus',.44,.96,dict(scaleX=.78,scaleY=.84,opacity=0),dict(scaleX=1,scaleY=1,opacity=1),ease='back.out(1.7)',optional=True)
    leave('.bui-copy .wt-focus',0,.46,dict(scaleX=1,scaleY=1,opacity=1),dict(scaleX=.86,scaleY=.80,opacity=0),optional=True)
    for i,sel in enumerate(['.bui-tab-main','.bui-tab-side','.bui-rail-left','.bui-rail-right','.bui-stitch']):
        direction=-1 if i%2 else 1
        enter(sel,.38+i*.035,.82+i*.035,dict(y=direction*10,opacity=0),dict(y=0,opacity=1),ease='back.out(1.7)')
        leave(sel,i*.04,.46+i*.04,dict(y=0,opacity=1),dict(y=direction*12,opacity=0))
    return tracks


def compose(value):
    from .caption_type_effects import compose as previous
    value=copy.deepcopy(value);value['version']=4
    effect=value.get('typeEffect','crt')
    transition=value.pop('transition',effect)
    if transition not in PRESETS:raise ValueError('transition需要crt/score/foil')
    result=previous(value)
    # Separate inherited entrance/exit from the tiny reading pose. Its last
    # sampled pose remains in place through resolve, so there is no reset snap.
    markup=result['cueHtml'].replace('<div class="bui-assembly">',
        '<div class="bui-life"><div class="bui-assembly">',1)
    close=markup.rfind('</div>')
    markup=markup[:close]+'</div>'+markup[close:]
    markup=markup.replace('<div class="bui-grain"',
        '<div class="bui-scan-window" aria-hidden="true"><div class="bui-scan"></div></div><div class="bui-grain"',1)
    result['cueHtml']=markup
    result['cueCss']+='''
.bui-life{position:relative;width:max-content;max-width:100%;transform-origin:50% 70%}
.bui-scan-window{position:absolute;inset:.18em .38em;overflow:hidden;border-radius:.08em;pointer-events:none}
.bui-scan{position:absolute;inset:-200% 0 0;height:200%;background:linear-gradient(180deg,transparent 64%,#89E4D515 78%,#E3FFF927 82%,transparent 95%);opacity:.6}
.bui-grain{background-image:repeating-linear-gradient(0deg,transparent 0 .10em,#050D1615 .10em .115em),repeating-linear-gradient(125deg,#F2EDD209 0 .013em,transparent .013em .12em);background-size:auto;opacity:.35}
'''
    tracks=transition_tracks(transition)
    result['motionSpec']['tracks']=tracks
    def life(selector,before,after,period,*,ease='sine.inOut',yoyo=True,optional=False):
        tracks.append(dict(selector=selector,phase='breathe',start=0,end=1,ease=ease,
            **{'from':before,'to':after},durationMs=period,sustain=True,yoyo=yoyo,
            **({'optional':True} if optional else {})))
    life('.bui-life',dict(rotation=0,y=0),dict(rotation=.22,y=-.65),1450)
    life('.bui-grain',dict(backgroundPositionX=0,backgroundPositionY=0),
         dict(backgroundPositionX=3,backgroundPositionY=4),2100,ease='none',yoyo=False)
    if effect=='crt':
        life('.bui-scan',dict(yPercent=0),dict(yPercent=100),2600,ease='none',yoyo=False)
        life('.bui-copy .wt-w',dict(backgroundPositionY=0),dict(backgroundPositionY=4),2300)
    elif effect=='score':
        # Keep the rounded emphasis border in one compositor layer. Chromium
        # otherwise caches different antialiasing after a long reverse seek.
        result['cueCss']+='\n.bui-scan{opacity:.18}.bui-copy .wt-focus{will-change:transform}'
        life('.bui-copy .wt-focus',dict(rotation=0),dict(rotation=.45),1100,optional=True)
        life('.bui-glint',dict(x=-1100),dict(x=1100),3200,ease='none',yoyo=False)
    else:
        result['cueCss']+='\n.bui-scan{opacity:.15}'
        life('.bui-copy .wt-w',dict(backgroundPositionX=-65),dict(backgroundPositionX=65),2600)
        life('.bui-glint',dict(x=-1100),dict(x=1100),3500,ease='none',yoyo=False)
    return result


def examples():
    from .caption_type_effects import examples as previous
    return [dict(v,version=5) for v in previous()]


def capability_text():
    from .caption_type_effects import capability_text as previous
    return previous()+'''\n当前首选caption-components-5：version:5。typeEffect选crt/score/foil字面；transition可独立选crt通电压线|score冲击结算|foil双向遮罩封套，默认同typeEffect，其余参数同v4。可组合三种框体、材料与三套转场，不只换色。参考视频转场插件的信号锁定、冲击回弹、遮罩分割：将全屏运动缩到字幕框内；不依赖安装插件。
阅读期的sustain:true+durationMs由工程时钟循环至窗口末尾，短cue不加速；CRT持续扫描/颗粒、局部wiggle/foil都克制，正文可读。
自写源码也用MotionSpec v2 breathe start:0,end:1,sustain:true,durationMs:1100..3500，不同时写repeat。微动层与进退层分开，接纳最后保持姿态，禁止退场瞬间复位。主动作必须通电/锁定/扣合/结算/封存等主题事件，不能仅普通淡入平移。'''
