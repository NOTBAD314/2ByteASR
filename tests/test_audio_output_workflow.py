"""Disabled owner, gap, detached instance and real output PCM regressions."""
import copy
import os
import threading
import wave
from pathlib import Path
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QAudioFormat
from twobyteasr.playback.audio_graph import capture_audio_graph,preview_audio_layers,audio_graph_signature
from twobyteasr.playback.audio_engine import AudioOutputSpec,_PcmRingDevice,StudioAudioEngine,build_audio_mix_command
from twobyteasr.exports.audio_export import audio_mix_arguments
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,AudioTrack,AudioClip,sync_linked_av_contract,save_project,load_project
from twobyteasr.timeline.studio_media_pool import add_media_asset,create_video_track,add_video_clip
from twobyteasr.timeline.studio_edit_sequence import sequence_of
from twobyteasr.timeline.studio_clip_edit import clip_edit_command
from twobyteasr.timeline.studio_track_delete import DeleteTrackCommand
from twobyteasr.system.processes import run_hidden_subprocess
FFMPEG=Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'

@pytest.fixture(scope='module',autouse=True)
def app():return QApplication.instance() or QApplication([])

@pytest.fixture
def project(tmp_path):
    for name,freq in [('v1',440),('v2',880)]:
        values=(2400*np.sin(np.arange(48000*6)*2*np.pi*freq/48000)).astype('<i2')
        with wave.open(str(tmp_path/(name+'.wav')),'wb') as out:
            out.setparams((1,2,48000,0,'NONE',''));out.writeframes(values.tobytes())
    p=SubtitleProject(media=StudioMedia(str(tmp_path/'v1.wav'),duration_ms=6000,width=160,height=90));p.validate()
    p.video_tracks[0].locked=False;sequence_of(p).video_track_locked=False
    p.media_pool[0].audio_metadata['has_audio']=True
    a=add_media_asset(p,tmp_path/'v2.wav',duration_ms=6000,video_metadata={'has_video':True},audio_metadata={'has_audio':True})
    v=create_video_track(p);add_video_clip(p,v.id,a.asset_id,source_out_ms=6000)
    p.video_tracks[0].enabled=False;sync_linked_av_contract(p)
    return p

def gap(p):
    lane=p.video_tracks[1];command=clip_edit_command(p,lane.id,'split',clip_id=lane.clips[0].id,time_ms=2000);command.redo()
    lane=p.video_tracks[1];clip_edit_command(p,lane.id,'split',clip_id=lane.clips[-1].id,time_ms=4000).redo()
    return DeleteTrackCommand(p,'video',lane.id,clip_ids=[p.video_tracks[1].clips[1].id])

def owners(p,t):return {(x['track_id'],x['clip_id']) for x in preview_audio_layers(capture_audio_graph(p),t)}

def test_linked_gap_silences_disabled_owner_and_reopen_undo(project,tmp_path):
    p=project;before=copy.deepcopy(p.video_tracks[0]);stack=QUndoStack();stack.push(gap(p))
    assert owners(p,1000) and not owners(p,3000) and owners(p,5000)
    group=next(g for g in p.av_track_groups if g.video_track_id=='V2')
    sound=next(t for t in p.audio_tracks if t.id==group.audio_track_id)
    assert [(c.timeline_in_ms,c.timeline_out_ms) for c in sound.clips]==[(0,2000),(4000,6000)]
    assert p.video_tracks[0]==before
    saved=load_project(save_project(p,tmp_path/'gap.2byteproj'))
    assert not saved.video_tracks[0].enabled and not owners(saved,3000)
    stack.undo();assert {t for t,c in owners(p,3000)}=={'V2'}
    stack.redo();assert not owners(p,3000)

@pytest.mark.parametrize('kind',['separate','same-linked-lane','detached'])
def test_same_source_independent_audio_keeps_own_output(project,kind):
    p=project;gap(p).redo()
    if kind=='detached':p.av_track_groups[0].linked=False
    else:
        clip=AudioClip('music',p.media_pool[0].asset_id,source_out_ms=6000,timeline_out_ms=6000)
        if kind=='same-linked-lane':p.audio_tracks[0].clips.append(clip)
        else:p.audio_tracks.append(AudioTrack('BGM','Music',clips=[clip]))
    layers=preview_audio_layers(capture_audio_graph(p),3000)
    assert len(layers)==1 and layers[0]['source_path']==p.media.path
    assert layers[0]['track_id']==('A1' if kind!='separate' else 'BGM')
    assert layers[0]['audio_only_source']
    next(t for t in p.audio_tracks if t.id==layers[0]['audio_track_id']).muted=True
    assert not owners(p,3000)

@pytest.mark.parametrize('flag',['track','clip','clip-audio','sound','sound-clip','mute'])
def test_instance_output_flags_and_lock_are_separate(project,flag):
    p=project;t=p.video_tracks[1];c=t.clips[0];a=p.audio_tracks[1]
    t.locked=True;a.locked=True
    assert {owner for owner,_ in owners(p,3000)}=={'V2'}
    before=audio_graph_signature(p)
    if flag=='track':t.enabled=False
    if flag=='clip':c.enabled=False
    if flag=='clip-audio':c.audio_enabled=False
    if flag=='sound':a.enabled=False
    if flag=='sound-clip':a.clips[0].enabled=False
    if flag=='mute':t.muted=True
    assert audio_graph_signature(p)!=before and not owners(p,3000)


def test_missing_owned_audio_does_not_fall_back_and_link_signature_changes(project):
    p=project;p.audio_tracks[1].clips.clear()
    assert not owners(p,1000)
    p.audio_tracks[1].clips.append(AudioClip('independent',p.media_pool[0].asset_id,source_out_ms=6000,timeline_out_ms=6000))
    before=audio_graph_signature(p);p.audio_tracks[1].clips[0].linked_video_clip_id=p.video_tracks[1].clips[0].id
    assert audio_graph_signature(p)!=before


def test_overlapping_audio_instances_keep_distinct_gain_lanes(project):
    p=project;p.video_tracks[1].enabled=False
    p.audio_tracks.append(AudioTrack('BGM','Music',clips=[AudioClip('quiet',p.media_pool[0].asset_id,source_out_ms=6000,timeline_out_ms=6000,gain_db=-12),AudioClip('loud',p.media_pool[0].asset_id,source_out_ms=6000,timeline_out_ms=6000,gain_db=0)]))
    layers=preview_audio_layers(capture_audio_graph(p),1000)
    assert {c['clip_id'] for c in layers}=={'quiet','loud'}
    ring=_PcmRingDevice();spec=AudioOutputSpec(48000,2,QAudioFormat.SampleFormat.Int16,2,'s16le')
    ring.configure_mix(['BGM','BGM'],spec,[1,1]);ring.set_gains([.25,1.])
    assert list(ring._mix_gains)==[.25,1.]
    ring.close()


def test_same_media_same_clip_id_on_other_track_invalidates_transport_epoch():
    class Signal:
        def emit(self,*args):pass
    engine=SimpleNamespace(_av_sync_map_payload=None,_draining=False,_last_source_request=None,_request_generation=0,
        _session_generation=1,_shutdown_requested=False,_flush_sync=lambda:None,parent=lambda:None)
    layer=dict(source_path='same.wav',clip_id='same-id',track_id='V1',audio_track_id='A1',source_out_ms=6000,source_ms=0)
    StudioAudioEngine.synchronize(engine,layer,audible=True,paused=True,transport_rate=1.,volume=1.)
    StudioAudioEngine.synchronize(engine,{**layer,'track_id':'V2','audio_track_id':'A2'},audible=True,paused=True,transport_rate=1.,volume=1.)
    assert engine._request_generation==1


def export_pcm(p,tmp_path):
    graph=capture_audio_graph(p);job=SimpleNamespace(start_seconds=0.,duration_seconds=6.,video_graph={'duration_ms':6000})
    movie=tmp_path/'actual.mkv'
    run_hidden_subprocess([str(FFMPEG),'-v','error','-y','-f','lavfi','-i','color=s=160x90:r=10:d=6',
        *audio_mix_arguments(FFMPEG,job,graph['segments']),'-map','0:v','-c:v','ffv1','-t','6',str(movie)],purpose='disabled owner actual export',check=True,timeout=20)
    result=run_hidden_subprocess([str(FFMPEG),'-v','error','-i',str(movie),'-vn','-ac','2','-ar','48000','-f','s16le','pipe:1'],purpose='actual exported audio samples',capture_output=True,check=True,timeout=15)
    return np.frombuffer(result.stdout,'<i2').reshape(-1,2)

@pytest.mark.parametrize('background',[False,True])
def test_actual_export_gap_and_preview_share_sources(project,tmp_path,background):
    p=project;gap(p).redo()
    if background:p.audio_tracks.append(AudioTrack('BGM','Same source music',clips=[AudioClip('music',p.media_pool[0].asset_id,source_out_ms=6000,timeline_out_ms=6000)]))
    actual=export_pcm(p,tmp_path);assert len(actual)==6*48000
    window=actual[round(2.2*48000):round(3.8*48000)].astype(float)
    rms=float(np.sqrt(np.mean(window**2)))
    assert rms>1000 if background else rms==0
    layers=preview_audio_layers(capture_audio_graph(p),2500)
    assert {x['track_id'] for x in layers}==({'BGM'} if background else set())
    if background:
        ref=run_hidden_subprocess(build_audio_mix_command(FFMPEG,[{**x,'source_out_ms':3000} for x in layers]),purpose='same-source music preview PCM',capture_output=True,check=True,timeout=15)
        expected=np.frombuffer(ref.stdout,'<i2').reshape(-1,2)
        assert np.max(abs(actual[2500*48:3000*48].astype(int)-expected.astype(int)))<=1


@pytest.mark.parametrize('rate',[1.,2.])
def test_real_equal_power_transition_preview_export_and_seek(project,tmp_path,rate):
    from twobyteasr.projects.studio_project import VideoClip
    from twobyteasr.timeline.studio_transitions import set_transition,transition_gain
    p=project;t=p.video_tracks[1]
    t.clips=[VideoClip('left',t.clips[0].asset_id,source_out_ms=2000,timeline_out_ms=2000),
             VideoClip('right',p.media_pool[0].asset_id,source_in_ms=1000,source_out_ms=3000,timeline_in_ms=2000,timeline_out_ms=4000)]
    sync_linked_av_contract(p);a=p.audio_tracks[1]
    a.clips[0].gain_db=-6;a.clips[1].gain_db=-12
    transition=set_transition(p,'audio',a.id,a.clips[0].id,a.clips[1].id,duration_ms=500)
    original=copy.deepcopy(t.clips)
    graph=capture_audio_graph(p);layers=preview_audio_layers(graph,1900)
    assert len(layers)==2 and t.clips==original
    assert len({x['audio_clip_id'] for x in layers})==2
    assert all(x['audio_envelopes'] for x in layers)
    preview=run_hidden_subprocess(build_audio_mix_command(FFMPEG,[{**x,'source_out_ms':x['source_ms']+300} for x in layers],transport_rate=rate),purpose='transition actual preview PCM',capture_output=True,check=True,timeout=15)
    reference=np.frombuffer(preview.stdout,'<i2').reshape(-1,2)
    assert len(reference)==round(300*48/rate)
    if rate==1:
        job=SimpleNamespace(start_seconds=1.9,duration_seconds=.3,video_graph={'duration_ms':4000})
        movie=tmp_path/'transition.mkv'
        run_hidden_subprocess([str(FFMPEG),'-v','error','-y','-f','lavfi','-i','color=s=160x90:r=10:d=0.3',*audio_mix_arguments(FFMPEG,job,graph['segments']),'-map','0:v','-c:v','ffv1','-t','0.3',str(movie)],purpose='actual transition export',check=True,timeout=15)
        actual=run_hidden_subprocess([str(FFMPEG),'-v','error','-i',str(movie),'-vn','-ac','2','-ar','48000','-f','s16le','pipe:1'],purpose='actual transition exported samples',capture_output=True,check=True,timeout=15)
        values=np.frombuffer(actual.stdout,'<i2').reshape(-1,2)
        assert values.shape==reference.shape and np.max(abs(values.astype(int)-reference.astype(int)))<=2
    assert transition_gain(layers[0]['audio_envelopes'],2000)==pytest.approx(2**-.5)
    reopened=load_project(save_project(p,tmp_path/'transition.2byteproj'))
    assert reopened.studio_state['clip_transitions']==p.studio_state['clip_transitions']
    assert capture_audio_graph(reopened)['segments']==graph['segments']


def test_detached_clip_id_on_other_track_cannot_suppress_linked_instance(project):
    p=project
    p.video_tracks[1].clips[0].id=p.video_tracks[0].clips[0].id
    sync_linked_av_contract(p)
    p.av_track_groups[0].linked=False
    p.audio_tracks[0].muted=True
    layers=preview_audio_layers(capture_audio_graph(p),1000)
    assert len(layers)==1 and layers[0]['track_id']=='V2'
    assert layers[0]['audio_track_id']=='A2'
