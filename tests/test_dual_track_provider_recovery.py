import os,json,copy,sys,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPixmap,QColor
from twobyteasr.providers.ai_providers import CLIProvider,AIProviderError


@pytest.fixture(autouse=True)
def isolated_provider_logs(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    monkeypatch.setenv('APPDATA',str(tmp_path/'roaming'))


def test_valid_section_bundle_ends_before_cli_eof(tmp_path):
    from twobyteasr.providers.ai_providers import GrokCLIProvider
    source=Path(__file__).parent/'fixtures/death_stranding_original.txt'
    script=tmp_path/'section_stream.py'
    script.write_text('import json,sys,time\nfrom pathlib import Path\ntext=Path(sys.argv[1]).read_text(encoding="utf8")\n'
        'print(json.dumps({"type":"stream_event","event":{"delta":{"text":text}}}),flush=True)\ntime.sleep(20)\n',encoding='utf8')
    provider=GrokCLIProvider(executable=sys.executable);start=time.monotonic()
    result=provider._run_cli_stream([sys.executable,str(script),str(source)],purpose='fixture section bundle',timeout=4,
        complete_json_early=True,on_stream_event=lambda *a:None)
    assert result==source.read_text('utf8') and time.monotonic()-start<4
    assert provider.last_timings['response_complete']


def test_cli_terminal_thinking_without_body_has_actionable_error(tmp_path):
    from twobyteasr.providers.ai_providers import GrokCLIProvider
    script=tmp_path/'empty_stream.py'
    script.write_text('import json,time\nprint(json.dumps({"type":"stream_event","event":{"delta":{"thinking":"thought"}}}),flush=True)\n'
        'print(json.dumps({"type":"result","result":""}),flush=True)\ntime.sleep(20)\n',encoding='utf8')
    provider=GrokCLIProvider(executable=sys.executable)
    with pytest.raises(AIProviderError,match='Provider 已完成思考但未返回主题正文') as failed:
        provider._run_cli_stream([sys.executable,str(script)],purpose='fixture no body',timeout=4,on_stream_event=lambda *a:None)
    assert failed.value.category=='provider_no_body'


def test_complete_assistant_replaces_partial_and_keeps_all_text_blocks():
    state={'text':'prefix','thinking':'thought'};events=[]
    CLIProvider._consume_cli_stream_line(json.dumps({'type':'assistant','message':{'stop_reason':'end_turn',
        'content':[{'type':'text','text':'full '},{'type':'text','text':'body'}]}}),state,lambda *x:events.append(x))
    assert state['text']==state['final']=='full body'
    assert state['finished'] and events[-1]==('final','full body')


def test_finished_thinking_without_body_is_explicit():
    state={'text':'','thinking':'thought'};events=[]
    CLIProvider._consume_cli_stream_line(json.dumps({'type':'stream_event','event':{'type':'content_block_stop'}}),state,lambda *x:events.append(x))
    assert events==[('thinking_end','')]
    CLIProvider._consume_cli_stream_line(json.dumps({'type':'result','result':''}),state,lambda *x:events.append(x))
    assert state['finished'] and not state['final']


@pytest.mark.parametrize('elapsed,category',[(241.,'provider_inactivity_timeout'),(901.,'provider_total_timeout')])
def test_stage_timeouts_are_distinct_and_keep_design(monkeypatch,elapsed,category):
    from tests.test_hero_theme_compiler import setup,design as make_design
    from twobyteasr.caption_design import studio_ai, web_theme_compiler
    def stalled(kwargs):
        start=web_theme_compiler.time.monotonic()
        web_theme_compiler.time.monotonic=lambda:start+elapsed
        kwargs['cancel_check']()
        raise AssertionError('deadline did not fire')
    design=make_design('b')
    project,settings,calls,traces=setup(monkeypatch,[stalled])
    settings.setdefault("models",{})["ai_design_cli_timeout_seconds"]=900
    with pytest.raises(AIProviderError) as failed:
        studio_ai.request_web_theme_design(project,'cue','北极熊',settings,resume_design=design)
    assert failed.value.category==category
    assert failed.value.design_checkpoint['selected_concept_id']=='b'


def test_subtitle_prompt_keeps_one_concept_and_has_fresh_long_stage(monkeypatch):
    from tests.test_hero_theme_compiler import setup,design as make_design,hero
    from twobyteasr.caption_design import studio_ai
    design=make_design('b')
    p,settings,calls,traces=setup(monkeypatch,[json.dumps(hero(True))])
    settings.setdefault("models",{})["ai_design_cli_timeout_seconds"]=900
    studio_ai.request_web_theme_design(p,'cue','北极熊',settings,resume_design=design)
    assert len(calls)==1 and calls[0][1]['timeout']==900
    prompt=json.loads(calls[0][0][1]['content'])
    assert prompt['selected_concept']['id']=='b'
    assert 'concepts' not in prompt and 'source' not in prompt
    assert prompt['duration_seconds']==3


@pytest.mark.parametrize('stride',[1,2,3])
def test_vector_pixel_gates_match_scalar_reference(stride):
    from twobyteasr.rendering.studio_live_canvas import _count_stroke_pixels,_pixmap_alpha_metrics
    app=QApplication.instance() or QApplication([])
    image=QImage(97,53,QImage.Format_RGBA8888)
    for y in range(image.height()):
        for x in range(image.width()):image.setPixelColor(x,y,QColor(x*19%256,y*37%256,(x+y)*13%256,(x*3+y*7)%256))
    pixmap=QPixmap.fromImage(image);canonical=pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    refs=[QColor('#FF203040'),QColor('#806090B0')];count=0;points=[]
    for y in range(0,image.height(),stride):
        for x in range(0,image.width(),stride):
            c=canonical.pixelColor(x,y)
            if c.alpha()<=40:continue
            points.append((x,y))
            count+=int(any(all(abs(a-b)<=24 for a,b in zip((c.red(),c.green(),c.blue()),(r.red(),r.green(),r.blue()))) for r in refs))
    assert _count_stroke_pixels(pixmap,['#FF203040','#806090B0'],stride=stride)==count
    result=_pixmap_alpha_metrics(pixmap,stride=stride)
    assert result['alpha']==len(points)
    xs,ys=zip(*points)
    assert result['bbox']==(min(xs),min(ys),max(xs)-min(xs)+stride,max(ys)-min(ys)+stride)


@pytest.mark.parametrize('concept',['goggle-peek','ski-slide','powder-shake'])
def test_local_polar_template_is_valid_and_marked(concept):
    from twobyteasr.caption_style.local_subtitle_theme import local_subtitle_theme
    from twobyteasr.caption_design.web_theme_compiler import code_gate
    design=json.loads((Path(__file__).parent/'fixtures/polar_bear_f38c393_concepts.json').read_text('utf-8-sig'))
    design['selected_concept_id']=concept
    theme=local_subtitle_theme(design)
    validated,_=code_gate(json.dumps(theme),'北极熊透明字幕','subtitle')
    assert 'LOCAL_FALLBACK' in validated['notes'] and '.bear' in validated['cueCss']
    assert 'display:none' in validated['stageCss'] and 'var(--wt-dur)' in validated['cueCss']
