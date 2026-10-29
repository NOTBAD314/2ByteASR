import json
import sys
import threading
import time
from pathlib import Path

import pytest


def test_wire_ascii_escaping_rechecked_before_network(monkeypatch):
    from twobyteasr.providers.provider_stream import request_chat,StreamProtocolError
    from twobyteasr.providers.provider_input_budget import prepare_input
    import requests
    messages=[{'role':'user','content':'字幕'*80}]
    _,budget=prepare_input(messages,operation='generate',max_tokens=32000)
    budget['policy']['payload_bytes']=800
    assert budget['payload_utf8_bytes']<800
    monkeypatch.setattr(requests,'post',lambda *a,**k:pytest.fail('oversize request reached network'))
    diagnostics={}
    with pytest.raises(StreamProtocolError) as caught:
        request_chat('https://example.test/v1/chat/completions',{},dict(model='custom',messages=messages,max_tokens=32000),
            10,diagnostics,lambda *_:None,input_budget=budget)
    assert caught.value.category=='request_too_large'
    assert budget['wire_payload_bytes']>800 and budget['dispatched'] is False

from twobyteasr.providers.provider_stream import chat_body, StreamProtocolError
from twobyteasr.providers.structured_output import response_object, StructuredResponseError

def test_http_request_rejection_keeps_bounded_redacted_reason(monkeypatch):
    from twobyteasr.providers.provider_stream import request_chat
    class Response:
        status_code=400
        headers={'Content-Type':'application/json'}
        def iter_content(self,**kwargs):
            yield json.dumps({'error':{'message':'JSON is required; api_key=sk-123456789012345678',
                                      'type':'invalid_request_error'}}).encode()
        def close(self):pass
    monkeypatch.setattr('requests.post',lambda *a,**kw:Response())
    diagnostics={}
    with pytest.raises(StreamProtocolError) as exc:
        request_chat('https://invalid.example',{}, {},2,diagnostics,lambda *_:None)
    assert exc.value.category=='request_rejected'
    assert 'JSON is required' in str(exc.value) and '123456789012345678' not in str(exc.value)
    assert diagnostics['provider_error']['type']=='invalid_request_error'


def event(content=None, finish=None, **extra):
    return ('data: '+json.dumps(dict(id='request-framing', choices=[dict(index=0,
        delta={} if content is None else {'content': content}, finish_reason=finish)], **extra), ensure_ascii=False)+'\r\n\r\n').encode('utf8')


def test_every_byte_boundary_and_character_delta_has_one_final_body():
    body = json.dumps({'name': '三轨中文字幕', 'cueCss': '.x {color:red}'}, ensure_ascii=False, indent=2)
    raw = b': ping\n\n'+b''.join(event(c) for c in body)+event(finish='stop')+b'data: [DONE]\n\n'
    for width in (1, 2, 3, 7, 1024, len(raw)):
        diagnostics = {}; notifications = []
        result = chat_body((raw[i:i+width] for i in range(0, len(raw), width)), diagnostics,
                           lambda *args: notifications.append(args))
        assert response_object(result) == json.loads(body)
        assert sum(kind == 'final' for kind, _ in notifications) == 1
        assert diagnostics['content_chars'] == len(body)
        assert diagnostics['completed'] and diagnostics['finish_reason'] == 'stop'


@pytest.mark.parametrize('raw,category', [
    (event('{')+event(finish='length'), 'structured_output_truncated'),
    (event('{}'), 'structured_output_truncated'),
    (event('{}')+b'data: [DONE]\n\n', 'structured_output_truncated'),
    (event('{}')+event(finish='stop')+event('bad'), 'conflicting_final'),
    (b'data: []\n\n', 'provider_protocol_error'),
    (b'data: {broken}\n\n', 'provider_protocol_error'),
    (event('{}')+b'data: \xe4\xb8', 'structured_output_truncated'),
])
def test_incomplete_or_conflicting_streams_are_never_success(raw, category):
    with pytest.raises(StreamProtocolError) as exc:
        chat_body([raw], {})
    assert exc.value.category == category


def test_thinking_and_progress_do_not_pollute_body_and_cancel_wins():
    packet = {'id':'request-framing', 'choices':[{'delta':{'reasoning_content':'隐藏思考'}, 'finish_reason':None}]}
    raw = ('data: '+json.dumps(packet)+'\n\n').encode()+event('{"ok":true}')+event(finish='stop')+b'data: [DONE]\n\n'
    assert chat_body([raw], {}) == '{"ok":true}'
    with pytest.raises(StreamProtocolError) as exc:
        chat_body([raw], {}, cancel_check=lambda: True)
    assert exc.value.category == 'cancelled'


def test_pretty_truncated_body_does_not_become_jsonl_and_strings_are_not_redecoded():
    with pytest.raises(StructuredResponseError) as exc:
        response_object('{\n  "candidates": [\n    {"cueCss": "box-shadow:0 0 30px rgba')
    assert exc.value.category == 'structured_output_truncated'
    assert 'jsonl' not in str(exc.value) and 'length=1' not in str(exc.value)
    with pytest.raises(ValueError, match='received str'):
        response_object(json.dumps('{"name":"double encoded"}'))
    assert response_object('\n{"type":"progress"}\n\n{"type":"final","result":{"ok":true}}\n') == {'ok': True}
    with pytest.raises(StructuredResponseError) as exc:
        response_object('{"type":"progress"}\n{"type":"cancelled"}')
    assert exc.value.category == 'cancelled'


def test_agy_nested_structured_result_is_authoritative():
    from twobyteasr.providers.ai_providers import CLIProvider
    state={};events=[]
    CLIProvider._consume_cli_stream_line(json.dumps({'event':'result','result':{
        'status':'SUCCESS','response':'{"candidates":[]}\n{"candidates":[],"toolAction":"submit"}',
        'structured_output':{'candidates':[]}}}),state,lambda *x:events.append(x))
    assert json.loads(state['final'])=={'candidates':[]}
    assert state['finished'] and state['terminal_result']


def test_provider_keeps_finish_metadata_and_does_not_retry(monkeypatch):
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider, AIProviderError
    from twobyteasr.providers.llm_adapter import LLMRequestError
    # Test the production HTTP provider, with one local transport invocation.
    provider = OpenAICompatibleProvider(endpoint=dict(provider='deepseek', model='fixture', api_key='fixture', url='https://api.deepseek.com/chat/completions', base_url='https://api.deepseek.com'))
    calls = []
    def failed(*args, **kwargs):
        calls.append(kwargs)
        raise LLMRequestError('truncated', category='structured_output_truncated')
    monkeypatch.setattr('twobyteasr.providers.llm_adapter.post_chat_completion_stream', failed)
    monkeypatch.setattr(provider, '_sender', lambda *a, **kw: pytest.fail('must not retry non-streaming'))
    with pytest.raises(AIProviderError) as exc:
        provider.complete([{'role':'user','content':'JSON'}], on_stream_event=lambda *_:None)
    assert exc.value.category == 'structured_output_truncated' and len(calls) == 1


@pytest.mark.parametrize('operation,scope,thinking',[
    ('generate','three_new_candidates',True),('generate','one_full_creative_redo',True),
    ('generate','design_directions',True),('generate','one_candidate',False),('generate','render_repair',False),
    ('local_patch','single_candidate',False),('polish','transcript',False)])
def test_only_full_design_requests_enable_selected_deepseek_planning(monkeypatch,operation,scope,thinking):
    from twobyteasr.providers.ai_providers import OpenAICompatibleProvider
    from twobyteasr.providers.llm_adapter import get_last_llm_response_diagnostics
    provider=OpenAICompatibleProvider(endpoint=dict(provider='deepseek',model='fixture',api_key='fixture',
        url='https://api.deepseek.com/chat/completions',base_url='https://api.deepseek.com'))
    # Input budgets are tested separately; here exercise the real HTTP body boundary.
    monkeypatch.setattr('twobyteasr.providers.provider_input_budget.prepare_input',lambda messages,**k:(messages,{}))
    calls=[]
    def send(url,headers,body,*args,**kwargs):calls.append(body);return '{"ok":true}'
    monkeypatch.setattr('twobyteasr.providers.provider_stream.request_chat',send)
    provider.complete([{'role':'user','content':'JSON'}],json_schema={'type':'object'},
        on_stream_event=lambda *_:None,operation_kind=operation,input_scope={'kind':scope})
    assert calls[0]['thinking']=={'type':'enabled' if thinking else 'disabled'}
    assert calls[0]['model']=='fixture' and calls[0]['response_format']=={'type':'json_object'}


def test_real_cli_conflicting_finals_and_nonzero_exit(monkeypatch, tmp_path):
    from twobyteasr.providers.ai_providers import CLIProvider, AIProviderError
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'local'))
    for content, category in [
        ([{'type':'result','result':'{"a":1}'}, {'type':'result','result':'{"a":2}'}], 'conflicting_final'),
        ([{'type':'result','result':'{"a":1}'}], 'nonzero_exit'),
        ([{'type':'assistant','message':{'content':[{'type':'text','text':'{"a":'}], 'stop_reason':'max_tokens'}}], 'structured_output_truncated'),
    ]:
        script = tmp_path/'emit.py'
        script.write_text('import sys\nprint('+repr('\n'.join(json.dumps(x) for x in content))+', flush=True)\nsys.exit(7)\n', 'utf8')
        provider = CLIProvider(executable=sys.executable)
        with pytest.raises(AIProviderError) as exc:
            provider._run_cli_stream([sys.executable, str(script)], purpose='fixture response framing', timeout=3)
        assert exc.value.category == category


def test_cli_assistant_and_structured_final_compare_json_contents():
    from twobyteasr.providers.ai_providers import CLIProvider
    state={'text':'','thinking':'','final':None,'finished':False}
    packets=[{'type':'assistant','message':{'content':[{'type':'text','text':'{"candidates":[{"id":"one"}]}'}]}},
             {'type':'result','is_error':False,'structured_output':{'candidates':[{'id':'one'}]}}]
    for packet in packets:CLIProvider._consume_cli_stream_line(json.dumps(packet),state,lambda *_:None)
    assert not state.get('terminal_error') and state['terminal_result']
    assert json.loads(state['final'])==packets[1]['structured_output']


def test_cli_schema_error_preserves_failure_and_summarizes_field_lengths():
    from twobyteasr.providers.ai_providers import CLIProvider
    state = {'text': json.dumps({'cueHtml': 'X' * 9095}),
             'final': '{"cueHtml":"old"}',
             'response_schema': {'properties': {'cueHtml': {'maxLength': 8192}}}}
    events = []
    CLIProvider._consume_cli_stream_line(json.dumps({
        'type': 'result', 'is_error': True,
        'subtype': 'error_max_structured_output_retries',
        'errors': ['X' * 9095 + ' is longer than 8192 characters'],
    }), state, lambda *x: events.append(x))
    assert state['terminal_category'] == 'structured_output_schema'
    assert state['terminal_diagnostics']['issues'][0] == dict(path='$.cueHtml', validator='maxLength', actual=9095, limit=8192)
    assert len(state['terminal_error']) < 200 and not events
    assert state['finished'] and state['terminal_result']


@pytest.mark.parametrize('terminal', ['error', 'success', 'missing'])
def test_schema_cli_waits_for_delayed_result_receipt(monkeypatch, tmp_path, terminal):
    from twobyteasr.providers.ai_providers import CLIProvider, AIProviderError
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'local'))
    packets = [{'type': 'assistant', 'message': {'stop_reason': 'end_turn',
                'content': [{'type': 'text', 'text': '{"ok":true}'}]}}]
    receipt = ({'type': 'result', 'is_error': True,
                'subtype': 'error_max_structured_output_retries', 'errors': ['invalid schema']}
               if terminal == 'error' else
               {'type': 'result', 'is_error': False, 'structured_output': {'ok': True}})
    script = tmp_path/'delayed.py'
    script.write_text('import time\nprint('+repr(json.dumps(packets[0]))+', flush=True)\n'
                      'time.sleep(.65)\n'+
                      ('print('+repr(json.dumps(receipt))+', flush=True)\n' if terminal != 'missing' else ''), 'utf8')
    provider = CLIProvider(executable=sys.executable)
    events = []
    run = lambda: provider._run_cli_stream([sys.executable, str(script)],
        purpose='delayed schema receipt', timeout=3, complete_json_early=True,
        require_terminal_result=True, on_stream_event=lambda *x: events.append(x))
    if terminal == 'success':
        assert json.loads(run()) == {'ok': True}
        assert sum(kind == 'final' for kind, _ in events) == 1
    else:
        with pytest.raises(AIProviderError) as caught:run()
        assert caught.value.category == ('structured_output_schema' if terminal == 'error' else 'provider_protocol_error')
        assert not any(kind == 'final' for kind, _ in events)


def test_cancelled_client_does_not_reuse_previous_billing_receipt(monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.providers.provider_service import AIClient, ProviderRequestHandle
    from twobyteasr.providers.ai_providers import AIProviderError
    client = object.__new__(AIClient)
    client._last_request_trace = {'request_id': 'previous', 'actual_cost_usd': 8.5}
    handle = ProviderRequestHandle('current', 'fixture', time.monotonic()+3)
    monkeypatch.setattr(client, 'submit', lambda *a, **k: handle)
    with pytest.raises(AIProviderError) as caught:
        client.complete([], cancel_check=lambda:True, _timeout_policy=SimpleNamespace(queue=1,total=3))
    assert caught.value.category == 'cancelled' and handle.cancelled
    assert client.invocation_trace() == {'request_id':'current','receipt_status':'cleanup_pending'}


def test_structured_submit_preflight_failure_drops_previous_receipt():
    from types import SimpleNamespace
    from twobyteasr.providers.provider_service import AIClient
    from twobyteasr.providers.ai_providers import AIProviderError
    client=object.__new__(AIClient)
    client._settings={};client._stage='polish';client._sender=None
    client._last_request_trace={'request_id':'previous','actual_cost_usd':8.5}
    def rejected(*args,**kwargs):raise AIProviderError('budget',category='request_too_large')
    client._service=SimpleNamespace(submit=rejected)
    with pytest.raises(AIProviderError):client.structured_complete([],{'type':'object'})
    assert client.invocation_trace()=={}
