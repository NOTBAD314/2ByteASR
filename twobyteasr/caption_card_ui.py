"""Reference-led card UI vocabulary, expanded into portable WebTheme source.

Three structural families share independent material, lettering, keyword and
choreography axes. No sprites, portraits, remote assets or additional clock.
"""
import html

OPTIONS = {'structure': ('seal', 'table', 'legend'),
           'surface': ('paper', 'felt', 'foil'),
           'lettering': ('pressed', 'enamel', 'silver'),
           'keyword': ('mult', 'chip', 'sticker'),
           'motion': ('deal', 'press', 'sleeve')}


def compose(value):
    from .caption_components import normalize, COLORS
    extra = set(value) - {'version', *OPTIONS, *COLORS, 'fontSize', 'fontFamily',
                         'emphasis', 'buildMs', 'resolveMs'}
    if extra:
        raise ValueError('不支持的卡牌UI参数：' + ','.join(sorted(extra)))
    axes = {key:value.get(key, choices[0]) for key,choices in OPTIONS.items()}
    for key, choices in OPTIONS.items():
        if axes[key] not in choices:
            raise ValueError('不支持卡牌UI ' + key + ': ' + str(axes[key]))
    base = dict(version=1, ink='#253B3C', paper='#F4EEDB', accent='#ED5147',
                edge='#657A7D', fontSize=64, buildMs=620, resolveMs=380)
    base.update({key:val for key,val in value.items() if key not in OPTIONS and key != 'version'})
    c = normalize(base)
    labels = {'seal':('MULT', 'CHIPS'), 'table':('CHIPS', '♣ ♦'),
              'legend':('LEGENDARY', 'FOIL')}[axes['structure']]
    structure = {
        'seal':'<div class="bui-header-band" aria-hidden="true"><span class="bui-suit">♦</span></div>',
        'table':'<div class="bui-press-top" aria-hidden="true"></div><div class="bui-press-bottom" aria-hidden="true"></div>',
        'legend':'<div class="bui-fold" aria-hidden="true"></div><div class="bui-perforation" aria-hidden="true"></div>',
    }[axes['structure']]
    markup = ('<div class="bui-layout"><div class="bui-assembly">'
        '<div class="bui-backing" aria-hidden="true"></div>'
        '<div class="bui-shell" aria-hidden="true"><div class="bui-stock"></div>'
        '<div class="bui-grain"></div><div class="bui-rim"></div>'
        '<div class="bui-rail bui-rail-left"></div><div class="bui-rail bui-rail-right"></div>'
        '<div class="bui-shine-window"><div class="bui-glint"></div></div>'+structure+'</div>'
        '<div class="bui-copy" data-semantic-text="true" data-emphasis="'
        + html.escape('|'.join(c['emphasis']), quote=True) + '">{{words}}</div>'
        '<div class="bui-tab bui-tab-main" aria-hidden="true">'+labels[0]+'</div>'
        '<div class="bui-tab bui-tab-side" aria-hidden="true">'+labels[1]+'</div>'
        '<div class="bui-stitch" aria-hidden="true"></div></div></div>')
    css = '.bui-assembly{' + ''.join('--bui-'+key+':'+c[key]+';' for key in COLORS) + '}\n' + '''
.bui-layout{position:absolute;left:7%;right:7%;bottom:9.5%;display:flex;justify-content:center;font-family:var(--wt-font);font-size:var(--wt-size)}
.bui-assembly{position:relative;width:max-content;max-width:96%;min-width:4.6em;padding:.47em .72em .44em;box-sizing:border-box}
.bui-shell,.bui-backing{position:absolute;inset:0;border-radius:.17em;background:#263B3E}
.bui-backing{inset:.10em -.05em -.13em .055em;background:var(--bui-accent);border:.032em solid #17282C;box-shadow:0 .08em 0 #132629}
.bui-shell{border:.06em solid var(--bui-edge);box-shadow:inset 0 .026em 0 #CAD6D3,0 .08em 0 #102529,0 .14em 0 #152428}
.bui-stock{position:absolute;inset:.14em .16em;border-radius:.065em;background:var(--bui-paper);box-shadow:0 -.028em 0 #172A2C,inset 0 .025em 0 #FFFFFFAF,0 .027em 0 #FFFFFF85}
.bui-rim{position:absolute;inset:.08em;border:.016em solid #D7E5DCAA;border-radius:.08em}
.bui-grain{position:absolute;inset:.17em .20em;border-radius:.06em;pointer-events:none;background:radial-gradient(#213D3520 .012em,transparent .014em) 0 0/.13em .11em;opacity:.55}
.bui-rail{position:absolute;top:.29em;bottom:.29em;width:.065em;background:var(--bui-accent);border-radius:.02em}
.bui-rail-left{left:.26em}.bui-rail-right{right:.26em;background:#009FEC}
.bui-shine-window{position:absolute;left:.20em;right:.20em;top:.085em;height:.04em;overflow:hidden;border-radius:.03em;pointer-events:none}
.bui-glint{position:absolute;left:50%;top:0;bottom:0;width:1.4em;background:linear-gradient(90deg,transparent,#FFFFFFD0,transparent)}
.bui-copy{position:relative;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:var(--wt-weight);color:var(--bui-ink);line-height:1.42;letter-spacing:.012em;text-align:center}
.bui-copy .wt-w{display:inline-block;white-space:pre}
.bui-copy .wt-focus{display:inline-block;max-width:100%;vertical-align:baseline;margin:0 .05em;padding:.01em .12em .035em;box-sizing:border-box;line-height:1.23;border-radius:.065em}
.bui-tab{position:absolute;font-family:var(--wt-font);font-size:.31em;font-weight:var(--wt-weight);line-height:1.25;letter-spacing:.045em;border-radius:.15em;padding:.12em .62em .18em;border:.08em solid #1C2F33;box-shadow:0 .14em 0 #14292D;color:#FFFEED;white-space:nowrap}
.bui-tab-main{top:-.37em;left:1.48em;background:var(--bui-accent)}
.bui-tab-side{bottom:-.25em;right:1.65em;background:#058ACE}
.bui-stitch{position:absolute;left:.66em;right:.66em;bottom:.225em;height:.022em;background:repeating-linear-gradient(90deg,var(--bui-edge) 0 .06em,transparent .06em .14em);opacity:.6}
'''
    css += {'seal':''' 
.bui-assembly{max-width:min(96%,12.6em);padding:.72em .66em .41em}
.bui-stock{top:.46em}.bui-grain{top:.49em}.bui-rail{top:.62em}
.bui-header-band{position:absolute;left:.18em;right:.18em;top:.06em;height:.32em;border-bottom:.017em solid #9CAC9F;display:flex;align-items:center;justify-content:center;color:#E9DBC1}
.bui-suit{font-size:.29em;line-height:1}
.bui-tab-main{top:.14em;left:1.6em;transform:rotate(-2deg);font-size:.27em;padding:.05em .65em .11em}
.bui-tab-side{top:.14em;bottom:auto;right:1.6em;transform:rotate(1deg);font-size:.27em;padding:.05em .65em .11em}
.bui-copy{line-height:1.33}
''', 'table':'''
.bui-assembly{padding:.36em .86em .38em;min-width:5em}
.bui-shell,.bui-backing{border-radius:.36em .10em .36em .10em}
.bui-backing{inset:.11em -.035em -.12em .025em;background:#A88145}
.bui-shell{border:.09em solid #B29C72;box-shadow:inset 0 .04em 0 #ECDFBC,0 .095em 0 #112726,0 .16em 0 #142626}
.bui-stock{inset:.12em .35em;border-radius:.18em .055em .18em .055em}
.bui-rim{inset:.09em;border:.019em solid #EBD9A8;border-radius:.24em .035em .24em .035em}
.bui-rail{top:.15em;bottom:.15em;width:.19em;border-radius:.10em;background:repeating-linear-gradient(0deg,#EADAB3 0 .11em,#197D98 .11em .23em);border:.027em solid #152D2D;box-shadow:inset .03em 0 0 #FFF4C788}
.bui-rail-left{left:.04em}.bui-rail-right{right:.04em;background:repeating-linear-gradient(0deg,#EADAB3 0 .11em,#B6483C .11em .23em)}
.bui-tab-main{top:auto;bottom:-.28em;left:2.8em;background:#176A71;border-color:#BCA57B;color:#FFF0BC;font-size:.27em}
.bui-tab-side{top:-.27em;bottom:auto;right:2.8em;background:#243B35;border-color:#BCA57B;color:#F1D18B;font-size:.27em}
.bui-stitch{left:.69em;right:.69em;bottom:.21em;background:#DCC499;opacity:.4}
.bui-press-top,.bui-press-bottom{position:absolute;left:.4em;right:.4em;height:.065em;background:linear-gradient(90deg,#71502B,#EBCEA0 25%,#957548 55%,#EAD6AA 80%,#826840);border-radius:.03em}
.bui-press-top{top:-.08em}.bui-press-bottom{bottom:-.1em}
''', 'legend':'''
.bui-assembly{padding:.43em .82em .69em;min-width:5.8em}
.bui-backing{inset:-.055em .06em .075em -.045em;background:linear-gradient(125deg,#C6E9F6,#7866A0 24%,#F9DDAA 49%,#DDACD6 71%,#88CCE0);border:.035em solid #DDDFEA;transform:rotate(-1.3deg);box-shadow:.075em .14em 0 #121C31}
.bui-shell{border:.065em solid #B6B9D6;border-radius:.055em .22em .055em .22em;background:#25283E;box-shadow:inset 0 .035em 0 #FBF0DB,0 .075em 0 #565477,0 .15em 0 #1C2333}
.bui-stock{inset:.17em .20em;border-radius:.035em .10em .035em .10em}
.bui-rim{inset:.085em;border:.020em solid #DEDCE8;border-radius:.045em .15em .045em .15em}
.bui-rail{top:.20em;bottom:.20em;width:.11em;background:linear-gradient(180deg,#AFF0ED,#D2A4DC,#EAE3A0,#B7C8FF)}
.bui-rail-left{left:.045em}.bui-rail-right{right:.045em}
.bui-tab-main{top:auto;bottom:.24em;left:50%;transform:translateX(-50%);background:#8751B2;border-color:#D4BADA;color:#FFFBED;font-size:.26em;box-shadow:0 .13em 0 #412D55;padding:.05em 1em .09em}
.bui-tab-side{top:-.30em;bottom:auto;right:1.4em;background:linear-gradient(135deg,#BBDBD2,#B29ACD,#E6C0C8,#EBD7A5);border-color:#F4E7DA;color:#323448;font-size:.28em;box-shadow:.1em .13em 0 #28283E}
.bui-shine-window{top:.005em;left:.04em;right:.04em;height:.12em}
.bui-stitch{opacity:.35;bottom:.25em;background:linear-gradient(90deg,transparent,#CFB6E2,#F5ECCB,#ABCADA,transparent);height:.03em}
.bui-fold{position:absolute;right:-.01em;top:-.015em;width:.32em;height:.32em;background:linear-gradient(135deg,#C1A9CC,#F0E6C8 44%,#516682 47%,#D9CDDD 53%,#EBECDF);clip-path:polygon(0% 0%,100% 0%,100% 100%);filter:drop-shadow(-.025em .025em .01em #121727)}
.bui-perforation{position:absolute;left:.42em;top:.20em;bottom:.18em;width:.025em;background:repeating-linear-gradient(0deg,#CEBCE35C 0 .025em,transparent .025em .09em)}
'''}[axes['structure']]
    css += {'paper':'''
.bui-stock{background:linear-gradient(170deg,#FFFFFF80,transparent 45%,#CFB66E16),var(--bui-paper)}
''','felt':'''
.bui-stock{background:radial-gradient(ellipse at 50% 0%,#3E8B7240,transparent 65%),var(--bui-paper);box-shadow:inset 0 .045em .06em #071A16B0,inset 0 -.025em 0 #D1D9A238}
.bui-grain{inset:.18em .39em;background:repeating-linear-gradient(35deg,#ECDBAE08 0 .014em,transparent .014em .075em),repeating-linear-gradient(125deg,#00000016 0 .015em,transparent .015em .11em);opacity:1}
''','foil':'''
.bui-stock{background:linear-gradient(130deg,#CFBEE91A,transparent 24%,#5B88A61A 70%,#B787B322),var(--bui-paper)}
.bui-grain{inset:.08em .08em;background:repeating-radial-gradient(ellipse at 92% 15%,transparent 0 .10em,#D7E3FF40 .11em .12em,transparent .13em .25em);opacity:.32;clip-path:polygon(0% 0%,100% 0%,100% 100%,96% 100%,96% 12%,4% 12%,4% 88%,96% 88%,96% 100%,0% 100%)}
'''}[axes['surface']]
    css += {'pressed':'''
.bui-copy .wt-w{-webkit-text-stroke:.007em var(--bui-ink);text-shadow:0 .027em 0 #FFFFFFBB,-.008em -.009em 0 #061C3340}
''','enamel':'''
.bui-copy .wt-w{-webkit-text-stroke:.010em #172D2E;text-shadow:.012em .016em 0 #E1CDA9,.035em .053em 0 #0C2224,0 -.014em 0 #FFFFFFB0}
''','silver':'''
.bui-copy .wt-w{background:linear-gradient(175deg,#FFFFFF 5%,#E5E7F1 49%,#B9B4D0 51%,#F6EEE8 82%);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;filter:drop-shadow(.015em .026em 0 #0F132B)}
'''}[axes['lettering']]
    css += {'mult':'''
.bui-copy .wt-focus{background:var(--bui-accent);border:.032em solid #A12728;border-top-color:#FFB195;border-left-color:#FFC1A5;box-shadow:0 .06em 0 #9D3030;color:#FFF8E8}
.bui-copy .wt-focus .wt-w{background:none;-webkit-text-fill-color:#FFF8E8;-webkit-text-stroke:.004em #FFF8E8;filter:none;text-shadow:.016em .024em 0 #933731}
''','chip':'''
.bui-copy .wt-focus{background:#087DB3;color:#FFFFFF;border:.047em dashed #CDE7E2;border-radius:.30em;padding:.025em .21em .04em;box-shadow:0 .065em 0 #094E66,inset 0 -.028em 0 #034E7C}
.bui-copy .wt-focus .wt-w{background:none;-webkit-text-fill-color:#FCF8DA;-webkit-text-stroke:.003em #FCF8DA;filter:none;text-shadow:.017em .032em 0 #065177}
''','sticker':'''
.bui-copy .wt-focus{background:#8447A3;border:.045em solid #F1DCE8;color:#FFF6E8;border-radius:.045em .20em .045em .20em;padding:.015em .18em .04em;box-shadow:.035em .065em 0 #391D54,inset 0 .025em 0 #C896D7}
.bui-copy .wt-focus .wt-w{background:none;-webkit-text-fill-color:#FFF4DB;-webkit-text-stroke:.004em #FFF4DB;filter:none;text-shadow:.015em .022em 0 #4A2366}
'''}[axes['keyword']]
    tracks=[]
    def move(sel,phase,start,end,before,after,ease='power2.out',**kw):
        tracks.append(dict(selector=sel,phase=phase,start=start,end=end,ease=ease,
                           **{'from':before,'to':after},**kw))
    def enter(sel,start,end,before,after,ease='power2.out',**kw):
        move(sel,'build',start,end,before,after,ease,**kw)
    def leave(sel,start,end,before,after,**kw):
        move(sel,'resolve',start,end,before,after,'power2.in',**kw)
    # Hide complete assembly at time zero; opacity is a gate, the inner actors
    # provide the themed event. Static position stays on the unanimated layout.
    enter('.bui-assembly',0,.12,{'opacity':0},{'opacity':1},'none')
    if axes['motion']=='deal':
        enter('.bui-backing',0,.57,dict(x=-19,y=16,rotation=-3,opacity=0),dict(x=0,y=0,rotation=0,opacity=1),'back.out(1.7)')
        enter('.bui-shell',.06,.67,dict(y=-22,rotation=2,scaleX=1.025,scaleY=1.09,opacity=0),dict(y=0,rotation=0,scaleX=1,scaleY=1,opacity=1),'back.out(1.7)')
        enter('.bui-rim',.16,.66,dict(scaleX=1.035,scaleY=1.16,opacity=0),dict(scaleX=1,scaleY=1,opacity=1))
        enter('.bui-copy .wt-w',.28,.9,dict(y=-9,scaleY=1.07,opacity=0),dict(y=0,scaleY=1,opacity=1),stagger=dict(amountMs=100,groupSize=3,order='center'))
        leave('.bui-shell',.30,.94,dict(x=0,y=0,rotation=0,opacity=1),dict(x=33,y=15,rotation=3,opacity=0))
        leave('.bui-backing',.39,.94,dict(x=0,y=0,rotation=0,opacity=1),dict(x=39,y=17,rotation=4,opacity=0))
    elif axes['motion']=='press':
        enter('.bui-backing',0,.54,dict(scaleX=.96,scaleY=.78,opacity=0),dict(scaleX=1,scaleY=1,opacity=1))
        enter('.bui-shell',.07,.63,dict(y=16,scaleY=1.12,opacity=0),dict(y=0,scaleY=1,opacity=1),'back.out(1.7)')
        enter('.bui-rim',.10,.69,dict(scaleY=1.24,opacity=0),dict(scaleY=1,opacity=1))
        enter('.bui-copy .wt-w',.31,.91,dict(scaleX=1.11,scaleY=1.13,y=-5,opacity=0),dict(scaleX=1,scaleY=1,y=0,opacity=1),stagger=dict(amountMs=65,groupSize=4,order='center'))
        leave('.bui-shell',.27,.94,dict(y=0,scaleY=1,opacity=1),dict(y=22,scaleY=.93,opacity=0))
        leave('.bui-backing',.38,.94,dict(x=0,opacity=1),dict(x=-34,opacity=0))
    else:
        enter('.bui-backing',0,.58,dict(x=-18,rotation=-3,opacity=0),dict(x=0,rotation=-1.3,opacity=1))
        enter('.bui-shell',.06,.70,dict(y=27,rotationX=22,opacity=0),dict(y=0,rotationX=0,opacity=1),'back.out(1.7)')
        enter('.bui-rim',.15,.76,dict(scaleX=.92,opacity=0),dict(scaleX=1,opacity=1))
        enter('.bui-copy .wt-w',.28,.90,dict(y=8,rotationX=18,opacity=0),dict(y=0,rotationX=0,opacity=1),stagger=dict(amountMs=110,groupSize=3,order='forward'))
        leave('.bui-shell',.26,.94,dict(y=0,rotationX=0,opacity=1),dict(y=25,rotationX=-24,opacity=0))
        leave('.bui-backing',.40,.94,dict(x=0,rotation=-1.3,opacity=1),dict(x=-26,rotation=-4,opacity=0))
    enter('.bui-rail-left',.24,.73,dict(x=-8,opacity=0),dict(x=0,opacity=1))
    enter('.bui-rail-right',.28,.77,dict(x=8,opacity=0),dict(x=0,opacity=1))
    enter('.bui-tab-main',.35,.92,dict(y=-12,rotation=-7,opacity=0),dict(y=0,rotation=-2 if axes['structure']=='seal' else 0,opacity=1),'back.out(1.7)')
    enter('.bui-tab-side',.43,1,dict(y=10,rotation=6,opacity=0),dict(y=0,rotation=1 if axes['structure']=='seal' else 0,opacity=1),'back.out(1.7)')
    enter('.bui-copy .wt-focus',.42,.98,dict(rotationX=45,scaleY=.8,opacity=0),dict(rotationX=0,scaleY=1,opacity=1),'back.out(1.7)',optional=True)
    enter('.bui-stitch',.15,.75,dict(scaleX=.8,opacity=0),dict(scaleX=1,opacity=.6))
    # One bounded reflection on the rim, never a moving duplicate of the text.
    move('.bui-glint','breathe',.06,.63,dict(x=-1150),dict(x=1150),'sine.inOut',durationMs=950 if axes['motion']=='sleeve' else 700)
    leave('.bui-copy .wt-focus',0,.51,dict(rotationX=0,scaleY=1,opacity=1),dict(rotationX=-48,scaleY=.85,opacity=0),optional=True)
    leave('.bui-copy .wt-w',.06,.70,dict(y=0,opacity=1),dict(y=6,opacity=0),stagger=dict(amountMs=70,groupSize=3,order='reverse'))
    leave('.bui-tab-main',0,.58,dict(y=0,opacity=1),dict(y=-13,opacity=0))
    leave('.bui-tab-side',.06,.59,dict(y=0,opacity=1),dict(y=12,opacity=0))
    leave('.bui-rail-left',.13,.61,dict(x=0,opacity=1),dict(x=-9,opacity=0))
    leave('.bui-rail-right',.16,.64,dict(x=0,opacity=1),dict(x=9,opacity=0))
    leave('.bui-stitch',.12,.60,dict(scaleX=1,opacity=.6),dict(scaleX=.8,opacity=0))
    leave('.bui-assembly',.91,.97,dict(opacity=1),dict(opacity=0))
    return dict(cueHtml=markup,cueCss=css,stageHtml='',stageCss='',
        palette=dict(primary=c['accent'],text=c['ink']),
        appearance=dict(fontFamily=c['fontFamily'],fontSize=c['fontSize'],
            fontWeight=900 if 'Heavy' in c['fontFamily'] else 500 if 'Source Han' in c['fontFamily'] else 400),
        motionSpec=dict(version=2,runtime='gsap',buildMs=c['buildMs'],resolveMs=c['resolveMs'],tracks=tracks))


def examples():
    """Local authored examples, explicitly identified; never model fallbacks."""
    return [dict(version=3,structure='seal',surface='paper',lettering='pressed',keyword='mult',motion='deal'),
        dict(version=3,structure='table',surface='felt',lettering='enamel',keyword='chip',motion='press',
             paper='#234C42',ink='#F5E7BC',accent='#C25B43',edge='#B49C71',buildMs=580,resolveMs=360),
        dict(version=3,structure='legend',surface='foil',lettering='silver',keyword='sticker',motion='sleeve',
             paper='#33334F',ink='#F1EADB',accent='#9962BE',edge='#A6B0C8',buildMs=650,resolveMs=400)]


def capability_text():
    return '''卡牌UI组件caption-components-3：PARAMETERS只写components，HTML/CSS/STAGE_CSS留空，宿主一次展开同份源码供预览/采用/导出。也可完全自创安全源码+MotionSpec；两种交付不混用。组件无角色素材，不是像素小卡插图。
components:{version:3,structure:seal效果框倍率封签|table筹码压印牌匾|legend稀有叠层封套,surface:paper纸墨|felt织物压纹|foil边缘刻纹,lettering:pressed压印|enamel厚字|silver银墨,keyword:mult红倍率签|chip蓝筹码标签|sticker稀有贴纸,motion:deal扣牌|press压合|sleeve封牌,fontSize:40..100,fontFamily:实际打包字体名,ink/paper/accent/edge:#RRGGBB,emphasis:[实际正文重点字组],buildMs:180..650,resolveMs:120..400}。枚举只写英文ID，各轴可独立组合，默认字号64。框内字、贴签和局部反光有完整三段动作；无关键词仍显示主题框。三稿须不同结构/材料/关键词/动作，不只换色。'''
