"""Three authored compositions for the September 11 brief; not a theme compiler."""
from pathlib import Path
import json,re,sys,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'examples/web-themes/balatro-20260911'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def track(selector,phase,before,after,start=0,end=1,ease='power2.out'):
    return dict(selector=selector,phase=phase,start=start,end=end,ease=ease,**{'from':before,'to':after})

def letters():
    return '<div class="lettering"><span class="glyph outer" aria-hidden="true">{{text}}</span><span class="glyph inner" aria-hidden="true">{{text}}</span><span class="glyph core" data-semantic-text="true">{{text}}</span></div>'

TYPE='''
.wt-cue{position:absolute;inset:0;pointer-events:none}
.lettering{position:absolute;display:grid;align-items:center;justify-items:center;white-space:nowrap;text-align:center;z-index:5}
.glyph{grid-area:1/1;font-family:var(--wt-font);font-size:var(--wt-size);font-weight:900;line-height:1.25;letter-spacing:1px;white-space:nowrap}
.outer{color:#f5e6c4;-webkit-text-stroke:8px #f5e6c4;text-shadow:0 8px 8px rgba(7,8,20,.3)}
.inner{color:#10152a;-webkit-text-stroke:4px #10152a}
.core{color:transparent;-webkit-text-fill-color:transparent;background:linear-gradient(180deg,#b8e3ff 8%,#51aaf0 43%,#337bd4 49%,#6fbbf7 88%);background-clip:text;-webkit-background-clip:text}
.chips-stack{position:absolute;width:72px;height:66px;z-index:6}
.chips-stack i{position:absolute;left:0;width:68px;height:22px;border-radius:50%;border:3px solid #accdf0;background:repeating-linear-gradient(90deg,#1364c0 0 13px,#cbdcee 13px 18px);box-shadow:0 5px 0 #173b73,inset 0 0 0 4px #1b5595}
.chips-stack i:nth-child(1){bottom:0}.chips-stack i:nth-child(2){bottom:15px;left:4px}.chips-stack i:nth-child(3){bottom:30px;left:-3px}
.mult-flame{position:absolute;width:110px;height:94px;background:linear-gradient(0deg,#e23e48 5%,#ee654c 55%,#f5d78a 96%);clip-path:polygon(0% 100%,12% 60%,24% 72%,33% 14%,48% 48%,64% 0%,73% 51%,88% 24%,100% 100%);transform-origin:50% 100%;z-index:1}
.foil-shimmer{position:absolute;pointer-events:none;background:repeating-linear-gradient(118deg,rgba(235,142,165,.08) 0%,rgba(121,182,227,.75) 12%,rgba(179,139,217,.62) 22%,rgba(210,216,156,.75) 31%,rgba(127,208,209,.4) 40%,rgba(235,142,165,.08) 50%)}
.crt-local{position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,transparent 0 3px,rgba(3,7,19,.2) 3px 4px);z-index:7}
.joker-mark{font:900 23px Consolas,monospace;letter-spacing:2px}
'''

def scaled(css):return re.sub(r'(-?\d+(?:\.\d+)?)px',lambda m:f'{float(m[1])/10.8:.6f}vh',css).strip()

def source(name,font,size,html,css,tracks):
    return dict(name=name,concept='Balatro：作者独立构图，红蓝计分、印刷牌面和有限机械动作。',palette=dict(primary='#398fec',text='#9ccefb'),
        appearance=dict(fontFamily=font,fontSize=size,bold=True),stageHtml='',stageCss='',cueHtml=html,cueCss=scaled(TYPE+css),
        motionSpec=dict(version=1,runtime='gsap',buildMs=420,resolveMs=280,tracks=tracks))

def candidates():
    a_html='<div class="a-machine"><div class="a-rail"><i></i><b>DRAW / LOCK</b></div><div class="a-deck"><div class="joker-mark">J<br>O<br>K<br>E<br>R</div><i></i></div><div class="a-window"><div class="card-slider"><div class="a-paper"><div class="a-corner">J<span>♦</span></div><div class="a-caption">'+letters()+'</div><div class="foil-shimmer"></div><div class="a-edition">POLYCHROME / RARE</div><div class="crt-local"></div></div><div class="a-score"><div class="chips-stack"><i></i><i></i><i></i></div><b>120</b><span>×</span><strong>4 MULT</strong><div class="mult-flame"></div></div></div></div><div class="a-claw"><i></i><b></b></div></div>'
    a_css='''
.a-machine{position:absolute;left:310px;top:810px;width:1300px;height:216px}
.a-rail{position:absolute;left:10px;right:0;bottom:4px;height:36px;background:linear-gradient(#2d3447 0 12%,#090f21 15% 65%,#63708a 67% 75%,#151d30 78%);border-radius:4px;box-shadow:0 8px 10px rgba(8,10,21,.35)}
.a-rail i{position:absolute;left:160px;right:110px;top:9px;height:6px;background:repeating-linear-gradient(90deg,#303e57 0 9px,#101625 10px 22px)}.a-rail b{position:absolute;right:6px;bottom:6px;color:#8191a8;font:11px Consolas,monospace;letter-spacing:2px}
.a-deck{position:absolute;left:0;top:21px;width:166px;height:180px;background:repeating-linear-gradient(90deg,#273c5c 0 3px,#14233b 3px 7px);border:4px solid #122037;border-radius:12px 5px 5px 12px;box-shadow:3px 3px 0 #a8a7a1,7px 5px 0 #263e60,11px 8px 0 #949997,15px 11px 0 #172942}
.a-deck .joker-mark{position:absolute;left:19px;top:13px;color:#c8d0cb;line-height:28px;font-size:19px}.a-deck i{position:absolute;left:65px;top:26px;width:74px;height:120px;border:2px solid #647383;transform:rotate(6deg);background:repeating-linear-gradient(45deg,transparent 0 8px,#405777 9px 11px,transparent 12px 20px)}
.a-window{position:absolute;left:175px;top:0;width:1100px;height:201px;overflow:hidden}.card-slider{position:absolute;inset:0}
.a-paper{position:absolute;left:7px;top:11px;width:1065px;height:157px;border:4px solid #738899;border-bottom:7px solid #0a1225;border-radius:11px;background:repeating-linear-gradient(13deg,rgba(217,205,179,.045) 0 1px,transparent 1px 4px),linear-gradient(150deg,#26344e,#14243e 55%,#11172b);box-shadow:inset 0 0 0 3px #101726,inset 0 0 0 5px #9a9583,0 8px 0 #080f1d;overflow:hidden}
.a-corner{position:absolute;left:15px;top:10px;font:900 25px Georgia,serif;color:#dc545a}.a-corner span{display:block;font-size:27px;line-height:24px}.a-caption{position:absolute;left:67px;right:28px;top:6px;height:126px}.a-caption .lettering{inset:0}
.a-paper .foil-shimmer{left:53px;top:0;width:290px;height:157px;opacity:.28;clip-path:polygon(0 0,100% 0,87% 9%,15% 9%,0 85%,50% 85%,50% 100%,0 100%)}
.a-edition{position:absolute;left:83px;bottom:5px;font:10px Consolas,monospace;letter-spacing:6px;color:#778397}
.a-score{position:absolute;right:42px;top:152px;width:255px;height:43px;background:#101526;z-index:9;border:2px solid #6e6671;border-radius:4px;box-shadow:0 4px 0 #080d17;color:#94c5ee;font:900 27px Consolas,monospace;display:flex;align-items:center;justify-content:space-evenly}
.a-score .chips-stack{left:-61px;top:-19px;transform:scale(.68)}.a-score span{font-size:22px;color:#e1d5bc}.a-score strong{color:#f27d80;font-size:23px}.a-score .mult-flame{right:2px;bottom:0;opacity:.2;height:65px;width:98px;z-index:-1}
.a-claw{position:absolute;right:6px;top:26px;width:38px;height:149px;z-index:10;border-right:10px solid #8f938f;border-top:8px solid #b9b7a3;border-bottom:8px solid #3b4b60;background:linear-gradient(90deg,transparent 58%,#273147 60%);box-shadow:4px 3px 0 #101c31}.a-claw i,.a-claw b{position:absolute;right:2px;width:23px;height:11px;background:#bd5154}.a-claw i{top:7px}.a-claw b{bottom:7px}
'''
    a_tracks=[track('.a-machine','build',{'opacity':0},{'opacity':1},0,.08),track('.card-slider','build',{'x':-1080},{'x':0},0,.82,'expo.out'),track('.a-claw','build',{'x':26},{'x':0},.82,1,'power3.in'),track('.chips-stack','build',{'y':-35},{'y':0},.65,1,'power3.in'),track('.foil-shimmer','breathe',{'x':0},{'x':670},.05,.65,'sine.inOut'),track('.mult-flame','breathe',{'scaleY':.7},{'scaleY':1},.02,.22),track('.a-claw','resolve',{'x':0},{'x':26},0,.2),track('.card-slider','resolve',{'x':0},{'x':-1080},.15,1,'power3.in'),track('.a-machine','resolve',{'opacity':1},{'opacity':0},.9,1)]
    b_html='<div class="b-scoring"><div class="b-lane"><i></i><b>HAND SCORE</b><div class="joker-mark">JOKER ×4</div></div><div class="card-slider"><div class="b-print"><div class="foil-shimmer"></div><div class="crt-local"></div></div>'+letters()+'</div><div class="b-equation"><div class="b-blue"><span>CHIPS</span><b>120</b><div class="chips-stack"><i></i><i></i><i></i></div></div><div class="b-times">×</div><div class="b-red"><div class="mult-flame"></div><span>MULT</span><strong>4</strong></div><div class="b-result"><span>=</span><b>480</b><i>HIGH CARD</i></div></div></div>'
    b_css='''
.b-scoring{position:absolute;left:305px;top:795px;width:1310px;height:239px}
.b-lane{position:absolute;left:5px;top:1px;width:195px;height:215px;background:linear-gradient(100deg,#192138,#0d172b);clip-path:polygon(0 0,82% 0,100% 18%,100% 100%,0 100%);border-left:6px solid #3d94f5;box-shadow:0 9px 0 #080b14}.b-lane i{position:absolute;left:12px;top:12px;width:45px;height:20px;background:repeating-linear-gradient(90deg,#7182a4 0 5px,transparent 5px 9px)}.b-lane b{position:absolute;left:15px;top:51px;font:900 25px Consolas,monospace;color:#a6adba;max-width:125px;line-height:27px}.b-lane .joker-mark{position:absolute;bottom:16px;left:15px;color:#ef606b;font-size:17px;letter-spacing:0}
.b-scoring .card-slider{position:absolute;left:196px;top:3px;width:1110px;height:133px}.b-print{position:absolute;left:0;top:8px;width:1100px;height:120px;background:linear-gradient(168deg,#162540 0 70%,transparent 71%);clip-path:polygon(0 0,97% 0,100% 21%,100% 71%,91% 100%,0 100%);overflow:hidden}.b-print .foil-shimmer{left:0;top:0;width:100%;height:7px;opacity:.7}.b-print .crt-local{opacity:.7}
.b-scoring .lettering{left:20px;right:12px;top:-2px;height:135px}.b-scoring .core{background:linear-gradient(180deg,#a7d7ff 5%,#4298ed 38%,#397dc7 48%,#80bef3 90%);background-clip:text;-webkit-background-clip:text}.b-scoring .outer{-webkit-text-stroke:7px #d7deeb;color:#d7deeb}
.b-equation{position:absolute;left:214px;top:134px;width:1060px;height:92px;display:flex;gap:14px;align-items:center;color:#e3e3d8;font-family:Consolas,monospace}
.b-blue{position:relative;width:325px;height:87px;background:linear-gradient(0deg,#1d5091,#277ccb);border:4px solid #112743;border-radius:7px;box-shadow:0 6px 0 #101c30,inset 0 3px 0 #8daacc}.b-blue span{position:absolute;left:20px;top:13px;font-size:19px;letter-spacing:5px;color:#bdd4ee}.b-blue b{position:absolute;left:18px;bottom:2px;font-size:43px;line-height:48px}.b-blue .chips-stack{right:30px;bottom:14px}
.b-times{font-size:64px;color:#e8d8be;text-shadow:3px 3px 0 #16213b;line-height:1}
.b-red{position:relative;width:215px;height:87px;background:linear-gradient(#ca4656,#a92e43);border:4px solid #301527;border-radius:7px;box-shadow:0 6px 0 #26121e,inset 0 3px 0 #df9a9d}.b-red span{position:absolute;left:19px;top:12px;font-size:19px;letter-spacing:4px}.b-red strong{position:absolute;right:23px;bottom:0;font-size:67px;line-height:75px;z-index:3}.b-red .mult-flame{right:4px;bottom:0;opacity:.58}
.b-result{position:relative;height:78px;flex:1;background:#131b2c;clip-path:polygon(0 0,100% 0,100% 77%,94% 100%,0 100%);border-bottom:5px solid #7285a5}.b-result span{position:absolute;left:13px;top:10px;font-size:39px;color:#7f8ba4}.b-result b{position:absolute;left:70px;top:0;font-size:52px;color:#ded6b6}.b-result i{position:absolute;left:72px;bottom:4px;font-size:12px;font-style:normal;letter-spacing:4px;color:#8693a8}
'''
    b_tracks=[track('.b-lane','build',{'y':55,'opacity':0},{'y':0,'opacity':1},0,.45),track('.card-slider','build',{'x':-90,'opacity':0},{'x':0,'opacity':1},.1,.8),track('.b-blue','build',{'y':75,'opacity':0},{'y':0,'opacity':1},.15,.65,'power3.out'),track('.chips-stack','build',{'y':-90},{'y':0},.2,.82,'power3.in'),track('.b-red','build',{'y':75,'opacity':0},{'y':0,'opacity':1},.35,.85),track('.b-times','build',{'opacity':0},{'opacity':1},.6,.85),track('.b-result','build',{'y':38,'opacity':0},{'y':0,'opacity':1},.72,1),track('.mult-flame','breathe',{'scaleY':.55},{'scaleY':1},0,.15),track('.foil-shimmer','breathe',{'x':-190},{'x':100},.05,.32),track('.b-result','breathe',{'y':4},{'y':0},0,.06),track('.b-equation','resolve',{'y':0,'opacity':1},{'y':80,'opacity':0},0,.65,'power3.in'),track('.card-slider','resolve',{'x':0,'opacity':1},{'x':-300,'opacity':0},.25,1,'power3.in'),track('.b-lane','resolve',{'y':0,'opacity':1},{'y':60,'opacity':0},.65,1)]
    c_html='<div class="c-press"><div class="c-shadow"></div><div class="c-brackets"><i></i><i></i><i></i><i></i></div><div class="card-slider"><div class="c-border"><div class="foil-shimmer"></div><div class="crt-local"></div></div><div class="c-joker"><div class="joker-mark">JOKER</div><b>RARE / 003</b></div><div class="c-type">'+letters()+'</div><div class="c-serial">POLYCHROME EDITION</div><div class="c-lower"><div class="c-chips"><div class="chips-stack"><i></i><i></i><i></i></div><b>120 CHIPS</b></div><span>×</span><div class="c-mult"><div class="mult-flame"></div><b>4 MULT</b></div></div></div><div class="c-lock"><i></i><i></i></div></div>'
    c_css='''
.c-press{position:absolute;left:330px;top:803px;width:1260px;height:222px;perspective:1100px}
.c-shadow{position:absolute;left:55px;right:55px;bottom:5px;height:24px;background:linear-gradient(90deg,transparent,rgba(14,11,30,.38) 15% 85%,transparent);border-radius:50%}
.c-brackets{position:absolute;inset:4px 0 8px}.c-brackets i{position:absolute;width:145px;height:65px;border-color:#767180;border-style:solid;border-width:0;background:linear-gradient(140deg,rgba(24,23,40,.94),rgba(30,24,40,.65));box-shadow:0 5px 0 rgba(6,10,22,.5)}.c-brackets i:nth-child(1){left:0;top:0;border-left-width:6px;border-top-width:4px;clip-path:polygon(0 0,100% 0,100% 21%,17% 21%,17% 100%,0 100%)}.c-brackets i:nth-child(2){right:0;top:0;border-right-width:6px;border-top-width:4px;clip-path:polygon(0 0,100% 0,100% 100%,83% 100%,83% 21%,0 21%)}.c-brackets i:nth-child(3){left:0;bottom:0;border-left-width:6px;border-bottom-width:4px;clip-path:polygon(0 0,17% 0,17% 79%,100% 79%,100% 100%,0 100%)}.c-brackets i:nth-child(4){right:0;bottom:0;border-right-width:6px;border-bottom-width:4px;clip-path:polygon(83% 0,100% 0,100% 100%,0 100%,0 79%,83% 79%)}
.c-press .card-slider{position:absolute;left:25px;right:25px;top:12px;height:193px;transform-style:preserve-3d}
.c-border{position:absolute;inset:0;border:2px solid #777f9d;border-radius:10px;background:linear-gradient(165deg,rgba(23,25,45,.9) 0 17%,rgba(22,24,43,.12) 17.2% 82%,rgba(16,24,43,.9) 82.2%);overflow:hidden}
.c-border .foil-shimmer{left:-420px;top:-45px;width:1770px;height:260px;opacity:.7;clip-path:polygon(0 0,100% 0,100% 18%,0 18%,0 84%,100% 84%,100% 100%,0 100%)}.c-border .crt-local{clip-path:polygon(0 0,100% 0,100% 15%,0 15%,0 88%,100% 88%,100% 100%,0 100%);opacity:.7}
.c-joker{position:absolute;left:20px;top:17px;width:133px;height:137px;background:linear-gradient(155deg,#23243d,#101c32);border:2px solid #777088;border-radius:5px;transform:rotate(-7deg);box-shadow:0 4px 0 #090e20;overflow:hidden}.c-joker::before{content:"J";position:absolute;left:37px;top:12px;font:italic 900 74px Georgia,serif;color:#808cc4;-webkit-text-stroke:1px #cdb4cf}.c-joker .joker-mark{position:absolute;bottom:19px;left:15px;font-size:17px;letter-spacing:3px;color:#c9bed9}.c-joker b{position:absolute;bottom:5px;left:21px;font:9px Consolas,monospace;color:#727caa;letter-spacing:1px}
.c-type{position:absolute;left:170px;right:32px;top:20px;height:125px}.c-type .lettering{inset:0}.c-press .glyph{letter-spacing:2px}.c-press .outer{color:#d4ccdc;-webkit-text-stroke:7px #d4ccdc}.c-press .inner{color:#1b1736;-webkit-text-stroke:4px #1b1736}.c-press .core{background:linear-gradient(115deg,#87bee8 0%,#b0a3d4 24%,#71a9e0 42%,#dfadca 59%,#8bbedc 74%,#9daddd 100%);background-clip:text;-webkit-background-clip:text}
.c-serial{position:absolute;left:192px;top:2px;font:10px Consolas,monospace;letter-spacing:7px;color:#918fa9}
.c-lower{position:absolute;left:520px;right:40px;bottom:4px;height:42px;display:flex;justify-content:flex-end;gap:21px;align-items:center;color:#bfb9cb;font:900 18px Consolas,monospace}.c-chips{position:relative;width:200px;background:#173a68;padding:8px 12px 8px 26px;border-left:3px solid #669ccb}.c-chips .chips-stack{left:-32px;bottom:-12px;transform:scale(.52)}.c-chips b{padding-left:12px;color:#97bfe2}.c-mult{position:relative;width:148px;background:#692d43;border-right:3px solid #be7281;padding:8px 10px;overflow:hidden}.c-mult .mult-flame{right:0;bottom:0;height:55px;width:72px;opacity:.27}.c-mult b{position:relative;z-index:3;color:#e3a1ae}
.c-lock{position:absolute;inset:0;pointer-events:none}.c-lock i{position:absolute;top:89px;width:20px;height:49px;background:linear-gradient(90deg,#1a2135,#838492 45%,#2c3046);border:2px solid #0e1528}.c-lock i:nth-child(1){left:7px}.c-lock i:nth-child(2){right:7px}
'''
    c_tracks=[track('.c-brackets','build',{'y':34,'opacity':0},{'y':0,'opacity':1},0,.5),track('.card-slider','build',{'y':-90,'rotationX':18,'opacity':0},{'y':0,'rotationX':0,'opacity':1},0,.88,'power3.out'),track('.c-lock','build',{'scaleX':1.08,'opacity':0},{'scaleX':1,'opacity':1},.8,1,'power3.in'),track('.card-slider','breathe',{'rotationY':-7},{'rotationY':7},.02,.88,'sine.inOut'),track('.foil-shimmer','breathe',{'x':0},{'x':360},.02,.88,'sine.inOut'),track('.mult-flame','breathe',{'scaleY':.65},{'scaleY':1},.05,.25),track('.c-lock','resolve',{'scaleX':1,'opacity':1},{'scaleX':1.08,'opacity':0},0,.2),track('.card-slider','resolve',{'y':0,'rotationX':0,'opacity':1},{'y':100,'rotationX':-16,'opacity':0},.2,1,'power3.in'),track('.c-brackets','resolve',{'y':0,'opacity':1},{'y':30,'opacity':0},.65,1)]
    definitions=[('A','抽卡锁轨','Smiley Sans, Source Han Sans SC',112,a_html,a_css,a_tracks,'diecast_drawer_with_oversized_joker','diecast and printed card stock','从牌组沿滑轨抽出，末段金属爪锁住牌边。','反向抽卡，爪先解锁，纸牌回收到牌组。'),('B','红蓝结算','ZCOOL QingKe HuangYou, Source Han Sans SC',118,b_html,b_css,b_tracks,'vertical_hand_label_over_score_equation','screen printed scoring modules','蓝筹码先落定，红倍率入位，最后结果计数锁定。','计分模块依次落入收纳槽，字幕向左抽回。'),('C','稀有压印','ZCOOL KuaiLe, Source Han Sans SC',105,c_html,c_css,c_tracks,'open_four_jaw_holographic_press','local holographic foil on open card mount','牌面倾斜落入四角压台，侧爪闭合。','侧爪松开，牌面倾向收纳口，向下机械回收。')]
    rows=[]
    for ident,name,font,size,html,css,tracks,family,material,entrance,exit in definitions:
        # Text fill and stroke layers are coplanar. Flatten them before the
        # entire card is projected, avoiding GPU z-fighting in video export.
        css=css.replace('transform-style:preserve-3d','transform-style:flat')
        # One concentrated visual revision: give A a red printed deck/score
        # relationship and C a visible angle-bound local diffraction surface.
        if ident=='A':
            css+='''.a-deck{background:repeating-linear-gradient(90deg,rgba(221,150,153,.12) 0 2px,transparent 2px 6px),linear-gradient(100deg,#72333f 0 34%,#162941 34%);border-color:#231d32}.a-deck .joker-mark{color:#ecbab7}.a-score{width:330px;background:linear-gradient(90deg,#153b67 0 47%,#712b3f 47% 100%);border-color:#736875}.a-score strong{color:#edb4b1}.a-score .mult-flame{opacity:.3;width:145px}.a-paper .crt-local{opacity:.38}.a-paper{background:repeating-linear-gradient(13deg,rgba(217,205,179,.075) 0 1px,transparent 1px 4px),linear-gradient(150deg,#26344e,#14243e 55%,#11172b)}'''
        if ident=='C':
            css+='''.c-border .foil-shimmer{opacity:.95;clip-path:polygon(0 0,100% 0,100% 18%,70% 18%,100% 38%,100% 42%,65% 18%,0 18%,0 84%,100% 84%,100% 100%,0 100%);background:repeating-linear-gradient(118deg,#834669 0%,#78b9d3 7%,#7376b5 14%,#b5b484 21%,#5088ae 28%,#834669 35%)}.c-border{border-color:#9d8aab}.c-joker{background:repeating-linear-gradient(120deg,rgba(149,168,189,.13) 0 1px,transparent 1px 4px),linear-gradient(145deg,#443046,#121d35 63%)}.c-mult{background:#8a344c}.c-chips{background:#225189}.c-press .core{background:linear-gradient(115deg,#8bc7f3 0%,#a5ace7 22%,#66a8e4 41%,#d895b7 59%,#79b2d9 78%,#b09cd3 100%);background-clip:text;-webkit-background-clip:text}'''
        source_theme=source('Balatro / '+name,font,size,html,css,tracks)
        vocabulary=['chips-stack','mult-flame','joker-mark','foil-shimmer','card-slider','crt-local']
        roles=[dict(role='base',hex='#131B2C',percent=60,use='暗牌面/计分结构；含support与shadow'),dict(role='primary',hex='#398FEC',percent=23,use='CHIPS蓝与字芯主色'),dict(role='contrast',hex='#D04B5C',percent=12,use='MULT红与牌角印刷'),dict(role='highlight',hex='#E8D9C0',percent=5,use='外缘/纸纤维/局部foil'),dict(role='support',hex='#6E7892',percent=0,use='归入base的压铸边缘与印刷小字'),dict(role='shadow',hex='#080E20',percent=0,use='归入base；低透明接触阴影')]
        rows.append(dict(id=ident,name=name,composition_family=family,art_direction_contract=dict(theme='Balatro',vocabulary=vocabulary,metaphor=name,foreground='梯度字芯/深内圈/浅外圈',midground=material,background='暗接触阴影；簇外透明',asset_disclosure='使用排印JOKER字标；图像端点404，没有生成或伪造Joker插画'),design_spec=dict(theme='Balatro',vocabulary=vocabulary,metaphor=name,font=font,composition=family,layer_order=['contact-shadow','mechanical-or-score-structure','caption','scoring-accents','local-print-texture']),ColorRole=roles,MaterialContract=dict(material=material,selectors=['.foil-shimmer','.crt-local'],implementation='纸纤维/金属断面/有限局部foil；所有纹理限在牌面或分数区域'),MotionContract=dict(entrance=entrance,hold='独立局部foil与倍率火焰；一次有限动作；字形不变形',exit=exit),generated_source=source_theme))
    return rows

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--prompt',type=Path,default=OUT/'raw-user-prompt.txt')
    parser.add_argument('--negative-image',type=Path,action='append',default=[])
    args=parser.parse_args()
    from twobyteasr.caption_creative_pipeline import ThemeLedger,accept_authored_set,digest
    from twobyteasr.web_theme import theme_archive_html
    raw_path=args.prompt
    raw=raw_path.read_text('utf8');write(OUT/'raw-user-prompt.txt',raw)
    refs=[(ROOT/'assets/theme-references/balatro-crt-mult.html','accepted-history-source'),(ROOT/'assets/theme-references/balatro-crt-mult.png','accepted-history-pixels'),(ROOT/'tmp/caption-audit-20260910/visual/game.png','current-media')]
    refs.extend((path,'current-negative-pixels') for path in args.negative_image)
    positives=[dict(name='旧版 Balatro CRT Mult',acceptance='用户在本轮明确列作较满意的历史参考',path='assets/theme-references/balatro-crt-mult.html',sha256=digest(refs[0][0].read_bytes()))]
    negative=[dict(name=x,user_rating=3,accepted=False) for x in ['琥珀舷刃','潮汐压印舷签','压印票根-温玉琥珀']]
    ledger=ThemeLedger(OUT,raw,references=refs,positive=positives,negative=negative)
    ledger.value['unresolved_references']=[dict(name='theme(2).html',reason='未定位到可核验原文件，不以其他近名文件冒充')]
    ledger.value['provider_inputs']=[dict(provider='Astra',mode='current assistant authors source',pixels_inspected=['用户两张负面截图','旧版A-game-1500.png'],main_design_requests=0),dict(provider='imagegen',purpose='Joker插画资产',attempts=1,result='HTTP404; no generated asset')]
    ledger.value['provider_inputs'].append(dict(provider='Agy',attempts=0,pixels_attached=False,pixels_seen_confirmed=False,result='Automatic approval review rejected external image transmission; no request executed'))
    ledger.value['revision']=dict(count=1,limit=1,changes=['A红色印刷牌组与红蓝倍率模块','C局部衍射层与牌角印刷材质'],original='tmp/balatro-initial-review')
    rows=candidates();payload={'candidates':rows}
    ledger.raw_response(json.dumps(payload,ensure_ascii=False,indent=2),'Astra','current assistant')
    suggestion=accept_authored_set(payload,ledger,'Astra','current assistant')
    for row in rows:
        folder=OUT/row['id'];write(folder/'contracts.json',{k:v for k,v in row.items() if k!='generated_source'})
        theme=next(c for c in ledger.value['candidates'] if c['id']==row['id'])['generated_source']
        write(folder/'theme.json',theme);write(folder/'theme.html',theme_archive_html(theme,sample_text='啊感觉他就是你看',duration_seconds=3,auto_replay=False))
        write(folder/'DESIGN.md',f"# {row['name']}\n\n原始要求 SHA256：`{digest(raw)}`。Balatro核心语汇及图层用途见同目录contracts.json。\n\n构图：{row['composition_family']}。材质：{row['MaterialContract']['material']}。\n\n入场：{row['MotionContract']['entrance']} 保持：{row['MotionContract']['hold']} 退场：{row['MotionContract']['exit']}\n\nColorRole为设计面积目标，尚未声称像素测量通过；support/shadow归入base。仅JOKER排印标记，没有冒充插画。\n")
    write(OUT/'suggestion.json',dict(brief=suggestion.brief,concepts=suggestion.concepts,quality=suggestion.quality,selected_concept_id=''))
    prefs_path=ROOT/'docs/design/caption-preferences.json';prefs=json.loads(prefs_path.read_text('utf8'))
    for row in prefs['trial_runs']:row.update(user_rating=3,accepted=False,user_selected=False,rating_source='用户2026-09-11原始要求；三稿全部负面')
    prefs['status']='previous_candidates_rejected';prefs['accepted_history']=positives
    prefs['negative_rules'][-1]='真实Joker插画使用已有或生成图像资产；禁止难辨随手SVG冒充。用户当前要求高于house style。'
    write(prefs_path,prefs)
    print(OUT)

if __name__=='__main__':main()
