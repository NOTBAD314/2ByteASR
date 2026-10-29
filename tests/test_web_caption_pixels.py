"""Browser pixels, not an encodable transparent movie, are the HTML contract."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import pytest
from PIL import Image, ImageFont
from twobyteasr.rendering.advanced_renderer import compile_composition_data
from twobyteasr.rendering.renderer_service import RendererJob, RendererService
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, SubtitleStyle
from twobyteasr.caption_style.style_recipe import StyleRecipe
from twobyteasr.caption_design.web_theme import theme_archive_html, effective_appearance

ROOT=Path(__file__).resolve().parents[1]
TEXTS=['一二三四五六七','一二三四五六七八九十甲乙丙丁戊',
       '这是怎么做到的居然还能继续上传吗','字幕测试 Aa123，Hello！']


@pytest.fixture(scope='module')
def renderer():
    if not (ROOT/'renderer/node_modules').exists(): pytest.skip('production browser required')
    service=RendererService(ROOT/'renderer')
    yield service
    service.shutdown()


def fixture(text):
    theme=dict(name='No authored root sizing',palette={'primary':'#FFFFFF','text':'#FFFFFF'},stageHtml='',stageCss='',cueHtml='<div class="lettering">{{text}}</div>',
       cueCss='.lettering{position:absolute;left:50%;bottom:100px;transform:translateX(-50%);width:1799.2px;text-align:center;font-family:var(--wt-font);font-weight:var(--wt-weight);font-size:var(--wt-size);line-height:1.12;color:white}',
       appearance=dict(fontFamily='Source Han Sans SC Heavy',fontWeight=900,fontSize=90,bold=False,strokeWidth=0,letterSpacing=0))
    style=SubtitleStyle('default','Heavy',font_family='Source Han Sans SC Heavy',font_size=90,font_weight=900,outline_width=0,shadow=0)
    p=SubtitleProject(media=StudioMedia('fixture.mp4',width=1920,height=1080,duration_ms=2000),
        styles=[style],cues=[StudioCue('c',0,1000,text)])
    p.style_recipes['default']=StyleRecipe('test',engine='remotion',web_theme=theme).to_dict()
    p.validate()
    return p,theme


@pytest.mark.parametrize('text',TEXTS)
def test_live_and_remotion_keep_authored_face_size_and_single_line(tmp_path,renderer,text):
    p,theme=fixture(text);before=deepcopy(p.to_dict())
    props=compile_composition_data(p,width=1920,height=1080,fps=60,start_seconds=0,duration_seconds=2)
    job=RendererJob(str(tmp_path/'remotion.png'),props,30,job_kind='diagnostic')
    renderer.submit([job],timeout=90).result(100).require_job(job)
    actual=Image.open(job.output).getchannel('A').getbbox()
    assert actual is not None
    expected=ImageFont.truetype(str(ROOT/'assets/fonts/SourceHanSansSC-Heavy.otf'),90).getmask(text).getbbox()
    assert abs(actual[2]-actual[0]-(expected[2]-expected[0]))<=3
    assert actual[3]-actual[1]<100 and 800<actual[1]<1080
    renderer.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=1,auto_replay=False),width=1920,height=1080)
    png=renderer.live_frame(cue_ms=500,stage_ms=500,timeout=15)
    live=Image.open(BytesIO(png)).getchannel('A').getbbox()
    assert live is not None and max(abs(a-b) for a,b in zip(live,actual))<=2
    assert p.to_dict()==before


def test_entire_cue_and_smaller_preview_keep_geometry(tmp_path,renderer):
    p,theme=fixture(TEXTS[1])
    for width,height,frame in [(1920,1080,0),(1920,1080,59),(1920,1080,60),(960,540,30)]:
        props=compile_composition_data(p,width=width,height=height,fps=60,start_seconds=0,duration_seconds=2)
        assert props['cues'][0]['visual']['webTheme']['appearance']['fontSize']==90
        job=RendererJob(str(tmp_path/f'{width}-{frame}.png'),props,frame,job_kind='diagnostic')
        renderer.submit([job],timeout=90).result(100).require_job(job)
        box=Image.open(job.output).getchannel('A').getbbox()
        if frame==60: assert box is None
        else:
            assert box is not None
            assert abs((box[2]-box[0])-1345*width/1920)<=3
    # A narrow authored well wraps stably at its real width, retaining 90px.
    theme['cueCss']=theme['cueCss'].replace('1799.2px','700px')
    renderer.live_set(theme_archive_html(theme,sample_text=TEXTS[1],duration_seconds=1,auto_replay=False),width=1920,height=1080)
    image=Image.open(BytesIO(renderer.live_frame(cue_ms=500,stage_ms=500,timeout=15)))
    box=image.getchannel('A').getbbox()
    assert box is not None and box[2]-box[0]<=700 and box[3]-box[1]>100
    diagnostic=renderer._live_request({'type':'live_diagnostics'},timeout=15)['diagnostics']
    assert all(run['fontSize']=='90px' for run in diagnostic['semantic_text_runs'])


def test_padded_text_well_and_decorative_copy_share_readable_width(renderer):
    _,theme=fixture('')
    theme['appearance'].update(fontFamily='Cubic 11',fontWeight=400,fontSize=48)
    theme['cueHtml']='<div class="well"><div class="main" data-semantic-text="true">{{text}}</div><div class="copy" aria-hidden="true">{{text}}</div></div>'
    theme['cueCss']='.well{position:absolute;left:3%;width:94%;bottom:8%;padding:18px 50px;border:4px solid #333;overflow:hidden}.main,.copy{font-family:var(--wt-font);font-size:var(--wt-size);line-height:1.2;color:#00ff00}.copy{position:absolute;top:18px;left:50px;opacity:.1}'
    text='就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句，这是最后六个字'
    renderer.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False),width=1280,height=720)
    renderer.live_pause(cue_ms=1500,stage_ms=1500)
    d=renderer._live_request({'type':'live_diagnostics'},timeout=10)['diagnostics']
    # 94vw minus the two borders and actual horizontal padding; both the
    # reading layer and the absolute-positioned copy must wrap inside it.
    assert len(d['caption_layout']['fitted'])==2
    assert all(r['width']<=1096 for r in d['caption_layout']['fitted'])
    assert {r['lineCount'] for r in d['caption_layout']['fitted']}=={2}
    assert not d['caption_layout']['overflow']


def test_max_content_well_does_not_round_short_caption_into_two_lines(renderer):
    _,theme=fixture('')
    theme['appearance'].update(fontFamily='Cubic 11',fontWeight=400,fontSize=48)
    theme['cueHtml']='<div class="well"><div class="main">{{text}}</div></div>'
    theme['cueCss']='.well{position:absolute;left:3%;bottom:8%;width:max-content;max-width:94%;padding:1.2vh 2.2vh;border:4px solid #333}.main{font-family:var(--wt-font);font-size:var(--wt-size);line-height:1.2;color:#00ff00}'
    renderer.live_set(theme_archive_html(theme,sample_text='短句',duration_seconds=.05,auto_replay=False),width=1280,height=720)
    renderer.live_pause(cue_ms=0,stage_ms=0)
    d=renderer._live_request({'type':'live_diagnostics'},timeout=10)['diagnostics']
    assert d['caption_layout']['lineCount']==1
    assert d['caption_layout']['fitted'][0]['fontSize']==32


def test_fixed_height_well_fits_long_text_then_restores_short_size(renderer):
    _,theme=fixture('')
    theme['cueHtml']='<div class="plaque"><div class="caption" data-semantic-text="true">{{text}}</div></div>'
    theme['cueCss']='.plaque{position:absolute;left:100px;top:200px;width:600px;height:180px;overflow:hidden}.caption{position:absolute;inset:20px;display:flex;align-items:center;justify-content:center;font-family:var(--wt-font);font-size:var(--wt-size);line-height:1.2;color:white;text-align:center}'
    before=deepcopy(theme)
    text='就算这句话很长也应该完整呈现每一个中文字，不应裁掉后半句，这是最后六个字'
    renderer.live_set(theme_archive_html(theme,sample_text=text,duration_seconds=3,auto_replay=False),width=1920,height=1080)
    png=renderer.live_pause(cue_ms=1500,stage_ms=1500)
    diagnostic=renderer._live_request({'type':'live_diagnostics'},timeout=10)['diagnostics']
    layout=diagnostic['caption_layout'];box=Image.open(BytesIO(png)).getchannel('A').getbbox()
    assert not layout['overflow'] and layout['fitted'][0]['fontSize']<90
    assert box and box[1]>=220 and box[3]<=360
    assert diagnostic['cue_text'].replace('\n','')==text
    renderer.live_text(text='短句',speaker='',duration_ms=3000)
    renderer.live_pause(cue_ms=1500,stage_ms=1500)
    short=renderer._live_request({'type':'live_diagnostics'},timeout=10)['diagnostics']['caption_layout']
    assert short['fitted'][0]['fontSize']==90 and not short['overflow']
    assert theme==before


def test_theme_own_font_does_not_inherit_another_faces_weight():
    look=effective_appearance({'appearance':{'fontFamily':'Source Han Sans SC Heavy','bold':False}})
    assert look['fontWeight']==900
    other=effective_appearance({'appearance':{'fontFamily':'Microsoft YaHei UI','bold':True}},
        {'fontFamily':'Source Han Sans SC Heavy','fontWeight':900})
    assert other['fontWeight']==700


@pytest.mark.parametrize('text',['只要打PVP顺手就给他做完了','第一行\n第二行\n第三行'])
def test_long_and_explicit_lines_match_live_and_export(tmp_path,renderer,text):
    p,theme=fixture(text);p.styles[0].font_size=180
    theme['appearance']['fontSize']=180
    p.style_recipes['default']=StyleRecipe('wrapped',engine='remotion',web_theme=theme).to_dict()
    before=deepcopy(p.to_dict())
    props=compile_composition_data(p,width=1920,height=1080,fps=60,start_seconds=0,duration_seconds=2)
    job=RendererJob(str(tmp_path/'wrapped.png'),props,30,job_kind='diagnostic')
    renderer.submit([job],timeout=90).result(100).require_job(job)
    exported=Image.open(job.output).getchannel('A').getbbox()
    renderer.live_set(theme_archive_html(theme,sample_text=props['cues'][0]['text'],duration_seconds=1,auto_replay=False),width=1920,height=1080)
    live=Image.open(BytesIO(renderer.live_frame(cue_ms=500,stage_ms=500,timeout=15))).getchannel('A').getbbox()
    assert live is not None and exported is not None
    assert max(abs(a-b) for a,b in zip(live,exported))<=2
    assert exported[2]-exported[0]<=1814 and exported[3]-exported[1]>180
    assert p.to_dict()==before


def test_default_stroke_keeps_thin_pixel_font_fill(renderer):
    import numpy as np
    _,theme=fixture('这次终于找到出口了')
    theme['appearance'].update(fontFamily='Cubic 11',fontWeight=400,fontSize=58)
    theme['cueCss']+=' .lettering{-webkit-text-stroke:3px #302020;}'
    html=theme_archive_html(theme,sample_text='这次终于找到出口了',duration_seconds=1,auto_replay=False)
    counts=[]
    for suffix in ('','<style>[data-caption-text]{paint-order:normal!important}</style>'):
        renderer.live_set(html.replace('</head>',suffix+'</head>'),width=1920,height=1080)
        pixels=np.asarray(Image.open(BytesIO(renderer.live_frame(cue_ms=500,stage_ms=500,timeout=15))).convert('RGBA'))
        counts.append(int(((pixels[:,:,:3].min(axis=2)>235)&(pixels[:,:,3]>220)).sum()))
    assert counts[0]>counts[1]*2.5


def test_production_preflight_rejects_transparent_caption(tmp_path):
    from twobyteasr.rendering.web_caption_preflight import preflight_web_captions
    p,theme=fixture('字幕必须可见')
    theme['cueCss'] += '.lettering{opacity:0}'
    p.style_recipes['default']=StyleRecipe('invisible',engine='remotion',web_theme=theme).to_dict()
    props=compile_composition_data(p,width=1920,height=1080,fps=60,start_seconds=0,duration_seconds=2)
    with pytest.raises(RuntimeError,match='HTML_EMPTY_LAYER'):
        preflight_web_captions(props,ROOT/'renderer',tmp_path)
