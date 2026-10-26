"""Playback indexing contracts: edits/undo, boundaries, rollback and ownership."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
from twobyteasr.projects.studio_runtime_state import state_for, DirtyDomain
from twobyteasr.playback.playback_plan import playback_plan, IntervalIndex, invalidate_playback_plan
from twobyteasr.playback.audio_graph import capture_audio_graph, preview_audio_layers
from twobyteasr.timeline.studio_media_pool import (add_media_asset, create_video_track,
    add_video_clip, active_video_clips, set_audio_master_mode)
from twobyteasr.timeline.studio_media_commands import media_graph_command

@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])

@pytest.fixture
def project(tmp_path):
    p=SubtitleProject(media=StudioMedia(path=str(tmp_path/'one.mp4'),duration_ms=6000,width=160,height=90))
    p.validate()
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    p.video_tracks[0].locked=sequence_of(p).video_track_locked=False
    asset=add_media_asset(p,tmp_path/'two.mp4',duration_ms=6000,
        video_metadata={'has_video':True,'width':160,'height':90},audio_metadata={'has_audio':True})
    track=create_video_track(p)
    add_video_clip(p,track.id,asset.asset_id,source_out_ms=2000,timeline_in_ms=1000)
    add_video_clip(p,track.id,asset.asset_id,source_in_ms=2000,source_out_ms=4000,timeline_in_ms=2000)
    for asset in p.media_pool:asset.offline=False
    set_audio_master_mode(p,'mix_all')
    return p

def test_half_open_overlaps_keep_input_order():
    index=IntervalIndex([(3,8),(0,6),(5,7)],lambda x:x[0],lambda x:x[1])
    assert index.at(5)==((3,8),(0,6),(5,7))
    assert index.at(6)==((3,8),(5,7))
    assert index.at(8)==()

def test_index_matches_existing_video_and_export_audio_at_boundaries(project):
    plan=playback_plan(project)
    graph=capture_audio_graph(project)
    for ms in [0,999,1000,1999,2000,2999,3000,3999,4000,5999,6000]:
        assert [(t.id,c.id,c.source_in_ms) for t,c in plan.video_at(ms)]==[(t.id,c.id,c.source_in_ms) for t,c in active_video_clips(project,ms)]
        assert plan.audio_at(ms)==preview_audio_layers(graph,ms)
    assert plan.prewarm_at(0)[0][0]==1000
    assert plan.prewarm_at(3000)==()

@pytest.mark.parametrize('mutation', ['mute','disable','relink','speed','gain'])
def test_edits_and_undo_rebuild_current_plan(project,mutation):
    before=playback_plan(project);before_audio=before.audio_at(2500)
    def change(p):
        if mutation=='mute':p.audio_tracks[1].muted=True
        if mutation=='disable':p.video_tracks[1].enabled=False
        if mutation=='relink':p.media_pool[1].canonical_source='replacement.mp4'
        if mutation=='speed':p.video_tracks[1].clips[0].playback_rate=2
        if mutation=='gain':p.studio_state['audio_track_gain_db']={p.audio_tracks[1].id:-6.0}
    stack=QUndoStack();stack.push(media_graph_command(project,'plan contract',change))
    after=playback_plan(project)
    assert after is not before
    assert after.audio_at(2500)==preview_audio_layers(capture_audio_graph(project),2500)
    stack.undo();restored=playback_plan(project)
    assert restored is not after
    assert restored.audio_at(2500)==before_audio
    stack.redo();assert playback_plan(project) is not restored

def test_selection_does_not_rebuild_and_availability_does(project):
    original=playback_plan(project)
    with state_for(project).transaction(project,action_id='select',dirty=DirtyDomain.CUE_SELECTION,snapshot_cues=False):pass
    assert playback_plan(project) is original
    project.media_pool[1].offline=True
    invalidate_playback_plan(project,'media_availability')
    current=playback_plan(project)
    assert current is not original
    assert [t.id for t,c in current.video_at(1500)]==['V1']

def test_project_copy_never_reuses_original_objects(project):
    original=playback_plan(project)
    other=copy.deepcopy(project);current=playback_plan(other)
    assert current is not original
    assert current.assets is not original.assets
    assert current.video_at(1500)[0][1] is not original.video_at(1500)[0][1]

def test_tick_does_not_traverse_canonical_media_lists(project):
    plan=playback_plan(project)
    class NoIteration(list):
        def __iter__(self):raise AssertionError('whole project traversal during playback')
    project.media_pool=NoIteration(project.media_pool)
    project.video_tracks=NoIteration(project.video_tracks)
    project.audio_tracks=NoIteration(project.audio_tracks)
    for ms in (1000,1500,2000,3000):
        assert playback_plan(project) is plan
        assert plan.video_at(ms)
        assert plan.audio_at(ms)

def test_failed_transaction_releases_derived_references(project):
    previous=playback_plan(project)
    with pytest.raises(RuntimeError):
        with state_for(project).transaction(project,action_id='abort',dirty=DirtyDomain.VIDEO_TRACKS):
            project.video_tracks[0].enabled=False
            raise RuntimeError('abort edit')
    assert playback_plan(project) is not previous
    assert project.video_tracks[0].enabled
