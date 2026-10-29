import json
from pathlib import Path
import pytest
from twobyteasr.caption_design.source_artifact import frame, unframe, from_theme, to_theme
from twobyteasr.providers.ai_providers import CLIProvider


def test_raw_source_roundtrip_and_program_serialization():
    source=dict(cueHtml='<div class="刻痕" title="\\">{{text}}中文😀</div>\n',
        cueCss='.x{content:"\\\\";filter:url(#ink);background:linear-gradient(red,blue)}',
        stageCss='',motionSpec={'tracks':[]})
    artifact=from_theme(source,'request/A/v1')
    result,receipt=to_theme('\ufeff```text\n'+artifact+'\n```','request/A/v1',{'name':'铜版'})
    for key in ('cueHtml','cueCss','stageCss','motionSpec'):assert result[key]==source[key]
    assert json.loads(json.dumps(result,ensure_ascii=False))==result
    assert receipt['wrappers']==['single_code_fence']


@pytest.mark.parametrize('mutation',[
    lambda v:v.rsplit('===END',1)[0],lambda v:v+v,lambda v:'说明\n'+v,
    lambda v:v.replace('===HTML===','===CSS==='),lambda v:v.replace('===CSS===','===UNKNOWN==='),
])
def test_incomplete_or_ambiguous_artifact_rejected(mutation):
    value=frame(dict(HTML='<div>{{text}}</div>',CSS='.x{}',STAGE_CSS='',PARAMETERS='{}'),'current')
    with pytest.raises(ValueError):unframe(mutation(value),'current')
    with pytest.raises(ValueError):unframe(value,'old')


def test_cli_artifact_waits_for_success_receipt_without_structured_output():
    state=dict(text='',thinking='',final=None,require_terminal_result=True,artifact_mode=True,expected_session='current')
    def feed(packet):CLIProvider._consume_cli_stream_line(json.dumps(packet),state,lambda *a:None)
    feed({'type':'assistant','session_id':'current','message':{'stop_reason':'end_turn',
        'content':[{'type':'thinking','thinking':'private'},{'type':'text','text':'source'}]}})
    assert not state['final']
    feed({'type':'result','session_id':'current','is_error':False,'subtype':'success'})
    assert state['final']=='source' and state['terminal_result']
    feed({'type':'result','session_id':'old','result':'different'})
    assert state['terminal_category']=='provider_protocol_error'


def test_cli_failure_never_accepts_complete_assistant():
    state=dict(text='',thinking='',final=None,require_terminal_result=True,artifact_mode=True)
    for packet in [{'type':'assistant','message':{'stop_reason':'end_turn','content':[{'type':'text','text':'source'}]}},
                   {'type':'result','is_error':True,'subtype':'error_max_turns'}]:
        CLIProvider._consume_cli_stream_line(json.dumps(packet),state,lambda *a:None)
    assert state['terminal_error'] and not state['final']


def test_cli_null_message_stop_and_terminal_only_end_turn():
    state=dict(artifact_mode=True,require_terminal_result=True)
    for packet in [
        {'type':'stream_event','event':{'type':'message_start','message':{'id':'m1'}}},
        {'type':'assistant','message':{'id':'m1','stop_reason':None,'content':[{'type':'text','text':'complete'}]}},
        {'type':'result','subtype':'success','stop_reason':'end_turn','is_error':False},
    ]:CLIProvider._consume_cli_stream_line(json.dumps(packet),state,lambda *a:None)
    assert state['final']=='complete' and not state.get('terminal_error')


@pytest.mark.parametrize('packet',[
    {'type':'assistant','message':{'id':'other','content':[{'type':'text','text':'complete'}]}},
    {'type':'assistant','message':{'id':'m1','content':[{'type':'text','text':'different'}]}},
    {'type':'stream_event','event':{'type':'message_start','message':{'id':'m2'}}},
    {'type':'result','subtype':'success','stop_reason':'max_tokens','is_error':False,'result':'complete'},
    {'type':'result','subtype':'error_max_turns','is_error':False,'result':'complete'},
])
def test_cli_rejects_conflicts_and_unsuccessful_terminal(packet):
    state=dict(artifact_mode=True,require_terminal_result=True)
    CLIProvider._consume_cli_stream_line(json.dumps({'type':'assistant','message':{'id':'m1','content':[{'type':'text','text':'complete'}]}}),state,lambda *a:None)
    CLIProvider._consume_cli_stream_line(json.dumps(packet),state,lambda *a:None)
    assert state.get('terminal_error') and not state.get('final')


def test_original_direction_failure_is_not_source_or_outer_event_failure():
    body='{"MaterialContract":{"material":"皮革","selectors":[".brand-deep"]},{"material":"unused","selectors":[]}],"MotionContract":{}}'
    event=json.loads(json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':body}]}}))
    with pytest.raises(json.JSONDecodeError):json.loads(event['message']['content'][0]['text'])
