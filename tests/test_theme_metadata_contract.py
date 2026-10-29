import copy
import json
from pathlib import Path

import pytest

from twobyteasr.caption_design.web_theme import WebThemeDocument, export_theme_archive, import_theme_archive
from twobyteasr.caption_design.theme_metadata import recover_generated_names, validate_theme_before_save
from twobyteasr.providers.structured_output import response_object


def theme():
    return dict(name='清晰字幕', palette=dict(primary='#334455', text='#FFFFFF'),
                cueHtml='<div class="caption">{{text}}</div>',
                cueCss='.caption{font-family:var(--wt-font);color:#FFFFFF}', stageHtml='', stageCss='')


def test_valid_name_has_stable_identity_across_rename_and_roundtrip(tmp_path):
    value=theme();value['name']='  清晰字幕  '
    document=WebThemeDocument.from_dict(value).to_dict()
    assert document['name']=='清晰字幕' and document['id']
    renamed=dict(document,name='用户新名称')
    archive=export_theme_archive(renamed,tmp_path)
    for path in (archive/'theme.json',archive/'theme.html'):
        assert import_theme_archive(path)==renamed
    assert WebThemeDocument.from_dict(document).to_dict()['id']==renamed['id']


@pytest.mark.parametrize('alias',['theme_name','display_name','title'])
def test_alias_migrates_only_at_theme_boundary(alias):
    value=theme();value[alias]=value.pop('name')
    result=WebThemeDocument.from_dict(value).to_dict()
    assert result['name']=='清晰字幕' and alias not in result


def test_known_nested_webtheme_envelope_keeps_all_visuals():
    value=theme()
    result=WebThemeDocument.from_dict({'WebTheme':value}).to_dict()
    assert result==WebThemeDocument.from_dict(value).to_dict()
    with pytest.raises(ValueError,match='WebTheme'):
        WebThemeDocument.from_dict({'WebTheme':value,'name':'ambiguous'})


@pytest.mark.parametrize('value',[[],['bad'],{}, {'bad':'name'},None,17,'x'*81,'多行\n说明文本'])
def test_invalid_name_is_rejected_without_coercion(value):
    payload=theme();payload.update(name=value,title='不能掩盖坏类型')
    with pytest.raises(ValueError,match='name'):
        WebThemeDocument.from_dict(payload)


@pytest.mark.parametrize('missing',[True,False])
def test_missing_or_blank_name_one_repair_and_fallback_preserve_visuals(missing):
    value=theme()
    if missing:value.pop('name')
    else:value['name']='   '
    calls=[];events=[]
    def repair(fields):
        calls.append(fields);return {'names':[],'cueCss':'never copy visual repair fields'}
    result=recover_generated_names({'generated_source':value},request_id='fbbc674ba397498e8d0d0c91ba017d81',
        repair=repair,event=lambda event,fields:events.append(event))['generated_source']
    assert len(calls)==1 and result['name'].startswith('AI主题-fbbc674b-')
    assert {k:v for k,v in result.items() if k!='name'}=={k:v for k,v in value.items() if k!='name'}
    assert 'name_fallback_applied' in events


@pytest.mark.parametrize('encoding',['json','fenced','jsonl','jsonl_plain_final'])
def test_all_response_encodings_feed_same_contract(encoding):
    raw=json.dumps(theme(),ensure_ascii=False)
    if encoding=='fenced':raw='```json\n'+raw+'\n```'
    if encoding=='jsonl':raw=json.dumps({'type':'progress','message':'working'})+'\n'+json.dumps({'type':'final','result':theme()})
    if encoding=='jsonl_plain_final':raw=json.dumps({'type':'progress','message':'working'})+'\n'+raw
    assert WebThemeDocument.from_dict(response_object(raw)).to_dict()['name']=='清晰字幕'


def test_three_missing_names_get_only_one_batch_repair():
    values={f'candidates[{i}].generated_source':dict(theme(),name='') for i in range(3)}
    calls=[]
    def repair(fields):
        calls.append(fields)
        return {'names':[{'path':r['path'],'name':f'修复-{i}'} for i,r in enumerate(fields)]}
    result=recover_generated_names(values,request_id='request-1',repair=repair)
    assert len(calls)==1 and [v['name'] for v in result.values()]==['修复-0','修复-1','修复-2']


def test_duplicate_repair_result_falls_back_atomically():
    value=dict(theme(),name='')
    result=recover_generated_names({'theme':value},request_id='r',repair=lambda _:{'names':[
        {'path':'theme','name':'first'},{'path':'theme','name':'late duplicate'}]})
    assert result['theme']['name'].startswith('AI主题-')


def test_cancelled_late_repair_cannot_mutate_next_request():
    value=dict(theme(),name='');cancelled=False
    def repair(_):
        nonlocal cancelled
        cancelled=True
        return {'names':[{'path':'theme','name':'late'}]}
    with pytest.raises(Exception,match='取消'):
        recover_generated_names({'theme':value},request_id='old',repair=repair,cancel_check=lambda:cancelled)
    new=recover_generated_names({'theme':theme()},request_id='new')['theme']
    assert new['name']=='清晰字幕' and value['name']==''


def test_other_invalid_fields_do_not_trigger_metadata_repair():
    value=dict(theme(),name='',cueHtml='<div>no placeholder</div>');calls=[]
    with pytest.raises(ValueError,match='cue_html'):
        recover_generated_names({'theme':value},request_id='r',repair=lambda fields:calls.append(fields))
    assert not calls


def test_lost_name_before_save_leaves_no_partial_archive(tmp_path):
    valid=WebThemeDocument.from_dict(theme()).to_dict();valid.pop('name')
    with pytest.raises(ValueError,match='name'):
        export_theme_archive(valid,tmp_path)
    assert list(tmp_path.iterdir())==[]


def test_fallback_can_be_renamed_saved_and_reopened(tmp_path):
    valid=recover_generated_names({'theme':dict(theme(),name='')},request_id='sameprefix-1')['theme']
    document=WebThemeDocument.from_dict(valid).to_dict();identity=document['id']
    document['name']='人工重命名'
    archive=export_theme_archive(document,tmp_path)
    result=import_theme_archive(archive)
    assert result['name']=='人工重命名' and result['id']==identity


def test_library_validates_full_theme_before_atomic_write(tmp_path):
    from twobyteasr.caption_style.style_presets import StylePresetStore
    from twobyteasr.projects.studio_project import SubtitleStyle
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    store=StylePresetStore(tmp_path)
    recipe=StyleRecipe(name='正常',engine='remotion',web_theme=theme()).to_dict()
    style=SubtitleStyle(id='ai-contract',name='正常')
    store.upsert(style,recipe,source='ai');before=store.path.read_bytes()
    corrupted=copy.deepcopy(recipe);corrupted['webTheme']['name']=None
    with pytest.raises(ValueError,match='name'):
        store.upsert(style,corrupted,source='ai')
    assert store.path.read_bytes()==before
    assert [p for p in tmp_path.rglob('*') if p.is_file()]==[store.path]


def test_library_rename_updates_theme_name_and_keeps_id(tmp_path):
    from twobyteasr.caption_style.style_presets import StylePresetStore
    from twobyteasr.projects.studio_project import SubtitleStyle
    from twobyteasr.caption_style.style_recipe import StyleRecipe
    store=StylePresetStore(tmp_path)
    theme_value=WebThemeDocument.from_dict(theme()).to_dict()
    store.upsert(SubtitleStyle(id='ai-contract',name=theme_value['name']),
        StyleRecipe(name=theme_value['name'],engine='remotion',web_theme=theme_value).to_dict(),source='ai')
    store.rename('ai-contract','用户命名')
    saved=store.load_recipes()['ai-contract']
    assert saved['name']==saved['webTheme']['name']==store.load_user()['ai-contract'].name=='用户命名'
    assert saved['webTheme']['id']==theme_value['id']


def test_provider_schema_requires_nested_name_and_boundary_unwraps(tmp_path):
    from twobyteasr.caption_design.caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA,ThemeLedger,accept_authored_set
    from scripts.author_balatro_candidates import candidates
    assert 'name' in AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']['properties']['generated_source']['required']
    item=AUTHORED_OUTPUT_SCHEMA['properties']['candidates']['items']
    assert set(item['required'])=={'id','name','composition_family','art_direction_contract','design_spec',
        'ColorRole','MaterialContract','MotionContract','generated_source'}
    assert set(item['required'])<=set(item['properties'])
    rows=candidates();before=copy.deepcopy(rows)
    for row in rows:row['generated_source']={'WebTheme':row['generated_source']}
    result=accept_authored_set({'candidates':rows},ThemeLedger(tmp_path,'Balatro'),'test','model')
    for original,concept in zip(before,result.concepts):
        assert concept['authored_theme']['name']==original['generated_source']['name']
        assert concept['authored_theme']['cueCss']==original['generated_source']['cueCss']


def test_changed_staging_file_cannot_be_published(tmp_path):
    def corrupt(staging):
        value=json.loads((staging/'theme.json').read_text('utf8'));value.pop('name')
        (staging/'theme.json').write_text(json.dumps(value),encoding='utf8')
    with pytest.raises(ValueError,match='name'):
        export_theme_archive(theme(),tmp_path,validate_before_publish=corrupt)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('phase',['READY','APPLIED','CANCELLED'])
def test_duplicate_or_late_repair_ready_does_not_replace_ui(phase):
    import threading
    from types import SimpleNamespace
    from twobyteasr.caption_design.studio_theme_draft import StudioThemeDraftController
    project=object();calls=[]
    controller=SimpleNamespace(phase=phase,operation='repair-result',cancel_event=threading.Event(),
        page=SimpleNamespace(project=project),project=project,current=SimpleNamespace(content_hash='same'),
        _set_phase=lambda *args:calls.append(args))
    StudioThemeDraftController._ready(controller,'repair-result',{'content_hash':'same'})
    assert not calls


def test_normal_provider_route_repairs_names_once_and_keeps_authored_source(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.caption_design.caption_creative_pipeline import request_creative_options
    from tests.test_authored_generation import fixture
    rows,directions=fixture()
    # Name repair tests keep the first caption frame readable, an independent gate.
    for row in rows:
        for track in row['generated_source']['motionSpec']['tracks']:
            if track['phase']=='build' and 'opacity' in track['from']:track['from']['opacity']=1
    visuals=[row['generated_source']['cueCss'] for row in rows]
    for row in rows:row['generated_source'].pop('name')
    calls=[]
    class Client:
        def capabilities(self):return SimpleNamespace(vision=False)
        def complete(self,messages,**kwargs):
            calls.append((messages,kwargs))
            if len(calls)==1:return json.dumps(directions)
            return json.dumps(rows[len(calls)-2]['generated_source'])
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:SimpleNamespace(provider='test',model='fake'))
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a,**k:Client())
    monkeypatch.setattr('twobyteasr.caption_design.authored_preview.render_candidate_preview',lambda *a,**kw:dict(
        motion={'status':'motion_ready'},picture='fixture.png',full_frame='fixture.png',elapsed_seconds=0))
    result=request_creative_options(SimpleNamespace(cues=[SimpleNamespace(id='x',text='合成字幕')]),
        'x','Balatro',{},ledger_root=tmp_path,request_id='fbbc674b-synthetic')
    assert len(calls)==4 and all('json_schema' in kwargs for _,kwargs in calls)
    assert [c['authored_theme']['name'] for c in result.concepts]==[r['name'] for r in directions['candidates']]
    assert [c['authored_theme']['cueCss'] for c in result.concepts]==visuals
    assert all(kwargs['operation_kind']=='generate' for _,kwargs in calls)
    for ident in ('A','B','C'):
        ledger=json.loads((tmp_path/f'candidates/{ident}/v1/ledger.json').read_text('utf8'))
        assert ledger['normalization']==[dict(path='generated_source.name',action='inherit_validated_direction_name',value=next(r['name'] for r in rows if r['id']==ident))]


def test_motion_numeric_failure_reports_exact_field_path():
    from twobyteasr.caption_design.theme_motion import validate_motion_spec
    motion=dict(version=1,runtime='gsap',tracks=[dict(selector='.card',phase='build',start=0,end=1,
        **{'from':{'rotationY':0},'to':{'rotationY':180}})])
    with pytest.raises(ValueError,match=r'motionSpec\.tracks\[0\]\.to\.rotationY'):
        validate_motion_spec(motion)


def test_provider_schema_rejects_blank_names():
    import jsonschema
    from twobyteasr.caption_design.theme_metadata import NAME_SCHEMA
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate('   ',NAME_SCHEMA)


def test_duplicate_final_packets_cannot_override_repaired_metadata():
    raw='\n'.join(json.dumps(row) for row in [
        {'type':'progress','message':'working'},
        {'type':'final','result':{'names':[{'path':'theme','name':'first'}]}},
        {'type':'final','result':{'names':[{'path':'theme','name':'late'}]}}])
    value=recover_generated_names({'theme':dict(theme(),name='')},request_id='duplicate-packet',repair=lambda _:raw)['theme']
    assert value['name'].startswith('AI主题-duplicat-')


def test_missing_outer_candidate_name_reuses_valid_inner_metadata(tmp_path):
    from scripts.author_balatro_candidates import candidates
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,accept_authored_set
    rows=candidates()
    for row in rows:row.pop('name')
    result=accept_authored_set({'candidates':rows},ThemeLedger(tmp_path,'Balatro'),'test','fake')
    assert all(c['name']==c['authored_theme']['name'] for c in result.concepts)


def test_deepseek_chat_uses_supported_json_mode_not_strict_schema():
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
    from twobyteasr.caption_design.caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA
    calls=[]
    provider=OpenAICompatibleProvider(dict(provider='deepseek',model='synthetic-model',api_key='synthetic',
        url='https://unused.invalid/chat/completions'),sender=lambda messages,**kwargs:calls.append(kwargs) or '{}')
    assert provider.complete([{'role':'user','content':'synthetic'}],json_schema=AUTHORED_OUTPUT_SCHEMA)=='{}'
    assert calls[0]['response_format']=={'type':'json_object'} and 'json_schema' not in calls[0]


def test_responses_transport_receives_full_schema(monkeypatch):
    from twobyteasr.providers import ai_providers
    from twobyteasr.caption_design.caption_creative_pipeline import AUTHORED_OUTPUT_SCHEMA
    calls=[]
    monkeypatch.setattr(ai_providers,'post_responses',lambda messages,**kwargs:calls.append(kwargs) or '{}')
    provider=ai_providers.OpenAICompatibleProvider(dict(provider='custom',model='synthetic-model',api_key='synthetic',
        protocol='responses',url='https://unused.invalid/responses'))
    assert provider.complete([{'role':'user','content':'synthetic'}],json_schema=AUTHORED_OUTPUT_SCHEMA)=='{}'
    assert calls[0]['json_schema']==AUTHORED_OUTPUT_SCHEMA


def test_raw_provider_provenance_hashes_actual_bytes_on_windows(tmp_path):
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,digest
    raw='```json\n{"name":"合成名称"}\n```'
    ledger=ThemeLedger(tmp_path,'synthetic prompt');ledger.raw_response(raw,'fixture','fixture')
    actual=(tmp_path/'provider-original.txt').read_bytes()
    assert actual==raw.encode('utf8') and ledger.value['raw_response']['sha256']==digest(actual)
