"""Production dialog/page behavior: target defaults, retained rows and stale AI."""
import copy
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest

from tests.test_bilingual_text_targets import APP, make_project
from twobyteasr.studio.studio_find_replace import FindReplaceDialog
from twobyteasr.studio.subtitle_text_targets import scope_entries, text_entries, review_project
from twobyteasr.glossary.glossary_proofread import GlossaryProofreadPage, _StandalonePage
from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
from twobyteasr.glossary.terminology import snapshot_from_pairs
from twobyteasr.subtitle_rules import subtitle_translation as st


def settle_search(dialog):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        QTest.qWait(2)
        APP.processEvents()
        if not getattr(dialog,'_search_pending',False) and not dialog._search_timer.isActive():
            QTest.qWait(2)
            if not getattr(dialog,'_search_pending',False) and not dialog._search_timer.isActive():return
    raise AssertionError('asynchronous text search did not settle')


class Page(QWidget):
    def __init__(self, translation=False):
        super().__init__()
        self.session = SimpleNamespace(project=make_project(), selected_cue_id='source-a', undo_stack=QUndoStack(self))
        self.timeline = SimpleNamespace(active_subtitle_layer='translation' if translation else 'original',
                                        translation_selected_ids={'source-a'} if translation else set())
        self.hint = ''

    def _changed(self):
        pass

    def _show_studio_hint(self, hint):
        self.hint = hint

    def selected_cue_ids(self):
        return [self.session.selected_cue_id]

    def select_cue(self, cue_id):
        self.session.selected_cue_id = cue_id


@pytest.fixture
def page():
    page = Page()
    yield page
    page.close()
    page.deleteLater()
    APP.processEvents()


@pytest.fixture
def review(tmp_path):
    p = make_project()
    w = GlossaryProofreadPage(SimpleNamespace(studio_page=None))
    w._project = p
    w._project_path = str(tmp_path / 'work.2byteproj')
    w._standalone = _StandalonePage(p)
    w._bind_stack(w._standalone.session.undo_stack)
    w._build_rows(p, start_checks=False)
    w._snapshot = snapshot_from_pairs([('那维来特', '那维莱特')])
    yield w, p
    w._save_timer.stop()
    w._rematch_timer.stop()
    w.shutdown()
    w.close()
    w.deleteLater()
    APP.processEvents()


def test_dialog_translation_results_selected_apply_and_same_matching_rules(page):
    p = page.session.project
    dialog = FindReplaceDialog(page)
    try:
        dialog.text_targets.mode.setCurrentIndex(1)
        dialog.text_targets.track.setCurrentIndex(dialog.text_targets.track.findData('translation-records:zh-Hans'))
        dialog.find_edit.setText('那维来特')
        dialog.replace_edit.setText('那维莱特')
        dialog._do_preview()
        settle_search(dialog)
        assert dialog.preview.count() == 2
        assert all('译文' in dialog.preview.item(i).text() and '那维来特' in dialog.preview.item(i).text() for i in range(2))
        assert all('英语' not in dialog.preview.item(i).text() for i in range(2))
        dialog.preview.item(1).setCheckState(Qt.Unchecked)
        dialog._do_apply_preview()
        settle_search(dialog)
        assert sum('那维莱特' in row['text'] for row in st.records_of(p).values()) == 1
        assert page.session.undo_stack.count() == 1
        assert dialog.preview.count() == 1
        assert all('Neuvillette' in c.text for c in p.cues[:2])
        page.session.undo_stack.undo()
        assert sum('那维来特' in row['text'] for row in st.records_of(p).values()) == 2
    finally:
        dialog.close()


def test_entry_defaults_and_explicitly_hidden_track_scope(page):
    source = FindReplaceDialog(page)
    assert source.text_targets.mode_value() == 'original'
    source.close()
    page.timeline.active_subtitle_layer = 'translation'
    translated = FindReplaceDialog(page)
    assert translated.text_targets.mode_value() == 'translation'
    assert translated.text_targets.tracks() == {'translation-records:zh-Hans'}
    page.session.project.studio_state['hidden_speaker_tracks'] = ['zh-import']
    entries = scope_entries(page, 'all', mode='translation', tracks={'zh-import'})
    assert {e.target.cue_id for e in entries} == {'independent-split-1', 'independent-split-2'}
    translated.close()
    page.session.project.generation_metadata['subtitle_imports']['tracks']['zh-import']['language']=''
    all_tracks=FindReplaceDialog(page)
    all_tracks.text_targets.mode.setCurrentIndex(1)
    all_tracks.text_targets.track.setCurrentIndex(0)
    assert 'zh-import' in all_tracks.text_targets.tracks()
    assert any(e.target.cue_id=='independent-split-1' and e.target.language==''
               for e in all_tracks.text_targets.entries())
    all_tracks.close()


def test_next_uses_regex_case_and_language_selection(page):
    p = page.session.project
    dialog = FindReplaceDialog(page)
    try:
        dialog.text_targets.mode.setCurrentIndex(1)
        dialog.text_targets.track.setCurrentIndex(dialog.text_targets.track.findData('translation-records:zh-Hans'))
        dialog.find_edit.setText('(SH)(ARED)')
        dialog.replace_edit.setText(r'\2\1')
        dialog.regex_box.setChecked(True)
        dialog.case_box.setChecked(True)
        # Navigation is covered separately with the actual Studio timeline.
        dialog._page.timeline = None
        dialog._do_replace_next()
        settle_search(dialog)
        assert st.records_of(p)['source-a']['text'].startswith('AREDSH')
        assert p.cues[1].text.startswith('SHARED')
        assert st.records_of(p)['source-b']['text'].startswith('SHARED')
    finally:
        dialog.close()


@pytest.mark.xfail(strict=True, raises=AssertionError,
    reason='Known accepted-daily issue: a corrected translation row leaves the old-term search filter; clear search to inspect it. Release 1.0.0 records this limit.')
def test_ai_page_translation_apply_retains_issue_and_undo_redo(review):
    w, p = review
    w.text_targets.mode.setCurrentIndex(1)
    w.text_targets.track.setCurrentIndex(w.text_targets.track.findData('translation-records:zh-Hans'))
    w._snapshot = snapshot_from_pairs([('那维来特', '那维莱特')])
    entries = w._text_entries(p)
    result = preview_glossary_correction(review_project(p, entries), [e.key for e in entries], w._snapshot, {}, use_ai=False)
    w._show_result(result, p, False, {e.key: e.text for e in entries})
    key = next(e.key for e in entries if e.target.cue_id == 'source-a')
    row = w._by_id[key]
    assert row['target'].layer == 'translation' and row['source_text'] == p.cues[1].text
    assert len(row['issues']) == 1
    w.filter_buttons['suggested'].setChecked(True)
    w.search.setText('那维来特')
    w._apply_filter()
    w._toggle_issue(key, 0)
    assert st.records_of(p)['source-a']['text'] == 'SHARED 那维莱特出现了'
    assert len(w._by_id[key]['issues']) == 1 and w._by_id[key]['issues'][0]['checked']
    assert any(i == w._row_indexes[key] for i in w.list.visible)
    w._undo()
    assert st.records_of(p)['source-a']['text'] == 'SHARED 那维来特出现了'
    w._redo()
    assert st.records_of(p)['source-a']['text'] == 'SHARED 那维莱特出现了'
    assert len(w._by_id[key]['issues']) == 1
    assert w._row_indexes[key] in w.list.visible
    w.text_targets.mode.setCurrentIndex(0)
    assert w._by_id['source-a']['base'] == 'SHARED Neuvillette appears'


def test_ai_page_late_results_manual_edit_and_edit_undo_are_rejected(review):
    w, p = review
    w.text_targets.mode.setCurrentIndex(1)
    w.text_targets.track.setCurrentIndex(w.text_targets.track.findData('translation-records:zh-Hans'))
    w._snapshot = snapshot_from_pairs([('那维来特', '那维莱特')])
    entries = w._text_entries(p)
    texts = {e.key: e.text for e in entries}
    revisions = dict(st.translation_revisions(p))
    result = preview_glossary_correction(review_project(p, entries), list(texts), w._snapshot, {}, use_ai=False)
    before, _ = st.set_manual(p, 'source-a', '手动新译文')
    st.restore_snapshot(p, before)
    w._show_result(result, p, True, texts, revisions_at_run=revisions)
    akey = next(e.key for e in entries if e.target.cue_id == 'source-a')
    bkey = next(e.key for e in entries if e.target.cue_id == 'source-b')
    assert not w._by_id[akey]['issues']
    assert w._by_id[bkey]['issues']


def test_ignore_decisions_include_language_and_track_identity(review):
    from dataclasses import replace
    from twobyteasr.glossary.proofread_rules import decision_for, is_ignored, DECISIONS_KEY
    w,p=review
    w.text_targets.mode.setCurrentIndex(1)
    w.text_targets.track.setCurrentIndex(w.text_targets.track.findData('zh-import'))
    row=w._by_id['independent-split-1']
    issue={'kind':'term','span':(7,11),'original':'那维来特','replacement':'那维莱特'}
    p.studio_state[DECISIONS_KEY]={row['cue_id']:[decision_for(row,issue)]}
    assert is_ignored(p,row,issue)
    changed=dict(row,target=replace(row['target'],language='ja'))
    assert not is_ignored(p,changed,issue)


def test_workbench_list_edit_follows_translation_layer_without_editing_source():
    from twobyteasr.studio.studio_cue_table import CueTableModel
    p=make_project()
    model=CueTableModel(p)
    writes=[]
    model.text_edit_requested.connect(lambda key,text:writes.append(('source',key,text)))
    model.translation_edit_requested.connect(lambda key,text:writes.append(('translation',key,text)))
    model.set_text_layer('translation')
    row=model.row_for_cue_id('source-a')
    index=model.index(row,3)
    assert '那维来特' in model.data(index,Qt.DisplayRole)
    assert model.data(index,Qt.EditRole)==st.records_of(p)['source-a']['text']
    model.setData(index,'修订译文')
    assert writes==[('translation','source-a','修订译文')]
    imported=model.index(model.row_for_cue_id('independent-split-1'),3)
    model.setData(imported,'独立译文修订')
    assert writes[-1]==('source','independent-split-1','独立译文修订')
    assert next(c.text for c in p.cues if c.id=='source-a')=='SHARED Neuvillette appears'


def test_ai_page_both_language_distinct_rows_search_and_ignore(review):
    w, p = review
    w.text_targets.mode.setCurrentIndex(2)
    w.text_targets.track.setCurrentIndex(w.text_targets.track.findData('translation-records:zh-Hans'))
    w.search.setText('SHARED')
    w._apply_filter()
    assert len(w.list.visible) == 4
    assert w.replace_counts('SHARED') == (4, 4)
    before = copy.deepcopy(p.cues)
    assert w.replace_everywhere('SHARED', 'UPDATED') == 4
    assert w._standalone.session.undo_stack.count() == 1
    w._undo()
    assert p.cues == before


def test_actual_review_worker_late_result_and_cancel_preserve_manual_text(review, monkeypatch):
    w, p = review
    w.text_targets.mode.setCurrentIndex(1)
    w.text_targets.track.setCurrentIndex(w.text_targets.track.findData('translation-records:zh-Hans'))
    snapshot = snapshot_from_pairs([('那维来特', '那维莱特')])
    w._snapshot = snapshot
    monkeypatch.setattr(w, '_selected_ids', lambda: ('review-fixture',))
    monkeypatch.setattr(w, '_read_snapshot', lambda: setattr(w,'_snapshot',snapshot))
    entered, released = threading.Event(), threading.Event()
    def stand_in(*args, **kwargs):
        entered.set()
        assert released.wait(5)
        return preview_glossary_correction(*args, **kwargs, use_ai=False)
    w.ai_stand_in = stand_in
    w._run(True)
    deadline = time.monotonic()+5
    while not entered.is_set() and time.monotonic()<deadline:
        QTest.qWait(10)
    assert entered.is_set()
    st.set_manual(p, 'source-a', '手动译文保持')
    w._sync_from_project()
    released.set()
    while w._worker is not None and time.monotonic()<deadline:
        QTest.qWait(10)
    akey = next(e.key for e in w._text_entries(p) if e.target.cue_id=='source-a')
    assert not w._by_id[akey]['issues']
    assert st.records_of(p)['source-a']['text']=='手动译文保持'
    w._rematch_timer.stop()
    entered.clear()
    released.clear()
    w._run(True)
    deadline=time.monotonic()+5
    while not entered.is_set() and time.monotonic()<deadline:
        QTest.qWait(10)
    assert entered.is_set()
    before=copy.deepcopy(st.snapshot(p))
    w._cancel_run()
    released.set()
    while w._worker is not None and time.monotonic()<deadline:
        QTest.qWait(10)
    assert st.snapshot(p)==before

