import json
import time
from types import SimpleNamespace

import pytest

from twobyteasr.providers.ai_providers import AIProviderError
from twobyteasr.caption_design.design_task_budget import DesignTaskBudget,transport_retry_delay
from twobyteasr.caption_design.design_progress import PublicProgress,aggregate_activity,compact_status


def test_shared_allowance_absolute_deadline_and_cancellation():
    clock=[10.]
    budget=DesignTaskBudget(100,2,clock=lambda:clock[0])
    budget.reserve('network',candidate_id='A')
    budget.reserve('runtime',candidate_id='B')
    with pytest.raises(AIProviderError,match='次数'):budget.reserve('another')
    assert budget.remaining()==100
    clock[0]=111
    with pytest.raises(AIProviderError,match='总预算'):budget.check()
    with pytest.raises(AIProviderError,match='取消'):DesignTaskBudget(10).reserve('retry',cancel_check=lambda:True)


def test_retry_after_and_permanent_failures():
    from twobyteasr.providers.provider_stream import retry_after_seconds
    e=AIProviderError('429',category='rate_limited');e.retry_after_seconds=120
    assert transport_retry_delay(e)==120
    for category in ('quota_exhausted','auth_error','cancelled','request_rejected','request_too_large'):
        assert transport_retry_delay(AIProviderError(category,category=category)) is None
    assert retry_after_seconds('3')==3
    assert retry_after_seconds('bad date')==0


def test_local_and_heartbeat_never_forge_content_and_private_thinking_is_not_saved(tmp_path):
    events=[]
    progress=PublicProgress('r','等待首个输出',120,event_callback=events.append,path=tmp_path/'partial.txt')
    progress.stream('process_alive','local')
    progress.stream('heartbeat','heartbeat')
    progress.stream('thinking','PRIVATE SECRET REASONING')
    assert progress.phase['last_output_monotonic'] is None
    assert '尚无作品正文' in compact_status(progress.phase,progress.phase['started_monotonic']+91)
    assert '远端内部进度不可见' in compact_status(progress.phase,progress.phase['started_monotonic']+91)
    progress.stream('reasoning_summary','公开摘要：将文字与环纹分层。')
    progress.stream('delta','<div>字')
    progress.finish('failed')
    assert (tmp_path/'partial.txt').read_text('utf8')=='<div>字'
    assert 'PRIVATE' not in (tmp_path/'public-events.jsonl').read_text('utf8')
    assert progress.phase['public_summary'].startswith('公开摘要')
    aggregated=aggregate_activity({'A':{'activity':progress.phase}})
    assert aggregated['last_output_monotonic']==progress.phase['last_output_monotonic']


def test_responses_public_summary_is_distinct_from_reasoning_and_body():
    from twobyteasr.providers.provider_stream import responses_body
    packets=[{'type':'response.reasoning.delta','delta':'PRIVATE'},
             {'type':'response.reasoning_summary_text.delta','delta':'public summary'},
             {'type':'response.output_text.delta','delta':'art'},
             {'type':'response.completed','response':{'id':'r','status':'completed','output_text':'art'}}]
    raw=[('data: '+json.dumps(p)+'\n\n').encode() for p in packets]
    events=[]
    assert responses_body(raw,{},lambda *a:events.append(a))=='art'
    assert ('reasoning_summary','public summary') in events
    assert 'PRIVATE' not in repr(events)


def test_nonstreaming_interface_reports_transport_then_complete_body(monkeypatch):
    from twobyteasr.providers.provider_stream import request_chat
    class Response:
        status_code=200
        headers={'Content-Type':'application/json'}
        def iter_content(self,**kwargs):
            yield json.dumps({'id':'r','choices':[{'message':{'content':'正文'},'finish_reason':'stop'}]}).encode()
        def close(self):pass
    monkeypatch.setattr('requests.post',lambda *a,**kw:Response())
    events=[];diag={}
    assert request_chat('https://unit.test',{}, {},2,diag,lambda *a:events.append(a))=='正文'
    assert events[0][0]=='transport'
    assert any(k=='delta' and v=='正文' for k,v in events)
    assert not any(k in {'thinking','reasoning_summary'} for k,v in events)
    assert diag['protocol']=='chat_completions_json'


def test_http_retry_after_and_exhausted_quota_are_preserved(monkeypatch):
    from twobyteasr.providers.provider_stream import request_chat,StreamProtocolError
    class Response:
        status_code=429
        headers={'Content-Type':'application/json','Retry-After':'120'}
        code='rate_limit_exceeded'
        def iter_content(self,**kwargs):yield json.dumps({'error':{'code':self.code,'message':'wait'}}).encode()
        def close(self):pass
    response=Response();monkeypatch.setattr('requests.post',lambda *a,**kw:response)
    with pytest.raises(StreamProtocolError) as caught:request_chat('https://unit.test',{}, {},2,{},lambda *a:None)
    assert caught.value.retry_after_seconds==120 and caught.value.category=='rate_limited'
    response.code='insufficient_quota'
    with pytest.raises(StreamProtocolError) as caught:request_chat('https://unit.test',{}, {},2,{},lambda *a:None)
    assert caught.value.category=='quota_exhausted'


def test_no_hidden_deepseek_deadline_multiplier():
    from twobyteasr.caption_design.theme_generation_policy import authored_request_budget
    assert authored_request_budget('deepseek',{'ai_design_cli_timeout_seconds':150},candidate_count=1)[1].concepts==150


def test_builtin_easing_is_preserved_without_expression_evaluation():
    from twobyteasr.caption_design.theme_motion import validate_motion_spec
    spec=dict(version=2,runtime='gsap',tracks=[dict(selector='.copy',phase='build',
        ease='power4.out',start=0,end=1,**{'from':{'y':18},'to':{'y':0}})])
    assert validate_motion_spec(spec)['tracks'][0]['ease']=='power4.out'
    spec['tracks'][0]['ease']='arbitraryFunction()'
    with pytest.raises(ValueError):validate_motion_spec(spec)


def test_expired_local_preview_cannot_restart_renderer():
    from twobyteasr.caption_design.design_recovery import preview_with_recovery
    calls=[]
    with pytest.raises(AIProviderError,match='总预算'):
        preview_with_recovery(lambda **kw:calls.append(kw),remaining=lambda:0,
            on_retry=lambda:None,cancel_check=lambda:False)
    assert calls==[]


def test_deadline_expiring_inside_renderer_is_not_user_cancellation():
    from twobyteasr.caption_design.design_recovery import preview_with_recovery
    seconds=[1]
    def render(**kwargs):
        seconds[0]=0
        assert kwargs['cancel_check']()
        raise InterruptedError('render stopped')
    with pytest.raises(AIProviderError) as caught:
        preview_with_recovery(render,remaining=lambda:seconds[0],on_retry=lambda:None,cancel_check=lambda:False)
    assert caught.value.category=='provider_total_timeout'


@pytest.mark.parametrize('kind',['one_candidate','render_repair','implementation_completion'])
def test_raw_artifact_stream_explicitly_disables_repeated_deepseek_thinking(monkeypatch,kind):
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
    provider=OpenAICompatibleProvider(dict(provider='deepseek',model='fixture',api_key='fixture',
        url='https://api.deepseek.com/chat/completions',base_url='https://api.deepseek.com'))
    monkeypatch.setattr('twobyteasr.providers.provider_input_budget.prepare_input',lambda messages,**kw:(messages,{}))
    calls=[]
    def send(url,headers,body,*a,**kw):calls.append(body);return 'source artifact'
    monkeypatch.setattr('twobyteasr.providers.provider_stream.request_chat',send)
    provider.complete([dict(role='user',content='retained direction')],json_schema=None,
        on_stream_event=lambda *_:None,operation_kind='generate',input_scope={'kind':kind})
    assert 'response_format' not in calls[0]
    assert calls[0]['thinking']=={'type':'disabled'}


def test_transient_recovery_uses_saved_direction_and_same_task_budget(tmp_path,monkeypatch):
    from tests.test_authored_generation import Client,fixture
    from twobyteasr.caption_design.authored_generation import generate_staged
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    monkeypatch.setattr('twobyteasr.caption_design.design_task_budget.wait_for_retry',lambda *a:None)
    rows,directions=fixture()
    client=Client([AIProviderError('503',category='transport_error'),rows[0]['generated_source']])
    ledger=ThemeLedger(tmp_path,'金属机械文字')
    result=generate_staged(ledger,client,SimpleNamespace(provider='deepseek',model='test'),'',{},
        request_id='retry',retained={'directions':directions},only_candidate='A')
    assert len(client.calls)==2
    assert all(c[1]['input_scope']['kind']=='one_candidate' for c in client.calls)
    assert result.concepts[0].get('technical_status')!='failed'
    assert ledger.value['candidate_states']['A']['task_budget']['repairs_used']==1
    assert (tmp_path/'candidates/A/v1/transport-retry-1/provider-original.txt').exists()


def test_no_third_repair_request_when_transient_errors_persist(tmp_path,monkeypatch):
    from tests.test_authored_generation import Client,fixture
    from twobyteasr.caption_design.authored_generation import generate_staged
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    monkeypatch.setattr('twobyteasr.caption_design.design_task_budget.wait_for_retry',lambda *a:None)
    _,directions=fixture()
    client=Client([AIProviderError('503',category='transport_error') for _ in range(4)])
    ledger=ThemeLedger(tmp_path,'金属机械文字')
    result=generate_staged(ledger,client,SimpleNamespace(provider='deepseek',model='test'),'',{},
        request_id='retry',retained={'directions':directions},only_candidate='A')
    assert len(client.calls)==3
    assert result.concepts[0]['technical_status']=='failed'
    assert ledger.value['candidate_states']['A']['category']=='repair_budget_exhausted'


def test_empty_preview_terminal_refresh_and_scroll_retention():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog
    c=dict(id='A',name='方向',pending=True,technical_status='pending')
    d=ThemeConceptDialog([c],{})
    assert d.primary.text()=='停止并保留'
    d.set_task_states({'A':{'status':'failed','error':'输出截断','stage':'output_incomplete'}})
    assert '输出截断' in d.picture.text()
    assert '已停止' in d.candidate_list.item(0).text()
    assert d.primary.text()!='停止并保留'
    assert '正在处理此方向' not in d.picture.text()
    d.close()


def test_restored_local_source_does_not_invent_a_remote_task_clock():
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    from twobyteasr.caption_design.theme_concept_dialog import ThemeConceptDialog
    d=ThemeConceptDialog([dict(id='A',name='本地作品',technical_status='ready',authored_theme={'name':'作品'})],{})
    assert '源已保存' in d.status.text()
    assert '准备任务' not in d.status.text() and '尚无作品正文' not in d.status.text()
    d.close()


def test_theme_guidance_has_no_unrelated_presets(tmp_path):
    from twobyteasr.caption_design.authored_prompt import assemble
    from twobyteasr.caption_design.caption_creative_pipeline import ThemeLedger
    from twobyteasr.caption_design.caption_reference_search import queries_for,prompt_evidence
    ledger=ThemeLedger(tmp_path,'塞尔达主题')
    prompt,receipt=assemble(ledger,direction={'name':'方向','design':'字与环纹'},artifact_identity='a')
    assert 'CRT用持续缓慢扫描' not in prompt
    assert 'verified_components' not in receipt['components']
    assert not any(f['path'].endswith('material-caption.md') for f in receipt['skills']['files'])
    assert queries_for('塞尔达主题')[0].startswith('Nintendo')
    ledger.value['reference_search']={'status':'cached','translation':['旧禁止'], 'sources':[]}
    assert 'translation' not in prompt_evidence(ledger)
    from twobyteasr.caption_design.design_recovery import implementation_message
    repair,assembly=implementation_message(ledger,{'name':'方向','design':'字与环纹'},'b')
    assert 'verified_components' not in assembly['components']
