"""Production export distinguishes intentional invisibility from lost ink."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from dataclasses import replace
import av
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QFontDatabase
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
from twobyteasr.exports.studio_render import RenderJob, RenderSettings
from twobyteasr.exports.static_caption_export import render_static_graph
from twobyteasr.system.processes import run_hidden_subprocess


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    assert QFontDatabase.addApplicationFont(str(Path(__file__).resolve().parents[1]/'assets/fonts/SourceHanSansSC-Medium.otf'))>=0
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    ffmpeg=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
    media=tmp_path/'source.mp4'
    run_hidden_subprocess([ffmpeg,'-v','error','-f','lavfi','-i','color=c=0x202020:s=320x180:r=30:d=1',
                           '-c:v','libx264','-threads','2',media],check=True,timeout=30,purpose='empty caption fixture')
    project=SubtitleProject(media=StudioMedia(str(media),duration_ms=1000,width=320,height=180),
        styles=[SubtitleStyle('g','Gradient',font_size=80)],
        cues=[StudioCue('visible-a',0,300,'Visible',style_id='g'),
              StudioCue('invisible',300,600,'  \n  ',style_id='g'),
              StudioCue('visible-b',600,1000,'Next',style_id='g')])
    project.style_recipes['g']={'name':'Gradient','engine':'remotion','motion':{'mode':'none'},'colors':{
        'fill':{'type':'linear-gradient','stops':[{'position':0,'color':'#FFFF0000'},{'position':1,'color':'#FFFF0000'}]}}}
    job=RenderJob(str(media),str(tmp_path/'p.ass'),str(tmp_path/'out.mp4'),
        RenderSettings(encoder='libx264',preset='ultrafast',width=320,height=180,fps=30,audio_codec='none'),duration_seconds=1)
    return app,project,ffmpeg,job


def test_empty_display_text_keeps_visible_neighbours_and_timing(fixture):
    app,project,ffmpeg,job=fixture;trace=[]
    render_static_graph(project,ffmpeg,job,trace=lambda name,data:trace.append((name,data)))
    frames=list(av.open(job.output_path).decode(video=0))
    assert len(frames)==30
    def red(frame):
        rgb=frame.to_ndarray(format='rgb24').astype(int)
        return ((rgb[:,:,0]>100)&(rgb[:,:,0]>rgb[:,:,1]+30)).sum()
    assert red(frames[2])>5 and red(frames[14])==0 and red(frames[25])>5
    empty=[data for name,data in trace if name=='static_caption_empty']
    assert empty[0]['cue_id']=='invisible' and empty[0]['task_index']==1
    assert empty[0]['reason_code']=='empty_display_text'


def test_unexpected_empty_ink_still_fails_with_identity_and_preserves_output(fixture,monkeypatch):
    app,project,ffmpeg,job=fixture
    from twobyteasr.rendering import advanced_live_renderer
    def blank(snapshot,*,width,height,**kwargs):
        image=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent);return image
    monkeypatch.setattr(advanced_live_renderer,'render_live_snapshot',blank)
    Path(job.output_path).write_bytes(b'previous output')
    trace=[]
    with pytest.raises(RuntimeError,match='visible-a.*unexpected_empty_raster'):
        render_static_graph(project,ffmpeg,replace(job,overwrite_existing=True),trace=lambda name,data:trace.append((name,data)))
    assert Path(job.output_path).read_bytes()==b'previous output'
    detail=next(data for name,data in trace if name=='static_caption_empty')
    assert detail['output']==[320,180] and detail['dpr']==1
    assert 'text' not in detail and detail['text_length']>0


def test_explicit_transparent_style_exports_video_without_inventing_ink(fixture):
    app,project,ffmpeg,job=fixture
    for cue in project.cues:cue.text='Hidden on purpose'
    project.style_recipes['g']['colors']['fill']={'type':'solid','color':'#00FF0000'}
    project.styles[0].primary_color='#00FF0000'
    project.styles[0].outline_width=0
    project.styles[0].shadow=0
    trace=[]
    render_static_graph(project,ffmpeg,job,trace=lambda name,data:trace.append((name,data)))
    assert len(list(av.open(job.output_path).decode(video=0)))==30
    assert [data['reason_code'] for name,data in trace if name=='static_caption_empty']==['explicitly_transparent_paint']*3


def test_auto_dimensions_use_the_same_frozen_canvas_for_raster_and_video(fixture):
    app,project,ffmpeg,job=fixture
    project.media.width=project.media.height=0
    job=replace(job,settings=replace(job.settings,width=0,height=0),
                export_context={'caption_canvas':{'output':[640,360]}})
    render_static_graph(project,ffmpeg,job)
    frames=list(av.open(job.output_path).decode(video=0))
    assert len(frames)==30 and (frames[0].width,frames[0].height)==(640,360)
    rgb=frames[2].to_ndarray(format='rgb24').astype(int)
    assert ((rgb[:,:,0]>100)&(rgb[:,:,0]>rgb[:,:,1]+30)).sum()>10


def test_zero_opacity_background_is_intentionally_invisible(fixture):
    app,project,ffmpeg,job=fixture
    project.style_recipes['g']['colors']['fill']={'type':'solid','color':'#00FF0000'}
    project.style_recipes['g']['background']={'enabled':True,'color':'#FF204080','opacity':0}
    project.styles[0].primary_color='#00FF0000';project.styles[0].outline_width=0;project.styles[0].shadow=0
    trace=[]
    render_static_graph(project,ffmpeg,job,trace=lambda name,data:trace.append((name,data)))
    assert len(list(av.open(job.output_path).decode(video=0)))==30
    assert any(name=='static_caption_empty' for name,_ in trace)


def test_canvas_panel_retains_full_renderer_route():
    from twobyteasr.exports.static_caption_contract import shared_static_recipe
    assert not shared_static_recipe({'visualGraph':{'panelLayer':{'primitive':'ROUNDED_PANEL',
        'params':{'coordinateSpace':'video-canvas'}}}})
