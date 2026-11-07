"""Editor submission compares the translation value its command really stores."""
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.studio.caption_editor import CaptionEditorMixin
from twobyteasr.studio.studio_bilingual import set_manual_translation
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.timeline.studio_commands import SetCueFieldsCommand

APP = QApplication.instance() or QApplication([])


@pytest.mark.parametrize('value,expected,count', [(' 旧译文 \n','旧译文',0),(' 新译文 \n','新译文',1)])
def test_translation_normalization_has_no_empty_undo_or_false_failure(value,expected,count):
    page, errors, ended, deltas = page_for(value,'translation')
    assert CaptionEditorMixin._submit_caption_draft_impl(page)
    assert errors == [] and ended == [True]
    assert page.undo_stack.index() == count
    assert page.project.generation_metadata['translations']['a'] == expected
    assert bool(deltas) == bool(count)
    if count:
        page.undo_stack.undo()
        assert page.project.generation_metadata['translations']['a'] == '旧译文'
        page.undo_stack.redo()
        assert page.project.generation_metadata['translations']['a'] == '新译文'


def test_original_editor_preserves_significant_whitespace():
    page, errors, ended, _ = page_for(' 原文 ','original')
    assert CaptionEditorMixin._submit_caption_draft_impl(page)
    assert not errors and ended == [True]
    assert page.project.cues[0].text == ' 原文 '
    assert page.undo_stack.index() == 1


def test_no_change_submission_retires_live_preview_without_a_data_delta():
    page, errors, ended, deltas = page_for('旧译文','translation')
    refreshed = []
    page._refresh_ass_preview = lambda:refreshed.append(True)
    assert CaptionEditorMixin._submit_caption_draft_impl(page)
    assert not errors and ended == [True] and refreshed == [True]
    assert page.undo_stack.index() == 0 and not deltas


def page_for(value, layer):
    project = SubtitleProject(StudioMedia('',duration_ms=2000),cues=[StudioCue('a',0,1000,'原文')])
    st.set_manual(project,'a','旧译文',target='zh-Hans')
    stack = QUndoStack()
    errors, ended, deltas = [], [], []
    state_for(project).subscribe(deltas.append)
    target = SimpleNamespace(layer=layer,language='zh-Hans',cue_id='a',
        resolve=lambda project:project.cues[0],
        read=lambda project:project.generation_metadata['translations']['a'] if layer=='translation' else project.cues[0].text)
    draft = SimpleNamespace(target=target,before=target.read(project),entity_epoch=0)
    page = SimpleNamespace(project=project,session=SimpleNamespace(project=project,undo_stack=stack),
        undo_stack=stack,_caption_draft=draft,subtitle_edit_input=SimpleNamespace(toPlainText=lambda:value),
        timeline=SimpleNamespace(locked_speakers=set()),_caption_owns_draft=lambda draft:True,
        _caption_editor_failed=lambda message,**options:errors.append(message),
        _draft_patch_decisions=lambda *args:{},_finish_caption_draft=lambda:ended.append(True),
        _refresh_ass_preview=lambda:None)
    def original(cue_id,text):
        stack.push(SetCueFieldsCommand(project,cue_id,{'text':text},'编辑原文'))
        return True
    page.cue_controller = SimpleNamespace(set_text=original,
        set_translation=lambda cue_id,text,**options:set_manual_translation(page,cue_id,text,**options))
    return page, errors, ended, deltas
