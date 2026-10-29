"""User-facing multi-lane edit invariants; every expected value is source content."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, AudioTrack, AudioClip, save_project, load_project
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, add_video_clip, set_video_track_state
from twobyteasr.timeline.studio_media_commands import media_graph_command
from twobyteasr.timeline.studio_edit_sequence import sequence_of
from twobyteasr.timeline.studio_clip_edit import playhead_edit_command, ripple_ranges_command, reassign_clips_command, clip_edit_command


@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def project():
    p = SubtitleProject(media=StudioMedia(path='first.mp4', duration_ms=40000))
    p.validate()
    sequence_of(p).video_track_locked = p.video_tracks[0].locked = False
    asset = add_media_asset(p, 'second.mp4', duration_ms=60000)
    track = create_video_track(p, 'V2')
    add_video_clip(p, track.id, asset.asset_id, timeline_in_ms=20000, source_in_ms=10000, source_out_ms=50000)
    p.audio_tracks.append(AudioTrack('music', '独立音乐', [AudioClip('music', asset.asset_id, 0, 60000, 0, 60000)]))
    return p


def spans(p, index):
    return [(c.timeline_in_ms, c.timeline_out_ms, c.source_in_ms, c.source_out_ms) for c in p.video_tracks[index].clips]


@pytest.mark.parametrize('action,expected', [
    ('ripple_start', [[(0,20000,0,20000),(20000,30000,30000,40000)], [(20000,50000,20000,50000)]]),
    ('ripple_end', [[(0,30000,0,30000)], [(20000,30000,10000,20000),(30000,50000,30000,50000)]])])
def test_shared_interval_retains_source_content(action, expected):
    p = project()
    music = copy.deepcopy(p.audio_tracks[-1])
    before = p.to_dict()
    stack = QUndoStack()
    stack.push(playhead_edit_command(p, action, 30000))
    assert [spans(p, i) for i in range(2)] == expected
    assert p.audio_tracks[-1] == music
    for t in p.video_tracks:
        linked = [a for sound in p.audio_tracks for a in sound.clips if a.linked_video_clip_id in {c.id for c in t.clips}]
        assert len(linked) == len(t.clips)
        for c in t.clips:
            a = next(a for a in linked if a.linked_video_clip_id == c.id)
            assert (a.source_in_ms,a.source_out_ms,a.timeline_in_ms,a.timeline_out_ms) == (c.source_in_ms,c.source_out_ms,c.timeline_in_ms,c.timeline_out_ms)
    stack.undo()
    assert p.to_dict() == before
    stack.redo()
    assert [spans(p, i) for i in range(2)] == expected


def test_split_all_covering_lanes_and_boundary_noop():
    p = project()
    playhead_edit_command(p,'split',30000).redo()
    assert [len(t.clips) for t in p.video_tracks] == [2,2]
    with pytest.raises(ValueError,match='边界'):
        playhead_edit_command(p,'split',30000)
    playhead_edit_command(p,'split',45000).redo()
    assert [len(t.clips) for t in p.video_tracks] == [2,3]


def test_batch_original_timestamps_one_undo():
    p = project()
    before = p.to_dict()
    cmd = ripple_ranges_command(p,[(5000,10000),(25000,30000),(26000,29000)])
    cmd.redo()
    assert spans(p,0) == [(0,5000,0,5000),(5000,20000,10000,25000),(20000,30000,30000,40000)]
    assert spans(p,1) == [(15000,20000,10000,15000),(20000,50000,20000,50000)]
    cmd.undo()
    assert p.to_dict() == before


def test_locked_v2_gap_and_all_edits_are_atomic():
    p = project()
    media_graph_command(p,'锁定 V2',lambda w:set_video_track_state(w,'V2',locked=True)).redo()
    before = p.to_dict()
    with pytest.raises(ValueError,match='锁定'):
        clip_edit_command(p,'V2','gap',start=0,end=20000)
    with pytest.raises(ValueError,match='锁定'):
        reassign_clips_command(p,'V2','V1',[p.video_tracks[1].clips[0].id],append=True)
    assert p.to_dict() == before
    locked = copy.deepcopy(p.video_tracks[1])
    playhead_edit_command(p,'split',30000).redo()
    assert p.video_tracks[1] == locked
    assert len(p.video_tracks[0].clips) == 2


def test_linked_audio_conflict_refuses_entire_split_and_ripple():
    p = project()
    p.audio_tracks[1].locked = True
    before = p.to_dict()
    for action in ('split','ripple_start','ripple_end'):
        with pytest.raises(ValueError,match='音轨'):
            playhead_edit_command(p,action,30000)
        assert p.to_dict() == before


def test_move_to_primary_and_back_preserves_identity_settings_and_audio(tmp_path):
    p = project()
    c = p.video_tracks[1].clips[0]
    c.transform.position_x=.23
    c.effects['blendMode']='screen'
    c.playback_rate=2
    c.timeline_out_ms=40000
    from twobyteasr.projects.studio_project import sync_linked_av_contract
    sync_linked_av_contract(p)
    source = copy.deepcopy(c)
    a = next(a for a in p.audio_tracks[1].clips if a.linked_video_clip_id==c.id)
    a.gain_db=-4
    audio_id=a.id
    command=reassign_clips_command(p,'V2','V1',[c.id],append=True)
    command.redo()
    assert spans(p,0)[1] == (40000,60000,10000,50000)
    moved=p.video_tracks[0].clips[1]
    assert moved.id==source.id and moved.transform==source.transform and moved.effects==source.effects and moved.playback_rate==2
    linked=[a for t in p.audio_tracks for a in t.clips if a.linked_video_clip_id==moved.id]
    assert len(linked)==1 and linked[0].id==audio_id and linked[0].gain_db==-4
    loaded=load_project(save_project(p,tmp_path/'multi.2byteproj'))
    assert loaded.video_tracks==p.video_tracks
    assert len(sequence_of(loaded).segments)==2
    reassign_clips_command(p,'V1','V2',[moved.id],start=80000).redo()
    assert spans(p,0)==[(0,40000,0,40000)]
    assert spans(p,1)==[(80000,100000,10000,50000)]
    command.undo()
    assert p.video_tracks[1].clips[0]==source


def test_cross_lane_collision_refused_without_mutation():
    p=project();before=p.to_dict()
    with pytest.raises(ValueError,match='同轨'):
        reassign_clips_command(p,'V2','V1',[p.video_tracks[1].clips[0].id],start=10000)
    assert p.to_dict()==before


def test_multi_select_keeps_spacing():
    p=project()
    playhead_edit_command(p,'split',30000).redo()
    ids=[c.id for c in p.video_tracks[1].clips]
    clip_edit_command(p,'V2','move',clip_id=ids[-1],start=35000).redo()
    reassign_clips_command(p,'V2','V1',ids,append=True).redo()
    assert spans(p,0)[-2:] == [(40000,50000,10000,20000),(55000,85000,20000,50000)]


def test_moved_caption_owner_survives_split_save_undo_without_guessing_v2(tmp_path):
    from twobyteasr.projects.studio_project import StudioCue
    from twobyteasr.timeline.studio_edit_sequence import projected_cues
    p=project();p.cues=[StudioCue('voice',5000,9000,'字幕跟随')]
    old=copy.deepcopy(p.to_dict())
    command=reassign_clips_command(p,'V1','V2',[p.video_tracks[0].clips[0].id],start=70000)
    command.redo()
    assert [(c.start_ms,c.end_ms) for c in projected_cues(p)]==[(75000,79000)]
    playhead_edit_command(p,'split',77000).redo()
    loaded=load_project(save_project(p,tmp_path/'bound.2byteproj'))
    assert [(c.start_ms,c.end_ms) for c in projected_cues(loaded)]==[(75000,77000),(77000,79000)]
    command.undo()
    restored=p.to_dict()
    # Saving deliberately touches the wall-clock timestamp; crossing a second
    # must not make this edit-state/ownership regression nondeterministic.
    restored.pop('updated_at');old.pop('updated_at')
    assert restored==old


def test_empty_video_delete_preserves_independent_audio():
    from twobyteasr.timeline.studio_track_delete import DeleteTrackCommand
    p=project();c=p.video_tracks[1].clips[0]
    reassign_clips_command(p,'V2','V1',[c.id],append=True).redo()
    audio=p.audio_tracks[1]
    audio.clips.append(AudioClip('independent',c.asset_id,0,4000,90000,94000))
    before=p.to_dict()
    command=DeleteTrackCommand(p,'video','V2');command.redo()
    assert len(p.video_tracks)==1
    assert next(t for t in p.audio_tracks if t.id==audio.id).clips[0].id=='independent'
    command.undo();assert p.to_dict()==before


def test_locked_properties_and_linked_gain_refuse():
    from twobyteasr.timeline.studio_media_pool import rename_video_track,reorder_video_track
    from twobyteasr.timeline.studio_track_gain import gain_command
    p=project();set_video_track_state(p,'V2',locked=True);before=p.to_dict()
    for action in (lambda:set_video_track_state(p,'V2',enabled=False),
                   lambda:rename_video_track(p,'V2','x'),lambda:reorder_video_track(p,'V1',1),
                   lambda:gain_command(p,'A2',-10)):
        with pytest.raises(ValueError,match='锁定'):action()
        assert p.to_dict()==before


def test_recognition_instance_ownership_follows_cross_lane_and_locked_caption_rejects():
    from twobyteasr.projects.studio_project import StudioCue
    from twobyteasr.timeline.studio_edit_sequence import projected_cues
    p=project();p.cues=[StudioCue('voice',5000,9000,'识别快照',speaker_id='S1'),
                        StudioCue('independent',50000,51000,'独立字幕',speaker_id='S2')]
    p.generation_metadata['timeline_recognition']={'sequence':copy.deepcopy(sequence_of(p).to_dict())}
    ids=[p.video_tracks[0].clips[0].id];before=p.to_dict()
    with pytest.raises(ValueError,match='字幕轨道已锁定'):
        reassign_clips_command(p,'V1','V2',ids,start=70000,locked_speakers={'S1'})
    assert p.to_dict()==before
    reassign_clips_command(p,'V1','V2',ids,start=70000).redo()
    assert [(c.text,c.start_ms,c.end_ms) for c in projected_cues(p)]==[
        ('独立字幕',50000,51000),('识别快照',75000,79000)]


def test_primary_rebind_uses_source_clock_and_explicit_project_coordinate(tmp_path):
    from types import SimpleNamespace
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=MpvCanvas()
    posts=[]
    canvas.controller=SimpleNamespace(running=True,
        post_load_at=lambda path,seconds,**kw: posts.append((seconds,kw)) or True,
        post_set_speed=lambda speed:True)
    canvas._duration=1800
    canvas.set_project_time_mapping(enabled=False,source_in_ms=1500000,timeline_in_ms=0)
    assert canvas.switch_media_at_async(str(tmp_path/'deep.flv'),'',source_seconds=1500,project_ms=0)
    assert posts[0][0]==1500
    assert canvas._playback_clock.snapshot().presentation_media_ms==1500000
    assert canvas._active_seek_trace['requested_project_ms']==0
    assert canvas._active_seek_trace['project_time_ms']==0
    canvas._timer.stop();canvas._sync_timer.stop();canvas.controller=None


def test_secondary_deep_source_seek_is_not_clamped_to_project_duration():
    from types import SimpleNamespace
    from twobyteasr.studio.studio_video_canvas import MpvCanvas
    canvas=MpvCanvas();posts=[]
    canvas.controller=SimpleNamespace(running=True,post_seek=lambda seconds,**kw:posts.append(seconds) or True)
    canvas._duration=25
    canvas.set_project_time_mapping(enabled=True,source_in_ms=600000,timeline_in_ms=10000)
    canvas.seek(605,project_ms=15000)
    assert posts==[605]
    assert canvas._playback_clock.snapshot().presentation_media_ms==15000
    canvas._timer.stop();canvas._sync_timer.stop();canvas.controller=None


@pytest.mark.parametrize('buffered,startup,requested,expected',[
    (True,'READY',False,False),(False,'MEDIA_OPENING',True,False),(False,'READY',False,True)])
def test_late_source_rebind_preserves_pending_play_request(buffered,startup,requested,expected):
    from types import SimpleNamespace
    from twobyteasr.studio.studio_video_flow import StudioVideoFlowMixin
    pauses=[]
    page=SimpleNamespace(video=SimpleNamespace(_paused=True,_buffered_play_pending=buffered,
        _startup_state=startup,_startup_play_requested=requested,set_paused=pauses.append),
        _maybe_apply_av_sync_map=lambda:None,
        _activate_multitrack_preview=lambda ms:({'switch_seek_posted':True},True))
    StudioVideoFlowMixin._sync_multitrack_preview_at(page,0)
    assert pauses==[expected]
