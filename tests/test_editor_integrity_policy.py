"""Synthetic regressions for the eight screenshots; no original audio is implied."""
from copy import deepcopy
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,save_project,load_project
from twobyteasr.subtitle_rules.machine_text_policy import machine_text_allowed,compliant_candidate
from twobyteasr.subtitle_rules.review_suggestions import ReviewSuggestion,SuggestionOption,model_suggestions

@pytest.mark.parametrize('word',['他','她','它','我','你','您','我们','你们','他们','她们','它们','这','那','这里','那里'])
def test_normal_pronouns_are_not_machine_deletions(word):
    before=word+'会打打雪仗我们走吧'
    assert not machine_text_allowed(before,before[len(word):])
    row=ReviewSuggestion(0,len(word),word,(SuggestionOption('',operation='delete'),),'model')
    assert row.apply(before)==before

@pytest.mark.parametrize('before,after',[('其他人在这里','其人在这里'),('吉他在门口','吉在门口'),('他这里会打','她这里会打')])
def test_word_parts_and_explicit_pronoun_replacement_remain_allowed(before,after):
    assert machine_text_allowed(before,after)

def test_compound_candidate_keeps_independent_term_fix_without_deleting_pronoun():
    before='他这里在营第等一下';proposed='这里在营地等一下'
    assert compliant_candidate(before,proposed)=='他这里在营地等一下'
    rows=model_suggestions(before,[(proposed,('FireRed',))])
    for row in reversed(rows):before=row.apply(before)
    assert before=='他这里在营地等一下'

@pytest.mark.parametrize('option',[SuggestionOption(None),SuggestionOption('')])
def test_missing_and_unspecified_empty_candidate_never_mean_delete(option):
    assert ReviewSuggestion(0,1,'字',(option,),'model').apply('字词')=='字词'

def test_explicit_non_pronoun_delete_is_still_available():
    assert ReviewSuggestion(0,2,'重复',(SuggestionOption('',operation='delete'),),'model').apply('重复重复')=='重复'

def test_legacy_proofread_cache_and_batch_recheck_protection():
    from twobyteasr.glossary.proofread_policy import pending_issue,issue_enabled
    from twobyteasr.glossary.proofread_batch import adoption_text
    text='他这里营第';issue=dict(span=(0,1),original='他',replacement='',kind='ai')
    assert not pending_issue(issue,text=text)
    with pytest.raises(ValueError,match='代称'):adoption_text(text,[issue])
    assert issue_enabled(dict(issue,checked=True),text=text)  # past human result remains visible

def media_project():
    p=SubtitleProject(StudioMedia('synthetic.mp4',duration_ms=16000,width=960,height=540),
        cues=[StudioCue('c',0,15000,'他这里在营第')]);p.validate();return p

@pytest.fixture(scope='module',autouse=True)
def app():yield QApplication.instance() or QApplication([])

def test_machine_single_and_batch_apply_are_gated_but_manual_undo_is_unrestricted():
    from twobyteasr.timeline.studio_commands import SetCueFieldsCommand,BatchReplaceTextCommand,MutationOrigin
    p=media_project();before=p.cues[0].text
    with pytest.raises(ValueError,match='代称'):SetCueFieldsCommand(p,'c',{'text':before[1:]},'AI',origin=MutationOrigin.MODEL_ADOPTION)
    with pytest.raises(ValueError,match='代称'):BatchReplaceTextCommand(p,{'c':before[1:]},origin=MutationOrigin.LLM)
    stack=QUndoStack();stack.push(SetCueFieldsCommand(p,'c',{'text':before[1:]},'人工删除'))
    assert p.cues[0].text==before[1:];stack.undo();assert p.cues[0].text==before

@pytest.mark.parametrize('saved_sequence_lock',[None,True,False])
def test_graph_unlock_is_authoritative_on_first_load(tmp_path,saved_sequence_lock):
    from twobyteasr.timeline.studio_edit_sequence import sequence_of
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command,video_track_locked
    p=media_project();assert not p.video_tracks[0].locked
    sequence=sequence_of(p).to_dict()
    if saved_sequence_lock is None:sequence.pop('video_track_locked')
    else:sequence['video_track_locked']=saved_sequence_lock
    p.edit_sequence=sequence
    p=load_project(save_project(p,tmp_path/'unlocked.2byteproj'))
    assert not video_track_locked(p,p.video_tracks[0])
    stack=QUndoStack();stack.push(clip_edit_command(p,'V1','split',clip_id=p.video_tracks[0].clips[0].id,time_ms=5000))
    assert len(p.video_tracks[0].clips)==len(p.audio_tracks[0].clips)==2
    stack.undo();assert len(p.video_tracks[0].clips)==len(p.audio_tracks[0].clips)==1
    stack.redo();assert len(p.video_tracks[0].clips)==len(p.audio_tracks[0].clips)==2

@pytest.mark.parametrize('lane',['video','audio'])
def test_real_linked_lock_rejects_atomically_and_names_object(lane):
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command
    p=media_project();track=p.video_tracks[0] if lane=='video' else p.audio_tracks[0]
    track.locked=True;before=deepcopy((p.video_tracks,p.audio_tracks))
    with pytest.raises(ValueError,match=track.id):clip_edit_command(p,'V1','split',clip_id=p.video_tracks[0].clips[0].id,time_ms=5000)
    assert (p.video_tracks,p.audio_tracks)==before

def test_detached_audio_lock_and_unrelated_caption_lock_do_not_block_video():
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command
    p=media_project();p.av_track_groups[0].linked=False;p.audio_tracks[0].locked=True
    p.studio_state['locked_speakers']=['S0']
    clip_edit_command(p,'V1','split',clip_id=p.video_tracks[0].clips[0].id,time_ms=5000).redo()
    assert len(p.video_tracks[0].clips)==2 and len(p.audio_tracks[0].clips)==1

@pytest.mark.parametrize('value,expected',[('false',False),('0',False),('true',True),('1',True)])
def test_persisted_string_flags_have_boolean_meaning(value,expected):
    p=media_project();p.video_tracks[0].locked=value;p.audio_tracks[0].locked=value;p.validate()
    assert p.video_tracks[0].locked is expected and p.audio_tracks[0].locked is expected








def test_locked_audio_without_target_link_is_outside_razor_scope():
    from twobyteasr.timeline.studio_clip_edit import clip_edit_command
    p=media_project();p.video_tracks[0].clips[0].audio_enabled=False
    p.audio_tracks[0].clips=[];p.audio_tracks[0].locked=True
    clip_edit_command(p,'V1','split',clip_id=p.video_tracks[0].clips[0].id,time_ms=5000).redo()
    assert len(p.video_tracks[0].clips)==2 and not p.audio_tracks[0].clips






def test_cloud_correction_generation_cannot_drop_normal_pronoun():
    import subtitle_core  # production owner initializes legacy domain adapters
    from twobyteasr.subtitle_rules.correction_safety import correction_is_safe
    assert correction_is_safe('他这里会打打雪仗我们走吧','这里会打打雪仗我们走吧')[0] is False


def test_unknown_nonempty_lock_flag_does_not_silently_unlock():
    from twobyteasr.projects.field_flags import flag
    assert flag('locked') is True and flag(None,default=True) is True


@pytest.mark.parametrize('text',['好好好','行行行行','对对对','可以试试'])
def test_normal_response_is_not_shortened(text):
    assert not machine_text_allowed(text,text[1:])
