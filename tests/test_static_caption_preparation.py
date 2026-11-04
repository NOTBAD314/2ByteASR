"""Fail at the first lost raster; preserve replay inputs and real preparation state."""
import json
import time
from pathlib import Path
from dataclasses import replace

import pytest
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt
from tests.test_static_caption_empty_pixels import fixture
from twobyteasr.exports.static_caption_export import render_static_graph


def test_first_empty_is_detected_before_rendering_later_tasks_and_is_replayable(fixture, monkeypatch):
    app, project, ffmpeg, job = fixture
    from twobyteasr.rendering import advanced_live_renderer
    calls, trace = [], []
    def blank(snapshot, *, width, height, **kwargs):
        calls.append(snapshot.cue_id)
        image=QImage(width,height,QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        return image
    monkeypatch.setattr(advanced_live_renderer, 'render_live_snapshot', blank)
    with pytest.raises(RuntimeError, match='visible-a'):
        render_static_graph(project, ffmpeg, job, trace=lambda name,data: trace.append((name,data)))
    assert calls == ['visible-a']
    artifact=next(data for name,data in trace if name=='static_caption_failure_artifact')
    folder=Path(artifact['local_artifact'])
    evidence=json.loads((folder/'failure.json').read_text('utf8'))
    assert evidence['task']['task_index']==0 and evidence['task']['stable_cue_id']=='visible-a'
    assert evidence['task']['alpha_nonzero']==0
    assert evidence['task']['resolved_font']['file']
    assert len(evidence['snapshots'])==2
    assert evidence['snapshots'][0]['snapshot']['text']=='Visible'
    assert evidence['snapshots'][1]['task_index']==1
    assert json.loads((folder/'project.json').read_text('utf8'))['cues'][0]['text']=='Visible'
    assert 'RuntimeError' in evidence['exception_chain']
    manifest=json.loads((folder.parent/'manifest.json').read_text('utf8'))
    assert manifest['caption_failure']['alpha_nonzero']==0
    assert 'Visible' not in json.dumps(manifest['caption_failure'])


def test_slow_raster_has_real_heartbeat_and_completed_cache_counts(fixture, monkeypatch):
    app, project, ffmpeg, job = fixture
    from twobyteasr.rendering import advanced_live_renderer
    original=advanced_live_renderer.render_live_snapshot
    for cue in project.cues: cue.text='Repeated text'
    def slow(*args, **kwargs):
        time.sleep(5.3)
        return original(*args, **kwargs)
    monkeypatch.setattr(advanced_live_renderer, 'render_live_snapshot', slow)
    progress=[];trace=[]
    render_static_graph(project, ffmpeg, job, progress=progress.append,trace=lambda name,data:trace.append((name,data)))
    states=[row for row in progress if 'static_total' in row]
    assert any(row['static_step']=='raster' and float(row['static_task_elapsed_ms'])>=900 for row in states)
    assert states[-1]['static_completed']=='3' and states[-1]['static_reused']=='2'
    assert states[-1]['static_failed']=='0'
    assert all(row['indeterminate']=='1' and 'percent' not in row for row in states)
    assert any(row['stage']=='encode' for row in progress)
    stalled=next(data for name,data in trace if name=='static_caption_wait_stacks')
    assert stalled['task_index']==0 and stalled['step']=='raster' and stalled['stacks']
    assert stalled['resources']
    count=len(progress);time.sleep(1.1)
    assert len(progress)==count


def test_screenshot_gradient_shadow_glow_remains_visible_with_automatic_canvas(fixture):
    app, project, ffmpeg, job = fixture
    style=project.styles[0]
    style.font_family='Microsoft YaHei UI'; style.font_size=43; style.bold=True
    style.outline_width=4; style.outline_color='#FF000000'
    project.style_recipes['g'].update(typography={'fontFamily':'Microsoft YaHei UI','fontSize':43,'fontWeight':700},
        outline={'width':4,'color':'#FF000000','shadow':
                 {'enabled':True,'color':'#FF000000','opacity':.35,'offset_x':5,'offset_y':5,'blur':2}},
        effects={'glow':{'enabled':True,'color':'#FF000000','radius':5,'opacity':1}})
    project.style_recipes['g']['colors']['fill']={'type':'linear-gradient','angle':0,'stops':[
        {'position':0,'color':'#FFFFDF62'},{'position':1,'color':'#FFFF599F'}]}
    for index,cue in enumerate(project.cues):cue.text=('used', "driver updates or something", '字幕颜色配置')[index]
    job=replace(job,settings=replace(job.settings,width=0,height=0),
                export_context={'caption_canvas':{'output':[1920,1080]}})
    render_static_graph(project,ffmpeg,job)
    import av
    frames=list(av.open(job.output_path).decode(video=0))
    assert len(frames)==30 and (frames[0].width,frames[0].height)==(1920,1080)
    for index in (2,14,25):
        rgb=frames[index].to_ndarray(format='rgb24').astype(int)
        assert ((rgb[:,:,0]>120)&(rgb[:,:,0]>rgb[:,:,2]+15)).sum()>10
