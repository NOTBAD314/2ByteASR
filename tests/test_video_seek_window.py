"""Do not shorten preroll across sparse frames, unknown clocks or broken probes."""
import json
from types import SimpleNamespace
import pytest
from twobyteasr.exports.studio_render import RenderJob, RenderSettings
from twobyteasr.exports.video_seek_window import video_seek_window


@pytest.mark.parametrize('times,origin,codec,expected', [
    ([19.2,19.9,20.,20.1],0,'h264',19.),
    ([19.2,19.9,20.,20.1],0,'hevc',19.),
    ([15.,18.,21.],0,'h264',10.),
    ([19.5,20.,20.5],2,'h264',10.),
    ([19.5,20.,20.5],0,'av1',10.),
    ([float('nan'),20.],0,'h264',10.),
])
def test_packet_predecessor_and_clock_gate(monkeypatch,times,origin,codec,expected):
    import twobyteasr.system.processes as processes
    calls=[]
    def probe(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=json.dumps(dict(format=dict(start_time=str(origin)),
            streams=[dict(codec_name=codec,start_time='0')],
            packets=[dict(pts_time=str(v)) for v in times])))
    monkeypatch.setattr(processes,'run_hidden_subprocess',probe)
    job=RenderJob('input.mp4','','output.mp4',RenderSettings())
    assert video_seek_window('ffmpeg.exe',job,'input.mp4',20)==expected
    assert video_seek_window('ffmpeg.exe',job,'input.mp4',20)==expected
    assert len(calls)==1
    assert video_seek_window('ffmpeg.exe',job,'input.flv',20)==0
    assert video_seek_window('ffmpeg.exe',job,'input.mkv',20)==10


def test_optional_probe_failure_keeps_established_route(monkeypatch):
    import subprocess
    import twobyteasr.system.processes as processes
    def fail(*args,**kwargs):raise subprocess.TimeoutExpired('probe',8)
    monkeypatch.setattr(processes,'run_hidden_subprocess',fail)
    job=RenderJob('input.mp4','','output.mp4',RenderSettings())
    assert video_seek_window('ffmpeg.exe',job,'input.mp4',20)==10


def test_explicit_encoder_does_not_probe_other_vendors(monkeypatch):
    import twobyteasr.exports.studio_render as render
    calls=[]
    monkeypatch.setattr(render,'cached_encoder_choices',lambda *a:None)
    monkeypatch.setattr(render,'available_encoders',lambda *a:{'h264_nvenc','h264_amf'})
    monkeypatch.setattr(render,'probe_encoder',lambda path,name:calls.append(name) or True)
    assert render.select_encoder('ffmpeg.exe',RenderSettings(encoder='h264_nvenc'))=='h264_nvenc'
    assert calls==['h264_nvenc']


@pytest.mark.parametrize('sparse,start,fps', [(False,12.137,30000/1001),(True,11.137,24.)])
def test_shorter_seek_keeps_every_output_frame_with_long_gop_and_vfr(tmp_path,sparse,start,fps):
    from dataclasses import replace
    from twobyteasr.system.platform_media import ffmpeg_tool
    from twobyteasr.system.processes import run_hidden_subprocess
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.exports.video_export import capture_video_graph
    from twobyteasr.exports.export_filtergraph import compile_video_filtergraph
    ffmpeg=ffmpeg_tool();source=tmp_path/'long-gop.mp4'
    command=[str(ffmpeg),'-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=30:d=16']
    if sparse:command+=['-vf',r'select=not(between(t\,10\,12))','-fps_mode','vfr']
    command+=['-c:v','libx264','-preset','ultrafast','-threads','2','-g','150',str(source)]
    run_hidden_subprocess(command,purpose='long GOP / sparse VFR seek fixture',capture_output=True,check=True,timeout=30)
    project=SubtitleProject(StudioMedia(str(source),duration_ms=16000,width=320,height=180))
    job=RenderJob(str(source),'',str(tmp_path/'out.mp4'),
        RenderSettings(encoder='libx264',width=320,height=180,fps=fps,audio_codec='none'),
        start_seconds=start,duration_seconds=2.433,direct_video_graph=capture_video_graph(project))
    outputs=[]
    for mode in ['legacy','bounded']:
        current=replace(job,export_context={'video_preroll':mode})
        args=compile_video_filtergraph(ffmpeg,current,'null')
        result=run_hidden_subprocess([str(ffmpeg),'-v','error',*args,'-f','framemd5','-'],
            purpose='compare every exact seek output frame',capture_output=True,check=True,timeout=30)
        outputs.append([line for line in result.stdout.splitlines() if not line.startswith(b'#')])
    assert outputs[0]==outputs[1] and len(outputs[0])>=58
