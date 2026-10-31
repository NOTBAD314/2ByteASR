"""Drafts survive rejection/IME/persistence failure and preserve cue identity."""
import os,copy
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor,QInputMethodEvent
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import StudioCue,load_project
from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand


@pytest.mark.parametrize('path',['partial','all','clear'])
def test_same_final_text_keeps_identity_timing_and_undo_state(tmp_path,monkeypatch,path):
    from tests.test_review_replay_and_window_bounds import _page
    app,page=_page(tmp_path,monkeypatch,[StudioCue('stable',1000,4000,'原句文字')])
    try:
        p=page.project;before=copy.deepcopy(p.cues[0]);page.select_cue('stable');page._open_caption_editor()
        editor=page.subtitle_edit_input
        if path=='partial':
            cursor=editor.textCursor();cursor.setPosition(1);cursor.setPosition(2,QTextCursor.KeepAnchor);cursor.insertText('新')
        else:
            editor.selectAll()
            if path=='clear':
                editor.insertPlainText('');app.processEvents()
                assert len(p.cues)==1 and p.cues[0].text==before.text
            editor.insertPlainText('原新文字')
        assert page._submit_caption_draft()
        cue=p.cues[0]
        assert (cue.id,cue.start_ms,cue.end_ms,cue.speaker_id,cue.style_id)==(before.id,before.start_ms,before.end_ms,before.speaker_id,before.style_id)
        assert cue.text=='原新文字' and cue.appearance_override['text_alignment']['status']=='needs_alignment'
        page.undo_stack.undo();assert p.cues[0].text==before.text and p.cues[0].appearance_override==before.appearance_override
        page.undo_stack.redo();assert p.cues[0].text=='原新文字'
        errors=[];page.project_controller.save(message_box_fn=lambda *args:errors.append(str(args[-1])))
        assert not errors and load_project(page.project_path).cues[0].text=='原新文字'
    finally:page.close_page();page.deleteLater();app.processEvents()


def test_failed_command_retains_bound_editor_and_can_retry(tmp_path,monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    from twobyteasr.studio.studio_cue_controller import StudioCueController
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',1000,4000,'原句')])
    try:
        page.select_cue('a');page._open_caption_editor();page.subtitle_edit_input.setPlainText('新句')
        original=StudioCueController.set_text
        monkeypatch.setattr(StudioCueController,'set_text',lambda *a,**kw:True)  # false success at a Qt callback boundary
        assert not page._submit_caption_draft()
        assert page._canvas_editor is page.subtitle_edit_input and page.subtitle_edit_input.toPlainText()=='新句'
        monkeypatch.setattr(StudioCueController,'set_text',original)
        assert page._submit_caption_draft() and page.project.cues[0].text=='新句'
    finally:page.close_page();page.deleteLater();app.processEvents()


def test_button_save_cannot_reset_uncommitted_ime_candidate(tmp_path,monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',1000,4000,'原句')])
    try:
        page.select_cue('a');page._open_caption_editor()
        editor=page.subtitle_edit_input
        QApplication.sendEvent(editor,QInputMethodEvent('候选',[]))
        assert not page._submit_caption_draft()
        assert page._caption_draft is not None and page.project.cues[0].text=='原句'
        event=QInputMethodEvent();event.setCommitString('确认')
        QApplication.sendEvent(editor,event)
        value=editor.toPlainText();assert page._submit_caption_draft()
        assert page.project.cues[0].text==value and '确认' in value
    finally:page.close_page();page.deleteLater();app.processEvents()


def test_real_atomic_replace_failure_keeps_dirty_memory_and_retry(tmp_path,monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    from twobyteasr.projects import studio_project as persistence
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',1000,4000,'原句')])
    try:
        page.select_cue('a');page._open_caption_editor();page.subtitle_edit_input.setPlainText('磁盘失败也保留这句')
        assert page._submit_caption_draft()
        original=persistence.os.replace
        def blocked(src,dst):
            if str(dst)==str(page.project_path):raise PermissionError('isolated file replacement failure')
            return original(src,dst)
        monkeypatch.setattr(persistence.os,'replace',blocked)
        errors=[];page.project_controller.save(message_box_fn=lambda *a:errors.append(str(a[-1])))
        assert errors and not page.undo_stack.isClean()
        assert page.project.cues[0].text=='磁盘失败也保留这句'
        assert load_project(page.project_path).cues[0].text=='原句'
        monkeypatch.setattr(persistence.os,'replace',original)
        page.project_controller.save(message_box_fn=lambda *a:errors.append(str(a[-1])))
        assert page.undo_stack.isClean() and load_project(page.project_path).cues[0].text=='磁盘失败也保留这句'
    finally:page.close_page();page.deleteLater();app.processEvents()


def test_batch_text_invalidates_alignment_and_restores_it_on_undo():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    p=SubtitleProject(media=StudioMedia(''),cues=[StudioCue('a',100,1000,'旧字')])
    before=copy.deepcopy(p.cues[0].appearance_override)
    command=BatchReplaceTextCommand(p,{'a':'新字'});command.redo()
    assert p.cues[0].appearance_override['text_alignment']=={'text':'新字','status':'needs_alignment'}
    command.undo();assert p.cues[0].appearance_override==before
