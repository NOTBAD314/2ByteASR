import threading
import time
import json

import pytest

from twobyteasr.providers.llm_adapter import post_responses, get_last_llm_response_diagnostics, LLMRequestError


def test_design_json_mode_preserves_usage_without_unsupported_schema(monkeypatch):
    sent = []
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return dict(id='fixture-request', output_text='{"ok":true}',
                usage=dict(input_tokens=20, output_tokens=10, total_tokens=30))
        def close(self): pass
    monkeypatch.setattr('requests.post', lambda *a, **k: sent.append(k['json']) or Response())
    result = post_responses([dict(role='user', content=[dict(type='text',text='Return JSON.'),
        dict(type='image_url',image_url=dict(url='data:image/png;base64,fixture'))])], model='fixture', api_key='fixture',
        url='https://example.invalid/responses', max_tokens=40, json_schema={'allOf':[]}, json_mode=True)
    assert result == '{"ok":true}'
    assert sent[0]['text']['format'] == {'type':'json_object'}
    assert sent[0]['input'][0]['content'] == [dict(type='input_text',text='Return JSON.'),
        dict(type='input_image',image_url='data:image/png;base64,fixture')]
    assert get_last_llm_response_diagnostics()['total_tokens'] == 30
    assert get_last_llm_response_diagnostics()['output_delivery'] == 'json_object'


def test_responses_parent_cancel_discards_late_result_without_retry(monkeypatch):
    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    calls = []
    class Response:
        def close(self): closed.set()
    def send(*a, **k):
        calls.append(1); started.set(); release.wait(2); return Response()
    monkeypatch.setattr('requests.post', send)
    begin = time.monotonic()
    with pytest.raises(LLMRequestError) as error:
        post_responses([], model='fixture', api_key='fixture', url='https://example.invalid/responses',
            max_tokens=40, cancel_check=started.is_set, timeout=3)
    assert error.value.category == 'cancelled'
    assert time.monotonic()-begin < .5
    release.set()
    assert closed.wait(1)
    assert len(calls)==1


def response_events(text='{"作品":"方块"}', status='completed'):
    final = dict(id='resp-real', status=status, output=[dict(type='message', content=[dict(type='output_text',text=text)])],
        usage=dict(input_tokens=40,output_tokens=60,total_tokens=100,output_tokens_details=dict(reasoning_tokens=12)))
    if status=='incomplete': final['incomplete_details']={'reason':'max_output_tokens'}
    return [dict(type='response.created',response=dict(id='resp-real')),
        dict(type='response.output_text.delta',delta=text),
        dict(type='response.'+status,response=final)]


def sse_packets(events):
    raw=''.join('data: '+json.dumps(event,ensure_ascii=False)+'\n\n' for event in events).encode('utf-8')
    return [raw[i:i+1] for i in range(len(raw))]


def test_responses_sse_utf8_completion_usage_and_identity():
    from twobyteasr.providers.provider_stream import responses_body
    diagnostic={}; seen=[]
    assert responses_body(sse_packets(response_events()),diagnostic,lambda *args:seen.append(args))=='{"作品":"方块"}'
    assert diagnostic['request_id']=='resp-real' and diagnostic['total_tokens']==100
    assert diagnostic['reasoning_tokens']==12 and diagnostic['completed'] is True
    assert ('delta','{"作品":"方块"}') in seen and seen[-1]==('final','')


@pytest.mark.parametrize('failure', ['missing_terminal','truncated','mismatched_text','mismatched_identity','tool'])
def test_responses_sse_never_accepts_partial_or_conflicting_body(failure):
    from twobyteasr.providers.provider_stream import responses_body,StreamProtocolError
    events=response_events(); diagnostic={}
    if failure=='missing_terminal': events.pop()
    if failure=='truncated': events=response_events(status='incomplete')
    if failure=='mismatched_text': events[-1]['response']['output'][0]['content'][0]['text']='wrong'
    if failure=='mismatched_identity': events[-1]['response']['id']='other'
    if failure=='tool': events.insert(1,dict(type='response.output_item.added',item=dict(type='function_call')))
    with pytest.raises(StreamProtocolError): responses_body(sse_packets(events),diagnostic)
    assert not diagnostic.get('completed')
    if failure=='truncated': assert diagnostic['total_tokens']==100


@pytest.mark.parametrize('streaming',[True,False])
def test_responses_single_http_request_sse_or_same_response_json(monkeypatch,streaming):
    sent=[];closed=[]
    class Response:
        status_code=200
        headers={'Content-Type':'text/event-stream' if streaming else 'application/json'}
        def iter_content(self,chunk_size):
            yield from (sse_packets(response_events()) if streaming else [json.dumps(response_events()[-1]['response']).encode()])
        def close(self):closed.append(True)
    monkeypatch.setattr('requests.post',lambda *args,**kwargs:sent.append(kwargs) or Response())
    result=post_responses([],model='fixture',api_key='fixture',url='https://example.invalid/responses',max_tokens=100,
        temperature=None,on_stream_event=lambda *_:None)
    assert result=='{"作品":"方块"}' and len(sent)==1 and closed
    assert sent[0]['json']['stream'] is True and 'temperature' not in sent[0]['json']
    assert get_last_llm_response_diagnostics()['total_tokens']==100


def test_responses_fine_grained_events_allow_overhead_but_bound_body():
    from twobyteasr.providers.provider_stream import responses_body,StreamProtocolError
    # Reproduce the measured 15k-event, >4MiB envelope with a tiny body.
    packets=response_events(text='a'*16000)
    events=[packets[0]]+[dict(type='response.output_text.delta',delta='a',obfuscation='x'*250) for _ in range(16000)]+[packets[-1]]
    raw=''.join('data: '+json.dumps(e)+'\n\n' for e in events).encode()
    diagnostic={}
    assert len(raw)>4*1024*1024
    assert responses_body([raw],diagnostic)=='a'*16000
    with pytest.raises(StreamProtocolError) as exc:
        oversized='data: '+json.dumps(dict(type='response.output_text.delta',delta='x'*(1024*1024+1)))+'\n\n'
        responses_body([oversized.encode()],{})
    assert exc.value.category=='response_too_large'
