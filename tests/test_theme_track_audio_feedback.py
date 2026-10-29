"""Behavioral regressions for September 8 manual EXE feedback."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from types import SimpleNamespace
import wave
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack, QColor
from twobyteasr.playback.audio_engine import build_audio_decode_command, build_audio_mix_command
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project, load_project
from twobyteasr.timeline.studio_track_gain import track_gain_db, gain_command, gain_amplitude
from twobyteasr.timeline.studio_media_pool import set_video_track_state
from twobyteasr.timeline.studio_edit_sequence import sequence_of
from twobyteasr.system.processes import run_hidden_subprocess

FFMPEG = Path(__file__).resolve().parents[1]/"tools/ffmpeg/bin/ffmpeg.exe"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tone(tmp_path):
    path = tmp_path/'tone.wav'
    values = np.round(np.sin(np.arange(48000)*2*np.pi*440/48000)*4000).astype('<i2')
    values[0], values[-1] = 3000, -3000
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(48000); out.writeframes(values.tobytes())
    return path, values


def decode(command):
    result = run_hidden_subprocess(command, purpose="track gain PCM regression", capture_output=True, check=True, timeout=15)
    return np.frombuffer(result.stdout, dtype='<i2').reshape(-1,2)


def test_linked_track_gain_undo_and_save_roundtrip(app, tone, tmp_path):
    project = SubtitleProject(media=StudioMedia(path=str(tone[0]), duration_ms=1000, width=160, height=90))
    project.validate()
    set_video_track_state(project,'V1',locked=False)
    sequence_of(project).video_track_locked=False
    group = project.av_track_groups[0]
    undo = QUndoStack()
    undo.push(gain_command(project, group.video_track_id, -9.5))
    assert track_gain_db(project, group.audio_track_id) == -9.5
    undo.undo(); assert track_gain_db(project, group.video_track_id) == 0.
    undo.redo()
    path = save_project(project, tmp_path/'gain.2byteproj')
    assert track_gain_db(load_project(path), group.audio_track_id) == -9.5


@pytest.mark.parametrize('rate', [1., 2., 4.])
def test_decode_preserves_requested_duration_and_first_tail_signal(tone, rate):
    command = build_audio_decode_command(FFMPEG, tone[0], source_ms=0, source_out_ms=1000, rate=rate)
    actual = decode(command)
    assert len(actual) == round(48000/rate)
    assert np.max(np.abs(actual[:int(4800/rate)])) > 1000
    assert np.max(np.abs(actual[-int(480/rate):])) > 1000
    if rate == 1:
        # The original redundant atempo=1 filter dropped a complete 1024
        # sample tail. The exact first/last markers must survive now.
        assert abs(int(actual[0,0])) > 1500
        assert abs(int(actual[-1,0])) > 1500


def test_each_mix_input_has_independent_gain(tone):
    layers = [dict(source_path=str(tone[0]), source_ms=0, source_out_ms=1000, gain_db=0.),
              dict(source_path=str(tone[0]), source_ms=0, source_out_ms=1000, gain_db=-12.)]
    mixed = decode(build_audio_mix_command(FFMPEG, layers)).astype(float)
    reference = decode(build_audio_decode_command(FFMPEG, tone[0], source_ms=0, source_out_ms=1000, rate=1.)).astype(float)
    ratio = np.sqrt(np.mean(mixed**2)/np.mean(reference**2))
    assert ratio == pytest.approx(1+gain_amplitude(-12), abs=.002)


@pytest.mark.parametrize('rate', [1., 2., 4.])
def test_gain_export_renders_the_same_amplitude(tone, tmp_path, rate):
    from twobyteasr.exports.audio_export import audio_mix_arguments
    from twobyteasr.exports.video_export import capture_video_graph
    project = SubtitleProject(media=StudioMedia(path=str(tone[0]), duration_ms=1000, width=160, height=90))
    project.validate()
    set_video_track_state(project,'V1',locked=False)
    sequence_of(project).video_track_locked=False
    project.video_tracks[0].clips[0].playback_rate = rate
    gain_command(project, project.video_tracks[0].id, -12.).redo()
    graph = capture_video_graph(project)
    duration = 1./rate
    job = SimpleNamespace(start_seconds=0., duration_seconds=duration, video_graph=graph)
    output = tmp_path/'export.mkv'
    args = audio_mix_arguments(FFMPEG, job, graph['audio_mix'])
    run_hidden_subprocess([str(FFMPEG),'-v','error','-y','-f','lavfi','-i','color=s=160x90:r=10:d=1',
        *args,'-map','0:v','-c:v','ffv1','-t',str(duration),str(output)], purpose="gain export regression", check=True, timeout=15)
    actual = decode(build_audio_decode_command(FFMPEG, output, source_ms=0, source_out_ms=round(duration*1000), rate=1.)).astype(float)
    reference = decode(build_audio_decode_command(FFMPEG, tone[0], source_ms=0, source_out_ms=1000, rate=rate)).astype(float)
    assert len(actual) == len(reference)
    assert np.max(np.abs(actual[-480:])) > 300
    assert np.sqrt(np.mean(actual**2)/np.mean(reference**2)) == pytest.approx(gain_amplitude(-12), abs=.002)


@pytest.mark.parametrize('paused,epoch,drains', [(False, 7, True), (True, 7, False), (False, 6, False)])
def test_only_natural_current_generation_end_drains(paused, epoch, drains):
    from twobyteasr.playback.audio_engine import StudioAudioEngine
    silent = []
    engine = SimpleNamespace(_draining=False, _shutdown_requested=False, _session_generation=1,
        _last_payload={'paused': paused, 'transport_generation': (epoch, 0)},
        parent=lambda: SimpleNamespace(video=SimpleNamespace(_playback_clock=SimpleNamespace(generation=7))),
        synchronize=lambda *a, **kw: silent.append(kw), _flush_sync=lambda: None)
    StudioAudioEngine.finish_playback(engine)
    assert engine._draining is drains
    assert bool(silent) is not drains


@pytest.mark.parametrize('start,rate', [(0, 1.), (10, 1.), (100, 1.), (0, 2.)])
def test_aac_priming_does_not_remove_head_or_tail(tone, tmp_path, start, rate):
    source = tmp_path/'tone.m4a'
    run_hidden_subprocess([str(FFMPEG), '-v', 'error', '-y', '-i', str(tone[0]), '-c:a', 'aac', str(source)],
                          purpose='AAC priming regression', check=True, timeout=15)
    layers = [dict(source_path=str(source), source_ms=start, source_out_ms=1000)]*2
    actual = decode(build_audio_mix_command(FFMPEG, layers, transport_rate=rate))
    assert len(actual) == round((1000-start)*48/rate)
    assert np.sqrt(np.mean(actual[-480:].astype(float)**2)) > 500


def test_fit_command_resets_canvas_geometry_without_changing_opacity():
    from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin
    stored = []
    page = SimpleNamespace(_updating_video_transform_ui=False, timeline=SimpleNamespace(playhead_ms=500),
        _selected_video_clip=lambda: (SimpleNamespace(id='V2',locked=False), SimpleNamespace(id='clip')),
        _video_transform_values_from_controls=lambda: dict(position_x=.1,scale_x=.8275,opacity=.45,fit_mode='cover'),
        _video_transform_committed=lambda t,c,v: stored.append(v), _sync_video_compositor=lambda t: None)
    StudioVideoFlowMixin._video_fit_mode_committed(page)
    assert stored[0]['scale_x'] == stored[0]['scale_y'] == 1.
    assert stored[0]['position_x'] == .5 and stored[0]['fit_mode'] == 'cover'
    assert stored[0]['opacity'] == .45


def test_three_fit_modes_produce_distinct_nonmatching_aspects():
    from twobyteasr.playback.video_compositor import layer_geometry
    sizes = [layer_geometry(1600,900,{'transform':{'fit_mode':mode}},640,480)[0].size()
             for mode in ('contain','cover','stretch')]
    assert [(s.width(),s.height()) for s in sizes] == [(1200,900),(1600,1200),(1600,900)]


def test_dark_home_cards_follow_each_theme_and_grape_is_burgundy():
    from twobyteasr.app.home_studio_entry import studio_paper_colors
    from twobyteasr.design.ui_theme import THEMES
    assert len({studio_paper_colors(t)[0] for t in THEMES.values()}) == len(THEMES)
    grape = THEMES['grape']
    assert QColor(grape.accent).red() > QColor(grape.accent).blue()
    assert QColor(grape.app_background).blue() > QColor(grape.app_background).red()
    assert QColor(grape.text_on_accent).lightnessF() > .9
