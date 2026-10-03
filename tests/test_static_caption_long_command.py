"""Windows process limit regression through the production static renderer."""
from pathlib import Path
import subprocess

import av
import pytest

from twobyteasr.processes import run_hidden_subprocess
from twobyteasr.static_caption_export import _run_static_command


def test_file_graph_keeps_external_relative_inputs_and_callbacks(tmp_path):
    folder = tmp_path / 'stills'; folder.mkdir()
    source = Path('source.mp4')
    calls = []
    callback = lambda: False
    command = ['ffmpeg.exe', '-i', str(source), '-i', str(folder/'caption.png'),
               '-filter_complex', '[0:v][1:v]overlay[final]', '-map', '[final]', str(tmp_path/'out.mp4')]
    _run_static_command(command, folder, lambda cmd, **kw: calls.append((cmd, kw)), cancelled=callback)
    actual, options = calls[0]
    assert actual[2] == str(source.resolve()) and actual[4] == 'caption.png'
    assert options['cwd'] == folder and options['cancelled'] is callback
    assert (folder/'captions.ffgraph').read_text('utf8') == command[6]
    assert '-/filter_complex' in actual and command[6] not in actual


@pytest.mark.parametrize('direct,preview', [(False,False),(True,True)])
def test_179_static_captions_encode_beyond_old_windows_limit(tmp_path, monkeypatch, direct, preview):
    import numpy as np
    from PySide6.QtWidgets import QApplication
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, SubtitleStyle
    from twobyteasr.studio_render import RenderJob, RenderSettings
    from twobyteasr.advanced_renderer import AdvancedRendererBackend
    import twobyteasr.advanced_renderer as renderer
    from twobyteasr.video_export import capture_video_graph
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'local'))
    ffmpeg = Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
    source = tmp_path/'source.mp4'
    run_hidden_subprocess([ffmpeg, '-v','error','-f','lavfi','-i',
        'color=c=0x202020:s=320x180:r=30:d=12','-c:v','libx264','-threads','2',source],
        check=True, timeout=30, purpose='long static fixture')
    project = SubtitleProject(media=StudioMedia(str(source), duration_ms=12000,width=320,height=180),
        styles=[SubtitleStyle('g','Gradient',font_size=80)],
        cues=[StudioCue(str(i), i*67, (i+1)*67, f'C{i:03}',style_id='g') for i in range(179)])
    project.style_recipes['g'] = {'name':'Gradient','engine':'remotion','motion':{'mode':'none'},'colors':{
        'fill':{'type':'linear-gradient','angle':0,'stops':[
            {'position':0,'color':'#FFFF0000'},{'position':1,'color':'#FF00FFFF'}]}}}
    project.validate()
    previews=[]
    job=RenderJob(str(source),str(tmp_path/'p.ass'),str(tmp_path/'out.mp4'),
        RenderSettings(encoder='libx264',preset='ultrafast',width=320,height=180,fps=30,audio_codec='none'),
        start_seconds=.01,duration_seconds=11.99,
        video_graph=capture_video_graph(project) if direct else None,
        preview_callback=(lambda *args:previews.append(args)) if preview else None)
    original=renderer._run_streaming_process
    executed=[]
    def record(command, **kwargs):
        graph=Path(kwargs['cwd'])/command[command.index('-/filter_complex')+1]
        executed.append((len(subprocess.list2cmdline(command)),graph.read_text('utf8')))
        return original(command, **kwargs)
    monkeypatch.setattr(renderer,'_run_streaming_process',record)
    trace=[]
    AdvancedRendererBackend().render(project,ffmpeg,job,trace=lambda k,v:trace.append((k,v)))
    old=next(v for k,v in trace if k=='static_caption_command')
    assert len(subprocess.list2cmdline(old))>32767
    if __import__('os').name=='nt':
        with pytest.raises(OSError) as caught:
            run_hidden_subprocess(old,check=True,timeout=10,purpose='old overlong command reproduction')
        assert caught.value.winerror==206
    assert executed[0][0]<16000
    assert executed[0][1].count('overlay=')==179
    if preview:
        assert previews and '[exportpreview]' in executed[0][1]
    frames=list(av.open(job.output_path).decode(video=0))
    assert len(frames)==360
    for frame in frames[:-1]:
        rgb=frame.to_ndarray(format='rgb24').astype(int)
        assert np.count_nonzero((rgb[:,:,0]>120)&(rgb[:,:,0]>rgb[:,:,1]+30))>5
