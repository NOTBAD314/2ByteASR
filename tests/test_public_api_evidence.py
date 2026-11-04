import json
from twobyteasr.providers.public_api_response import message_evidence, observe, summary
from twobyteasr.providers import llm_adapter

def test_official_returned_fields_are_source_labelled_and_redacted():
    d=dict(endpoint='https://api.deepseek.com/v1/chat/completions',model='deepseek-v4-pro')
    observe(d,'request_started',{})
    message_evidence(dict(model='deepseek-v4-pro',choices=[dict(message=dict(content='{"ok":true}',reasoning_content='public text Bearer secret123'))]),d)
    assert d['request_sent'] and d['response_model']=='deepseek-v4-pro'
    assert 'Bearer secret123' not in d['public_reasoning']
    assert d['public_reasoning_source']=='DeepSeek API message.reasoning_content'

def test_relay_is_not_assumed_official_and_absence_is_explicit():
    d=dict(endpoint='https://relay.invalid/v1/chat/completions',model='deepseek-v4-pro')
    message_evidence(dict(choices=[dict(message=dict(content='answer',reasoning_content='private event'))]),d)
    assert not d.get('public_reasoning')
    assert d['reasoning_notice']=='此接口未返回可展示的推理内容'
    assert d['returned_reasoning_field_chars']==13
    observe(d,'reasoning_summary','server public summary')
    assert d['public_reasoning']=='server public summary'

def test_actual_stream_events_arrive_before_terminal_and_usage_is_kept(monkeypatch):
    events=[]
    class Response:
        status_code=200
        headers={'Content-Type':'text/event-stream'}
        def iter_content(self,chunk_size):
            for packet in [dict(id='real-id',model='real-model',choices=[dict(delta=dict(reasoning_content='public plan'))]),
                dict(id='real-id',choices=[dict(delta=dict(content='{"ok":true}'))]),
                dict(id='real-id',choices=[dict(delta={},finish_reason='stop')],usage=dict(total_tokens=17))]:
                yield ('data: '+json.dumps(packet)+'\n\n').encode()
            yield b'data: [DONE]\n\n'
        def close(self):pass
    monkeypatch.setattr(llm_adapter.network_policy,'post',lambda *a,**k:Response())
    monkeypatch.setattr(llm_adapter,'record_llm_invocation',lambda **k:None)
    result=llm_adapter.post_chat_completion_stream([dict(role='user',content='test')],model='deepseek-v4-pro',api_key='test-key',
        url='https://api.deepseek.com/v1/chat/completions',base_url='https://api.deepseek.com/v1',provider='deepseek',max_tokens=100,
        on_stream_event=lambda kind,value:events.append((kind,value)))
    assert result=='{"ok":true}'
    kinds=[k for k,v in events]
    assert kinds.index('request_started') < kinds.index('public_reasoning') < kinds.index('delta') < kinds.index('public_response')
    final=events[-1][1]
    assert final['response_model']=='real-model' and final['reported_usage']=={'total_tokens':17}
    assert final['last_activity_at'] and final['request_sent_at']
