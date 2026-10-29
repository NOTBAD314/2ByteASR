"""Offline reproduction of live-r2 model rejection; never probe accounts/models."""
import json
import subprocess
import threading
from dataclasses import replace

import pytest

from tests.test_stage9_cache_and_budget import context
from twobyteasr.providers.ai_providers import AIProviderError, GrokCLIProvider
from twobyteasr.recognition.transcript_data import SpeechSegment
from twobyteasr.providers.provider_input_budget import RetryBudget, retry_delay


def envelope():
    return {'type':'result', 'subtype':'error_during_execution', 'is_error':True,
            'errors':["Couldn't set model 'grok-fixture': Invalid params: \"unknown model id\". Run 'grok models' to see available models."],
            'access_token':'SECRET_FIXTURE_ONLY'}


def test_unknown_model_is_configuration_failure_with_redacted_details():
    from twobyteasr.providers.provider_diagnostics import cli_failure
    failure=cli_failure(json.dumps(envelope()))
    assert failure['category']=='unknown_model'
    assert 'SECRET_FIXTURE_ONLY' not in str(failure)
    assert retry_delay(AIProviderError(failure['message'], category=failure['category']),1) is None


@pytest.mark.parametrize('packet', [
    {'type':'assistant','message':{'content':[{'type':'text','text':'解释 unknown model id'}]}},
    {'type':'result','is_error':False,'result':"Couldn't set model 'fixture': unknown model id"},
    {'role':'user','content':'unknown model id'},
    {'type':'assistant','message':{'content':[{'type':'text','text':json.dumps({'errors':['unknown model id']})}]}},
    {'type':'user','message':{'errors':['unknown model id']}},
])
def test_success_or_user_text_does_not_reject_model(packet):
    from twobyteasr.providers.provider_diagnostics import cli_failure
    assert cli_failure(json.dumps(packet)) is None


@pytest.mark.parametrize('channel',['stdout','stderr'])
def test_actual_cli_terminal_error_stops_stream_without_accepting_body(monkeypatch,channel):
    provider=GrokCLIProvider(executable='fixture-grok.exe',model='grok-fixture')
    def run(command,**kwargs):
        kwargs['on_line'](channel,json.dumps(envelope()))
        assert kwargs['stop_when']()
        return subprocess.CompletedProcess(command,1,'','')
    monkeypatch.setattr(provider,'_run_cli_command',run)
    with pytest.raises(AIProviderError) as caught:
        provider._run_cli_stream([provider.executable],purpose='offline-fixture',timeout=1)
    assert caught.value.category=='unknown_model' and not provider.request_succeeded


def test_nonstream_multiple_lines_do_not_hide_model_selection_error(monkeypatch):
    provider=GrokCLIProvider(executable='fixture-grok.exe',model='grok-fixture')
    monkeypatch.setattr(provider,'_run_cli_command',lambda command,**kw:
        subprocess.CompletedProcess(command,1,json.dumps({'type':'system','message':'fixture'})+'\n'+json.dumps(envelope()),''))
    with pytest.raises(AIProviderError) as caught:
        provider._complete_cli_command([provider.executable,'--cwd','.'],1,False,None,None,{})
    assert caught.value.category=='unknown_model'


@pytest.mark.parametrize('stage',['polished','grouped'])
def test_later_batches_preserve_local_results_and_new_snapshot_can_retry(context,monkeypatch,stage):
    from twobyteasr.subtitle_rules import polishing, grouping
    _,ctx,_=context
    calls=[]
    class Provider:
        def complete(self,*a,**kw):
            calls.append(kw)
            raise AIProviderError('服务端拒绝 unknown model id',category='unknown_model')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**kw:Provider())
    monkeypatch.setattr(grouping,'provider_for_stage',lambda *a,**kw:Provider())
    monkeypatch.setattr(RetryBudget,'wait',lambda *a,**kw:pytest.fail('deterministic model errors never retry'))
    budget=RetryBudget(2)
    abort=threading.Event()
    def call(cue_id, shared=budget):
        segment=SpeechSegment(cue_id,0.,3.,'这个选手也没有接住最后一枪',.9,[])
        if stage=='polished':
            result=polishing.call_correction_api([segment],[], '', '', 'fixture','fixture',[],[],[],
                _planned=True,_retry_budget=shared,abort_event=abort)
            assert result[cue_id]==segment.text and result.failures[cue_id]=='unknown_model'
            assert not result.succeeded
        else:
            diagnostics={}
            result=grouping.call_grouping_api([segment],_packed=True,_retry_budget=shared,
                abort_event=abort,batch_diagnostics=diagnostics)
            assert ''.join(cue.text for cue in result)==segment.text
            assert result.origin=='fallback' and not result.validated
            assert diagnostics['fallback_reason']=='unknown_model'
        return result
    call(1)
    call(2)
    assert len(calls)==1 and budget.remaining==2 and not abort.is_set()
    ctx.provider_snapshot=replace(ctx.provider_snapshot,model='fixture-corrected')
    call(3)
    assert len(calls)==2
    call(4,RetryBudget(2))
    assert len(calls)==3


def test_queue_checks_task_rejection_before_start_and_does_not_poison_provider(context):
    from twobyteasr.providers.provider_service import ProviderService
    _,ctx,_=context
    budget=RetryBudget(2)
    scope=(budget,'grouped',ctx.provider_snapshot.fingerprint)
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def send(*a,**kw):
        calls.append(kw)
        assert '_task_failure_scope' not in kw
        if len(calls)==1:
            entered.set()
            assert release.wait(2)
            raise AIProviderError('unknown model id',category='unknown_model')
        return '{}'
    service=ProviderService(workers=1,circuit_failures=1)
    client=service.client_for_stage(ctx.provider_snapshot.execution_settings(),'group',sender=send)
    options=dict(timeout=2,_timeout_policy=ctx.provider_snapshot.timeout_policy,_task_failure_scope=scope)
    first=client.submit([],**options)
    assert entered.wait(1)
    second=client.submit([],**options)
    release.set()
    for handle in (first,second):
        with pytest.raises(AIProviderError) as caught:
            handle.result(2)
        assert caught.value.category=='unknown_model'
    assert len(calls)==1 and service.wait_for_idle(1)
    runtime=service._runtime_for(ctx.provider_snapshot.execution_settings(),'group',send)
    assert runtime.failure_count==0 and runtime.circuit_open_until==0
    fresh=(RetryBudget(2),'grouped',ctx.provider_snapshot.fingerprint)
    assert client.complete([],timeout=2,_timeout_policy=ctx.provider_snapshot.timeout_policy,
        _task_failure_scope=fresh)=='{}'
    assert len(calls)==2 and service.wait_for_idle(1)


def test_task_latch_is_stage_scoped_and_does_not_latch_transient_errors():
    budget=RetryBudget(2)
    assert not budget.reject_snapshot('polished','same-model',AIProviderError('timeout',category='total_timeout'))
    assert budget.reject_snapshot('polished','same-model',AIProviderError('unknown model',category='unknown_model'))
    assert budget.snapshot_rejection('grouped','same-model') is None
    assert budget.snapshot_rejection('polished','corrected-model') is None
