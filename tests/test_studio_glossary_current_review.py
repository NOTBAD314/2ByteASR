"""Current editable baseline, visible review candidates, and explicit association."""
import copy
import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QWidget

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry
from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
from twobyteasr.glossary.studio_glossary_review import recover_review_edits, diff_occurrences
from twobyteasr.studio.studio_text_tools import TextOccurrence, values_from_occurrences
from twobyteasr.studio.studio_find_replace import GlossaryReviewDialog, TermAssociationDialog, PreviewBinding, apply_occurrences


def library(*terms):
    return GlossarySnapshot((GlossaryLibrary('v','瓦罗兰特','1',terms=tuple(terms),
        profile_json=json.dumps({'_content_domain':{'id':'v','name':'瓦罗兰特','source':'saved_library_game'}})),))


def project(*texts):
    p=SubtitleProject(media=StudioMedia(path='isolated.mp4'),glossary_ids=['v'],
        cues=[StudioCue(str(i),i*2000,i*2000+1000,text,original_text=text,speaker_id='S01')
            for i,text in enumerate(texts,1)])
    p.validate(); return p


def fake_model(monkeypatch,callback):
    import subtitle_core
    import twobyteasr.providers.asr_provider_snapshot as provider
    import twobyteasr.subtitle_rules.polishing as polish
    monkeypatch.setattr(provider,'resolve_provider_snapshot',lambda *_a,**_kw:
        SimpleNamespace(public_identity=lambda:{'provider':'offline-test','model':'offline-test'},
            timeout_policy=SimpleNamespace(total=10)))
    monkeypatch.setattr(polish,'call_correction_api',callback)
    return polish.PolishBatchResult


def test_no_cloud_preview_retains_current_text_and_reports_missing(monkeypatch):
    def forbidden(*_a,**_kw):raise AssertionError('local preview must not request provider')
    import twobyteasr.providers.asr_provider_snapshot as provider
    monkeypatch.setattr(provider,'resolve_provider_snapshot',forbidden)
    p=project('还是在等奥特曼出结果','而且球球能奶自己')
    before=copy.deepcopy(p)
    s=library(TermEntry('CHICHOO',('CHICHOO',),category='选手ID'))
    result=preview_glossary_correction(p,['1','2'],s,{},use_ai=False)
    assert p==before and not result.hits
    surfaces={row['surface'] for row in result.receipt['pending_rows']}
    assert {'奥特曼','球球'}<=surfaces
    assert result.receipt['ai_requested'] is False and result.receipt['checked_cues']==2
    assert result.receipt['missing_associations']>=2
    assert json.loads(open(result.receipt['diagnostic_path'],encoding='utf8').read())['project_id']==p.project_id


@pytest.mark.parametrize('failed',[False,True])
def test_local_confirmed_mapping_survives_model_keep_or_failure(monkeypatch,failed):
    Result=fake_model(monkeypatch,lambda rows,*_a,**_kw:
        (_ for _ in ()).throw(RuntimeError('offline request failure')) if failed else
        Result({row.segment_id:row.text.replace('autumn','奥特曼') for row in rows}))
    p=project('还是在等奥特曼出结果')
    s=library(TermEntry('autumn',('奥特曼',),category='选手ID'))
    result=preview_glossary_correction(p,['1'],s,{})
    assert values_from_occurrences(p,result.hits)=={'1':'还是在等autumn出结果'}
    assert all(h.default_selected for h in result.hits)
    row=result.receipt['segments'][0]
    assert row['original_baseline']=='还是在等奥特曼出结果' and row['local_draft']=='还是在等autumn出结果'
    assert bool(result.receipt['request_errors'])==failed


def test_model_diff_back_to_asr_remains_visible_unselected(monkeypatch):
    Result=fake_model(monkeypatch,lambda rows,*_a,**_kw:Result({1:'BerLIN守住'}))
    p=project('Borlin守住');p.cues[0].original_text='BerLIN守住'
    result=preview_glossary_correction(p,['1'],library(TermEntry('BerLIN',category='选手ID')),{})
    assert result.hits and all(not hit.default_selected for hit in result.hits)
    assert values_from_occurrences(p,result.hits)=={'1':'BerLIN守住'}
    assert p.cues[0].text=='Borlin守住'
    assert result.receipt['segments'][0]['original_asr']=='BerLIN守住'


def test_protocol_fallback_has_actionable_empty_state(monkeypatch):
    Result=fake_model(monkeypatch,lambda rows,*_a,**_kw:Result({1:rows[0].text},succeeded=(),failures={1:'invalid_format'}))
    p=project('普通句')
    result=preview_glossary_correction(p,['1'],library(TermEntry('autumn',category='选手ID')),{})
    assert result.receipt['empty_state']=='request_failed'
    assert result.receipt['failed_cues']==[{'cue_id':'1','reason':'invalid_format'}]
    assert result.receipt['successful_cues']==0 and result.receipt['fallback_cues']==1


def test_automatic_gate_rejection_is_visible_without_automatic_authority(monkeypatch):
    detail={'sent_candidates':[{'candidate_id':'autumn-id','canonical':'autumn'}],
        'rejected_edits':[{'from':'奥特曼','to':'autumn','start':4,'end':7,
            'candidate_id':'autumn-id','basis':'glossary context','rule_id':'catalog_without_local_support'}]}
    Result=fake_model(monkeypatch,lambda rows,*_a,**_kw:Result({1:rows[0].text},details={1:detail}))
    p=project('还是在等奥特曼出结果')
    result=preview_glossary_correction(p,['1'],library(TermEntry('autumn',category='选手ID')),{})
    hits=[hit for hit in result.hits if hit.source=='ai_review']
    assert len(hits)==1 and hits[0].original=='奥特曼' and hits[0].replacement=='autumn'
    assert not hits[0].default_selected and '缺少局部支持' in hits[0].missing_evidence
    assert result.receipt['rejected_changes']==1 and result.receipt['confirmation_changes']>=1


@pytest.mark.parametrize('patch',[
    {'candidate_id':'invented'}, {'start':0,'end':3}, {'start':False,'end':7},
    {'rule_id':'invalid_original_span'}, {'to':'invented'}, {'rule_id':'overlapping_speaker_protection'}])
def test_invalid_review_output_cannot_become_checkable(patch):
    cue=project('还是在等奥特曼出结果').cues[0]
    edit={'from':'奥特曼','to':'autumn','start':4,'end':7,'candidate_id':'a',
        'rule_id':'catalog_without_local_support'};edit.update(patch)
    hits,invalid=recover_review_edits(cue,cue.text,{'sent_candidates':[{'candidate_id':'a','canonical':'autumn'}],
        'rejected_edits':[edit]},library(TermEntry('autumn',category='选手ID')),None)
    assert not hits and invalid


def test_confirmed_nickname_respects_animation_topic():
    p=project('小时候喜欢看奥特曼动画')
    result=preview_glossary_correction(p,['1'],library(TermEntry('autumn',('奥特曼',),category='选手ID')),{},use_ai=False)
    assert not result.hits and result.receipt['segments'][0]['final_text']==p.cues[0].text


def test_independent_changes_partial_accept_undo_and_reopen(tmp_path):
    p=project('奥特曼和球球守住');before=copy.deepcopy(p)
    s=library(TermEntry('autumn',('奥特曼',),category='选手ID'),
        TermEntry('CHIOCHOO',('球球',),category='选手ID'),TermEntry('CHICHOO',category='选手ID'))
    result=preview_glossary_correction(p,['1'],s,{},use_ai=False)
    assert len(result.hits)==2
    page=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=QUndoStack()),_changed=lambda:None)
    first=[hit for hit in result.hits if hit.replacement=='autumn']
    assert apply_occurrences(page,first,title='确认',binding=PreviewBinding.capture(p),glossary_ids=['v'],review_receipt=result.receipt)==(1,1)
    assert p.cues[0].text=='autumn和球球守住'
    target=tmp_path/'test.2byteproj';save_project(p,target)
    reopened=load_project(target)
    assert reopened.cues[0].text==p.cues[0].text and reopened.cues[0].original_text==before.cues[0].original_text
    assert (reopened.cues[0].start_ms,reopened.cues[0].end_ms,reopened.cues[0].speaker_id)==(2000,3000,'S01')
    page.session.undo_stack.undo()
    assert p.cues[0]==before.cues[0]
    page.session.undo_stack.redo();assert p.cues[0].text=='autumn和球球守住'


def test_overlapping_candidates_are_rejected_before_any_mutation():
    p=project('奥特曼守住')
    page=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=QUndoStack()),_changed=lambda:None)
    hits=[TextOccurrence('1',2000,'奥特曼',target,(0,3)) for target in ['autumn','CHICHOO']]
    assert apply_occurrences(page,hits,title='确认',binding=PreviewBinding.capture(p))==(0,0)
    assert p.cues[0].text=='奥特曼守住' and page.session.undo_stack.count()==0


class Page(QWidget):
    def __init__(self,p):
        super().__init__();self.session=SimpleNamespace(project=p,undo_stack=QUndoStack(),selected_cue_id=p.cues[0].id)
    def selected_cue_ids(self):return [self.session.selected_cue_id]
    def select_cue(self,value):self.session.selected_cue_id=value
    def _changed(self):pass
    def _show_studio_hint(self,value):pass


@pytest.fixture
def actual_store(monkeypatch,tmp_path):
    import subtitle_core as core
    monkeypatch.setattr(core,'LEARNED_TERMS_PATH',str(tmp_path/'terms.json'))
    monkeypatch.setattr(core,'load_game_profiles',lambda: {})
    core.add_learned_mapping('v','CHICHOO','CHICHOO',category='选手ID')
    return core


def test_empty_ui_missing_row_prefills_newcanonical_and_disables_apply(actual_store):
    app=QApplication.instance() or QApplication([])
    p=project('奥特曼守住');page=Page(p);dialog=GlossaryReviewDialog(page)
    dialog._do_preview()
    assert not dialog.all_button.isEnabled() and dialog.preview.count()>0
    item=next(dialog.preview.item(i) for i in range(dialog.preview.count())
        if dialog.preview.item(i).data(Qt.UserRole+1)['surface']=='奥特曼')
    assert not item.flags() & Qt.ItemIsUserCheckable
    dialog.preview.setCurrentItem(item);assert dialog.associate_button.isEnabled()
    dialog.associate_button.click();form=dialog._association_dialog
    assert form.alias_edit.text()=='奥特曼' and form.canonical_combo.currentText()==''
    form.canonical_combo.setEditText('autumn')
    assert form.save_button.isEnabled() and '新增' in form.status.text()
    form.save_button.click()
    assert dialog.all_button.isEnabled() and dialog._checked_hits()
    dialog._do_apply_preview();assert p.cues[0].text=='autumn守住'
    assert not dialog.all_button.isEnabled()
    page.session.undo_stack.undo();assert p.cues[0].text=='奥特曼守住'
    dialog.reject();page.close()


def test_association_preserves_distinct_ids_and_revision(actual_store):
    from twobyteasr.glossary.terminology import snapshot_glossaries
    app=QApplication.instance() or QApplication([]);parent=QWidget()
    before=snapshot_glossaries(actual_store,['v'])
    form=TermAssociationDialog({'surface':'球球'},before,parent)
    form.canonical_combo.setEditText('CHIOCHOO');form.save_button.click()
    after=snapshot_glossaries(actual_store,['v'])
    assert {'CHIOCHOO','CHICHOO'}<=set(after.canonical_terms)
    assert after.digest!=before.digest and after.libraries[0].revision!=before.libraries[0].revision
    assert ('球球','CHIOCHOO') in [(r['from'],r['to']) for r in actual_store.load_learned_term_payload()['games']['v']['mappings']]
    form.close();parent.close()


def test_unchecked_review_controls_apply_button(actual_store):
    app=QApplication.instance() or QApplication([]);p=project('Borlin守住');page=Page(p)
    dialog=GlossaryReviewDialog(page)
    hits=diff_occurrences(p.cues[0],'BerLIN守住',reason='待确认',source='ai_review',selected=False)
    dialog._fill_preview(hits)
    assert not dialog.all_button.isEnabled()
    dialog.preview.item(0).setCheckState(Qt.Checked);assert dialog.all_button.isEnabled()
    dialog._set_all_preview_checked(False);assert not dialog.all_button.isEnabled()
    dialog.close();page.close()
