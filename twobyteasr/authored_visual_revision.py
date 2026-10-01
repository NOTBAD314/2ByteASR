"""A user's bounded visual revision of one authored candidate, with frozen identity."""
import copy,json,re,time,uuid
from .web_theme import _MAX_CSS_CHARS
from pathlib import Path


def preserve_typography(before,proposed):
    """Restore explicitly frozen declarations, retaining exact source ranges."""
    from .authored_repair import css_values
    def fonts(css):
        rows={}
        for d in css_values(css):
            if d['property'].startswith('font') or d['property']=='letter-spacing':
                rows.setdefault((d['selector'],d['property']),[]).append(d)
        return rows
    old,new=fonts(before),fonts(proposed)
    if old.keys()!=new.keys() or any(len(old[k])!=len(new[k]) for k in old):
        raise ValueError('微调新增或移除了冻结字体声明；保留原候选')
    changes=[]
    for key in old:
        for prior,current in zip(old[key],new[key]):
            if prior['value']!=current['value']:
                changes.append(dict(selector=key[0],property=key[1],start=current['start'],end=current['end'],
                    proposed=current['value'],restored=prior['value'],action='restore_frozen_typography'))
    for row in sorted(changes,key=lambda r:r['start'],reverse=True):
        proposed=proposed[:row['start']]+row['restored']+proposed[row['end']:]
    return proposed,changes


def saved_payload(ledger):
    """Reconstruct explicit one-candidate generation without falsifying its raw response."""
    from .caption_creative_pipeline import canonical,digest
    from .structured_output import response_object
    raw=Path(ledger.value['raw_response']['path']).read_bytes()
    if digest(raw)!=ledger.value['raw_response']['sha256']:raise ValueError('原始响应已改变')
    normalized=ledger.value.get('normalized_response')
    if normalized:
        data=Path(normalized['path']).read_bytes()
        if digest(data)!=normalized['sha256']:raise ValueError('规范化响应已改变')
        parsed=json.loads(data)
    elif ledger.value['raw_response'].get('completed') is False:
        from .authored_partial import retained_candidate_prefix
        parsed=retained_candidate_prefix(raw.decode('utf8'))
    else:parsed=response_object(raw.decode('utf8'))
    resumed=ledger.value.get('resume_assembly')
    if resumed:
        assembled=Path(resumed['path']).read_bytes()
        if digest(assembled)!=resumed['sha256']:raise ValueError('继续生成的候选集合已改变')
        parsed=json.loads(assembled)
    assembly=ledger.value.get('composition_seed')
    if assembly:
        seed=Path(assembly['path']).read_bytes()
        if digest(seed)!=assembly['sha256']:raise ValueError('保留候选集合已改变')
        payload=json.loads(seed)
        row=parsed['candidate'];index=next(i for i,r in enumerate(payload['candidates']) if r['id']==row['id'])
        payload['candidates'][index]=row
        return payload
    return parsed


def normalize_redo_response(value,candidate_id,ledger,*,peer_ids=()):
    """The request owns the candidate slot; the model may name a new theme."""
    from .caption_creative_pipeline import canonical,digest
    if not isinstance(value,dict) or set(value)!={'candidate'}:return value
    row=value['candidate']
    if not isinstance(row,dict) or row.get('id')==candidate_id:return value
    supplied=row.get('id')
    if not supplied or supplied in peer_ids:raise ValueError('重新创作返回了其他候选身份')
    normalized=copy.deepcopy(value);normalized['candidate']['id']=candidate_id
    path=ledger.root/'normalized-response.json';path.write_text(canonical(normalized),'utf8')
    ledger.value['normalized_response']=dict(path=str(path),sha256=digest(path.read_bytes()),
        action='retain_requested_candidate_slot',candidate_id=candidate_id,provider_candidate_id=supplied)
    ledger.save();return normalized


def parse_redo_response(raw,ledger,client,schema,*,timeout,cancel_check=None):
    """One metadata syntax repair, only when the entire artwork parses intact."""
    from .structured_output import response_object
    from .caption_creative_pipeline import canonical,digest
    try:return response_object(raw)
    except ValueError as exc:
        if getattr(exc,'category','')!='structured_output_invalid_json' or not isinstance(raw,str):raise
        matches=list(re.finditer(r'"generated_source"\s*:\s*',raw))
        if len(matches)!=1:raise
        start=matches[0].end()
        source,length=json.JSONDecoder().raw_decode(raw[start:])
        if not isinstance(source,dict) or not {'cueHtml','cueCss','motionSpec'}<=set(source):raise
        metadata=raw[:start]+'{}'+raw[start+length:]
    repair_schema=copy.deepcopy(schema)
    allowed=['candidate.'+k for k in repair_schema['properties']['candidate']['properties'] if k!='generated_source']
    # Syntax repair must not invent missing design metadata to satisfy the
    # full contract. The usual bounded field repair validates that afterward.
    repair_schema['properties']['candidate']={'type':'object','required':['generated_source'],
        'properties':{'generated_source':{'type':'object','maxProperties':0}}}
    prompt=('只修复以下单候选JSON元数据的语法/引号转义，保持全部说明、材质、颜色、身份和动作语义的值；'
        '不得重新设计。generated_source的完整源码已经独立解析并锁定，本次必须保留为空对象。仅返回修复后的JSON。\n'+metadata)
    (ledger.root/'envelope-repair-input.json').write_text(canonical(dict(prompt=prompt,schema=repair_schema)),'utf8')
    repaired=client.complete([dict(role='user',content=prompt)],json_schema=repair_schema,
        timeout=min(180,max(.1,timeout)),max_tokens=4096,cancel_check=cancel_check,
        operation_kind='local_patch',input_scope=dict(kind='one_candidate_metadata_syntax',source_omitted=True,
            allowed_paths=allowed))
    (ledger.root/'envelope-repair-output.txt').write_text(repaired,'utf8')
    value=response_object(repaired)
    import jsonschema
    jsonschema.validate(value,repair_schema)
    value['candidate']['generated_source']=source
    path=ledger.root/'normalized-response.json';path.write_text(canonical(value),'utf8')
    ledger.value['normalized_response']=dict(path=str(path),sha256=digest(path.read_bytes()),
        action='metadata_syntax_repair_source_unchanged',source_sha256=digest(canonical(source)))
    ledger.save();return value


def redesign_candidate(path,candidate_id,feedback,settings,*,ledger_root,request_id,cancel_check=None,stage_callback=None,stage_event_callback=None,
                       revision_kind='redo',current_theme=None,locked_paths=()):
    """Explicit creative redo: one new candidate, preserved peers, generation budget."""
    from .caption_creative_pipeline import ThemeLedger,digest,canonical,accept_authored_set,AUTHORED_OUTPUT_SCHEMA
    from .authored_theme_contract import AUTHORED_TECHNICAL_DELIVERY
    from .caption_material_direction import MOTION_DELIVERY,MATERIAL_DIRECTION,TEXT_EMPHASIS_DELIVERY
    from .theme_revision_constraints import capture_constraints,enforce_constraints
    from .design_guidance import load_design_guidance
    from .provider_registry import GLOBAL_PROVIDER_REGISTRY
    from .provider_service import GLOBAL_PROVIDER_SERVICE
    from .structured_output import response_object
    from .authored_repair import provider_callbacks
    prior=ThemeLedger.open(path)
    if not prior.value.get('raw_response'):
        from .caption_creative_pipeline import retry_saved_candidate
        return retry_saved_candidate(path,candidate_id,settings,ledger_root=ledger_root,request_id=request_id,
            cancel_check=cancel_check,stage_callback=stage_callback,stage_event_callback=stage_event_callback,
            implementation_feedback=feedback)
    payload=saved_payload(prior)
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    if (selection.provider,selection.model)!=(prior.value['raw_response']['provider'],prior.value['raw_response']['model']):
        raise ValueError('重做方向须使用原Provider与模型')
    retained={r['id']:r for r in prior.value['candidates']}
    required=AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['required']
    for i,row in enumerate(payload['candidates']):
        if row['id'] in retained:
            saved=retained[row['id']]
            if digest(canonical(saved['generated_source']))!=saved['generated_source_hash']:raise ValueError('保留候选源码已改变')
            payload['candidates'][i]={k:copy.deepcopy(saved[k]) for k in required}
    index=next(i for i,r in enumerate(payload['candidates']) if r['id']==candidate_id)
    before=copy.deepcopy(payload['candidates'][index]['generated_source'])
    current=copy.deepcopy(current_theme if current_theme is not None else before)
    constraints=capture_constraints(current,before,locked_paths)
    from .theme_design_preservation import PRESERVATION_DIRECTION,SURFACE_DIRECTION,protect_structure,validate_surface_revision
    if revision_kind=='art_revision':constraints=protect_structure(current,constraints)
    ledger=ThemeLedger(ledger_root,prior.value['raw_user_prompt'])
    ledger.value.update(reference_files=copy.deepcopy(prior.value['reference_files']),visibility_policy='composed-timeline-v2',
        resumed_from=dict(ledger=str(path),candidate_id=candidate_id),creative_context=copy.deepcopy(prior.value.get('creative_context',{})))
    seed=ledger.root/'preserved-candidate-set.json';seed.write_text(canonical(payload),'utf8')
    ledger.value['composition_seed']=dict(path=str(seed),sha256=digest(seed.read_bytes()),replaced_id=candidate_id)
    from .authored_prompt import assemble, compose
    from .source_artifact import from_theme, to_theme
    identity=request_id+'/'+candidate_id+'/redo'
    direction=payload['candidates'][index]
    base, base_receipt=assemble(ledger,direction=direction,artifact_identity=identity)
    scope=('保留当前HTML和MotionSpec，增强背景、边缘与字面材质。' if revision_kind=='art_revision'
           else '按本次反馈重新设计当前候选，保留明确用户锁与已经采用的原件。')
    prompt,assembly=compose(dict(current_request=base,revision_scope=scope,feedback=feedback,
        current_source=from_theme(current,identity),user_locks=constraints))
    assembly['base_assembly']=base_receipt
    (ledger.root/'request-components.json').write_text(canonical(assembly),'utf8')
    schema=None
    client=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish');started=time.monotonic()
    ledger.value['creative_redo']=dict(candidate_id=candidate_id,feedback=feedback,status='requesting',budget_kind='generation',
        revision_kind=revision_kind,before_hash=digest(canonical(current)),user_constraints=constraints)
    (ledger.root/'before-theme.json').write_text(canonical(current),'utf8')
    (ledger.root/'provider-prompt.txt').write_text(prompt,'utf8');ledger.save()
    if stage_callback:stage_callback('重新创作方向 '+candidate_id+' · 保留其他候选')
    from .theme_generation_policy import authored_request_budget
    output_tokens,limits=authored_request_budget(selection.provider,settings.get('models',{}),candidate_count=1)
    request_timeout=limits.concepts
    ledger.value['authorship_budget']=dict(completion_tokens=output_tokens,total_seconds=request_timeout,
        includes_reasoning=selection.provider=='deepseek')
    from .design_progress import PublicProgress
    progress=PublicProgress(request_id+'/redo','重新创作方向 '+candidate_id,request_timeout,event_callback=stage_event_callback,
        stage_callback=stage_callback,path=ledger.root/'provider-partial.txt')
    try:
        raw=client.complete([dict(role='user',content=prompt)],json_schema=schema,timeout=request_timeout,max_tokens=output_tokens,
            cancel_check=cancel_check,on_stream_event=progress.stream,_timeout_policy=limits.transport_policy(),
            operation_kind='generate',input_scope=dict(kind='one_full_creative_redo',candidate_id=candidate_id),response_kind='source_artifact')
        progress.finish('complete')
        (ledger.root/'provider-original-source.txt').write_text(raw,'utf8')
        theme, artifact_receipt=to_theme(raw,identity,direction)
        ledger.value['artifact_receipt']=artifact_receipt
        value={'candidate':dict(direction,generated_source=theme)}
        proposed,restored=enforce_constraints(value['candidate']['generated_source'],constraints)
        value['candidate']['generated_source']=proposed
        if revision_kind=='art_revision':validate_surface_revision(current,proposed)
        ledger.value['creative_redo']['restored_user_intent']=restored
        payload['candidates'][index]=value['candidate']
        ledger.raw_response(canonical({'candidate':value['candidate']}),selection.provider,selection.model)
        ledger.value['raw_response']['kind']='assembled_source_redo'
        ledger.value['stage_original']=str(ledger.root/'provider-original-source.txt')
        patch,regenerate=provider_callbacks(client,request_id,cancel_check=cancel_check,stage_callback=stage_callback,
            remaining_seconds=lambda:request_timeout-(time.monotonic()-started),trace_root=ledger.root,stage_event_callback=stage_event_callback)
        if cancel_check and cancel_check():raise ValueError('重新创作已取消')
        result=accept_authored_set(payload,ledger,selection.provider,selection.model,technical_repair=None,
            candidate_regenerate=None,allow_partial=True,repair_indices={index},cancel_check=cancel_check,request_id=request_id)
        revised=next(c for c in result.concepts if c['id']==candidate_id)
        if revised.get('technical_status')=='failed':raise ValueError('新美术版本未通过技术检查；保留改前稿')
        after=revised['authored_theme']
        if revision_kind=='art_revision':validate_surface_revision(current,after)
        if enforce_constraints(after,constraints)[1]:raise ValueError('技术修复改变了用户锁；保留改前稿')
        from .motion_spec_repair import changed_paths
        ledger.value['creative_redo'].update(after_hash=digest(canonical(after)),changed_paths=changed_paths(current,after))
        ledger.value['creative_redo']['status']='generated';return result
    except Exception as exc:
        progress.finish('failed')
        ledger.value['creative_redo'].update(status='failed',error=str(exc)[:600]);raise
    finally:
        ledger.value['creative_redo'].update(elapsed_seconds=time.monotonic()-started,invocation=client.invocation_trace());ledger.save()


def revise_candidate(path,candidate_id,feedback,settings,*,ledger_root,request_id,cancel_check=None,stage_callback=None):
    from .caption_creative_pipeline import ThemeLedger,digest,canonical,accept_authored_set,AUTHORED_OUTPUT_SCHEMA
    from .structured_output import response_object
    from .provider_registry import GLOBAL_PROVIDER_REGISTRY
    from .provider_service import GLOBAL_PROVIDER_SERVICE
    from .authored_repair import css_values,collect_issues
    prior=ThemeLedger.open(path);raw=Path(prior.value['raw_response']['path']).read_bytes()
    if digest(raw)!=prior.value['raw_response']['sha256']:raise ValueError('原始响应已改变')
    selection=GLOBAL_PROVIDER_REGISTRY.selection(settings,stage='polish')
    if (selection.provider,selection.model)!=(prior.value['raw_response']['provider'],prior.value['raw_response']['model']):
        raise ValueError('局部微调须使用原Provider与模型')
    saved={r['id']:r for r in prior.value['candidates']}
    if candidate_id not in saved:raise ValueError('请先修复此候选的技术错误')
    counts=prior.value.setdefault('visual_revision_counts',{})
    if counts.get(candidate_id,0)>=2:raise ValueError('此候选已达两次视觉微调上限')
    counts[candidate_id]=counts.get(candidate_id,0)+1;prior.save()
    payload=saved_payload(prior)
    for i,row in enumerate(payload['candidates']):
        if row['id'] in saved:
            retained=saved[row['id']]
            if digest(canonical(retained['generated_source']))!=retained['generated_source_hash']:raise ValueError('保留候选源码已改变')
            payload['candidates'][i]={k:copy.deepcopy(retained[k]) for k in AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['required']}
    index=next(i for i,r in enumerate(payload['candidates']) if r['id']==candidate_id)
    source=payload['candidates'][index]['generated_source'];before=copy.deepcopy(source)
    ledger=ThemeLedger(ledger_root,prior.value['raw_user_prompt'])
    ledger.value.update(reference_files=copy.deepcopy(prior.value['reference_files']),visual_revision_counts=copy.deepcopy(counts),
        resumed_from=dict(ledger=str(path),candidate_id=candidate_id),visibility_policy='composed-timeline-v2',
        creative_context=copy.deepcopy(prior.value.get('creative_context',{})))
    if prior.value.get('composition_seed'):ledger.value['composition_seed']=copy.deepcopy(prior.value['composition_seed'])
    ledger.raw_response(raw.decode('utf8'),selection.provider,selection.model,
        completed=prior.value['raw_response'].get('completed',True))
    paths=[f'candidates[{index}].generated_source.cueCss',f'candidates[{index}].generated_source.motionSpec']
    schema=dict(type='object',additionalProperties=False,required=['cueCss'],properties={
        'cueCss':dict(type='string',maxLength=_MAX_CSS_CHARS),'motionSpec':dict(type='object')})
    contract=('只返回JSON对象，含完整修正后的cueCss，必要时另含完整motionSpec。只微调这一个候选的构图、材质细节和动作。'
        '保持全部HTML、class、正文、主题名称/id、字体族/字重/字号/颜色不变；不要修改其他候选。颜色字面值清单必须保持。'
        '只处理反馈中点名的问题；MotionSpec必须保持受支持属性与有限范围。不得添加animation/transition/外部资源。')
    from .theme_design_preservation import PRESERVATION_DIRECTION
    from .authored_prompt import compose,authoring_source
    editable=copy.deepcopy(payload['candidates'][index])
    editable['generated_source']=authoring_source(editable['generated_source'])
    prompt,assembly=compose(dict(step_contract=contract,feedback=feedback,current_candidate=editable,
        user_requirement=prior.value['raw_user_prompt'],preservation=PRESERVATION_DIRECTION),schema=schema)
    (ledger.root/'request-components.json').write_text(canonical(assembly),'utf8')
    client=GLOBAL_PROVIDER_SERVICE.client_for_stage(settings,'polish');started=time.monotonic()
    ledger.value['visual_revision']=dict(feedback=feedback,allowed_paths=paths,status='requesting',before_hash=digest(canonical(source)))
    ledger.save();(ledger.root/'visual-revision-input.json').write_text(canonical(dict(prompt=prompt,schema=schema)),'utf8')
    if stage_callback:stage_callback('局部微调 '+candidate_id+' · 保留字体、配色、身份与其他候选')
    try:
        raw_result=client.complete([dict(role='user',content=prompt)],json_schema=schema,timeout=90,max_tokens=6000,
            cancel_check=cancel_check,operation_kind='visual_feedback',input_scope=dict(kind='one_visual_candidate',allowed_paths=paths))
        (ledger.root/'visual-revision-output.txt').write_text(raw_result,'utf8')
        value=response_object(raw_result)
        import jsonschema
        jsonschema.validate(value,schema)
        value['cueCss'],restored=preserve_typography(before['cueCss'],value['cueCss'])
        ledger.value['visual_revision']['normalization']=restored
        def frozen(css):
            return (sorted(re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)',css)),
                sorted((d['selector'],d['property'],d['value']) for d in css_values(css) if d['property'].startswith('font') or d['property']=='letter-spacing'))
        if frozen(before['cueCss'])!=frozen(value['cueCss']):raise ValueError('微调改变了未授权字体或配色；保留原候选')
        source.update(value)
        errors=[i for i in collect_issues(payload,ledger) if i['candidate_index']==index]
        if errors:raise ValueError('微调仍有技术错误：'+'；'.join(i['path']+': '+str(i.get('constraint',i['category'])) for i in errors))
        if cancel_check and cancel_check():raise ValueError('局部微调已取消')
        from .motion_spec_repair import changed_paths
        ledger.value['visual_revision'].update(status='applied',changed_paths=changed_paths(before,source),after_hash=digest(canonical(source)))
        return accept_authored_set(payload,ledger,selection.provider,selection.model,allow_partial=True,cancel_check=cancel_check,request_id=request_id)
    except Exception as exc:
        ledger.value['visual_revision'].update(status='rejected',error=str(exc)[:600]);raise
    finally:
        ledger.value['visual_revision'].update(elapsed_seconds=time.monotonic()-started,invocation=client.invocation_trace());ledger.save()
