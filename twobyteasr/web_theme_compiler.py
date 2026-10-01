"""Bounded same-model design compilation; no provider or theme fallback."""
from __future__ import annotations
import copy
import base64
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Mapping

from .ai_providers import AIProviderError
from .theme_draft import canonical_theme, theme_structure
from .web_theme import WebThemeDocument, parse_web_theme_sections, validate_generated_theme
from .theme_generation_policy import ThemeGenerationLimits


BRIEF_FIELDS = ('style','mood','scope','anchor','foreground','midground','background',
                'materials','palette_ratio','typography','entrance','hold','exit',
                'forbidden_patterns','performance_level','transparent','allow_vignette')
REPAIR_SYSTEM = '''修复提供的完整字幕主题，只修改列出的缺陷。保留名称、视觉主体、
语义class、主题文字框、可辨识角色、场景物件、配色与三段动画意图；禁止用删框或缩角色解决错误。
明确动画修订允许改相关图层及动作，用户已否定的主动作/扫白亮带不冻结。非发光纹理和刻槽应稳定，不强制所有材料循环。
输出完整原格式，禁止删段、省略、脚本、
网络资源、自动重播。{{text}}或{{words}}必须保留；--wt-dur为cue时长；
舞台透明，主字幕在指定安全区。CONCEPT点名物件必须对应实际HTML/CSS。
如果原稿有motionSpec，完整保留MOTION_SPEC分节及GSAP单一权威，CSS保持静态，不改宿主placement。
build/breathe/resolve有限、同属性无重叠、至少65%阅读时间；不转换成CSS keyframes。'''


def parse_object(raw):
    from .structured_output import response_object
    return response_object(raw)


def parse_critique(raw):
    try:
        value=parse_object(raw)
        if not isinstance(value.get('passed'),bool) or not isinstance(value.get('defects'),list):
            raise ValueError('需要passed布尔值和defects数组')
        if not value['passed'] and not value['defects']:
            raise ValueError('拒收必须列出具体缺陷')
        return value
    except (ValueError,TypeError) as exc:
        raise AIProviderError('视觉复核格式无效，已保留可渲染主题：'+str(exc),category='visual_review_error') from exc


def choose_concept(payload, scope):
    brief = payload.get('brief')
    concepts = payload.get('concepts')
    if not isinstance(brief,dict) or any(key not in brief for key in BRIEF_FIELDS):
        raise ValueError('设计brief字段不完整')
    if not isinstance(concepts,list) or len(concepts)!=3:
        raise ValueError('需要恰好三个轻量概念方向')
    seen = set()
    for index, concept in enumerate(concepts):
        if not isinstance(concept,dict): raise ValueError('概念必须为结构化对象')
        for key in ('id','name','subject','composition','palette','materials','motion',
                    'signature_elements','risks','estimated_performance'):
            if key not in concept: raise ValueError('概念缺少字段：'+key)
        if not isinstance(concept['motion'],dict) or any(not concept['motion'].get(p) for p in ('entrance','hold','exit')):
            raise ValueError('概念需有入场、持续和出场动作')
        if len(str({k:v for k,v in concept.items() if k not in ('hero_theme','design_markdown')})) > 9000:
            raise ValueError('概念说明过长')
        elements = concept['signature_elements']
        if not isinstance(elements,list) or not (1 if payload.get('schema_version')==2 else 3)<=len(elements)<=8:
            raise ValueError('概念需有3至8个具象物件')
        identity = (str(concept['subject']),str(concept['composition']))
        if identity in seen: raise ValueError('三个概念的主体与构图不能重复')
        seen.add(identity)
        concept['id'] = str(concept['id'] or chr(65+index))
        if not isinstance(concept['risks'],list): raise ValueError('风险必须是数组')
        cost = str(concept['estimated_performance']).lower()
        if cost not in ('low','medium','high'): raise ValueError('性能开销须为low/medium/high')
        text = json.dumps(concept,ensure_ascii=False).lower()
        criteria = dict(motion=20,identity=min(20,len(set(map(str,elements)))*4),
            readability=15 if re.search('中文|可读|清晰|安全区|safe|legib',text) else 5,
            palette=15 if re.search('70|25|5%|材质|哑光|matte|steel',text) else 8,
            performance={'low':20,'medium':13,'high':4}[cost],
            obstruction=max(0,10-len(concept['risks'])*2))
        if 'design' not in concept:
            concept['rule_score'] = sum(criteria.values())
            concept['score_details'] = criteria
        else:
            concept.pop('rule_score',None);concept.pop('score_details',None)
    if len(set(c['id'] for c in concepts)) != 3: raise ValueError('概念id必须不同')
    brief['scope'] = scope
    brief['transparent'] = True
    return brief,concepts,concepts[0] if all('design' in c for c in concepts) else max(concepts,key=lambda c:c.get('rule_score',0))


def code_gate(raw, instruction, scope, design_version=1, *, request_id='', metadata_repair=None, cancel_check=None, metadata_event=None):
    from .theme_metadata import parse_theme_input, recover_generated_names
    parsed = recover_generated_names({'webTheme':parse_theme_input(raw)},
        request_id=request_id or 'legacy',repair=metadata_repair,cancel_check=cancel_check,event=metadata_event)['webTheme']
    doc = WebThemeDocument.from_dict(parsed)
    validate_generated_theme(doc,instruction=instruction,design_version=design_version)
    normalized = doc.to_dict()
    warnings = []
    for key in ('stageHtml','stageCss','cueHtml','cueCss'):
        if str(parsed.get(key,'')) != str(normalized.get(key,'')):
            warnings.append(key+'经安全清理；已记录前后结构')
    css = normalized['cueCss']
    if design_version==2 and 'DESIGN_V2_HERO_GSAP' in doc.notes and not doc.motion_spec:
        raise ValueError('新主题必须从MotionSpec编译GSAP时间线')
    if not doc.motion_spec and not re.search(r'--wt-dur',css): raise ValueError('出场必须使用--wt-dur')
    if not doc.motion_spec and scope=='fullscreen' and (not normalized['stageHtml'].strip() or not re.search(r'animation\s*:',normalized['stageCss'])):
        raise ValueError('全画面方向必须含有效stage动效和cue字幕层')
    if len(re.findall(r'filter\s*:|box-shadow\s*:',css+normalized['stageCss']))>12:
        warnings.append('较多filter/阴影，需检查实时帧率')
    return normalized,dict(parsed=theme_structure(parsed),sanitized=theme_structure(normalized),
                           sanitizer_changes=warnings)


def prepare_static_v3_options(payload, text, *, asset_root, background_data=""):
    """Compile a complete static review set without Provider or motion calls.

    Kept separate from WebThemeDocument/GSAP execution: a static design is not
    yet an approved animated theme. The local browser is the review consumer.
    """
    from .theme_art_direction_v2 import validate_art_direction
    from .theme_design_spec_v3 import compile_static_html, optional_motif, DesignSpecError
    value = validate_art_direction(copy.deepcopy(payload))
    concepts = value.get('concepts', [])
    if len(concepts) != 3 or any(c['design'].get('visual_contract_version') != 3 for c in concepts):
        raise DesignSpecError('静态选择门需要恰好三个V3设计')
    for key, getter in (
        ('底板结构', lambda d:d['local_backplate']['structure']),
        ('整体轮廓', lambda d:d['composition_silhouette']['description']),
        ('字体', lambda d:d['font_family']),
    ):
        if len({getter(c['design']) for c in concepts}) != 3:
            raise DesignSpecError('三个静态方向必须有不同的'+key)
    asset_status={c['id']:optional_motif(c['design'],asset_root)[1] for c in concepts}
    return dict(visual_contract_version=3, selected_concept_id='', motion_authored=False,
                asset_status=asset_status,
                options=[dict(id=c['id'], name=c['name'], design=copy.deepcopy(c['design']),
                              html=compile_static_html(c['design'], text, asset_root=asset_root, background_data=background_data))
                         for c in concepts])


def compile_theme(project,cue_id,instruction,runtime_settings=None,*,deadline_seconds=None,
                  cancel_check=None,stage_callback=None,on_stream_text=None,effect_scope='subtitle',
                  request_id='',render_validator=None,stage_event_callback=None,resume_design=None,
                  concepts_only=False,reference_frames=()):
    from . import studio_ai as api
    GLOBAL_PROVIDER_REGISTRY = api.GLOBAL_PROVIDER_REGISTRY
    from .studio_commands import cue_by_id
    from .theme_draft import digest
    # Every new request first produces reviewable static directions. Legacy
    # themes remain readable, but no new request enters the old CSS generator.
    concepts_only=bool(concepts_only or not (resume_design or {}).get('concepts'))
    started=time.monotonic()
    settings=copy.deepcopy(runtime_settings or GLOBAL_PROVIDER_REGISTRY.settings())
    models=settings.get('models',{})
    limits=ThemeGenerationLimits.from_settings(models,deadline_seconds)
    budget=limits.concepts
    deadline=started+budget
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    provider=api.provider_for_stage(settings,'polish')
    request_id=request_id or uuid.uuid4().hex
    cue=cue_by_id(project,cue_id)
    speaker=next((s.name for s in project.speakers if s.id==cue.speaker_id),'')
    trace=dict(schema_version=2,stage='studio_web_theme_compiler',request_id=request_id,
        cue_id=cue_id,instruction=instruction,scope=effect_scope,raw_provider_responses=[],
        validation_errors=[],provider=dict(provider=selection.provider,model=selection.model),
        web_theme_source='failed',repair_count=0,phases=[])
    beat=time.monotonic()
    active_phase=None
    metadata_attempted=False
    def progress(value):
        if stage_callback: stage_callback(value)
    def publish_phase(**fields):
        if active_phase is None:return
        active_phase.update(fields)
        if stage_event_callback:stage_event_callback(copy.deepcopy(active_phase))
    def begin_phase(name, label, seconds):
        nonlocal deadline,beat,active_phase
        if cancel_check and cancel_check():raise AIProviderError('当前设计已取消',category='cancelled')
        beat=time.monotonic();deadline=beat+seconds
        active_phase=dict(name=name,label=label,request_id=request_id+'/'+name+'/'+uuid.uuid4().hex,
            started_monotonic=beat,last_output_monotonic=beat,status='running',timeout_seconds=seconds,
            inactivity_seconds=limits.inactivity,provider_state='starting',output_chars=0,
            stage_kind={'concepts':'brief_concepts','theme_code':'theme_recipe_or_code','validation':'parse_validate',
                'render':'render_preview'}.get(name,name))
        trace['phases'].append(active_phase)
        if trace.get('concepts'):
            active_phase['design']=dict(schema_version=design_version,brief=copy.deepcopy(trace['brief']),concepts=copy.deepcopy(trace['concepts']),selected_concept_id='' if concepts_only else trace.get('selected_concept_id',''))
        publish_phase();progress(label)
    def finish_phase(**fields):
        publish_phase(status='complete',finished_monotonic=time.monotonic(),**fields)
    def provider_diagnostics():
        getter=getattr(provider,'invocation_trace',None)
        return getter() if callable(getter) else getattr(provider,'last_invocation_trace',{})
    def cancelled():
        if cancel_check and cancel_check():return True
        now=time.monotonic()
        if now>deadline:
            raise AIProviderError('当前阶段达到总时限，可单独重试主题代码',category='provider_total_timeout')
        if now-beat>limits.inactivity:
            raise AIProviderError(f'Provider 已连续 {limits.inactivity:g} 秒没有输出活动，可单独重试主题代码',category='provider_inactivity_timeout')
        return False
    def remaining():
        if cancel_check and cancel_check(): raise AIProviderError('当前设计已取消',category='cancelled')
        left=deadline-time.monotonic()
        if left<=0: raise AIProviderError('当前阶段超过时限，可单独重试',category=(active_phase or {}).get('name','provider')+'_timeout')
        return left
    def call(phase,system,prompt,tokens,images=()):
        nonlocal beat
        name={'理解字幕与画面':'art_direction','生成三个概念':'concepts','编写选定主题':'theme_code'}.get(phase,'hero' if phase.startswith('静态英雄帧') else 'theme_repair' if '修复' in phase else 'visual_review')
        begin_phase(name,phase,limits.theme if name in ('theme_code','theme_repair','hero') else budget)
        # Shared adapter enforces context and actual transport budgets, including
        # file/stdin. A prompt-character argv guard is invalid here.
        pending=[];partial=[];last_flush=time.monotonic();call_started=last_flush
        def event(kind,detail):
            nonlocal beat,last_flush
            beat=time.monotonic()
            active_phase['last_output_monotonic']=beat
            active_phase['provider_state']={'thinking':'thinking','thinking_end':'awaiting_body','delta':'streaming',
                'final':'complete','stderr':'stderr'}.get(kind,'active')
            if kind=='delta':
                partial.append(str(detail))
                active_phase['output_chars']+=len(str(detail))
                pending.append(str(detail))
                if on_stream_text and beat-last_flush>=.25:
                    on_stream_text(''.join(pending));pending.clear();last_flush=beat
            if beat-last_flush>=1. or kind in ('thinking_end','final'):
                labels={'thinking':'Provider 正在思考','thinking_end':'Provider 已结束思考，等待主题正文',
                    'delta':'正在接收主题正文','final':'主题正文已返回'}
                progress(phase+' · '+labels.get(kind,'Provider 有输出活动'));publish_phase();last_flush=beat
        try:
            content = prompt
            if images:
                content = [dict(type='text',text=prompt)] + [dict(type='image_url',
                    image_url=dict(url='data:image/png;base64,'+base64.b64encode(Path(p).read_bytes()).decode('ascii')))
                    for p in images]
            raw=provider.complete([dict(role='system',content=system),dict(role='user',content=content)],
                max_tokens=tokens,temperature=.8,timeout=remaining(),cancel_check=cancelled,
                stage='studio_web_theme_'+phase,on_stream_event=event,
                complete_json_early=True)
        except Exception as exc:
            value=''.join(partial)
            trace['raw_provider_responses'].append(dict(phase=phase,partial_response_text=value,
                chars=len(value),sha256=digest(value),elapsed_seconds=time.monotonic()-call_started,
                completed=False,error=str(exc),category=getattr(exc,'category','provider_error')))
            publish_phase(status='failed',error=str(exc),category=getattr(exc,'category','provider_error'),
                provider_diagnostics=provider_diagnostics())
            if getattr(exc,'category','') in {'cancelled','timeout'} and not (cancel_check and cancel_check()):
                message=phase+'（Provider）超时；已完成的候选方案保留，可单独重试主题代码'
                publish_phase(status='failed',error=message,category=name+'_timeout')
                raise AIProviderError(message,category=name+'_timeout') from exc
            raise
        if pending and on_stream_text:on_stream_text(''.join(pending))
        trace['raw_provider_responses'].append(dict(phase=phase,response_text=str(raw),chars=len(str(raw)),
            sha256=digest(str(raw)),elapsed_seconds=time.monotonic()-call_started,
            request_id=active_phase['request_id'],completed=True))
        if cancel_check and cancel_check():raise AIProviderError('当前设计已取消',category='cancelled')
        finish_phase(provider_state='complete',provider_diagnostics=provider_diagnostics())
        return str(raw)
    try:
        if not selection.credential_ready:
            raise AIProviderError('当前Provider尚未配置凭据',category='authentication_required')
        from .web_theme_fonts import FONT_FILES
        source=dict(instruction=instruction,scope=effect_scope,text=cue.text,speaker=speaker,
            viewport=[1920,1080],default_anchor='bottom safe lower third',transparent=True,
            fonts=[*FONT_FILES,'Source Han Sans SC (fallback only)'])
        from .caption_design_trials import CaptionPreferences
        from .runtime_paths import detect_install_root
        preferences=CaptionPreferences(detect_install_root()/'docs/design/caption-preferences.json')
        source['preference_context']={'positive':preferences.positive_references(limit=2),
            'negative':preferences.read()['negative_rules'],'training_claim':False}
        design_version=2
        if design_version==2:source.pop('speaker',None)
        if design_version==2:
            from .web_placement import cue_placement
            source.update(duration_seconds=max(.1,(cue.end_ms-cue.start_ms)/1000),
                placement=cue_placement(project,cue),safe_area=dict(left=.05,right=.95,top=.75,bottom=.95),performance_level='balanced')
        if resume_design and resume_design.get('concepts'):
            if not all(c.get('design') for c in resume_design['concepts']):
                raise AIProviderError('旧候选未包含DESIGN与静态英雄帧；请重新生成三个方向。原主题仍可使用。',category='design_upgrade_required')
            if design_version==2 and not concepts_only and not any(c.get('id')==resume_design.get('selected_concept_id') for c in resume_design['concepts']):
                raise AIProviderError('请先选择一个视觉方向，再生成完整主题',category='selection_required')
            brief,concepts,chosen=choose_concept(copy.deepcopy(resume_design),effect_scope)
            chosen=next((c for c in concepts if c['id']==resume_design.get('selected_concept_id')),chosen)
            trace['resumed_concepts']=True
        elif concepts_only:
            from .theme_art_direction_v2 import ART_DIRECTION_SYSTEM,V2_OPTIONS_SYSTEM,validate_art_direction
            capability=getattr(provider,'capabilities',None)
            supplied_frames=reference_frames if callable(capability) and getattr(capability(),'vision',False) else ()
            art={'brief':copy.deepcopy(resume_design['brief'])} if resume_design and resume_design.get('brief') else parse_object(call('理解字幕与画面',ART_DIRECTION_SYSTEM,json.dumps(source,ensure_ascii=False),1800,supplied_frames))
            if not isinstance(art.get('brief'),dict) or any(k not in art['brief'] for k in BRIEF_FIELDS):raise ValueError('ArtDirectionSpec字段不完整')
            trace['art_direction']=art['brief'];api._persist_ai_design_trace(copy.deepcopy(trace))
            publish_phase(design=dict(schema_version=2,brief=art['brief'],concepts=[],selected_concept_id=''))
            raw=call('生成三个概念',V2_OPTIONS_SYSTEM,json.dumps(dict(brief=art['brief'],text=cue.text,fonts=source['fonts']),ensure_ascii=False),5000)
            options=parse_object(raw);options['brief']=art['brief'];validate_art_direction(options)
            if not all(c.get('design') for c in options['concepts']):raise ValueError('新候选必须先提供DESIGN，不能回退本地组件预设')
            brief,concepts,chosen=choose_concept(options,effect_scope)
        trace.update(brief=brief,concepts=concepts,selected_concept_id=chosen['id'])
        design=dict(brief=brief,concepts=concepts,selected_concept_id=chosen['id'],schema_version=design_version)
        if concepts_only:design['selected_concept_id']=''
        if not resume_design:publish_phase(design=design)
        # Durable checkpoint exists even if the following model never emits a byte.
        api._persist_ai_design_trace(copy.deepcopy(trace))
        if concepts_only:
            from .theme_art_direction_v2 import V2_HERO_SYSTEM
            for concept in concepts:
                if not concept.get('design') or concept.get('hero_theme'):continue
                markdown='# '+concept['name']+'\n\n'+'\n\n'.join('## '+k+'\n\n'+(v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2)) for k,v in concept['design'].items())+'\n'
                concept['design_markdown']=markdown
                # Save the actual design before requesting any HTML. The
                # checkpoint retains each finished hero across retries.
                trace_path=api._persist_ai_design_trace(copy.deepcopy(trace))
                if trace_path:
                    design_folder=Path(trace_path).parent/('heroes-'+re.sub(r'[^a-zA-Z0-9_-]','_',request_id))/concept['id']
                    design_folder.mkdir(parents=True,exist_ok=True)
                    (design_folder/'DESIGN.md').write_text(markdown,encoding='utf8')
                publish_phase(design=design)
                hero_raw=call('静态英雄帧 · '+concept['name'],V2_HERO_SYSTEM,json.dumps(dict(design_markdown=markdown,text=cue.text,fonts=source['fonts'],scope=effect_scope),ensure_ascii=False),5000)
                hero=WebThemeDocument.from_dict(parse_object(hero_raw))
                if hero.motion_spec or re.search(r'@keyframes|\b(?:animation|transition)(?:-[\w-]+)?\s*:',hero.cue_css+hero.stage_css,re.I):
                    raise ValueError('英雄帧必须完全静态，选择后才编排动作')
                concept['hero_theme']=hero.to_dict()
                api._persist_ai_design_trace(copy.deepcopy(trace));publish_phase(design=design)
            return api.AIWebThemeSuggestion(theme={},source='concepts',message='三个方向已生成，请看预览后选择',
                request_id=request_id,model=selection.model,provider=selection.provider,brief=brief,concepts=concepts,
                selected_concept_id='',quality={'design_version':2},elapsed_seconds=time.monotonic()-started)
        if design_version==2 and not resume_design.get('selected_concept_id'):
            raise AIProviderError('请先选择一个可见方案',category='selection_required')
        if not chosen.get('hero_theme'):
            raise AIProviderError('所选方向缺少静态英雄帧，请先重试方向预览阶段',category='hero_required')
        code_input=dict(brief=brief,selected_concept={k:v for k,v in chosen.items() if k not in ('rule_score','score_details','risks')},
            text=cue.text,duration_seconds=max(.1,(cue.end_ms-cue.start_ms)/1000),viewport=[1920,1080],
            safe_area=dict(left=.05,right=.95,top=.75,bottom=.95),speaker=speaker)
        if design_version==2:code_input.pop('speaker',None)
        prompt=json.dumps(code_input,ensure_ascii=False)
        from .theme_art_direction_v2 import V2_CODE_SYSTEM
        raw=call('编写选定主题',V2_CODE_SYSTEM,prompt,8000)
        evidence=None;quality={};visual_images=()
        capabilities=getattr(provider,'capabilities',None)
        transport=str(getattr(getattr(provider,'transport',None),'value',getattr(provider,'transport','')))
        can_review=bool(render_validator and callable(capabilities) and
            transport != 'antigravity_cli' and getattr(capabilities(),'vision',False))
        for attempt in range(4):
            try:
                begin_phase('validation','解析与安全校验',10.)
                def repair_metadata(fields):
                    nonlocal metadata_attempted
                    if metadata_attempted:return {'names':[]}
                    metadata_attempted=True
                    return call('修复主题名称','只补全name元数据，输出JSON {"names":[{"path":"原path","name":"短名称"}]}。禁止输出或修改视觉内容。',json.dumps(fields,ensure_ascii=False),600)
                theme,quality=code_gate(raw,instruction,effect_scope,design_version,
                    request_id=request_id,metadata_repair=repair_metadata,cancel_check=cancelled,
                    metadata_event=lambda event,fields:trace.setdefault('metadata_events',[]).append(dict(event=event,**fields)))
                if chosen.get('design') and not theme.get('motionSpec'):
                    raise ValueError('新英雄帧必须使用同一GSAP MotionSpec编排动作')
                quality['design_version']=design_version
                remaining();finish_phase()
                if render_validator:
                    begin_phase('render','预览渲染与像素校验',40.)
                    evidence=render_validator(theme,35.)
                    remaining();finish_phase()
                    if can_review:
                        visual_images=tuple(evidence.get('review_images') or (f['path'] for f in evidence.get('frames',[])))
                        from .theme_art_direction_v2 import AESTHETIC_REVIEW_SYSTEM,validate_visual_checks
                        critique=parse_critique(call('复核实际故事板',
                            AESTHETIC_REVIEW_SYSTEM if design_version==2 else '你是字幕视觉审查员。依次检查六帧入场、保持与退场，核对用户风格、辨识度、材质、'
                            '中文可读性、下部安全区、遮挡和动作逻辑。只返回JSON {"passed":true或false,'
                            '"defects":[具体可修复缺陷],"rationale":"简短依据"}。无明确缺陷就通过，禁止空泛打分。',
                            json.dumps(dict(instruction=instruction,concept=chosen,
                                times=[f['seconds'] for f in evidence.get('frames',[])]),ensure_ascii=False),
                            2200,visual_images))
                        if design_version==2:critique=validate_visual_checks(critique)
                        if not isinstance(critique.get('passed'),bool) or not isinstance(critique.get('defects'),list):
                            raise AIProviderError('视觉复核格式无效，已保留可渲染主题',category='visual_review_error')
                        quality['visual_review']=critique
                        evidence['visual_review']=f'已由当前模型 {selection.model} 复核'
                        if not critique['passed']:
                            raise ValueError('实际故事板视觉缺陷：'+'；'.join(map(str,critique['defects'])))
                remaining()
                break
            except (ValueError,RuntimeError) as exc:
                failed_evidence=getattr(exc,'render_evidence',None)
                if failed_evidence and can_review:
                    visual_images=tuple(failed_evidence.get('review_images') or (f['path'] for f in failed_evidence.get('frames',[])))
                if active_phase is not None and active_phase['status']=='running':
                    publish_phase(status='failed',error=str(exc),category=getattr(exc,'category','validation_error'))
                category=getattr(exc,'category','')
                if category and category not in ('render_validation',):
                    if 'theme' in locals():exc.preview_theme=theme
                    raise
                trace['validation_errors'].append(str(exc))
                if attempt>=3: raise AIProviderError('三次定向修复后仍未通过，请更换方向：'+str(exc),category='quality_validation') from exc
                trace['repair_count']=attempt+1
                raw=call('定向修复',REPAIR_SYSTEM,
                    '选定方向：'+json.dumps(chosen,ensure_ascii=False)+'\n具体缺陷：'+str(exc)+
                    '\n上一版完整原文：\n'+raw,12000,visual_images)
        trace.update(web_theme_source='ai',theme_name=theme['name'],quality=quality,content_hash=digest(canonical_theme(theme)))
        trace_path=api._persist_ai_design_trace(trace)
        return api.AIWebThemeSuggestion(theme=theme,source='ai',message='技术校验已完成，请检查实际预览；模型意见不等于视觉验收',
            trace_path=trace_path,provider=selection.provider,elapsed_seconds=time.monotonic()-started,
            request_id=request_id,model=selection.model,brief=brief,concepts=concepts,
            selected_concept_id=chosen['id'],quality=quality,render_evidence=evidence,repair_count=trace['repair_count'])
    except Exception as exc:
        if 'theme' in locals():exc.preview_theme=theme
        if 'design' in locals():exc.design_checkpoint=copy.deepcopy(design)
        if active_phase is not None and active_phase['status']=='running':
            publish_phase(status='failed',error=str(exc),category=getattr(exc,'category','design_error'))
        trace.update(error=str(exc),category=getattr(exc,'category','design_error'))
        exc.trace_path=api._persist_ai_design_trace(trace)
        raise
