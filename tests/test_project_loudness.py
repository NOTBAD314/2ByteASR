from pathlib import Path
from types import SimpleNamespace
import json
import math
import subprocess
import pytest
from twobyteasr.playback.project_loudness import (match_gain, freeze_baseline, analyze_baseline, baseline_identity,
    project_gain_command, project_gain_db)
from twobyteasr.playback.audio_graph import capture_audio_graph
from twobyteasr.exports.audio_delivery import build_audio_command
from twobyteasr.exports.studio_render import RenderJob, RenderSettings
from twobyteasr.system.platform_media import ffmpeg_tool
from twobyteasr.system.processes import run_hidden_subprocess
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project, load_project


def test_matching_is_absolute_peak_limited_and_finite():
    assert match_gain(-20,-9)['gain_db']==6
    result=match_gain(-20,-3)
    assert result['gain_db']==2 and result['integrated']==-18 and result['true_peak']==-1
    assert match_gain(-10,-.5)['gain_db']==-4
    assert not match_gain(-20,80)['available']
    for value in [float('nan'),float('inf'),-float('inf')]:
        with pytest.raises(ValueError):match_gain(value,-9)


@pytest.fixture
def project(tmp_path):
    source=tmp_path/'tone.wav'
    run_hidden_subprocess([str(ffmpeg_tool()),'-v','error','-y','-f','lavfi','-i',
        'sine=frequency=997:sample_rate=48000:duration=12','-af','volume=0.5','-ac','2',str(source)],
        purpose='loudness synthetic input',check=True,capture_output=True)
    p=SubtitleProject(media=StudioMedia(path=str(source),duration_ms=12000))
    p.validate()
    for asset in p.media_pool: asset.offline=False;asset.audio_metadata={'has_audio':True,'sample_rate':48000,'channels':2}
    p.video_tracks[0].locked=False
    p.audio_tracks[0].locked=False
    return p


def test_actual_measure_match_export_remeasure_and_roundtrip(project,tmp_path):
    key, baseline=freeze_baseline(project,ffmpeg_tool())
    progress=[]
    result=analyze_baseline(ffmpeg_tool(),baseline,progress=progress.append)
    assert progress[-1]==1 and result['duration']==12
    assert -35<result['integrated']<-20 and -30<result['true_peak']<-18
    identity=baseline_identity(project)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QUndoStack
    app=QApplication.instance() or QApplication([])
    stack=QUndoStack()
    for _ in range(10):
        value=match_gain(result['integrated'],result['true_peak'])['gain_db']
        if value!=project_gain_db(project):stack.push(project_gain_command(project,value))
    assert stack.count()==1 and baseline_identity(project)==identity
    output=tmp_path/'matched.wav'
    job=RenderJob('', '',str(output),settings=RenderSettings(output_kind='audio',container='wav'),
                  start_seconds=0.,duration_seconds=12.,audio_graph=capture_audio_graph(project))
    command,rate,channels=build_audio_command(ffmpeg_tool(),job)
    run_hidden_subprocess(command,purpose='actual matched WAV export',check=True,capture_output=True)
    exported=SubtitleProject(media=StudioMedia(path=str(output),duration_ms=12000));exported.validate()
    for asset in exported.media_pool:asset.offline=False
    _, bus=freeze_baseline(exported,ffmpeg_tool())
    measured=analyze_baseline(ffmpeg_tool(),bus)
    assert abs(measured['integrated']+14)<=.5
    assert measured['true_peak']<=-1
    path=tmp_path/'saved.2byteproj';save_project(project,path);reopened=load_project(path)
    assert project_gain_db(reopened)==value
    stack.undo();assert project_gain_db(project)==0
    stack.redo();assert project_gain_db(project)==value
    project.studio_state['audio_track_gain_db']={'A1':3.}
    assert baseline_identity(project)!=identity


def test_cancel_and_silence(project):
    _, baseline=freeze_baseline(project,ffmpeg_tool())
    with pytest.raises(InterruptedError):analyze_baseline(ffmpeg_tool(),baseline,cancelled=lambda:True)
    project.audio_tracks[0].muted=True
    with pytest.raises(ValueError,match='无可听'):freeze_baseline(project,ffmpeg_tool())


def test_preview_preserves_clip_track_master_and_override(project):
    from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin
    project.audio_tracks[0].clips[0].gain_db=2.
    project.studio_state['audio_track_gain_db']={'A1':3.}
    project.studio_state['project_gain_db']=4.
    page=SimpleNamespace(project=project,_gain_preview_values={'A1':6.})
    layers=StudioVideoFlowMixin._multitrack_audio_layers(page,1000)
    assert layers[0]['gain_db']==12.  # 2 clip + 6 temporary track + 4 master
    assert capture_audio_graph(project)['segments'][0]['gain_db']==5.
    page._project_gain_preview=-1.
    assert StudioVideoFlowMixin._multitrack_audio_layers(page,1000)[0]['gain_db']==7.


def test_output_format_and_edit_changes_expire_only_baseline(project):
    identity=baseline_identity(project)
    project.studio_state['project_gain_db']=9.
    project.studio_state['monitor_volume']=18
    project.studio_state['loudness_target']=-16
    assert baseline_identity(project)==identity
    project.render_settings['output_kind']='audio';project.render_settings['audio_channels']=1
    assert baseline_identity(project)!=identity
    _,bus=freeze_baseline(project,ffmpeg_tool());assert bus['channels']==1
    identity=baseline_identity(project)
    project.video_tracks[0].clips[0].playback_rate=2.
    assert baseline_identity(project)!=identity
    for asset in project.media_pool:asset.offline=True
    with pytest.raises(ValueError,match='失联'):freeze_baseline(project,ffmpeg_tool())


def test_digital_silence_is_not_zero_lufs(project,tmp_path):
    source=tmp_path/'silent.wav'
    run_hidden_subprocess([str(ffmpeg_tool()),'-v','error','-y','-f','lavfi','-i',
        'anullsrc=r=48000:cl=stereo','-t','2',str(source)],purpose='digital silence fixture',check=True,capture_output=True)
    for asset in project.media_pool:asset.canonical_source=str(source)
    _,bus=freeze_baseline(project,ffmpeg_tool())
    with pytest.raises(ValueError,match='静音|门控'):analyze_baseline(ffmpeg_tool(),bus)
