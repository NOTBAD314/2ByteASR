import copy
import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage
from tests.test_studio_style_controller import _page, _finish
from twobyteasr.caption_style.style_recipe import FillSpec
from twobyteasr.caption_style.visual_snapshot import build_visual_cue_snapshot
from twobyteasr.rendering.advanced_live_renderer import render_live_snapshot


def test_gradient_angle_stops_alpha_change_glyph_pixels_and_cache(tmp_path,monkeypatch):
    from dataclasses import replace
    app,page=_page(tmp_path,monkeypatch)
    try:
        snap=build_visual_cue_snapshot(page.project,'a');seen=set();centers=[]
        for angle in (0,180,90,270):
            fill=dict(type='linear-gradient',angle=angle,stops=[dict(position=0,color='#FFFF0000'),dict(position=1,color='#FF00FFFF')])
            value=replace(snap,fill=fill)
            seen.add(value.pixel_hash(renderer_version='test',resolution=(960,540),device_pixel_ratio=1.))
            image=render_live_snapshot(value,width=960,height=540,layers=frozenset({'text'})).convertToFormat(QImage.Format_RGBA8888)
            a=np.asarray(image.constBits()).reshape(image.height(),image.width(),4)
            red=(a[:,:,0]>a[:,:,1]+30)&(a[:,:,3]>240)&(a[:,:,1]<100)
            cyan=(a[:,:,1]>a[:,:,0]+30)&(a[:,:,3]>240)&(a[:,:,0]<100)
            assert red.sum()>5 and cyan.sum()>5
            centers.append((np.argwhere(red).mean(0)-np.argwhere(cyan).mean(0)).tolist())
        assert len(seen)==4 and centers[0][1]<0<centers[1][1] and centers[3][0]<0<centers[2][0]
        fill['stops'].insert(1,dict(position=.4,color='#8000FF00'))
        value=replace(snap,fill=fill)
        assert value.pixel_hash(renderer_version='test',resolution=(960,540),device_pixel_ratio=1.) not in seen
        image=render_live_snapshot(value,width=960,height=540,layers=frozenset({'text'})).convertToFormat(QImage.Format_RGBA8888)
        a=np.asarray(image.constBits()).reshape(image.height(),image.width(),4)
        assert np.count_nonzero((a[:,:,1]>180)&(a[:,:,0]<100)&(a[:,:,3]>125)&(a[:,:,3]<180))>5
    finally:_finish(page)


def test_authored_motion_and_unsupported_features_keep_production_backend():
    from twobyteasr.exports.static_caption_contract import shared_static_recipe
    assert shared_static_recipe({'motion':{'mode':'none'}})
    for recipe in ({'motion':{'mode':'explicit','preset':'quick_pop'}},{'webTheme':{'html':'<div>'}},
                   {'typography':{'underline':True}}, {'visualGraph':{'motionGraph':{'tracks':[{}]}}}):
        assert not shared_static_recipe(recipe)


def test_static_gradient_real_frames_repeat_raster_and_nonzero_range(tmp_path,monkeypatch):
    import av
    from pathlib import Path
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject,SubtitleStyle
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.exports.export_timeline import write_export_ass
    from twobyteasr.exports.studio_render import RenderJob,RenderSettings
    from twobyteasr.rendering.advanced_renderer import AdvancedRendererBackend
    app=__import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication.instance()
    if app is None:app=__import__('PySide6.QtWidgets',fromlist=['QApplication']).QApplication([])
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    ffmpeg=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
    media=tmp_path/'source.mp4'
    run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=c=0x202020:s=640x360:r=60:d=3',
        '-c:v','libx264','-threads','2',str(media)],check=True,timeout=20,purpose='static caption fixture')
    project=SubtitleProject(media=StudioMedia(str(media),duration_ms=3000,width=640,height=360),
        styles=[SubtitleStyle('g','G',font_size=140)],cues=[StudioCue('a',417,933,'REPEAT',style_id='g'),StudioCue('b',1401,2100,'REPEAT',style_id='g')])
    project.style_recipes['g']={'name':'Gradient','engine':'remotion','colors':{'fill':{'type':'linear-gradient','angle':0,
        'stops':[{'position':0,'color':'#FFFF0000'},{'position':1,'color':'#FF00FFFF'}]}},'motion':{'mode':'none'}}
    project.validate()
    snapshot=write_export_ass(project,tmp_path/'p.ass',fps=60)
    job=RenderJob(str(media),str(tmp_path/'p.ass'),str(tmp_path/'burned.mp4'),
        RenderSettings(encoder='libx264',preset='ultrafast',quality=10,width=640,height=360,fps=0,audio_codec='none'),
        start_seconds=.2,duration_seconds=2.3,video_graph=capture_video_graph(project))
    trace=[]
    AdvancedRendererBackend().render(snapshot,ffmpeg,job,trace=lambda key,value:trace.append((key,value)))
    assert any(k=='static_caption_timings' for k,_ in trace)
    with av.open(job.output_path) as output:
        assert float(output.streams.video[0].average_rate)==60
    mismatches=[];onsets=[];previous=False
    for frame in av.open(job.output_path).decode(video=0):
        rgb=frame.to_ndarray(format='rgb24').astype(int)
        red=(rgb[:,:,0]>170)&(rgb[:,:,1]<80);cyan=(rgb[:,:,0]<80)&(rgb[:,:,1]>170)
        visible=red.sum()>12 and cyan.sum()>12;t=.2+float(frame.pts*frame.time_base)
        if visible and not previous:onsets.append(t)
        previous=visible
        wanted=any(c.start_ms/1000<=t<c.end_ms/1000 for c in snapshot.cues)
        if visible!=wanted:mismatches.append(min(abs(t-v/1000) for c in snapshot.cues for v in (c.start_ms,c.end_ms)))
    assert len(onsets)==2 and (not mismatches or max(mismatches)<=1/60+.00001)


def test_gradient_survives_scalar_override_edits_undo_save_and_pixels(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.project.cues[0].appearance_override={'primary_color':'#FFFF0000'}
        page.style_controller._apply_fill_spec(FillSpec.from_value({'type':'linear-gradient','angle':0,
            'stops':[{'position':0,'color':'#FFFF0000'},{'position':1,'color':'#FF00FFFF'}]}))
        snap=build_visual_cue_snapshot(page.project,'a')
        assert snap.fill['type']=='linear-gradient'
        image=render_live_snapshot(snap,width=1920,height=1080,layers=frozenset({'text'})).convertToFormat(QImage.Format_RGBA8888)
        a=np.asarray(image.constBits()).reshape((image.height(),image.width(),4))
        assert np.count_nonzero((a[:,:,0]>180)&(a[:,:,1]<100)&(a[:,:,3]>240))>10
        assert np.count_nonzero((a[:,:,0]<100)&(a[:,:,1]>180)&(a[:,:,3]>240))>10
        # Old saved documents keep their redundant scalar: rich fill wins too.
        page.project.cues[0].appearance_override['primary_color']='#FFFF0000'
        assert build_visual_cue_snapshot(page.project,'a').fill==snap.fill
        from twobyteasr.projects.studio_project import save_project,load_project
        reopened=load_project(save_project(page.project,tmp_path/'p.2byteproj'))
        assert build_visual_cue_snapshot(reopened,'a').fill==snap.fill
        page.style_controller._apply_fill_spec(FillSpec.solid('#FF00FF00'))
        assert build_visual_cue_snapshot(page.project,'a').fill['type']=='solid'
        page.undo_stack.undo();assert build_visual_cue_snapshot(page.project,'a').fill==snap.fill
        page.undo_stack.redo();assert build_visual_cue_snapshot(page.project,'a').fill['type']=='solid'
    finally:_finish(page)


def test_disc_drag_is_one_undo_with_live_direction(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        page.show();app.processEvents();disc=page.style_shadow_angle
        before=page.undo_stack.count()
        # Points on the disc's own size (72 px before 2026-10-18, 112 px since).
        center=QPoint(disc.width()//2,disc.height()//2);reach=disc.width()//2-7
        right=center+QPoint(reach,0);down=center+QPoint(0,reach)
        QTest.mousePress(disc,Qt.LeftButton,pos=right)
        assert abs(build_visual_cue_snapshot(page.project,'a').shadow['offset_y'])<.1
        QTest.mouseMove(disc,down,20)
        QTest.mouseRelease(disc,Qt.LeftButton,pos=down)
        assert disc.angle()==90 and page.style_shadow_angle_value.value()==90
        assert page.undo_stack.count()==before+1
        shadow=build_visual_cue_snapshot(page.project,'a').shadow
        assert abs(shadow['offset_x'])<.1 and shadow['offset_y']>0
        page.undo_stack.undo();page.undo_stack.redo()
        assert build_visual_cue_snapshot(page.project,'a').shadow==shadow
    finally:_finish(page)
