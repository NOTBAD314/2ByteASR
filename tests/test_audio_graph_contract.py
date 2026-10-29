"""Routing and actual PCM equivalence, including the default 0 dB path."""
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QAudioFormat
from twobyteasr.playback.audio_engine import _PcmRingDevice, AudioOutputSpec
from twobyteasr.playback.audio_graph import capture_audio_graph, preview_audio_layers
from twobyteasr.exports.audio_export import capture_audio_mix
from twobyteasr.exports.video_export import capture_video_graph
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, add_video_clip, set_audio_master_mode
from twobyteasr.timeline.studio_track_gain import gain_command

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def project(tmp_path):
    p = SubtitleProject(media=StudioMedia(path=str(tmp_path/'one.mp4'),duration_ms=2000,width=160,height=90))
    p.validate()
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    p.video_tracks[0].locked = sequence_of(p).video_track_locked = False
    asset = add_media_asset(p,tmp_path/'two.mp4',duration_ms=4000,
        video_metadata={'has_video':True,'width':160,'height':90},audio_metadata={'has_audio':True})
    track = create_video_track(p)
    add_video_clip(p,track.id,asset.asset_id,source_out_ms=2000)
    # Fixtures describe offline-independent routing; no decoder is needed here.
    for a in p.media_pool: a.offline=False
    set_audio_master_mode(p,'mix_all')
    return p

def test_default_graph_is_serializable_and_export_uses_same_segments(project):
    graph=capture_audio_graph(project)
    assert json.loads(json.dumps(graph)) == graph
    assert {x['track_id'] for x in graph['segments']} == {'V1','V2'}
    assert {x['audio_track_id'] for x in graph['segments']} == {'A1','A2'}
    assert all(x['gain_db']==0 for x in graph['segments'])
    assert capture_video_graph(project)['audio_mix'] == graph['segments']
    assert capture_audio_mix(project) == graph['segments']


@pytest.mark.parametrize('mode,selected,expected', [
    ('follow_active_video','V2',{'V1','V2'}),
    ('follow_active_video','V1',{'V1','V2'}),
    ('mix_all','V2',{'V1','V2'}),
])
def test_preview_consumes_resolved_track_selection_even_when_base_is_v1(project,mode,selected,expected):
    from twobyteasr.playback.audio_playback_graph import AudioPlaybackGraph
    set_audio_master_mode(project,mode)
    project.studio_state['selected_video_track_id']=selected
    layers=preview_audio_layers(capture_audio_graph(project),500)
    graph=AudioPlaybackGraph(master_track_id='V1')
    choice=graph.consume_resolved(layers,base_track_id='V1')
    actual=set(choice.mix_track_ids) if choice.mix_mode else {choice.audible_track_id}
    assert choice.has_owner and actual==expected
    assert {x['track_id'] for x in capture_audio_mix(project)}==expected


def test_resolved_solo_and_silence_are_not_replaced_by_visible_video(project):
    from twobyteasr.playback.audio_playback_graph import AudioPlaybackGraph
    project.studio_state['audio_solo_track_ids']=['A2']
    graph=AudioPlaybackGraph(master_track_id='V1')
    decision=graph.consume_resolved(preview_audio_layers(capture_audio_graph(project),500),base_track_id='V1')
    assert decision.audible_track_id=='V2'
    project.audio_tracks[1].muted=True
    assert not graph.consume_resolved(preview_audio_layers(capture_audio_graph(project),500),base_track_id='V1').has_owner


def test_preview_reuses_only_current_video_index_without_mutating_export(project, monkeypatch):
    from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin
    from twobyteasr.media.indexed_media import GLOBAL_INDEXED_MEDIA
    raw = str(Path(project.media_pool[0].canonical_source).with_suffix('.flv'))
    project.media_pool[0].canonical_source = raw
    canonical = capture_audio_graph(project)
    def must_not_build(*args, **kwargs):
        raise AssertionError('audio preview must not enqueue an index')
    monkeypatch.setattr(GLOBAL_INDEXED_MEDIA, 'resolve', must_not_build)
    owner = SimpleNamespace(project=project, _preview_path_project=project,
        _preview_resolved_paths={raw:raw}, _preview_indexed_paths={raw:'ready-index.mkv'})
    expected = preview_audio_layers(canonical,500)
    actual = StudioVideoFlowMixin._multitrack_audio_layers(owner,500)
    changed = [{**layer, 'source_path':'ready-index.mkv'} if layer['source_path']==raw else layer for layer in expected]
    assert actual == changed
    assert capture_audio_graph(project) == canonical
    assert capture_video_graph(project)['audio_mix'] == canonical['segments']
    owner._preview_path_project = object()
    assert StudioVideoFlowMixin._multitrack_audio_layers(owner,500) == expected
    owner._preview_path_project = project
    owner._preview_indexed_paths.clear()
    assert StudioVideoFlowMixin._multitrack_audio_layers(owner,500) == expected

def test_gain_mute_linked_solo_and_trim_share_routing(project):
    gain_command(project,'A2',-12).redo()
    second=project.video_tracks[1].clips[0]
    second.source_in_ms=500;second.source_out_ms=1500
    second.timeline_in_ms=250;second.timeline_out_ms=1250
    project.studio_state['audio_solo_track_ids']=['A2']
    graph=capture_audio_graph(project)
    layers=preview_audio_layers(graph,500)
    assert len(layers)==1 and layers[0]['track_id']=='V2'
    assert layers[0]['source_ms']==750 and layers[0]['gain_db']==-12
    assert not preview_audio_layers(graph,1500)
    project.audio_tracks[1].muted=True
    assert capture_audio_graph(project)['segments']==[]

def test_ring_has_no_qiodevice_readahead_or_preroll_and_gain_does_not_reset(app):
    spec=AudioOutputSpec(48000,2,QAudioFormat.SampleFormat.Int16,2,'s16le')
    ring=_PcmRingDevice(sample_format=spec.sample_format)
    ring.configure_mix(['V1','V2'],spec,[1.,1.])
    epoch=ring.reset_stream()
    values=np.zeros((480,2,2),dtype='<f4');values[:,0,:]=.1;values[:,1,:]=.2
    assert ring.append(values.tobytes(),epoch,threading.Event(),source_start_ms=0)
    assert ring.read(1920)==b'' and ring.consumed_bytes==0
    ring.publish_enabled=True
    pcm=np.frombuffer(ring.read(960),dtype='<i2')
    assert len(pcm)==480 and np.all(abs(pcm-9830)<=1)
    ring.set_gains({'V1':1.,'V2':0.})
    pcm=np.frombuffer(ring.read(960),dtype='<i2')
    assert ring._generation==epoch and len(pcm)==480
    assert pcm[-1]==pytest.approx(3277,abs=2)
    next_epoch=ring.reset_stream()
    assert ring.read(1920)==b''
    assert not ring.append(values.tobytes(),epoch,threading.Event())
    assert next_epoch==epoch+1

@pytest.mark.parametrize('mode',['default','positive-negative','mute','solo','linked-trim'])
def test_actual_export_range_matches_preview_pcm(app, project, tmp_path, mode):
    import wave
    from twobyteasr.playback.audio_engine import build_audio_mix_command
    from twobyteasr.exports.audio_export import audio_mix_arguments
    from twobyteasr.system.processes import run_hidden_subprocess
    ffmpeg=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
    for index,asset in enumerate(project.media_pool):
        source=tmp_path/f'tone-{index}.wav'
        t=np.arange(192000)/48000
        values=(2000*np.sin(2*np.pi*(440+index*330)*t)).astype('<i2')
        with wave.open(str(source),'wb') as f:
            f.setparams((1,2,48000,0,'NONE','not compressed'));f.writeframes(values.tobytes())
        asset.canonical_source=str(source)
    if mode=='positive-negative':
        gain_command(project,'A1',6).redo();gain_command(project,'A2',-12).redo()
    if mode=='mute':project.audio_tracks[0].muted=True
    if mode=='solo':project.studio_state['audio_solo_track_ids']=['A2']
    if mode=='linked-trim':
        from twobyteasr.timeline.studio_media_pool import trim_video_clip_edges
        clip=project.video_tracks[1].clips[0]
        trim_video_clip_edges(project,'V2',clip.id,timeline_in_ms=250,timeline_out_ms=1250)
    graph=capture_video_graph(project)
    job=SimpleNamespace(start_seconds=.5,duration_seconds=.5,video_graph=graph)
    out=tmp_path/'render.mkv'
    args=audio_mix_arguments(ffmpeg,job,graph['audio_mix'])
    run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i','color=s=160x90:r=10:d=0.5',
        *args,'-map','0:v','-c:v','ffv1','-t','0.5',str(out)],purpose='shared graph real export',check=True,timeout=20)
    layers=preview_audio_layers(capture_audio_graph(project),500)
    layers=[{**x,'source_out_ms':x['source_ms']+500} for x in layers]
    result=run_hidden_subprocess(build_audio_mix_command(ffmpeg,layers),purpose='preview reference PCM',
        capture_output=True,check=True,timeout=15)
    actual=run_hidden_subprocess([str(ffmpeg),'-v','error','-i',str(out),'-vn','-ac','2','-ar','48000','-f','s16le','pipe:1'],
        purpose='actual export PCM',capture_output=True,check=True,timeout=15)
    a=np.frombuffer(actual.stdout,dtype='<i2').astype(float)
    b=np.frombuffer(result.stdout,dtype='<i2').astype(float)
    assert len(a)==len(b)==48000
    assert np.corrcoef(a,b)[0,1]>.999
    assert np.sqrt(np.mean(a*a)/np.mean(b*b))==pytest.approx(1.,abs=.003)
