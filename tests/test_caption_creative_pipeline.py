import copy,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from twobyteasr.caption_design.caption_creative_pipeline import (ThemeLedger,digest,canonical,accept_authored_set,
    reviewed_concepts,request_creative_options,validate_material_contract,resume_authored)
from scripts.author_balatro_candidates import candidates

def authored(tmp_path):
    ledger=ThemeLedger(tmp_path,'Balatro 三个不同构图')
    result=accept_authored_set({'candidates':candidates()},ledger,'test','test')
    return ledger,result

def review(ledger):
    paths=[]
    for index in range(5):
        path=ledger.root/f'frame-{index}.png';path.write_bytes(b'actual-test-fixture'+bytes([index]));paths.append(path)
    for ident in 'ABC':ledger.record_preview(ident,paths,dict(pixels_inspected=True,accepted=True,
        notes='Fixture review binds five actual files',reviewer='test fixture'))
    return paths

def test_authored_dom_survives_and_three_different_structures(tmp_path):
    ledger,result=authored(tmp_path)
    assert len(result.concepts)==3
    assert [c['composition'] for c in result.concepts]==[c['composition_family'] for c in candidates()]
    assert len({c['generated_source_hash'] for c in ledger.value['candidates']})==3
    assert all(s['raw_prompt_hash']==digest('Balatro 三个不同构图') and s['semantic_review']=='pending' for s in ledger.value['stages'])
    assert 'pressed_ticket' not in canonical(ledger.value['candidates'])

def test_cache_key_covers_prompt_reference_bytes_and_version(tmp_path):
    ref=tmp_path/'reference.html';ref.write_text('one')
    one=ThemeLedger(tmp_path/'one','Balatro',references=[(ref,'positive')]).value['cache_key']
    assert ThemeLedger(tmp_path/'two','Crystal',references=[(ref,'positive')]).value['cache_key']!=one
    ref.write_text('two')
    assert ThemeLedger(tmp_path/'three','Balatro',references=[(ref,'positive')]).value['cache_key']!=one

def test_actual_missing_material_layer_stops_candidate(tmp_path):
    rows=candidates()
    rows[0]['generated_source']['cueHtml']=rows[0]['generated_source']['cueHtml'].replace('foil-shimmer','absent-foil')
    with pytest.raises(ValueError):accept_authored_set({'candidates':rows},ThemeLedger(tmp_path,'Balatro'),'test','test')

def test_score_cannot_bypass_unseen_or_changed_pixels(tmp_path):
    ledger,result=authored(tmp_path)
    with pytest.raises(ValueError):reviewed_concepts(result.concepts)
    paths=review(ledger);assert reviewed_concepts(result.concepts,raw_user_prompt='Balatro 三个不同构图')
    paths[0].write_bytes(b'changed')
    with pytest.raises(ValueError,match='预览文件'):reviewed_concepts(result.concepts)

def test_new_prompt_or_source_cannot_resume_old_brief(tmp_path):
    ledger,result=authored(tmp_path);review(ledger)
    design=dict(brief=result.brief,concepts=result.concepts,selected_concept_id='A')
    with pytest.raises(ValueError,match='原始要求'):resume_authored(design,'new',raw_user_prompt='another theme')
    result.concepts[0]['authored_theme']['cueCss']+=' .new{opacity:1}'
    with pytest.raises(ValueError,match='源码'):reviewed_concepts(result.concepts)

def test_failed_provider_raw_saved_and_never_local_fallback(tmp_path,monkeypatch):
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='fake'))
    calls=[]
    class Client:
        def capabilities(self):return SimpleNamespace(vision=False)
        def complete(self,messages,**kwargs):calls.append((messages,kwargs));return '{invalid json original'
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:Client())
    with pytest.raises(Exception):request_creative_options(SimpleNamespace(cues=[SimpleNamespace(id='x',text='字幕')]),'x','scope appended',{},raw_user_prompt='  Balatro\n原始要求 ',ledger_root=tmp_path)
    assert (tmp_path/'directions/provider-original.txt').read_text('utf8')=='{invalid json original'
    saved=json.loads((tmp_path/'ledger.json').read_text('utf8'))
    assert saved['raw_user_prompt']=='  Balatro\n原始要求 '
    assert saved['status']=='failed' and len(calls)==1 and calls[0][1]['timeout']<=90
    context=saved['creative_context']
    assert 'Cubic 11' in context['bundled_fonts']
    assert context['material_direction']['motion'] and not context['current_feedback']
    assert saved['historical_feedback_not_applied']['revision_feedback']
    assert '先无字HTML装置' not in calls[0][0][0]['content']
    sent=calls[0][0][0]['content']
    schema=json.loads((tmp_path/'directions/request-schema.json').read_text('utf8'))
    assert set(schema['properties']['candidates']['items']['required'])=={'name','design'}
    assert 'backgroundPositionY' not in sent  # Full runtime contract belongs to implementation.

def test_material_label_is_not_visual_proof_or_a_fixed_class_template():
    validate_material_contract(dict(material='crystal',selectors=[]),dict(cueHtml='<div class="blue"></div>',cueCss='.blue{background:#2388cc}'))
    # Fidelity is pending actual pixels; technical validation does not invent
    # five mandatory class names as a proxy for the appearance of crystal.

def test_current_negative_samples_are_not_positive_preferences():
    from twobyteasr.caption_design.caption_design_trials import CaptionPreferences
    prefs=CaptionPreferences(Path(__file__).resolve().parents[1]/'docs/design/caption-preferences.json')
    assert all(r['user_rating']==3 and r['accepted'] is False for r in prefs.read()['trial_runs'])
    assert prefs.positive_references()==[]

def test_every_fresh_request_uses_authored_route(monkeypatch):
    from twobyteasr.caption_design import studio_ai, caption_creative_pipeline
    sentinel=object();calls=[]
    monkeypatch.setattr(caption_creative_pipeline,'request_creative_options',lambda *a,**k:calls.append(k) or sentinel)
    assert studio_ai.request_web_theme_design(None,'x','Balatro',{'models':{}},raw_user_prompt=' exact raw ')==sentinel
    assert calls[0]['raw_user_prompt']==' exact raw '


def test_authored_route_honors_configured_cli_deadline_and_reports_stream(monkeypatch,tmp_path):
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='fake'))
    calls=[];events=[]
    class Client:
        def capabilities(self):return SimpleNamespace(vision=False)
        def complete(self,messages,**kwargs):
            calls.append(kwargs)
            kwargs['on_stream_event']('thinking','not copied into the phase record')
            kwargs['on_stream_event']('delta','{invalid')
            return '{invalid'
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:Client())
    with pytest.raises(Exception):
        request_creative_options(SimpleNamespace(cues=[SimpleNamespace(id='x',text='字幕')]),'x','Balatro',
            {'models':{'ai_design_cli_timeout_seconds':300}},ledger_root=tmp_path,stage_event_callback=events.append)
    assert 299<=calls[0]['timeout']<=300
    assert 299<=events[0]['timeout_seconds']<=300 and events[-1]['output_chars']==8
    assert events[-1]['status']=='failed'
    assert 'not copied' not in json.dumps(events)
    assert (tmp_path/'provider-invocation.json').is_file()


def test_visual_advice_is_retained_without_becoming_a_technical_block(tmp_path):
    ledger,result=authored(tmp_path);paths=review(ledger)
    ledger.record_preview('B',paths,dict(accepted=False,blocking=True,pixels_inspected=True,reviewer='test fixture',
        notes='主题层次建议，待用户审美签收',scores=dict(theme=3,color=5,material=4,composition=2,typography=2)))
    assert reviewed_concepts(result.concepts)
    assert [c['id'] for c in ledger.value['candidates']]==list('ABC')
    design=dict(brief=result.brief,concepts=result.concepts,selected_concept_id='B')
    assert resume_authored(design,'')
    for ident in 'AC':
        ledger.record_preview(ident,paths,dict(accepted=False,blocking=True,pixels_inspected=True,notes='不可读',reviewer='test fixture',
            scores=dict(theme=3,color=5,material=4,composition=2,typography=2)))
    assert reviewed_concepts(result.concepts)


def test_partial_generation_keeps_good_candidates_and_failed_identity(tmp_path):
    rows=candidates();rows[1]['generated_source']['cueHtml']='<script>bad</script>'+rows[1]['generated_source']['cueHtml']
    def fail(*args):raise ValueError('provider could not repair')
    ledger=ThemeLedger(tmp_path,'Balatro')
    result=accept_authored_set({'candidates':rows},ledger,'test','test',technical_repair=fail,
        candidate_regenerate=fail,allow_partial=True)
    assert [c['id'] for c in result.concepts]==['A','B','C']
    assert result.concepts[1]['technical_status']=='failed'
    assert [c['id'] for c in ledger.value['candidates']]==['A','C']
    assert result.concepts[0]['authored_theme']['cueCss']==rows[0]['generated_source']['cueCss']


def test_explicit_user_choice_needs_no_fabricated_external_score(tmp_path):
    ledger,result=authored(tmp_path)
    frames=[]
    for i in range(5):
        p=tmp_path/f'local-{i}.png';p.write_bytes(bytes([i]));frames.append(p)
    ledger.record_preview('A',frames,dict(accepted=True,user_approval=True,pixels_inspected=True,
        reviewer='local-user',notes='User selected actual preview'))
    assert reviewed_concepts(result.concepts)
    row=ledger.value['candidates'][0]
    assert row['visual_review']['user_approval'] and 'scores' not in row['visual_review']
    design=dict(brief=result.brief,concepts=result.concepts,selected_concept_id='B')
    with pytest.raises(ValueError,match='所选候选尚无真实预览'):resume_authored(design,'')


@pytest.mark.parametrize('has_unfinished_sibling',[False,True])
def test_one_reviewed_candidate_can_be_adopted_independently(tmp_path,has_unfinished_sibling):
    ledger,result=authored(tmp_path);paths=review(ledger)
    chosen=result.concepts[0]
    concepts=[chosen]
    if has_unfinished_sibling:
        concepts.append(dict(id='unfinished',technical_status='pending',ledger_path='not-created'))
    design=dict(brief=result.brief,concepts=concepts,selected_concept_id=chosen['id'])
    assert resume_authored(design,'').theme==chosen['authored_theme']
    paths[0].write_bytes(b'changed selected preview')
    with pytest.raises(ValueError,match='预览文件'):resume_authored(design,'')


def test_qualitative_art_concerns_preserve_voluntary_adoption_without_scores(tmp_path):
    ledger,result=authored(tmp_path);frames=review(ledger)
    for ident in 'ABC':
        ledger.record_preview(ident,frames,dict(accepted=False,blocking=False,pixels_inspected=True,
            reviewer='actual reviewer',notes='闭合底板过大，装饰脱离正文；美术未达目标，技术预览可用'))
    assert reviewed_concepts(result.concepts)
    assert not any(r['visual_review']['accepted'] for r in ledger.value['candidates'])
    design=dict(brief=result.brief,concepts=result.concepts,selected_concept_id='B')
    assert resume_authored(design,'')
    with pytest.raises(ValueError,match='实际看图'):
        ledger.record_preview('B',frames,dict(accepted=True,pixels_inspected=False,
            reviewer='model',notes='score alone',scores=dict(theme=10)))


def test_saved_response_revalidates_retained_source_without_new_generation(tmp_path,monkeypatch):
    from twobyteasr.caption_design import caption_creative_pipeline as pipeline
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    prior,result=authored(tmp_path/'prior');prior.raw_response(json.dumps({'candidates':candidates()}),'test','test')
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='test'))
    class Client:
        def complete(self,*a,**k):raise AssertionError('Retained valid sources must not request another generation')
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:Client())
    # The first-frame contract is deliberately disabled only on this test's
    # authored fixture, whose animation was designed before that requirement.
    original=pipeline.accept_authored_set
    def accept(data,ledger,*a,**k):
        ledger.value['require_readable_first_frame']=False
        return original(data,ledger,*a,**k)
    monkeypatch.setattr(pipeline,'accept_authored_set',accept)
    project=SimpleNamespace(cues=[SimpleNamespace(id='x')])
    resumed=pipeline.resume_saved_response(prior.root/'ledger.json',project,'x',{},ledger_root=tmp_path/'new',request_id='retry')
    assert [c['authored_theme'] for c in resumed.concepts]==[c['authored_theme'] for c in result.concepts]
    saved=ThemeLedger.open(tmp_path/'new'/'ledger.json').value
    assert saved['explicit_resume_count']==1 and saved['resumed_from']['sha256']==prior.value['raw_response']['sha256']
    (prior.root/'provider-original.txt').write_text('{}','utf8')
    with pytest.raises(ValueError,match='原始响应已改变'):
        pipeline.resume_saved_response(prior.root/'ledger.json',project,'x',{},ledger_root=tmp_path/'bad',request_id='tampered')


@pytest.mark.parametrize('elapsed',[292,301])
def test_direction_failure_and_overall_budget_never_start_source_requests(monkeypatch,tmp_path,elapsed):
    from twobyteasr.caption_design import caption_creative_pipeline as pipeline
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='fake'))
    clock=[1000.];calls=[]
    monkeypatch.setattr(pipeline.time,'monotonic',lambda:clock[0])
    class Client:
        def capabilities(self):return SimpleNamespace(vision=False)
        def complete(self,messages,**kwargs):
            calls.append(kwargs);clock[0]+=elapsed;return '{}'
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:Client())
    with pytest.raises(Exception) as error:
        pipeline.request_creative_options(SimpleNamespace(cues=[SimpleNamespace(id='x',text='字幕')]),'x','三稿',
            {'models':{'ai_design_cli_timeout_seconds':300}},ledger_root=tmp_path)
    if elapsed>300:assert error.value.category=='provider_total_timeout'
    assert len(calls)==1
    assert (tmp_path/'directions/provider-original.txt').read_text('utf8')=='{}'
