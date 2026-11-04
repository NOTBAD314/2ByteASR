"""Source ranges, stream routing and atomic non-ripple insertion contracts."""
import copy

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.projects.studio_project import (SubtitleProject, StudioMedia, StudioCue, save_project, load_project)
from twobyteasr.timeline.source_selection import (SourceSelection, SourceInsertCommand, source_state, source_boundary)
from twobyteasr.timeline.studio_media_pool import add_media_asset, create_video_track
from twobyteasr.timeline.studio_edit_sequence import sequence_of
from twobyteasr.playback.audio_graph import capture_audio_graph


def fixture_project(tmp_path):
    path = tmp_path/'source.mp4'; path.write_bytes(b'fixture')
    project = SubtitleProject(media=StudioMedia(path=''), cues=[StudioCue('keep', 1000, 3000, '不要移动')],
                              edit_sequence={'empty_timeline': True}, render_settings={'_cue_domain':'timeline'})
    project.validate()
    asset = add_media_asset(project, path, duration_ms=600000,
        video_metadata={'has_video': True, 'fps': 25},
        audio_metadata={'has_audio': True, 'streams': [{'ordinal': 0}, {'ordinal': 1}]}, materialize_audio=False)
    return project, asset


@pytest.mark.parametrize('mode,video_count,audio_count', [('av',1,1),('video',1,0),('audio',0,1)])
def test_modes_range_undo_roundtrip(tmp_path, mode, video_count, audio_count):
    app = QApplication.instance() or QApplication([])
    project, asset = fixture_project(tmp_path)
    state = source_state(project, asset.asset_id)
    state.update(in_ms=10000, out_ms=15000, position_ms=13000, stream_index=1)
    selection = SourceSelection.capture(project, asset.asset_id, mode)
    cues = copy.deepcopy(project.cues)
    before = copy.deepcopy((project.video_tracks,project.audio_tracks,project.av_track_groups))
    stack = QUndoStack(); stack.push(SourceInsertCommand(project, selection, 60000))
    videos = [c for t in project.video_tracks for c in t.clips]
    audios = [c for t in project.audio_tracks for c in t.clips]
    assert len(videos) == video_count and len(audios) == audio_count
    for clip in videos+audios:
        assert (clip.source_in_ms,clip.source_out_ms,clip.timeline_in_ms,clip.timeline_out_ms)==(10000,15000,60000,65000)
    if mode == 'av':
        assert audios[0].linked_video_clip_id == videos[0].id
        assert audios[0].link_group_id
    if audios:
        assert audios[0].stream_index == 1
        assert capture_audio_graph(project)['segments'][0]['stream_index'] == 1
    else:
        assert not capture_audio_graph(project)['segments']
    state.update(in_ms=30000, out_ms=45000)
    assert selection.source_in_ms == 10000
    assert project.cues == cues
    after = copy.deepcopy((project.video_tracks,project.audio_tracks,project.av_track_groups))
    stack.undo(); assert (project.video_tracks,project.audio_tracks,project.av_track_groups)==before
    stack.redo(); assert (project.video_tracks,project.audio_tracks,project.av_track_groups)==after
    path = tmp_path/'roundtrip.2byteproj'
    save_project(project,path); reopened=load_project(path)
    assert (reopened.video_tracks,reopened.audio_tracks,reopened.av_track_groups)==after
    assert source_state(reopened,asset.asset_id)['in_ms']==30000


def test_two_ranges_streams_collision_and_linked_lock_are_atomic(tmp_path):
    project, asset = fixture_project(tmp_path)
    a=SourceSelection(asset.asset_id,10000,15000,'av',1)
    first=SourceInsertCommand(project,a,60000); first.redo()
    video=first.placement['video_track_id']; audio=first.placement['audio_track_id']
    before=copy.deepcopy((project.video_tracks,project.audio_tracks,sequence_of(project)))
    with pytest.raises(ValueError,match='重叠'):
        SourceInsertCommand(project,a,62000,video)
    assert (project.video_tracks,project.audio_tracks,sequence_of(project))==before
    next(t for t in project.audio_tracks if t.id==audio).locked=True
    with pytest.raises(ValueError,match='锁定'):
        SourceInsertCommand(project,a,70000,video)
    next(t for t in project.audio_tracks if t.id==audio).locked=False
    SourceInsertCommand(project,SourceSelection(asset.asset_id,30000,45000,'video'),70000,video).redo()
    clips=next(t for t in project.video_tracks if t.id==video).clips
    assert [(c.source_in_ms,c.source_out_ms) for c in clips]==[(10000,15000),(30000,45000)]
    assert len(next(t for t in project.audio_tracks if t.id==audio).clips)==1
    project.validate()
    assert len(next(t for t in project.audio_tracks if t.id==audio).clips)==1


def test_pool_audio_is_not_an_implicit_timeline_edit_and_video_boundaries(tmp_path):
    project, asset = fixture_project(tmp_path)
    audio=tmp_path/'music.wav'; audio.write_bytes(b'fixture')
    before=copy.deepcopy(project.audio_tracks)
    add_media_asset(project,audio,duration_ms=10000,video_metadata={'has_video':False},
                    audio_metadata={'has_audio':True},materialize_audio=False)
    assert project.audio_tracks==before
    assert source_boundary(asset,10019)==10000
    assert source_boundary(asset,10021)==10040
    assert source_boundary(asset,600001)==600000
    state=source_state(project,asset.asset_id)
    state['in_ms']=10000
    assert SourceSelection.capture(project,asset.asset_id).source_out_ms==600000
    state.clear(); state['out_ms']=15000
    assert SourceSelection.capture(project,asset.asset_id).source_in_ms==0
    asset.audio_metadata['has_audio']=False
    assert SourceSelection.capture(project,asset.asset_id).mode=='video'
    with pytest.raises(ValueError):
        SourceSelection.capture(project,asset.asset_id,'av')


def test_primary_lane_insertion_keeps_sequence_and_subtitles(tmp_path):
    project, asset=fixture_project(tmp_path)
    create_video_track(project)
    project.video_tracks[0].locked=False
    sequence_of(project).video_track_locked=False
    command=SourceInsertCommand(project,SourceSelection(asset.asset_id,10000,15000,'video'),60000,'V1')
    command.redo()
    assert sequence_of(project).segments[0].source_in_ms==10000
    assert sequence_of(project).segments[0].timeline_in_ms==60000
    assert project.cues[0].start_ms==1000
    command.undo(); assert not sequence_of(project).segments


def test_reusing_primary_source_does_not_duplicate_legacy_captions(tmp_path):
    from twobyteasr.timeline.studio_edit_sequence import projected_cues
    path=tmp_path/'legacy.mp4'; path.write_bytes(b'fixture')
    project=SubtitleProject(media=StudioMedia(str(path),duration_ms=10000),
        cues=[StudioCue('original',1000,2000,'原字幕')])
    project.validate(); project.video_tracks[0].locked=False
    sequence_of(project).video_track_locked=False
    asset=project.media_pool[0]
    before=copy.deepcopy(project.cues)
    command=SourceInsertCommand(project,SourceSelection(asset.asset_id,0,5000,'video'),20000,'V1')
    command.redo()
    visible=projected_cues(project)
    assert len(visible)==1 and (visible[0].start_ms,visible[0].end_ms)==(1000,2000)
    command.undo(); assert project.cues==before and '_cue_domain' not in project.render_settings


def test_independent_audio_on_linked_lane_extends_sequence(tmp_path):
    from twobyteasr.timeline.studio_edit_sequence import timeline_duration_ms
    project,asset=fixture_project(tmp_path)
    command=SourceInsertCommand(project,SourceSelection(asset.asset_id,10000,15000,'av'),0)
    command.redo()
    SourceInsertCommand(project,SourceSelection(asset.asset_id,30000,45000,'audio'),10000,
                        audio_target=command.placement['audio_track_id']).redo()
    assert timeline_duration_ms(project)==25000
