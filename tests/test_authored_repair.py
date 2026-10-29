import copy,json
from types import SimpleNamespace
import pytest
from scripts.author_balatro_candidates import candidates
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,accept_authored_set
from twobyteasr.caption_design.authored_repair import collect_issues,apply_patch_transaction,css_values


def broken():
    rows=candidates();source=rows[0]['generated_source'];track=source['motionSpec']['tracks'][0]
    track['from']['rotationY']=180;track['to']['rotationY']=0
    track['from']['backgroundPositionX']='100%';track['to']['backgroundPositionX']=0
    track['from']['x']=10;track['to'].pop('x',None)
    track['selector']='.invalid.compound'
    source['cueHtml']+='<i class="audit-surface"></i>'
    source['cueCss']+=' .audit-surface{background-image:url("data:image/svg+xml,abc");color:#FFFFFF;}'
    rows[1]['generated_source']['stageHtml']='<i class="audit-stage"></i>'
    rows[1]['generated_source']['stageCss']='.audit-stage{opacity:.2;}'
    return {'candidates':rows}


def reply(issues):
    patches=[]
    for issue in issues:
        schema=issue['replacement_schema'];kind=issue['category']
        if kind=='selector':value=candidates()[issue['candidate_index']]['generated_source']['motionSpec']['tracks'][0]['selector']
        elif kind=='css_url':value='linear-gradient(90deg,#FFFFFF,#A0A0A0)'
        elif schema.get('type') in ('number','integer'):value=max(schema.get('minimum',0),min(0,schema.get('maximum',0)))
        else:raise AssertionError(issue)
        patches.append(dict(candidate_index=issue['candidate_index'],path=issue['path'],value=value))
    return {'patches':patches}


def test_collects_independent_errors_without_mutating_original(tmp_path):
    data=broken();before=copy.deepcopy(data)
    issues=collect_issues(data,ThemeLedger(tmp_path,'Balatro'))
    assert data==before
    assert {'numeric_range','numeric_type','from_to','selector','css_url','stage_html'}<={i['category'] for i in issues}
    assert len({i['path'] for i in issues if i['repair']=='patch'})==len([i for i in issues if i['repair']=='patch'])


def test_out_of_range_opacity_keeps_safety_without_aesthetic_minimum(tmp_path):
    rows=candidates();rows[0]['generated_source']['motionSpec']['tracks'][0]['from']['opacity']=-1
    ledger=ThemeLedger(tmp_path,'Balatro');ledger.value['require_readable_first_frame']=True
    issues=collect_issues({'candidates':rows},ledger)
    matching=[i for i in issues if i['path']=='candidates[0].generated_source.motionSpec.tracks[0].from.opacity']
    assert len(matching)==1
    assert matching[0]['replacement_schema']['minimum']==0
    assert matching[0]['category']=='numeric_range'


def test_exit_repeat_is_one_repairable_leaf_and_preserves_other_artwork(tmp_path):
    rows=candidates()
    tracks=rows[2]['generated_source']['motionSpec']['tracks']
    index=next(i for i,t in enumerate(tracks) if t['phase']=='resolve')
    tracks[index]['repeat']=3
    payload={'candidates':rows};before=copy.deepcopy(payload)
    ledger=ThemeLedger(tmp_path,'balatro小丑牌风格')
    issues=[i for i in collect_issues(payload,ledger) if i['candidate_index']==2]
    path=f'candidates[2].generated_source.motionSpec.tracks[{index}].repeat'
    assert len(issues)==1 and issues[0]['path']==path
    assert issues[0]['category']=='motion_repeat_phase' and issues[0]['repair']=='patch'
    assert payload==before
    fixed,changed=apply_patch_transaction(payload,{'patches':[dict(candidate_index=2,path=path,value=0)]},issues)
    assert changed==[path] and fixed['candidates'][:2]==before['candidates'][:2]
    assert not collect_issues(fixed,ledger)
    with pytest.raises(ValueError):
        apply_patch_transaction(payload,{'patches':[dict(candidate_index=2,path=path,value=1)]},issues)


def test_missing_source_fields_have_typed_local_scope_without_rewriting_material(tmp_path):
    rows=candidates();saved=copy.deepcopy(rows[2]['generated_source'])
    for field in ('cueHtml','cueCss','motionSpec'):rows[2]['generated_source'].pop(field)
    ledger=ThemeLedger(tmp_path,'Balatro');payload={'candidates':rows}
    issues=[i for i in collect_issues(payload,ledger) if i['candidate_index']==2]
    assert {i['path'] for i in issues}=={f'candidates[2].generated_source.{key}' for key in ('cueHtml','cueCss','motionSpec')}
    assert all(i['repair']=='regenerate' and i['exists'] is False and i['replacement_schema'] for i in issues)
    patches={'patches':[dict(candidate_index=2,path=i['path'],value=saved[i['path'].rsplit('.',1)[1]]) for i in issues]}
    repaired,_=apply_patch_transaction(payload,patches,issues)
    assert repaired['candidates'][:2]==rows[:2]
    assert repaired['candidates'][2]['MaterialContract']==rows[2]['MaterialContract']
    assert repaired['candidates'][2]['generated_source']==saved


def test_child_budget_uses_remaining_parent_and_retains_failed_invocation(tmp_path):
    from twobyteasr.caption_design.authored_repair import provider_callbacks
    from twobyteasr.providers.ai_providers import AIProviderError
    calls=[]
    class Client:
        transport='grok_cli'
        def complete(self,messages,**kwargs):
            calls.append(kwargs);raise AIProviderError('fixture timeout',category='timeout')
        def invocation_trace(self):return {'request_id':'child-fixture','timeout_seconds':12,'reported_usage':None}
    patch,_=provider_callbacks(Client(),'parent',remaining_seconds=lambda:12,trace_root=tmp_path)
    with pytest.raises(AIProviderError) as caught:patch([dict(path='x',replacement_schema={'type':'number'})],'repair',{})
    assert calls[0]['timeout']==12 and caught.value.repair_receipt['provider_request_id']=='child-fixture'
    assert json.loads((tmp_path/'invocation-repair.json').read_text('utf8'))['request_id']=='child-fixture'
    patch,_=provider_callbacks(Client(),'parent',remaining_seconds=lambda:0)
    with pytest.raises(AIProviderError,match='总时限'):patch([dict(path='x',replacement_schema={'type':'number'})],'no-call',{})
    assert len(calls)==1


def test_all_local_paths_one_request_and_stage_bytes_preserved(tmp_path):
    data=broken();before=copy.deepcopy(data);calls=[];ledger=ThemeLedger(tmp_path,'Balatro')
    def patch(issues,*args):calls.append(issues);return reply(issues)
    result=accept_authored_set(data,ledger,'fixture','model',technical_repair=patch,
        candidate_regenerate=lambda *args:pytest.fail('local errors do not require full candidate regeneration'),request_id='parent')
    assert data==before and len(calls)==1 and len(result.concepts)==3
    repaired=result.concepts[1]['authored_theme']
    assert '<i class="audit-stage"></i>' in repaired['cueHtml'] and '.audit-stage{opacity:.2;}' in repaired['cueCss']
    assert repaired['stageHtml']==repaired['stageCss']==''
    record=ledger.value['technical_repairs'][-1]
    assert record['status']=='applied' and record['parent_request_id']=='parent'
    assert all(path.startswith('candidates[0].') for path in record['changed_paths'])
    assert all(i['path'] in record['allowed_paths'] for i in calls[0])


def test_patch_rejects_changes_outside_a_css_value(tmp_path):
    data=broken();issues=[i for i in collect_issues(data,ThemeLedger(tmp_path,'Balatro')) if i['repair']=='patch']
    response=reply(issues);response['patches'].append(dict(candidate_index=2,path='candidates[2].name',value='changed'))
    with pytest.raises(Exception):apply_patch_transaction(data,response,issues)
    response=reply(issues);response['patches'][0]['path']='candidates[2].name'
    with pytest.raises(Exception):apply_patch_transaction(data,response,issues)


def test_same_dom_is_not_a_technical_failure(tmp_path):
    originals=candidates();rows=copy.deepcopy(originals);rows[1]=copy.deepcopy(rows[0]);rows[1]['id']='B'
    data={'candidates':rows};before=copy.deepcopy(data);calls=[]
    def regenerate(brief,*args):pytest.fail('DOM shape cannot decide visual diversity')
    result=accept_authored_set(data,ThemeLedger(tmp_path,'Balatro'),'fixture','model',
        technical_repair=lambda *a:pytest.fail('no scalar patch needed'),candidate_regenerate=regenerate)
    assert not calls and data==before
    # Existing safe serialization canonicalizes the HTML void tag spelling.
    assert result.concepts[0]['authored_theme']['cueHtml']==originals[0]['generated_source']['cueHtml'].replace('<br>','<br/>')
    assert result.concepts[2]['authored_theme']['cueCss']==originals[2]['generated_source']['cueCss']


def test_late_repair_after_parent_cancel_never_publishes(tmp_path):
    data=broken();before=copy.deepcopy(data);cancel=[False];ledger=ThemeLedger(tmp_path,'Balatro')
    def patch(issues,*args):cancel[0]=True;return reply(issues)
    with pytest.raises(Exception,match='cancel'):
        accept_authored_set(data,ledger,'fixture','model',technical_repair=patch,cancel_check=lambda:cancel[0])
    assert data==before and not ledger.value['candidates']
    assert ledger.value['technical_repairs'][-1]['status']=='cancelled'


def test_css_value_offsets_survive_quoted_semicolon_and_nested_functions():
    css='.a{background:url("data:image/svg+xml;a(b)");color:rgb(1,2,3)} .b{opacity:.5}'
    values=list(css_values(css))
    assert len(values)==3
    assert values[0]['value']=='url("data:image/svg+xml;a(b)")'
    assert all(css[row['start']:row['end']]==row['value'] for row in values)


def test_new_first_frame_contract_does_not_apply_to_hidden_text_copies(tmp_path):
    ledger=ThemeLedger(tmp_path,'Balatro');ledger.value['require_readable_first_frame']=True
    rows=candidates();source=rows[0]['generated_source']
    source['motionSpec']['tracks']=[{'selector':'.core','phase':'build','from':{'opacity':0},'to':{'opacity':1}},
        {'selector':'.outer','phase':'build','from':{'opacity':0},'to':{'opacity':1}}]
    issues=collect_issues({'candidates':rows},ledger)
    paths=[i['path'] for i in issues if i['category']=='first_frame_visibility' and i['candidate_index']==0]
    assert paths==[]


def test_exact_legacy_metadata_conversion_preserves_colors_and_selectors(tmp_path):
    rows=candidates();source=copy.deepcopy(rows)
    for row in rows:
        for role in row['ColorRole']:
            role['role']={'contrast':'text','highlight':'accent'}.get(role['role'],role['role'])
        row['MaterialContract']['selectors']=', '.join(row['MaterialContract']['selectors'])
    ledger=ThemeLedger(tmp_path,'Balatro')
    result=accept_authored_set({'candidates':rows},ledger,'fixture','model',technical_repair=lambda *a:pytest.fail('deterministic metadata needs no API'))
    assert len(result.concepts)==3
    assert ledger.value['technical_repairs'][0]['operation']=='local_exact_metadata'
    assert ledger.value['technical_repairs'][0]['model_calls']==0
    assert [row['ColorRole'] for row in ledger.value['candidates']]==[row['ColorRole'] for row in source]


def test_repeated_selector_context_fits_budget_without_dropping_paths(tmp_path):
    from twobyteasr.caption_design.authored_repair import provider_callbacks, patch_schema
    from twobyteasr.providers.provider_input_budget import prepare_input
    data=broken();issues=collect_issues(data,ThemeLedger(tmp_path,'Balatro'))
    selector=next(i for i in issues if i['category']=='selector')
    repeated=[]
    for index in range(12):
        issue=copy.deepcopy(selector);issue['path']=f'candidates[0].generated_source.motionSpec.tracks[{index}].selector'
        repeated.append(issue)
    calls=[]
    class Client:
        transport='openai_compatible'
        def complete(self,messages,**kwargs):
            prepared,budget=prepare_input(messages,schema=kwargs['json_schema'],max_tokens=kwargs['max_tokens'],
                operation=kwargs['operation_kind'],scope=kwargs['input_scope'])
            calls.append((prepared,budget));return {'patches':[]}
    patch,_=provider_callbacks(Client(),'parent')
    patch(repeated,'repair',patch_schema(repeated))
    prompt=calls[0][0][0]['content']
    assert all(i['path'] in prompt for i in repeated)
    assert prompt.count('parent_structure')==1 and calls[0][1]['passed']


def test_does_not_patch_a_candidate_that_needs_structural_regeneration(tmp_path):
    originals=candidates();rows=copy.deepcopy(originals)
    rows[1]['generated_source']['cueHtml']='<script>unsafe</script>'+rows[1]['generated_source']['cueHtml']
    rows[1]['generated_source']['motionSpec']['tracks'][0]['from']['opacity']=-1
    calls=[]
    result=accept_authored_set({'candidates':rows},ThemeLedger(tmp_path,'Balatro'),'fixture','model',
        technical_repair=lambda *a:pytest.fail('replaced structure must not consume a patch request'),
        candidate_regenerate=lambda brief,*args:(calls.append(brief) or originals[1]))
    assert len(result.concepts)==3 and len(calls)==1


def test_material_metadata_is_advisory_and_numeric_error_is_repaired(tmp_path):
    rows=candidates();before=copy.deepcopy(rows)
    source=rows[0]['generated_source']
    rows[0]['MaterialContract']['selectors']=['.missing-layer']
    source['motionSpec']['tracks'][0]['from']['opacity']=-1
    calls=[]
    def patch(issues,*args):
        calls.append(issues)
        patches=[]
        for issue in issues:
            if issue['category']=='material_binding':
                value=source['cueHtml']+'<i class="foil-shimmer" aria-hidden="true"></i>'
            else:value=0
            patches.append(dict(candidate_index=issue['candidate_index'],path=issue['path'],value=value))
        return {'patches':patches}
    result=accept_authored_set({'candidates':rows},ThemeLedger(tmp_path,'Balatro'),'fixture','model',technical_repair=patch)
    assert len(calls)==1 and len(result.concepts)==3
    assert result.concepts[0]['authored_theme']['appearance']==before[0]['generated_source']['appearance']
    assert result.concepts[1]['authored_theme']['cueCss']==before[1]['generated_source']['cueCss']


def test_material_repair_rejects_text_layout_and_font_edits():
    from twobyteasr.caption_design.material_contract import validate_material_html_edit
    original='<div class="card"><span class="text">{{text}}</span></div>'
    validate_material_html_edit(original,original+'<i class="foil" aria-hidden="true"></i>',{'foil'})
    validate_material_html_edit(original,original.replace('class="card"','class="card foil"'),{'foil'})
    for changed in (original.replace('text"','text moved"'),original.replace('{{text}}','wrong'),
                    '<div class="foil" aria-hidden="true">'+original+'</div>'):
        with pytest.raises(ValueError):validate_material_html_edit(original,changed,{'foil'})


def test_material_binding_checks_nodes_and_effective_rules_not_substrings():
    from twobyteasr.caption_design.material_contract import validate_material_bindings
    contract={'selectors':['.paper']}
    validate_material_bindings(contract,{'cueHtml':'<div class="paper folded"></div>',
        'cueCss':'.paper.folded{background:#fff}'})
    for html,css in [('<div class="paper-other"></div>','.paper{color:red}'),
                     ('<div class="paper"></div>','/* .paper */ .other{color:red}')]:
        with pytest.raises(ValueError):validate_material_bindings(contract,{'cueHtml':html,'cueCss':css})


def test_selector_conversion_preserves_exact_nodes_and_never_chooses_parent():
    from twobyteasr.caption_design.authored_repair import equivalent_motion_selector,selector_targets
    html='<div class="outer"><i class="shard left"></i><i class="shard right"></i></div>'
    assert equivalent_motion_selector(html,'.shard.left')=='.left'
    assert selector_targets(html,'.outer > .shard.left')==selector_targets(html,'.left')=={1}
    ambiguous='<div class="outer"><i class="shard left"></i><i class="shard"></i><i class="left"></i></div>'
    assert equivalent_motion_selector(ambiguous,'.shard.left') is None


def test_svg_presentation_paint_is_material_without_redundant_css():
    from twobyteasr.caption_design.material_contract import validate_material_bindings
    contract={'selectors':['.soil','.grain']}
    validate_material_bindings(contract,dict(cueHtml='<svg viewBox="0 0 80 80"><polygon class="soil" points="0,0 80,0 80,80" fill="#845632"/><g fill="#654321"><rect class="grain" width="8" height="8"/></g></svg>',cueCss=''))
    validate_material_bindings({'selectors':['.soil']},dict(cueHtml='<svg><g class="soil"><path d="M0 0H80V40Z" fill="#845632"/></g></svg>',cueCss=''))
    for markup in ('<div class="soil" fill="#845632"></div>',
                   '<svg><rect class="soil" fill="none"/></svg>',
                   '<svg fill="#845632"><rect class="soil" fill="none"/></svg>',
                   '<svg><rect class="soil"/></svg>'):
        with pytest.raises(ValueError):validate_material_bindings({'selectors':['.soil']},dict(cueHtml=markup,cueCss=''))


def test_html_collects_all_unsupported_parts_and_accepts_safe_serialization():
    from twobyteasr.caption_design.authored_html import html_problems,html_signature
    from twobyteasr.caption_design.web_theme import sanitize_html
    bad='<div aria-label="caption"><svg><feDropShadow/><feMerge><feMergeNode/></feMerge></svg></div>'
    problems=html_problems(bad)
    assert len(problems)==2  # feMerge/feMergeNode are now supported inline SVG.
    assert any('aria-label' in p for p in problems) and any('fedropshadow' in p for p in problems)
    safe='<svg viewBox="0 0 1 1"><defs><linearGradient id="g"><stop offset="0" /></linearGradient></defs></svg>'
    assert not html_problems(safe)
    assert html_signature(safe)==html_signature(sanitize_html(safe,section='cue'))
