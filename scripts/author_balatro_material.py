"""Three authored object animations, consumed by the unchanged shared runtime."""
from pathlib import Path
import argparse,json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'examples/web-themes/balatro-object-motion-20260911'


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def tr(selector,phase,before,after,start=0,end=1,ease='power2.out',**extra):
    return dict(selector=selector,phase=phase,start=start,end=end,ease=ease,**{'from':before,'to':after},**extra)


def glyph(name,semantic=False):
    role='data-semantic-text="true"' if semantic else 'aria-hidden="true"'
    return f'<span class="glyph {name}" {role}>{{{{text}}}}</span>'


# Share layout and font rules only. Each object owns its texture and motion.
COMMON='''
.wt-cue{position:absolute;inset:0;pointer-events:none}.object{position:absolute;transform-style:flat}
.lettering{position:absolute;display:grid;place-items:center;white-space:nowrap;text-align:center}
.glyph{grid-area:1/1;position:relative;display:block;font:400 var(--wt-size)/1.16 var(--wt-font);font-synthesis:none;white-space:nowrap;letter-spacing:0}
.micro{font:400 12px var(--wt-font);letter-spacing:3px}
'''


def paper():
    html='''<div class="object a-dealer"><div class="a-deck"><div class="a-deck-card a-deck-low"></div><div class="a-deck-card a-deck-top"></div></div><div class="a-carriage"><div class="a-card-back"><div class="a-back-medallion"><i></i></div></div><div class="a-card-front"><div class="a-paper-fibres"></div><div class="a-rule"></div><div class="a-corner">J<span>♦</span></div><div class="a-corner a-corner-end">J<span>♦</span></div><div class="a-impression"><div class="lettering">'''
    html+=glyph('a-ink ink',True)+glyph('a-register-red')+glyph('a-register-warm')+glyph('a-ink-fibres')
    html+='''</div></div><div class="a-colophon micro">LETTERPRESS <span>01 · JOKER</span></div><div class="a-registration"><i></i><i></i><i></i></div></div></div></div>'''
    css='''
.a-dealer{left:345px;top:792px;width:1230px;height:216px}
.a-deck{position:absolute;left:14px;top:19px;right:0;height:189px}
.a-deck-card{position:absolute;inset:0;border:7px solid #dec8a5;border-radius:13px;background:repeating-linear-gradient(38deg,transparent 0px 8px,rgba(219,175,141,.28) 8px 9px,transparent 9px 17px),#693332;box-shadow:inset 0 0 0 2px #885044,0 4px 0 #bba387,0 7px 0 #654d3d,0 12px 12px rgba(31,21,12,.24)}
.a-deck-low{transform:rotate(1.35deg);left:-12px;right:9px;top:2px}.a-deck-top{transform:rotate(-1.25deg);left:-17px;right:14px;top:-3px}
.a-carriage{position:absolute;left:0;right:0;top:0;height:194px;perspective:1500px}
.a-card-front,.a-card-back{position:absolute;inset:0;border-radius:13px;transform-origin:50% 48%;will-change:transform,opacity}
.a-card-front{background:linear-gradient(117deg,#f2e2c2,#e8cfaa 74%,#ddc196);border:3px solid #cbb193;box-shadow:inset 0 1px 0 #fff0d4,0 3px 0 #f4e2bf,0 6px 0 #c6ab85,0 9px 0 #69503d,0 13px 18px rgba(38,23,13,.24);overflow:hidden}
.a-paper-fibres{position:absolute;inset:0;background:repeating-linear-gradient(21deg,transparent 0px 3px,rgba(99,63,38,.085) 3px 4px,transparent 4px 9px),repeating-linear-gradient(103deg,transparent 0px 8px,rgba(255,250,223,.21) 8px 9px,transparent 9px 15px);opacity:.48}
.a-rule{position:absolute;inset:12px;border:1px solid #a37259;border-radius:7px;box-shadow:inset 0 0 0 4px #ead5b0,inset 0 0 0 5px #c09171}
.a-corner{position:absolute;left:23px;top:22px;color:#803e36;font:400 32px/30px var(--wt-font)}.a-corner span{display:block;font-size:26px}.a-corner-end{left:auto;top:auto;right:23px;bottom:20px;transform:rotate(180deg)}
.a-impression{position:absolute;left:91px;right:91px;top:24px;height:122px;transform-origin:50% 63%}.a-impression .lettering{inset:0}
.a-ink{z-index:2;color:#793c35;text-shadow:0 1px 0 #eedbb7,0 -1px 0 #ad7961}
.a-register-red{z-index:3;color:#9d433c;opacity:0}.a-register-warm{z-index:1;color:#b99566;opacity:0}
.a-ink-fibres{z-index:4;color:transparent;-webkit-text-fill-color:transparent;background-clip:text;-webkit-background-clip:text;background-image:repeating-linear-gradient(17deg,transparent 0px 8px,rgba(240,216,171,.65) 8px 9px,transparent 9px 17px),repeating-linear-gradient(103deg,transparent 0px 13px,rgba(100,47,34,.7) 13px 14px);opacity:.14}
.a-colophon{position:absolute;left:102px;right:103px;bottom:20px;color:#6f4833;font-size:10px;letter-spacing:4px}.a-colophon span{float:right;font-size:10px;letter-spacing:2px}
.a-registration{position:absolute;left:50%;bottom:22px;display:flex;gap:5px}.a-registration i{width:5px;height:5px;background:#9b7252;border-radius:50%;opacity:.65}
.a-card-back{background:repeating-linear-gradient(38deg,transparent 0px 8px,rgba(219,175,141,.3) 8px 9px,transparent 9px 17px),#713632;border:8px solid #e3cfac;box-shadow:inset 0 0 0 3px #a4775b,0 4px 0 #b99b79,0 7px 0 #6c4c38;overflow:hidden}
.a-back-medallion{position:absolute;left:43%;right:43%;top:25px;bottom:25px;border:1px solid #bd9972;transform:rotate(8deg)}.a-back-medallion i{position:absolute;inset:12px;border:1px solid #bd9972;transform:rotate(-16deg)}
'''
    tracks=[
        tr('.a-dealer','build',{'opacity':0},{'opacity':1},0,.06),
        tr('.a-carriage','build',{'x':-54,'y':-25,'rotation':-2.8},{'x':0,'y':0,'rotation':0},0,.60,'power2.out'),
        # Two half turns stay inside the existing +/-80 degree safety range.
        # Swap faces only at the edge; do not dissolve print through the back.
        tr('.a-card-back','build',{'rotationX':0,'scaleY':1},{'rotationX':80,'scaleY':.04},0,.15,'power1.in'),
        tr('.a-card-back','build',{'opacity':1},{'opacity':0},.145,.15,'none'),
        tr('.a-card-front','build',{'opacity':0},{'opacity':1},.15,.155,'none'),
        tr('.a-card-front','build',{'rotationX':-80,'scaleY':.04},{'rotationX':0,'scaleY':1},.15,.50,'power2.out'),
        tr('.a-impression','build',{'scaleY':.975,'y':1.8},{'scaleY':1,'y':0},.15,1,'power1.out'),
        tr('.a-ink','build',{'opacity':0},{'opacity':1},.15,1,'none'),
        tr('.a-register-red','build',{'x':1.6,'y':.8,'opacity':.34},{'x':0,'y':0,'opacity':0},.15,.96,'power1.out'),
        tr('.a-register-warm','build',{'x':-1.2,'y':-.7,'opacity':.20},{'x':0,'y':0,'opacity':0},.15,1,'power1.out'),
        tr('.a-ink-fibres','breathe',{'backgroundPositionX':0},{'backgroundPositionX':4},0,1,'sine.inOut'),
        tr('.a-paper-fibres','breathe',{'opacity':.48},{'opacity':.54},0,1,'sine.inOut'),
        tr('.a-card-front','resolve',{'rotationX':0,'scaleY':1},{'rotationX':-80,'scaleY':.04},0,.49,'power1.in'),
        tr('.a-card-front','resolve',{'opacity':1},{'opacity':0},.49,.50,'none'),
        tr('.a-card-back','resolve',{'opacity':0},{'opacity':1},.50,.51,'none'),
        tr('.a-card-back','resolve',{'rotationX':80,'scaleY':.04},{'rotationX':0,'scaleY':1},.50,.91,'power2.out'),
        tr('.a-carriage','resolve',{'x':0,'y':0,'rotation':0},{'x':14,'y':19,'rotation':-1.25},.48,1,'power2.out'),
        tr('.a-dealer','resolve',{'opacity':1},{'opacity':0},.94,1,'none'),
    ]
    return ('A','翻牌印字',html,css,tracks,'#793c35',99,600,420)


def mint():
    html='''<div class="object b-press"><div class="b-bed"><div class="b-bed-edge"></div></div><div class="b-platen"><div class="b-milling"></div><div class="b-letter-bed"><div class="lettering">'''
    html+=glyph('b-relief-shadow')+glyph('b-gold ink',True)+glyph('b-letter-sheen-a b-slow-reflection')+glyph('b-letter-sheen-b')
    html+='''</div></div><div class="b-seat"></div><div class="b-fastener bolt-a"></div><div class="b-fastener bolt-b"></div></div>
<div class="b-ram"><div class="b-ram-face"></div><span class="b-mark micro">MINT / JOKER</span><span class="b-mark b-mark-right micro">DIE 01</span><div class="b-guide guide-a"></div><div class="b-guide guide-b"></div></div>
<div class="b-coin"><div class="b-rim"><div class="b-die"><div class="b-emblem"><span class="b-dollar">$</span><span class="b-dollar-light b-slow-reflection" aria-hidden="true">$</span></div><span class="b-legend micro">LUCKY</span><div class="b-hallmark hallmark-a"></div><div class="b-hallmark hallmark-b"></div></div><div class="b-rim-specular"></div><i class="b-edge-glint glint-a"></i><i class="b-edge-glint glint-b"></i></div></div>
<div class="b-contact-ring"></div></div>'''
    css='''
.b-press{left:338px;top:786px;width:1248px;height:229px}
.b-bed{position:absolute;left:106px;right:0;top:175px;height:47px;background:linear-gradient(#604527 0px 6px,#322c22 6px 30px,#151710 30px);clip-path:polygon(0% 0%,98% 0%,100% 30%,100% 76%,98% 100%,2% 100%,0% 70%);box-shadow:0 6px 0 #17120e}
.b-bed-edge{position:absolute;left:29px;right:18px;top:14px;height:2px;background:linear-gradient(90deg,#705536,#b49659 58%,#3b3324)}
.b-platen{position:absolute;left:97px;right:11px;top:36px;height:155px;border:3px solid #805e36;border-radius:9px 6px 10px 14px;background:linear-gradient(112deg,#27261f,#30291d 48%,#201e16);box-shadow:inset 0 2px 0 #b5955e,inset 0 -4px 0 #14130d,inset 0 -5px 0 #68482b,0 7px 0 #503b23,0 11px 0 #19160f;overflow:hidden}
.b-milling{position:absolute;inset:0;opacity:.38;background:repeating-linear-gradient(114deg,transparent 0px 11px,rgba(180,144,82,.09) 11px 12px,transparent 12px 25px)}
.b-letter-bed{position:absolute;left:129px;right:33px;top:19px;height:117px;border-top:1px solid #14150f;border-bottom:1px solid #634c30;transform-origin:50% 52%}.b-letter-bed .lettering{inset:0}
.b-gold{z-index:2;color:#d9b36d;text-shadow:0 -1px 0 #f1d395,0 2px 0 #624024,1px 4px 0 #100f0b}
.b-relief-shadow{z-index:1;color:#100e0a;text-shadow:0 2px 0 #0d0c08;opacity:.9}
.b-letter-sheen-a,.b-letter-sheen-b{z-index:3;color:transparent;-webkit-text-fill-color:transparent;background-clip:text;-webkit-background-clip:text;pointer-events:none;background-repeat:no-repeat}
.b-letter-sheen-a{background-image:linear-gradient(108deg,transparent 0% 31%,rgba(255,235,184,.07) 38%,rgba(255,236,190,.61) 51%,rgba(240,204,145,.14) 66%,transparent 75%);background-size:1400px 180px;opacity:.46}
.b-letter-sheen-b{background-image:linear-gradient(73deg,transparent 0% 39%,rgba(252,222,160,.48) 48%,rgba(255,240,207,.17) 57%,transparent 70%);background-size:1100px 180px;opacity:.22}
.b-seat{position:absolute;left:22px;top:32px;width:77px;height:92px;border:3px solid #0d100b;border-radius:50%;box-shadow:1px 0 0 #a17b46;opacity:.75}
.b-fastener{position:absolute;right:15px;width:9px;height:9px;border:2px solid #231c10;border-radius:50%;background:linear-gradient(135deg,#b39151 43%,#322714 43% 57%,#967440 57%);box-shadow:0 1px 0 #c0a16a}.bolt-a{top:13px}.bolt-b{bottom:13px}
.b-ram{position:absolute;left:94px;right:2px;top:2px;height:44px;transform-origin:50% 100%}
.b-ram-face{position:absolute;inset:0;border:2px solid #937445;background:linear-gradient(#a88950 0px 2px,#5a482d 2px 8px,#2c2c23 8px 33px,#10160f 33px);clip-path:polygon(1.5% 0%,98% 0%,100% 35%,100% 100%,0% 100%,0% 35%);box-shadow:0 3px 0 #a1814b}
.b-mark{position:absolute;left:141px;top:16px;color:#b19968;font-size:10px;letter-spacing:3px}.b-mark-right{left:auto;right:35px;font-size:10px}
.b-guide{position:absolute;top:33px;width:19px;height:33px;background:linear-gradient(90deg,#131811,#967346 23%,#392d1b 48%,#b08d50 71%,#14140d);border:2px solid #322d1e;z-index:-1}.guide-a{left:15px}.guide-b{right:14px}
.b-coin{position:absolute;left:0;top:1px;width:218px;height:218px;transform-origin:50% 50%;will-change:transform}
.b-rim{position:absolute;inset:0;border-radius:50%;border:5px solid #987038;background:repeating-conic-gradient(#bb8f46 0deg 4deg,#edd095 4deg 7deg,#967036 7deg 10deg);box-shadow:0 4px 0 #806035,0 8px 0 #41301b,0 12px 0 #1b1a11,0 15px 16px rgba(17,12,7,.32);overflow:hidden}
.b-die{position:absolute;inset:14px;border-radius:50%;border:3px solid #e2c083;background:radial-gradient(ellipse at 33% 22%,#dbb975,#bd914d 53%,#a07639);box-shadow:inset 0 0 0 3px #987039,inset 0 0 0 5px #d3ab61,inset 0 7px 10px rgba(57,35,9,.15)}
.b-emblem{position:absolute;inset:0;display:grid;place-items:center}
.b-dollar,.b-dollar-light{grid-area:1/1;display:block;font:400 105px/1 var(--wt-font);font-synthesis:none;transform:translate(3.5px,3px)}
.b-dollar{color:#63431f;text-shadow:0 -1px 0 #402b13,1px 2px 0 #f1d397}
.b-dollar-light{color:transparent;-webkit-text-fill-color:transparent;background-clip:text;-webkit-background-clip:text;background-image:linear-gradient(112deg,transparent 35%,rgba(255,235,187,.48) 50%,transparent 74%);background-size:330px 210px;background-repeat:no-repeat;opacity:.6}
.b-legend{position:absolute;left:35px;right:35px;bottom:15px;text-align:center;font-size:9px;letter-spacing:4px;color:#37270f}
.b-hallmark{position:absolute;top:50%;width:5px;height:5px;background:#79572c;transform:rotate(45deg)}.hallmark-a{left:18px}.hallmark-b{right:18px}
.b-rim-specular{position:absolute;inset:1px;border:4px solid transparent;border-top-color:#ffe4a2;border-left-color:#c4a063;border-radius:50%;opacity:.48;transform-origin:50% 50%}
.b-edge-glint{position:absolute;background:#ffe9ab;opacity:0;clip-path:polygon(46% 0%,54% 0%,59% 40%,100% 47%,100% 53%,59% 60%,54% 100%,46% 100%,41% 60%,0% 53%,0% 47%,41% 40%)}
.glint-a{right:27px;top:22px;width:17px;height:23px}.glint-b{left:12px;bottom:39px;width:12px;height:16px}
.b-contact-ring{position:absolute;left:-2px;top:-1px;width:222px;height:222px;border:2px solid #f8d98d;border-radius:50%;opacity:0;pointer-events:none}
'''
    tracks=[
        tr('.b-press','build',{'opacity':0},{'opacity':1},0,.07),
        tr('.b-ram','build',{'y':-23},{'y':0},.40,.70,'power3.in'),
        tr('.b-platen','build',{'y':13},{'y':0},.10,.70,'power2.out'),
        tr('.b-coin','build',{'x':24,'y':-73,'rotationY':-78,'rotation':-145},{'x':0,'y':0,'rotationY':0,'rotation':0},0,.47,'power2.out'),
        tr('.b-contact-ring','build',{'opacity':0},{'opacity':.72},.43,.48,'power1.out'),
        tr('.b-contact-ring','build',{'opacity':.72},{'opacity':0},.48,.70,'power2.out'),
        tr('.b-letter-bed','build',{'scaleY':.975,'y':2.4},{'scaleY':1,'y':0},.42,1,'power2.out'),
        tr('.b-gold','build',{'opacity':0},{'opacity':1},.42,1,'power1.inOut'),
        tr('.b-relief-shadow','build',{'y':-.6,'opacity':0},{'y':2.5,'opacity':.9},.43,.96,'power2.inOut'),
        # Two slow, differently angled lobes, no repeat/yoyo. The first also
        # crosses the raised dollar; the rim highlight is a separate arc.
        tr('.b-slow-reflection','breathe',{'backgroundPositionX':-470},{'backgroundPositionX':430},.02,.91,'sine.inOut'),
        tr('.b-letter-sheen-b','breathe',{'backgroundPositionX':670},{'backgroundPositionX':-260},.31,1,'sine.inOut'),
        tr('.b-rim-specular','breathe',{'rotation':-31,'opacity':.28},{'rotation':38,'opacity':.58},0,1,'sine.inOut'),
        tr('.glint-a','breathe',{'opacity':0},{'opacity':.66},.17,.23,'power2.out'),
        tr('.glint-a','breathe',{'opacity':.66},{'opacity':0},.23,.34,'power1.in'),
        tr('.glint-b','breathe',{'opacity':0},{'opacity':.46},.76,.81,'power1.out'),
        tr('.glint-b','breathe',{'opacity':.46},{'opacity':0},.81,.88,'power1.in'),
        tr('.b-ram','resolve',{'y':0},{'y':-26},0,.40,'power2.out'),
        tr('.b-coin','resolve',{'x':0,'y':0,'rotationY':0,'rotation':0},{'x':-58,'y':-53,'rotationY':78,'rotation':122},.27,1,'power2.in'),
        tr('.b-relief-shadow','resolve',{'y':2.5,'opacity':.9},{'y':-.6,'opacity':0},.35,.88,'power1.in'),
        tr('.b-letter-bed','resolve',{'y':0,'opacity':1},{'y':7,'opacity':0},.41,.96,'power2.in'),
        tr('.b-platen','resolve',{'y':0},{'y':13},.55,1,'power2.in'),
        tr('.b-press','resolve',{'opacity':1},{'opacity':0},.87,1,'power1.in'),
    ]
    return ('B','金币压印',html,css,tracks,'#d9b36d',99,600,420)


def television():
    html='''<div class="object c-tv"><div class="c-depth"></div><div class="c-cabinet"><div class="c-bezel"><div class="c-glass"><div class="c-osd micro"><span>JOKER TV</span><span>16 BIT</span></div><div class="c-screen-type"><div class="lettering">'''
    html+=glyph('c-phosphor ink',True)+glyph('c-raster')+glyph('c-phosphor-pass')
    html+=glyph('c-lock-top')+glyph('c-lock-middle')+glyph('c-lock-bottom')+glyph('c-interference')
    html+='''</div></div><div class="c-noise"></div><div class="c-glass-raster"></div><div class="c-rolling-band"></div><div class="c-reflection"></div><div class="c-signal"><i></i><span class="micro">CH 01</span></div></div><div class="c-powerline"></div><div class="c-afterglow"></div></div><div class="c-controls"><div class="c-knob knob-one"><i></i></div><div class="c-knob knob-two"><i></i></div><div class="c-led"></div><div class="c-vent"></div></div></div></div>'''
    css='''
.c-tv{left:334px;top:773px;width:1252px;height:254px}
.c-depth{position:absolute;inset:12px -8px -10px 12px;background:linear-gradient(90deg,#1c201b,#141915 80%,#30362a);border-radius:53px 28px 32px 48px;box-shadow:0 7px 15px rgba(7,11,8,.4)}
.c-cabinet{position:absolute;inset:0;background:repeating-linear-gradient(17deg,rgba(141,147,109,.035) 0px 1px,transparent 1px 4px),linear-gradient(110deg,#65684d,#3c4535 42%,#4d533d 83%,#343e31);border:3px solid #858a68;border-bottom:8px solid #202b22;border-right:8px solid #263024;border-radius:46px 26px 30px 46px;box-shadow:inset 0 2px 0 #a0a081,inset 0 -3px 0 #535c41}
.c-bezel{position:absolute;left:19px;right:122px;top:15px;bottom:16px;background:#101b15;border:6px solid #28352a;border-radius:55px / 38px;box-shadow:0 2px 0 #85866a,inset 0 4px 0 #090f0b;overflow:hidden}
.c-glass{position:absolute;inset:5px 7px;border-radius:48px / 30px;background:radial-gradient(ellipse at 50% 30%,#28352b,#15241c 60%,#0c1811 100%);overflow:hidden;transform-origin:50% 50%;isolation:isolate;will-change:transform}
.c-osd{position:absolute;left:32px;right:35px;top:16px;color:#7c996e;font-size:12px;letter-spacing:3px;display:flex;justify-content:space-between}.c-osd span:last-child{color:#a8af77}
.c-screen-type{position:absolute;left:32px;right:32px;top:48px;bottom:33px}.c-screen-type .lettering{inset:0}
.c-phosphor{z-index:2;color:#c4df9e;text-shadow:1px 0 0 #babb72,-1px 0 0 #678e73,0 0 2px rgba(190,217,141,.3)}
.c-raster,.c-phosphor-pass{z-index:3;color:transparent;-webkit-text-fill-color:transparent;background-clip:text;-webkit-background-clip:text}
.c-raster{background-image:repeating-linear-gradient(0deg,transparent 0px 3px,rgba(9,33,15,.78) 3px 5px),repeating-linear-gradient(90deg,transparent 0px 3px,rgba(11,40,17,.3) 3px 4px);opacity:.24}
.c-phosphor-pass{background-image:linear-gradient(0deg,transparent 15%,rgba(236,244,183,.18) 36%,rgba(230,241,175,.8) 49%,rgba(191,221,146,.19) 66%,transparent 81%);background-size:1200px 150px;background-repeat:no-repeat;opacity:.44}
.c-lock-top,.c-lock-middle,.c-lock-bottom,.c-interference{z-index:4;opacity:0}
.c-lock-top{color:#d2e5b1;clip-path:inset(12% 54% 64% 1%)}
.c-lock-middle{color:#b6b784;clip-path:polygon(36% 37%,93% 37%,93% 49%,62% 49%,62% 57%,36% 57%)}
.c-lock-bottom{color:#90b9a0;clip-path:inset(73% 18% 10% 17%)}
.c-interference{color:#94b29f;clip-path:inset(57% 7% 36% 61%);transform:translateX(2px)}
.c-noise{position:absolute;inset:-20px;background-image:radial-gradient(circle at 7px 3px,rgba(202,134,124,.7) 0px 1px,transparent 1px),radial-gradient(circle at 11px 9px,rgba(150,190,166,.7) 0px 1px,transparent 1px),repeating-conic-gradient(rgba(207,231,167,.34) 0% 25%,transparent 0% 50%);background-size:17px 13px,23px 19px,5px 3px;opacity:.055}
.c-glass-raster{position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,transparent 0px 3px,rgba(8,12,9,.09) 3px 4px)}
.c-rolling-band{position:absolute;left:0;right:0;top:0;height:15px;background:linear-gradient(transparent,rgba(157,185,135,.075),transparent);opacity:.5}
.c-reflection{position:absolute;inset:0;background:linear-gradient(164deg,rgba(181,194,144,.12),transparent 24% 72%,rgba(185,201,150,.035) 86%,transparent);border-radius:50%;opacity:.8}
.c-signal{position:absolute;left:36px;bottom:7px;right:35px;height:18px;border-bottom:2px solid #354b31}.c-signal i{position:absolute;left:0;top:4px;width:8px;height:3px;background:#748966}.c-signal span{position:absolute;right:0;top:1px;font-size:9px;color:#899a77;letter-spacing:2px}
.c-controls{position:absolute;right:15px;top:25px;width:80px;height:205px}
.c-knob{position:absolute;left:7px;width:59px;height:59px;border-radius:50%;border:4px solid #232d21;background:radial-gradient(circle at 35% 28%,#788160,#535f42 49%,#34422f 73%,#1d291d 76%,#75805d 80%,#36432e 89%);box-shadow:0 4px 0 #1b251b,0 5px 0 #777c57,inset 0 0 0 6px #636f4d}
.c-knob i{position:absolute;left:20px;top:10px;width:17px;height:20px;background:#b5b992;clip-path:polygon(70% 0%,96% 0%,30% 100%,4% 100%)}.knob-one{top:0}.knob-two{top:79px}.knob-two i{clip-path:polygon(4% 0%,30% 0%,96% 100%,70% 100%)}
.c-led{position:absolute;left:8px;bottom:12px;width:9px;height:9px;background:#d4b36c;border-radius:50%;box-shadow:0 0 3px rgba(203,179,87,.4)}.c-vent{position:absolute;left:27px;right:0;bottom:4px;height:28px;background:repeating-linear-gradient(0deg,#1e2b20 0px 2px,transparent 2px 6px)}
.c-powerline{position:absolute;left:3%;right:3%;top:50%;height:3px;background:#dce8af;opacity:0;box-shadow:0 0 5px rgba(193,217,147,.4);will-change:opacity}
.c-afterglow{position:absolute;left:50%;top:50%;width:4px;height:3px;background:#f0eabd;border-radius:50%;opacity:0;box-shadow:0 0 4px rgba(222,224,150,.5)}
'''
    tracks=[
        tr('.c-tv','build',{'opacity':0},{'opacity':1},0,.08),
        tr('.c-powerline','build',{'opacity':0},{'opacity':1},0,.09,'power1.out'),
        tr('.c-powerline','build',{'clipPath':'inset(0% 49.8% 0% 49.8%)'},{'clipPath':'inset(0% 0% 0% 0%)'},.035,.28,'power2.out'),
        tr('.c-powerline','build',{'opacity':1},{'opacity':0},.28,.53,'power1.in'),
        tr('.c-glass','build',{'scaleX':.18},{'scaleX':1},.06,.29,'power2.out'),
        tr('.c-glass','build',{'scaleY':.009},{'scaleY':1},.19,.65,'power2.out'),
        tr('.c-screen-type','build',{'opacity':0},{'opacity':1},.27,.98,'steps(9)'),
        tr('.c-lock-top','build',{'x':15,'y':-1,'opacity':.95},{'x':0,'y':0,'opacity':0},.26,.75,'steps(7)'),
        tr('.c-lock-middle','build',{'x':-11,'y':2,'opacity':.72},{'x':0,'y':0,'opacity':0},.39,.94,'steps(6)'),
        tr('.c-lock-bottom','build',{'x':8,'y':-2,'opacity':.90},{'x':0,'y':0,'opacity':0},.32,.85,'steps(8)'),
        tr('.c-phosphor-pass','breathe',{'backgroundPositionY':-125},{'backgroundPositionY':126},0,1,'none',repeat=1),
        tr('.c-raster','breathe',{'backgroundPositionY':0},{'backgroundPositionY':5},0,1,'steps(5)',repeat=2),
        tr('.c-noise','breathe',{'backgroundPositionX':0,'backgroundPositionY':0},{'backgroundPositionX':23,'backgroundPositionY':19},0,1,'steps(16)',repeat=2),
        tr('.c-rolling-band','breathe',{'y':-15},{'y':210},0,1,'none'),
        tr('.c-interference','breathe',{'opacity':0},{'opacity':.24},.59,.615,'steps(2)'),
        tr('.c-interference','breathe',{'opacity':.24},{'opacity':0},.615,.65,'steps(3)'),
        tr('.c-lock-middle','resolve',{'x':0,'opacity':0},{'x':-8,'opacity':.34},0,.27,'steps(3)'),
        tr('.c-glass','resolve',{'scaleY':1},{'scaleY':.008},.08,.64,'power2.in'),
        # Once the explicit shutdown line takes over, stop painting the
        # compressed screen. A 1.5px textured strip rasterizes differently
        # after a reverse seek and otherwise survives behind the final dot.
        tr('.c-glass','resolve',{'opacity':1},{'opacity':0},.58,.64,'none'),
        tr('.c-powerline','resolve',{'opacity':0},{'opacity':1},.42,.64,'power1.out'),
        tr('.c-powerline','resolve',{'clipPath':'inset(0% 0% 0% 0%)'},{'clipPath':'inset(0% 49.8% 0% 49.8%)'},.64,.89,'power2.in'),
        tr('.c-powerline','resolve',{'opacity':1},{'opacity':0},.89,.94,'none'),
        # The 30fps frame at 2966.7ms must actually contain the afterglow;
        # starting it at 2979ms would exist only between encoded frames.
        tr('.c-afterglow','resolve',{'opacity':0},{'opacity':.85},.84,.89,'none'),
        tr('.c-afterglow','resolve',{'opacity':.85},{'opacity':0},.89,1,'power1.out'),
        tr('.c-tv','resolve',{'opacity':1},{'opacity':0},.97,1,'none'),
    ]
    return ('C','显像管',html,css,tracks,'#c4df9e',99,600,420)


def definitions():
    return [paper(),mint(),television()]


def build_theme(definition):
    from twobyteasr.web_theme import WebThemeDocument
    ident,name,html,css,tracks,color,size,build,resolve=definition
    css=re.sub(r'(-?\d+(?:\.\d+)?)px',lambda m:f'{float(m[1])/10.8:.6f}vh',COMMON+css)
    return WebThemeDocument.from_dict(dict(name='Balatro · '+name+' II',
        concept='用户逐项返修：物件、材质与文字因果；独立作者源，同一paused GSAP。',
        palette=dict(primary=color,text=color),appearance=dict(fontFamily='Cubic 11, Source Han Sans SC',fontSize=size,bold=False),
        stageHtml='',stageCss='',cueHtml=html,cueCss=css,
        motionSpec=dict(version=1,runtime='gsap',buildMs=build,resolveMs=resolve,tracks=tracks))).to_dict()


def main():
    from twobyteasr.web_theme import theme_archive_html
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=OUT);a=p.parse_args()
    for ident,name,html,css,tracks,color,size,build,resolve in definitions():
        theme=build_theme((ident,name,html,css,tracks,color,size,build,resolve))
        folder=a.output/ident;write(folder/'theme.json',theme)
        write(folder/'theme.html',theme_archive_html(theme,sample_text='啊感觉他就是你看',duration_seconds=3,auto_replay=False))
        surface=dict(theme);surface['cueCss']+=' .lettering{visibility:hidden}'
        write(folder/'surface.html',theme_archive_html(surface,sample_text='啊感觉他就是你看',duration_seconds=3,auto_replay=False))
        write(folder/'timing.json',dict(buildMs=build,resolveMs=resolve,holdMs=3000-build-resolve,tracks=tracks))
        print(ident,name,len(tracks),flush=True)


if __name__=='__main__':main()
