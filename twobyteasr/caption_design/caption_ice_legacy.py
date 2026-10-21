"""Ice material vocabulary, expanded once into editable HTML/SVG/MotionSpec.

These are optical illustrations (facets, trapped frost, reflection), not a
video-background shader. All animation remains on the existing cue clock.
"""
import html

OPTIONS={'geometry':('shelf','facet'),'frost':('rime','snow'),
         'lettering':('carved','clear'),'motion':('crystallize','lock')}


def compose(value):
    from .caption_components import normalize, COLORS
    extra=set(value)-{'version',*OPTIONS,*COLORS,'fontSize','fontFamily','emphasis','buildMs','resolveMs'}
    if extra:raise ValueError('不支持的冰材质参数：'+','.join(sorted(extra)))
    axes={key:value.get(key,choices[0]) for key,choices in OPTIONS.items()}
    for key,choices in OPTIONS.items():
        if axes[key] not in choices:raise ValueError('不支持冰材质 '+key+': '+str(axes[key]))
    params=dict(version=1,ink='#EDFAFF',paper='#27627B',accent='#ADE9F4',edge='#0D3548',fontSize=64,
                buildMs=620,resolveMs=380,fontFamily='Source Han Sans SC Heavy')
    params.update({k:v for k,v in value.items() if k not in OPTIONS and k!='version'})
    c=normalize(params)
    # Facets run around a quiet reading well; no noisy crack crosses a glyph.
    facets='''<svg class="ice-optics" viewBox="0 0 1200 210" preserveAspectRatio="none" aria-hidden="true">
<defs><linearGradient id="ice-face" x1="0" y1="0" x2="0.8" y2="1"><stop offset="0" stop-color="#efffff" stop-opacity=".75"/><stop offset=".18" stop-color="#81bfd6" stop-opacity=".45"/><stop offset=".6" stop-color="#15455e" stop-opacity=".85"/><stop offset="1" stop-color="#51a2bf" stop-opacity=".6"/></linearGradient>
<linearGradient id="ice-bevel" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#f2ffff"/><stop offset=".45" stop-color="#9cdde9" stop-opacity=".9"/><stop offset="1" stop-color="#06374e"/></linearGradient>
<filter id="ice-grain"><feTurbulence type="fractalNoise" baseFrequency=".07 .24" numOctaves="3" seed="7"/><feColorMatrix type="saturate" values="0"/><feComposite in2="SourceGraphic" operator="in"/></filter></defs>
<path d="M30 17 L210 8 337 17 570 6 704 17 910 7 1167 19 1190 48 1181 174 1154 194 808 184 590 198 362 187 26 193 8 164 13 47Z" fill="url(#ice-face)"/>
<path d="M13 47L30 17 210 8 337 17 570 6 704 17 910 7 1167 19 1190 48 1151 41 922 28 703 34 568 25 338 33 211 25 42 39Z" fill="#ddffff" fill-opacity=".8"/>
<path d="M8 164L26 193 362 187 590 198 808 184 1154 194 1181 174 1147 171 809 162 590 181 360 169 42 175Z" fill="url(#ice-bevel)"/>
<path d="M13 47L42 39 31 87 42 175 8 164ZM1190 48L1151 41 1165 98 1147 171 1181 174Z" fill="#a5efff" fill-opacity=".68"/>
<path d="M30 17L62 47 170 34 112 18ZM337 17L394 48 490 23 570 6ZM704 17L813 41 910 7ZM1018 13L1100 56 1167 19ZM26 193L118 161 240 182ZM362 187L463 153 590 198ZM808 184L932 156 1154 194Z" fill="#d6ffff" fill-opacity=".3"/>
<path d="M44 47L196 36 335 44 568 35 702 44 915 35 1147 48M47 164L356 158 590 172 808 153 1143 164" fill="none" stroke="#e2ffff" stroke-opacity=".5" stroke-width="2"/>
<path class="ice-crack" d="M125 23L138 40 125 56 144 63M138 40L171 46M415 19L430 35 417 48 448 57M430 35L461 28M1030 24L1008 42 1020 58 993 69M1008 42L975 46M257 181L276 163 267 149M276 163L310 154M824 180L800 160 816 151M800 160L774 154" fill="none" stroke="#d9ffff" stroke-opacity=".8" stroke-width="1.5" stroke-dasharray="240"/>
<path d="M39 25L211 15 337 25 570 14 704 25 910 15 1160 27" fill="none" stroke="#ffffff" stroke-width="7" stroke-opacity=".85"/>
<path d="M39 25L211 15 337 25 570 14 704 25 910 15 1160 27" fill="none" stroke="#f4ffff" stroke-width="15" stroke-opacity=".6" filter="url(#ice-grain)"/>
</svg>'''
    markup=('<div class="ice-layout"><div class="ice-body">'
        '<div class="ice-mist" aria-hidden="true"></div>'
        '<div class="ice-depth" aria-hidden="true"></div>'
        '<div class="ice-left" aria-hidden="true"></div><div class="ice-right" aria-hidden="true"></div>'
        '<div class="ice-core" aria-hidden="true">'+facets+
        '<div class="ice-caustic"></div><div class="ice-rime"></div></div>'
        '<div class="ice-snow" aria-hidden="true"><svg viewBox="0 0 1200 20" preserveAspectRatio="none"><path d="M0 10L96 3 228 7 300 1 444 6 564 0 744 8 900 2 1080 7 1176 4 1200 14 1092 13 900 10 744 15 576 11 432 14 300 10 216 13 96 10 0 19Z" fill="#e9ffff"/></svg></div>'
        '<div class="ice-copy" data-semantic-text="true" data-emphasis="'+html.escape('|'.join(c['emphasis']),quote=True)+'">{{text}}</div>'
        '<div class="ice-shard ice-shard-a" aria-hidden="true"></div>'
        '<div class="ice-shard ice-shard-b" aria-hidden="true"></div>'
        '<div class="ice-shard ice-shard-c" aria-hidden="true"></div>'
        '<div class="ice-glint" aria-hidden="true"></div>'
        '</div></div>')
    css='''
.ice-layout{position:absolute;left:50%;bottom:11%;transform:translateX(-50%);width:max-content;max-width:86%;font-size:var(--wt-size);font-family:var(--wt-font);line-height:1.22;}
.ice-body{position:relative;isolation:isolate;padding:.59em .9em .63em;min-width:3.5em;max-width:100%;}
.ice-depth,.ice-left,.ice-right,.ice-core{position:absolute;inset:0;pointer-events:none;}
.ice-depth{inset:.16em -.035em -.14em;clip-path:polygon(2% 8%,16% 2%,48% 1%,76% 3%,98% 7%,100% 24%,99% 84%,97% 98%,66% 94%,49% 100%,28% 95%,2% 98%,0% 82%,0% 24%);background:linear-gradient(178deg,#67bad1 2%,#0c3b50 18%,#082838 72%,#5b9caf 90%,#092d3b 100%);box-shadow:inset 0 -.06em .03em #001723;}
.ice-left,.ice-right{inset:.02em .04em 0;background:linear-gradient(120deg,#c2f3f4aa,#225971dd 40%,#133b51f5 75%,#6ebacebb);}
.ice-left{clip-path:polygon(2% 2%,53% 0%,48% 42%,53% 78%,48% 99%,2% 97%,0% 80%,0% 23%);}
.ice-right{clip-path:polygon(53% 0%,98% 3%,100% 23%,99% 81%,98% 96%,48% 99%,53% 78%,48% 42%);}
.ice-core{overflow:hidden;clip-path:polygon(2.5% 8%,17.5% 4%,28% 8%,47.5% 3%,59% 8%,76% 4%,97% 9%,99% 23%,98% 83%,96% 93%,67% 88%,49% 95%,30% 89%,2% 93%,.7% 78%,1% 22%);}
.ice-optics{position:absolute;inset:0;width:100%;height:100%;}
.ice-caustic{position:absolute;inset:12% -45%;background:linear-gradient(112deg,transparent 24%,#c6ffff00 38%,#ccffff24 40%,#ddffff09 44%,transparent 50%,#7dd7ed12 59%,transparent 63%);mix-blend-mode:screen;}
.ice-rime{position:absolute;inset:9% 2% 9%;border:.045em solid #eaffff77;box-shadow:inset 0 .075em .065em #ffffff99,inset 0 -.04em .07em #a7f6ff77;opacity:.7;clip-path:polygon(0% 0%,100% 0%,100% 100%,0% 100%,0% 83%,98% 84%,98% 15%,2% 14%,2% 83%,0% 83%);}
.ice-snow{position:absolute;left:3%;right:3%;top:3%;height:.21em;filter:drop-shadow(0 .035em .018em #072f45aa);}.ice-snow svg{display:block;width:100%;height:100%;}
.ice-copy{position:relative;z-index:2;font-family:var(--wt-font);font-size:1em;font-weight:900;line-height:1.22;letter-spacing:.015em;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--ice-ink);text-align:center;paint-order:stroke fill;-webkit-text-stroke:.018em #10384c;text-shadow:0 .025em 0 #8ed5e8,0 .055em 0 #12364a,0 .08em .045em #032131cc;}
.ice-copy [data-caption-text]{background:linear-gradient(176deg,#fff 12%,var(--ice-ink) 45%,#a2d7e8 66%,#f1ffff 69%,#d5f3fa 87%);background-clip:text;-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.ice-copy .wt-focus{color:#fff;}
.ice-mist{position:absolute;left:1%;right:1%;top:1%;bottom:-15%;background:radial-gradient(ellipse at 23% 85%,#a2e8ee28,transparent 48%),radial-gradient(ellipse at 77% 15%,#ddffff28,transparent 52%);filter:blur(.11em);pointer-events:none;}
.ice-shard{position:absolute;z-index:3;width:.28em;height:.34em;background:linear-gradient(130deg,#f5ffffdd,#a4e7ef99 43%,#2b738daa 45%,#cefaffcc);clip-path:polygon(20% 0%,100% 18%,77% 100%,0% 61%);}
.ice-shard-a{left:1.2%;top:42%;transform:rotate(-18deg);}.ice-shard-b{right:1.4%;top:21%;width:.36em;height:.28em;}.ice-shard-c{right:14%;bottom:-.13em;width:.22em;height:.25em;}
.ice-glint{position:absolute;left:21%;top:.015em;width:.52em;height:.09em;background:radial-gradient(ellipse,#fff 5%,#e9ffffaa 30%,transparent 75%);mix-blend-mode:screen;}
'''
    css+=f'.ice-body{{--ice-ink:{c["ink"]};--ice-paper:{c["paper"]};--ice-accent:{c["accent"]};--ice-edge:{c["edge"]};}}'
    css+='.ice-left,.ice-right{background:linear-gradient(124deg,var(--ice-accent),var(--ice-paper) 29%,var(--ice-edge) 72%,var(--ice-paper));}'
    if axes['geometry']=='facet':css+='.ice-body{padding:.63em 1em .69em;}.ice-depth,.ice-core{clip-path:polygon(0% 24%,5% 0%,93% 3%,100% 28%,97% 90%,91% 100%,5% 95%,0% 76%);}'
    if axes['frost']=='snow':css+='.ice-snow{height:.34em;top:-.01em;}.ice-rime{opacity:.95;}'
    if axes['lettering']=='clear':css+='.ice-copy [data-caption-text]{background:linear-gradient(#fff 18%,#e2fbff 62%,#99c9dc 63%,#dbf4fc);background-clip:text;-webkit-background-clip:text;}.ice-copy{text-shadow:0 .035em 0 #0e3047,0 .065em 0 #73c8dc;}'
    tracks=[]
    def move(selector,phase,start,end,a,b,ease='power2.out',**kw):
        tracks.append(dict(selector=selector,phase=phase,start=start,end=end,ease=ease,**{'from':a,'to':b},**kw))
    opened='inset(0% 0% 0% 0%)'
    move('.ice-body','build',0,.035,dict(opacity=0),dict(opacity=1),'none')
    move('.ice-body','resolve',.95,1,dict(opacity=1),dict(opacity=0),'none')
    move('.ice-depth','build',0,.6,dict(opacity=0,scaleX=.86,y=5),dict(opacity=1,scaleX=1,y=0),'expo.out')
    spread=20 if axes['motion']=='crystallize' else 36
    move('.ice-left','build',.08,.68,dict(x=-spread,opacity=0),dict(x=0,opacity=1),'power3.out')
    move('.ice-right','build',.12,.73,dict(x=spread,opacity=0),dict(x=0,opacity=1),'power3.out')
    move('.ice-core','build',.14,.83,dict(clipPath='inset(0% 48% 0% 48%)'),dict(clipPath=opened),'power2.out')
    move('.ice-snow','build',.1,.82,dict(clipPath='inset(0% 100% 0% 0%)'),dict(clipPath=opened))
    move('.ice-crack','build',.16,.8,dict(strokeDashoffset=240),dict(strokeDashoffset=0))
    move('.ice-copy','build',.3,.91,dict(opacity=0,y=4,clipPath='inset(0% 0% 100% 0%)'),dict(opacity=1,y=0,clipPath=opened))
    for i,sel in enumerate(('.ice-shard-a','.ice-shard-b','.ice-shard-c')):
        move(sel,'build',.18+i*.1,.67+i*.1,dict(y=-13,opacity=0),dict(y=0,opacity=1),'power3.out')
        move(sel,'resolve',.20+i*.04,.9,dict(y=0,opacity=1),dict(y=15+i*4,opacity=0),'power2.in')
    move('.ice-mist','build',0,.8,dict(opacity=0,scaleX=.6),dict(opacity=.65,scaleX=1))
    move('.ice-caustic','breathe',0,1,dict(xPercent=-15),dict(xPercent=15),'sine.inOut',durationMs=3200,sustain=True,yoyo=True)
    move('.ice-glint','breathe',0,1,dict(opacity=.2),dict(opacity=.85),'sine.inOut',durationMs=2300,sustain=True,yoyo=True)
    move('.ice-crack','resolve',0,.46,dict(opacity=.65),dict(opacity=1),'power2.in')
    move('.ice-copy','resolve',.10,.70,dict(opacity=1,clipPath=opened),dict(opacity=0,clipPath='inset(0% 0% 100% 0%)'),'power2.in')
    move('.ice-snow','resolve',.12,.8,dict(clipPath=opened),dict(clipPath='inset(0% 0% 0% 100%)'),'power2.in')
    move('.ice-core','resolve',.28,.88,dict(opacity=1),dict(opacity=0),'power2.in')
    move('.ice-left','resolve',.34,.92,dict(x=0,y=0,opacity=1),dict(x=-24,y=8,opacity=0),'power2.in')
    move('.ice-right','resolve',.36,.94,dict(x=0,y=0,opacity=1),dict(x=24,y=-5,opacity=0),'power2.in')
    move('.ice-depth','resolve',.42,.94,dict(opacity=1,scaleX=1,y=0),dict(opacity=0,scaleX=.93,y=5),'power2.in')
    move('.ice-mist','resolve',.12,.96,dict(opacity=.65,scaleX=1),dict(opacity=0,scaleX=1.13))
    return dict(cueHtml=markup,cueCss=css,stageHtml='',stageCss='',
        appearance=dict(fontFamily=c['fontFamily'],fontSize=c['fontSize'],fontWeight=900 if 'Heavy' in c['fontFamily'] else 500),
        palette=dict(primary=c['accent'],text=c['ink']),
        motionSpec=dict(version=2,runtime='gsap',buildMs=c['buildMs'],resolveMs=c['resolveMs'],tracks=tracks))


def capability_text():
    return '''冰材质组件 version:6：PARAMETERS.components；HTML/CSS/STAGE_CSS留空，由宿主一次展开普通可编辑源码。
components:{version:6,geometry:shelf|facet,frost:rime|snow,lettering:carved|clear,motion:crystallize|lock,fontFamily:打包字体,fontSize:40..100,ink/paper/accent/edge:#RRGGBB,emphasis:[真实重点字组],buildMs:180..650,resolveMs:120..400}。
geometry是分层冰架/大切面，frost是薄霜/积雪压边，lettering是实心冰刻/透明亮字，motion是结晶拼合/冻结锁定；这些轴独立组合。内含厚边、SVG切面和裂缝、霜化、局部screen冷光、分层结晶与退散；不添加人物。也可自创安全HTML/CSS/MotionSpec，组件不是能力上限；不得混用。'''
