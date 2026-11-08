"""Report-scale correctness fences and event-loop lifecycle regression."""
import copy
import time
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication,QWidget
from twobyteasr.acceptance.studio_search_fixture import make_project
from twobyteasr.studio.studio_find_replace import FindReplaceDialog,TextReplaceBinding,apply_occurrences
from twobyteasr.studio.subtitle_text_targets import text_entries,entry_lookup
from twobyteasr.subtitle_rules import subtitle_translation as st
from twobyteasr.diagnostics.text_work import TextWork

APP=QApplication.instance() or QApplication([])


class Page(QWidget):
    def __init__(self,p):
        super().__init__()
        self.session=SimpleNamespace(project=p,undo_stack=QUndoStack(self),selected_cue_id='0',generation=1)
        self.timeline=SimpleNamespace(active_subtitle_layer='translation',translation_selected_ids=['0'])
    def selected_cue_ids(self):return [self.session.selected_cue_id]
    def _changed(self):pass
    def _show_studio_hint(self,*args):pass


def drain(d,timeout=15):
    start=time.monotonic()
    while d._search_timer.isActive() or getattr(d,'_search_pending',False):
        APP.processEvents()
        if time.monotonic()-start>timeout:raise AssertionError('search did not finish')
        time.sleep(.001)
    APP.processEvents()


def search(d,needle='勇者',mode='translation'):
    d.text_targets.mode.setCurrentIndex(d.text_targets.mode.findData(mode))
    d.find_edit.setText(needle)
    d.replace_edit.setText('新文字')
    d._do_preview()
    drain(d)


def test_text_reads_never_compute_status_even_with_terms(monkeypatch):
    p=make_project(100,20,0)
    monkeypatch.setattr(st,'statuses',lambda *a,**k:(_ for _ in ()).throw(AssertionError('unexpected status scan')))
    assert len(text_entries(p,mode='original'))==100
    entries=text_entries(p,mode='translation')
    assert len(entries)==98
    assert len(entry_lookup(p,targets=[entries[0].target]))==1


def test_status_cache_exact_dependencies_and_current_cue(monkeypatch):
    from twobyteasr.glossary import translation_terms as terms
    p=make_project(50,2,0)
    p.cues[10].text='用語00000'
    r=st.records_of(p)['10'];r['source_sha']=st.source_sha(p.cues[10].text)
    calls=[];original=terms.rule_version
    monkeypatch.setattr(terms,'rule_version',lambda *a,**k:(calls.append(1),original(*a,**k))[1])
    first=st.statuses(p);cold=len(calls)
    assert first['10']=='needs_update' and cold>0
    assert st.statuses(p)==first and len(calls)==cold
    p.generation_metadata['translation_terminology']['libraries'][0]['terms'][0]['target']='新名字'
    st.statuses(p);assert len(calls)>cold
    calls.clear();p.cues[12].text+=' changed'
    changed=st.statuses(p)
    assert changed['12']==st.NEEDS_UPDATE and len(calls)<=7
    # Changing only a record version must still update status despite cached rules.
    p.generation_metadata['translation_terminology']['enabled']=False
    r.pop('terminology_version',None)
    assert st.statuses(p)['10'] in ('done','manual')
    p.generation_metadata['translation_records']['target']='ja'
    assert st.statuses(p,target='ja')['10']=='needs_update'


@pytest.mark.parametrize('change',[
    lambda p:setattr(p.cues[0],'text','direct original'),
    lambda p:st.records_of(p)['0'].update(text='direct record'),
    lambda p:p.generation_metadata['translations'].update({'0':'direct legacy'}),
    lambda p:p.generation_metadata['translation_records'].update(target='en'),
    lambda p:p.generation_metadata['translation_terminology'].update(selected_ids=[]),
    lambda p:p.studio_state.update(locked_cue_ids=['0']),
    lambda p:p.cues[0].appearance_override.update(translation_group={'id':'g','text':'direct group'}),
    lambda p:p.cues.reverse(),
])
def test_binding_rejects_direct_mutations_without_revision(change):
    p=make_project(20,2,0);binding=TextReplaceBinding.capture(p)
    change(p)
    assert not binding.matches(p)


def test_binding_ignores_playhead_and_rejects_different_instance():
    p=make_project(20,2,0);b=TextReplaceBinding.capture(p)
    p.studio_state.update(playhead_ms=42000,zoom=3,last_selected_cue='2')
    assert b.matches(p)
    other=copy.deepcopy(p)
    assert not b.matches(other)


def test_dialog_input_no_scan_cancellation_cache_and_batched_results(monkeypatch):
    p=make_project(5555,100,0);page=Page(p);d=FindReplaceDialog(page)
    try:
        search(d,'勇者','both')
        assert len(d._preview_hits)==11108
        assert d._last_search_metrics['calls'].get('statuses',0)==0
        assert d.preview.item(1000)._content_factory is not None
        old=d._search_generation
        # Input callback only invalidates/schedules; no data scan runs here.
        with TextWork('input').activate() as work:
            d.find_edit.setText('新查询')
        assert not work.calls and not work.counts
        assert d._preview_binding is None
        d.find_edit.setText('勇者');drain(d)
        assert d._search_generation>old
        assert d._last_search_metrics['counts'].get('text_snapshot_cache_hits')==1
        search(d,'绝无此字','original')
        assert not d._preview_hits
        assert d._last_search_metrics['calls']['translation_view']==0
    finally:d.reject();page.deleteLater();APP.processEvents()


def test_old_query_project_and_queued_apply_cannot_publish_or_edit():
    p=make_project(500,2,0);page=Page(p);d=FindReplaceDialog(page)
    try:
        search(d,'勇者','translation')
        generation=d._search_generation;query=d._query()
        d.find_edit.setText('never')
        d._run_search_action(generation,p,query,'apply')
        assert page.session.undo_stack.count()==0
        d._do_preview();APP.processEvents()
        other=make_project(20,0,0);page.session.project=other
        drain(d)
        assert not d._preview_hits
        assert d._preview_binding.project is other
        d._do_preview();d.reject();APP.processEvents()
        assert not d._search_pending and not d._slice_timer.isActive()
    finally:d.reject();page.deleteLater();APP.processEvents()


def test_two_translation_replacements_correct_undo_redo_and_terms():
    p=make_project(5555,100,0);page=Page(p);d=FindReplaceDialog(page)
    before=st.snapshot(p)
    try:
        assert all(st.status_of(st.records_of(p)[i],p.cues[int(i)].text)=='needs_update' for i in ('400','2777'))
        search(d,'待替换名','translation')
        assert len(d._preview_hits)==2
        d._do_apply_preview();drain(d)
        assert not d._preview_hits and page.session.undo_stack.count()==1
        assert d._last_text_work['calls']['statuses']==0
        assert d._last_text_work['counts'].get('translation_view_full_scans',0)==0
        assert d._last_text_work['counts']['translation_records_observed']==4
        assert all('新文字' in st.records_of(p)[i]['text'] for i in ('400','2777'))
        assert all(st.statuses(p)[i]=='manual' for i in ('400','2777'))
        page.session.undo_stack.undo()
        assert st.snapshot(p)==before
        page.session.undo_stack.redo()
        assert all('新文字' in st.records_of(p)[i]['text'] for i in ('400','2777'))
    finally:d.reject();page.deleteLater();APP.processEvents()


def test_regex_process_and_cancel_have_no_qt_or_project_input():
    p=make_project(30,0,0);page=Page(p);d=FindReplaceDialog(page)
    try:
        d.regex_box.setChecked(True)
        search(d,r'翻译\s+\d+','translation')
        assert len(d._preview_hits)==28
        assert d._last_search_metrics['counts']['regex_process_jobs']==1
        p.cues[0].text='a'*100000+'!'
        d.find_edit.setText('(a+)+$');d._do_preview()
        for _ in range(5):APP.processEvents();time.sleep(.01)
        d.reject();APP.processEvents()
        assert not d._search_pending
    finally:d.reject();page.deleteLater();APP.processEvents()


def test_statuses_match_current_term_semantics_across_edits():
    from twobyteasr.glossary.translation_terms import freeze,effective_policy,relevant,validation_issues
    p=make_project(40,3,0,term_shape='shared-alias')
    def reference():
        records=st.records_of(p)
        result={c.id:st.status_of(records.get(c.id),c.text) for c in p.cues}
        source=st.translation_source(p);policy=freeze(source.terminology)
        for cue in source.cues:
            r=records.get(cue.id,{})
            if result[cue.id]!=st.DONE:continue
            direction=r.get('target') or st.container_target(p)
            rules=relevant(effective_policy(policy,source.inline_pairs,source.language,direction),source.language,direction,cue.text)
            if validation_issues(cue.text,str(r.get('text') or ''),rules):result[cue.id]=st.NEEDS_UPDATE
        return result
    for index in range(6):
        assert st.statuses(p)==reference()
        assert st.statuses(p)==reference()
        if index==0:p.cues[10].text+='用語00000'
        elif index==1:p.generation_metadata['translation_terminology']['selected_ids']=[]
        elif index==2:p.generation_metadata['translation_terminology']['enabled']=False
        elif index==3:p.generation_metadata['translation_glossary']=[('匿名','匿名译名')]
        else:p.generation_metadata['translation_terminology']['libraries'][0]['target_language']='en'


def test_picker_defaults_to_selected_record_language_and_preserves_unclassified_source():
    p=make_project(20,0,0)
    st.records_of(p)['1']['target']='en'
    page=Page(p);page.session.selected_cue_id='1'
    d=FindReplaceDialog(page)
    try:assert d.text_targets.tracks()=={'translation-records:en'}
    finally:d.reject()
    p.generation_metadata['subtitle_imports']={'tracks':{'S00':{'role':'independent','language':''}}}
    page.session.selected_cue_id='0';page.timeline.active_subtitle_layer='original'
    d=FindReplaceDialog(page)
    try:assert d.text_targets.mode_value()=='original'
    finally:d.reject();page.deleteLater();APP.processEvents()


def test_large_translation_batch_keeps_source_and_exact_undo():
    p=make_project(5555,20,0);page=Page(p);d=FindReplaceDialog(page)
    before=st.snapshot(p);source=[(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues]
    try:
        search(d,'勇者','translation')
        assert len(d._preview_hits)==5553
        d._do_apply_preview();drain(d)
        assert len(page._last_text_edit_result.changed)==5553
        assert [(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues]==source
        assert page.session.undo_stack.count()==1
        page.session.undo_stack.undo();assert st.snapshot(p)==before
        page.session.undo_stack.redo()
        assert all('新文字' in st.records_of(p)[str(i)]['text'] for i in range(5553))
    finally:d.reject();page.deleteLater();APP.processEvents()


def test_operation_summary_keeps_numeric_counts_without_subtitle_content(monkeypatch):
    from twobyteasr.diagnostics import event_log
    captured=[]
    monkeypatch.setattr(event_log,'emit',lambda name,**data:captured.append(event_log.Sanitizer().clean(data)))
    work=TextWork('test.search')
    with work.activate():text_entries(make_project(20,0,0),mode='original')
    work.finish()
    assert captured[0]['calls']['text_entries_count']==1
    assert captured[0]['counts']['text_cues_scanned_count']==20
    assert all(isinstance(r['duration_ms'],(int,float)) for r in captured[0]['phase_times'])
    assert '匿名の字幕' not in str(captured) and '待替换名' not in str(captured)


def test_unversioned_edit_and_rollback_between_slices_cannot_mix_snapshot_rows():
    p=make_project(5555,0,0);page=Page(p);d=FindReplaceDialog(page)
    try:
        d.text_targets.mode.setCurrentIndex(0)
        d.find_edit.setText('transientX');d._do_preview();d._slice_timer.stop()
        iterator=d._search_iterator;work=d._search_work
        with work.activate():next(iterator)
        original=p.cues[0].text;p.cues[0].text='transientX'
        try:
            with work.activate():next(iterator)
        except StopIteration:pass
        p.cues[0].text=original
        if d._search_pending:d._slice_timer.start(0)
        drain(d)
        assert d._preview_hits==[]
        assert d._preview_binding is not None and d._preview_binding.matches(p)
    finally:d.reject();page.deleteLater();APP.processEvents()
