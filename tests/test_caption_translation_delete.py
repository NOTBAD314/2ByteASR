"""Deleting linked translations is one all-or-nothing edit, retaining sources."""
import copy
from types import SimpleNamespace as NS

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QLabel
from tests.test_subtitle_edit_integrity import APP, project
from twobyteasr.projects.studio_runtime_state import state_for
from twobyteasr.studio.studio_translation_edit import clear_translation
from twobyteasr.studio.studio_bilingual import set_manual_translation
from twobyteasr.subtitle_rules import subtitle_translation as st


def page_for(p):
    stack = QUndoStack()
    page = NS(project=p,session=NS(project=p,undo_stack=stack),undo_stack=stack,
              timeline=NS(translation_selected_ids={'a','b'},subtitle_target_language='zh-Hans'),save_state=QLabel())
    page.cue_controller = NS(set_translation=lambda key,text,**kw:set_manual_translation(page,key,text,**kw))
    return page


def test_translation_multi_delete_has_one_commit_and_complete_undo():
    p = project(); p.validate()
    for key in ('a','b','c'): st.set_manual(p,key,'译文'+key)
    page = page_for(p); before = copy.deepcopy(p.cues); view = dict(p.generation_metadata['translations'])
    count = state_for(p).commit_count
    assert clear_translation(page)
    assert p.cues == before
    assert state_for(p).commit_count == count+1
    assert page.undo_stack.count() == 1
    assert p.generation_metadata['translations'] == {'c':'译文c'}
    page.undo_stack.undo(); assert p.generation_metadata['translations'] == view
    page.undo_stack.redo(); assert p.generation_metadata['translations'] == {'c':'译文c'}


def test_invalid_translation_target_cannot_partially_delete_other_records():
    p = project(); p.validate(); st.set_manual(p,'a','译文a');st.set_manual(p,'b','English b'); p.generation_metadata[st.RECORDS_KEY]['records']['b']['target']='en'
    page = page_for(p); before=st.snapshot(p)
    assert clear_translation(page) is False
    assert st.snapshot(p) == before and page.undo_stack.count() == 0

