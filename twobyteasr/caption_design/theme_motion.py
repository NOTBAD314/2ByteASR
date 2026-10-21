"""Safe declarative motion, compiled by the shared paused GSAP runtime."""
import math
import re

NUMERIC={'opacity':(0,1),'x':(-1920,1920),'y':(-1080,1080),'xPercent':(-100,100),
         'yPercent':(-100,100),'rotation':(-180,180),'scaleX':(0,3),'scaleY':(0,3),
         'rotationX':(-80,80),'rotationY':(-80,80),
         'backgroundPositionX':(-1920,1920),'backgroundPositionY':(-1080,1080),
         'strokeDashoffset':(-10000,10000)}
# GSAP's built-in, finite easing functions use the same deterministic clock.
# Keep an explicit vocabulary; do not evaluate model-supplied expressions.
EASES={'none','back.out(1.7)'} | {family+'.'+direction
    for family in ('power1','power2','power3','power4','sine','expo','circ','back','bounce','elastic')
    for direction in ('in','out','inOut')}
SELECTOR=re.compile(r'^\.[A-Za-z][\w-]*(?:(?:\s+|\s*>\s*)\.[A-Za-z][\w-]*)*(?::(?:first-child|last-child|nth-child\([1-9]\d?\)|nth-last-child\([1-9]\d?\)))?$')
HOST_SELECTORS=('.wt-cue','.wt-stage','.wt-scope','.subtitle-placement','.theme-motion')
CLIP_PATH_PATTERN=r'(?:inset|polygon)\([\d.%,\s-]+\)'
ORIGIN_PATTERN=r'[\d.]+% [\d.]+%'
STEPS_PATTERN=r'steps\((?:[2-9]|[12]\d|3[0-2])\)'
CAPTION_VARIABLES={'--caption-reveal':(0,1),'--caption-sheen':(0,100),'--pixel-progress':(0,1)}
from .pixel_motion import PIXEL_SCHEMA,validate_pixels
STAGGER_SCHEMA={'type':'object','additionalProperties':False,'required':['amountMs'],
    'properties':{'amountMs':{'type':'number','minimum':0,'maximum':240},
        'groupSize':{'type':'integer','minimum':1,'maximum':8},
        'order':{'enum':['forward','reverse','center']}}}
WIGGLE_RANGES={'amplitudeX':(0,240),'amplitudeY':(0,240),'rotation':(0,30),
    'frequency':(.1,60),'intensity':(0,4),'fadeInMs':(0,30000),'fadeOutMs':(0,30000)}
WIGGLE_SCHEMA={'type':'object','additionalProperties':False,
    'required':[*WIGGLE_RANGES,'seed'],
    'properties':{**{p:{'type':'number','minimum':lo,'maximum':hi}
                    for p,(lo,hi) in WIGGLE_RANGES.items()},
        'seed':{'type':'integer','minimum':0,'maximum':2147483647}}}


class MotionRangeError(ValueError):
    """A validator-owned numeric leaf diagnostic, never parsed from prose."""
    def __init__(self, path, value, low, high):
        self.path, self.value, self.low, self.high = path, value, low, high
        self.repairable = (not isinstance(value, bool) and isinstance(value, (int, float))
                           and math.isfinite(value) and not low <= value <= high)
        super().__init__(f'{path}: MotionSpec 数值必须介于 {low} 与 {high}；请只修正该字段后重试。')

# Provider output uses the same finite vocabulary as local validation. JSON
# Schema cannot express cross-track overlap or equal from/to property sets;
# validate_motion_spec remains the authority for those relationships.
MOTION_STATE_SCHEMA={'type':'object','minProperties':1,'additionalProperties':False,
    'properties':{**{prop:{'type':'number','minimum':low,'maximum':high} for prop,(low,high) in NUMERIC.items()},
        'clipPath':{'type':'string','maxLength':180,'pattern':'^'+CLIP_PATH_PATTERN+'$'},
        'transformOrigin':{'type':'string','pattern':'^'+ORIGIN_PATTERN+'$'}}}
MOTION_OUTPUT_SCHEMA={'type':'object','required':['version','runtime','tracks'],
    'properties':{'version':{'enum':[1,2]},'runtime':{'const':'gsap'},
        'buildMs':{'type':'number','minimum':0,'maximum':800},
        'resolveMs':{'type':'number','minimum':0,'maximum':500},
        'timingProfile':{'enum':['readable-pixel']},
        'tracks':{'type':'array','minItems':1,'maxItems':64,'items':{'type':'object',
            'required':['selector','phase','from','to'],'properties':{
                'selector':{'type':'string','pattern':SELECTOR.pattern,
                    'not':{'pattern':'|'.join(re.escape(s) for s in HOST_SELECTORS)}},
                'phase':{'enum':['build','breathe','resolve']},
                'start':{'type':'number','minimum':0,'maximum':1},
                'end':{'type':'number','minimum':0,'maximum':1},
                'ease':{'anyOf':[{'enum':sorted(EASES)},{'type':'string','pattern':'^'+STEPS_PATTERN+'$'}]},
                'repeat':{'type':'integer','minimum':0,'maximum':24},'yoyo':{'type':'boolean'},
                'durationMs':{'type':'number','minimum':120,'maximum':30000},
                'sustain':{'type':'boolean'},
                'minCueMs':{'type':'number','minimum':0,'maximum':30000},
                'wiggle':WIGGLE_SCHEMA,
                'pixels':PIXEL_SCHEMA,
                'stagger':STAGGER_SCHEMA,'optional':{'type':'boolean'},
                'from':MOTION_STATE_SCHEMA,'to':MOTION_STATE_SCHEMA}}}}}
MOTION_STATE_SCHEMA['properties'].update({p:{'type':'number','minimum':lo,'maximum':hi}
    for p,(lo,hi) in CAPTION_VARIABLES.items()})


def validate_motion_spec(value, *, cue_html=None, duration_ms=3000):
    if not isinstance(value,dict) or type(value.get('version')) is not int or value.get('version') not in (1,2) or value.get('runtime')!='gsap':
        raise ValueError('motionSpec 必须为 version=1或2、runtime=gsap 的对象')
    if value['version']==2 and set(value)-{'version','runtime','buildMs','resolveMs','tracks','timingProfile'}:
        raise ValueError('MotionSpec v2含不支持的顶层能力字段')
    def number(v,low,high,path='motionSpec'):
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not low<=v<=high:
            raise MotionRangeError(path, v, low, high)
        return float(v)
    result=dict(version=value['version'],runtime='gsap',buildMs=number(value.get('buildMs',320),0,800,'motionSpec.buildMs'),resolveMs=number(value.get('resolveMs',180),0,500,'motionSpec.resolveMs'),tracks=[])
    if 'timingProfile' in value:
        if value['version']!=2 or value['timingProfile']!='readable-pixel':raise ValueError('timingProfile需要v2 readable-pixel')
        result['timingProfile']=value['timingProfile']
    tracks=value.get('tracks')
    if not isinstance(tracks,list) or not 1<=len(tracks)<=64:raise ValueError('MotionSpec 需要1–64条有限动作')
    breathe=0
    for track_index,row in enumerate(tracks):
        if not isinstance(row,dict):raise ValueError('MotionSpec track必须是对象')
        unknown=set(row)-set(MOTION_OUTPUT_SCHEMA['properties']['tracks']['items']['properties'])
        if unknown:raise ValueError('MotionSpec不支持字段：'+','.join(sorted(unknown)))
        if value['version']==1 and ({'stagger','optional','wiggle','minCueMs','pixels'} & set(row)):
            raise ValueError('stagger/optional/wiggle/minCueMs需要MotionSpec version=2')
        selector=str(row.get('selector',''))
        if any(s in selector for s in HOST_SELECTORS):
            raise ValueError(f'motionSpec.tracks[{track_index}].selector: 不能动画宿主placement；请只定位cueHtml内部内容class。')
        if not SELECTOR.fullmatch(selector):
            raise ValueError(f'motionSpec.tracks[{track_index}].selector: 选择器语法只支持单class、class后代/子级链与末尾有限子项伪类；不支持.a.b、逗号、ID或标签，请为目标内容使用独立class。')
        phase=row.get('phase')
        if phase not in ('build','breathe','resolve'):raise ValueError('MotionSpec phase无效')
        if phase=='breathe':breathe+=1
        start=number(row.get('start',0),0,1,f'motionSpec.tracks[{track_index}].start');end=number(row.get('end',1),0,1,f'motionSpec.tracks[{track_index}].end')
        if end<=start:raise ValueError('MotionSpec动作必须有正的有限时长')
        ease=row.get('ease','power2.out')
        if ease not in EASES and not re.fullmatch(STEPS_PATTERN,ease):raise ValueError('MotionSpec easing不在有限白名单内')
        repeat=row.get('repeat',0)
        if isinstance(repeat,bool) or not isinstance(repeat,int) or not 0<=repeat<=24:
            raise ValueError('MotionSpec repeat 必须为0–24的有限整数')
        yoyo=row.get('yoyo',False)
        if not isinstance(yoyo,bool):raise ValueError('MotionSpec yoyo 必须为布尔值')
        if repeat and phase!='breathe':raise ValueError('重复材质动作只允许在阅读阶段')
        before=row.get('from');after=row.get('to')
        if not isinstance(before,dict) or not before or not isinstance(after,dict) or before.keys()!=after.keys():
            raise ValueError('MotionSpec from/to必须显式指定同一组属性')
        clean=[]
        for state_name,state in (('from',before),('to',after)):
            item={}
            for prop,v in state.items():
                if prop in NUMERIC:item[prop]=number(v,*NUMERIC[prop],path=f'motionSpec.tracks[{track_index}].{state_name}.{prop}')
                elif value['version']==2 and prop in CAPTION_VARIABLES:item[prop]=number(v,*CAPTION_VARIABLES[prop],path=f'motionSpec.tracks[{track_index}].{state_name}.{prop}')
                elif prop=='clipPath' and isinstance(v,str) and len(v)<=180 and re.fullmatch(CLIP_PATH_PATTERN,v):item[prop]=v
                elif prop=='transformOrigin' and isinstance(v,str) and re.fullmatch(ORIGIN_PATTERN,v):item[prop]=v
                else:raise ValueError(f'MotionSpec不支持属性/值：{prop}')
            clean.append(item)
        item=dict(selector=selector,phase=phase,start=start,end=end,ease=ease,**{'from':clean[0],'to':clean[1]})
        if 'pixels' in row:
            if (phase not in {'build','resolve'} or row.get('ease')!='none' or before!={'--pixel-progress':0} or after!={'--pixel-progress':1}
                    or any(k in row for k in ('repeat','yoyo','sustain','wiggle','stagger','durationMs','minCueMs'))):
                raise ValueError('pixels只支持build/resolve独立轨，from/to为--pixel-progress:0/1，不可重复或混合其他程序动作')
            item['pixels']=validate_pixels(row['pixels'])
        elif '--pixel-progress' in before:raise ValueError('--pixel-progress需要明确的pixels效果参数')
        if 'minCueMs' in row:
            item['minCueMs']=number(row['minCueMs'],0,30000,f'motionSpec.tracks[{track_index}].minCueMs')
        if 'wiggle' in row:
            wiggle=row['wiggle'];path=f'motionSpec.tracks[{track_index}].wiggle'
            if not isinstance(wiggle,dict) or set(wiggle)!=set(WIGGLE_SCHEMA['properties']):
                raise ValueError(path+': 必须明确振幅X/Y、rotation、frequency、seed、intensity和fadeInMs/fadeOutMs')
            if type(wiggle['seed']) is not int or not 0<=wiggle['seed']<=2147483647:
                raise ValueError(path+'.seed: 需要0–2147483647的固定整数')
            if clean[0]!={'x':0,'y':0,'rotation':0} or clean[1]!=clean[0]:
                raise ValueError(path+': 独立扰动层from/to必须为x/y/rotation全零；布局与入退场使用嵌套层')
            if any(key in row for key in ('stagger','repeat','yoyo','sustain')):
                raise ValueError(path+': 用绝对时间采样，不与stagger/repeat/yoyo/sustain组合')
            item['wiggle']={p:number(wiggle[p],lo,hi,path+'.'+p) for p,(lo,hi) in WIGGLE_RANGES.items()}
            item['wiggle']['seed']=wiggle['seed']
        if 'stagger' in row:
            stagger=row['stagger']
            if not isinstance(stagger,dict) or set(stagger)-{'amountMs','groupSize','order'}:
                raise ValueError('stagger仅支持amountMs/groupSize/order')
            amount=number(stagger.get('amountMs'),0,240,'motionSpec.stagger.amountMs')
            group=stagger.get('groupSize',1);order=stagger.get('order','forward')
            if type(group) is not int or not 1<=group<=8 or order not in ('forward','reverse','center'):
                raise ValueError('stagger分组或顺序不支持')
            if phase=='breathe' or repeat:raise ValueError('stagger仅用于一次入场或出场')
            item['stagger']=dict(amountMs=amount,groupSize=group,order=order)
        if 'optional' in row:
            if type(row['optional']) is not bool or not selector.endswith('.wt-focus'):
                raise ValueError('optional只用于可能未匹配的.wt-focus重点词')
            item['optional']=row['optional']
        if 'repeat' in row:item['repeat']=repeat
        if 'yoyo' in row:item['yoyo']=yoyo
        if 'durationMs' in row:
            if phase!='breathe':raise ValueError('durationMs 固定节奏只允许在阅读阶段')
            item['durationMs']=number(row['durationMs'],120,30000,f'motionSpec.tracks[{track_index}].durationMs')
        if 'sustain' in row:
            if type(row['sustain']) is not bool or value['version']!=2 or phase!='breathe' or 'durationMs' not in row or repeat:
                raise ValueError('sustain需要v2阅读阶段、durationMs真实周期且不能同时指定repeat')
            item['sustain']=row['sustain']
        result['tracks'].append(item)
    if breathe>8:raise ValueError('阅读阶段最多八个有界动作；各属性仍需独立且有限')
    from .motion_ownership import motion_ownership_issues,MotionOwnershipError
    issues=motion_ownership_issues(result,cue_html,duration_ms)
    if issues:raise MotionOwnershipError(issues)
    return result
