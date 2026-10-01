"""Aggregate technical diagnostics and apply bounded, inspectable transactions.

The provider original is immutable. Only explicitly listed scalar leaves or
CSS value spans may be patched; a failed structure replaces one candidate.
"""
import copy
import hashlib
import json
import math
import re
import time
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
import jsonschema
from .motion_spec_repair import changed_paths
from .theme_motion import NUMERIC,MOTION_STATE_SCHEMA,SELECTOR,HOST_SELECTORS,validate_motion_spec
from .theme_motion import MOTION_OUTPUT_SCHEMA
from .web_theme import _MAX_HTML_CHARS, _MAX_CSS_CHARS
MOTION_OUTPUT_SELECTOR_SCHEMA=MOTION_OUTPUT_SCHEMA['properties']['tracks']['items']['properties']['selector']


@dataclass(frozen=True)
class RepairResponse:
    value: object
    receipt: dict


def compact_patch_context(issues):
    """Send shared evidence once, while retaining every editable leaf constraint."""
    contexts = {}; rows = []
    for original in issues:
        row = copy.deepcopy(original)
        context = row.pop('context', None)
        if context:
            # Selector replacement depends on the actual DOM. CSS values and
            # variables are unchanged by this operation, and need not be echoed.
            if row.get('category') == 'selector':
                context = {'parent_structure': context.get('parent_structure', []),
                    'available_nodes':context.get('available_nodes',[])}
            key = digest(context)[:16]
            contexts[key] = context
            row['context_ref'] = key
        rows.append(row)
    return dict(issues=rows, contexts=contexts)


def provider_callbacks(client,parent_request_id,*,cancel_check=None,stage_callback=None,remaining_seconds=None,trace_root=None,stage_event_callback=None):
    """Shared production callbacks for UI generation and authorized replay."""
    from .authored_theme_contract import AUTHORED_TECHNICAL_DELIVERY
    def receipt():
        trace=getattr(client,'invocation_trace',lambda:getattr(client,'last_invocation_trace',{}))()
        return dict(provider_request_id=trace.get('request_id'),input_budget=trace.get('timings',{}).get('request_budget')
                    or getattr(client,'last_timings',{}).get('request_budget'),
                    reported_usage=trace.get('reported_usage'),actual_cost_usd=trace.get('actual_cost_usd'),
                    invocation_seconds=trace.get('timings',{}).get('total_seconds'),timeout_seconds=trace.get('timeout_seconds'))
    def complete(repair_id,messages,**kwargs):
        from .design_progress import PublicProgress
        from .theme_generation_policy import DesignTransportPolicy
        from pathlib import Path
        seconds=float(kwargs['timeout'])
        assembly=kwargs.pop('_assembly',None)
        progress=PublicProgress(repair_id,'修复候选技术字段',seconds,event_callback=stage_event_callback,stage_callback=stage_callback,
            path=Path(trace_root)/f'repair-partial-{repair_id}.txt' if trace_root else None)
        kwargs.update(on_stream_event=progress.stream,_timeout_policy=DesignTransportPolicy(total=seconds,read_idle=min(300.,seconds),
            deadline_monotonic=time.monotonic()+seconds))
        if trace_root is not None:
            from pathlib import Path
            request=dict(parent_request_id=parent_request_id,repair_request_id=repair_id,
                messages=messages,schema=kwargs.get('json_schema'),operation_kind=kwargs.get('operation_kind'),
                timeout_seconds=kwargs.get('timeout'),input_scope=kwargs.get('input_scope'))
            (Path(trace_root)/f'repair-input-{repair_id}.json').write_text(canonical(request),'utf8')
            if assembly is not None:
                (Path(trace_root)/f'repair-components-{repair_id}.json').write_text(canonical(assembly),'utf8')
        try:
            raw=client.complete(messages,**kwargs)
            if trace_root is not None:
                from pathlib import Path
                (Path(trace_root)/f'repair-response-{repair_id}.json').write_text(canonical(raw),'utf8')
            progress.finish('complete');return raw
        except Exception as exc:
            progress.finish('failed')
            exc.repair_receipt=receipt();raise
        finally:
            if trace_root is not None:
                from pathlib import Path
                from .provider_diagnostics import redact_diagnostics
                trace=getattr(client,'invocation_trace',lambda:{})()
                (Path(trace_root)/f'invocation-{repair_id}.json').write_text(json.dumps(redact_diagnostics(trace),ensure_ascii=False,indent=2),'utf8')
    def seconds(api_limit,cli_limit):
        transport=getattr(client,'transport','');transport=getattr(transport,'value',transport)
        limit=cli_limit if str(transport).endswith('_cli') else api_limit
        # Every child owns only the parent's remaining wall-clock budget.
        # An old 45/90 second constant must not discard a near-finished design.
        if remaining_seconds is not None:limit=float(remaining_seconds())
        if limit<=0:
            from .ai_providers import AIProviderError
            raise AIProviderError('修复前已达到本次生成总时限',category='provider_total_timeout')
        return limit
    def patch_call(fields, repair_id, text, assembly, **kwargs):
        """Large source leaves travel raw; the app constructs patch JSON."""
        if not any(str(field.get('path','')).endswith(('Html','Css')) for field in fields):
            return complete(repair_id,[{'role':'user','content':text}],_assembly=assembly,**kwargs)
        from .source_artifact import frame, unframe
        names=['VALUE_'+str(i) for i in range(len(fields))]
        identity=parent_request_id+'/'+repair_id
        kinds=[field.get('replacement_schema',{}).get('type','string') for field in fields]
        instructions=('仅返回下列完整分节工件。每个VALUE对应明确白名单路径；字符串源码原样写入，'
                      '其他值写短JSON值。禁止把HTML/CSS转义成JSON字符串。保留未授权内容。\n'
                      +json.dumps([dict(section=name,path=f['path'],type=kind) for name,f,kind in zip(names,fields,kinds)],ensure_ascii=False)
                      +'\n'+frame({name:'修正后的值' for name in names},identity,kind='2BYTE-PATCH/1'))
        text=text.replace('只返回合法 JSON 对象。','').replace(
            '返回 {"patches":[{"candidate_index":0,"path":"原path","value":"符合该replacement_schema的值"}]}。','').replace(
            '仅返回JSON对象 {"patches":[{"candidate_index":原编号,"path":"原path","value":修正值}]}。','')
        # The caller's source/diagnostics stay unchanged; remove the superseded
        # JSON envelope instruction before requesting raw source sections.
        kwargs.update(json_schema=None,response_kind='source_artifact')
        raw=complete(repair_id,[{'role':'user','content':text+'\n\n[output_protocol]\n'+instructions}],
                     _assembly=assembly,**kwargs)
        values,_=unframe(raw,identity,names,kind='2BYTE-PATCH/1')
        return {'patches':[dict(candidate_index=field['candidate_index'],path=field['path'],
                    value=values[name] if kind=='string' else json.loads(values[name]))
                    for name,field,kind in zip(names,fields,kinds)]}
    def patch(issues,repair_id,schema):
        numeric=all(issue['replacement_schema'].get('type') in ('number','integer','boolean') for issue in issues)
        if stage_callback:stage_callback(f'定点修复 {len(issues)} 个技术字段 · 完整重验')
        text=('只返回合法 JSON 对象。只修改白名单路径，保留全部未授权字段。CSS路径中的value@start:end只表示一个声明值，不能返回整段CSS。'
              '数值必须为有限数字，不用百分比字符串；selector只从已有内容class选择，不能更改宿主。'
              '本协议不接受.a.b复合选择器！只能用已有单一class（如.left，必须对应原目标），或空格/大于号分隔的后代class；不得凭空创建class。'
              'opacity范围0..1；xPercent/yPercent范围-100..100。允许有意的短暂淡入，合成可读性由渲染检查。'
              'material_binding只允许在cueHtml补入缺失材质class或aria-hidden=true的必要材质节点；已有节点、正文、属性、层级及CSS全部保持。'
              'css_url表示原值含不支持或危险资源：禁止网络/文件/脚本/任意data资源；可用受控静态SVG纹理或等价CSS渐变保留局部材质。url(#id)仅是SVG paint/filter引用，不能当CSS background-image；不要删除纹理来过关。'
              '返回 {"patches":[{"candidate_index":0,"path":"原path","value":"符合该replacement_schema的值"}]}。'
              '每个path恰好一次，context_ref指向共享DOM/CSS证据。禁止返回完整主题或其他候选。\n'+canonical(dict(
                  parent_request_id=parent_request_id,repair_request_id=repair_id,**compact_patch_context(issues))))
        from .authored_prompt import compose
        contract,_,_=text.partition('\n')
        text,assembly=compose(dict(step_contract=contract,diagnostics=dict(parent_request_id=parent_request_id,
            repair_request_id=repair_id,**compact_patch_context(issues))))
        assembly['schema_argument']=compose({'schema':schema})[1]['components']['schema']
        raw=patch_call(issues,repair_id,text,assembly,timeout=seconds(45,90),max_tokens=4096,json_schema=schema,
            operation_kind='numeric_patch' if numeric else 'local_patch',
            input_scope={'allowed_paths':[issue['path'] for issue in issues],'kind':'validator_owned_leaves_and_css_values'},cancel_check=cancel_check)
        return RepairResponse(raw,receipt())
    def regenerate(brief,repair_id,schema):
        if stage_callback:stage_callback(f"仅重做候选 {brief['candidate_id']} · 其余源码保持")
        # The local program owns the unchanged envelope. Asking the model to
        # repeat a full candidate plus its full schema both wasted tokens and
        # invited unrelated font/palette changes. Return only diagnosed leaves.
        index=brief['candidate_index'];source=brief['original_candidate']
        fields=[]
        for path in brief['allowed_paths']:
            issue=next(i for i in brief['issues'] if i['path']==path)
            value=issue.get('original_value') if issue.get('span') or not issue.get('exists',True) else get_leaf({'candidates':[{}]*index+[source]},path)
            replacement=issue.get('replacement_schema') or {'type':'string','minLength':1,
                'maxLength':_MAX_HTML_CHARS if path.endswith('Html') else _MAX_CSS_CHARS if path.endswith('Css') else 256}
            fields.append(dict(candidate_index=index,path=path,replacement_schema=replacement,
                original_value=value,exists=issue.get('exists',True),**{k:issue[k] for k in ('span','field_path','property') if k in issue}))
        schema=patch_schema(fields)
        compact_brief={k:v for k,v in brief.items() if k!='contexts'}
        compact_brief['issues']=[{k:v for k,v in i.items() if k not in ('context','context_ref')} for i in brief['issues']]
        text=('仅返回JSON对象 {"patches":[{"candidate_index":原编号,"path":"原path","value":修正值}]}。'
              '原候选完整附后，只修复列出的叶子；保持其他HTML节点、字形、配色、布局与身份。'
              '不复述完整候选。数值只取合法范围。宿主--wt-u是1.111111vh，在1920×1080时为12px，不是1px；'
              '原设计若用1920×1080像素坐标，定义候选内部--design-px:calc(100vh / 1080)，不可改写宿主单位。'
              'HTML禁止script、style、foreignObject、事件、外部资源；'
              'SVG只用原契约允许的原语；支持feGaussianBlur、feOffset、feComposite、feMerge与feMergeNode；feTurbulence的seed须为0..4096整数。不要增加不支持的标签。'
              '只可移除不支持的aria-label/title等属性，不改变class、正文及现有层级。CSS禁止url(data:)和外部URL。'
              '材质声明绑定真实存在且已有样式的材质节点。\n'+canonical(compact_brief))
        from .authored_prompt import compose,authoring_source
        compact_brief=copy.deepcopy(compact_brief)
        editable=compact_brief.pop('original_candidate')
        editable['generated_source']=authoring_source(editable['generated_source'])
        text,assembly=compose(dict(step_contract=text.partition('\n')[0],
            current_candidate=editable,diagnostics=compact_brief))
        assembly['schema_argument']=compose({'schema':schema})[1]['components']['schema']
        raw=patch_call(fields,repair_id,text,assembly,timeout=seconds(180,300),max_tokens=8000,json_schema=schema,
            operation_kind='regenerate_candidate',input_scope={'kind':'single_candidate','candidate_index':brief['candidate_index'],
                'allowed_paths':brief['allowed_paths'],'other_candidates':'not sent'},cancel_check=cancel_check)
        fixed,_=apply_patch_transaction({'candidates':[{}]*index+[source]},raw,fields)
        return RepairResponse(fixed['candidates'][index],receipt())
    return patch,regenerate


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
def path_text(parts):return ''.join(f'[{p}]' if isinstance(p,int) else ('.' if n else '')+p for n,p in enumerate(parts))


def path_parts(path):
    if not re.fullmatch(r'[A-Za-z_]\w*(?:(?:\.[A-Za-z_]\w*)|(?:\[\d+\]))*',path):raise ValueError('Invalid patch path')
    return [int(index) if index else name for name,index in re.findall(r'([A-Za-z_]\w*)|\[(\d+)\]',path)]


def get_leaf(value,path):
    for part in path_parts(path):value=value[part]
    return value


def set_leaf(value,path,replacement):
    parts=path_parts(path)
    for part in parts[:-1]:value=value[part]
    value[parts[-1]]=replacement


def css_values(text):
    """Lex declaration values with quoted strings, comments and nested functions."""
    begin=0;depth=0;paren=0;quote='';comment=False;escaped=False;colon=None;selector=''
    i=0
    while i<len(text):
        char=text[i]
        if comment:
            if text[i:i+2]=='*/':comment=False;i+=2;continue
        elif quote:
            if escaped:escaped=False
            elif char=='\\':escaped=True
            elif char==quote:quote=''
        elif text[i:i+2]=='/*':comment=True;i+=2;continue
        elif char in '\"\'':quote=char
        elif char=='(':paren+=1
        elif char==')':paren=max(0,paren-1)
        elif not paren:
            if char=='{':selector=text[begin:i].strip();depth+=1;begin=i+1;colon=None
            elif char==':' and depth and colon is None:colon=i
            elif char in ';}':
                if depth and colon is not None:
                    prop=text[begin:colon].strip()
                    if re.fullmatch(r'[-A-Za-z][\w-]*',prop):
                        start=colon+1
                        while start<i and text[start].isspace():start+=1
                        end=i
                        while end>start and text[end-1].isspace():end-=1
                        yield dict(property=prop,start=start,end=end,value=text[start:end],selector=selector)
                if char=='}':depth=max(0,depth-1)
                begin=i+1;colon=None
        i+=1


def local_context(source,selector):
    targets=set(re.findall(r'\.([A-Za-z][\w-]*)',selector))
    class Nodes(HTMLParser):
        def __init__(self):super().__init__();self.stack=[];self.chains=[];self.available=[]
        def handle_starttag(self,tag,attrs):
            row={'tag':tag,'attributes':dict(attrs)}
            if row['attributes'].get('class'):
                self.available.append(dict(tag=tag,classes=row['attributes']['class'],
                    parent_classes=self.stack[-1]['attributes'].get('class','') if self.stack else ''))
            if targets.intersection(dict(attrs).get('class','').split()):self.chains.append([*self.stack,row])
            if tag not in ('br','hr','img','input','meta','link'):self.stack.append(row)
        def handle_startendtag(self,tag,attrs):
            self.handle_starttag(tag,attrs)
            if self.stack and self.stack[-1]['tag']==tag:self.stack.pop()
        def handle_endtag(self,tag):
            for i in range(len(self.stack)-1,-1,-1):
                if self.stack[i]['tag']==tag:del self.stack[i:];break
    nodes=Nodes();nodes.feed(source.get('cueHtml',''))
    classes={name for chain in nodes.chains for node in chain for name in node['attributes'].get('class','').split()}
    css=source.get('cueCss','')+'\n'+source.get('stageCss','')
    declarations=list(css_values(css))
    return dict(parent_structure=nodes.chains,available_nodes=nodes.available if not nodes.chains else [],
        css_variables={d['property']:d['value'] for d in declarations if d['property'].startswith('--')},
        related_declarations=[{k:d[k] for k in ('selector','property','value')} for d in declarations
                              if classes.intersection(re.findall(r'\.([A-Za-z][\w-]*)',d['selector']))])


from .theme_dom import selector_targets


def equivalent_motion_selector(markup, selector):
    targets=selector_targets(markup,selector)
    if not targets:return None
    # Prefer an existing unique leaf class. Never animate its parent merely
    # because the parent's selector happens to pass the JSON Schema.
    for name in reversed(re.findall(r'\.([A-Za-z][\w-]*)',str(selector))):
        candidate='.'+name
        if SELECTOR.fullmatch(candidate) and candidate not in HOST_SELECTORS and selector_targets(markup,candidate)==targets:return candidate
    return None


def semantic_body_classes(markup):
    class Body(HTMLParser):
        def __init__(self):super().__init__();self.stack=[];self.classes=set()
        def handle_starttag(self,tag,attrs):
            if tag not in ('br','hr','img','input','meta','link'):self.stack.append((tag,dict(attrs)))
        def handle_startendtag(self,tag,attrs):pass
        def handle_endtag(self,tag):
            for index in range(len(self.stack)-1,-1,-1):
                if self.stack[index][0]==tag:del self.stack[index:];break
        def handle_data(self,text):
            if re.search(r'\{\{\s*(?:text|words)\s*\}\}',text) and not any(attrs.get('aria-hidden')=='true' for _,attrs in self.stack):
                self.classes.update(name for _,attrs in self.stack for name in attrs.get('class','').split())
                if '{{words}}' in text:self.classes.add('wt-w')
    body=Body();body.feed(markup);return body.classes


def collect_issues(payload,ledger):
    from .caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA,adapt_candidate,validate_material_contract
    from .web_theme import sanitize_html,sanitize_css,_FORBIDDEN_CSS_TOKENS
    issues=[];seen=set()
    def add(index,path,category,*,schema=None,value=None,exists=True,**details):
        # One transaction value per path, with the intersection of every
        # independent constraint (e.g. negative AND unreadable opacity).
        prior=next((row for row in issues if row['path']==path and row.get('replacement_schema')),None)
        if prior is not None and schema is not None:
            prior.setdefault('categories',[prior['category']])
            if category not in prior['categories']:prior['categories'].append(category)
            current=prior['replacement_schema']
            if schema.get('type')==current.get('type') and schema.get('type') in ('number','integer'):
                for key,combine in (('minimum',max),('maximum',min)):
                    if key in schema:current[key]=combine(current.get(key,schema[key]),schema[key])
            elif schema!=current:
                prior['replacement_schema']={'allOf':[current,schema]}
            return
        key=(path,category)
        if key in seen:return
        seen.add(key)
        row=dict(candidate_index=index,path=path,category=category,
            repair='regenerate' if category=='structural' or schema is None else 'patch',**details)
        if schema is not None:row.update(replacement_schema=schema,original_value=value,original_type=type(value).__name__,exists=exists)
        if isinstance(value,float) and not math.isfinite(value):row.update(original_value=None,original_repr=repr(value))
        issues.append(row)
    candidates=payload.get('candidates') if isinstance(payload,dict) else None
    if not isinstance(candidates,list) or not 1<=len(candidates)<=3:raise ValueError('One to three candidates are required before local repair')
    for index,row in enumerate(candidates):
        source=row.get('generated_source',{}) if isinstance(row,dict) else {}
        if not isinstance(source,dict):continue
        prefix=f'candidates[{index}].generated_source'
        roles=row.get('ColorRole')
        if isinstance(roles,list):
            names={item.get('role') for item in roles if isinstance(item,dict)}
            for role_index,item in enumerate(roles):
                if not isinstance(item,dict):continue
                target={'text':'contrast','accent':'highlight'}.get(item.get('role'))
                if target and target not in names:
                    add(index,f'candidates[{index}].ColorRole[{role_index}].role','role_name',
                        schema={'type':'string','const':target},value=item['role'],meaning='rename existing role, preserving its color and percent')
        if source.get('stageHtml'):
            add(index,prefix+'.stageHtml','stage_html',preserve='move original stage fragment and CSS into cue; never delete its artwork')
            issues[-1]['repair']='relocate'
        for field in ('cueCss','stageCss'):
            css=source.get(field,'')
            if not isinstance(css,str):continue
            for declaration in css_values(css):
                value=declaration['value']
                from .theme_texture_resource import checked_css_urls
                try:
                    remaining=checked_css_urls(value)
                    invalid=any(token.casefold() in remaining.casefold() for token in _FORBIDDEN_CSS_TOKENS)
                    resource_error='CSS contains a prohibited structure' if invalid else ''
                except ValueError as exc:invalid=True;resource_error=str(exc)
                if invalid:
                    path=prefix+'.'+field+f"::value@{declaration['start']}:{declaration['end']}"
                    add(index,path,'css_url',schema={'type':'string','minLength':1,'maxLength':4096},value=value,
                        expected='仅内部SVG引用、受控静态SVG纹理data URL或等价CSS纹理；禁止网络、脚本、递归资源。保留全部材质。',
                        constraint=resource_error,stage='technical_validation',blocking=True,
                        validator_version='static-svg-2',candidate_id=row.get('id'),
                        field_path=prefix+'.'+field,span=[declaration['start'],declaration['end']],
                        context=local_context(source,declaration['selector']),property=declaration['property'])
        spec=source.get('motionSpec',{})
        if isinstance(spec,dict) and isinstance(spec.get('tracks'),list):
            for track_index,track in enumerate(spec['tracks']):
                if not isinstance(track,dict):continue
                repeat=track.get('repeat',0)
                if type(repeat) is int and repeat>0 and track.get('phase') in ('build','resolve'):
                    add(index,f'{prefix}.motionSpec.tracks[{track_index}].repeat','motion_repeat_phase',
                        schema={'type':'integer','minimum':0,'maximum':0},value=repeat,
                        stage='technical_validation',blocking=True,
                        constraint='重复材质动作只允许在阅读阶段；入场和退场保留单次动作。',
                        context={'track':track,'rule':'只把此轨道repeat改为0；保留目标、阶段、窗口、from/to及其他所有动画，不删除材质。'})
                start=track.get('from');end=track.get('to')
                if isinstance(start,dict) and isinstance(end,dict):
                    for state,other,name in ((start,end,'from'),(end,start,'to')):
                        for prop,value in state.items():
                            if prop in NUMERIC and (type(value) not in (int,float) or not math.isfinite(value)
                                    or not NUMERIC[prop][0]<=value<=NUMERIC[prop][1]):
                                category='numeric_range' if type(value) in (int,float) and math.isfinite(value) else 'numeric_type'
                                add(index,f'{prefix}.motionSpec.tracks[{track_index}].{name}.{prop}',category,
                                    schema=copy.deepcopy(MOTION_STATE_SCHEMA['properties'][prop]),value=value,
                                    context={'phase':track.get('phase'),'selector':track.get('selector')})
                        for prop in other.keys()-state.keys():
                            schema=MOTION_STATE_SCHEMA['properties'].get(prop)
                            if schema:
                                add(index,f'{prefix}.motionSpec.tracks[{track_index}].{name}.{prop}','from_to',
                                    schema=copy.deepcopy(schema),value=None,exists=False,context={'track':track})
    for error in jsonschema.Draft202012Validator(AUTHORED_OUTPUT_SCHEMA).iter_errors(payload):
        parts=list(error.absolute_path);path=path_text(parts)
        index=parts[1] if len(parts)>1 and parts[0]=='candidates' and isinstance(parts[1],int) else -1
        if index<0:raise ValueError('Candidate set structure does not permit local repair')
        if path.endswith('.stageHtml') and isinstance(error.instance,str):continue
        if path.endswith(('.cueCss','.stageCss')) and any(r.get('field_path')==path for r in issues):continue
        schema=error.schema;expected=schema.get('type')
        if error.validator=='contains' and path.endswith('.ColorRole'):
            target=error.validator_value.get('properties',{}).get('role',{}).get('const')
            if any(i['candidate_index']==index and i.get('replacement_schema',{}).get('const')==target for i in issues):continue
        if '.motionSpec.tracks[' in path and path.endswith('.selector'):
            source=candidates[index].get('generated_source',{})
            equivalent=equivalent_motion_selector(source.get('cueHtml',''),error.instance)
            add(index,path,'target_selector' if equivalent else 'selector',
                schema={**copy.deepcopy(schema),**({'const':equivalent} if equivalent else {})},value=error.instance,
                context=local_context(source,str(error.instance)))
        elif '.motionSpec.tracks[' in path and path.endswith('.ease'):
            from .theme_motion import EASES,STEPS_PATTERN
            add(index,path,'easing',schema={'anyOf':[{'enum':sorted(EASES)},{'type':'string','pattern':'^'+STEPS_PATTERN+'$'}]},
                value=error.instance,expected='有限缓动白名单：'+', '.join(sorted(EASES))+' 或 '+STEPS_PATTERN)
        elif path.endswith('.MaterialContract.selectors') and isinstance(error.instance,str):
            selectors=[value.strip() for value in error.instance.split(',') if value.strip()]
            add(index,path,'value_type',schema={'type':'array','items':{'type':'string'},'const':selectors},value=error.instance,
                meaning='convert the same comma-separated selectors to an array; no selector may be dropped')
        elif expected in ('number','integer','boolean') and not isinstance(error.instance,(dict,list)):
            category='numeric_range' if error.validator in ('minimum','maximum') else 'numeric_type'
            add(index,path,category,schema=copy.deepcopy(schema),value=error.instance)
        elif expected=='string' and not path.endswith(('cueHtml','cueCss','stageHtml','stageCss')) and not isinstance(error.instance,(dict,list)):
            add(index,path,'single_value',schema=copy.deepcopy(schema),value=error.instance)
        elif error.validator=='required' and isinstance(error.instance,dict):
            for field in error.validator_value:
                if field in error.instance:continue
                field_schema=schema.get('properties',{}).get(field)
                if field=='name' and field_schema:
                    add(index,path+'.'+field,'single_value',schema=field_schema,value=None,exists=False)
                else:add(index,path+'.'+field,'structural',constraint='required',
                    schema=copy.deepcopy(field_schema) if field_schema else None,exists=False)
        else:add(index,path,'structural',constraint=error.validator)
    for index,row in enumerate(candidates):
        source=row.get('generated_source',{}) if isinstance(row,dict) else {}
        if not isinstance(source,dict):continue
        prefix=f'candidates[{index}].generated_source'
        from .motion_ownership import MotionOwnershipError
        spec=source.get('motionSpec',{})
        try:validate_motion_spec(source.get('motionSpec'),cue_html=source.get('cueHtml',''))
        except MotionOwnershipError as exc:
            for conflict in exc.issues:
                if conflict['category']=='motion_target':
                    ti=conflict['track_indices'][0]
                    add(index,f'{prefix}.motionSpec.tracks[{ti}].selector','selector',
                        schema=copy.deepcopy(MOTION_OUTPUT_SELECTOR_SCHEMA),value=source['motionSpec']['tracks'][ti]['selector'],
                        context={**local_context(source,conflict['selector']),'diagnostic':conflict})
                else:
                    for ti in conflict['track_indices']:
                        track=source['motionSpec']['tracks'][ti]
                        for field in ('start','end'):
                            add(index,f'{prefix}.motionSpec.tracks[{ti}].{field}','motion_conflict',
                                schema={'type':'number','minimum':0,'maximum':1},value=track.get(field,0 if field=='start' else 1),
                                exists=field in track,context={'diagnostic':conflict,'tracks':[
                                    {'index':n,**source['motionSpec']['tracks'][n]} for n in conflict['track_indices']],
                                    'rule':'只调整这些动作的相位内窗口；保留from/to、阶段、目标与全部动作。start<end，使用共享边界；不得删除或关闭动画。'})
        except (ValueError,KeyError,TypeError) as exc:
            # Preserve the failing subsystem, instead of turning a motion
            # diagnostic into an unrepairable candidate-wide replacement.
            if not any(i['candidate_index']==index and '.motionSpec' in i['path'] for i in issues):
                add(index,prefix+'.motionSpec','motion_structure',
                    schema=copy.deepcopy(MOTION_OUTPUT_SCHEMA),value=spec,
                    constraint=str(exc),context={'motionSpec':spec,
                        'rule':'只修复明确不兼容的动作字段；保留全部目标、动作、阶段及合法值。'})
        for section in ('cue','stage'):
            markup=source.get(section+'Html','')
            if not isinstance(markup,str):continue
            from .authored_html import html_problems,html_signature
            problems=html_problems(markup)
            if problems:
                add(index,prefix+'.'+section+'Html','structural',constraint='；'.join(problems),
                    html_problems=problems)
            try:
                sanitized=sanitize_html(markup,section=section)
                if html_signature(markup)!=html_signature(sanitized):add(index,prefix+'.'+section+'Html','structural',constraint='HTML sanitization changes author structure or attributes')
            except ValueError as exc:add(index,prefix+'.'+section+'Html','structural',constraint=str(exc)[:240])
        # Independently validate semantic contracts, without letting a numeric
        # failure hide a missing material or a different requested theme.
        probe=copy.copy(ledger);probe.value=copy.deepcopy(ledger.value);probe.save=lambda:None
        for field in ('art_direction_contract','design_spec'):
            if isinstance(row.get(field),dict):
                try:probe.stage(field,row[field],candidate_id=row.get('id',''),require_semantics=True)
                except ValueError as exc:add(index,f'candidates[{index}].'+field,'structural',constraint=str(exc)[:240])
        if not any(issue['candidate_index']==index and issue['category']!='dom_collision' for issue in issues):
            try:adapt_candidate(row,probe)
            except (ValueError,KeyError,TypeError) as exc:add(index,f'candidates[{index}]','structural',constraint=str(exc)[:240])
    return issues


def patch_schema(issues):
    choices=[]
    for issue in issues:
        choices.append({'type':'object','additionalProperties':False,'required':['candidate_index','path','value'],
            'properties':{'candidate_index':{'const':issue['candidate_index']},'path':{'const':issue['path']},
                          'value':issue['replacement_schema']}})
    return {'type':'object','additionalProperties':False,'required':['patches'],'properties':{
        'patches':{'type':'array','minItems':len(issues),'maxItems':len(issues),'items':{'anyOf':choices}}}}


def item_context(item):
    return {'actual':item['actual'],'expected':item['expected'],'context':item,'constraint':item['actual']}


def apply_patch_transaction(payload,response,issues):
    from .structured_output import response_object
    response=copy.deepcopy(response_object(response))
    # Providers sometimes return the declared leaf relative to their explicit
    # candidate_index. Resolve only an exact allowed pair; never guess a target
    # or normalize arbitrary traversal/path syntax.
    allowed_pairs={(issue['candidate_index'],issue['path']) for issue in issues}
    for patch in response.get('patches',[]) if isinstance(response,dict) else []:
        if not isinstance(patch,dict):continue
        path=patch.get('path');index=patch.get('candidate_index')
        full=f'candidates[{index}].{path}'
        if isinstance(path,str) and (index,full) in allowed_pairs:
            patch['path']=full
    try:jsonschema.validate(response,patch_schema(issues))
    except jsonschema.ValidationError as exc:
        path=path_text(list(exc.absolute_path))
        raise ValueError(f'$.{path}: Provider修复不符合{exc.validator}约束；原候选保留') from None
    allowed={issue['path']:issue for issue in issues};seen=set();output=copy.deepcopy(payload);css={}
    for patch in response['patches']:
        path=patch['path'];issue=allowed[path]
        if path in seen:raise ValueError('Duplicate repair path')
        seen.add(path);value=patch['value']
        if isinstance(value,float) and not math.isfinite(value):raise ValueError('Nonfinite repair value')
        if issue.get('allowed_material_classes'):
            from .material_contract import validate_material_html_edit
            validate_material_html_edit(get_leaf(payload,path),value,set(issue['allowed_material_classes']))
        if issue.get('span'):
            css.setdefault(issue['field_path'],[]).append((issue,value))
        else:set_leaf(output,path,value)
    if seen!=set(allowed):raise ValueError('Missing repair paths')
    for path,edits in css.items():
        text=get_leaf(payload,path);last=len(text)+1
        for issue,value in sorted(edits,key=lambda item:item[0]['span'][0],reverse=True):
            begin,end=issue['span']
            if end>last or text[begin:end]!=issue['original_value']:raise ValueError('CSS span changed or overlaps')
            text=text[:begin]+value+text[end:];last=begin
        set_leaf(output,path,text)
    changes=changed_paths(payload,output)
    roots={issue.get('field_path',issue['path']) for issue in issues}
    if set(changes)!=roots:raise ValueError('Repair diff exceeds or misses the allowed leaves')
    return output,changes


def repair_authored(payload,*,ledger,provider,model,parent_request_id,validate,patch_request,regenerate_request,cancel_check=None,candidate_indices=None):
    from .ai_providers import AIProviderError
    def check():
        if cancel_check and cancel_check():raise AIProviderError('Technical repair cancelled or parent identity changed',category='cancelled')
    def verify(value):
        try:validate(value);return {'passed':True}
        except (ValueError,KeyError,TypeError) as exc:return {'passed':False,'error':str(exc)[:400]}
    def scan(value):
        return [issue for issue in collect_issues(value,ledger)
                if candidate_indices is None or issue['candidate_index'] in candidate_indices]
    check();working=copy.deepcopy(payload);initial=scan(working)
    ledger.value['aggregate_technical_errors']=initial;ledger.save()
    if not initial:return working
    receipts=ledger.value.setdefault('technical_repairs',[])
    # A constant GSAP origin at track level has one exact representation in
    # our vocabulary. This is an explicit local revision, not a permissive
    # validator or deletion of an unknown field. Conflicts remain errors.
    from .theme_motion import ORIGIN_PATTERN
    for index,row in enumerate(working['candidates']):
        if candidate_indices is not None and index not in candidate_indices:continue
        before=copy.deepcopy(working)
        for track in row.get('generated_source',{}).get('motionSpec',{}).get('tracks',[]):
            origin=track.get('transformOrigin')
            if (not isinstance(origin,str) or not re.fullmatch(ORIGIN_PATTERN,origin)
                    or not all(isinstance(track.get(k),dict) and track[k].get('transformOrigin',origin)==origin
                               for k in ('from','to'))):continue
            for k in ('from','to'):track[k]['transformOrigin']=origin
            del track['transformOrigin']
        changes=changed_paths(before,working)
        if changes:
            check()
            receipts.append(dict(parent_request_id=parent_request_id,repair_request_id=uuid.uuid4().hex,
                operation='local_constant_motion_origin',model_calls=0,actual_cost_usd=0,
                changed_paths=changes,before_hash=digest(before),after_hash=digest(working),
                validation=verify(working),status='applied'))
            ledger.save()
    # Exact relocation is a local transaction, with all authored bytes kept.
    for index,row in enumerate(working['candidates']):
        if candidate_indices is not None and index not in candidate_indices:continue
        source=row.get('generated_source',{})
        if not isinstance(source,dict) or not isinstance(source.get('stageHtml'),str) or not source['stageHtml'].strip():continue
        before=copy.deepcopy(working);check()
        source['cueHtml']=source['stageHtml']+source.get('cueHtml','')
        source['cueCss']=source.get('stageCss','')+'\n'+source.get('cueCss','')
        source['stageHtml']='';source['stageCss']=''
        changes=changed_paths(before,working)
        allowed={f'candidates[{index}].generated_source.{field}' for field in ('stageHtml','stageCss','cueHtml','cueCss')}
        if not set(changes)<=allowed:raise ValueError('Stage migration changed an unrelated field')
        receipts.append(dict(parent_request_id=parent_request_id,repair_request_id=uuid.uuid4().hex,
            operation='local_stage_relocation',model_calls=0,actual_cost_usd=0,changed_paths=changes,
            before_hash=digest(before),after_hash=digest(working),validation=verify(working),status='applied'))
        ledger.save()
    issues=scan(working)
    exact=[issue for issue in issues if issue['category'] in ('role_name','value_type','target_selector')
           and 'const' in issue.get('replacement_schema',{})]
    if exact:
        # These are exact metadata conversions, with no aesthetic choice:
        # text/accent role aliases and the same CSV selectors as an array.
        # Keep them out of the model request rather than inviting the model
        # to echo a schema object where a literal constant is required.
        check();before=working
        response={'patches':[dict(candidate_index=i['candidate_index'],path=i['path'],value=copy.deepcopy(i['replacement_schema']['const'])) for i in exact]}
        working,changes=apply_patch_transaction(working,response,exact);check()
        receipts.append(dict(parent_request_id=parent_request_id,repair_request_id=uuid.uuid4().hex,
            operation='local_exact_metadata',model_calls=0,actual_cost_usd=0,allowed_paths=[i['path'] for i in exact],
            changed_paths=changes,before_hash=digest(before),after_hash=digest(working),validation=verify(working),status='applied'))
        ledger.save();issues=scan(working)
    structural={issue['candidate_index'] for issue in issues if issue['repair']=='regenerate'}
    patchable=[issue for issue in issues if issue['repair']=='patch' and issue['candidate_index'] not in structural]
    if patchable:
        if patch_request is None:raise ValueError('Technical patch required: '+', '.join(i['path'] for i in patchable))
        check();request_id=uuid.uuid4().hex;started=time.monotonic()
        record=dict(parent_request_id=parent_request_id,repair_request_id=request_id,operation='technical_patch',
            provider=provider,model=model,allowed_paths=[i['path'] for i in patchable],status='requesting',actual_cost_usd=None)
        receipts.append(record);ledger.save()
        try:
            raw=patch_request(copy.deepcopy(patchable),request_id,patch_schema(patchable));check()
            if isinstance(raw,RepairResponse):record.update(raw.receipt);raw=raw.value
            (ledger.root/f'technical-{request_id}.json').write_text(canonical(raw),'utf8')
            before=working;working,changes=apply_patch_transaction(working,raw,patchable);check()
            record.update(changed_paths=changes,before_hash=digest(before),after_hash=digest(working),validation=verify(working))
            remaining=scan(working)
            patched_indices={issue['candidate_index'] for issue in patchable}
            if any(issue['repair']=='patch' and issue['candidate_index'] in patched_indices for issue in remaining):raise ValueError('Technical patch still violates local constraints')
            record['status']='applied'
        except Exception as exc:
            record.update(getattr(exc,'repair_receipt',{}))
            exc.retained_payload=copy.deepcopy(before if 'before' in locals() else payload)
            record.update(status='cancelled' if getattr(exc,'category','')=='cancelled' else 'rejected',error=str(exc)[:500]);raise
        finally:record['elapsed_seconds']=time.monotonic()-started;ledger.save()
    regenerated=set()
    while True:
        check();issues=scan(working)
        if not issues:break
        index=next((i['candidate_index'] for i in issues if i['repair']=='regenerate'),issues[0]['candidate_index'])
        if index in regenerated or len(regenerated)>=3 or regenerate_request is None:
            raise ValueError('Candidate repair budget exhausted: '+', '.join(i['path'] for i in issues))
        regenerated.add(index);request_id=uuid.uuid4().hex;started=time.monotonic();before=copy.deepcopy(working)
        record=dict(parent_request_id=parent_request_id,repair_request_id=request_id,operation='regenerate_candidate',candidate_index=index,
            provider=provider,model=model,allowed_paths=[f'candidates[{index}]'],status='requesting',actual_cost_usd=None)
        receipts.append(record);ledger.save()
        try:
            from .caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA
            candidate_issues=[i for i in issues if i['candidate_index']==index]
            allowed_paths=sorted({i['path'] for i in candidate_issues})
            # An unknown candidate-wide error is not permission to redesign it.
            if f'candidates[{index}]' in allowed_paths:
                raise ValueError('无法安全定位局部修复范围：'+str(candidate_issues))
            record['allowed_paths']=allowed_paths
            brief=dict(candidate_index=index,candidate_id=working['candidates'][index]['id'],
                requested_theme=ledger.value['raw_user_prompt'],**compact_patch_context([i for i in issues if i['candidate_index']==index]),
                visibility_policy='composed-timeline-v2',allowed_paths=allowed_paths,
                original_candidate=working['candidates'][index])
            raw=regenerate_request(brief,request_id,AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']);check()
            if isinstance(raw,RepairResponse):record.update(raw.receipt);raw=raw.value
            from .structured_output import response_object
            candidate=response_object(raw)
            if candidate.get('id')!=brief['candidate_id']:raise ValueError('Regeneration changed candidate identity')
            (ledger.root/f'technical-{request_id}.json').write_text(canonical(raw),'utf8')
            working['candidates'][index]=candidate
            changes=changed_paths(before,working)
            if any(not path.startswith(f'candidates[{index}].') for path in changes):raise ValueError('Regeneration changed a different candidate')
            if any(not any(path==p or path.startswith(p+'.') or path.startswith(p+'[') for p in allowed_paths) for path in changes):
                raise ValueError('局部结构修复改变了未授权的字体、配色、布局、名称或身份；原候选保留')
            check();record.update(changed_paths=changes,before_hash=digest(before),after_hash=digest(working),validation=verify(working))
            remaining=[i for i in scan(working) if i['candidate_index']==index]
            if remaining:
                # A regenerated structure can introduce a small typed error.
                # Permit one scoped transaction within the shared two-patch
                # budget, then validate again; never delete a failing row.
                patch_count=sum(r['operation'] in ('technical_patch','regenerated_candidate_patch') for r in receipts)
                if any(i['repair']!='patch' for i in remaining) or patch_request is None or patch_count>=2:
                    raise ValueError('Regenerated candidate contract failed: '+', '.join(i['path']+': '+i['category'] for i in remaining))
                patch_id=uuid.uuid4().hex
                repair_record=dict(parent_request_id=parent_request_id,repair_request_id=patch_id,
                    operation='regenerated_candidate_patch',candidate_index=index,provider=provider,model=model,
                    allowed_paths=[i['path'] for i in remaining],status='requesting',actual_cost_usd=None)
                receipts.append(repair_record);ledger.save()
                try:
                    patch=patch_request(copy.deepcopy(remaining),patch_id,patch_schema(remaining));check()
                    if isinstance(patch,RepairResponse):repair_record.update(patch.receipt);patch=patch.value
                    (ledger.root/f'technical-{patch_id}.json').write_text(canonical(patch),'utf8')
                    before_patch=working
                    working,patch_changes=apply_patch_transaction(working,patch,remaining);check()
                    repair_record.update(changed_paths=patch_changes,before_hash=digest(before_patch),after_hash=digest(working))
                    remaining=[i for i in scan(working) if i['candidate_index']==index]
                    if remaining:raise ValueError('Regenerated candidate patch rejected: '+', '.join(i['path'] for i in remaining))
                    repair_record['status']='applied'
                except Exception as exc:
                    repair_record.update(status='rejected',error=str(exc)[:500]);raise
                finally:ledger.save()
            record['status']='applied'
        except Exception as exc:
            record.update(getattr(exc,'repair_receipt',{}))
            exc.retained_payload=copy.deepcopy(before)
            record.update(status='cancelled' if getattr(exc,'category','')=='cancelled' else 'rejected',error=str(exc)[:500]);raise
        finally:record['elapsed_seconds']=time.monotonic()-started;ledger.save()
    check();validate(working);check()
    ledger.value['technical_repaired_payload_hash']=digest(working);ledger.save()
    return working
