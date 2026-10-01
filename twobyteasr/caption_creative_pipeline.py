"""Authored caption compositions with an inspectable input-to-pixel ledger.

The adapter validates an author's DOM/CSS/motion; it never chooses a layout.
"""
from __future__ import annotations
import base64,copy,hashlib,json,re,time,uuid
from pathlib import Path
from .theme_metadata import NAME_SCHEMA, ID_SCHEMA, normalize_theme_input, recover_generated_names, validate_name, validate_id
from .authored_theme_contract import (AUTHORED_SOURCE_SCHEMA, AUTHORED_TECHNICAL_DELIVERY,
    COLOR_ROLE_SCHEMA, SEMANTIC_MOTION_SCHEMA)

VERSION='caption-creative-source-9'
PRIORITY=['raw_user_prompt','media_and_caption','current_positive_references',
          'technical_contract','aesthetic_skills','local_defaults']
FORBIDDEN=('pressed_ticket','cut_crystal','glacier_window','雪脊','远征','赤岩','极地')

# Send the actual object shape to every provider. The previous prose value
# "完整WebTheme name/..." encouraged a spurious {"WebTheme": {...}} envelope.
WEB_THEME_OUTPUT_SCHEMA=AUTHORED_SOURCE_SCHEMA
AUTHORED_OUTPUT_SCHEMA={'type':'object','required':['candidates'],'properties':{'candidates':{'type':'array',
    'minItems':1,'maxItems':3,'items':{'type':'object','required':['id','name','composition_family',
        'art_direction_contract','design_spec','ColorRole','MaterialContract','MotionContract','generated_source'],
        'properties':{'id':ID_SCHEMA,'name':NAME_SCHEMA,'composition_family':{'type':'string'},
            'art_direction_contract':{'type':'object'},'design_spec':{'type':'object'},
            'ColorRole':{'type':'array','items':{'type':'object'}},
            'MaterialContract':{'type':'object','required':['material','selectors'],
                'properties':{'material':{'type':'string'},'selectors':{'type':'array','items':{'type':'string'}}}},
            'MotionContract':SEMANTIC_MOTION_SCHEMA,
            'generated_source':WEB_THEME_OUTPUT_SCHEMA}}}}}
METADATA_REPAIR_SCHEMA={'type':'object','additionalProperties':False,'required':['names'],'properties':{'names':{
    'type':'array','items':{'type':'object','additionalProperties':False,'required':['path','name'],
        'properties':{'path':{'type':'string'},'name':NAME_SCHEMA}}}}}

def digest(value):
    return hashlib.sha256(value if isinstance(value,bytes) else value.encode('utf8')).hexdigest()

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def main_theme(prompt):
    if re.search(r'初音|Hatsune|Miku',prompt,re.I):return 'Miku'
    if re.search(r'Minecraft|我的世界',prompt,re.I):return 'Minecraft'
    # The Balatro brief explicitly includes Crystal as a counterexample.
    from .caption_style_reference import is_balatro
    if is_balatro(prompt):return 'Balatro'
    if re.search(r'Crystal|水晶',prompt,re.I):return 'Crystal'
    return 'user-defined'

def reference_record(path,role):
    p=Path(path).resolve()
    return {'path':str(p),'role':role,'exists':p.is_file(),
            'sha256':digest(p.read_bytes()) if p.is_file() else None}

class ThemeLedger:
    @classmethod
    def open(cls,path):
        ledger=cls.__new__(cls);ledger.root=Path(path).parent
        ledger.value=json.loads(Path(path).read_text('utf8'));return ledger

    def __init__(self,root,prompt,*,references=(),positive=(),negative=()):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        refs=[reference_record(path,role) for path,role in references]
        self.value=dict(version=VERSION,raw_user_prompt=prompt,raw_prompt_hash=digest(prompt),
            reference_files=refs,accepted_positive_references=copy.deepcopy(list(positive)),
            negative_references=copy.deepcopy(list(negative)),priority=PRIORITY,
            theme=main_theme(prompt),stages=[],candidates=[],provider_inputs=[],status='created')
        self.value['cache_key']=digest(canonical([VERSION,self.value['raw_prompt_hash'],
            [(r['role'],r['sha256']) for r in refs],positive,negative]))
        self.save()
    def save(self):
        from .theme_persistence import write_text_atomic
        return write_text_atomic(self.root/'ledger.json',json.dumps(self.value,ensure_ascii=False,indent=2))
    def stage(self,name,payload,*,candidate_id='',require_semantics=False):
        if not isinstance(payload,dict):raise ValueError(name+': expected object')
        # The immutable user brief is authoritative. Author labels are evidence,
        # never a keyword-based technical gate or proof of visual fidelity.
        row=dict(stage=name,candidate_id=candidate_id,raw_prompt_hash=self.value['raw_prompt_hash'],
            reference_hashes=[r['sha256'] for r in self.value['reference_files']],
            payload_hash=digest(canonical(payload)),requested_theme=self.value['theme'],
            author_theme=payload.get('theme'),semantic_review='pending' if require_semantics else 'not_applicable')
        self.value['stages'].append(row);self.save();return row
    def raw_response(self,raw,provider,model,*,completed=True):
        path=self.root/('provider-original.txt' if completed else 'provider-partial.txt');path.write_bytes(raw.encode('utf8'))
        self.value['raw_response']={'path':str(path),'sha256':digest(raw),'provider':provider,'model':model,'completed':completed}
        self.save()  # Before parsing, even when JSON is invalid.
    def record_preview(self,candidate_id,paths,review=None):
        frames=[reference_record(p,'rendered-preview') for p in paths]
        if not frames or any(not r['exists'] for r in frames):raise ValueError('真实预览文件缺失')
        row=next(c for c in self.value['candidates'] if c['id']==candidate_id)
        previous=row.get('rendered_preview_hash')
        row['rendered_preview_hash']=digest(canonical([r['sha256'] for r in frames]))
        if previous!=row['rendered_preview_hash']:row.pop('visual_review',None)
        row['rendered_previews']=frames
        if review is not None:
            # Scores are retained as optional historical evidence only. A
            # qualitative review must not invent numbers to allow adoption.
            accepted=review.get('accepted') is True
            user_choice=review.get('user_approval') is True and review.get('reviewer')=='local-user'
            if not review.get('pixels_inspected') or not str(review.get('reviewer','')).strip():
                raise ValueError('视觉记录需要实际看图与具名审核者')
            if not str(review.get('notes','')).strip():raise ValueError('视觉记录需要具体画面观察')
            row['visual_review']=dict(review,accepted=bool(accepted),user_approval=user_choice,preview_hash=row['rendered_preview_hash'])
        self.stage('rendered_preview',{'theme':self.value['theme'],'frames':frames},candidate_id=candidate_id)
        self.save()

def reviewed_concepts(concepts,*,raw_user_prompt=None,allow_partial=False):
    """Never trust a score detached from the files and source actually reviewed."""
    if not allow_partial and len(concepts)!=3:raise ValueError('必须保留全部三个候选及其审核结果')
    accepted_count=0
    for concept in concepts:
        if concept.get('technical_status')=='pending':continue
        ledger=ThemeLedger.open(concept['ledger_path'])
        if raw_user_prompt is not None and digest(raw_user_prompt)!=ledger.value['raw_prompt_hash']:
            raise ValueError('当前原始要求已变更，旧预览不可复用')
        if concept.get('technical_status')=='failed':
            if not any(r['id']==concept['id'] for r in ledger.value.get('candidate_failures',[])):
                raise ValueError('失败候选记录与草稿不一致')
            continue
        row=next(c for c in ledger.value['candidates'] if c['id']==concept['id'])
        if digest(canonical(concept['authored_theme']))!=row['generated_source_hash']:
            raise ValueError('源码与审核对象不一致')
        review=row.get('visual_review',{})
        frames=row.get('rendered_previews',[])
        if not frames:continue
        accepted=review.get('accepted') is True
        if len(frames)<5 or (review and (not review.get('pixels_inspected') or not accepted and not review.get('notes'))):
            raise ValueError('预览已保存，尚待实际看图审核；未开放方向选择')
        hashes=[reference_record(f['path'],'preview')['sha256'] for f in frames]
        expected=row.get('rendered_preview_hash')
        if None in hashes or digest(canonical(hashes))!=expected or review and expected!=review.get('preview_hash'):
            raise ValueError('预览文件已改变，需要重新审核')
        if any(reference_record(r['path'],r['role'])['sha256']!=r['sha256'] for r in ledger.value['reference_files']):
            raise ValueError('参考文件已改变，禁止复用旧brief')
        # Ordinary aesthetic feedback never masquerades as a renderer failure.
        # A reviewer must explicitly flag a core requirement violation to block.
        accepted_count+=1  # Aesthetic advice never blocks technical adoption.
    if not accepted_count:raise ValueError('暂无可采用候选：请先完成真实预览或修复阻断问题')
    return True

def validate_material_contract(contract,theme):
    if not isinstance(contract,dict):raise ValueError('MaterialContract缺失')
    material=str(contract.get('material','')).lower()
    css=theme.get('cueCss','');html=theme.get('cueHtml','')
    from .material_contract import validate_material_bindings
    validate_material_bindings(contract,theme)

def adapt_candidate(candidate,ledger):
    """No layout enumeration or local template. Reject incompatible source."""
    from .web_theme import WebThemeDocument
    candidate=copy.deepcopy(candidate);identity=validate_id(candidate.get('id'),'candidate.id')
    candidate['name']=validate_name(candidate.get('name'),'candidate.name')
    contract=candidate['art_direction_contract'];spec=candidate['design_spec']
    ledger.stage('art_direction_contract',contract,candidate_id=identity,require_semantics=True)
    ledger.stage('design_spec',spec,candidate_id=identity,require_semantics=True)
    family=str(candidate['composition_family'])
    original=normalize_theme_input(candidate['generated_source'],path=f'candidates[{identity}].generated_source')
    text=canonical(original)
    theme=WebThemeDocument.from_dict(original).to_dict()
    if not theme.get('motionSpec'):raise ValueError('技术适配需要作者的有限MotionSpec，不能代替作者编排动作')
    for section in ('cueHtml','cueCss','stageHtml','stageCss'):
        # Whitespace normalization is allowed; lost attributes/markup are not.
        compact=lambda s:re.sub(r'<(br|hr)\s*/?>',r'<\1/>',re.sub(r'\s+',' ',str(s)).strip().replace("'",'"'))
        from .authored_html import html_signature
        unchanged=(html_signature(original.get(section,''))==html_signature(theme.get(section,''))
                   if section.endswith('Html') else compact(original.get(section,''))==compact(theme.get(section,'')))
        if not unchanged:
            raise ValueError('安全适配改变了作者源码 '+section+'；请修改原稿，不静默重设计')
    # Design declarations are advisory; actual safe source, text and motion are checked below.
    roles=candidate.get('ColorRole',[])
    try:validate_material_contract(candidate['MaterialContract'],theme)
    except ValueError as exc:
        ledger.value.setdefault('design_warnings',[]).append(dict(candidate_id=identity,message=str(exc)))
    ledger.stage('generated_source',dict(theme='Balatro' if ledger.value['theme']=='Balatro' else ledger.value['theme'],
        source=theme),candidate_id=identity,require_semantics=True)
    row=dict(id=identity,name=candidate['name'],art_direction_contract=contract,design_spec=spec,
        composition_family=family,ColorRole=roles,MaterialContract=candidate['MaterialContract'],
        MotionContract=candidate['MotionContract'],generated_source=theme,
        generated_source_hash=digest(canonical(theme)),rendered_preview_hash=None)
    ledger.value['candidates'].append(row);ledger.save()
    return row

def accept_authored_set(payload,ledger,provider,model,*,metadata_repair=None,motion_repair=None,technical_repair=None,
                        candidate_regenerate=None,cancel_check=None,request_id='',allow_partial=False,repair_indices=None):
    from .studio_ai import AIWebThemeSuggestion
    if not isinstance(payload,dict) or not isinstance(payload.get('candidates'),list) or not 1<=len(payload['candidates'])<=3:
        raise ValueError('$.candidates: 需要1至3个独立候选；请按交付结构重试。')
    rows=[normalize_theme_input(row,path=f'candidates[{i}]') for i,row in enumerate(copy.deepcopy(payload['candidates']))]
    for i,row in enumerate(rows):validate_id(row.get('id'),f'candidates[{i}].id')
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('$.candidates.id: 三个候选标识必须不同；请修正重复标识后重试。')
    if technical_repair is not None or candidate_regenerate is not None:
        from .authored_repair import repair_authored
        for i,row in enumerate(rows):
            row['generated_source']=normalize_theme_input(row.get('generated_source'),path=f'candidates[{i}].generated_source')
        def validate_all(value):
            probe=copy.copy(ledger);probe.value=copy.deepcopy(ledger.value);probe.value['candidates']=[];probe.save=lambda:None
            if repair_indices is not None:
                import jsonschema
                for index in repair_indices:
                    row=value['candidates'][index]
                    jsonschema.validate(row,AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items'])
                    adapt_candidate(row,probe)
                return
            return accept_authored_set(value,probe,provider,model,cancel_check=cancel_check,request_id=request_id)
        try:
            rows=repair_authored({'candidates':rows},ledger=ledger,provider=provider,model=model,
                parent_request_id=request_id or ledger.root.name,validate=validate_all,patch_request=technical_repair,
                regenerate_request=candidate_regenerate,cancel_check=cancel_check,candidate_indices=repair_indices)['candidates']
        except Exception as exc:
            if (not allow_partial or getattr(exc,'category','')=='cancelled'
                    or cancel_check and cancel_check()):raise
            rows=getattr(exc,'retained_payload',{'candidates':rows})['candidates']
            ledger.value['repair_failure']=dict(category=getattr(exc,'category','technical_contract'),error=str(exc)[:600])
            ledger.save()
    elif motion_repair is not None:
        from .motion_spec_repair import repair_numeric_once
        for i, row in enumerate(rows):
            row['generated_source'] = normalize_theme_input(row.get('generated_source'),
                path=f'candidates[{i}].generated_source')
        def validate_complete(value):
            # Same full acceptance path, isolated from receipts/candidates and
            # without any network callbacks. No partial draft is published.
            probe = copy.copy(ledger)
            probe.value = copy.deepcopy(ledger.value)
            probe.value['candidates'] = []
            probe.save = lambda: None
            return accept_authored_set(value,probe,provider,model,cancel_check=cancel_check,request_id=request_id)
        rows = repair_numeric_once({'candidates': rows},validate=validate_complete,repair=motion_repair,
            ledger=ledger,provider=provider,model=model,parent_request_id=request_id or ledger.root.name,
            cancel_check=cancel_check)['candidates']
    def metadata_event(event,fields):
        ledger.value.setdefault('metadata_events',[]).append(dict(event=event,**fields));ledger.save()
    unavailable=[]
    if allow_partial:
        import jsonschema
        from .authored_repair import collect_issues
        issues=collect_issues({'candidates':rows},ledger)
        valid=[]
        for index,row in enumerate(rows):
            errors=[i for i in issues if i['candidate_index']==index]
            if errors:
                unavailable.append(dict(id=row['id'],name=row.get('name') or row['id'],technical_status='failed',
                    technical_errors=errors,composition='技术检查未通过，原稿已保留',creative_version=VERSION,
                    ledger_path=str(ledger.root/'ledger.json'),provider=provider))
            else:valid.append(row)
        ledger.value['candidate_failures']=copy.deepcopy(unavailable);ledger.save()
        rows=valid
    sources={f'candidates[{i}].generated_source':row.get('generated_source') for i,row in enumerate(rows)}
    sources=recover_generated_names(sources,request_id=request_id or ledger.root.name,
        repair=metadata_repair,cancel_check=cancel_check,event=metadata_event)
    for i,row in enumerate(rows):
        row['generated_source']=sources[f'candidates[{i}].generated_source']
        if not row.get('name','').strip():row['name']=row['generated_source']['name']
    # Transport JSON mode alone does not enforce a schema. Validate the
    # normalized/repaired result locally, then retain the visual code gates.
    import jsonschema
    try:
        if allow_partial:
            for row in rows:jsonschema.validate(row,AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items'])
        else:jsonschema.validate({'candidates':rows},AUTHORED_OUTPUT_SCHEMA)
    except jsonschema.ValidationError as exc:
        path='$'+''.join(f'[{part}]' if isinstance(part,int) else '.'+part for part in exc.absolute_path)
        # ValidationError.__str__ includes the entire failing instance.
        # Keep provider/user content out of UI messages and traceback tails.
        raise ValueError(f'{path}: 主题结构不符合 {exc.validator} 约束；请只修正该字段后重试。') from None
    concepts=[]
    for candidate in rows:
        row=adapt_candidate(candidate,ledger);theme=row['generated_source']
        hero=copy.deepcopy(theme);hero.pop('motionSpec',None)
        spec=row['design_spec'];motion=row['MotionContract']
        concepts.append(dict(id=row['id'],name=row['name'],subject=spec.get('metaphor',row['name']),
            composition=row['composition_family'],palette=row['ColorRole'],materials=[row['MaterialContract']['material']],
            motion=motion,signature_elements=list(row['art_direction_contract'].get('vocabulary',[])) or ['authored-composition'],
            risks=['技术检查不能代替实际看图和用户认可'],estimated_performance='medium',design=spec,
            hero_theme=hero,authored_theme=theme,creative_version=VERSION,raw_prompt_hash=ledger.value['raw_prompt_hash'],
            ledger_path=str(ledger.root/'ledger.json'),provider=provider))
    concepts.extend(unavailable)
    order={r['id']:i for i,r in enumerate(payload['candidates'])}
    concepts.sort(key=lambda c:order[c['id']])
    ledger.value['status']='authored-awaiting-pixel-review';ledger.save()
    return AIWebThemeSuggestion(theme={},source='concepts',message='三份独立创意源码已保存；正在检查实际画面',
        request_id=ledger.root.name,provider=provider,model=model,brief={'raw_user_prompt':ledger.value['raw_user_prompt'],
        'raw_prompt_hash':ledger.value['raw_prompt_hash'],'theme':ledger.value['theme'],'priority':PRIORITY},
        concepts=concepts,selected_concept_id='',quality={'design_version':4,'creative_version':VERSION,'ledger_path':str(ledger.root/'ledger.json')})

def request_creative_options(project,cue_id,instruction,settings,*,reference_frames=(),raw_user_prompt=None,
        ledger_root=None,request_id='',cancel_check=None,stage_callback=None,deadline_seconds=None,
        on_stream_text=None,stage_event_callback=None,keyframe_review=None,effect_scope='subtitle',**unused):
    from .provider_registry import GLOBAL_PROVIDER_REGISTRY
    from .provider_service import GLOBAL_PROVIDER_SERVICE
    from .studio_project import studio_data_root
    from .caption_design_trials import CaptionPreferences
    from .runtime_paths import detect_install_root
    from .web_theme_compiler import parse_object
    from .web_theme_fonts import FONT_FILES
    from .font_system import windows_font_family_names
    from .caption_material_direction import MATERIAL_DIRECTION, MOTION_DELIVERY, TEXT_EMPHASIS_DELIVERY
    from .design_guidance import load_design_guidance
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    from .design_task_budget import DesignTaskBudget
    from .theme_generation_policy import authored_request_budget
    _,limits=authored_request_budget(selection.provider,settings.get('models',{}),deadline_seconds,candidate_count=1)
    task_budget=DesignTaskBudget(limits.concepts,settings.get('models',{}).get('ai_design_max_repair_calls',2))
    prefs=CaptionPreferences(detect_install_root()/'docs/design/caption-preferences.json').read()
    raw=instruction if raw_user_prompt is None else raw_user_prompt
    art_guidance, art_receipt = load_design_guidance(raw)
    install=detect_install_root()
    # Old Balatro feedback includes a pixel face and per-candidate art briefs.
    # It must not silently override paper/metal/Minecraft or an unrelated brief.
    # Historical per-artwork commands are evidence, not standing requirements.
    # They previously reintroduced three fixed containers on every Balatro ask.
    relevant_history=main_theme(raw)=='Balatro'
    accepted_history=[]
    historical=[(install/p['path'],'accepted-history') for p in accepted_history if p.get('path')]
    ledger=ThemeLedger(ledger_root or studio_data_root()/'logs/creative-themes'/(request_id or uuid.uuid4().hex),raw,
        references=[(p,'current-media') for p in reference_frames]+historical,positive=accepted_history,
        negative=[r for r in prefs.get('trial_runs',[]) if r.get('accepted') is False] if relevant_history else [])
    from .caption_style_reference import attach_reference
    attach_reference(ledger, root=install)
    from .caption_reference_search import search_references
    search_references(ledger, progress=stage_callback or (lambda _:None),
                      cancel_check=lambda:bool(cancel_check and cancel_check()) or task_budget.remaining()<=0)
    task_budget.check(cancel_check)
    ledger.value['visibility_policy']='composed-timeline-v2'
    ledger.value['historical_feedback_not_applied']={k:prefs.get(k,[]) for k in
        ('accepted_history','revision_feedback','negative_rules')} if relevant_history else {}
    ledger.value['design_skills'] = art_receipt
    cue=next(c for c in project.cues if c.id==cue_id)
    creative=dict(raw_user_prompt=raw,raw_prompt_hash=ledger.value['raw_prompt_hash'],
        priority=PRIORITY,subtitle_text=cue.text,references=ledger.value['reference_files'],
        accepted_positive_references=ledger.value['accepted_positive_references'],
        rejected_candidates=[{'name':r.get('candidate_id'),'rating':r.get('user_rating')} for r in ledger.value['negative_references']],
        bundled_fonts=list(FONT_FILES),installed_font_names=list(windows_font_family_names())[:100],
        font_policy='按当前主题选择实际打包字形：Cubic 11、ZCOOL KuaiLe、ZCOOL QingKe HuangYou为400；Source Han Sans SC/Medium为500，Heavy为900；Smiley Sans本身是斜体造型的固定字形。Cubic 11禁止伪粗体与斜体，不用fontWeight数值假装文件有多个字重；中文回退只补缺字。系统字体不保证跨机可复现。',
        current_feedback=[],negative_rules=[],
        material_direction=MATERIAL_DIRECTION)
    media=getattr(project,'media',None)
    render_settings=getattr(project,'render_settings',{}) or {}
    creative['project_context']=dict(width=getattr(media,'width',0) or 1920,height=getattr(media,'height',0) or 1080,
        fps=render_settings.get('fps',30),cue_start_ms=getattr(cue,'start_ms',0),cue_end_ms=getattr(cue,'end_ms',0),
        cue_duration_ms=max(0,getattr(cue,'end_ms',0)-getattr(cue,'start_ms',0)),
        preview_duration_ms=6000,effect_scope=effect_scope,
        time_contract='cue local time; host owns project mapping; original text and word timings immutable')
    creative['theme_authority']={'source':'raw_user_prompt','explicit_requirements':raw,
        'history_is_advisory':True,'semantic_theme_review':'actual rendered frames required'}
    ledger.value['creative_context']=creative;ledger.save()
    # This root file is a manifest, not a provider request. The exact per-stage
    # inputs live beside their unmodified responses and request receipts.
    prompt='请求清单：有风格依据的概念化UI字幕，背景框、边界、字面和三段动作共同服务正文。实际供应商输入见 directions/provider-prompt.txt 与 candidates/*/v*/provider-prompt.txt（并发稿位于 jobs/*/）。\n'+canonical(creative)
    # A style atlas gets its own slot; current media remains an overlay reference.
    reference_rows=([r for r in ledger.value['reference_files'] if r['role']=='style-reference']+
                    [r for r in ledger.value['reference_files'] if r['role']=='current-media'])[:3]
    references=[r['path'] for r in reference_rows];message=prompt
    delivery_record=dict(provider=selection.provider,model=selection.model,transport='text',pixels_attached=False,pixels_seen_confirmed=False)
    client=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish')
    capabilities=getattr(client,'capabilities',lambda:None)()
    if references and getattr(capabilities,'vision',False) and selection.provider in {'grok_oauth','openai','openai_compatible'}:
        message=[{'type':'text','text':prompt}]+[_reference_image_part(p) for p in references]
        delivery_record.update(transport='image_url_base64',pixels_attached=True,
            attached_reference_sha256=[r['sha256'] for r in reference_rows],
            attached_reference_roles=[r['role'] for r in reference_rows])
    if ledger.value.get('style_reference'):
        delivery_record['style_reference_delivery']='atlas_and_observations' if delivery_record['pixels_attached'] else 'observations_only_no_model_vision'
    ledger.value['provider_inputs'].append(delivery_record);ledger.save()
    ledger.value['technical_delivery'] = dict(manifest_sha256=digest(prompt), prompt_kind='manifest_not_dispatched',
        client_type=type(client).__name__)
    (ledger.root/'provider-prompt.txt').write_bytes(prompt.encode('utf8'))
    ledger.save()
    from .authored_generation import generate_staged
    from .authored_preview import render_candidate_preview
    from functools import partial
    reviewer=keyframe_review  # Optional paid review requires an explicit caller; never automatic.
    try:
        return generate_staged(ledger,client,selection,prompt,settings,request_id=request_id or ledger.root.name,
            cancel_check=cancel_check,stage_callback=stage_callback,stage_event_callback=stage_event_callback,
            on_stream_text=on_stream_text,deadline_seconds=deadline_seconds,
            image_parts=message[1:] if isinstance(message,list) else None,
            render_candidate=partial(render_candidate_preview,keyframe_review=reviewer),
            client_factory=lambda:GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish'),
            candidate_cancel_check=unused.get('candidate_cancel_check'),task_budget=task_budget)
    except Exception as exc:
        from .provider_diagnostics import redact_diagnostics
        import traceback
        ledger.value.update(status='cancelled' if getattr(exc,'category','')=='cancelled' else 'failed',
            error=str(exc)[:600],failure_diagnostics=redact_diagnostics(dict(category=getattr(exc,'category','generation_error'),
                traceback=traceback.format_exc())))
        ledger.save();exc.trace_path=str(ledger.root/'ledger.json');raise
    finally:
        from .provider_diagnostics import redact_diagnostics
        trace=getattr(client,'invocation_trace',lambda:{})()
        (ledger.root/'provider-invocation.json').write_text(json.dumps(redact_diagnostics(trace),ensure_ascii=False,indent=2),'utf8')


def _reference_image_part(path):
    payload=Path(path).read_bytes()
    mime='image/jpeg' if payload.startswith(b'\xff\xd8\xff') else 'image/png'
    return {'type':'image_url','image_url':{'url':f'data:{mime};base64,'+base64.b64encode(payload).decode('ascii')}}


def saved_reference_images(ledger):
    """Restore precisely the original pixel inputs; never pass by losing them."""
    attached = any(row.get('pixels_attached') for row in ledger.value.get('provider_inputs', []))
    parts = []
    exact=next((r['attached_reference_sha256'] for r in ledger.value.get('provider_inputs', [])
                if r.get('pixels_attached') and 'attached_reference_sha256' in r),None)
    verified={}
    for row in ledger.value.get('reference_files', []):
        path = Path(row['path'])
        if not path.is_file() or digest(path.read_bytes()) != row.get('sha256'):
            raise ValueError('原参考图缺失或内容已改变；请恢复原图后继续此方向')
        verified[row.get('sha256')]=path
        if exact is None and attached and row.get('role') == 'current-media' and len(parts) < 3:
            parts.append(_reference_image_part(path))
    if exact is not None:
        if any(sha not in verified for sha in exact):
            raise ValueError('原附图清单缺少图像，不能在恢复时丢弃风格参考')
        parts=[_reference_image_part(verified[sha]) for sha in exact]
    if attached and not parts:
        raise ValueError('已记录附图，但未找到可恢复的当前媒体参考图')
    return parts


def retry_saved_candidate(path,candidate_id,settings,*,ledger_root,request_id,cancel_check=None,stage_callback=None,stage_event_callback=None,implementation_feedback='',recovery_mode='continue'):
    """One explicit candidate retry, keeping valid peers byte-for-byte."""
    from .structured_output import response_object
    from .provider_registry import GLOBAL_PROVIDER_REGISTRY
    from .provider_service import GLOBAL_PROVIDER_SERVICE
    from .authored_repair import provider_callbacks
    prior=ThemeLedger.open(path)
    if prior.value.get('pipeline') in {'authored-stages-1','authored-stages-2','authored-stages-3'} and (not prior.value.get('raw_response') or recovery_mode in {'implementation','rebuild'}):
        # A locally blocked/unfinished source has no JSON to patch. Rebuild
        # this one implementation from its immutable saved direction instead.
        from .authored_generation import generate_staged
        from .authored_prompt import VERSION as assembly_version,assemble
        from .authored_preview import render_candidate_preview
        parent=ThemeLedger.open(prior.value['parent_ledger'])
        if prior.value.get('candidate_id')!=candidate_id:
            raise ValueError('候选身份不匹配，不能继续其他方向')
        selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
        configured=parent.value['provider']
        if (selection.provider,selection.model)!=(configured['provider'],configured['model']):
            raise ValueError('继续实现必须使用原Provider与模型')
        image_parts = saved_reference_images(parent)
        counts=copy.deepcopy(prior.value.get('implementation_retries_by_assembly',{}))
        counts[assembly_version]=counts.get(assembly_version,0)+1
        ledger=ThemeLedger(ledger_root,parent.value['raw_user_prompt'])
        ledger.value.update(creative_context=copy.deepcopy(parent.value.get('creative_context',{})),
            reference_files=copy.deepcopy(parent.value.get('reference_files',[])),style_reference=copy.deepcopy(parent.value.get('style_reference')),
            provider_inputs=copy.deepcopy(parent.value.get('provider_inputs',[])),
            resumed_from=dict(ledger=str(path),candidate_id=candidate_id,kind='saved_direction_implementation'))
        ledger.value['reference_search']=copy.deepcopy(parent.value.get('reference_search'))
        ledger.value['implementation_retries_by_assembly']=counts
        if implementation_feedback:
            ledger.value['creative_context']['current_feedback']=implementation_feedback
        prompt,_=assemble(ledger);ledger.save()
        from .artwork_recovery import saved_recovery
        recovery=saved_recovery(prior.root) if recovery_mode!='rebuild' else None
        if recovery_mode=='implementation' and recovery is None and prior.value.get('candidates'):
            from .source_artifact import from_theme
            from .artwork_recovery import save_recovery
            row=next((r for r in prior.value['candidates'] if r['id']==candidate_id),None)
            if row:
                (ledger.root/'provider-original.txt').write_text(from_theme(row['generated_source'],'saved-implementation'),'utf8')
                recovery=save_recovery(ledger.root,'saved-implementation')
        directions=copy.deepcopy(parent.value['directions'])
        # Explicit rebuild creates a new implementation from the same design,
        # even when that design originally carried a component definition.
        if recovery_mode=='rebuild':
            for row in directions['candidates']:row.pop('components',None)
        client=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish')
        class ExplicitAttemptClient:
            def __init__(self):
                self.calls=0
                def complete(*args,**kwargs):
                    if self.calls:raise ValueError('本次恢复已用完一次远端请求；请查看保留的结果与诊断')
                    self.calls+=1
                    ledger.value['recovery_remote_calls']=self.calls;ledger.save()
                    return client.complete(*args,**kwargs)
                complete._acceptance_repair_limit=0
                self.complete=complete
            def __getattr__(self,name):return getattr(client,name)
        return generate_staged(ledger,ExplicitAttemptClient(),selection,prompt,settings,
            request_id=request_id,cancel_check=cancel_check,stage_callback=stage_callback,
            stage_event_callback=stage_event_callback,
            retained={'directions':directions,'recoveries':{candidate_id:recovery} if recovery else {},'explicit_recovery':True},only_candidate=candidate_id,
            image_parts=image_parts, render_candidate=render_candidate_preview)
    source=Path(prior.value['raw_response']['path']);raw=source.read_bytes()
    if digest(raw)!=prior.value['raw_response']['sha256']:raise ValueError('原始响应已改变，无法局部重试')
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    if (selection.provider,selection.model)!=(prior.value['raw_response']['provider'],prior.value['raw_response']['model']):
        raise ValueError('局部重试必须使用原Provider与模型')
    from .authored_visual_revision import saved_payload
    parsed=saved_payload(prior)
    retained={c['id']:c for c in prior.value.get('candidates',[])}
    for index,row in enumerate(parsed['candidates']):
        saved=retained.get(row['id'])
        if saved:
            if digest(canonical(saved['generated_source']))!=saved['generated_source_hash']:raise ValueError('保留候选源码已改变')
            parsed['candidates'][index]={k:copy.deepcopy(saved[k]) for k in AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['required']}
    index=next((i for i,r in enumerate(parsed['candidates']) if r['id']==candidate_id),None)
    if index is None:raise ValueError('局部重试候选身份不存在')
    counts=copy.deepcopy(prior.value.get('candidate_retry_counts',{}))
    # A new explicit click owns one bounded attempt. Historic local rejection
    # counts must not permanently lock an otherwise exactly repairable source.
    # The network callbacks below share a one-call budget, independent of the
    # number of local validation/normalization steps.
    counts[candidate_id]=counts.get(candidate_id,0)+1
    ledger=ThemeLedger(ledger_root,prior.value['raw_user_prompt'])
    ledger.value.update(reference_files=copy.deepcopy(prior.value['reference_files']),candidate_retry_counts=counts,
        resumed_from=dict(ledger=str(path),candidate_id=candidate_id),visibility_policy='composed-timeline-v2')
    for key in ('pipeline','parent_ledger','candidate_id','candidate_version','creative_context','style_reference','reference_search'):
        if key in prior.value:ledger.value[key]=copy.deepcopy(prior.value[key])
    if prior.value.get('composition_seed'):ledger.value['composition_seed']=copy.deepcopy(prior.value['composition_seed'])
    ledger.raw_response(raw.decode('utf8'),selection.provider,selection.model,
        completed=prior.value['raw_response'].get('completed',True))
    client=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish');started=time.monotonic()
    from .theme_generation_policy import ThemeGenerationLimits
    budget=ThemeGenerationLimits.from_settings(settings.get('models',{})).concepts
    patch,regenerate=provider_callbacks(client,request_id,cancel_check=cancel_check,stage_callback=stage_callback,
        remaining_seconds=lambda:budget-(time.monotonic()-started),trace_root=ledger.root,stage_event_callback=stage_event_callback)
    calls=0
    def bounded(callback):
        def invoke(*args,**kwargs):
            nonlocal calls
            if calls:raise ValueError('本次恢复已用完一次远端请求；原稿及本轮诊断保留，请查看后再操作')
            calls+=1
            ledger.value['recovery_remote_calls']=calls;ledger.save()
            return callback(*args,**kwargs)
        return invoke
    patch,regenerate=bounded(patch),bounded(regenerate)
    return accept_authored_set(parsed,ledger,selection.provider,selection.model,technical_repair=patch,
        candidate_regenerate=regenerate,cancel_check=cancel_check,request_id=request_id,allow_partial=True,repair_indices={index})


def resume_saved_response(path,project,cue_id,settings,*,ledger_root,request_id,cancel_check=None,stage_callback=None,selected_direction=None):
    """An explicit retry reuses immutable provider bytes, with the same provider.

    Failed technical patches are not replayed: they may have changed the target
    of an animation. The original source is validated again under current code.
    """
    from .provider_registry import GLOBAL_PROVIDER_REGISTRY
    from .provider_service import GLOBAL_PROVIDER_SERVICE
    from .structured_output import response_object
    from .authored_repair import provider_callbacks
    from .ai_providers import AIProviderError
    prior=ThemeLedger.open(path)
    if prior.value.get('pipeline') in {'authored-stages-1','authored-stages-2','authored-stages-3'} and not prior.value.get('directions'):
        from .structured_failure import recover_saved_directions
        directions, recovery = recover_saved_directions(prior)
        prior.value.update(directions=directions, local_direction_recovery=recovery,
                           selected_direction=selected_direction or directions['candidates'][0]['id'])
        prior.save()
        if stage_callback: stage_callback('本地恢复了完整方向；原请求仍为失败，作品尚待实现与验证。')
    if prior.value.get('pipeline') in {'authored-stages-1','authored-stages-2','authored-stages-3'} and prior.value.get('directions'):
        from .authored_generation import generate_staged
        from .authored_preview import render_candidate_preview
        selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
        configured=prior.value.get('provider',{})
        if (selection.provider,selection.model)!=(configured.get('provider'),configured.get('model')):
            raise ValueError('请选择此草稿原来的Provider与模型，不能静默切换')
        image_parts = saved_reference_images(prior)
        selected_direction = selected_direction or prior.value.get('selected_direction')
        if selected_direction and selected_direction not in {r['id'] for r in prior.value['directions']['candidates']}:
            raise ValueError('所选方向不在保存的完整方向中')
        from .authored_prompt import VERSION as assembly_version
        resume_counts=prior.value.setdefault('resume_counts_by_assembly',{})
        resume_count=int(resume_counts.get(assembly_version,0))+1
        if resume_count>2:raise ValueError('此任务已达到两次继续上限，请保留诊断后定向修改')
        resume_counts[assembly_version]=resume_count
        prior.value['explicit_resume_count']=resume_count;prior.save()
        retained={}
        for row in prior.value.get('candidates',[]):
            if digest(canonical(row['generated_source']))!=row['generated_source_hash']:
                raise ValueError('保留候选源码已改变')
            retained[row['id']]=row
        ledger=ThemeLedger(ledger_root,prior.value['raw_user_prompt'])
        ledger.value.update(creative_context=copy.deepcopy(prior.value.get('creative_context',{})),
            local_direction_recovery=copy.deepcopy(prior.value.get('local_direction_recovery')),
            selected_direction=selected_direction,
            reference_files=copy.deepcopy(prior.value.get('reference_files',[])),style_reference=copy.deepcopy(prior.value.get('style_reference')),
            provider_inputs=copy.deepcopy(prior.value.get('provider_inputs',[])),
            explicit_resume_count=resume_count,resumed_from={'ledger':str(path),
                'kind':'local_syntax_recovery' if prior.value.get('local_direction_recovery') else 'explicit_completed_stage_reuse',
                'local_recovery':copy.deepcopy(prior.value.get('local_direction_recovery'))})
        # Current assembler rebuilds from the saved intent and latest contracts.
        ledger.value['reference_search']=copy.deepcopy(prior.value.get('reference_search'))
        from .authored_prompt import assemble
        prompt, _ = assemble(ledger)
        (ledger.root/'provider-prompt.txt').write_text(prompt,'utf8')
        ledger.save()
        return generate_staged(ledger,GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish'),selection,prompt,settings,
            request_id=request_id,cancel_check=cancel_check,stage_callback=stage_callback,
            retained={'directions':prior.value['directions'],'candidates':retained},image_parts=image_parts,
            render_candidate=render_candidate_preview,
            only_candidate=selected_direction)
    from .authored_partial import retained_response_record
    original=retained_response_record(prior)
    prior.value['raw_response']=original
    source=Path(original.get('path',''))
    if source.stat().st_size>4*1024*1024:raise ValueError('保存的响应超过正文上限')
    raw=source.read_bytes()
    if digest(raw)!=original.get('sha256'):raise ValueError('保存的原始响应已改变，无法继续该草稿')
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    if (original.get('provider'),original.get('model'))!=(selection.provider,selection.model):
        raise ValueError('请在设置中选择生成此草稿时的 Provider 和模型后再继续')
    if int(prior.value.get('explicit_resume_count',0))>=2:raise ValueError('该草稿已达到两次继续修复上限，请保留诊断后调整设计要求')
    if cancel_check and cancel_check():raise AIProviderError('字幕生成已取消',category='cancelled')
    from .authored_visual_revision import saved_payload
    parsed=saved_payload(prior)
    retained={c['id']:c for c in prior.value.get('candidates',[])}
    for index,row in enumerate(parsed['candidates']):
        saved=retained.get(row['id'])
        if saved:
            if digest(canonical(saved.get('generated_source',{})))!=saved.get('generated_source_hash'):
                raise ValueError('保留候选源码已改变，无法继续草稿')
            parsed['candidates'][index]={k:copy.deepcopy(saved[k]) for k in AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['required']}
    if not any(c.id==cue_id for c in project.cues):raise ValueError('当前字幕已不存在')
    ledger=ThemeLedger(ledger_root,prior.value['raw_user_prompt'],
        references=[(r['path'],r['role']) for r in prior.value.get('reference_files',[])],
        positive=prior.value.get('accepted_positive_references',[]),negative=prior.value.get('negative_references',[]))
    ledger.value.update(visibility_policy='composed-timeline-v2',explicit_resume_count=int(prior.value.get('explicit_resume_count',0))+1,
        resumed_from=dict(ledger=str(Path(path).absolute()),request_id=prior.root.parent.name,sha256=original['sha256']),
        creative_context=prior.value.get('creative_context',{}))
    ledger.value['prior_technical_repairs']=copy.deepcopy(prior.value.get('technical_repairs',[]))
    if prior.value.get('composition_seed'):ledger.value['composition_seed']=copy.deepcopy(prior.value['composition_seed'])
    ledger.raw_response(raw.decode('utf8'),selection.provider,selection.model,completed=original.get('completed',True))
    client=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish')
    started=time.monotonic()
    from .theme_generation_policy import ThemeGenerationLimits
    limits=ThemeGenerationLimits.from_settings(settings.get('models',{}))
    patch,regenerate=provider_callbacks(client,request_id,cancel_check=cancel_check,stage_callback=stage_callback,
        remaining_seconds=lambda:limits.concepts-(time.monotonic()-started),trace_root=ledger.root)
    try:
        missing=3-len(parsed['candidates'])
        if missing:
            from .design_guidance import load_design_guidance
            guidance,receipt=load_design_guidance(prior.value['raw_user_prompt'])
            ledger.value['design_skills']=receipt
            schema=copy.deepcopy(AUTHORED_OUTPUT_SCHEMA)
            schema['properties']['candidates'].update(minItems=missing,maxItems=missing)
            retained_briefs=[{k:r[k] for k in ('id','name','composition_family','art_direction_contract') if k in r} for r in parsed['candidates']]
            if stage_callback:stage_callback(f'保留已有 {3-missing} 稿，仅补充未完成的 {missing} 稿')
            message='继续已保存的设计。只生成缺失的候选，不复述或修改已完成候选，id必须不同，美术方向需有明显区别。\n'+guidance+'\n'+canonical(dict(
                user_prompt=prior.value['raw_user_prompt'],creative_context=prior.value.get('creative_context',{}),retained=retained_briefs,missing_count=missing))
            addition=client.complete([{'role':'user','content':message}],timeout=max(1.,limits.concepts-(time.monotonic()-started)),
                max_tokens=24000,json_schema=schema,operation_kind='generate',input_scope={'kind':'resume_missing_candidates','retained_count':3-missing},
                cancel_check=cancel_check,_timeout_policy=limits.transport_policy())
            added=response_object(addition)
            import jsonschema
            jsonschema.validate(added,schema)
            if set(r['id'] for r in parsed['candidates']) & set(r['id'] for r in added['candidates']):raise ValueError('补充候选身份与保留候选冲突')
            (ledger.root/'resume-addition.json').write_text(canonical(added),'utf8')
            parsed['candidates'].extend(added['candidates'])
            assembly=ledger.root/'resume-assembled.json';assembly.write_text(canonical(parsed),'utf8')
            ledger.value['resume_assembly']=dict(retained=3-missing,generated=missing,source_sha256=original['sha256'],
                path=str(assembly),sha256=digest(assembly.read_bytes()),invocation=client.invocation_trace())
            ledger.save()
        return accept_authored_set(parsed,ledger,selection.provider,selection.model,
            technical_repair=patch,candidate_regenerate=regenerate,cancel_check=cancel_check,request_id=request_id,allow_partial=True)
    except Exception as exc:
        ledger.value.update(status='failed',error=type(exc).__name__+': '+str(exc)[:500]);ledger.save();raise


def resume_authored(design,instruction,*,render_validator=None,raw_user_prompt=None,**unused):
    from .studio_ai import AIWebThemeSuggestion
    selected=next((c for c in design['concepts'] if c['id']==design.get('selected_concept_id')),None)
    if selected is None:raise ValueError('请先选择一个已看过的方向')
    if selected.get('technical_status')=='failed':raise ValueError('所选候选未通过技术检查，不能应用')
    raw=design.get('brief',{}).get('raw_user_prompt','')
    if digest(raw)!=selected['raw_prompt_hash']:raise ValueError('原始要求已改变，禁止复用旧主题brief')
    selected_ledger=ThemeLedger.open(selected['ledger_path'])
    row=next(c for c in selected_ledger.value['candidates'] if c['id']==selected['id'])
    if not row.get('rendered_previews'):raise ValueError('所选候选尚无真实预览，不能应用')
    # A completed candidate owns its source and preview evidence. Unfinished
    # siblings, or continuing just one saved direction, do not block adoption.
    reviewed_concepts([selected],raw_user_prompt=raw if raw_user_prompt is None else raw_user_prompt,
                      allow_partial=True)
    theme=copy.deepcopy(selected['authored_theme'])
    evidence=render_validator(theme,35.) if render_validator else None
    return AIWebThemeSuggestion(theme=theme,source='ai',message='按已选创意源码生成；没有重新设计',
        provider=selected.get('provider',''),brief=design['brief'],concepts=design['concepts'],
        selected_concept_id=selected['id'],quality={'design_version':4,'creative_version':VERSION},render_evidence=evidence,
        trace_path=selected['ledger_path'])
