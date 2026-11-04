import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,save_project,load_project
from twobyteasr.timeline.studio_media_pool import add_media_asset,create_video_track,add_video_clip,remove_video_clip,primary_video_track_id
from twobyteasr.timeline.studio_edit_sequence import sequence_of,recording_sequence,HighlightCandidate,timeline_duration_ms
from twobyteasr.timeline.studio_edit_commands import generate_edit_command,restore_full_sequence_command
from twobyteasr.studio.highlight_workflow import timeline_range


def test_only_retained_secondary_recording_generates_on_its_actual_track(tmp_path):
    app=QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia(path=str(tmp_path/'old.flv'),duration_ms=60000));p.validate()
    old_primary=p.video_tracks[0];old_primary.locked=False
    for c in list(old_primary.clips):remove_video_clip(p,old_primary.id,c.id)
    source=str(tmp_path/'last.flv')
    asset=add_media_asset(p,source,duration_ms=90000,video_metadata={'has_video':True},audio_metadata={'has_audio':True})
    track=create_video_track(p)
    add_video_clip(p,track.id,asset.asset_id,timeline_in_ms=0)
    seq=sequence_of(p);seq.segments=[];seq.empty_timeline=True;seq.video_track_locked=True
    p.render_settings['_cue_domain']='timeline'
    p.cues=[StudioCue('same',20000,25000,'这次真的成功了')]
    p.studio_state['caption_timeline']={'instances':{'same':{'source_path':source,'source_start_ms':20000,'source_end_ms':25000}}}
    c=HighlightCandidate('c','保留',19000,27000,source_path=source,source_duration_ms=90000,status='accepted',range_status='manual')
    seq.clip_candidates=[c]
    assert recording_sequence(p)[0]==track.id
    assert timeline_range(p,source,19000,27000)==(19000,27000)
    undo=QUndoStack();undo.push(generate_edit_command(p))
    assert primary_video_track_id(p)==track.id
    assert not p.video_tracks[0].clips
    actual=next(t for t in p.video_tracks if t.id==track.id).clips
    assert len(actual)==1 and (actual[0].source_in_ms,actual[0].source_out_ms)==(19000,27000)
    assert timeline_duration_ms(p)==8000
    assert p.cues[0].start_ms==1000 and p.cues[0].end_ms==6000
    sounds=[c for t in p.audio_tracks if t.linked_video_track_id==track.id for c in t.clips]
    assert sounds and all((c.source_in_ms,c.source_out_ms)==(19000,27000) for c in sounds)
    assert generate_edit_command(p) is None
    undo.undo();assert primary_video_track_id(p)==old_primary.id
    assert next(t for t in p.video_tracks if t.id==track.id).clips[0].source_out_ms==90000
    undo.redo()
    path=tmp_path/'edited.2byteproj';save_project(p,path);opened=load_project(path)
    assert primary_video_track_id(opened)==track.id and timeline_duration_ms(opened)==8000
    undo.push(restore_full_sequence_command(p))
    assert next(t for t in p.video_tracks if t.id==track.id).clips[0].source_out_ms==90000


@pytest.mark.parametrize('blocked_by',['foreign_captions','track_lock'])
def test_secondary_generation_respects_source_ownership_and_lock(tmp_path,blocked_by):
    app=QApplication.instance() or QApplication([])
    p=SubtitleProject(media=StudioMedia(path=str(tmp_path/'first.flv'),duration_ms=60000));p.validate()
    first=p.video_tracks[0];first.locked=False
    for c in list(first.clips):remove_video_clip(p,first.id,c.id)
    source=str(tmp_path/'last.flv')
    asset=add_media_asset(p,source,duration_ms=90000,video_metadata={'has_video':True},audio_metadata={'has_audio':True})
    track=create_video_track(p);add_video_clip(p,track.id,asset.asset_id,timeline_in_ms=5000)
    if blocked_by=='track_lock':track.locked=True
    else:
        p.cues=[StudioCue('foreign',20000,25000,'旧录播的字幕')]
        p.render_settings['_cue_domain']='timeline'
    seq=sequence_of(p);seq.segments=[];seq.empty_timeline=True
    seq.clip_candidates=[HighlightCandidate('c','保留',19000,27000,source_path=source,source_duration_ms=90000,status='accepted',range_status='manual')]
    assert timeline_range(p,source,19000,27000)==(24000,32000)
    with pytest.raises(ValueError):generate_edit_command(p)
    assert primary_video_track_id(p)==first.id and track.clips[0].source_out_ms==90000


def test_io_uses_the_retained_secondary_recording(tmp_path):
    from twobyteasr.studio.studio_edit_assembly import StudioEditAssemblyMixin
    class Page(StudioEditAssemblyMixin):
        def _sequence_changed(self,*args,**kwargs):pass
    app=QApplication.instance() or QApplication([])
    page=Page();p=SubtitleProject(media=StudioMedia(path=str(tmp_path/'first.flv'),duration_ms=60000));p.validate()
    first=p.video_tracks[0];first.locked=False
    for c in list(first.clips):remove_video_clip(p,first.id,c.id)
    source=str(tmp_path/'last.flv')
    asset=add_media_asset(p,source,duration_ms=90000,video_metadata={'has_video':True},audio_metadata={'has_audio':True})
    track=create_video_track(p);add_video_clip(p,track.id,asset.asset_id,timeline_in_ms=5000)
    seq=sequence_of(p);seq.segments=[];seq.empty_timeline=True;seq.in_point_ms=24000;seq.out_point_ms=32000
    page.project=p;page.undo_stack=QUndoStack();page._add_io_candidate()
    candidate=sequence_of(p).clip_candidates[0]
    assert candidate.source_path==source and candidate.clip_range==(19000,27000)
