"""Video edit invariants: authored clocks, atomic linked graphs, and recovery."""
import copy
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, load_project
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track, add_video_clip
from twobyteasr.timeline.studio_edit_sequence import sequence_of, projected_cues, timeline_duration_ms
from twobyteasr.timeline.studio_clip_edit import clip_edit_command, lane_gap
from twobyteasr.timeline.clip_time_mapper import project_to_source


@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def project():
    p = SubtitleProject(media=StudioMedia(path='long.mp4', duration_ms=3600000),
        cues=[StudioCue('cross', 1799000, 1801000, '人工跨界', speaker_id='S1'),
              StudioCue('kept', 2100000, 2102000, '人工文字', speaker_id='S1')])
    p.validate()
    p.video_tracks[0].locked = False
    sequence_of(p).video_track_locked = False
    return p


def clip(p, lane='V1', index=0):
    return next(t for t in p.video_tracks if t.id == lane).clips[index]


def edit(p, lane, action, **kwargs):
    if action != 'gap':
        kwargs.setdefault('clip_id', clip(p, lane).id)
    command = clip_edit_command(p, lane, action, **kwargs)
    command.redo()
    return command


def add_v2(p):
    a = add_media_asset(p, 'overlay.mp4', duration_ms=60000)
    t = create_video_track(p, 'V2')
    add_video_clip(p, t.id, a.asset_id, timeline_in_ms=5000)
    return t.id


def assert_linked(p, lane='V1'):
    group = next(g for g in p.av_track_groups if g.video_track_id == lane)
    audio = next(a for a in p.audio_tracks if a.id == group.audio_track_id)
    for c in next(t for t in p.video_tracks if t.id == lane).clips:
        sound = next(a for a in audio.clips if a.linked_video_clip_id == c.id)
        assert (sound.source_in_ms, sound.source_out_ms, sound.timeline_in_ms, sound.timeline_out_ms) == (c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms)
    if lane == 'V1':
        assert [(s.id, s.source_in_ms, s.source_out_ms, s.timeline_in_ms, s.timeline_out_ms) for s in sequence_of(p).segments] == [(c.id, c.source_in_ms, c.source_out_ms, c.timeline_in_ms, c.timeline_out_ms) for c in p.video_tracks[0].clips]


@pytest.mark.parametrize('lane', ['V1','V2'])
def test_move_split_trim_undo_reopen(tmp_path, lane):
    p = project()
    add_v2(p)
    original_cues = copy.deepcopy(p.cues)
    c = clip(p, lane)
    c.transform.position_x = .2
    c.effects['blendMode'] = 'screen'
    c.audio_enabled = False
    duration = c.timeline_out_ms - c.timeline_in_ms
    original_source = (c.source_in_ms, c.source_out_ms, c.playback_rate)
    stack = QUndoStack()
    command = clip_edit_command(p, lane, 'move', clip_id=c.id, start=20000)
    stack.push(command)
    c = clip(p, lane)
    assert (c.source_in_ms, c.source_out_ms, c.playback_rate) == original_source
    assert c.timeline_out_ms == 20000 + duration
    assert_linked(p, lane)
    edit(p, lane, 'split', time_ms=25000)
    edit(p, lane, 'split', clip_id=clip(p, lane, 1).id, time_ms=30000)
    pieces = next(t for t in p.video_tracks if t.id == lane).clips
    assert len(pieces) == 3
    assert all(c.transform.position_x == .2 and c.effects['blendMode'] == 'screen' and not c.audio_enabled for c in pieces)
    assert pieces[0].source_out_ms == pieces[1].source_in_ms
    assert pieces[1].source_out_ms == pieces[2].source_in_ms
    assert_linked(p, lane)
    saved = load_project(save_project(p, tmp_path / 'edit.2byteproj'))
    assert saved.video_tracks == p.video_tracks
    assert p.cues == original_cues == saved.cues
    command.undo()
    assert clip(p, lane).timeline_in_ms == (0 if lane == 'V1' else 5000)
    command.redo()
    assert clip(p, lane).timeline_in_ms == 20000
    assert_linked(p, lane)


def test_q_30min_w_50min_and_io(tmp_path):
    p = project()
    from twobyteasr.projects.studio_runtime_state import state_for
    runtime = state_for(p)
    original = copy.deepcopy(p.cues)
    seq = sequence_of(p)
    seq.in_point_ms, seq.out_point_ms = 1800000, 3000000
    q = edit(p, 'V1', 'ripple_start', time_ms=1800000)
    assert (clip(p).source_in_ms, clip(p).timeline_in_ms, timeline_duration_ms(p)) == (1800000, 0, 1800000)
    assert project_to_source(clip(p), 0) == 1800000
    assert runtime.cues_at(0)[0].text == '人工跨界'
    assert (sequence_of(p).in_point_ms, sequence_of(p).out_point_ms) == (0, 1200000)
    edit(p, 'V1', 'ripple_end', time_ms=1200000)
    assert (clip(p).source_in_ms, clip(p).source_out_ms, timeline_duration_ms(p)) == (1800000,3000000,1200000)
    assert p.studio_state['caption_timeline']['source_archive'] == [__import__('dataclasses').asdict(c) for c in original]
    assert [(c.start_ms,c.end_ms) for c in projected_cues(p)] == [(0,1000),(300000,302000)]
    loaded = load_project(save_project(p, tmp_path/'twenty-minutes.2byteproj'))
    assert_linked(loaded)
    assert project_to_source(clip(loaded),0) == 1800000
    q.undo()
    assert timeline_duration_ms(p) == 3600000


def test_gap_local_scope_and_nonripple_delete(tmp_path):
    p = project()
    lane = add_v2(p)
    overlay_before = copy.deepcopy(p.video_tracks[1])
    edit(p, 'V1', 'trim', start=1800000, end=3000000)
    assert lane_gap(p,'V1',1000) == (0,1800000)
    before = copy.deepcopy(p.to_dict())
    with pytest.raises(ValueError, match='在所选空隙内有素材'):
        edit(p,'V1','gap',start=0,end=1800000)
    assert p.to_dict() == before
    from twobyteasr.timeline.studio_selection import ClipSelection, delete_selection_command
    delete_selection_command(p, ClipSelection(video_ids={clip(p,lane).id})).redo()
    command = edit(p,'V1','gap',start=0,end=1800000)
    assert (clip(p).timeline_in_ms,clip(p).source_in_ms) == (0,1800000)
    assert not p.video_tracks[1].clips
    command.undo()
    assert clip(p).timeline_in_ms == 1800000
    command.redo()
    assert lane_gap(p,'V1',1200001) is None
    edit(p,'V1','split',time_ms=5000)
    edit(p,'V1','move',clip_id=clip(p,'V1',1).id,start=10000)
    c = edit(p,'V1','gap',start=5000,end=10000)
    assert clip(p,'V1',1).timeline_in_ms == 5000
    c.undo()
    assert clip(p,'V1',1).timeline_in_ms == 10000


@pytest.mark.parametrize('lock', ['video','audio'])
def test_locked_objects_reject_before_mutation(lock):
    p = project()
    if lock == 'video': p.video_tracks[0].locked=True
    if lock == 'audio': p.audio_tracks[0].locked=True
    before = p.to_dict()
    with pytest.raises(ValueError, match='锁定'):
        clip_edit_command(p,'V1','move',clip_id=clip(p).id,start=1000,
                          locked_speakers={'S1'} if lock=='subtitle' else ())
    assert p.to_dict() == before


def test_source_limits_collision_and_unrelated_gaps():
    p=project()
    edit(p,'V1','trim',start=10000,end=20000)
    edit(p,'V1','split',time_ms=15000)
    edit(p,'V1','move',clip_id=clip(p,'V1',1).id,start=30000)
    edit(p,'V1','ripple_end',time_ms=12000)
    assert [(c.timeline_in_ms,c.timeline_out_ms) for c in p.video_tracks[0].clips] == [(10000,12000),(27000,32000)]
    with pytest.raises(ValueError, match='重叠'):
        clip_edit_command(p,'V1','move',clip_id=clip(p,'V1',1).id,start=11000)
    with pytest.raises(ValueError, match='素材范围'):
        clip_edit_command(p,'V1','trim',clip_id=clip(p).id,start=0,end=4000000)


def test_recognized_independent_gap_caption_survives_primary_edit():
    p=project()
    edit(p,'V1','trim',start=0,end=1000)
    p.generation_metadata['timeline_recognition']={'sequence':copy.deepcopy(sequence_of(p).to_dict())}
    p.cues=[StudioCue('independent',3000,4000,'独立字幕')]
    edit(p,'V1','move',start=1000)
    assert [(c.start_ms,c.end_ms,c.text) for c in projected_cues(p)] == [(3000,4000,'独立字幕')]


def test_recognized_crossing_video_edge_survives_pure_split():
    p=project();edit(p,'V1','trim',start=0,end=5000)
    p.generation_metadata['timeline_recognition']={'sequence':copy.deepcopy(sequence_of(p).to_dict())}
    p.cues=[StudioCue('cross-edge',4000,6000,'跨视频边界')]
    edit(p,'V1','split',time_ms=2000)
    assert [(c.start_ms,c.end_ms,c.text) for c in projected_cues(p)] == [(4000,6000,'跨视频边界')]


def test_empty_video_preserves_own_locked_caption_track():
    p=project();original=copy.deepcopy(p.cues)
    command=clip_edit_command(p,'V1','ripple_start',clip_id=clip(p).id,time_ms=3600000,locked_speakers={'S1'})
    command.redo()
    assert not p.video_tracks[0].clips and p.cues==original
    assert command.skipped_caption_speakers=={'S1'}
    command.undo()
    edit(p,'V1','ripple_start',time_ms=3600000)
    assert not projected_cues(p) and not p.cues
    assert len(p.studio_state['caption_timeline']['source_archive'])==2


@pytest.mark.parametrize('action',['split','trim'])
def test_fractional_rate_repeated_edits_keep_endpoints(tmp_path,action):
    p=project()
    c=clip(p);c.playback_rate=2.5;c.source_out_ms=60001;c.timeline_out_ms=24000
    edit(p,'V1','move',start=0)
    for point in (1001,2002,3003,4004,5005,6006):
        c=p.video_tracks[0].clips[-1]
        edit(p,'V1',action,clip_id=c.id,**({'time_ms':point} if action=='split' else {'start':point,'end':24000}))
        assert p.video_tracks[0].clips[-1].timeline_out_ms==24000
        assert_linked(p)
    saved=load_project(save_project(p,tmp_path/'rate.2byteproj'))
    assert saved.video_tracks==p.video_tracks
    assert all(c.playback_rate==2.5 for c in saved.video_tracks[0].clips)


def test_delete_locked_caption_io_and_source_ownership():
    from types import SimpleNamespace
    from twobyteasr.timeline.studio_track_delete import DeleteTrackCommand
    p=project();edit(p,'V1','trim',start=0,end=10000)
    p.cues=[StudioCue('bound',1000,2000,'A ONLY',speaker_id='S1')]
    edit(p,'V1','split',time_ms=5000)
    page=SimpleNamespace(timeline=SimpleNamespace(locked_speakers={'S1'},playhead_ms=1000))
    # An ordinary video Delete never owns or inherits the caption lock.
    DeleteTrackCommand(p,'video','V1',page,clip_ids=[clip(p).id])
    sequence_of(p).in_point_ms=0;sequence_of(p).out_point_ms=10000
    DeleteTrackCommand(p,'video','V1',clip_ids=[clip(p,'V1',1).id]).redo()
    assert sequence_of(p).out_point_ms==5000
    add_v2(p)
    DeleteTrackCommand(p,'video','V1',clip_ids=[clip(p).id]).redo()
    assert [(c.start_ms,c.end_ms,c.text) for c in projected_cues(p)]==[(1000,2000,'A ONLY')]
    assert p.cues[0].text=='A ONLY'


def test_mapper_split_undo_returns_same_source_instance():
    from twobyteasr.timeline.studio_sequence_mapper import map_playhead_between_sequences
    p=project();before=copy.deepcopy(sequence_of(p))
    edit(p,'V1','split',time_ms=5000)
    mapped=map_playhead_between_sequences(sequence_of(p),before,7000)
    assert mapped.timeline_ms==mapped.source_ms==7000


def test_gap_preserves_unlinked_music_and_independent_caption():
    from twobyteasr.projects.studio_project import AudioTrack,AudioClip
    p=project();add_v2(p)
    edit(p,'V1','trim',start=0,end=5000)
    p.generation_metadata['timeline_recognition']={'sequence':copy.deepcopy(sequence_of(p).to_dict())}
    p.cues=[StudioCue('independent',7000,9000,'独立字幕')]
    p.audio_tracks.append(AudioTrack('music','背景音乐',[AudioClip('music-clip',p.media_pool[0].asset_id,0,10000,0,10000)]))
    before=copy.deepcopy(p.audio_tracks[-1])
    original = copy.deepcopy(p.to_dict())
    with pytest.raises(ValueError, match='在所选空隙内有素材'):
        edit(p,'V2','gap',start=0,end=5000)
    assert p.to_dict() == original
    assert p.audio_tracks[-1]==before
    assert [(c.start_ms,c.end_ms) for c in projected_cues(p)]==[(7000,9000)]
