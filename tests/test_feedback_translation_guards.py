import copy
import json
from types import SimpleNamespace
from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand, merge_cues_command
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.studio.translation_actions import capture_intent, intent_current


def sample():
    p = SubtitleProject(media=StudioMedia(path='fixture.mp4'), cues=[
        StudioCue('a', 0, 1000, 'Hello my friend'), StudioCue('b', 1000, 2000, 'How are you')])
    p.generation_metadata['language'] = {'code': 'en'}
    return p


def result(p):
    source = st.translation_source(p)
    return st.TranslationResult('zh-Hans', 'model', 'provider', project_id=source.project_id,
        project_instance=source.project_instance, content_revisions=dict(source.content_revisions),
        sources={'a': p.cues[0].text}, translations={
            'a': st.TranslatedItem('a', '你好朋友', p.cues[0].text, st.source_sha(p.cues[0].text), '')})


def test_edited_then_undone_source_rejects_late_result():
    p = sample(); r = result(p); stack = QUndoStack()
    stack.push(SetCueFieldsCommand(p, 'a', {'text':'Changed'}, 'Edit'))
    stack.undo()
    before, after = st.apply_translation_result(p, r)
    assert before == after and r.discarded == {'a':'revision_changed'}


def test_deleted_or_different_project_cannot_receive_result():
    p = sample(); r = result(p); p.cues.pop(0)
    before, after = st.apply_translation_result(p, r)
    assert before == after and r.discarded['a'] == 'cue_removed'
    p = sample(); r = result(p); other = copy.deepcopy(p)
    before, after = st.apply_translation_result(other, r)
    assert before == after and r.discarded['a'] == 'project_changed'


def test_selection_change_is_safe_and_manual_translation_remains_protected():
    p=sample(); r=result(p)
    state_for(p).selected_cue_id='b'
    st.set_manual(p, 'a', '我自己写的')
    st.apply_translation_result(p, r)
    assert p.generation_metadata['translations']['a'] == '我自己写的'
    assert 'a' in r.suggestions and not r.discarded


def test_settings_continuation_is_bound_to_scope_source_and_language():
    p=sample(); page=SimpleNamespace(project=p)
    intent=capture_intent(page,['a'],'zh-Hans')
    state_for(p).selected_cue_id='b'
    assert intent_current(page,intent,'zh-Hans')
    assert not intent_current(page,intent,'ja')
    p.cues[0].text='changed'
    assert not intent_current(page,intent,'zh-Hans')


def test_merge_keeps_old_translation_stale_and_undo_restores_it():
    p=sample(); st.set_manual(p,'a','手工译文')
    stack=QUndoStack(); stack.push(merge_cues_command(p,['a','b']))
    assert st.cue_status(p,p.cues[0],target='zh-Hans') == st.NEEDS_UPDATE
    stack.undo()
    assert st.cue_status(p,p.cues[0],target='zh-Hans') == st.MANUAL
