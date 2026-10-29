"""V1 protection, independent captions, exact half-open ripple transactions."""
import copy
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, load_project
from twobyteasr.timeline.studio_media_pool import create_video_track, add_video_clip
from twobyteasr.timeline.studio_edit_sequence import sequence_of, projected_cues, VideoSegment, store_sequence
from twobyteasr.timeline.studio_clip_edit import playhead_edit_command, ripple_ranges_command, clip_edit_command
from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions, KEY, set_caption_ripple_command
from twobyteasr.recognition.cue_word_alignment import cue_words
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand, EditCueIntervalsCommand
from twobyteasr.timeline.timeline_cue_gesture import CueInterval
from twobyteasr.timeline.studio_track_delete import DeleteTrackCommand

APP = QApplication.instance() or QApplication([])


def fixture(words=False):
    p = SubtitleProject(media=StudioMedia(path='same-instance.mp4', duration_ms=20000), cues=[
        StudioCue('before', 8000, 9000, '区间前', speaker_id='S1'),
        StudioCue('left', 9500, 10500, '左跨界', speaker_id='S1'),
        StudioCue('inside', 10200, 11400, '删除', speaker_id='S1'),
        StudioCue('right', 11500, 12500, '右跨界', speaker_id='S1'),
        StudioCue('cross', 9000, 13000, '11223344' if words else '双跨界人工文字', speaker_id='S2',
                  evidence_refs=['exact'] if words else [], appearance_override={'color':'#FEECFA'}),
        StudioCue('after', 12500, 14000, '区间后', speaker_id='S2'),
    ])
    if words:
        p.asr_evidence={'exact':{'words':[
            {'text':'11','start_ms':9000,'end_ms':9900},
            {'text':'22','start_ms':10200,'end_ms':10900},
            {'text':'33','start_ms':11100,'end_ms':11900},
            {'text':'44','start_ms':12200,'end_ms':12900}]}}
    p.validate()
    p.video_tracks[0].locked = True
    p.video_tracks[0].enabled = False
    sequence_of(p).video_track_locked = True
    v2 = create_video_track(p, 'V2'); v2.locked = False
    add_video_clip(p, v2.id, p.video_tracks[0].clips[0].asset_id, timeline_in_ms=0)
    return p


def signature(p):
    return [(c.id,c.start_ms,c.end_ms,c.text,c.speaker_id) for c in projected_cues(p)]


def linked_ranges(p, lane='V2'):
    group = next(g for g in p.av_track_groups if g.video_track_id == lane)
    sound = next(a for a in p.audio_tracks if a.id == group.audio_track_id)
    videos = next(v for v in p.video_tracks if v.id == lane)
    return [(c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for c in videos.clips], [
        (c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for c in sound.clips]


def test_q_without_subtitle_selection_uses_v2_once_and_undo_whole_graph(tmp_path):
    p = fixture(); v1 = copy.deepcopy(p.video_tracks[0]); original = copy.deepcopy(p.cues)
    clip_edit_command(p,'V2','split',clip_id=p.video_tracks[1].clips[0].id,time_ms=10000).redo()
    before = copy.deepcopy(p.to_dict()); stack = QUndoStack()
    stack.push(playhead_edit_command(p,'ripple_start',12000,target_track_id='V2'))
    assert p.video_tracks[0] == v1
    video, audio = linked_ranges(p)
    assert video == audio == [(0,10000,0,10000),(10000,18000,12000,20000)]
    assert 'inside' not in {c.id for c in p.cues}
    assert next(c for c in p.cues if c.id=='after').start_ms == 10500
    assert next(c for c in p.cues if c.id=='cross').text == original[4].text
    assert p.studio_state[KEY]['source_archive'] == before['cues']
    after = copy.deepcopy(p.to_dict()); stack.undo()
    assert p.to_dict() == before
    stack.redo(); assert p.to_dict() == after
    reopened = load_project(save_project(p,tmp_path/'independent.2byteproj'))
    assert signature(reopened) == signature(p)
    assert reopened.studio_state[KEY] == p.studio_state[KEY]
    ensure_independent_captions(reopened)
    assert signature(reopened) == signature(p)


def test_w_uses_target_boundary_not_another_editable_lane():
    p=fixture(); extra=create_video_track(p,'V3'); extra.locked=False
    add_video_clip(p,extra.id,p.media_pool[0].asset_id,timeline_in_ms=0)
    c=extra.clips[0];c.source_out_ms=11000;c.timeline_out_ms=11000
    command=playhead_edit_command(p,'ripple_end',10000,target_track_id='V2')
    command.redo()
    assert [(c.timeline_in_ms,c.timeline_out_ms) for c in p.video_tracks[1].clips]==[(0,10000)]
    # V3 has a different boundary at 11s, but the one range is [10s,20s).
    assert [(c.timeline_in_ms,c.timeline_out_ms) for c in p.video_tracks[2].clips]==[(0,10000)]


@pytest.mark.parametrize('locked,disabled',[(True,False),(False,True),(True,True)])
def test_caption_track_lock_or_disabled_follow_skip_only_their_track(locked,disabled):
    p=fixture();ensure_independent_captions(p)
    original={c.id:copy.deepcopy(c) for c in p.cues if c.speaker_id=='S1'}
    if disabled:set_caption_ripple_command(p,'S1',False).redo()
    c=ripple_ranges_command(p,[(10000,12000)],locked_speakers={'S1'} if locked else ())
    c.redo()
    assert {x.id:x for x in p.cues if x.speaker_id=='S1'}==original
    assert c.skipped_caption_speakers=={'S1'}
    assert next(x for x in p.cues if x.id=='after').start_ms==10500
    assert p.video_tracks[0].locked and not p.video_tracks[0].enabled


def test_hidden_caption_track_still_follows_ripple():
    p=fixture();p.studio_state['subtitle_track_visibility']={'S1':False}
    ripple_ranges_command(p,[(10000,12000)]).redo()
    assert 'inside' not in {c.id for c in p.cues}
    assert p.studio_state['subtitle_track_visibility']=={'S1':False}


def test_exact_words_clip_repeated_digits_without_duplicate_sentence(tmp_path):
    p=fixture(words=True); raw=copy.deepcopy(p.asr_evidence)
    ripple_ranges_command(p,[(10000,12000)]).redo()
    pieces=[c for c in p.cues if c.speaker_id=='S2' and c.text in {'11','44'}]
    assert [(c.text,c.start_ms,c.end_ms) for c in pieces]==[('11',9000,9900),('44',10200,10900)]
    assert p.asr_evidence==raw
    assert all(c.appearance_override=={'color':'#FEECFA'} for c in pieces)
    assert [tuple((w.text,w.start_ms,w.end_ms) for w in cue_words(p,c)[0]) for c in pieces]==[
        (('11',9000,9900),),(('44',10200,10900),)]
    saved=load_project(save_project(p,tmp_path/'words.2byteproj'))
    assert signature(saved)==signature(p)
    assert [tuple((w.text,w.start_ms,w.end_ms) for w in cue_words(saved,c)[0]) for c in saved.cues if c.text in {'11','44'}]==[
        (('11',9000,9900),),(('44',10200,10900),)]


def test_missing_words_keeps_text_once_and_visible_review_receipt():
    p=fixture();ripple_ranges_command(p,[(10000,12000)]).redo()
    cross=[c for c in p.cues if c.text=='双跨界人工文字']
    assert len(cross)==1 and (cross[0].start_ms,cross[0].end_ms)==(9000,11000)
    assert p.studio_state[KEY]['instances']['cross']['needs_review']
    assert p.studio_state['cue_statuses']['cross']=='issue'
    from twobyteasr.subtitle_rules.studio_review import cached_review_risks
    assert cached_review_risks(p)['cross']['level']=='high'


def test_successive_and_merged_ranges_keep_nonnegative_half_open_timing():
    p=fixture();ensure_independent_captions(p)
    ripple_ranges_command(p,[(10000,11000),(10999,12000)]).redo()
    ripple_ranges_command(p,[(0,1000)]).redo()
    assert all(c.start_ms>=0 and c.end_ms>c.start_ms for c in p.cues)
    assert next(c for c in p.cues if c.id=='after').start_ms==9500
    assert p.video_tracks[0].clips[0].timeline_out_ms==20000


def test_legacy_current_projection_freezes_once_with_complete_original_archive(tmp_path):
    p=fixture();seq=copy.deepcopy(sequence_of(p));seq.video_track_locked=True
    original_id=seq.segments[0].id
    seq.segments=[VideoSegment(original_id,p.media.path,5000,15000,1000,11000)]
    store_sequence(p,seq)
    before=signature(p); original=copy.deepcopy(p.cues)
    assert ensure_independent_captions(p)
    assert signature(p)==before
    assert p.studio_state[KEY]['source_archive']==[__import__('dataclasses').asdict(c) for c in original]
    assert not ensure_independent_captions(p)
    reopened=load_project(save_project(p,tmp_path/'legacy.2byteproj'))
    assert signature(reopened)==before
    assert not ensure_independent_captions(reopened)


def test_independent_timing_does_not_touch_locked_v1_and_words_restore_on_undo():
    p=fixture(words=True);ensure_independent_captions(p);v1=copy.deepcopy(p.video_tracks[0])
    before_words=cue_words(p,next(c for c in p.cues if c.id=='cross'))[0]
    c=SetCueFieldsCommand(p,'cross',{'start_ms':9001,'end_ms':13000},'字幕自身裁切')
    c.redo();assert p.video_tracks[0]==v1
    # A display trim retains the measured words, including words outside its envelope.
    assert cue_words(p,next(c for c in p.cues if c.id=='cross'))[0]==before_words
    c.undo();assert cue_words(p,next(c for c in p.cues if c.id=='cross'))[0]==before_words
    move=EditCueIntervalsCommand(p,{'cross':CueInterval(10000,14000,'S2')})
    move.redo()
    assert [w.start_ms for w in cue_words(p,next(c for c in p.cues if c.id=='cross'))[0]]==[10000,11200,12100,13200]
    move.undo();assert cue_words(p,next(c for c in p.cues if c.id=='cross'))[0]==before_words


def test_ordinary_delete_leaves_caption_objects_and_v1_untouched():
    p=fixture();before=copy.deepcopy(p.cues);v1=copy.deepcopy(p.video_tracks[0])
    c=DeleteTrackCommand(p,'video','V2',clip_ids=[p.video_tracks[1].clips[0].id]);c.redo()
    assert p.cues==before and p.video_tracks[0]==v1
    assert p.studio_state[KEY]['source_archive']
    c.undo();assert p.video_tracks[0]==v1 and p.cues==before


def test_no_eligible_clip_never_falls_back_to_locked_v1_or_zero():
    p=fixture();p.video_tracks[1].locked=True;before=p.to_dict()
    with pytest.raises(ValueError,match='没有可编辑'):
        playhead_edit_command(p,'ripple_start',12000,target_track_id='V2')
    assert p.to_dict()==before


def test_independent_render_cues_are_project_time_and_source_ass_is_empty():
    p=fixture();ripple_ranges_command(p,[(10000,12000)]).redo()
    assert projected_cues(p,domain='source')==[]
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    store=StudioRevisionStore(p)
    assert store.render.cues==()
    assert [(c.id,c.start_ms,c.end_ms) for c in store.render.timeline_cues]==[(c.id,c.start_ms,c.end_ms) for c in p.cues]


def test_fresh_single_caption_scene_uses_project_clock_without_priming():
    from types import SimpleNamespace
    from PySide6.QtCore import QRectF
    from twobyteasr.rendering.caption_scene import CaptionScene
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue
    project=SubtitleProject(media=StudioMedia('fixture.mp4', duration_ms=1000),
        cues=[StudioCue('single#stable',0,1000,'one')],render_settings={'_cue_domain':'timeline'})
    calls=[]
    page=SimpleNamespace(project=project,video=SimpleNamespace(controller=None,clear_caption_boundaries=lambda:calls.append('clear')),
        _stop_web_live_preview=lambda reason:calls.append('stop'),_revoke_advanced_preview=lambda **kwargs:calls.append('revoke'),
        _revision_store=SimpleNamespace(render=None),position_overlay=SimpleNamespace(_content_rect=lambda:QRectF()))
    scene=SimpleNamespace(page=page,project=project,closed=False,active=False)
    assert CaptionScene.present(scene,project.cues,500)
    assert scene.active and calls==['stop','revoke','clear']


def test_design_target_preserves_independent_instance_id():
    from types import SimpleNamespace
    from twobyteasr.timeline.studio_design_target import DesignTarget
    project=SimpleNamespace(render_settings={'_cue_domain':'timeline'})
    cue=SimpleNamespace(id='same-source#second-instance')
    assert DesignTarget(project,1,cue,project).canonical_id==cue.id


def test_structural_split_merge_preserves_exact_words_and_undo_source_receipts():
    from twobyteasr.timeline.studio_commands import split_cue_command,merge_cues_command
    p=fixture(words=True);ensure_independent_captions(p);before=p.to_dict()
    command=split_cue_command(p,'cross',11000,'1122','3344');command.redo()
    parts=[c for c in p.cues if c.speaker_id=='S2' and c.text in {'1122','3344'}]
    assert [[w.text for w in cue_words(p,c)[0]] for c in parts]==[['11','22'],['33','44']]
    merge=merge_cues_command(p,[c.id for c in parts]);merge.redo()
    merged=next(c for c in p.cues if c.id=='cross')
    assert [w.text for w in cue_words(p,merged)[0]]==['11','22','33','44']
    merge.undo();command.undo();assert p.to_dict()==before
    command.redo();ripple_ranges_command(p,[(10000,12000)]).redo()
    assert [(c.text,c.start_ms,c.end_ms) for c in p.cues if c.text in {'11','44'}]==[('11',9000,9900),('44',10200,10900)]
