"""Actual encodes for source-only projects, with independent pixel/PCM checks."""
from pathlib import Path

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
from twobyteasr.timeline.studio_media_pool import add_media_asset
from twobyteasr.timeline.source_selection import SourceSelection, SourceInsertCommand
from twobyteasr.exports.video_export import capture_video_graph
from twobyteasr.exports.studio_render import RenderJob, RenderSettings, run_render_job
from twobyteasr.exports.export_timeline import write_export_ass
from twobyteasr.system.processes import run_hidden_subprocess

FFMPEG=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'


@pytest.mark.parametrize('mode',['av','video','audio'])
def test_blank_project_source_modes_have_exact_picture_and_sound(tmp_path,mode):
    app=QApplication.instance() or QApplication([])
    source=tmp_path/'source.mp4'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-y','-f','lavfi','-i',
        'color=c=red:s=160x90:r=25:d=4','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=4',
        '-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=4',
        '-vf',"drawbox=color=green:t=fill:enable='between(t,1,2.999)'",'-map','0:v','-map','1:a','-map','2:a',
        '-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac',str(source)],
        purpose='source insert integration fixture',check=True,timeout=30)
    project=SubtitleProject(media=StudioMedia(''),edit_sequence={'empty_timeline':True})
    asset=add_media_asset(project,source,duration_ms=4000,video_metadata={'has_video':True,'fps':25,'width':160,'height':90},
                          audio_metadata={'has_audio':True,'streams':[{},{}]},materialize_audio=False)
    SourceInsertCommand(project,SourceSelection(asset.asset_id,1000,3000,mode,1),2000).redo()
    ass=tmp_path/'empty.ass'; write_export_ass(project,ass,fps=25)
    job=RenderJob('',str(ass),str(tmp_path/'output.mp4'),
                  RenderSettings(encoder='libx264',width=160,height=90,fps=25,audio_codec='aac',preset='ultrafast'),
                  duration_seconds=4,video_graph=capture_video_graph(project))
    run_render_job(FFMPEG,job)
    container=av.open(job.output_path); frames=list(container.decode(video=0))
    assert len(frames)==100
    before=frames[25].to_ndarray(format='rgb24').mean(axis=(0,1))
    after=frames[75].to_ndarray(format='rgb24').mean(axis=(0,1))
    assert max(before)<5
    assert max(after)<5 if mode=='audio' else after[1]>after[0]+60 and after[1]>after[2]+60
    container=av.open(job.output_path)
    if mode=='video':
        assert not container.streams.audio
    else:
        rate=container.streams.audio[0].rate
        audio=np.concatenate([frame.to_ndarray().reshape(frame.layout.nb_channels,-1).mean(axis=0)
                              for frame in container.decode(audio=0)])
        assert np.sqrt(np.mean(audio[rate//2:rate]**2))<1e-4
        selected=audio[round(rate*2.5):round(rate*3.5)]
        spectrum=np.abs(np.fft.rfft(selected*np.hanning(len(selected))))
        hz=np.fft.rfftfreq(len(selected),1/rate)[spectrum.argmax()]
        assert abs(hz-880)<2 and np.sqrt(np.mean(selected**2))>.04
