"""A draft follows its entity and field, never a selection or stale track."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.projects.studio_runtime_state import state_for


@pytest.fixture
def page(tmp_path, monkeypatch):
    app, page = _page(tmp_path, monkeypatch, [
        StudioCue('a', 0, 5000, 'Raw, unchanged!', speaker_id='S00'),
        StudioCue('b', 6000, 8000, 'Other', speaker_id='S01')])
    page.select_cue('a')
    page._open_caption_editor('a', 'original')
    yield page
    page.close_page(); page.deleteLater(); app.processEvents()


def test_track_move_preserves_current_fields_and_edits_stable_entity(page):
    draft = page._caption_draft
    page.subtitle_edit_input.setPlainText('New text')
    cue = page.project.cues[0]
    cue.speaker_id = 'S01'
    cue.start_ms = 250
    state_for(page.project).reindex_cues(page.project)
    page.select_cue('b')
    assert page._submit_caption_draft()
    assert (cue.id, cue.text, cue.speaker_id, cue.start_ms) == ('a', 'New text', 'S01', 250)
    assert page.project.cues[1].text == 'Other'
    page.undo_stack.undo()
    assert cue.text == draft.before and cue.speaker_id == 'S01'


def test_lock_is_checked_on_current_target_track_and_unlock_is_retryable(page):
    page.subtitle_edit_input.setPlainText('Keep this draft')
    page.project.cues[0].speaker_id = 'S01'
    state_for(page.project).reindex_cues(page.project)
    page.timeline.locked_speakers = {'S01'}
    assert not page._submit_caption_draft()
    assert page.subtitle_edit_input.toPlainText() == 'Keep this draft'
    page.timeline.locked_speakers = {'S00', 'translation', 'video'}
    assert page._submit_caption_draft()
    assert page.project.cues[0].text == 'Keep this draft'


def test_same_field_already_at_requested_value_is_idempotent(page):
    page.subtitle_edit_input.setPlainText('Identical result')
    page.cue_controller.set_text('a', 'Identical result')
    index = page.undo_stack.index()
    assert page._submit_caption_draft()
    assert page.project.cues[0].text == 'Identical result'
    assert page.undo_stack.index() == index


def test_rebuilt_objects_and_other_cue_revision_do_not_conflict(page):
    page.subtitle_edit_input.setPlainText('Draft')
    page.cue_controller.set_text('b', 'Other changed')
    page.project.cues = copy.deepcopy(page.project.cues)
    state_for(page.project).reindex_cues(page.project)
    assert page._submit_caption_draft()
    assert page.project.cues[0].text == 'Draft'
    assert page.project.cues[1].text == 'Other changed'


def test_real_field_conflict_retains_draft_and_has_precise_reason(page):
    page.subtitle_edit_input.setPlainText('My draft')
    page.cue_controller.set_text('a', 'Concurrent text')
    assert not page._submit_caption_draft()
    assert page.project.cues[0].text == 'Concurrent text'
    assert page.subtitle_edit_input.toPlainText() == 'My draft'
    assert 'text_conflict' in page.subtitle_edit_card.error_detail.text()
    assert page.subtitle_edit_card.reload_current_button.isVisible()


def test_session_generation_invalidates_even_reused_project_object(page):
    page.subtitle_edit_input.setPlainText('Stale draft')
    page.session.generation += 1
    assert not page._submit_caption_draft()
    assert page.project.cues[0].text == 'Raw, unchanged!'
    assert 'session_changed' in page.subtitle_edit_card.error_detail.text()


def test_confirm_key_does_not_recommit_rebound_draft(page, monkeypatch):
    calls=[]
    original=page.cue_controller.set_text
    monkeypatch.setattr(type(page.cue_controller),'set_text',lambda self,*a,**kw:(calls.append(a),original(*a,**kw))[1])
    page.subtitle_edit_input.setPlainText('Once')
    QTest.keyClick(page.subtitle_edit_input, Qt.Key.Key_Return)
    QTest.keyClick(page.subtitle_edit_input, Qt.Key.Key_Return)
    assert len(calls)==1 and page.project.cues[0].text=='Once'


def test_rolled_back_model_change_does_not_invalidate_draft(page):
    from twobyteasr.projects.studio_runtime_state import DirtyDomain
    state=state_for(page.project)
    with pytest.raises(ValueError):
        with state.transaction(page.project,action_id='failed structural edit',dirty=DirtyDomain.CUE_MODEL,affected_cue_ids=('a',)):
            state.entity_epochs['a']=1
            raise ValueError('controlled rollback')
    page.subtitle_edit_input.setPlainText('After rollback')
    assert page._submit_caption_draft() and page.project.cues[0].text=='After rollback'


def test_failed_disk_save_keeps_rebound_track_as_pending_target(page):
    page.project.cues[0].speaker_id='S01'
    state_for(page.project).reindex_cues(page.project)
    page.subtitle_edit_input.setPlainText('Pending disk save')
    token=page._commit_caption_for_manual_save()
    assert token and token[1]==page._caption_draft.target
    page._finish_caption_manual_save(token,error=OSError('controlled disk failure'))
    assert page._caption_disk_pending==page._caption_draft.target
    assert page.subtitle_edit_input.toPlainText()=='Pending disk save'


def test_default_failure_events_do_not_embed_exception_subtitle_body(page,monkeypatch):
    from twobyteasr.diagnostics import event_log
    secret='PRIVATE_SUBTITLE_BODY_91827'
    rows=[]
    monkeypatch.setattr(event_log,'emit',lambda name,**fields:rows.append((name,fields)))
    def fail(*args,**kwargs):raise ValueError(secret)
    monkeypatch.setattr(type(page.cue_controller),'set_text',fail)
    page.subtitle_edit_input.setPlainText(secret)
    assert not page._submit_caption_draft()
    assert secret not in repr(rows) and page.subtitle_edit_input.toPlainText()==secret


def test_undo_restores_original_entity_identity_but_live_split_rejects_old_draft(page):
    from twobyteasr.timeline.studio_commands import SpliceCuesCommand
    source=page.project.cues[0]
    left=copy.deepcopy(source);left.end_ms=2500
    right=copy.deepcopy(source);right.id='split-right';right.start_ms=2500
    page.subtitle_edit_input.setPlainText('Draft before split')
    command=SpliceCuesCommand(page.project,0,1,[left,right],'split for identity check')
    command.redo()
    assert not page._submit_caption_draft()
    assert 'entity_restructured' in page.subtitle_edit_card.error_detail.text()
    command.undo()
    assert page._submit_caption_draft()
    assert page.project.cues[0].text=='Draft before split'
