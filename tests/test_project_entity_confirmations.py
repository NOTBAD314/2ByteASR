from copy import deepcopy
from types import SimpleNamespace

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.glossary.project_entity_confirmations import confirmation_receipt, confirmed_entity_occurrences
from twobyteasr.studio.studio_find_replace import PreviewBinding, apply_occurrences
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, load_project, save_project
from twobyteasr.studio.studio_text_tools import find_occurrences


def project():
    return SubtitleProject(media=StudioMedia(path='isolated-test.mp4',fingerprint='media-fingerprint'),
        cues=[StudioCue('a',0,1000,'So还在往里走',speaker_id='S00'),
              StudioCue('b',1000,2000,'So的反应',speaker_id='S00'),
              StudioCue('c',2000,3000,'Somebody So2 So_player xSo So中文',speaker_id='S00')])


def page():
    app=QApplication.instance() or QApplication([])
    return SimpleNamespace(session=SimpleNamespace(project=project(),undo_stack=QUndoStack()),_changed=lambda:None)


def test_receipt_is_human_evidence_without_model_claim():
    p=project();receipt=confirmation_receipt(p,'So','S0pp',['a'])
    assert receipt['source']=='user_confirmed' and receipt['audio_verified_by_model'] is False
    assert receipt['confirmed_occurrences']==[{'cue_id':'a','start_ms':0,'end_ms':1000,'text':'So还在往里走'}]


def test_one_confirmation_preview_preserves_original_and_is_one_undo(tmp_path):
    a=page();p=a.session.project;before=deepcopy(p.to_dict())
    receipt=confirmation_receipt(p,'So','S0pp',['a'])
    hits=find_occurrences(p,['a'],'So','S0pp',case_sensitive=True)
    assert apply_occurrences(a,hits,title='本工程确认',binding=PreviewBinding.capture(p),
        glossary_ids=p.glossary_ids,review_receipt=receipt)==(1,1)
    assert p.cues[0].text=='S0pp还在往里走'
    assert p.studio_state['manual_caption_text']['a']==p.cues[0].text
    candidates=confirmed_entity_occurrences(p)
    assert p.cues[1].text=='So的反应'  # Preview does not mutate other cues.
    assert any(hit.cue_id=='b' for hit in candidates)
    a.session.undo_stack.undo()
    assert [c.text for c in p.cues]==[row['text'] for row in before['cues']]
    assert p.generation_metadata.get('glossary_review_jobs') is None
    assert p.studio_state.get('manual_caption_text',{})=={}
    a.session.undo_stack.redo()
    target=tmp_path/'confirmed.2byteproj';save_project(p,target)
    reopened=load_project(target)
    assert reopened.studio_state['manual_caption_text']['a']=='S0pp还在往里走'
    assert any(hit.cue_id=='b' for hit in confirmed_entity_occurrences(reopened))
    assert p.asr_evidence==before['asr_evidence']


def test_foreign_project_receipt_is_not_adopted_even_for_the_same_media():
    first=project();other=project()
    other.generation_metadata['glossary_review_jobs']=[confirmation_receipt(first,'So','S0pp',['a'])]
    assert not confirmed_entity_occurrences(other)


def test_different_media_identity_and_missing_identity_do_not_propagate():
    p=project();p.generation_metadata['glossary_review_jobs']=[confirmation_receipt(p,'So','S0pp',['a'])]
    p.media.fingerprint='different'
    assert not confirmed_entity_occurrences(p)
    p.media.fingerprint='';p.media.path=''
    assert not confirmed_entity_occurrences(p)


def test_complete_latin_handle_boundary_and_locks():
    p=project();p.generation_metadata['glossary_review_jobs']=[confirmation_receipt(p,'So','S0pp',['a'])]
    hits=confirmed_entity_occurrences(p,locked_ids=['a'])
    assert [(h.cue_id,h.original) for h in hits]==[('b','So'),('c','So')]
    start=p.cues[2].text.rindex('So')
    assert hits[-1].span==(start,start+2)


def test_conflicting_alias_confirmations_are_skipped_with_diagnostic():
    p=project()
    p.generation_metadata['glossary_review_jobs']=[confirmation_receipt(p,'So','S0pp',['a']),
        confirmation_receipt(p,'So','OtherPlayer',['b'])]
    conflicts=[]
    assert not confirmed_entity_occurrences(p,diagnostics=conflicts)
    assert conflicts==['So']


def test_entity_review_ui_respects_selected_scope_and_does_not_learn_globally(monkeypatch):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.studio.studio_find_replace import FindReplaceDialog
    from twobyteasr.studio.studio_text_tools import SCOPE_SELECTED
    import subtitle_core
    monkeypatch.setattr(subtitle_core,'glossary_catalog',lambda:[])
    app=QApplication.instance() or QApplication([])
    class Page(QWidget):
        def __init__(self):
            super().__init__()
            self.session=SimpleNamespace(project=project(),undo_stack=QUndoStack())
            self._selected=['a']
            self.cue_controller=None
            self.learned=[]
        def selected_cue_ids(self):return self._selected
        def _changed(self):pass
        def _show_studio_hint(self,text):pass
    a=Page();d=FindReplaceDialog(a)
    d.find_edit.setText('So');d.replace_edit.setText('S0pp');d.case_box.setChecked(True)
    d.project_entity_box.setChecked(True)
    d.scope_combo.setCurrentIndex(d.scope_combo.findData(SCOPE_SELECTED))
    d._do_preview();d._do_apply_preview()
    assert a.session.project.cues[0].text=='S0pp还在往里走'
    assert a.session.project.generation_metadata['glossary_review_jobs'][0]['source']=='user_confirmed'
    a._selected=['b'];d.tabs.setCurrentIndex(3)
    d.terms_scope.setCurrentIndex(d.terms_scope.findData(SCOPE_SELECTED))
    d._do_project_entities_preview()
    assert {hit.cue_id for hit in d._preview_hits}=={'b'}
    d.reject()
    assert a.session.project.cues[1].text=='So的反应'
    a.deleteLater();app.processEvents()


def test_stale_manual_edit_and_media_replacement_reject_preview():
    a=page();p=a.session.project;receipt=confirmation_receipt(p,'So','S0pp',['a'])
    rows=find_occurrences(p,['a'],'So','S0pp',case_sensitive=True)
    binding=PreviewBinding.capture(p);p.cues[0].text='人工另一位选手'
    assert apply_occurrences(a,rows,title='确认',binding=binding,review_receipt=receipt)==(0,0)
    assert p.cues[0].text=='人工另一位选手'
    p.cues[0].text='So还在往里走';binding=PreviewBinding.capture(p)
    p.media.path='different-video.mp4';p.media.fingerprint='different-media'
    assert apply_occurrences(a,rows,title='确认',binding=binding,review_receipt=receipt)==(0,0)
