"""A review row belongs to a round until the user explicitly dismisses it."""
from types import SimpleNamespace
import copy
import pytest
from PySide6.QtWidgets import QApplication
from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage, _StandalonePage, _issue, rebase_issue
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project

APP=QApplication.instance() or QApplication([])

@pytest.fixture
def page(tmp_path):
    p=SubtitleProject(StudioMedia('',duration_ms=9000),cues=[
        StudioCue('middle',1000,2500,'古龙和火龙来了'),StudioCue('later',4000,5500,'另一条古龙')])
    p.validate()
    w=GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    w._project=p;w._project_path=str(tmp_path/'work.2byteproj')
    w._standalone=_StandalonePage(p);w._bind_stack(w._standalone.session.undo_stack)
    w._build_rows(p,start_checks=False)
    w._by_id['middle']['issues']=[_issue('term',(0,2),'古龙','大骨龙',checked=False),
        _issue('near',(3,5),'火龙','火笼',checked=False)]
    w._by_id['later']['issues']=[_issue('term',(3,5),'古龙','骨龙',checked=False)]
    w.filter_buttons['suggested'].setChecked(True);w._apply_filter()
    yield w,p
    w._save_timer.stop();w._rematch_timer.stop()
    if hasattr(w,'_local_timer'):w._local_timer.stop()
    w.shutdown();w.deleteLater();APP.processEvents()

def visible(w):return [w._rows[n]['cue_id'] for n in w.list.visible]

def test_adopt_two_different_lengths_retains_row_and_is_idempotent(page):
    w,p=page
    w._toggle_issue('middle',0)
    assert p.cues[0].text=='大骨龙和火龙来了'
    assert visible(w)==['middle','later']
    w._toggle_issue('middle',1)
    assert p.cues[0].text=='大骨龙和火笼来了'
    assert visible(w)==['middle','later']
    count=w._live_stack().count()
    w._toggle_issue('middle',0)
    assert p.cues[0].text=='大骨龙和火笼来了'
    assert w._live_stack().count()==count
    assert not w._row_state(w._by_id['middle'])[1]

def test_manual_rewrite_retains_even_all_stale_and_dismiss_keeps_edit(page):
    w,p=page
    w._edit_committed('middle','手动改成完整的新句子')
    assert visible(w)==['middle','later']
    w._dismiss_group('middle',-1)
    assert visible(w)==['later']
    assert p.cues[0].text=='手动改成完整的新句子'
    w.filter_buttons['changed'].setChecked(True);w._apply_filter()
    assert 'middle' in visible(w)

def test_ignore_without_edit_is_not_changed_and_does_not_revive(page):
    w,p=page
    w._dismiss_group('middle',0)
    assert visible(w)==['later']
    assert not w._row_state(w._by_id['middle'])[2]
    w._by_id['middle']['issues'].append(_issue('ai',(0,2),'古龙','骨龙',checked=False))
    w._apply_decisions(w._by_id['middle'],{});w._apply_filter(cue_ids={'middle'})
    assert visible(w)==['later']
    assert w.proposal_counts()['changed']==0

def test_adopted_row_can_be_dismissed_undo_redo_and_restored_from_disk(page,tmp_path):
    w,p=page
    w._toggle_issue('middle',0);w._toggle_issue('middle',1)
    assert 'middle' in visible(w)
    w._dismiss_group('middle',0)
    assert visible(w)==['later']
    w._undo();assert 'middle' in visible(w)
    w._redo();assert visible(w)==['later']
    path=tmp_path/'saved.2byteproj';save_project(p,path)
    reopened=load_project(path)
    w._project=reopened;w._build_rows(reopened,start_checks=False);w._apply_filter()
    assert 'middle' not in visible(w)
    row=w._by_id['middle']
    assert row['origin']=='古龙和火龙来了'
    assert row['base']=='大骨龙和火笼来了'
    assert w._row_state(row)[2]

def test_retained_adoption_reopens_without_relying_on_rematch(page,tmp_path):
    w,p=page;w._toggle_issue('middle',0);w._toggle_issue('middle',1)
    path=tmp_path/'retained.2byteproj';save_project(p,path)
    reopened=load_project(path)
    w._project=reopened;w._build_rows(reopened,start_checks=False);w._apply_filter()
    assert 'middle' in visible(w)
    assert len([i for i in w._by_id['middle']['issues'] if i['checked']])==2

def test_ambiguous_deleted_occurrence_does_not_move_old_proposal_to_another_word():
    i=_issue('term',(0,2),'古龙','骨龙',checked=False)
    assert not rebase_issue(i,'古龙和古龙','古龙')
    assert i['stale']

def test_single_row_result_reuses_other_layouts(page,monkeypatch):
    w,p=page
    calls=[];orig=w._groups
    def groups(row):calls.append(row['cue_id']);return orig(row)
    monkeypatch.setattr(w,'_groups',groups)
    w._toggle_issue('middle',0)
    assert 'later' not in calls

def test_undo_adoption_restores_pending_state_without_losing_retention(page):
    w,p=page
    w._toggle_issue('middle',0)
    assert w._by_id['middle']['issues'][0]['checked']
    w._undo()
    row=w._by_id['middle']
    assert not row['issues'][0]['checked'] and not row['issues'][0]['reviewed']
    assert w._row_state(row)==(True,True,False)
    w._redo()
    assert w._by_id['middle']['issues'][0]['checked']
    assert 'middle' in visible(w)

def test_batch_adoption_then_explicit_batch_ignore_keeps_written_text(page):
    w,p=page
    w._batch_selected={'middle','later'}
    w._batch_adopt()
    assert visible(w)==['middle','later']
    text=[c.text for c in p.cues]
    w._batch_selected={'middle','later'}
    w._batch_ignore()
    assert visible(w)==[] and [c.text for c in p.cues]==text
    w._undo()
    assert visible(w)==['middle','later'] and [c.text for c in p.cues]==text

def test_explicit_new_round_releases_round_dismissal_and_can_be_undone(page,monkeypatch):
    w,p=page
    w._dismiss_group('middle',0)
    calls=[];monkeypatch.setattr(w,'_run',lambda *args:calls.append(args))
    w._restart_review(False)
    assert not w._by_id['middle'].get('review_dismissed')
    row=w._by_id['middle'];row['issues']=[_issue('term',(0,2),'古龙','骨龙',checked=False)]
    w._apply_filter()
    assert 'middle' in visible(w) and calls==[(False,None)]
    w._undo()
    assert 'middle' not in visible(w)

def test_hidden_speaker_incremental_edit_does_not_reprocess_other_rows(page,monkeypatch):
    w,p=page
    p.cues[1].speaker_id='hidden';w._by_id['later']['speaker_id']='hidden'
    w._hidden_speakers={'hidden'};w._apply_filter()
    calls=[];original=w._groups
    def groups(row):calls.append(row['cue_id']);return original(row)
    monkeypatch.setattr(w,'_groups',groups)
    w._edit_committed('middle','改过的文字')
    assert 'later' not in calls and w._filter_counts['all']==1

def test_save_ownership_remains_until_thread_finished(page,monkeypatch):
    import threading,time
    from twobyteasr.glossary import glossary_proofread as module
    w,p=page;release=threading.Event();emitted=threading.Event()
    original=module._SaveThread
    class SlowFinish(original):
        def run(self):
            self.done.emit('');emitted.set();release.wait(3)
    monkeypatch.setattr(module,'_SaveThread',SlowFinish)
    w._save_timer.stop();w._save_now();thread=w._save_thread
    try:
        assert emitted.wait(1)
        for _ in range(10):APP.processEvents();time.sleep(.005)
        assert w._save_thread is thread and thread.isRunning()
    finally:
        release.set();thread.wait(3000);APP.processEvents()

def test_review_worker_view_has_no_live_runtime_or_mutable_caption_receipt(page):
    from twobyteasr.glossary.glossary_proofread import _review_copy
    w,p=page
    p._native_owner=object()
    p.studio_state['caption_timeline']={'instances':{'middle':{'words':[{'text':'旧'}]}}}
    view=_review_copy(p,{'middle'})
    assert '_native_owner' not in view.__dict__ and '_studio_state_runtime' not in view.__dict__
    assert [c.id for c in view.cues]==['middle']
    p.studio_state['caption_timeline']['instances']['middle']['words'][0]['text']='改过'
    assert view.studio_state['caption_timeline']['instances']['middle']['words'][0]['text']=='旧'

def test_ignore_all_after_adoption_never_reverts_and_does_not_count_unedited_as_changed(page):
    w,p=page;w._toggle_issue('middle',0)
    before=[c.text for c in p.cues]
    w._set_all(False)
    assert visible(w)==[] and [c.text for c in p.cues]==before
    assert w.proposal_counts()['changed']==1
    w._undo()
    assert visible(w)==['middle','later'] and [c.text for c in p.cues]==before

def test_explicit_repeated_word_deletion_is_adopted_but_never_deletes_again(page):
    w,p=page;w._edit_committed('middle','它它来了')
    row=w._by_id['middle'];row['issues']=[_issue('stutter',(0,1),'它','',checked=False)]
    w._apply_filter();w._toggle_issue('middle',0)
    assert row['base']=='它来了' and row['issues'][0]['checked'] and not row['issues'][0]['stale']
    w._toggle_issue('middle',0)
    assert row['base']=='它来了' and 'middle' in visible(w)
    w._undo();assert row['base']=='它它来了' and not row['issues'][0]['checked']

def test_shift_r_uses_same_retained_adoption_and_r_stays_text_in_editor(page):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w,p=page;w.show();w.list.current='middle';w.list.setFocus()
    QTest.keyClick(w.list,Qt.Key.Key_R,Qt.KeyboardModifier.ShiftModifier)
    assert p.cues[0].text=='大骨龙和火龙来了' and 'middle' in visible(w)
    QTest.keyClick(w.list,Qt.Key.Key_R,Qt.KeyboardModifier.ShiftModifier)
    assert p.cues[0].text=='大骨龙和火笼来了' and 'middle' in visible(w)
    w._edit('middle');w.list.editor.setText('')
    QTest.keyClick(w.list.editor,Qt.Key.Key_R)
    assert w.list.editor.text()=='r' and p.cues[0].text=='大骨龙和火笼来了'
    w.list.cancel_edit()
