"""Checkpointed authoring using the existing candidate and WebTheme contracts.

One compact direction set, then independently validated candidate versions.
No successful output is regenerated to recover another candidate.
"""
from __future__ import annotations
import copy
import json
import time
from dataclasses import replace
from pathlib import Path

import jsonschema

STAGED_VERSION='authored-stages-3'


def render_repair_message(ledger, direction, theme, evidence, *, receipt=False, artifact_identity='repair'):
    """Send one source and relevant runtime facts, without repeating ideation."""
    from .caption_creative_pipeline import canonical
    from .authored_prompt import authoring_source,compose
    from .caption_material_direction import MOTION_DELIVERY,TEXT_EMPHASIS_DELIVERY
    context=ledger.value.get('creative_context',{})
    contract=('仅修复当前候选的实际试渲问题，保持已选主题、形体、配色和动作意图。'
        '只返回完整修复后的源码工件，不带业务JSON包装。原稿已通过结构检查；'
        '不要删框、角色、材质或认可动效来过检查，不重做其他候选。正文不增删，时间和作用范围不变。'
        '长句在安全宽度换行，1920×1080与960×540须同比例；参考像素用'
        '--design-px:calc(100vh / 1080)和calc(N * var(--design-px))。'
        '字体使用var(--wt-font)/var(--wt-size)，静态定位层与动作层分开。'
        '保留HTML白名单与实际class对应，不引入网络/文件/脚本资源；舞台由宿主提供。'
        '错误来自实际渲染，路径仅为证据；未附像素不能声称看过。')
    from .source_artifact import contract as artifact_contract, from_theme
    value=compose(dict(step_contract=contract,user_requirement=ledger.value['raw_user_prompt'],
        caption_and_resources={k:context.get(k) for k in ('subtitle_text','project_context','font_policy','bundled_fonts')},
        diagnostics=evidence,design_direction={k:v for k,v in direction.items() if k!='generated_source'},
        current_source=from_theme(theme,artifact_identity),artifact_protocol=artifact_contract(artifact_identity),
        motion_contract=MOTION_DELIVERY,text_capability=TEXT_EMPHASIS_DELIVERY))
    return value if receipt else value[0]


def candidate_source(parsed, ident, ledger):
    """Accept only unambiguous known envelopes; never choose among peers."""
    from .theme_metadata import normalize_theme_input
    value=parsed
    if isinstance(value,dict) and set(value)=={'candidates'}:
        rows=value['candidates']
        if not isinstance(rows,list) or len(rows)!=1 or rows[0].get('id')!=ident:
            raise ValueError('单稿响应包含多个方向或身份不符；原始响应已保存')
        value=rows[0]
        ledger.value.setdefault('normalization',[]).append(dict(action='unwrap_single_matching_candidate',candidate_id=ident))
    if isinstance(value,dict) and 'generated_source' in value:
        value=value['generated_source']
        ledger.value.setdefault('normalization',[]).append(dict(action='unwrap_generated_source',candidate_id=ident))
    return normalize_theme_input(value,path=ident+'.generated_source')

def direction_schema(count=3, *, drafts=False):
    schema={'type':'object','required':['candidates'],'properties':{'candidates':{
        'type':'array','minItems':count,'maxItems':count,'items':{'type':'object',
        'required':['name','design'],'properties':{'name':{'type':'string','minLength':1,'maxLength':80},
        'design':{'type':'string','minLength':10,'maxLength':1800}},'additionalProperties':False}}},
        'additionalProperties':False}

    if drafts:
        item=schema['properties']['candidates']['items']
        item['required'].append('components')
        item['properties']['components']={'type':'object'}
    return schema


def legacy_direction_schema():
    from .caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA
    from .caption_material_direction import DESIGN_SPEC_FIELDS
    schema=copy.deepcopy(AUTHORED_OUTPUT_SCHEMA)
    item=schema['properties']['candidates']['items']
    item['required'].remove('generated_source');item['properties'].pop('generated_source')
    item['properties']['design_spec']={'type':'object',
        'required':['theme_identifiers','shape','material','typography','text_region','composition'],
        'properties':{k:{'type':'string','minLength':3,'maxLength':1500,'description':v}
                      for k,v in DESIGN_SPEC_FIELDS.items()}}
    return schema


def normalize_directions(value):
    """Saved legacy directions remain readable; new IDs/envelopes are app owned."""
    if not isinstance(value,dict) or not isinstance(value.get('candidates'),list) or not 1<=len(value['candidates'])<=3:
        raise ValueError('方向响应需要1到3个完整候选')
    if value.get('direction_protocol') == 'concise-1':
        value={'candidates':[dict(name=r['name'],design=r['design_spec']['design'],**({'components':r['components']} if 'components' in r else {})) for r in value['candidates']]}
    if all(isinstance(row,dict) and 'design' in row for row in value.get('candidates',[])):
        jsonschema.validate(value,direction_schema(len(value['candidates']),drafts=any('components' in r for r in value['candidates'])))
        rows=[]
        for ident,item in zip('ABC',value['candidates']):
            rows.append(dict(id=ident,name=item['name'],composition_family=item['design'],
                art_direction_contract={},design_spec={'design':item['design']},
                ColorRole=[],MaterialContract={'material':'','selectors':[]},
                MotionContract={'entrance':'由作品动作定义','hold':'由作品动作定义','exit':'由作品动作定义'},
                **({'components':copy.deepcopy(item['components'])} if 'components' in item else {})))
        return {'candidates':rows,'direction_protocol':'concise-1'}
    jsonschema.validate(value,legacy_direction_schema())
    return value

def generate_staged(ledger,client,selection,prompt,settings,*,request_id,cancel_check=None,
                    stage_callback=None,stage_event_callback=None,on_stream_text=None,deadline_seconds=None,
                    retained=None,image_parts=None,render_candidate=None,only_candidate=None,
                    client_factory=None,candidate_cancel_check=None,task_budget=None):
    from .caption_creative_pipeline import canonical,digest,ThemeLedger,accept_authored_set,AUTHORED_OUTPUT_SCHEMA
    from .theme_generation_policy import authored_request_budget
    from .structured_output import response_object
    from .theme_metadata import normalize_theme_input
    from .provider_diagnostics import redact_diagnostics
    from .design_progress import PublicProgress,aggregate_activity
    from .ai_providers import AIProviderError
    from .authored_repair import provider_callbacks
    from .design_recovery import checkpoint,source_checkpoints,can_complete,implementation_message
    tokens,limits=authored_request_budget(selection.provider,settings.get('models',{}),deadline_seconds,candidate_count=1)
    repair_limit=max(0,min(2,int(settings.get('models',{}).get('ai_design_max_repair_calls',2))))
    repair_limit=min(repair_limit,getattr(client.complete,'_acceptance_repair_limit',repair_limit))
    requested_count=1 if only_candidate else (3 if settings.get('models',{}).get('ai_design_candidate_count',1)==3 else 1)
    drafts=settings.get('models',{}).get('ai_design_mode')=='drafts'
    from .caption_style_reference import is_balatro
    if not retained and requested_count==1 and is_balatro(ledger.value['raw_user_prompt']) and settings.get('models',{}).get('ai_design_mode','single')=='single':
        drafts=True
    if retained:
        saved_rows=retained['directions']['candidates']
        if not only_candidate:requested_count=len(saved_rows)
        # Resume the saved task, independently of the current new-task defaults.
        drafts=bool(saved_rows) and all('components' in row for row in saved_rows)
    ledger.value['requested_candidates']=requested_count
    ledger.value['component_drafts']=drafts
    from .design_task_budget import DesignTaskBudget,transport_retry_delay,wait_for_retry
    task_budget=task_budget or DesignTaskBudget(limits.concepts,repair_limit)
    task_budget.max_repairs=min(task_budget.max_repairs,repair_limit)
    started=task_budget.started;deadline=task_budget.deadline
    ledger.value.update(pipeline=STAGED_VERSION,provider=dict(provider=selection.provider,model=selection.model),
        authorship_budget=dict(total_seconds=limits.concepts,implementation_tokens=tokens,repair_calls_per_candidate=repair_limit),
        candidate_states={},remote_request_resumable=False)
    ledger.save()
    ledger.value['automatic_completion_policy']=dict(max_calls_per_candidate=repair_limit,enabled=bool(repair_limit),
        scope='整个任务共用恢复次数与时限；已完成阶段保留；取消/认证/额度错误停止')
    active_candidate=None
    publish_candidate=None
    def cancelled():
        return bool(cancel_check and cancel_check()) or bool(active_candidate and candidate_cancel_check and candidate_cancel_check(active_candidate))
    def report_event(event):
        event=dict(event,task_budget=task_budget.snapshot(),task_started_monotonic=started)
        if active_candidate and publish_candidate:
            ledger.value['candidate_states'][active_candidate]['activity']=copy.deepcopy(event)
            publish_candidate()
        elif stage_event_callback:stage_event_callback(event)
    def check():
        if active_candidate and candidate_cancel_check and candidate_cancel_check(active_candidate):raise AIProviderError('此候选已取消',category='candidate_cancelled')
        if cancel_check and cancel_check():raise AIProviderError('字幕生成已取消；已完成产物可继续',category='cancelled')
        task_budget.check(cancel_check)
    def recover(reason):
        check()
        receipt=task_budget.reserve(reason,candidate_id=active_candidate,cancel_check=cancel_check)
        ledger.value['task_budget']=task_budget.snapshot()
        if active_candidate:
            ledger.value['candidate_states'][active_candidate].update(status='repairing',detail=f'自动恢复 {receipt["attempt"]}/{task_budget.max_repairs} · {str(reason)[:180]}')
        ledger.save()
        return receipt
    def call_once(label,folder,schema,message,*,max_tokens,operation_kind='generate',scope=None,assembly=None,artifact=None):
        check();folder.mkdir(parents=True,exist_ok=True)
        remaining=max(.1,deadline-time.monotonic())
        if artifact and not folder.name.startswith('completion-') and not (retained or {}).get('explicit_recovery'):
            # Reserve part of the existing total deadline for the product's
            # second communication; never silently extend the user's wait.
            remaining=max(.1,remaining-min(90,remaining*.2))
        (folder/'request-schema.json').write_text(canonical(schema),'utf8')
        (folder/'provider-prompt.txt').write_text(message,'utf8')
        if assembly is not None:
            if schema is not None and 'schema' not in assembly.get('components',{}):
                from .authored_prompt import compose
                assembly['schema_argument']=compose({'schema':schema})[1]['components']['schema']
            (folder/'request-components.json').write_text(canonical(assembly),'utf8')
        progress=PublicProgress(request_id+'/'+folder.relative_to(ledger.root).as_posix(),label,remaining,event_callback=report_event,
            stage_callback=stage_callback,path=folder/'provider-partial.txt')
        def stream(kind,detail):
            progress.stream(kind,detail)
            if kind=='delta' and on_stream_text:on_stream_text(str(detail))
        from .design_timing import DesignTiming
        timing=DesignTiming(folder/'timing.json')
        original_stream=stream
        def stream(kind,detail):
            timing.event(kind,detail);original_stream(kind,detail)
        local_trace=None;outcome='failed'
        try:
            timing.mark('submitted_to_provider')
            content=[{'type':'text','text':message},*image_parts] if image_parts else message
            raw=client.complete([{'role':'user','content':content}],timeout=remaining,max_tokens=max_tokens,
                json_schema=schema,cancel_check=cancelled,on_stream_event=stream,
                operation_kind=operation_kind,input_scope=scope or {'kind':'design_directions'},
                _timeout_policy=replace(limits.transport_policy(),total=remaining,
                    deadline_monotonic=min(deadline,time.monotonic()+remaining)),response_kind='source_artifact' if artifact else 'structured')
            timing.mark('response_complete');timing.mark('parse_started')
            original=raw if isinstance(raw,str) else canonical(raw)
            (folder/'provider-original.txt').write_bytes(original.encode('utf8'))
            if folder.name in {'directions','directions-completion'}:
                ledger.value['direction_response']=dict(path=str(folder/'provider-original.txt'),sha256=digest(original),
                    provider=selection.provider,model=selection.model,completed=True)
                ledger.save()
            check()
            if artifact:
                from .source_artifact import to_theme
                if artifact.get('recovery'):
                    from .artwork_recovery import merge_completion
                    raw=merge_completion(raw,artifact['recovery'],artifact['identity'])
                    (folder/'source-completed.txt').write_text(raw,'utf8')
                parsed, receipt = to_theme(raw,artifact['identity'],artifact['direction'])
                if artifact.get('recovery'):
                    receipt['recovered_sections']=list(artifact['recovery']['parts'])
                    receipt['original_prefix_sha256']=artifact['recovery']['sha256']
                (folder/'artifact-receipt.json').write_text(canonical(receipt),'utf8')
                from .artwork_recovery import inspect_source
                source_checkpoints(folder,inspect_source(raw,artifact['identity']))
                if stage_callback:stage_callback('作品接收完成 · 准备安全预览')
            else:parsed=response_object(raw)
            (folder/'parsed.json').write_text(canonical(parsed),'utf8')
            timing.mark('parse_complete');outcome='complete'
            progress.finish('complete')
            return parsed
        except Exception as exc:
            # Flush the final sub-second chunk before inspecting recoverable
            # sections. Otherwise a quick transport failure loses its tail.
            progress.emit()
            if artifact:
                from .artwork_recovery import save_recovery,retain_prefix
                recovery=(retain_prefix(folder,artifact['recovery'],artifact['identity']) if artifact.get('recovery')
                          else save_recovery(folder,artifact['identity']))
                source_checkpoints(folder,recovery)
                if active_candidate:
                    ledger.value['candidate_states'][active_candidate]['source_recovery']={k:v for k,v in recovery.items() if k!='parts'}
            if getattr(exc,'category','')=='request_too_large':
                local_trace=dict(provider=selection.provider,model=selection.model,
                    failure_stage='local_budget',failure_category='request_too_large',dispatched=False,
                    request_budget=getattr(exc,'report',None),assembly=assembly)
            outcome='cancelled' if (cancel_check and cancel_check()) or (active_candidate and candidate_cancel_check and candidate_cancel_check(active_candidate)) else 'failed'
            progress.finish(outcome);raise
        finally:
            trace=redact_diagnostics(local_trace if local_trace is not None else getattr(client,'invocation_trace',lambda:{})())
            timing.finish(outcome,trace)
            (folder/'invocation.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),'utf8')
            ledger.value.setdefault('invocations',[]).append(dict(stage=label,path=str(folder/'invocation.json'),
                elapsed_seconds=time.monotonic()-progress.phase['started_monotonic'],provider=selection.provider,model=selection.model))
            ledger.save()
    def call(label,folder,schema,message,**kwargs):
        original_folder=folder
        while True:
            if kwargs.get('artifact') and folder!=original_folder:
                from .theme_persistence import write_text_atomic
                write_text_atomic(original_folder/'latest-source.json',canonical({'folder':str(folder.relative_to(original_folder))}))
            try:return call_once(label,folder,schema,message,**kwargs)
            except Exception as exc:
                check()
                delay=transport_retry_delay(exc,len(task_budget.repairs))
                partial=folder/'provider-partial.txt'
                # A partial source needs targeted completion, not retransmission.
                if partial.exists() and partial.stat().st_size and delay is not None:
                    exc.category='structured_output_truncated'
                    raise
                if delay is None:
                    raise
                if task_budget.remaining() <= delay+5:
                    raise AIProviderError('服务端等待时间超出任务剩余预算；已停止恢复',category='repair_budget_exhausted') from exc
                receipt=recover(str(exc))
                report_event(dict(name='retry_wait',label=f'恢复 {receipt["attempt"]}/{task_budget.max_repairs} · {delay:g}s后重连',
                    request_id=request_id+'/retry',status='repairing',started_monotonic=time.monotonic(),
                    retry_reason=str(exc)[:600],retry_after_seconds=delay))
                wait_for_retry(delay,task_budget,cancelled)
                folder=original_folder/('transport-retry-'+str(receipt['attempt']))
    if retained:
        directions=copy.deepcopy(retained['directions'])
    else:
        from .authored_prompt import assemble
        # The exact fixed implementation contract must fit before paying for
        # direction planning. This lower bound is not a promise that every
        # future direction will fit; each final serialized request is checked.
        from .provider_input_budget import prepare_input, project_transport_messages, InputBudgetError
        from .llm_config import endpoint_from_settings
        from .model_discovery import model_limits
        from .ai_providers import transport_for_stage
        endpoint = endpoint_from_settings(settings, 'polish')
        source_schema = None
        fixed, fixed_assembly = assemble(ledger, direction={}, schema=source_schema)
        content = [{'type':'text', 'text':fixed}, *(image_parts or [])] if image_parts else fixed
        fixed_messages = project_transport_messages([{'role':'user','content':content}], source_schema,
                                                    transport_for_stage(settings,'polish'))
        try:
            _, fixed_budget = prepare_input(fixed_messages, schema=source_schema, max_tokens=tokens,
                operation='generate', scope={'kind':'implementation_fixed_lower_bound'},
                model_limits=model_limits(endpoint.get('provider',''), endpoint.get('base_url',''),
                                          endpoint.get('api_key',''), endpoint.get('model','')))
        except InputBudgetError as exc:
            ledger.value['implementation_preflight'] = dict(passed=False, budget=exc.report, assembly=fixed_assembly)
            ledger.save()
            error = AIProviderError('固定实现契约超过输入预算；构思尚未发送。'+str(exc), category='request_too_large')
            error.report = exc.report
            raise error from exc
        ledger.value['implementation_preflight'] = dict(passed=True, budget=fixed_budget, assembly=fixed_assembly,
            scope='仅固定开销；返回设计方向后逐稿再次检查')
        ledger.save()
        message, assembly = assemble(ledger, schema=direction_schema(requested_count,drafts=drafts))
        try:
            directions=call('构思设计方向',ledger.root/'directions',direction_schema(requested_count,drafts=drafts),message,
                max_tokens=16000 if selection.provider=='deepseek' else 8000, assembly=assembly)
            directions=normalize_directions(directions)
        except Exception as exc:
            check()
            if not repair_limit or not can_complete(exc,remaining=deadline-time.monotonic()):raise
            from .authored_prompt import compose as prompt_compose,compact_context
            from .caption_components import capability_text
            from .caption_reference_catalog import component_style
            # Planning/component replies can also be empty. Keep the request,
            # reference ledger and any returned description before retrying.
            response=ledger.root/'directions/provider-original.txt'
            if not response.exists():response=ledger.root/'directions/provider-partial.txt'
            checkpoint(ledger.root,'description',response.read_text('utf8') if response.exists() else '',status='partial',origin='provider')
            compact,receipt=prompt_compose(dict(step_contract=f'上次未给出可运行结果。完成原任务的{requested_count}个方向，直接返回约定JSON；不要额外分析。'+('每项必须包含完整components实现。' if drafts else ''),
                user_requirement=ledger.value['raw_user_prompt'],resources=compact_context(ledger.value.get('creative_context',{})),
                saved_description=response.read_text('utf8') if response.exists() else '',
                verified_components=capability_text(component_style(ledger.value['raw_user_prompt'])) if drafts else '本阶段只给name/design'),
                schema=direction_schema(requested_count,drafts=drafts))
            ledger.value['automatic_direction_completion']=dict(attempt=1,reason=str(exc)[:500]);ledger.save()
            recover(str(exc))
            directions=call('自动补完方向与实现 1/1',ledger.root/'directions-completion',direction_schema(requested_count,drafts=drafts),compact,
                max_tokens=16000 if selection.provider=='deepseek' else 8000,assembly=receipt)
    directions=normalize_directions(directions)
    from .caption_style_reference import validate_draft_diversity
    validate_draft_diversity(directions, ledger.value['raw_user_prompt'])
    if not retained and len(directions['candidates'])!=requested_count:
        raise ValueError('方向响应数量与本次选择不符；保留原响应，不自动追加调用')
    rows=copy.deepcopy(directions['candidates'])
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('方向ID必须互不相同')
    # Persist validated design decisions before any long source request.
    ledger.value['directions']=copy.deepcopy(directions)
    checkpoint(ledger.root,'direction',directions,origin='saved_direction' if retained else 'provider')
    ledger.value['status']='implementing';ledger.save()
    if drafts:
        from .caption_components import compose
        retained=dict(retained or {})
        saved_sources=copy.deepcopy(retained.get('candidates',{}))
        component_failures={}
        for row in rows:
            if not saved_sources.get(row['id'],{}).get('generated_source'):
                try:saved_sources[row['id']]=dict(generated_source=dict(name=row['name'],**compose(row['components'])))
                except ValueError as exc:component_failures[row['id']]=str(exc)
        retained['candidates']=saved_sources
        retained['component_failures']=component_failures
    if not only_candidate and requested_count==1:rows=rows[:1]
    if not only_candidate and len(rows)>1 and client_factory is not None and not drafts:
        from .candidate_scheduler import run_candidates
        def worker(row,events):
            check()
            child=ThemeLedger(ledger.root/'jobs'/row['id'],ledger.value['raw_user_prompt'])
            child.value.update(creative_context=copy.deepcopy(ledger.value.get('creative_context',{})),
                reference_files=copy.deepcopy(ledger.value.get('reference_files',[])),style_reference=copy.deepcopy(ledger.value.get('style_reference')),reference_search=copy.deepcopy(ledger.value.get('reference_search')),
                provider_inputs=copy.deepcopy(ledger.value.get('provider_inputs',[])))
            result=generate_staged(child,client_factory(),selection,prompt,settings,
                request_id=request_id+'/'+row['id'],cancel_check=cancel_check,candidate_cancel_check=candidate_cancel_check,
                stage_event_callback=events,deadline_seconds=max(.1,deadline-time.monotonic()),
                retained={'directions':directions,'candidates':(retained or {}).get('candidates',{})},
                image_parts=image_parts,render_candidate=render_candidate,only_candidate=row['id'],task_budget=task_budget)
            return result,child
        return run_candidates(ledger,rows,worker,concurrency=settings.get('models',{}).get('ai_design_concurrency',2),
            cancel_check=cancel_check,event_callback=stage_event_callback,request_id=request_id)
    for row in rows:row['generated_source']={}
    concepts=[]
    ledger.value['scheduling']=dict(requested_candidates=1 if only_candidate else len(rows),
        configured_concurrency=1,actual_peak_candidates=0,provider_limit='provider broker also applies its configured limits')
    for row in rows:
        if only_candidate is None or row['id']==only_candidate:
            ledger.value['candidate_states'][row['id']]=dict(status='queued',stage='application_queue',queued_at=time.time())
    def publish_candidate():
        from .design_progress import aggregate_activity
        budget=task_budget.snapshot();ledger.value['task_budget']=budget
        for value in ledger.value['candidate_states'].values():value['task_budget']=budget
        ledger.save()
        if stage_event_callback:
            stage_event_callback(dict(name='candidate_progress',label='候选独立进行',request_id=request_id+'/candidates',
                status='running',started_monotonic=started,task_budget=budget,**aggregate_activity(ledger.value['candidate_states']),
                candidate_states=copy.deepcopy(ledger.value['candidate_states']),partial_concepts=copy.deepcopy(concepts),
                brief={k:ledger.value[k] for k in ('raw_user_prompt','raw_prompt_hash','theme')},
                pending_directions=[dict({k:v for k,v in r.items() if k!='generated_source'},
                    preview_picture=ledger.value['candidate_states'].get(r['id'],{}).get('preview_picture')) for r in rows
                    if r['id'] not in {c['id'] for c in concepts} and (only_candidate is None or r['id']==only_candidate)]))
    publish_candidate()
    for index,row in enumerate(rows):
        ident=row['id']
        if only_candidate is not None and ident!=only_candidate:continue
        active_candidate=ident
        child=ThemeLedger(ledger.root/'candidates'/ident/'v1',ledger.value['raw_user_prompt'])
        child.value.update(reference_files=copy.deepcopy(ledger.value.get('reference_files',[])),style_reference=copy.deepcopy(ledger.value.get('style_reference')),reference_search=copy.deepcopy(ledger.value.get('reference_search')),
            creative_context=copy.deepcopy(ledger.value.get('creative_context',{})),parent_ledger=str(ledger.root/'ledger.json'),
            candidate_id=ident,candidate_version=1,pipeline=STAGED_VERSION)
        state=dict(candidate_id=ident,version=1,stage='implementation',status='running',
            started_at=time.time(),repairs=0,ledger_path=str(child.root/'ledger.json'))
        checkpoint(child.root,'direction',{k:v for k,v in row.items() if k!='generated_source'},origin='saved_direction')
        checkpoint(child.root,'description',row.get('design_spec',{}),origin='saved_direction')
        from .authored_prompt import direction_adjustment
        adjustment=direction_adjustment(row) if retained else ''
        if adjustment:
            state['direction_adjustment']=adjustment
            child.value['direction_adjustment']=adjustment
        ledger.value['candidate_states'][ident]=state
        ledger.value['scheduling']['actual_peak_candidates']=1
        publish_candidate()
        try:
            check()
            kept=(retained or {}).get('candidates',{}).get(ident)
            if kept:
                row['generated_source']=copy.deepcopy(kept['generated_source'])
                state['reused_source_hash']=digest(canonical(row['generated_source']))
            else:
                source_schema=None
                from .authored_prompt import assemble
                artifact_identity=request_id+'/'+ident+'/v1'
                message, assembly = assemble(ledger, direction=row, artifact_identity=artifact_identity)
                component_failure=(retained or {}).get('component_failures',{}).get(ident)
                if component_failure:
                    if not repair_limit:raise ValueError(component_failure)
                    recover(component_failure)
                    message,assembly=implementation_message(ledger,row,artifact_identity)
                    state.update(stage='auto_completing',automatic_completions=1)
                    child.value['automatic_completion']=dict(attempt=1,reason=component_failure,
                        category='component_definition',mode='from_description',status='running')
                    child.save();publish_candidate()
                recovery=(retained or {}).get('recoveries',{}).get(ident)
                if recovery and recovery.get('mode') in {'complete_sections','continue_tail'}:
                    from .artwork_recovery import completion_contract
                    from .source_artifact import contract as source_contract
                    message=message.replace(source_contract(artifact_identity),completion_contract(recovery,artifact_identity))
                try:
                    if recovery and recovery.get('mode')=='revalidate':
                        from .source_artifact import frame,to_theme
                        parsed,receipt=to_theme(frame(recovery['parts'],artifact_identity),artifact_identity,row)
                        receipt.update(original_prefix_sha256=recovery['sha256'],revalidated_saved_source=True)
                        (child.root/'artifact-receipt.json').write_text(canonical(receipt),'utf8')
                    else:
                        parsed=call('补全作品 '+ident if recovery and recovery.get('mode')=='complete_sections' else '生成作品 '+ident,child.root,source_schema,message,max_tokens=tokens,
                            scope={'kind':'implementation_completion' if component_failure or recovery or (retained or {}).get('explicit_recovery') else 'one_candidate','candidate_ids':[ident]}, assembly=assembly,
                            artifact={'identity':artifact_identity,'direction':row,
                                'recovery':recovery if recovery and recovery.get('mode') in {'complete_sections','continue_tail'} else None})
                except Exception as exc:
                    check()
                    # A single bounded second communication, not a recursive
                    # retry of planning, peers, searches or completed source.
                    if not repair_limit or not can_complete(exc,remaining=deadline-time.monotonic(),used=1 if component_failure or retained and retained.get('explicit_recovery') else 0):
                        if component_failure:
                            child.value['automatic_completion'].update(status='failed',error=str(exc)[:600]);child.save()
                        raise
                    recover(str(exc))
                    from .artwork_recovery import saved_recovery
                    recovery=saved_recovery(child.root)
                    completion_identity=request_id+'/'+ident+'/completion-1'
                    message,assembly=implementation_message(ledger,row,completion_identity,recovery)
                    state.update(stage='auto_completing',automatic_completions=1)
                    child.value['automatic_completion']=dict(attempt=1,reason=str(exc)[:600],
                        category=getattr(exc,'category','implementation_error'),
                        mode=(recovery or {}).get('mode','from_description'),status='running')
                    child.save();publish_candidate()
                    if stage_callback:stage_callback('方向 '+ident+f' 实现未完成 · 自动恢复 {len(task_budget.repairs)}/{task_budget.max_repairs}，保留已有说明')
                    try:
                        parsed=call('自动补完作品 '+ident,child.root/'completion-1',None,message,max_tokens=tokens,
                            scope={'kind':'implementation_completion','candidate_ids':[ident],'attempt':1},assembly=assembly,
                            artifact={'identity':completion_identity,'direction':row,'recovery':recovery if recovery and recovery.get('mode') in {'complete_sections','continue_tail'} else None})
                    except Exception:
                        child.value['automatic_completion']['status']='failed';child.save();raise
                    child.value['automatic_completion']['status']='complete';child.save()
                if component_failure:
                    child.value['automatic_completion']['status']='complete';child.save()
                row['generated_source']=candidate_source(parsed,ident,child)
                if not row['generated_source'].get('name'):
                    row['generated_source']['name']=row['name']
                    child.value.setdefault('normalization',[]).append(dict(path='generated_source.name',
                        action='inherit_validated_direction_name',value=row['name']))
            source=row['generated_source']
            checkpoint(child.root,'structure',source.get('cueHtml',''),origin='validated_implementation')
            checkpoint(child.root,'html',source.get('cueHtml',''),origin='validated_implementation')
            checkpoint(child.root,'css',dict(cueCss=source.get('cueCss',''),stageCss=source.get('stageCss','')),origin='validated_implementation')
            checkpoint(child.root,'motion',source.get('motionSpec',{}),origin='validated_implementation')
            state.update(stage='technical_validation',status='running',compile_started_at=time.time())
            publish_candidate()
            assembly=child.root/'provider-assembled.json';assembly.write_text(canonical({'candidates':rows}),'utf8')
            child.value['raw_response']=dict(path=str(assembly),sha256=digest(assembly.read_bytes()),
                provider=selection.provider,model=selection.model,completed=not bool(child.value.get('unaccepted_proposal')),
                kind='unaccepted_schema_proposal' if child.value.get('unaccepted_proposal') else 'assembled_direction_and_sources')
            child.value['stage_original']=str(child.root/('provider-partial.txt' if child.value.get('unaccepted_proposal') else 'provider-original.txt')) if not kept else None
            budget_calls=[state.get('automatic_completions',0)]
            repair_receipts=[0]
            patch,regenerate=provider_callbacks(client,request_id+'/'+ident,cancel_check=cancelled,
                stage_callback=stage_callback,stage_event_callback=stage_event_callback,
                remaining_seconds=lambda:max(0.,deadline-time.monotonic()),trace_root=child.root)
            def bounded(fn):
                def run(*args):
                    check()
                    if budget_calls[0]>=repair_limit:raise ValueError('此稿已达到本轮技术修复调用上限')
                    recover('技术校验失败，定向修复')
                    budget_calls[0]+=1;state['repairs']=budget_calls[0];ledger.save()
                    result=fn(*args)
                    repair_receipts[0]+=1
                    return result
                return run
            partial=accept_authored_set({'candidates':rows},child,selection.provider,selection.model,
                technical_repair=bounded(patch) if repair_limit else None,candidate_regenerate=bounded(regenerate) if repair_limit else None,
                allow_partial=True,repair_indices={index},cancel_check=cancelled,request_id=request_id+'/'+ident)
            concept=next(c for c in partial.concepts if c['id']==ident)
            concept['reference_research']=copy.deepcopy(ledger.value.get('reference_search'))
            component_response = drafts and bool(ledger.value.get('direction_response'))
            artifact_receipt=child.root/'artifact-receipt.json'
            if artifact_receipt.is_file():
                component_response=bool(json.loads(artifact_receipt.read_text('utf8')).get('component_definition'))
            concept['source_origin']=('local_fixture' if selection.model=='local-caption-fixture'
                else 'model_components_new' if component_response else 'historical_response' if kept else 'model_new')
            recovery=(retained or {}).get('recoveries',{}).get(ident)
            if recovery and not kept:
                concept['source_origin']='saved_source_revalidated' if recovery.get('mode')=='revalidate' else 'model_source_completed'
            if child.value.get('automatic_completion'):
                concept['automatic_completion']=copy.deepcopy(child.value['automatic_completion'])
                concept['source_origin']='model_source_completed'
            if selection.model=='local-caption-fixture':concept['source_origin']='local_fixture'
            child.value['source_origin']=concept['source_origin']
            child.value['provider_inputs']=copy.deepcopy(ledger.value.get('provider_inputs',[]))
            child.save()
            if adjustment:concept['direction_adjustment']=adjustment
            if child.value.get('unaccepted_proposal') and not repair_receipts[0]:
                raise AIProviderError('未验收提案没有新的技术修复回执，不能采用。',category='structured_output_schema')
            if concept.get('technical_status')!='failed':
                rows[index]=copy.deepcopy(next(c for c in child.value['candidates'] if c['id']==ident))
                state.update(stage='render_pending',status='complete',compile_complete_at=time.time(),source_hash=rows[index]['generated_source_hash'])
                if render_candidate:
                    state.update(stage='rendering',status='running');publish_candidate()
                    def preview_progress(label):
                        if concept.get('static_preview_ready'):
                            state['preview_picture']=concept['preview_picture']
                        state['stage']=label;publish_candidate()
                        if stage_callback:stage_callback(label)
                    def retry_preview():
                        state['local_preview_rebuilds']=1
                        preview_progress('自动重建预览 1/1 · 保留源码，不调用模型')
                    try:
                        from .design_recovery import preview_with_recovery
                        preview=preview_with_recovery(render_candidate,concept,child.root/'preview',
                            ledger.value.get('creative_context',{}).get('subtitle_text','字幕'),
                            remaining=lambda:deadline-time.monotonic(),on_retry=retry_preview,
                            cancel_check=cancelled,
                            progress=preview_progress)
                        concept.update(motion_preview=preview['motion'],preview_picture=preview['picture'],
                            full_frame_preview=preview['full_frame'],preview_receipt=preview,
                            semantic_review=preview.get('semantic_review','not_run'))
                        check()
                        state.update(stage='ready',status='complete',detail='',preview_seconds=preview['elapsed_seconds'],preview_milestones=preview.get('milestones',{}))
                        checkpoint(child.root,'preview',preview,origin='production_renderer')
                        checkpoint(child.root,'acceptance',dict(technical=True,preview=True,user_selected=False),origin='production_validation')
                    except Exception as exc:
                        if cancel_check and cancel_check():check()
                        if candidate_cancel_check and candidate_cancel_check(ident):
                            raise AIProviderError('此候选预览已取消',category='candidate_cancelled') from exc
                        # Shared browser failures are not authoring failures.
                        # Only diagnosed content/geometry gets one new version.
                        if (getattr(exc,'category','')=='render_validation'
                                and deadline-time.monotonic()>45 and budget_calls[0]<repair_limit):
                            recover(str(exc))
                            budget_calls[0]+=1
                            state.update(stage='render_repair',render_repairs=1,repairs=budget_calls[0]);ledger.save()
                            evidence=getattr(exc,'render_evidence',{})
                            repair_context={'errors':evidence.get('errors',[str(exc)]),
                                'alpha_coverage':evidence.get('alpha_coverage'),
                                'failed_text_cases':[{k:c.get(k) for k in ('duration_ms','text','invalid_runs','composed_text')}
                                    for c in evidence.get('text_cases',[]) if not c.get('passed')],
                                'actual_frame_paths':evidence.get('review_images',[])}
                            version=ThemeLedger(ledger.root/'candidates'/ident/'v2',ledger.value['raw_user_prompt'])
                            version.value.update(reference_files=copy.deepcopy(child.value['reference_files']),
                                creative_context=copy.deepcopy(child.value.get('creative_context',{})),candidate_id=ident,
                                candidate_version=2,parent_ledger=str(child.root/'ledger.json'),repair_context=repair_context)
                            version.save()
                            artifact_identity=request_id+'/'+ident+'/v2'
                            repair_message,repair_assembly=render_repair_message(ledger,row,concept['authored_theme'],repair_context,receipt=True,artifact_identity=artifact_identity)
                            fixed=call('修复方向 '+ident+' 的真实渲染',version.root,None,
                                repair_message,max_tokens=tokens,assembly=repair_assembly,
                                scope={'kind':'render_repair','candidate_ids':[ident],'version':2},
                                artifact={'identity':artifact_identity,'direction':row})
                            proposed=copy.deepcopy(rows)
                            proposed[index]['generated_source']=candidate_source(fixed,ident,version)
                            state.update(version=2,ledger_path=str(version.root/'ledger.json'))
                            assembly=version.root/'provider-assembled.json';assembly.write_text(canonical({'candidates':proposed}),'utf8')
                            version.value['raw_response']=dict(path=str(assembly),sha256=digest(assembly.read_bytes()),
                                provider=selection.provider,model=selection.model,completed=True,kind='assembled_render_repair')
                            patch2,regenerate2=provider_callbacks(client,request_id+'/'+ident+'/v2',cancel_check=cancelled,
                                stage_callback=stage_callback,stage_event_callback=stage_event_callback,
                                remaining_seconds=lambda:max(0.,deadline-time.monotonic()),trace_root=version.root)
                            candidate_set=accept_authored_set({'candidates':proposed},version,selection.provider,selection.model,
                                allow_partial=True,repair_indices={index},technical_repair=bounded(patch2),
                                candidate_regenerate=bounded(regenerate2),cancel_check=cancelled,request_id=request_id+'/'+ident+'/v2')
                            revised=next(c for c in candidate_set.concepts if c['id']==ident)
                            if revised.get('technical_status')!='failed':
                                try:
                                    preview=render_candidate(revised,version.root/'preview',
                                        ledger.value.get('creative_context',{}).get('subtitle_text','字幕'),
                                        cancel_check=lambda:cancelled() or task_budget.remaining()<=0,progress=stage_callback or (lambda _:None))
                                    check()
                                    revised.update(motion_preview=preview['motion'],preview_picture=preview['picture'],
                                        full_frame_preview=preview['full_frame'],preview_receipt=preview,semantic_review=preview.get('semantic_review','not_run'))
                                    concept=revised;child=version
                                    rows[index]=copy.deepcopy(next(c for c in version.value['candidates'] if c['id']==ident))
                                    state.update(stage='ready',status='complete',version=2,ledger_path=str(version.root/'ledger.json'),
                                        preview_seconds=preview['elapsed_seconds'],source_hash=rows[index]['generated_source_hash'])
                                    exc=None
                                except Exception as retry_error:exc=retry_error;concept=revised;child=version
                            else:
                                concept=revised;child=version
                                exc=ValueError('修复稿仍未通过技术检查：'+canonical(revised.get('technical_errors',[]))[:800])
                                exc.category='technical_validation'
                        if exc is None:
                            concepts.append(concept)
                            # Fall through to the common checkpoint/event below.
                        else:
                            errors=[dict(candidate_id=ident,stage='render_validation',version=state.get('version',1),blocking=True,
                                category=getattr(exc,'category','runtime_render'),path='rendered_preview',constraint=str(exc)[:1000],
                                expected='根据已保存真实错误帧局部修复，再复验相同案例')]
                            concept.update(technical_status='failed',preview_failed=True,technical_errors=errors)
                            state.update(stage='render_validation',status='failed',errors=errors)
                            latest=ThemeLedger.open(child.root/'ledger.json')
                            latest.value['candidate_failures']=[dict(id=ident,errors=errors)];latest.save()
            else:state.update(stage='technical_validation',status='failed',errors=concept['technical_errors'])
            if not any(c['id']==ident for c in concepts):concepts.append(concept)
        except Exception as exc:
            if getattr(exc,'category','')=='cancelled' and not (candidate_cancel_check and candidate_cancel_check(ident)):raise
            category=getattr(exc,'category','implementation_error')
            if candidate_cancel_check and candidate_cancel_check(ident):category='candidate_cancelled'
            if category=='request_too_large':state['stage']='local_budget'
            elif category in {'output_truncated','reasoning_only','provider_no_body',
                    'structured_output_truncated','structured_output_reasoning_exhausted'}:state['stage']='output_incomplete'
            if state.get('source_recovery',{}).get('body_chars')==0 and state['stage']=='output_incomplete':
                state['stage']='response_without_source'
            state.update(status='cancelled' if category=='candidate_cancelled' else 'failed',category=category,error=str(exc)[:600])
            if category=='request_too_large':
                state['budget_report']=getattr(exc,'report',{})
                child.value['budget_report']=state['budget_report']
            concepts.append(dict(id=ident,name=row['name'],composition=(
                '设计说明已保存；实现请求被输入预算阻断' if state['stage']=='local_budget' else
                '自动补完后仍无实现正文；说明与参考已保存，可在应用内继续完成此方向' if state['stage']=='response_without_source' else
                '模型已响应但实现正文不完整；原响应与设计说明已保存' if state['stage']=='output_incomplete' else
                '此方向未完成，设计说明已保存'),
                technical_status='failed',technical_errors=[dict(candidate_id=ident,stage=state['stage'],version=1,
                    category=state['category'],constraint=state['error'],path='generated_source',blocking=True,
                    expected='继续已保存的设计说明，仅重试此方向',budget_report=state.get('budget_report'))],creative_version='caption-creative-source-9',
                direction_adjustment=adjustment,
                source_recovery=copy.deepcopy(state.get('source_recovery',{})),
                automatic_completion=copy.deepcopy(child.value.get('automatic_completion',{})),
                ledger_path=str(child.root/'ledger.json'),provider=selection.provider))
            child.value.update(status='failed',error=str(exc)[:600],candidate_failures=[copy.deepcopy(concepts[-1])]);child.save()
        state.update(finished_at=time.time(),finished_monotonic=time.monotonic(),task_budget=task_budget.snapshot());ledger.save()
        assembled={'candidates':[{k:v for k,v in r.items() if k in AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['required']} for r in rows]}
        path=ledger.root/'provider-assembled.json';path.write_text(canonical(assembled),'utf8')
        ledger.value['raw_response']=dict(path=str(path),sha256=digest(path.read_bytes()),provider=selection.provider,
            model=selection.model,completed=len(concepts)==(1 if only_candidate else len(rows)),kind='assembled_stages')
        ledger.value['candidates']=[copy.deepcopy(r) for r in rows if r.get('generated_source_hash')]
        ledger.value['partial_concepts']=copy.deepcopy(concepts);ledger.save()
        if stage_event_callback:
            stage_event_callback(dict(name='candidate_complete',label='方向 '+ident+' 已保存',request_id=request_id+'/'+ident,
                status=state['status'],started_monotonic=started,task_budget=task_budget.snapshot(),**aggregate_activity(ledger.value['candidate_states']),
                candidate_id=ident,completed_candidates=len(concepts),candidate_states=copy.deepcopy(ledger.value['candidate_states']),
                partial_concepts=copy.deepcopy(concepts),brief={'raw_user_prompt':ledger.value['raw_user_prompt'],
                'raw_prompt_hash':ledger.value['raw_prompt_hash'],'theme':ledger.value['theme']},
                pending_directions=[{k:v for k,v in r.items() if k!='generated_source'} for r in rows if r['id'] not in {c['id'] for c in concepts} and not only_candidate]))
    from .studio_ai import AIWebThemeSuggestion
    ready=sum(c.get('technical_status')!='failed' for c in concepts)
    usable=sum(bool(c.get('motion_preview')) and c.get('technical_status')!='failed' for c in concepts)
    ledger.value.update(status=('ready' if usable else 'render_pending') if ready else 'failed',elapsed_seconds=time.monotonic()-started);ledger.save()
    total=1 if only_candidate else len(rows)
    return AIWebThemeSuggestion(theme={},source='concepts',message=f'{usable}/{total}稿有完整动画，{total-ready}稿尚未完成（各稿显示具体阶段）',
        request_id=request_id,provider=selection.provider,model=selection.model,
        brief={'raw_user_prompt':ledger.value['raw_user_prompt'],'raw_prompt_hash':ledger.value['raw_prompt_hash'],
               'theme':ledger.value['theme']},concepts=concepts,selected_concept_id='',
        quality={'design_version':4,'creative_version':'caption-creative-source-9','ledger_path':str(ledger.root/'ledger.json')})
