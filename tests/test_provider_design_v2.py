import base64
import io
import json
from PIL import Image
from twobyteasr.providers.ai_providers import CLIProvider,GrokCLIProvider


def test_tool_use_message_is_not_final_then_real_answer_completes():
    state={'text':'','thinking':'','final':None,'finished':False};events=[]
    def consume(value):CLIProvider._consume_cli_stream_line(json.dumps(value),state,lambda *x:events.append(x))
    consume({'type':'stream_event','event':{'type':'message_start'}})
    consume({'type':'stream_event','event':{'type':'content_block_delta','delta':{'text':'先尝试工具'}}})
    consume({'type':'stream_event','event':{'type':'content_block_start','content_block':{'type':'tool_use','name':'read_file'}}})
    consume({'type':'stream_event','event':{'type':'message_delta','delta':{'stop_reason':'tool_use'}}})
    consume({'type':'stream_event','event':{'type':'message_stop'}})
    consume({'type':'assistant','message':{'stop_reason':'tool_use','content':[{'type':'text','text':'先尝试工具'},{'type':'tool_use','name':'read_file'}]}})
    assert not state['finished'] and not state['final']
    assert not any(kind=='final' for kind,value in events)
    consume({'type':'stream_event','event':{'type':'message_start'}})
    consume({'type':'assistant','message':{'stop_reason':'end_turn','content':[{'type':'text','text':'{"brief":{}}'}]}})
    assert state['finished'] and state['final']=='{"brief":{}}'


def test_grok_screenshot_uses_acp_image_block_and_bounded_command():
    image=Image.new('RGBA',(960,540),(0,0,0,0));stream=io.BytesIO();image.save(stream,format='PNG')
    provider=GrokCLIProvider(executable='grok.exe',model='grok-4.6')
    prompt,blocks=provider._image_prompt([{'role':'user','content':[{'type':'text','text':'只修镜片遮字'},
        {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()}}]}])
    assert 'base64' not in prompt and blocks[1]['type']=='image' and blocks[1]['mimeType']=='image/jpeg'
    assert len(json.dumps(blocks))<28500
    assert provider.runtime_capabilities()['vision']


def test_theme_inline_markers_preserve_values_and_normal_multiline():
    from twobyteasr.caption_design.web_theme import parse_web_theme_sections
    for separator in ('','\n'):
        result=parse_web_theme_sections('===NAME==='+separator+'雪绒\n===PALETTE==='+separator+'primary=#FFFFFF text=#AABBCC\n===CUE_CSS===\n.x {opacity:1}')
        assert result['name']=='雪绒'
        assert result['palette']['text']=='#AABBCC'
        assert result['cueCss']=='.x {opacity:1}'


def test_grok_structured_result_is_the_payload_not_the_wrapper():
    from twobyteasr.providers.ai_providers import _extract_cli_text
    value={'candidates':[{'id':'A'}]}
    packet={'type':'result','result':'','structured_output':value}
    assert json.loads(_extract_cli_text(json.dumps(packet)))==value
    state={'text':'','thinking':'','finished':False};events=[]
    CLIProvider._consume_cli_stream_line(json.dumps(packet),state,lambda *x:events.append(x))
    assert json.loads(state['final'])==value and state['terminal_result']


def test_thinking_message_end_waits_for_structured_result(tmp_path,monkeypatch):
    import sys
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    script=tmp_path/'late_structured_result.py'
    script.write_text('import json,time\n'
        'print(json.dumps({"type":"stream_event","event":{"type":"content_block_delta","delta":{"thinking":"fixture"}}}),flush=True)\n'
        'print(json.dumps({"type":"stream_event","event":{"type":"message_stop"}}),flush=True)\n'
        'time.sleep(.25)\n'
        'print(json.dumps({"type":"result","result":"","structured_output":{"name":"actual body"}}),flush=True)\n',encoding='utf8')
    provider=GrokCLIProvider(executable=sys.executable)
    result=provider._run_cli_stream([sys.executable,str(script)],purpose='fixture late structured body',timeout=3,on_stream_event=lambda *a:None)
    assert json.loads(result)=={'name':'actual body'}
