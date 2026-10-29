"""Installed JSON capability evidence, final boundaries and settings snapshots."""
import json
import subprocess

import pytest

from twobyteasr.providers.ai_providers import (AIProviderError, CLIProvider, GrokCLIProvider,
                                    AntigravityCLIProvider, _extract_json_object, _extract_cli_text)
from twobyteasr.providers.llm_config import activate_ai_service, update_active_profile, resolved_service_values
from twobyteasr.storage.settings import DEFAULT_SETTINGS
from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
from tests.test_stage9_cache_and_budget import context

SCHEMA = {'type': 'object', 'properties': {'text': {'type': 'string'}},
          'required': ['text'], 'additionalProperties': False}


@pytest.mark.parametrize('provider_class', [AntigravityCLIProvider, GrokCLIProvider])
def test_structured_request_reaches_native_schema_and_retains_local_contract(monkeypatch, provider_class):
    provider = provider_class(executable='synthetic.exe', model='synthetic-json')
    monkeypatch.setattr(provider, '_record_installed_version', lambda *a: None)
    monkeypatch.setattr(provider, 'json_capabilities', lambda **k: {'native_schema': True, 'state': 'supported_unverified'})
    received = []
    def complete(messages, **kwargs):
        received.append(kwargs['json_schema'])
        return '{"text":"兔白字幕"}'
    monkeypatch.setattr(provider, 'complete', complete)
    assert provider.structured_complete([], SCHEMA) == {'text': '兔白字幕'}
    assert received == [SCHEMA]
    monkeypatch.setattr(provider, 'complete', lambda *a, **kw: '{"text":17}')
    with pytest.raises(AIProviderError, match='字段校验') as caught:
        provider.structured_complete([], SCHEMA)
    assert caught.value.category == 'structured_output_schema'


def test_detection_failure_does_not_become_unsupported(monkeypatch):
    provider = GrokCLIProvider(executable='synthetic.exe', model='detection-failure')
    monkeypatch.setattr(provider, '_run_cli_command', lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired('help', 5)))
    failed = provider.json_capabilities(probe=True)
    assert failed['state'] == 'failed' and failed['native_schema'] is None
    monkeypatch.setattr(provider, '_run_cli_command', lambda *a, **k: subprocess.CompletedProcess('help', 0, '--json-schema --output-format json streaming-json', ''))
    supported = provider.json_capabilities(probe=True)
    assert supported['native_schema'] and supported['state'] == 'supported_unverified'


def test_capability_cache_separates_path_version_provider_and_model(monkeypatch):
    first = GrokCLIProvider(executable='one.exe', model='a')
    monkeypatch.setattr(first, '_run_cli_command', lambda *a, **k: subprocess.CompletedProcess('help', 0, '--json-schema json', ''))
    assert first.json_capabilities(probe=True)['native_schema']
    for second in (GrokCLIProvider(executable='two.exe', model='a'),
                   GrokCLIProvider(executable='one.exe', model='b'),
                   AntigravityCLIProvider(executable='one.exe', model='a')):
        assert second.json_capabilities()['native_schema'] is None
    first.cli_version = 'new-version'
    assert first.json_capabilities()['native_schema'] is None


@pytest.mark.parametrize('text', ['progress {"text":"错误对象"}\n{"text":"最终"}',
                                 '{"text":"最终"} trailing log',
                                 '```json\n{"text":"最终"}\n```\nextra'])
def test_json_parser_does_not_take_object_from_logs(text):
    with pytest.raises(AIProviderError):
        _extract_json_object(text)


def test_agy_uses_terminal_structured_output_instead_of_text_or_tools():
    state = {'text': '', 'final': None, 'require_terminal_result': True}
    emit = lambda *a: None
    CLIProvider._consume_cli_stream_line(json.dumps({'event': 'step_update', 'step_update': {
        'step_type': 'tool', 'text_delta': '{"text":"工具"}'}}), state, emit)
    CLIProvider._consume_cli_stream_line(json.dumps({'event': 'step_update', 'step_update': {
        'step_type': 'agent_response', 'text_delta': '正文外有解释'}}), state, emit)
    assert not state.get('terminal_result')
    CLIProvider._consume_cli_stream_line(json.dumps({'event': 'result', 'result': {
        'status': 'SUCCESS', 'response': '重复解释', 'structured_output': {'text': '兔白字幕'}}}), state, emit)
    assert json.loads(state['final']) == {'text': '兔白字幕'} and state['terminal_result']


@pytest.mark.parametrize('reason,category', [('length', 'structured_output_truncated'),
                                           ('refusal', 'provider_refusal')])
def test_terminal_truncation_and_refusal_do_not_accept_valid_partial_json(reason, category):
    state = {'text': '', 'final': None}
    CLIProvider._consume_cli_stream_line(json.dumps({'type': 'result', 'finish_reason': reason,
        'structured_output': {'text': '部分'}}), state, lambda *a: None)
    assert state['terminal_category'] == category


@pytest.mark.parametrize('envelope', [{'models': ['x']}, {'authenticated': True}, {'loggedIn': True}])
def test_account_or_catalogue_is_not_a_business_answer(envelope):
    assert not _extract_cli_text(json.dumps(envelope))


def test_saved_json_preference_is_part_of_recognition_snapshot():
    import copy
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    activate_ai_service(settings, 'antigravity', unified=True)
    update_active_profile(settings, model='gemini-synthetic', json_mode=True,
                          structured_output=False, unified=True)
    assert not resolved_service_values(settings, 'antigravity')['structured_output']
    snapshot = resolve_provider_snapshot(settings, stage='polish')
    update_active_profile(settings, structured_output=True, unified=True)
    assert not snapshot.structured_output
    assert not snapshot.execution_settings()['models']['polish_structured_output']


@pytest.mark.parametrize('reason,category', [('length', 'structured_output_truncated'),
    ('content_filter','provider_refusal'), ('tool_calls','provider_tool_request')])
def test_http_terminal_reason_stays_distinct_even_with_valid_partial_json(reason, category):
    from twobyteasr.providers.provider_stream import chat_body, StreamProtocolError
    packets = [dict(choices=[dict(index=0,delta={'content':'{"text":"兔白字幕"}'},finish_reason=reason)])]
    wire = ''.join('data: '+json.dumps(row)+'\n\n' for row in packets)+'data: [DONE]\n\n'
    with pytest.raises(StreamProtocolError) as caught:
        chat_body([wire.encode('utf8')], {})
    assert caught.value.category == category


def test_http_explicit_refusal_does_not_become_json_body():
    from twobyteasr.providers.provider_stream import responses_final, StreamProtocolError
    response = {'status':'completed','output':[{'type':'message','content':[
        {'type':'refusal','refusal':'declined'}]}]}
    with pytest.raises(StreamProtocolError) as caught:
        responses_final(response, {})
    assert caught.value.category == 'provider_refusal'


def test_retries_and_queue_policy_keep_one_wall_clock_deadline():
    from twobyteasr.providers.provider_input_budget import RetryBudget
    from twobyteasr.providers.asr_provider_snapshot import TimeoutPolicy
    clock = [100.]
    budget = RetryBudget(3, total_seconds=10, clock=lambda:clock[0])
    first = budget.request_policy(TimeoutPolicy())
    clock[0] = 106.
    second = budget.request_policy(TimeoutPolicy())
    assert first.deadline_monotonic == second.deadline_monotonic == 110.
    assert first.total == 10 and second.total == second.queue == 4
    clock[0] = 110.
    assert not budget.take()
    with pytest.raises(AIProviderError) as raised:
        budget.request_policy(TimeoutPolicy())
    assert raised.value.category == 'total_timeout'


def test_production_polish_does_not_restart_time_after_timeout(context, monkeypatch):
    from twobyteasr.subtitle_rules import polishing
    from twobyteasr.providers.provider_input_budget import RetryBudget
    from twobyteasr.recognition.transcript_data import SpeechSegment
    _, owner, _ = context
    monkeypatch.setattr('twobyteasr.providers.asr_provider_snapshot.task_provider_snapshot',
                        lambda *_:owner.provider_snapshot)
    clock = [100.]
    budget = RetryBudget(3,total_seconds=10,clock=lambda:clock[0])
    calls = []
    class Provider:
        def complete(self, *args, **kwargs):
            calls.append(kwargs['_timeout_policy'])
            clock[0] = 111.
            raise AIProviderError('fixture timeout',category='total_timeout')
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage',lambda *a,**kw:Provider())
    first = SpeechSegment(1,0.,1.,'原始字幕一',.9,[])
    second = SpeechSegment(2,1.,2.,'原始字幕二',.9,[])
    def run(segment):
        return polishing.call_correction_api([segment],[], '', '', 'fixture', '', [], [], [],
            _retry_budget=budget)
    result = run(first)
    later = run(second)
    assert len(calls) == 1 and calls[0].deadline_monotonic == 110.
    assert result.failures == {1:'total_timeout'} and later.failures == {2:'total_timeout'}
    assert result[1] == '原始字幕一' and later[2] == '原始字幕二'


def test_editor_discards_stale_callback_after_draft_changes_back(monkeypatch):
    import copy
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app import ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui.EndpointEditor,'_queue_model_discovery',lambda *a:None)
    from twobyteasr.providers import endpoint_editor_ui
    monkeypatch.setattr(endpoint_editor_ui,'read_api_key',lambda *a:('', 'fixture'))
    settings=copy.deepcopy(DEFAULT_SETTINGS)
    activate_ai_service(settings,'grok_account',unified=True)
    editor=ui.EndpointEditor('fixture','#ac4169','group',settings)
    class Worker:
        def isRunning(self): return False
    worker=Worker()
    editor._tester=worker
    delivered=[]
    stale=editor._endpoint_callback(worker,'_tester',lambda *a:delivered.append(a))
    original=editor.model.currentText()
    editor.model.setCurrentText('draft-away')
    editor.model.setCurrentText(original)
    editor._tester=worker
    stale(True,'old response')
    assert not delivered and editor.test_button.isEnabled()
    editor._tester=None
    editor.close()


@pytest.mark.parametrize('provider_class,flag', [(GrokCLIProvider,'--reasoning-effort'),
    (AntigravityCLIProvider,'--effort')])
def test_request_scoped_low_effort_uses_installed_help_not_profile_edits(monkeypatch,tmp_path,provider_class,flag):
    provider=provider_class(executable='fixture.exe',model='fixture-low-effort')
    monkeypatch.setattr(provider,'_record_installed_version',lambda *a:None)
    monkeypatch.setattr(provider,'json_capabilities',lambda **kw:{
        'reasoning_effort_argument':flag,'executable':'fixture.exe','version':'fixture-version','help_sha256':'fixture-help'})
    monkeypatch.setattr('tempfile.tempdir',str(tmp_path))
    commands=[]
    monkeypatch.setattr(provider,'_complete_cli_command',lambda command,*a:commands.append(command) or '{}')
    diagnostics={}
    provider.complete([{'role':'user','content':'有限校对'}],enable_thinking=False,request_diagnostics=diagnostics)
    assert commands[0][commands[0].index(flag)+1] == 'low'
    assert diagnostics['cli_reasoning_effort']['version'] == 'fixture-version'
    provider.complete([{'role':'user','content':'保留默认推理'}])
    assert commands[0].count(flag) == 1
    assert commands[1][commands[1].index(flag)+1] == ('high' if provider_class is GrokCLIProvider else 'medium')


def test_agy_explicit_high_model_suffix_keeps_user_model_without_conflicting_effort(monkeypatch,tmp_path):
    provider=AntigravityCLIProvider(executable='fixture.exe',model='gemini-synthetic-flash-high')
    monkeypatch.setattr(provider,'_record_installed_version',lambda *a:None)
    monkeypatch.setattr(provider,'json_capabilities',lambda **kw:{'reasoning_effort_argument':'--effort'})
    monkeypatch.setattr('tempfile.tempdir',str(tmp_path))
    commands=[]
    monkeypatch.setattr(provider,'_complete_cli_command',lambda command,*a:commands.append(command) or '{}')
    diagnostics={}
    provider.complete([{'role':'user','content':'保持可见模型'}],enable_thinking=False,request_diagnostics=diagnostics)
    assert '--effort' not in commands[0]
    assert commands[0][commands[0].index('--model')+1] == provider.model
    assert diagnostics['cli_reasoning_effort']['requested_effort'] == 'low'
    assert diagnostics['cli_reasoning_effort']['actual_model_suffix'] == 'high'
    assert diagnostics['cli_reasoning_effort']['not_applied_reason'] == 'selected_model_suffix_owns_effort'
