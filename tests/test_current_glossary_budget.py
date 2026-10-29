import base64
import hashlib
import json
import time
from types import SimpleNamespace

import pytest


def legacy():
    return SimpleNamespace(RUNTIME_GAME_NAME='', load_active_game_lexicon_names=lambda **k:([], []),
        builtin_reference_terms_for_game=lambda *a,**k:[], learned_canonical_terms=lambda *a:[],
        user_confirmed_mappings_for_game=lambda *a:[], hidden_reference_terms_for_game=lambda *a:set(),
        load_learned_term_payload=lambda:{'games':{}})


def test_fresh_minecraft_403_has_failure_outcome_and_preserves_cursor(monkeypatch):
    from twobyteasr.glossary import glossary_build as gb, glossary_sources as gs, minecraft_catalogs as mc
    from twobyteasr.glossary.glossary_outcome import empty_result_message
    monkeypatch.setattr(gb, 'detect_search_capability', lambda s:dict(provider_search=False, model='test', service='test'))
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a:None)
    monkeypatch.setattr(mc, 'fetch_official_terms', lambda *a:(_ for _ in ()).throw(ValueError('http_403')))
    calls=[]
    def blocked(site, params, board, *a, **k):
        calls.append(params.copy());board.for_host('zh.minecraft.wiki').record_failure('blocked');return None
    monkeypatch.setattr(gs, '_api_get', blocked)
    checkpoints=[];events=[]
    result=gb.run_full_library_update(legacy(), '我的世界', {}, checkpoint_writer=checkpoints.append,on_event=events.append)
    assert len(calls)==1 and result['candidate_count']==0
    assert result['outcome']['status']=='blocked' and result['outcome']['verified_sources']==0
    assert '已覆盖' not in empty_result_message(result)
    assert not result['checkpoint']['done_urls']
    assert any(c.get('current') for c in result['checkpoint']['category_cursors'].values())
    assert any(e['kind']=='outcome' for e in events)


def test_source_verified_empty_is_distinct_from_failure_or_new_candidates():
    from twobyteasr.glossary.glossary_outcome import collection_outcome
    valid=dict(url='https://example.com',read=True,enumeration_complete=True,catalog_member_count=0)
    assert collection_outcome([], [valid])['status']=='no_changes'
    assert collection_outcome([], [])['status']=='no_verified_content'
    assert collection_outcome([object()], [valid,dict(url='https://bad.com',read=False,error='blocked')])['status']=='partial'


def test_verified_names_do_not_double_count_resource_keys_or_sources():
    from twobyteasr.glossary.glossary_outcome import collection_outcome
    names=[dict(term='石头',verification='catalog_verified'),
           dict(term='石头',verification='page_verified'),
           dict(term='未核对',verification='sourced')]
    sources=[dict(url='official',read=True,catalog_member_count=2),
             dict(url='wiki',read=True,catalog_member_count=1)]
    result=collection_outcome(names,sources)
    assert result['verified_names']==1
    assert result['verified_source_entries']==3
    assert collection_outcome(names,[dict(url='failed',read=False)])['verified_names']==0


def test_checkpoint_fresh_scope_expiry_and_game_boundary():
    from twobyteasr.glossary.glossary_outcome import resumable_checkpoint
    old=dict(game='我的世界',done_urls=['fresh','stale'],category_cursors={'fresh':{},'stale':{}},
        source_results=[dict(url='fresh',read=True,fetched_at=1000),dict(url='stale',read=True,fetched_at=1,evidence_url='asset')],
        candidates=[dict(verification='catalog_verified',sources=[dict(url='asset')])])
    result,receipt=resumable_checkpoint(old,'我的世界',now=1010,ttl_seconds=100)
    assert result['done_urls']==['fresh'] and 'stale' not in result['category_cursors']
    assert result['candidates'][0]['verification']=='sourced'
    assert old['candidates'][0]['verification']=='catalog_verified'
    assert receipt['expired_sources']==['stale']
    assert resumable_checkpoint(old,'另一个游戏')[0]=={}


def test_official_translation_filter_not_navigation_or_description():
    from twobyteasr.glossary.minecraft_catalogs import translation_terms
    payload={'entity.minecraft.creeper':'苦力怕','block.minecraft.stone':'石头',
        'item.minecraft.apple':'苹果','item.minecraft.apple.description':'描述','menu.start':'开始',
        'enchantment.minecraft.sharpness':'锋利','enchantment.minecraft.sharpness.desc':'%s 伤害',
        'effect.minecraft.speed':'速度','biome.minecraft.desert':'沙漠'}
    terms=list(translation_terms(payload))
    assert len(terms)==6 and terms[0]['category_key']=='entity'
    assert all('描述' not in x['term'] and x['term']!='开始' for x in terms)
    payload.update({'item.minecraft.creeper_spawn_egg':'苦力怕刷怪蛋','entity.minecraft.arrow':'箭'})
    rows={r['registry_key']:r for r in translation_terms(payload)}
    assert rows['entity.minecraft.creeper']['category_key']=='mob'
    assert rows['entity.minecraft.arrow']['category_key']=='entity'


def test_failed_outcome_is_not_green_task_and_still_reviewable():
    from twobyteasr.glossary.glossary_task_manager import GlossaryUpdateManager,GlossaryTaskState
    manager=GlossaryUpdateManager(object())
    task=GlossaryTaskState('a','game','full','service','model',time.time(),status='running')
    manager._tasks['a']=task
    result=dict(candidate_count=0,outcome=dict(status='blocked',message='HTTP403'),diffs=[])
    manager._on_finished_ok('a','game',result)
    assert task.status=='failed' and task.result is result and task.error_code=='blocked'


def test_native_schema_projection_keeps_images_user_constraints_and_is_idempotent():
    from twobyteasr.providers.provider_input_budget import project_transport_messages,compact
    schema={'type':'object','required':['name'],'properties':{'name':{'type':'string'}}}
    messages=[{'role':'user','content':[{'type':'text','text':'保留完整框体\n'+compact(schema)},
        {'type':'image_url','image_url':{'url':'data:image/png;base64,unchanged'}}]}]
    projected=project_transport_messages(messages,schema,'grok_cli')
    assert compact(schema) not in projected[0]['content'][0]['text']
    assert '保留完整框体' in projected[0]['content'][0]['text']
    assert projected[0]['content'][1]==messages[0]['content'][1]
    assert project_transport_messages(projected,schema,'grok_cli')==projected
    assert project_transport_messages(messages,schema,'openai_compatible')==messages


def test_restore_reference_hash_preserved_missing_or_changed_rejected(tmp_path):
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger,saved_reference_images
    p=tmp_path/'ref.png';p.write_bytes(b'original-pixels')
    ledger=ThemeLedger(tmp_path/'draft','测试',references=[(p,'current-media')])
    ledger.value['provider_inputs']=[dict(pixels_attached=True)]
    parts=saved_reference_images(ledger)
    assert base64.b64decode(parts[0]['image_url']['url'].split(',',1)[1])==p.read_bytes()
    p.write_bytes(b'changed')
    with pytest.raises(ValueError,match='参考图'):saved_reference_images(ledger)
    p.unlink()
    with pytest.raises(ValueError,match='参考图'):saved_reference_images(ledger)


def test_fixed_implementation_over_budget_stops_before_planning(tmp_path):
    from twobyteasr.caption_design.authored_generation import generate_staged
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    ledger=ThemeLedger(tmp_path,'长'*40000)
    client=SimpleNamespace(complete=lambda *a,**k:pytest.fail('must not send planning'))
    with pytest.raises(Exception, match='固定实现契约'):
        generate_staged(ledger,client,SimpleNamespace(provider='grok_oauth',model='test'),'',{},request_id='test')
    assert ledger.value['implementation_preflight']['passed'] is False


def test_broker_resolves_cli_transport_before_preflight(monkeypatch):
    from twobyteasr.providers.provider_service import ProviderService
    from twobyteasr.providers.llm_config import activate_ai_service,endpoint_from_settings
    from twobyteasr.providers.provider_input_budget import compact
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    import copy
    settings=copy.deepcopy(DEFAULT_SETTINGS);activate_ai_service(settings,'grok_account')
    assert 'transport' not in endpoint_from_settings(settings,'polish')
    broker=ProviderService()
    schema={'type':'object','description':'x'*30000}
    def reached(*a):raise RuntimeError('budget accepted before runtime')
    monkeypatch.setattr(broker,'_runtime_for',reached)
    with pytest.raises(RuntimeError,match='budget accepted'):
        broker.submit(settings,'polish',[{'role':'user','content':'保留设计要求 '+compact(schema)}],
            json_schema=schema,max_tokens=10000,operation_kind='generate')


def test_staged_grok_fixed_contract_is_sendable_with_reference(tmp_path):
    import copy,io
    from PIL import Image
    from twobyteasr.caption_design.authored_generation import generate_staged
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    from twobyteasr.providers.llm_config import activate_ai_service
    from twobyteasr.storage.settings import DEFAULT_SETTINGS
    settings=copy.deepcopy(DEFAULT_SETTINGS);activate_ai_service(settings,'grok_account')
    image=io.BytesIO();Image.new('RGB',(960,540)).save(image,format='PNG')
    parts=[dict(type='image_url',image_url=dict(url='data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()))]
    ledger=ThemeLedger(tmp_path,'白熊主题字幕')
    def planning(*a,**kw):raise RuntimeError('planning reached')
    client=SimpleNamespace(complete=planning)
    with pytest.raises(RuntimeError,match='planning reached'):
        generate_staged(ledger,client,SimpleNamespace(provider='grok_oauth',model='grok-4.7'),'',settings,request_id='test',image_parts=parts)
    assert ledger.value['implementation_preflight']['passed']
    assert ledger.value['implementation_preflight']['budget']['image_count']==1
