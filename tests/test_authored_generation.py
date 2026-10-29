import copy
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from twobyteasr.caption_design.authored_generation import generate_staged
from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger

def fixture():
    rows=json.loads((Path(__file__).parent/'fixtures/balatro-deepseek-4f5564.json').read_text('utf8'))['candidates']
    directions=copy.deepcopy(rows)
    for r in directions:
        r.pop('generated_source')
        r['design_spec'].update(theme_identifiers='纸牌印刷与倍率',shape='作者独立形体',typography='实际可用Cubic 11',
            text_region='主体内部稳定阅读区域',composition='文字与实体共同构图')
    return rows,{'candidates':directions}

class Client:
    def __init__(self,values):self.values=list(values);self.calls=[]
    def complete(self,messages,**kwargs):
        self.calls.append((messages,kwargs))
        if kwargs['operation_kind']!='generate':raise ValueError('bounded repair failure')
        value=self.values.pop(0)
        if isinstance(value,Exception):raise value
        if kwargs.get('response_kind')=='source_artifact':
            import re
            from twobyteasr.caption_design.source_artifact import from_theme,token
            marker=re.findall(r'2BYTE-ARTWORK/1 ([a-f0-9]{24})',messages[0]['content'])[-1]
            raw=from_theme(value,'fixture').replace(token('fixture'),marker)
        else:raw=json.dumps(value,ensure_ascii=False)
        kwargs['on_stream_event']('delta',raw);return raw
    def invocation_trace(self):return {'provider_id':'deepseek','model':'deepseek-v4-pro'}

def run(tmp_path,client,**kw):
    ledger=ThemeLedger(tmp_path,'balatro小丑牌风格')
    result=generate_staged(ledger,client,SimpleNamespace(provider='deepseek',model='deepseek-v4-pro'),
        'isolated test',{'models':{'ai_design_wait_mode':'long30','ai_design_candidate_count':3,'ai_design_concurrency':1,'ai_design_max_repair_calls':2}},request_id='test',**kw)
    return ledger,result

def test_design_first_originals_separate_and_independent_candidates(tmp_path):
    rows,directions=fixture();events=[]
    client=Client([directions,*[r['generated_source'] for r in rows]])
    ledger,result=run(tmp_path,client,stage_event_callback=events.append)
    assert len(client.calls)==4
    assert [r['id'] for r in result.concepts]==['A','B','C']
    assert all(c.get('technical_status')!='failed' for c in result.concepts)
    assert ledger.value['directions']==directions
    assert ledger.value['raw_response']['kind']=='assembled_stages'
    assert (tmp_path/'candidates/A/v1/provider-original.txt').read_text('utf8').startswith('2BYTE-ARTWORK/1 ')
    assert client.calls[1][1]['json_schema'] is None
    assert client.calls[1][1]['response_kind']=='source_artifact'
    assert [e['candidate_id'] for e in events if e['name']=='candidate_complete']==['A','B','C']
    assert ledger.value['remote_request_resumable'] is False

def test_one_bad_source_does_not_erase_or_regenerate_good_peers(tmp_path):
    rows,directions=fixture()
    client=Client([directions,ValueError('truncated JSON'),ValueError('completion still truncated'),rows[1]['generated_source'],rows[2]['generated_source']])
    ledger,result=run(tmp_path,client)
    assert len(client.calls)==5
    assert client.calls[2][1]['input_scope']['kind']=='implementation_completion'
    assert result.concepts[0]['technical_status']=='failed'
    assert [c.get('technical_status','passed') for c in result.concepts[1:]]==['passed','passed']
    assert result.concepts[1]['authored_theme']['cueCss']==rows[1]['generated_source']['cueCss']
    assert ledger.value['candidate_states']['A']['status']=='failed'

def test_resume_uses_saved_directions_and_successful_sources(tmp_path):
    rows,directions=fixture()
    client=Client([rows[2]['generated_source']])
    ledger,result=run(tmp_path,client,retained={'directions':directions,'candidates':{r['id']:r for r in rows[:2]}})
    assert len(client.calls)==1 and client.calls[0][1]['input_scope']['candidate_ids']==['C']
    assert all(c.get('technical_status')!='failed' for c in result.concepts)

def test_cancel_preserves_completed_candidate_and_stops_following_requests(tmp_path):
    rows,directions=fixture();cancel=[False]
    client=Client([directions,rows[0]['generated_source']])
    def event(e):
        if e['name']=='candidate_complete':cancel[0]=True
    with pytest.raises(Exception,match='取消'):
        run(tmp_path,client,stage_event_callback=event,cancel_check=lambda:cancel[0])
    saved=json.loads((tmp_path/'ledger.json').read_text('utf8'))
    assert len(client.calls)==2 and saved['partial_concepts'][0]['id']=='A'
    assert saved['candidate_states']['A']['status']=='complete'

def test_real_render_diagnostic_repairs_only_one_new_version(tmp_path):
    from twobyteasr.caption_design.theme_draft import DraftValidationError
    rows,directions=fixture();renders=[]
    client=Client([directions,rows[0]['generated_source'],rows[0]['generated_source'],
        rows[1]['generated_source'],rows[2]['generated_source']])
    def render(c,folder,text,**kwargs):
        renders.append(c['id'])
        if len(renders)==1:
            error=DraftValidationError('actual long text clipped');error.render_evidence={'errors':['actual long text clipped']};raise error
        return dict(motion={'status':'motion_ready'},picture='test.png',full_frame='full.png',elapsed_seconds=1)
    ledger,result=run(tmp_path,client,render_candidate=render)
    assert renders==['A','A','B','C'] and len(client.calls)==5
    assert ledger.value['candidate_states']['A']['version']==2
    assert ledger.value['candidate_states']['A']['repairs']==1
    assert (tmp_path/'candidates/A/v1/provider-original.txt').is_file()
    assert (tmp_path/'candidates/A/v2/provider-original.txt').is_file()
    assert client.calls[2][1]['input_scope']['kind']=='render_repair'
    repair_text=client.calls[2][0][0]['content']
    assert 'isolated test' not in repair_text
    assert 'actual long text clipped' in repair_text
    from twobyteasr.providers.provider_input_budget import prepare_input
    _,report=prepare_input(client.calls[2][0],schema=client.calls[2][1]['json_schema'],
        max_tokens=32000,operation='generate',scope=client.calls[2][1]['input_scope'])
    assert report['passed']

def test_shared_renderer_failure_never_asks_model_to_redesign(tmp_path):
    rows,directions=fixture();client=Client([directions,*[r['generated_source'] for r in rows]])
    def render(*a,**kw):raise RuntimeError('browser unavailable')
    ledger,result=run(tmp_path,client,render_candidate=render)
    assert len(client.calls)==4
    assert all(c['technical_status']=='failed' for c in result.concepts)
    assert all(not s.get('render_repairs') for s in ledger.value['candidate_states'].values())

def test_single_matching_envelope_recovery_preserves_source_and_rejects_peers(tmp_path):
    from twobyteasr.caption_design.authored_generation import candidate_source
    rows,_=fixture();ledger=ThemeLedger(tmp_path,'Balatro')
    assert candidate_source({'candidates':[rows[2]]},'C',ledger)==rows[2]['generated_source']
    assert ledger.value['normalization'][0]['action']=='unwrap_single_matching_candidate'
    with pytest.raises(ValueError,match='身份不符'):
        candidate_source({'candidates':[rows[0]]},'C',ledger)
    with pytest.raises(ValueError,match='多个方向'):
        candidate_source({'candidates':rows},'C',ledger)


@pytest.mark.parametrize('category,stage',[
    ('request_too_large','local_budget'),('structured_output_truncated','response_without_source'),
    ('structured_output_reasoning_exhausted','response_without_source'),('provider_no_body','response_without_source')])
def test_failure_boundaries_do_not_retry_or_disable_peers(tmp_path,category,stage):
    from twobyteasr.providers.ai_providers import AIProviderError
    rows,directions=fixture()
    failures=[AIProviderError(category,category=category)]*(1 if category=='request_too_large' else 2)
    client=Client([directions,*failures,rows[1]['generated_source'],rows[2]['generated_source']])
    ledger,result=run(tmp_path,client)
    assert len(client.calls)==3+len(failures)
    assert ledger.value['candidate_states']['A']['stage']==stage
    assert all(c.get('technical_status')!='failed' for c in result.concepts[1:])


def test_budget_blocked_card_rebuilds_only_its_saved_direction(tmp_path,monkeypatch):
    from twobyteasr.providers.ai_providers import AIProviderError
    from twobyteasr.caption_design.caption_creative_pipeline import retry_saved_candidate
    from twobyteasr.providers.provider_registry import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.providers.provider_service import GLOBAL_PROVIDER_SERVICE
    from twobyteasr.caption_design import authored_preview
    from twobyteasr.caption_design.authored_prompt import VERSION
    rows,directions=fixture()
    ledger,result=run(tmp_path/'original',Client([directions,
        AIProviderError('local limit',category='request_too_large'),
        rows[1]['generated_source'],rows[2]['generated_source']]))
    peers=copy.deepcopy(ledger.value['candidates'])
    path=result.concepts[0]['ledger_path']
    client=Client([rows[0]['generated_source']])
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'selection',lambda *a,**k:
        SimpleNamespace(provider='deepseek',model='deepseek-v4-pro'))
    monkeypatch.setattr(GLOBAL_PROVIDER_SERVICE,'client_for_stage',lambda *a:client)
    renders=[]
    def render(c,*a,**k):
        renders.append(c['id'])
        return dict(motion={'status':'motion_ready'},picture='test.png',full_frame='full.png',elapsed_seconds=1)
    monkeypatch.setattr(authored_preview,'render_candidate_preview',render)
    restored=retry_saved_candidate(path,'A',{},ledger_root=tmp_path/'retry',request_id='retry')
    assert renders==['A'] and len(client.calls)==1
    assert client.calls[0][1]['input_scope']=={'kind':'implementation_completion','candidate_ids':['A']}
    assert [c['id'] for c in restored.concepts]==['A']
    assert restored.concepts[0].get('technical_status')!='failed'
    assert ThemeLedger.open(ledger.root/'ledger.json').value['candidates']==peers
    child=ThemeLedger.open(path)
    assert 'implementation_retries_by_assembly' not in child.value
    assert ThemeLedger.open(tmp_path/'retry'/'ledger.json').value['implementation_retries_by_assembly'][VERSION]==1
    child.value.setdefault('implementation_retries_by_assembly',{})[VERSION]=2;child.save()
    client.values=[rows[0]['generated_source']]
    retry_saved_candidate(path,'A',{},ledger_root=tmp_path/'extra',request_id='extra')
    assert len(client.calls)==2


def test_native_failure_without_completed_artifact_cannot_be_promoted(tmp_path):
    from twobyteasr.providers.ai_providers import AIProviderError
    rows,directions=fixture()
    client=Client([AIProviderError('old native error',category='structured_output_schema'),AIProviderError('completion failed',category='structured_output_schema')])
    ledger,result=run(tmp_path,client,retained={'directions':directions},only_candidate='A')
    assert len(client.calls)==2
    assert result.concepts[0]['technical_status']=='failed'
    assert client.calls[0][1]['json_schema'] is None
