"""V4 letter surfaces and themed events over the existing V3 card structures.

No autonomous clock, random jitter, duplicate text or replacement of saved V3.
"""
import copy

EFFECTS=('crt','score','foil')


def compose(value):
    from .caption_card_ui import compose as card
    value=copy.deepcopy(value)
    effect=value.pop('typeEffect','crt')
    if effect not in EFFECTS:raise ValueError('typeEffect需要crt/score/foil')
    value['version']=3
    result=card(value)
    # Preserve successful frame geometry; the new glyph treatment belongs to
    # this version only. All text copies remain semantic host-provided glyphs.
    css=result['cueCss']
    if effect=='crt':
        css+='''
.bui-copy .wt-w{background:repeating-linear-gradient(0deg,#CEEEDC 0 .035em,#8EA698 .035em .050em,#EFFFF0 .050em .080em);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;-webkit-text-stroke:.004em #D7FDE0;text-shadow:none;filter:drop-shadow(.012em .016em 0 #12494F)}
.bui-copy .wt-focus{background:#8051AE;border:.034em solid #DFBCEE;box-shadow:0 .055em 0 #462C62,inset 0 .025em 0 #DFAEF0}
.bui-copy .wt-focus .wt-w{background:repeating-linear-gradient(0deg,#FFF6DA 0 .037em,#D9D19F .037em .053em,#FFFFF0 .053em .08em);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;-webkit-text-stroke:.003em #FFF6E0;text-shadow:none;filter:drop-shadow(.016em .022em 0 #402551)}
.bui-grain{background:repeating-linear-gradient(0deg,transparent 0 .075em,#050D1618 .075em .09em);opacity:.42}
'''
    elif effect=='score':
        css+='''
.bui-copy .wt-w{background:linear-gradient(180deg,#FFFAE1 0 48%,#E2CCA1 49% 57%,#FFF2C6 58%);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;-webkit-text-stroke:.007em #F9E7C8;text-shadow:none;filter:drop-shadow(.025em .045em 0 #13333D)}
.bui-copy .wt-focus{background:linear-gradient(175deg,#FF7865,#EB4239 60%,#C43535);border:.035em solid #FFC5A0;border-bottom-color:#842A31;box-shadow:0 .06em 0 #782631,inset 0 .025em 0 #FFE2B0;border-radius:.05em .12em .05em .12em}
.bui-copy .wt-focus .wt-w{background:linear-gradient(180deg,#FFFFFF 0 52%,#FFE4BB 53%);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;-webkit-text-stroke:.006em #FFF2DA;text-shadow:none;filter:drop-shadow(.023em .035em 0 #AF252D)}
.bui-tab-main{background:#EE4943}.bui-tab-side{background:#009FEC;color:#FFFFFF}
'''
    else:
        css+='''
.bui-copy .wt-w{background:linear-gradient(115deg,#F0EADB 0%,#F0EADB 24%,#BFCFE5 35%,#E6C4E0 44%,#FFFFE5 50%,#BFD8DC 56%,#F0EADB 68%,#F0EADB 100%);background-size:220% 100%;background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;-webkit-text-stroke:.004em #E5E1DB;filter:drop-shadow(.015em .03em 0 #17182F);text-shadow:none}
.bui-copy .wt-focus{background:linear-gradient(135deg,#6A417D,#9B658F 52%,#514C81);border:.036em solid #E0D2E0;box-shadow:.035em .06em 0 #302241,inset 0 .02em 0 #EEE1CB}
.bui-copy .wt-focus .wt-w{background:linear-gradient(115deg,#FFF1DD,#EDCAE0 35%,#FEFFEC 50%,#C1ECE7 65%,#FFF1DD);background-size:220% 100%;background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;-webkit-text-stroke:.004em #FDEFD8;filter:drop-shadow(.012em .023em 0 #41284F);text-shadow:none}
'''
    # A model can select a pale paper surface. Keep the same material but make
    # its glyph palette legible instead of fixing pale light-emitting ink.
    paper=value.get('paper','#F4EEDB').lstrip('#')
    luminance=sum(int(paper[i:i+2],16)*w for i,w in zip((0,2,4),(.2126,.7152,.0722)))
    if luminance>155:
        palettes={'crt':('repeating-linear-gradient(0deg,#24483E 0 .035em,#527365 .035em .050em,#24483E .050em .080em)','#24483E'),
                  'score':('linear-gradient(180deg,#1A424D 0 48%,#496875 49% 57%,#1B3742 58%)','#214652'),
                  'foil':('linear-gradient(115deg,#303E59 0%,#303E59 24%,#6A6582 35%,#755673 44%,#53636B 50%,#315A59 56%,#303E59 68%,#303E59 100%)','#394359')}
        gradient,stroke=palettes[effect]
        css+='\n.bui-copy .wt-w{background-image:'+gradient+';-webkit-text-stroke:.004em '+stroke+';filter:drop-shadow(.012em .022em 0 #FFF6DD)}'
    keyword=value.get('keyword','mult')
    badge={'mult':('#FF6252','#CA302F','#FFC3AA','#772832'),
           'chip':('#168BBC','#085078','#BCE9F5','#123C5F'),
           'sticker':('#77468E','#472757','#DFBFE8','#2F1F3E')}[keyword]
    css+='\n.bui-copy .wt-focus{background:linear-gradient(165deg,'+badge[0]+','+badge[1]+');border-color:'+badge[2]+';box-shadow:0 .055em 0 '+badge[3]+'}'
    result['cueCss']=css
    tracks=[]
    def move(selector,phase,start,end,before,after,ease='power2.out',**kw):
        tracks.append(dict(selector=selector,phase=phase,start=start,end=end,ease=ease,**{'from':before,'to':after},**kw))
    def enter(sel,start,end,a,b,**kw):move(sel,'build',start,end,a,b,**kw)
    def leave(sel,start,end,a,b,**kw):move(sel,'resolve',start,end,a,b,'power2.in',**kw)
    enter('.bui-assembly',0,.05,dict(opacity=0),dict(opacity=1),ease='none')
    leave('.bui-assembly',.92,.98,dict(opacity=1),dict(opacity=0))
    panels=['.bui-backing','.bui-shell','.bui-stock','.bui-rim','.bui-grain']
    for i,sel in enumerate(panels):
        if effect=='crt':
            enter(sel,i*.025,.58+i*.035,dict(clipPath='inset(49% 48% 49% 48%)',opacity=0),dict(clipPath='inset(0% 0% 0% 0%)',opacity=1))
            leave(sel,.28+i*.035,.87+i*.016,dict(clipPath='inset(0% 0% 0% 0%)',opacity=1),dict(clipPath='inset(49% 48% 49% 48%)',opacity=0))
        elif effect=='score':
            enter(sel,i*.02,.57+i*.03,dict(y=-15,scaleY=1.13,opacity=0),dict(y=0,scaleY=1,opacity=1),ease='back.out(1.7)')
            leave(sel,.34+i*.02,.90+i*.01,dict(x=0,scaleX=1,opacity=1),dict(x=18,scaleX=.86,opacity=0))
        else:
            enter(sel,i*.025,.62+i*.025,dict(rotationX=38,y=10,opacity=0),dict(rotationX=0,y=0,opacity=1),ease='back.out(1.7)')
            leave(sel,.33+i*.02,.88+i*.015,dict(rotationX=0,x=0,opacity=1),dict(rotationX=-32,x=-18,opacity=0))
    if effect=='crt':
        enter('.bui-copy',.29,.87,dict(clipPath='inset(0% 100% 0% 0%)',opacity=0),dict(clipPath='inset(0% 0% 0% 0%)',opacity=1))
        leave('.bui-copy',.08,.67,dict(clipPath='inset(0% 0% 0% 0%)',opacity=1),dict(clipPath='inset(48% 0% 48% 0%)',opacity=0))
        move('.bui-copy .wt-w','breathe',.15,.75,dict(backgroundPositionY=0),dict(backgroundPositionY=5),'none',durationMs=1600)
        move('.bui-grain','breathe',.10,.74,dict(backgroundPositionY=0),dict(backgroundPositionY=9),'none',durationMs=1700)
    else:
        enter('.bui-copy .wt-w',.26,.91,dict(y=8,rotationX=30,opacity=0),dict(y=0,rotationX=0,opacity=1),stagger=dict(amountMs=90,groupSize=3,order='center'))
        leave('.bui-copy .wt-w',.08,.7,dict(y=0,rotationX=0,opacity=1),dict(y=5,rotationX=-25,opacity=0),stagger=dict(amountMs=60,groupSize=3,order='reverse'))
        if effect=='foil':move('.bui-copy .wt-w','breathe',.13,.82,dict(backgroundPositionX=-65),dict(backgroundPositionX=65),'sine.inOut',durationMs=1300)
    enter('.bui-copy .wt-focus',.44,.95,dict(scaleX=.82,scaleY=.85,rotationX=45,opacity=0),dict(scaleX=1,scaleY=1,rotationX=0,opacity=1),ease='back.out(1.7)',optional=True)
    leave('.bui-copy .wt-focus',0,.54,dict(scaleX=1,scaleY=1,rotationX=0,opacity=1),dict(scaleX=.9,scaleY=.8,rotationX=-45,opacity=0),optional=True)
    if effect=='score':
        move('.bui-copy .wt-focus','breathe',0,.5,dict(rotation=1),dict(rotation=0),'sine.inOut',durationMs=150,optional=True)
    for i,sel in enumerate(['.bui-tab-main','.bui-tab-side','.bui-rail-left','.bui-rail-right','.bui-stitch']):
        enter(sel,.36+i*.035,.82+i*.035,dict(y=(-8 if i%2 else 8),opacity=0),dict(y=0,opacity=1),ease='back.out(1.7)')
        leave(sel,i*.045,.50+i*.04,dict(y=0,opacity=1),dict(y=(-12 if i%2 else 12),opacity=0))
    move('.bui-glint','breathe',.1,.8,dict(x=-1100),dict(x=1100),'sine.inOut',durationMs=1000)
    result['motionSpec']['tracks']=tracks
    return result


def examples():
    return [dict(version=4,structure='seal',surface='paper',lettering='enamel',keyword='sticker',motion='deal',typeEffect='crt',paper='#223B3D',ink='#E4F2DA',accent='#9864BA'),
            dict(version=4,structure='table',surface='felt',lettering='enamel',keyword='mult',motion='press',typeEffect='score',paper='#244E48',ink='#FFF3CF',accent='#F15349'),
            dict(version=4,structure='legend',surface='foil',lettering='silver',keyword='chip',motion='sleeve',typeEffect='foil',paper='#33334F',ink='#F1EADB',accent='#9962BE')]


def capability_text():
    from .caption_card_ui import capability_text as previous
    return previous()+'''\n升级能力caption-components-4：使用version:4并新增typeEffect:crt字内扫描/磷光细纹/屏幕激活收束|score立体双色字/倍率翻出/短促触发结算|foil银墨虹彩字/一次字内反光/封签抽离。其余五轴与v3相同；保留既有框体构图，typeEffect主导新动作语气。优先v4强化字本身；可自创完整安全源码。三稿建议Legendary CRT、Mult/Chips Trigger、Foil/Seal，但不要仅更名或换色。'''
