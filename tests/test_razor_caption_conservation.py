"""Independent razor, recovery, boundary and ripple contracts (integer ms)."""
import copy
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,load_project
from twobyteasr.studio_edit_sequence import projected_cues,sequence_of
from twobyteasr.studio_clip_edit import playhead_edit_command,clip_edit_command
from twobyteasr.studio_media_pool import create_video_track,add_video_clip

APP=QApplication.instance() or QApplication([])

def fixture():
    p=SubtitleProject(media=StudioMedia(path='same-cut.mp4',duration_ms=20000),cues=[
        StudioCue('before',1000,3100,'切点前字幕',speaker_id='A'),
        StudioCue('cross',3000,7000,'跨切点完整字幕',speaker_id='B',appearance_override={'color':'#fafafa'}),
        StudioCue('micro',4495,4505,'字',speaker_id='B'),
        StudioCue('after',7600,11600,'切点后字幕',speaker_id='A'),
        StudioCue('tail',13000,17500,'末尾字幕',speaker_id='B')])
    p.generation_metadata['test_word_evidence']=[{'id':'字','start_ms':4495,'end_ms':4505}]
    p.validate();p.video_tracks[0].locked=False;sequence_of(p).video_track_locked=False
    return p

def signature(p,domain='timeline'):
    return [(c.text,c.start_ms,c.end_ms,c.speaker_id,c.style_id,c.appearance_override,c.evidence_refs)
            for c in projected_cues(p,domain=domain)]

@pytest.mark.parametrize('cut',[3000,3100,4495,4500,4505,7000])
def test_exact_boundary_and_crossing_word_survive_in_both_domains(cut):
    p=fixture();before=signature(p);raw=copy.deepcopy(p.to_dict())
    playhead_edit_command(p,'split',cut).redo()
    assert signature(p)==before and signature(p,'source')==before
    assert p.to_dict()['cues']==raw['cues']
    assert p.generation_metadata==raw['generation_metadata']

def test_undo_redo_multicut_save_reopen_are_independent(tmp_path):
    p=fixture();before=signature(p);stack=QUndoStack()
    stack.push(playhead_edit_command(p,'split',4500));stack.undo()
    assert len(sequence_of(p).segments)==1 and signature(p)==before
    stack.redo();stack.push(playhead_edit_command(p,'split',9200))
    assert len(sequence_of(p).segments)==3 and signature(p)==before
    reopened=load_project(save_project(p,tmp_path/'cut.2byteproj'))
    assert signature(reopened)==before and reopened.generation_metadata==p.generation_metadata
    right=reopened.video_tracks[0].clips[1];left=reopened.video_tracks[0].clips[0]
    right.effects['only-right']=1
    assert 'only-right' not in left.effects and right.id!=left.id


def test_legacy_materialized_clip_id_keeps_captured_recognition_ownership(tmp_path):
    from twobyteasr.studio_edit_sequence import store_sequence
    p=fixture();seq=copy.deepcopy(sequence_of(p))
    seq.segments[0].id='captured-original'
    store_sequence(p,seq)  # persisted legacy sequence and graph IDs differ
    p.generation_metadata['timeline_recognition']={'sequence':copy.deepcopy(seq.to_dict())}
    before=signature(p);raw=copy.deepcopy(p.to_dict()['cues'])
    playhead_edit_command(p,'split',4500).redo()
    assert signature(p)==before and p.to_dict()['cues']==raw
    assert all('captured-original' in sequence_of(p).segment_lineage[s.id] for s in sequence_of(p).segments)
    playhead_edit_command(p,'split',9200).redo()
    restored=load_project(save_project(p,tmp_path/'legacy-cut.2byteproj'))
    assert signature(restored)==before

@pytest.mark.parametrize('rate',[1,2,2.5])
@pytest.mark.parametrize('lane',['V1','V2'])
def test_nonzero_source_in_and_rate_have_identical_projection_after_cut(rate,lane):
    p=fixture();c=p.video_tracks[0].clips[0]
    c.source_in_ms=1000;c.source_out_ms=18001;c.playback_rate=rate
    c.timeline_in_ms=0;c.timeline_out_ms=round(17001/rate)
    clip_edit_command(p,'V1','move',clip_id=c.id,start=0).redo()
    if lane=='V2':
        track=create_video_track(p,'V2');track.locked=False
        added=add_video_clip(p,track.id,c.asset_id,timeline_in_ms=0)
        added.source_in_ms=c.source_in_ms;added.source_out_ms=c.source_out_ms
        added.timeline_out_ms=c.timeline_out_ms;added.playback_rate=c.playback_rate
        clip_edit_command(p,'V2','move',clip_id=added.id,start=0).redo()
    before=signature(p)
    for cut in (1001,2002,3003): playhead_edit_command(p,'split',cut).redo()
    assert signature(p)==before
    from fractions import Fraction
    pieces=next(t for t in p.video_tracks if t.id==lane).clips
    assert all(piece.source_in_ms == 1000+round(Fraction(piece.timeline_in_ms*17001,round(17001/rate))) for piece in pieces)

def test_reused_source_and_v2_without_selection_are_distinct_instances():
    p=fixture();v1=p.video_tracks[0];original=v1.clips[0]
    repeat=copy.deepcopy(original);repeat.id='repeat';repeat.timeline_in_ms=20000;repeat.timeline_out_ms=40000
    v1.clips.append(repeat)
    clip_edit_command(p,'V1','move',clip_id=original.id,start=0).redo()
    before=signature(p)
    v2=create_video_track(p,'V2');v2.locked=False
    add_video_clip(p,v2.id,original.asset_id,timeline_in_ms=0)
    # The command never receives a selected track. Ctrl+K cuts both lanes.
    playhead_edit_command(p,'split',4500).redo()
    assert len(v1.clips)==2  # stale detached graph is not mutated
    assert len(p.video_tracks[0].clips)==3 and len(p.video_tracks[1].clips)==2
    assert signature(p)==before
    assert [c[1:3] for c in signature(p) if c[0]=='跨切点完整字幕']==[(3000,7000),(23000,27000)]

@pytest.mark.parametrize('action,expected',[
    ('ripple_start',[('字',0,5),('跨切点完整字幕',0,2500),('切点后字幕',3100,7100),('末尾字幕',8500,13000)]),
    ('ripple_end',[('切点前字幕',1000,3100),('跨切点完整字幕',3000,4500),('字',4495,4500)])])
def test_qw_delete_only_expected_range_and_preserve_raw_cues(action,expected):
    p=fixture();raw=copy.deepcopy(p.cues)
    playhead_edit_command(p,action,4500).redo()
    assert [(c.text,c.start_ms,c.end_ms) for c in projected_cues(p)]==expected
    assert p.cues==raw
