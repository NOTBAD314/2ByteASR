"""Art direction contract and small component previews before theme generation."""
import re

SCORE_LABELS={'readability':'字幕可读性','hierarchy':'构图层级','theme_relevance':'主题关联性',
    'typography':'字体选择','material':'材质质感','color_restraint':'色彩克制','motion':'动画节奏',
    'originality':'原创辨识度','subject_clearance':'主体避让','sticker_restraint':'避免廉价贴纸感'}
AESTHETIC_REVIEW_SYSTEM='''你是动态排版审查员，依据实际渲染截图与时点检查，不凭代码臆测，不给数字评分。
返回JSON {"passed":布尔值,"checks":{readability,hierarchy,theme_relevance,typography,material,color_restraint,motion,originality,subject_clearance,sticker_restraint},"defects":[具体缺陷],"rationale":"依据"}。
每项必须是 {"passed":布尔值,"evidence":"指明截图/时点/可见结构的具体依据"}。
任何关键项失败必须拒收，不能以平均分抵消；证据不足也不能通过。这只是审查意见，不等于用户验收。
普通黑条、廉价霓虹、emoji、无关飘饰、同构换色、主体遮挡、默认跑到画面中上部、无真实主题动作直接拒收。
框、字、角色组成完整主题作品；主要阅读段保留实际承托框体，除非用户明确无框。检查原框和角色是否保留、新材质可辨且协调、已认可动作是否损失，以及持续细节和出入场。去框、变小、提高文字占比或减少动作不得算改善。意见关联实际截图和时间；只有静帧不能证明完整动画恢复。'''

def validate_aesthetic_scores(critique):
    scores=critique.get('scores',{})
    if any(isinstance(scores.get(k),bool) or not isinstance(scores.get(k),(int,float)) or not 0<=scores[k]<=10 for k in SCORE_LABELS):
        raise ValueError('审美复核必须包含十项0至10分评分')
    low=[SCORE_LABELS[k] for k in SCORE_LABELS if scores[k]<7]
    if low:
        critique['passed']=False
        if not critique.get('defects'):critique['defects']=['需定向修复：'+'、'.join(low)]
    return critique


def validate_visual_checks(critique):
    checks=critique.get('checks',{})
    for key in SCORE_LABELS:
        row=checks.get(key,{})
        if not isinstance(row,dict) or not isinstance(row.get('passed'),bool) or len(str(row.get('evidence','')).strip())<6:
            raise ValueError('视觉审查必须逐项提供可见证据：'+SCORE_LABELS[key])
    failed=[SCORE_LABELS[k]+'：'+checks[k]['evidence'] for k in SCORE_LABELS if not checks[k]['passed']]
    critique['passed']=bool(critique.get('passed')) and not failed and not critique.get('defects')
    if failed:critique['defects']=list(dict.fromkeys([*critique.get('defects',[]),*failed]))
    critique.pop('scores',None)
    return critique

V2_CONCEPT_RULES='''
本轮使用 ArtDirectionSpec v2，workflow="hero-gsap"。每个concept给design对象，字段必须为：
metaphor（一句话视觉隐喻）、silhouette（稳定帧整体轮廓）、hierarchy、font（所选字体及角色）、
colors（3至5项，每项hex和role）、material、rhythm（重量与Build/Breathe/Resolve节奏）、
forbidden、content_relevance（为什么和内容相关）。所有文本简短具体。
这份设计先保存为DESIGN.md，再各自生成完整静态HTML英雄帧，不能使用组件预设或固定图标列表。
框体、文字、角色共同构图，阅读段保留能与游戏背景分离的实体主题底板。不要为了物件数量或infinite数量堆装饰。
三个方案在构图、字体处理、符号、材质、三段动作都应明显不同。
只返回严格JSON，无HTML/CSS，无文件路径、用户名或工程信息。'''

ART_DIRECTION_SYSTEM='''你是动态排版美术总监。理解字幕、用户brief和参考帧后，只输出JSON对象{"brief":{...}}。
brief字段必须为style,mood,scope,anchor,foreground,midground,background,materials,palette_ratio,typography,
entrance,hold,exit,forbidden_patterns,performance_level,transparent,allow_vignette。
文字稳定可读，保留完整主题框与角色关系。透明外画布、底部安全区，框面具有可辨材质和明暗层次；按主题配色，动作统一且阅读段保留适量持续细节。
不写HTML/CSS，不输出候选，不臆造参考帧没有出现的内容。各文本字段不超过100字。'''

V2_OPTIONS_SYSTEM='''根据给定brief，为字幕设计三个明显不同的视觉方向。只输出JSON对象
{"schema_version":2,"workflow":"hero-gsap","concepts":[恰好三项]}。每项字段：id,name,subject,composition,palette,materials,
motion（entrance/hold/exit）,signature_elements（1至3项）,risks（数组）,estimated_performance（low/medium/high）,design。
构图、字体、主符号、材质和三段动作必须明显不同，禁止同构换色。'''+V2_CONCEPT_RULES

V2_HERO_SYSTEM='''你是静态动态排版设计师。只实现输入DESIGN.md对应的一张英雄帧。
输出严格JSON主题对象{name,concept,palette:{primary,secondary,background,accent,text},appearance:{fontFamily,fontSize,bold,color,strokeColor,strokeWidth},stageHtml:"",stageCss:"",cueHtml,cueCss,notes}。
concept点名实际语义.class。正文{{text}}或{{words}}，宿主提供.wt-cue，不能重复嵌套。
静态CSS，禁止animation/transition/@keyframes、脚本、事件、外部资源和随机数。允许清楚的几何主题结构，不得用难辨的inline SVG/CSS/emoji冒充角色。
.wt-cue{position:absolute;inset:0;width:100%;height:100%}，内部class布局，不改变subtitle-placement。
字体从输入可用字体选一个，思源/微软雅黑只回退；CSS用var(--wt-font)、var(--wt-size)，尺寸calc(N * var(--wt-u))，1u=12px。
主题与字形形成共同轮廓，不能贴纸加普通字幕；必要笔画完整，任意字幕可替换，长句必须显示前适配并保持单行。
默认透明底部安全区x5%..95% y75%..95%，字幕第一层级。3–5个有职责的颜色，材质优先于光效。
画布透明与局部字幕底板独立；不能因“透明”删除局部底板。需求中的文字渐变、多层边缘、框体、材质和颜色职责必须落实到可见CSS图层，不能仅填palette元数据。
角色资产不可用时直接省略角色，完整制作文字/底板/材质/构图，不留空的角色占位区，不因此停止本阶段。
HTML/CSS合计≤6500字。notes含DESIGN_V2_HERO_GSAP。此时不写动画。'''

V2_CODE_SYSTEM='''你是动态排版设计师，在已选静态hero_theme上添加MotionSpec，不重做已选轮廓。
输出完整的十个分节：
===NAME===主题名
===CONCEPT===主视觉符号及辅助细节，点名实际.class，不要堆数量
===PALETTE===primary=#RRGGBB secondary=#RRGGBB background=#RRGGBB accent=#RRGGBB text=#RRGGBB
===APPEARANCE===保留已选英雄帧的字体与外观，用逐行key=value
===STAGE_HTML===透明舞台的HTML
===STAGE_CSS===舞台CSS
===CUE_HTML===正文使用{{text}}或{{words}}，不要将{{words}}包入.wt-w
===CUE_CSS===完整CSS
===MOTION_SPEC===严格JSON {"version":1,"runtime":"gsap","buildMs":320,"resolveMs":180,"tracks":[...]}
===NOTES===DESIGN_V2_HERO_GSAP；一行说明

要求：主题框、文字和角色组成完整作品；阅读段保留有实际承托和背景分离的框体，明确无框需求才例外。材质、文字和动作属于同一语言，配色随主题。
禁止普通黑色圆角条、大面积霓虹、emoji、随机漂浮装饰、厚描边厚阴影彩虹渐变叠加。
入场必须有主题语义；保持只让局部细节微动，正文稳定；出场干净。不能只缩放淡入。
默认透明底部安全区x5%..95% y75%..95%。只有scope=fullscreen允许外围舞台。
.wt-cue{position:absolute;inset:0;width:100%;height:100%}；内部作者节点负责布局和动画。
宿主subtitle-placement只负责用户位置。不得选择或修改subtitle-placement及宿主transform。
stageHtml与stageCss必须为空，所有图层在cueHtml中。CSS只画静态，无animation/transition/@keyframes。
GSAP paused timeline是唯一动作权威，Studio与Remotion仅传入时间。注册、seek和结尾硬清除由宿主统一执行。
每个track为{selector:".语义class",phase:"build|breathe|resolve",start:0,end:1,ease:"power2.out",from:{x:0,opacity:0},to:{x:12,opacity:1}}。
start/end为该阶段0–1归一化位置，end>start。from/to显式同组属性：opacity,x,y,xPercent,yPercent,rotation,scaleX,scaleY,clipPath(inset/polygon),transformOrigin。
ease只用none、power1/2/3.in/out/inOut、sine.in/out/inOut、expo.in/out。同元素同属性时间不得重叠。
selector限内部class及first/last/nth-child(n)，不选宿主，不用伪元素；需要动作的细节用真实节点。
最多32条有限动作，阅读阶段最多8条有协调关系的局部细节动作，repeat有界。build不超过cue20%、resolve不超过15%，至少65%文字稳定可读。
按主题语义入场—完整形态与持续细节—呼应退出，不全句持续抖动、不无限循环、不随机雪花，不丢失已认可动作。
字体消费var(--wt-font)、var(--wt-size)，尺寸用calc(N * var(--wt-u))，1u在1080高时为12px。
允许内联SVG，禁止外部资源、脚本、事件属性、@import。长句必须显示前适配并保持单行，吉祥物不可抢字或遮字。
总HTML/CSS控制在12000字以内；不要重述未选方案或输出历史日志。'''


def validate_art_direction(payload):
    if payload.get('schema_version')!=2:raise ValueError('ArtDirectionSpec需要schema_version=2')
    rows=payload.get('concepts',[])
    for row in rows:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',str(row.get('id',''))):raise ValueError('方向id必须为安全的英文短标识')
        if 'design' in row:
            design=row['design']
            if isinstance(design,dict) and design.get('visual_contract_version') == 3:
                from .theme_design_spec_v3 import validate_design_spec
                validate_design_spec(design)
            for key in ('metaphor','silhouette','hierarchy','font','colors','material','rhythm','forbidden','content_relevance'):
                if not isinstance(design,dict) or not design.get(key):raise ValueError('DESIGN缺少'+key)
            if not isinstance(design['colors'],list) or not 3<=len(design['colors'])<=5:raise ValueError('DESIGN需要3–5个有职责的颜色')
            for color in design['colors']:
                if not isinstance(color,dict) or not re.fullmatch('#[0-9a-fA-F]{6}',str(color.get('hex',''))) or not color.get('role'):raise ValueError('DESIGN颜色需要hex和role')
            continue
        spec=row.get('preview_spec',{})
        for key,allowed in {'layout':('type-led','emblem-left','framed-right'),
            'symbol':('polar-bear','goggles','ice-shard','star-seal','orbit'),
            'font_treatment':('editorial','rounded','condensed'),
            'material':('paper','frosted-glass','brushed-metal')}.items():
            if spec.get(key) not in allowed:raise ValueError('preview_spec.'+key+'不受支持')
        for key in ('foreground','secondary','accent'):
            if not re.fullmatch('#[0-9a-fA-F]{6}',str(spec.get(key,''))):raise ValueError('预览配色需要#RRGGBB')
    if any('design' in row for row in rows):
        if not all('design' in row for row in rows):raise ValueError('三个方向都必须先有DESIGN')
        for key in ('silhouette','font','metaphor'):
            if len({str(row['design'][key]) for row in rows})!=3:raise ValueError('三个方向的'+key+'必须不同')
        return payload
    for key in ('layout','font_treatment','material'):
        if len({row['preview_spec'][key] for row in rows})!=3:raise ValueError('三个方向的'+key+'必须不同')
    return payload


SYMBOLS={
 'polar-bear':'<circle cx="24" cy="23" r="13"/><circle cx="76" cy="23" r="13"/><path d="M10 45 Q10 20 50 20 Q90 20 90 50 L86 82 Q50 99 14 82Z"/><path class="mark" d="M20 45 Q50 32 80 45 L74 62 Q50 70 26 62Z"/><ellipse class="ink" cx="50" cy="78" rx="6" ry="4"/>',
 'goggles':'<path d="M5 28 Q50 13 95 28 L86 73 Q62 85 50 65 Q38 85 14 73Z"/><path class="mark" d="M14 35 L43 30 L41 61 L20 63Z M57 30 L86 35 L80 63 L59 61Z"/>',
 'ice-shard':'<path d="M48 2 L80 35 L92 82 L53 96 L8 72 L19 28Z"/><path class="mark" d="M48 2 L53 96 L19 28Z"/>',
 'star-seal':'<path d="M50 4 L62 28 L90 22 L78 49 L96 71 L68 73 L50 97 L34 74 L5 71 L23 48 L10 23 L38 28Z"/><circle class="mark" cx="50" cy="50" r="20"/>',
 'orbit':'<circle cx="50" cy="50" r="28"/><ellipse class="orbit" cx="50" cy="50" rx="46" ry="15"/><circle class="mark" cx="85" cy="30" r="9"/>',
}


def preview_theme(concept):
    from .web_theme import WebThemeDocument
    if concept.get('hero_theme'):return WebThemeDocument.from_dict(concept['hero_theme']).to_dict()
    if concept.get('design'):raise ValueError('该方向的静态英雄帧尚未完成，请重试本阶段')
    p=concept['preview_spec'];kind=p['layout'];material=p['material']
    svg='<svg class="direction-symbol" viewBox="0 0 100 100">'+SYMBOLS[p['symbol']]+'</svg>'
    html=f'<div class="direction-cluster {kind}">{svg}<div class="direction-type">{{{{text}}}}</div><i class="direction-detail"></i></div>'
    font={'editorial':'"Source Han Sans SC", "Microsoft YaHei UI", sans-serif','rounded':'"Microsoft YaHei UI", sans-serif','condensed':'"Source Han Sans SC", "Microsoft YaHei UI", sans-serif'}[p['font_treatment']]
    texture={'paper':'linear-gradient(118deg,#F4F0E8,#C9CDD0)','frosted-glass':'linear-gradient(130deg,#E8F3F3,#87ADB7)','brushed-metal':'repeating-linear-gradient(0deg,#536774 0px,#8093A0 1px,#405565 3px)'}[material]
    css=f'''.wt-cue{{position:absolute;inset:0;width:100%;height:100%}}
.direction-cluster{{position:absolute;left:50%;bottom:9%;transform:translateX(-50%);display:flex;align-items:center;gap:calc(1.3*var(--wt-u));width:max-content;max-width:82%;color:{p['foreground']}}}
.direction-type{{font-family:var(--wt-font);font-size:var(--wt-size);font-weight:900;line-height:1.05;letter-spacing:.02em;text-align:center;paint-order:stroke fill;-webkit-text-stroke:calc(.10*var(--wt-u)) #253540;text-shadow:0 calc(.12*var(--wt-u)) 0 #17262C}}
.direction-symbol{{width:calc(7*var(--wt-u));height:calc(7*var(--wt-u));flex-shrink:0;fill:{p['secondary']};stroke:#36505B;stroke-width:1.5}}
.direction-symbol .mark{{fill:{p['accent']};stroke:none}}.direction-symbol .ink{{fill:#1C3542;stroke:none}}.direction-symbol .orbit{{fill:none;stroke:{p['accent']};stroke-width:4}}
.direction-detail{{position:absolute;left:0;right:0;bottom:calc(-1.2*var(--wt-u));height:calc(.28*var(--wt-u));background:{texture}}}
.type-led .direction-symbol{{position:absolute;right:calc(-2*var(--wt-u));top:calc(-3.5*var(--wt-u));width:calc(3.5*var(--wt-u));height:calc(3.5*var(--wt-u));transform:rotate(16deg)}}
.type-led .direction-type{{font-size:calc(var(--wt-size)*1.12);font-weight:950;letter-spacing:.08em}}
.type-led .direction-detail{{left:12%;right:12%;height:calc(.12*var(--wt-u))}}
.emblem-left .direction-type{{text-align:left;max-width:calc(43*var(--wt-u));letter-spacing:.03em}}
.emblem-left .direction-detail{{left:calc(8*var(--wt-u));right:10%;background:{p['accent']}}}
.framed-right{{padding:calc(1.4*var(--wt-u)) calc(6.5*var(--wt-u)) calc(1.4*var(--wt-u)) calc(2*var(--wt-u));border-left:calc(.2*var(--wt-u)) solid {p['accent']};background:{texture};clip-path:polygon(0 0,95% 0,100% 28%,100% 100%,0 100%)}}
.framed-right .direction-type{{font-size:calc(var(--wt-size)*.9);letter-spacing:-.04em;color:#142C37;-webkit-text-stroke:0;text-shadow:none}}
.framed-right .direction-symbol{{position:absolute;right:calc(.8*var(--wt-u));width:calc(4.5*var(--wt-u));height:calc(4.5*var(--wt-u))}}
.framed-right .direction-detail{{display:none}}'''
    # The component card must honor the director's explicit transparent/no-bar
    # decision. Materials belong to the symbol, not an invented wide plate.
    if re.search('无底栏|无框',concept.get('composition','')):
        css+='''.framed-right{background:transparent;border:0;clip-path:none;padding-left:0}
.framed-right .direction-type{color:var(--wt-color);-webkit-text-stroke:calc(.09*var(--wt-u)) #233844;transform:skewX(-6deg);font-weight:800}
.framed-right .direction-symbol{height:calc(9*var(--wt-u));width:calc(4*var(--wt-u));right:calc(.6*var(--wt-u));transform:rotate(8deg)}
.framed-right .direction-detail{display:block;left:0;right:calc(7*var(--wt-u));height:calc(.16*var(--wt-u));opacity:.6}'''
    css+=f'''.emblem-left .direction-type{{max-width:calc(62*var(--wt-u));font-weight:800}}
.emblem-left .direction-symbol{{fill:{p['foreground']};stroke:{p['secondary']}}}
.type-led .direction-symbol{{left:calc(-.5*var(--wt-u));right:auto;top:calc(-2.8*var(--wt-u));transform:rotate(-9deg)}}'''
    return WebThemeDocument.from_dict(dict(name=concept['name'],concept='方向预览组件 .direction-symbol 与排版 .direction-type',
        palette=dict(primary=p['foreground'],secondary=p['secondary'],accent=p['accent'],background='#FFFFFF',text=p['foreground']),
        appearance=dict(fontFamily=font,fontSize=64,color=p['foreground'],strokeColor='#253540',strokeWidth=1),
        stageHtml='<div></div>',stageCss='.wt-stage{display:none}',cueHtml=html,cueCss=css,
        notes='DESIGN_V2_STATIC_PREVIEW：按ArtDirectionSpec生成的组件构图预览，选中后才生成完整动画。')).to_dict()
