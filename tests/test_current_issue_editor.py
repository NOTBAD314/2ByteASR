import os
import time
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import replace
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
from twobyteasr.subtitle_rules.studio_qc import QCIssue, QCResult, QCSeverity, QCCategory, QCEvidence
from twobyteasr.subtitle_rules.current_issues import current_issue_view, invalidate, DECISIONS
from twobyteasr.studio.caption_editor import IssueDecisionsCommand, qt_position


def wait_editor_data(page):
    deadline=time.monotonic()+2
    while (page._caption_draft is not None and
           page._caption_draft.suggestion_text != page.subtitle_edit_input.toPlainText() and
           time.monotonic()<deadline):
        QTest.qWait(10)
    assert page._caption_draft is not None
    assert page._caption_draft.suggestion_text == page.subtitle_edit_input.toPlainText()


@pytest.mark.parametrize('before,other,legacy', [('名字甲','名字乙',False),('甲一句话乙','丙一句话丁',True)])
def test_adoption_remembers_only_the_chosen_span_and_roundtrips(tmp_path,monkeypatch,before,other,legacy):
    from tests.test_review_replay_and_window_bounds import _page
    from twobyteasr.subtitle_rules.studio_qc import SubtitleQCEngine,ASREvidenceRule
    class Timing:
        def evaluate(self,cue,context):
            yield issue(cue.id,'independent_time_check',category=QCCategory.TIMELINE)
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',0,3000,before)])
    try:
        monkeypatch.setattr(page,'_finish_chunked_qc_scan',lambda *args:None)
        p=page.project
        p.asr_evidence={'segment:1':{'start_ms':0,'end_ms':3000,'text':before,'moss_text':before,'qwen_asr_text':other}}
        p.cues[0].evidence_refs=['segment:1']
        p.studio_state['caption_timeline']['instances']['a']['evidence_refs']=['segment:1']
        if legacy:
            p.studio_state['manual_caption_text']={'a':before};p.studio_state['review_confirmations']={'a':'old-confirmation'}
            p.__dict__.pop('_legacy_review_inputs',None)
        engine=SubtitleQCEngine(rules=(ASREvidenceRule(),Timing()))
        page._qc_engine=engine;p._qc_result=engine.analyze(p);invalidate(p)
        page.select_cue('a');page._open_caption_editor();QTest.qWait(40)
        # Analysis is deferred until after the new row's first layout/paint.
        # Wait for its data, rather than assuming every host paints in 40ms.
        deadline=time.monotonic()+2
        while not page._caption_draft.suggestions and time.monotonic()<deadline:
            QTest.qWait(10)
        initial=page._caption_draft.suggestions
        assert len(initial)==(2 if legacy else 1)
        chosen=initial[0];expected=chosen.apply(before)
        assert page._apply_editor_suggestion()
        assert p.cues[0].text==before
        assert page.subtitle_edit_input.toPlainText()==expected
        if legacy:assert len(page._caption_draft.suggestions)==1  # still available in the SAME draft
        assert page._submit_caption_draft()
        page._refresh_review_risks({'a'},sync=True)
        remaining=current_issue_view(p).for_cue('a')
        assert any(r.kind=='independent_time_check' for r in remaining)
        lexical=[r for r in remaining if r.kind=='model_disagreement']
        assert len(lexical)==(1 if legacy else 0)
        if lexical:assert [r.original for r in lexical[0].suggestions]==['乙']
        saved=save_project(p,tmp_path/'accepted.2byteproj');reopened=load_project(saved)
        reopened._qc_result=engine.analyze(reopened)
        assert len([r for r in current_issue_view(reopened).for_cue('a') if r.kind=='model_disagreement'])==(1 if legacy else 0)
        page.undo_stack.undo();assert p.cues[0].text==before
        page.undo_stack.redo();assert p.cues[0].text==expected
    finally:
        page.close_page();page.deleteLater()


def project():
    return SubtitleProject(media=StudioMedia(path=""), cues=[
        StudioCue('a', 1000, 2000, 'Io avrei...'),
        StudioCue('b', 2200, 5000, '词错了')])


def issue(key, kind='high_cps', severity=QCSeverity.WARNING, category=QCCategory.READABILITY):
    return QCIssue(kind, severity, category, key, kind, '具体检查对象', source='test')


def test_diagnostic_optional_and_hard_problem_have_one_exclusive_count():
    p = project()
    p._qc_result = QCResult({'a': (issue('a'), issue('a', 'segmentation_difference', QCSeverity.INFO, QCCategory.ASR)),
                            'b': (issue('b', 'invalid_time', QCSeverity.CRITICAL, QCCategory.TIMELINE),
                                  issue('b', 'line_too_long'))})
    view = current_issue_view(p)
    assert view.counts() == {'priority': 0, 'critical': 1}
    assert not view.for_cue('a') and len(view.for_cue('b')) == 2
    assert len(view.diagnostics['a']) == 2
    assert current_issue_view(p) is view  # ordinary projects have no decisions key
    p.cues[0].end_ms=20_000
    p._qc_result=QCResult({'a':(issue('a','long_duration',category=QCCategory.TIMELINE),)})
    assert current_issue_view(p).level('a')=='high'  # extreme timing is never hidden with soft advice


def test_cached_issue_view_can_be_cloned_and_exported_without_decisions(tmp_path):
    from copy import deepcopy
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts, SubtitleExportOptions
    p = project()
    p._qc_result = QCResult({'b': (issue('b', 'short_duration', category=QCCategory.TIMELINE),)})
    view = current_issue_view(p)
    assert current_issue_view(p) is view
    cloned = deepcopy(p)
    assert current_issue_view(cloned).counts() == view.counts()
    artifacts = export_subtitle_artifacts(p, tmp_path/'export', '缓存后导出', SubtitleExportOptions())
    assert artifacts and any(artifact.path.is_file() for artifact in artifacts)
    assert current_issue_view(p) is view and DECISIONS not in p.studio_state


def test_decision_survives_style_and_save_reopen_but_revalidates_relevant_text(tmp_path):
    p = project(); p._qc_result = QCResult({'b': (issue('b', 'model_disagreement', QCSeverity.CRITICAL, QCCategory.ASR),)})
    row = current_issue_view(p).for_cue('b')[0]
    command = IssueDecisionsCommand(p, {row.issue_id: {'input_version': row.input_version, 'status': 'ignored'}})
    command.redo()
    assert not current_issue_view(p).for_cue('b')
    p.cues[1].appearance_override = {'font_size': 40}
    invalidate(p)
    assert not current_issue_view(p).for_cue('b')
    path = save_project(p, tmp_path/'roundtrip.2byteproj'); reopened = load_project(path)
    reopened._qc_result = p._qc_result
    assert not current_issue_view(reopened).for_cue('b')
    p.cues[1].text = '新的文本'; invalidate(p)
    assert current_issue_view(p).for_cue('b')
    p.cues[1].text = '词错了'; command.undo()
    assert current_issue_view(p).for_cue('b')


def test_filter_members_and_counts_agree_with_layers_and_queue(tmp_path):
    from twobyteasr.studio.studio_cue_table import CueTableModel
    p = project(); p._qc_result = QCResult({'a': (issue('a', 'short_duration', category=QCCategory.TIMELINE),),
                                          'b': (issue('b', 'model_disagreement', QCSeverity.CRITICAL, QCCategory.ASR),)})
    model = CueTableModel(p)
    for mode, expected in [('priority', ['a']), ('critical', ['b'])]:
        model.set_filter(mode)
        assert [model.cue_at(i).id for i in range(model.rowCount())] == expected
        assert model.rowCount() == current_issue_view(p).counts()[mode]
    p.render_settings['_cue_domain']='timeline'
    p.cues[1].id='a#independent-copy'
    p._qc_result=QCResult({'a#independent-copy':(issue('a#independent-copy','invalid_time',QCSeverity.CRITICAL,QCCategory.TIMELINE),)})
    model.set_filter('critical')
    assert [model.cue_at(i).id for i in range(model.rowCount())]==['a#independent-copy']


def test_editor_binding_draft_cancel_layer_undo_and_pronoun_focus(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    from twobyteasr.subtitle_rules.subtitle_translation import migrate
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 1000, 2000, "l'altro è qui"), StudioCue('b', 2200, 5000, 'seconda')])
    try:
        page.project.generation_metadata['translations'] = {'a': '😀他们弹吉他，她看其他人'}
        migrate(page.project)
        page.select_cue('a'); page.timeline.set_subtitle_layer('original')
        page._remember_canvas_edit_target('a','translation')
        page._shortcut_edit_at_playhead()
        assert page._canvas_editor is page.subtitle_edit_input
        assert page._caption_draft.target.layer == 'translation'
        assert page.subtitle_edit_input.toPlainText() == '😀他们弹吉他，她看其他人'
        cursor = page.subtitle_edit_input.textCursor(); cursor.setPosition(qt_position(cursor.document().toPlainText(), 1))
        page.subtitle_edit_input.setTextCursor(cursor)
        page._flip_editor_pronoun()
        assert page.subtitle_edit_input.toPlainText() == '😀她们弹吉他，他看其他人'
        assert page.project.generation_metadata['translations']['a'] == '😀他们弹吉他，她看其他人'
        page.select_cue('b')  # a bound draft must not move with selection
        assert page._end_caption_editor(keep_open=False)
        assert page.project.generation_metadata['translations']['a'] == '😀她们弹吉他，他看其他人'
        assert page._cue_lookup['a'].text == "l'altro è qui"
        page.undo_stack.undo(); assert page.project.generation_metadata['translations']['a'] == '😀他们弹吉他，她看其他人'
        page.undo_stack.redo(); assert page.project.generation_metadata['translations']['a'].startswith('😀她们')
        page.timeline.select_translation('a'); page._shortcut_edit_at_playhead()
        page.subtitle_edit_input.setPlainText('未提交')
        page._cancel_canvas_inline_edit()
        assert page.project.generation_metadata['translations']['a'].startswith('😀她们')
        page.timeline.set_subtitle_layer('original'); page.timeline.explicit_subtitle_id = 'a'; page.timeline.set_playhead(1200); page._open_caption_editor('a','original')
        assert page.subtitle_edit_input.toPlainText() == "l'altro è qui"
        page._cancel_canvas_inline_edit()
    finally:
        page.close_page(); page.deleteLater()


def test_ignored_candidate_is_transactional_and_other_issues_remain(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 1000, 4000, '名称错了')])
    try:
        p = page.project
        monkeypatch.setattr(page, '_finish_chunked_qc_scan', lambda *args: None)
        p._qc_result = QCResult({'a': (QCIssue('model_disagreement', QCSeverity.CRITICAL, QCCategory.ASR, 'a', '候选', '具体名称',
            (QCEvidence('model', '名称对了'),)), issue('a', 'short_duration', category=QCCategory.TIMELINE))})
        invalidate(p); page.select_cue('a'); page.timeline.explicit_subtitle_id = 'a'
        page._open_caption_editor(); wait_editor_data(page)
        page._ignore_editor_suggestion()
        assert not p.studio_state.get(DECISIONS)
        assert len(current_issue_view(p).for_cue('a')) == 2
        page._cancel_canvas_inline_edit()
        page._open_caption_editor(); wait_editor_data(page)
        assert page._caption_draft.suggestions
        page._ignore_editor_suggestion(); page._submit_caption_draft()
        assert [r.kind for r in current_issue_view(p).for_cue('a')] == ['short_duration']
        page.undo_stack.undo()
        assert len(current_issue_view(p).for_cue('a')) == 2
        page.undo_stack.redo()
        assert [r.kind for r in current_issue_view(p).for_cue('a')] == ['short_duration']
    finally:
        page.close_page(); page.deleteLater()


def test_editor_refuses_changed_project_track_lock_and_external_text(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 1000, 4000, '原文本')])
    try:
        page.select_cue('a'); page.timeline.explicit_subtitle_id = 'a'; page._open_caption_editor()
        p = page.project; cue = page._cue_lookup['a']; page.subtitle_edit_input.setPlainText('草稿')
        page.timeline.locked_speakers.add(cue.speaker_id)
        assert not page._submit_caption_draft() and cue.text == '原文本'
        page.timeline.locked_speakers.clear(); cue.text = '外部修改'
        assert not page._submit_caption_draft() and cue.text == '外部修改'
        page.project = project()
        assert not page._submit_caption_draft() and cue.text == '外部修改'
        page.project = p
        page._cancel_canvas_inline_edit()
    finally:
        page.close_page(); page.deleteLater()


def test_precise_pronouns_plural_words_and_input_focus(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 1000, 4000, '他们弹吉他，她看其他人')])
    try:
        page.select_cue('a'); page.timeline.explicit_subtitle_id = 'a'; page._open_caption_editor()
        editor = page.subtitle_edit_input
        editor.moveCursor(QTextCursor.MoveOperation.Start)
        QTest.keyClick(editor, Qt.Key.Key_P)
        assert editor.toPlainText().startswith('p他们')
        editor.setPlainText('他们弹吉他，她看其他人')
        cursor = editor.textCursor(); cursor.setPosition(0); cursor.setPosition(8, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        assert page._flip_editor_pronoun()
        assert editor.toPlainText() == '她们弹吉他，他看其他人'
        cursor.setPosition(0); editor.setTextCursor(cursor)
        assert page._flip_editor_pronoun()
        assert editor.toPlainText() == '他们弹吉他，她看其他人'
        QTest.mouseClick(page.caption_pronoun_button,Qt.MouseButton.LeftButton)
        assert editor.toPlainText()=='她们弹吉他，他看其他人'
        page._cancel_canvas_inline_edit()
    finally:
        page.close_page(); page.deleteLater()


def test_standalone_import_and_overlap_keep_identity_without_fake_reference(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    from twobyteasr.projects.studio_project import StudioSpeaker
    app, page = _page(tmp_path, monkeypatch, [StudioCue('source',1000,4000,'来源原句'), StudioCue('source#independent-a', 1000, 4000, '全文 A'), StudioCue('import-b', 1000, 4000, 'Full B')])
    try:
        p = page.project
        p.studio_state['manual_caption_text']={'source':'来源原句'}
        p.speakers.extend([StudioSpeaker('track-a','S00 · 中文'), StudioSpeaker('track-b','S01 · 意大利语')])
        page._cue_lookup['source#independent-a'].speaker_id='track-a';page._cue_lookup['import-b'].speaker_id='track-b'
        p.generation_metadata['subtitle_imports']={'tracks': {'track-a':{'language':'zh','role':'translation'}, 'track-b':{'language':'it','role':'independent'}}}
        page.select_cue('source#independent-a');page.timeline.explicit_subtitle_id='source#independent-a';page.timeline.set_subtitle_layer('original')
        page._open_caption_editor()
        assert '译文' in page.subtitle_edit_title.text()
        assert not page.caption_reference.isVisible()
        page.subtitle_edit_input.setPlainText('只改 A');page._submit_caption_draft()
        assert page._cue_lookup['source#independent-a'].text=='只改 A' and page._cue_lookup['import-b'].text=='Full B'
        assert p.studio_state['manual_caption_text']['source']=='来源原句'
        page.undo_stack.undo();assert page._cue_lookup['source#independent-a'].text=='全文 A'
    finally:
        page.close_page();page.deleteLater()


def test_manual_translation_undo_preserves_another_completed_result(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    from twobyteasr.subtitle_rules import subtitle_translation as st
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',1000,2000,'Uno'),StudioCue('b',2200,4000,'Due')])
    try:
        p=page.project;p.generation_metadata['translations']={'a':'一','b':'二'};st.migrate(p)
        p.generation_metadata['translations']['a']='旧界面刚改'
        page.timeline.select_translation('a');page._open_caption_editor()
        assert page.subtitle_edit_input.toPlainText()=='旧界面刚改'
        page._cancel_canvas_inline_edit()
        page.cue_controller.set_translation('a','一个')
        untouched=st.records_of(p)['b']
        # A late result for a different subtitle is unrelated to this undo.
        st.records_of(p)['b']={**untouched,'text':'另一条已完成'}
        p.generation_metadata['translations']['b']='另一条已完成'
        page.undo_stack.undo()
        assert p.generation_metadata['translations']=={'a':'旧界面刚改','b':'另一条已完成'}
        page.undo_stack.redo()
        assert p.generation_metadata['translations']=={'a':'一个','b':'另一条已完成'}
    finally:
        page.close_page();page.deleteLater()


def test_review_removal_undo_navigation_and_filter_restart_share_scope(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',1000,2000,'第一条'),StudioCue('b',2200,4000,'第二条'),StudioCue('normal',5000,7000,'正常字幕')])
    try:
        monkeypatch.setattr(page,'_finish_chunked_qc_scan',lambda *args:None)
        p=page.project;p._qc_result=QCResult({key:(issue(key,'invalid_time',QCSeverity.CRITICAL,QCCategory.TIMELINE),)for key in ('a','b')})
        invalidate(p);page._set_review_mode(True);page.select_cue('a')
        assert page.cue_model.filter_status=='critical' and page._review_session.total==2
        page._confirm_current_review()
        assert page.selected_cue_id=='b' and page.cue_model.rowCount()==1
        assert page._review_session.total==2 and page._review_session.completed==1
        page.undo_stack.undo()
        assert page.cue_model.rowCount()==2 and page._review_session.completed==0
        page._step_priority(-1);assert page.selected_cue_id=='a'
        assert page._resolve_caption_edit_target().cue_id=='a'
        page._step_priority(1);assert page.selected_cue_id=='b'
        page._step_priority(1);assert page.selected_cue_id=='b'
        page._activate_filter('priority')
        assert page._review_session.total==1 and page.cue_model.rowCount()==1
        assert page.selected_cue_id=='b' and current_issue_view(p).counts()['priority']==0
        page._activate_filter('all')
        assert page._review_session.total==3 and page.cue_model.rowCount()==3
    finally:
        page.close_page();page.deleteLater()


def test_editor_click_shift_r_ime_and_unicode_stale_candidates(tmp_path, monkeypatch):
    from tests.test_review_replay_and_window_bounds import _page
    app, page = _page(tmp_path, monkeypatch, [StudioCue('a', 1000, 4000, '😀那维来特')])
    try:
        p = page.project
        monkeypatch.setattr(page, '_finish_chunked_qc_scan', lambda *args: None)
        p._qc_result = QCResult({'a': (QCIssue('model_disagreement', QCSeverity.CRITICAL, QCCategory.ASR, 'a', '名称不同', '候选名称',
            (QCEvidence('model', '😀那维莱特'),)),)})
        invalidate(p); page.select_cue('a'); page.timeline.explicit_subtitle_id = 'a'; page.timeline.set_playhead(1200); page._shortcut_edit_at_playhead()
        app.processEvents(); QTest.qWait(40)
        assert len(page._caption_draft.suggestions) == 1
        assert page._apply_editor_suggestion()
        assert page.subtitle_edit_input.toPlainText() == '😀那维莱特'
        assert page._cue_lookup['a'].text == '😀那维来特'
        assert page._canvas_editor is not None
        page._cancel_canvas_inline_edit()
        assert current_issue_view(p).for_cue('a')
        page._shortcut_edit_at_playhead(); QTest.qWait(40)
        QApplication.sendEvent(page.subtitle_edit_input, QInputMethodEvent('拼音', []))
        QTest.keyClick(page.subtitle_edit_input, Qt.Key.Key_R, Qt.KeyboardModifier.ShiftModifier)
        assert '那维来特' in page.subtitle_edit_input.toPlainText()
        QApplication.sendEvent(page.subtitle_edit_input, QInputMethodEvent('', []))
        page.subtitle_edit_input.setPlainText('😀那维来特')
        # Candidate Space adopts; Shift+R always submits and resumes follow.
        QTest.keyClick(page.subtitle_edit_input, Qt.Key.Key_W, Qt.KeyboardModifier.ShiftModifier)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Space)
        assert page.subtitle_edit_input.toPlainText() == '😀那维莱特'
        page._cancel_canvas_inline_edit(); page._shortcut_edit_at_playhead()
        page.subtitle_edit_input.insertPlainText('x')
        assert not page._apply_editor_suggestion()
        assert page._cue_lookup['a'].text == '😀那维来特'
        QApplication.sendEvent(page.subtitle_edit_input,QInputMethodEvent('未提交组合',[]))
        page._cancel_canvas_inline_edit()
        assert not page.subtitle_edit_input._preediting and not page._studio_ime_composing
    finally:
        page.close_page(); page.deleteLater()
