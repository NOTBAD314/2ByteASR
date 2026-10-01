"""Controlled static DesignSpec trials, deterministic compilation and preferences.

Providers return data only. No provider-authored HTML, JS, filesystem action or
image route is executed. The caller owns request consent and output location.
"""
from __future__ import annotations
import base64
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from html import escape
from io import BytesIO
import json
import math
from pathlib import Path
import tempfile

VERSION='caption-design-spec-1'
FONTS=('Smiley Sans','ZCOOL KuaiLe','ZCOOL QingKe HuangYou','Source Han Sans SC')
STRUCTURES=('cut_crystal','field_seal','signal_fin','glacier_window','pressed_ticket','folded_ribbon')
NEGATIVE_RULES=[
    '禁止浅色第一圈描边：必须渐变字芯、深色内描边、浅色外描边、低透明深软阴影',
    '禁止冰蓝框加白字作为所有方向的共同模板；结构、字形、材质必须有差异',
    '禁止emoji、随机星星、无语义粒子、整屏闪光、廉价弹跳、clearProps all',
    '只一行字幕；主体稳定；动画仅外层transform/opacity/有限clip-path；结束硬隐藏',
    '不需要位图；不调用图片生成路由；不生成熊或人物占位物',
]


def _object(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def _enum(values):return {'type':'string','enum':list(values)}
def _number(low,high):return {'type':'number','minimum':low,'maximum':high}
COLOR={'type':'string','pattern':'^#[0-9A-Fa-f]{6}$'}
TEXT={'type':'string','minLength':1,'maxLength':100}
SCHEMA=_object({
    'version':{'const':VERSION},'name':TEXT,'concept':TEXT,
    'typography':_object({'family':_enum(FONTS),'weight':_number(500,900),'size':_number(112,152),'tracking':_number(-1,2),'tilt':_number(-4,4)}),
    'fill_gradient':_object({'angle':_number(0,360),'colors':{'type':'array','items':COLOR,'minItems':3,'maxItems':3}}),
    'inner_dark_stroke':_object({'color':COLOR,'width':_number(2,6)}),
    'outer_light_stroke':_object({'color':COLOR,'width':_number(4,10)}),
    'shadow':_object({'color':COLOR,'opacity':_number(.1,.35),'blur':_number(8,22),'y':_number(2,8)}),
    'backplate':_object({'structure':_enum(STRUCTURES),'color':COLOR,'edge':COLOR,'height':_number(88,148),'width_percent':_number(65,86)}),
    'material':_object({'kind':_enum(('strata','ceramic','woven','brushed','frost')),'intensity':_number(.04,.2)}),
    'accent_elements':{'type':'array','minItems':1,'maxItems':2,'items':_object({'kind':_enum(('notch','seal','fold','facet')),'color':COLOR})},
    'entrance':_object({'semantic':_enum(('fracture_lock','pressure_stamp','refraction_scan','frost_edge')),'duration_ms':_number(180,400)}),
    'hold':_object({'semantic':_enum(('still','local_highlight','edge_mist')),'intensity':_number(0,.15)}),
    'exit':_object({'semantic':{'const':'hard_hide'},'duration_ms':{'const':0}}),
    'performance_level':{'const':'low'},
    'forbidden_patterns':{'type':'array','items':TEXT,'minItems':3,'maxItems':8},
    'asset_requirements':{'type':'array','maxItems':0},
})


def luminance(color):
    values=[int(color[i:i+2],16)/255 for i in (1,3,5)]
    values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
    return sum(a*b for a,b in zip(values,(.2126,.7152,.0722)))


def validate_spec(value):
    from jsonschema import validate
    validate(value,SCHEMA)
    def finite(item):
        if isinstance(item,float) and not math.isfinite(item):raise ValueError('DesignSpec numbers must be finite')
        if isinstance(item,dict):
            for nested in item.values():finite(nested)
        if isinstance(item,list):
            for nested in item:finite(nested)
    finite(value)
    return copy.deepcopy(value)


def design_style_checks(value):
    """Visual-role checks are separate from transport/schema validity."""
    validate_spec(value)
    inner,outer=value['inner_dark_stroke'],value['outer_light_stroke']
    return {'inner_is_theme_dark':luminance(inner['color'])<=.16 and inner['color'].upper()!='#000000',
        'outer_is_wider':outer['width']>inner['width'],
        'stroke_contrast':(luminance(outer['color'])+.05)/(luminance(inner['color'])+.05)>=3,
        'brightest_fill_visible':max(map(luminance,value['fill_gradient']['colors']))>=.5,
        'gradient_low_stop_luminance':min(map(luminance,value['fill_gradient']['colors']))}


@dataclass(frozen=True)
class TrialInput:
    json_text: str
    @property
    def fingerprint(self):return hashlib.sha256(self.json_text.encode('utf8')).hexdigest()
    @classmethod
    def capture(cls,request,text,game_path,preferences):
        path=Path(game_path).resolve()
        value={'user_request':request,'subtitle_text':text,'game_frame':{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},
            'game_description':'水绿色游戏场景，人物与环境有明暗和细节；字幕置于底部，不能用全屏暗板压住原画面。',
            'canvas':{'width':1920,'height':1080},'safe_zone':{'x':96,'y':810,'width':1728,'height':216},
            'positive_references':preferences.positive_references(limit=2),'negative_rules':preferences.read()['negative_rules'],
            'output_schema':SCHEMA,'max_output_tokens':2600}
        return cls(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')))


class CaptionPreferences:
    def __init__(self,path):self.path=Path(path)
    def read(self):
        if self.path.is_file():return json.loads(self.path.read_text('utf8'))
        return {'version':1,'negative_rules':NEGATIVE_RULES,'choices':[],'status':'awaiting_user_selection'}
    def write(self,value):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        # Atomic replace with a same-directory staging file; no training claim.
        with tempfile.NamedTemporaryFile('w',encoding='utf8',dir=self.path.parent,delete=False,suffix='.tmp') as stream:
            json.dump(value,stream,ensure_ascii=False,indent=2);temporary=Path(stream.name)
        if json.loads(temporary.read_text('utf8'))!=value:raise ValueError('preference readback mismatch')
        temporary.replace(self.path)
    def record_choice(self,*,candidate_id,rating,accepted,provider,model,spec,screenshots,notes,verification):
        if not 0<=float(rating)<=10:raise ValueError('rating must be 0..10')
        value=self.read();value['choices'].append({'candidate_id':candidate_id,'user_rating':rating,'accepted':bool(accepted),
            'provider':provider,'model':model,'spec_version':VERSION,'design_spec':validate_spec(spec),'screenshots':list(screenshots),
            'notes':str(notes),'verification':verification,'timestamp':datetime.now(timezone.utc).isoformat()})
        value['status']='preferences_recorded';self.write(value)
    def positive_references(self,limit=2):
        choices=[row for row in self.read()['choices'] if row.get('accepted') and row.get('user_rating',0)>=8]
        return [{k:row[k] for k in ('candidate_id','user_rating','design_spec','provider','model')} for row in sorted(
            choices,key=lambda row:(row.get('user_rating',0),row.get('timestamp','')),reverse=True)[:limit]]


@lru_cache(maxsize=32)
def _subset_font(family,text):
    from .runtime_paths import detect_install_root
    from .web_theme_fonts import FONT_FILES
    path=detect_install_root()/'assets/fonts'/FONT_FILES[family][0]
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        # FontTools is an optional size optimization, never a design gate.
        return base64.b64encode(path.read_bytes()).decode(),FONT_FILES[family][1]
    font=TTFont(path);options=subset.Options();options.flavor='woff2'
    sub=subset.Subsetter(options=options);sub.populate(text=text);sub.subset(font)
    font.flavor='woff2';out=BytesIO();font.save(out);font.close()
    return base64.b64encode(out.getvalue()).decode(),'woff2'


def compile_static_candidate(spec,text,*,background_path=None,embed_font=True):
    spec=validate_spec(spec);text=str(text).replace('\n',' ').replace('\r',' ')
    typeface=spec['typography'];plate=spec['backplate'];inner=spec['inner_dark_stroke'];outer=spec['outer_light_stroke'];shadow=spec['shadow']
    font_data,font_format=_subset_font(typeface['family'],text) if embed_font else ('','woff2')
    background='transparent'
    if background_path:
        path=Path(background_path);mime='image/jpeg' if path.suffix.lower() in {'.jpg','.jpeg'} else 'image/png'
        background=f'url(data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}) center/cover no-repeat'
    fill=','.join(f'{color} {position}%' for color,position in zip(spec['fill_gradient']['colors'],(0,48,100)))
    structure=plate['structure'];material=spec['material']
    textures={'strata':'repeating-linear-gradient(164deg,transparent 0 13px,#d5edf5 14px,transparent 15px 35px)',
        'ceramic':'radial-gradient(ellipse at 50% -35%,#fff,transparent 70%)',
        'woven':'repeating-linear-gradient(85deg,transparent 0 5px,#d5edf5 6px,transparent 7px)',
        'brushed':'repeating-linear-gradient(175deg,transparent 0 2px,#d5edf5 3px,transparent 4px 8px)',
        'frost':'radial-gradient(#e6f4f5 .6px,transparent 1px)'}
    shadow_color=shadow['color'];rgb=','.join(str(int(shadow_color[i:i+2],16)) for i in (1,3,5))
    accents=''.join(f'<i class="accent {row["kind"]}" style="--accent:{row["color"]}"></i>' for row in spec['accent_elements'])
    metadata=json.dumps(spec,ensure_ascii=False).replace('</','<\/')
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{escape(spec['name'])}</title>
<style>@font-face{{font-family:TrialFace;src:url(data:font/{font_format};base64,{font_data}) format('{font_format}');font-weight:100 900;font-display:block}}
*{{box-sizing:border-box}}html,body{{margin:0;width:1920px;height:1080px;overflow:hidden;background:{background}}}
.caption{{position:absolute;left:50%;top:838px;width:{1920*plate['width_percent']/100:g}px;height:{plate['height']}px;transform:translateX(-50%);isolation:isolate;visibility:hidden}}
.plate{{position:absolute;inset:0;background:linear-gradient(170deg,{plate['edge']} 0%,{plate['color']} 22%,{plate['color']} 80%,{plate['edge']});border:1px solid {plate['edge']};box-shadow:0 10px 18px #07151d55;overflow:hidden}}
.material{{position:absolute;inset:0;background-image:{textures[material['kind']]};background-size:{'4px 4px' if material['kind']=='frost' else 'auto'};opacity:{material['intensity']}}}
.type{{position:absolute;inset:0;display:grid;place-content:center;font-family:TrialFace;font-weight:{typeface['weight']};font-size:{typeface['size']}px;letter-spacing:{typeface['tracking']}px;line-height:1.1;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;transform:skewX({typeface['tilt']}deg)}}
.letter{{grid-area:1/1;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;padding:10px 14px}}
.shadow{{color:{shadow_color};filter:blur({shadow['blur']}px);opacity:{shadow['opacity']};transform:translateY({shadow['y']}px)}}
.outer{{color:{outer['color']};-webkit-text-stroke:{outer['width']*2}px {outer['color']}}}
.inner{{color:{inner['color']};-webkit-text-stroke:{inner['width']*2}px {inner['color']}}}
.fill{{background:linear-gradient({spec['fill_gradient']['angle']}deg,{fill});background-clip:text;-webkit-background-clip:text;color:transparent}}
.accent{{position:absolute;display:block;background:var(--accent);z-index:1}}.notch{{width:6px;height:30px;left:21px;top:18px}}.seal{{width:29px;height:29px;left:27px;top:calc(50% - 14px);border:5px double {plate['color']};border-radius:50%}}.fold{{right:-10px;top:9px;width:34px;height:80%;clip-path:polygon(0 0,100% 18%,80% 100%,0 78%)}}.facet{{right:10px;top:7px;width:28px;height:24px;clip-path:polygon(0 40%,80% 0,100% 100%)}}
.cut_crystal .plate{{clip-path:polygon(2% 0,98% 0,100% 22%,98% 100%,1% 88%,0 24%)}}.cut_crystal .plate:after{{content:"";position:absolute;inset:0;border-bottom:10px solid {plate['edge']};clip-path:polygon(0 55%,100% 82%,100% 100%,0 100%)}}
.field_seal .plate{{border-radius:7px;background:{plate['color']};border-left:10px solid {plate['edge']};box-shadow:inset 0 0 0 7px {plate['color']},inset 0 0 0 8px {plate['edge']},0 8px 20px #07151d55}}
.signal_fin .plate{{clip-path:polygon(0 65%,3% 58%,3% 32%,12% 32%,12% 65%,87% 65%,90% 88%,100% 88%,100% 100%,0 100%)}}.signal_fin .type{{top:0}}
.signal_fin .facet{{top:auto;bottom:7px;right:28px;height:14px}}
.glacier_window .plate{{clip-path:polygon(3% 0,97% 0,100% 30%,100% 70%,97% 100%,3% 100%,0 70%,0 30%);box-shadow:inset 0 0 0 5px {plate['edge']}}}
.pressed_ticket .plate{{border:2px solid {plate['edge']};background:{plate['color']};border-radius:2px;box-shadow:inset 0 -6px 0 {plate['edge']},0 7px 12px #07151d44}}.pressed_ticket .material{{border-left:2px dashed {plate['edge']};left:58px}}
.folded_ribbon .plate{{clip-path:polygon(2% 0,96% 10%,100% 0,98% 100%,3% 92%,0 100%);transform:rotate(-1deg)}}
</style><div class="caption {structure}" data-design="{escape(spec['name'])}"><div class="plate"><div class="material"></div></div>{accents}<div class="type">
<span class="letter shadow" aria-hidden="true">{escape(text)}</span><span class="letter outer" aria-hidden="true">{escape(text)}</span><span class="letter inner" aria-hidden="true">{escape(text)}</span><span class="letter fill" data-semantic-text="true">{escape(text)}</span></div></div>
<script type="application/json" id="design-spec">{metadata}</script><script>
window.__trialReady=(async()=>{{let text=document.querySelector('[data-semantic-text]'),type=document.querySelector('.type'),root=document.querySelector('.caption');
await document.fonts.load(getComputedStyle(type).font,text.textContent);await document.fonts.ready;
let max=root.clientWidth-118;let size=parseFloat(getComputedStyle(type).fontSize);let width=text.getBoundingClientRect().width;
if(width>max)type.style.fontSize=(Math.floor(size*max/width*64)/64)+'px';root.style.visibility='visible';
const nodes=[...document.querySelectorAll('.letter')],rects=nodes.map(n=>{{let r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height]}});
let range=document.createRange();range.selectNodeContents(text);let lines=new Set([...range.getClientRects()].map(r=>Math.round(r.y)));
window.__trialMetrics={{fontLoaded:document.fonts.check(getComputedStyle(type).font,text.textContent),fontFamily:{json.dumps(typeface['family'])},fontSize:parseFloat(getComputedStyle(type).fontSize),
lineCount:lines.size,maxWidth:max,text:text.textContent,rects,semanticCount:document.querySelectorAll('[data-semantic-text]').length,structure:{json.dumps(structure)},strokeOrder:['gradient','dark-inner','light-outer','soft-shadow']}};
return window.__trialMetrics;}})();window.__2byteSeek=()=>window.__trialReady;</script></html>'''


def local_specs():
    base={'version':VERSION,'name':'雪脊断面','concept':'短促裂冰完成字芯锁定，冷色分层岩面托住高对比文字',
        'typography':{'family':'Smiley Sans','weight':800,'size':148,'tracking':0,'tilt':-2},
        'fill_gradient':{'angle':180,'colors':['#F3FAFC','#B0DEE9','#69ABBC']},
        'inner_dark_stroke':{'color':'#173C49','width':3.2},'outer_light_stroke':{'color':'#C9EFF3','width':5.2},
        'shadow':{'color':'#0D2430','opacity':.25,'blur':12,'y':5},
        'backplate':{'structure':'cut_crystal','color':'#263F4A','edge':'#75A7B6','height':130,'width_percent':76},
        'material':{'kind':'strata','intensity':.12},'accent_elements':[{'kind':'facet','color':'#C9EFF3'}],
        'entrance':{'semantic':'fracture_lock','duration_ms':280},'hold':{'semantic':'local_highlight','intensity':.08},
        'exit':{'semantic':'hard_hide','duration_ms':0},'performance_level':'low','forbidden_patterns':NEGATIVE_RULES[:4], 'asset_requirements':[]}
    second=copy.deepcopy(base);second.update(name='远征压印',concept='暖矿物釉面与压印铭牌，签名动作为一次压力锁定')
    second['typography'].update(family='ZCOOL QingKe HuangYou',size=150,tilt=0)
    second['fill_gradient']['colors']=['#FFF4D5','#ECDDAA','#BCAA7B'];second['inner_dark_stroke']['color']='#383A2C';second['outer_light_stroke']['color']='#FAE9BD'
    second['backplate'].update(structure='field_seal',color='#38463E',edge='#AD9B68',width_percent=72)
    second['material']={'kind':'ceramic','intensity':.12};second['accent_elements']=[{'kind':'seal','color':'#E6C57E'}];second['entrance']['semantic']='pressure_stamp'
    third=copy.deepcopy(base);third.update(name='赤岩信标',concept='岩层色字芯与偏置标记，仅在底边留下坚固结构，开放留白')
    third['typography'].update(family='ZCOOL KuaiLe',size=144,tilt=-1)
    third['fill_gradient']['colors']=['#FFF0DB','#F4BD91','#D4936C'];third['inner_dark_stroke']['color']='#4B2E36';third['outer_light_stroke']['color']='#FFE4C5'
    third['backplate'].update(structure='signal_fin',color='#3C3440',edge='#CC7C62',width_percent=78)
    third['material']={'kind':'brushed','intensity':.09};third['accent_elements']=[{'kind':'notch','color':'#F4B585'}];third['entrance']['semantic']='refraction_scan'
    return [validate_spec(spec) for spec in (base,second,third)]


def compile_web_theme(spec):
    """Same deterministic static design as a safe, editable Studio WebTheme."""
    import re
    from .web_theme import WebThemeDocument
    spec=validate_spec(spec)
    document=compile_static_candidate(spec,'CAPTION_TEXT_MARKER',embed_font=False)
    css=document.split('<style>',1)[1].split('</style>',1)[0]
    css=re.sub(r'@font-face\{[^}]*\}', '', css)
    css=re.sub(r'html,body\{[^}]*\}', '', css)
    css=css.replace('visibility:hidden','visibility:visible').replace('font-family:TrialFace','font-family:var(--wt-font)')
    css=css.replace(f"font-size:{spec['typography']['size']}px",'font-size:var(--wt-size)')
    css=re.sub(r'(-?\d+(?:\.\d+)?)px',lambda m:f'{float(m[1])/10.8:.6f}vh',css)
    body=document.split('</style>',1)[1].split('<script type=',1)[0]
    body=body.replace('CAPTION_TEXT_MARKER','{{text}}')
    index=[0];accent_rules=[]
    def accent(match):
        index[0]+=1;name=f'trial-accent-{index[0]}'
        accent_rules.append(f'.{name}{{--accent:{match[2]};}}')
        return f'class="{match[1]} {name}"'
    body=re.sub(r'class="([^"]+)" style="--accent:(#[0-9A-Fa-f]+)"',accent,body)
    typeface=spec['typography'];inner=spec['inner_dark_stroke'];outer=spec['outer_light_stroke']
    return WebThemeDocument.from_dict({'name':spec['name'],'concept':spec['concept']+' .caption .plate .material .type',
        'palette':{'primary':spec['fill_gradient']['colors'][0],'text':spec['fill_gradient']['colors'][0],'background':spec['backplate']['color']},
        'appearance':{'fontFamily':typeface['family'],'fontSize':typeface['size'],'bold':typeface['weight']>=700,
            'color':spec['fill_gradient']['colors'][0],'strokeColor':inner['color'],'strokeWidth':inner['width'],
            'stroke2Color':outer['color'],'stroke2Width':outer['width'],'letterSpacing':typeface['tracking']},
        'stageHtml':'','stageCss':'','cueHtml':body,'cueCss':'.wt-cue{position:absolute;inset:0;width:100%;height:100%}'+css+''.join(accent_rules),
        'notes':'DESIGN_V2_HERO_GSAP; static DesignSpec compiled locally; no image generation; animation awaits explicit selection'}).to_dict()


def request_static_options(project,cue_id,instruction,settings,*,request_id='',cancel_check=None,stage_callback=None,**unused):
    """Normal Studio entry: selected provider data + explicit local comparisons.

    Multi-provider benchmarking is a separate explicitly invoked operation.
    This entry never silently sends the project to additional providers.
    """
    import time
    from .provider_registry import GLOBAL_PROVIDER_REGISTRY
    from .provider_service import GLOBAL_PROVIDER_SERVICE
    from .runtime_paths import detect_install_root
    from .web_theme_compiler import BRIEF_FIELDS,parse_object
    from .studio_ai import AIWebThemeSuggestion
    cue=next(item for item in project.cues if item.id==cue_id)
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings)
    prefs=CaptionPreferences(detect_install_root()/'docs/design/caption-preferences.json')
    payload={'user_request':instruction,'subtitle_text':cue.text,'canvas':[1920,1080],
        'safe_zone':{'x':96,'y':810,'width':1728,'height':216},'output_schema':SCHEMA,
        'positive_references':prefs.positive_references(limit=2),'negative_rules':prefs.read()['negative_rules'],'max_output_tokens':2600}
    if stage_callback:stage_callback('生成静态设计规格 · 最长90秒')
    started=time.monotonic();deadline=started+89
    check=lambda:time.monotonic()>=deadline or bool(cancel_check and cancel_check())
    records=[];error=''
    try:
        client=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish')
        prompt='只返回一份符合schema的DesignSpec JSON，不写HTML/CSS/脚本，不修改文件。'+json.dumps(payload,ensure_ascii=False)
        references=tuple(unused.get('reference_frames') or ())[:1]
        message=prompt
        if references and selection.provider=='google_antigravity':
            message=prompt+'\n参考画面仅允许读取：'+str(Path(references[0]).resolve())+'；无法读图须说明，不读取其它文件。'
        elif references and selection.provider=='grok_oauth':
            path=Path(references[0]);mime='image/jpeg' if path.suffix.lower() in {'.jpg','.jpeg'} else 'image/png'
            message=[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode()}}]
        raw=client.complete([{'role':'user','content':message}],
            timeout=89,max_tokens=2600,cancel_check=check)
        records.append((validate_spec(parse_object(raw)),selection.provider))
    except Exception as exc:
        if cancel_check and cancel_check():raise
        from .provider_diagnostics import redact_diagnostics
        error=redact_diagnostics(str(exc))
    used={item[0]['backplate']['structure'] for item in records}
    used_fonts={item[0]['typography']['family'] for item in records}
    for spec in local_specs():
        if len(records)==3:break
        if spec['backplate']['structure'] in used or spec['typography']['family'] in used_fonts:continue
        records.append((spec,'local_rules'));used.add(spec['backplate']['structure']);used_fonts.add(spec['typography']['family'])
    for spec in local_specs():
        if len(records)==3:break
        spec['backplate']['structure']=next(kind for kind in STRUCTURES if kind not in used)
        spec['typography']['family']=next(family for family in FONTS if family not in used_fonts)
        records.append((spec,'local_rules'));used.add(spec['backplate']['structure']);used_fonts.add(spec['typography']['family'])
    concepts=[]
    for index,(spec,provider) in enumerate(records):
        identity=f'static-{index+1}'
        design={'metaphor':spec['concept'],'silhouette':spec['backplate']['structure'],
            'hierarchy':'渐变字芯、主题深内描、浅外描、软阴影；文字第一','font':spec['typography']['family'],
            'colors':[{'hex':spec['fill_gradient']['colors'][0],'role':'字芯'}, {'hex':spec['inner_dark_stroke']['color'],'role':'内描'},
                {'hex':spec['outer_light_stroke']['color'],'role':'外描'}, {'hex':spec['backplate']['color'],'role':'底板'}],
            'material':spec['material'],'rhythm':{'entrance':spec['entrance'],'hold':spec['hold'],'exit':spec['exit']},
            'forbidden':spec['forbidden_patterns'],'content_relevance':spec['concept']}
        concepts.append({'id':identity,'name':spec['name']+(' · 本地对照' if provider=='local_rules' else ''),
            'subject':spec['concept'],'composition':spec['backplate']['structure'],'palette':design['colors'],
            'materials':[spec['material']['kind']],'motion':{'entrance':spec['entrance']['semantic'],'hold':spec['hold']['semantic'],'exit':'hard_hide'},
            'signature_elements':[spec['entrance']['semantic']],'risks':['静态方向，未获用户审美确认'],'estimated_performance':'low',
            'design':design,'design_spec':spec,'provider':provider,'hero_theme':compile_web_theme(spec)})
    brief={key:'字幕文字优先，按静态设计规格' for key in BRIEF_FIELDS};brief.update(transparent=True,allow_vignette=False,scope='subtitle',performance_level='low')
    return AIWebThemeSuggestion(theme={},source='concepts',message=('Provider未返回；三个本地对照。'+error if error else '已选服务试稿与两个本地对照，请选择静态方向。'),
        request_id=request_id,provider=selection.provider,model=selection.model,brief=brief,concepts=concepts,selected_concept_id='',
        quality={'design_version':3,'deterministic_compiler':VERSION,'provider_error':error,'image_gen':'无需调用'},elapsed_seconds=time.monotonic()-started)
