"""Opt-in normal-entry audit of the complete copied Italian project."""
import dataclasses
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, QObject, QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .studio_acceptance_audit import require
    from .blank_project_audit import _capture

    output = Path(output)
    baseline = os.environ.get('REVIEW_EDITOR_BASELINE') == '1'
    try:
        page = window.studio_page
    except RuntimeError:
        QTimer.singleShot(100, lambda: start(window, output))
        return
    result = dict(checks=[], samples=[], passed=False, baseline=baseline, pid=os.getpid(),
                  executable=sys.executable, frozen=bool(getattr(sys, 'frozen', False)))
    clock = time.perf_counter
    started = clock()
    heartbeat = []
    last = [clock()]
    timer = QTimer(window)
    def beat():
        now = clock(); heartbeat.append((now-last[0])*1000); last[0] = now
    timer.timeout.connect(beat); timer.start(16)

    def receipt():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

    def check(name, condition, detail=None, *, required=True):
        result['checks'].append(dict(name=name, passed=bool(condition), detail=detail))
        receipt()
        if required and not baseline:
            require(condition, name)

    def wait(predicate, seconds=60):
        deadline = clock()+seconds
        while not predicate() and clock() < deadline:
            QTest.qWait(20)
        require(predicate(), 'wait condition timed out')

    def shot(name):
        QTest.qWait(100)
        _capture(window, output/(name+'.png'))
        page.subtitle_edit_card.grab().save(str(output/(name+'-editor.png')))

    def edit_key(cue, translation):
        if translation:
            page.timeline.select_translation(cue.id)
        else:
            page.timeline.set_subtitle_layer('original')
            page.select_cue(cue.id)
            page.timeline.explicit_subtitle_id = cue.id
        page.timeline.setFocus()
        t = clock()
        if os.environ.get('REVIEW_EDITOR_PROFILE') == '1':
            import cProfile, pstats
            profile=cProfile.Profile()
            profile.runcall(QTest.keyClick,page.timeline,Qt.Key.Key_E)
            with (output/f'profile-e-{cue.id}-{translation}.txt').open('w',encoding='utf8') as stream:
                pstats.Stats(profile,stream=stream).sort_stats('cumtime').print_stats(40)
        else:
            QTest.keyClick(page.timeline, Qt.Key.Key_E)
        editor = getattr(page, '_canvas_editor', None) or getattr(page.timeline, '_inline_editor', None)
        wait(lambda: editor is not None and editor.isVisible() and editor.hasFocus(), 10)
        return editor, (clock()-t)*1000

    def cancel():
        if getattr(page, '_canvas_editor', None) is not None:
            page._cancel_canvas_inline_edit()
        elif page.timeline._inline_editor is not None:
            page.timeline._cancel_inline_edit()

    def execute():
        try:
            wait(lambda: page.project is not None and page._readiness.ready, 120)
            window.resize(1600, 950); window.show(); QApplication.setActiveWindow(window)
            page.video.set_paused(True)
            p = page.project
            result['first_ready_ms'] = (clock()-started)*1000
            result['project'] = dict(id=p.project_id, originals=len(p.cues),
                translations=len(p.generation_metadata.get('translations', {})),
                size=[window.width(), window.height()], dpr=window.devicePixelRatioF())
            check('complete_real_project', p.project_id == 'd207fb158ba44d5baf28700ed9ca5904' and len(p.cues) == 1392)
            if not baseline:
                result['qc_pending_at_first_review']=not hasattr(p,'_qc_result')
                page._set_review_mode(True)
            wait(lambda: hasattr(p, '_qc_result'), 120)
            if not baseline:
                from ..subtitle_rules.current_issues import current_issue_view
                view = current_issue_view(p)
                wait(lambda: page._review_mode, 10)
                check('default_review_uses_actual_issue_scope',page.cue_model.filter_status=='critical'
                      and page._review_session.total==view.counts()['critical'])
                page._set_review_mode(False)
                result['classification'] = dict(counts=view.counts(), reasons=view.statistics())
                (output/'issues.json').write_text(json.dumps([dataclasses.asdict(r) for r in view.records], ensure_ascii=False, indent=2), encoding='utf8')
                for mode in ('priority', 'critical'):
                    page._activate_filter(mode)
                    check(mode+'_membership_equals_count', page.cue_model.rowCount() == view.counts()[mode],
                          dict(rows=page.cue_model.rowCount(), button=page.cue_filter_buttons[mode].text()))
                page._activate_filter('priority')
                initial = page.cue_model.rowCount()
                page._set_review_mode(True)
                check('review_denominator_is_selected_set', page._review_session.total == initial)
                ids = [page.cue_model.cue_at(i).id for i in range(min(4, initial))]
                if len(ids) >= 3:
                    page.select_cue(ids[0]); page.timeline.setFocus()
                    for key, expected in ((Qt.Key.Key_W, ids[1]), (Qt.Key.Key_D, ids[2]),
                                          (Qt.Key.Key_S, ids[1]), (Qt.Key.Key_A, ids[0])):
                        QTest.keyClick(page.timeline, key)
                        check('navigation_'+key.name, page.selected_cue_id == expected, page.selected_cue_id)
                    before = page.selected_cue_id
                    page.cue_search.setFocus(); QTest.keyClicks(page.cue_search, 'wdsap')
                    check('search_letters_are_input', page.cue_search.text() == 'wdsap' and page.selected_cue_id == before)
                    page.cue_search.clear()
                page._set_review_mode(False)
            page._activate_filter('all')
            cue = next(c for c in p.cues if c.id == '544')
            page._seek(cue.start_ms/1000)
            page.timeline.set_visible_window(cue.start_ms-5000, 30000)
            page.timeline.vertical_scrollbar.setValue(page.timeline.vertical_scrollbar.maximum())
            page.timeline._sync_scrollbars(); page.timeline.update(); QTest.qWait(300)
            shot('00-complete-project')
            rect = page.timeline._track_layout()[1]
            point = QPoint(round(page.timeline._time_to_x(cue.start_ms+200)), round(rect.center().y()))
            QTest.mouseClick(page.timeline, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            check('translation_mouse_selection', page.timeline.active_subtitle_layer == 'translation',
                  dict(point=[point.x(), point.y()], layer=page.timeline.active_subtitle_layer))
            editor, elapsed = edit_key(cue, True)
            result['translation_e_first_ms'] = elapsed
            check('translation_e_uses_independent_editor', editor is page.subtitle_edit_input)
            check('translation_full_current_text', editor.toPlainText() == p.generation_metadata['translations'][cue.id])
            shot('01-translation-edit')
            cancel()
            if not baseline:
                # Existing preview language selector / measured selection box
                # is an explicit target, even with an old original list focus.
                page.timeline.set_subtitle_layer('original');page.select_cue(cue.id)
                page._seek((cue.start_ms+200)/1000);QTest.qWait(250)
                panel=page.caption_transform_panel
                panel.language.setCurrentIndex(panel.language.findData('translation'))
                page._load_style_inspector();page.ensure_active_subtitle_renderer(reason='review-editor-preview-pick')
                wait(lambda: page.position_overlay.isVisible() and page.position_overlay._measured_bounds is not None,20)
                scope=page.selection_model.scope;undo_at=page.undo_stack.index()
                QTest.mouseClick(page.position_overlay,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,
                                 page.position_overlay._subtitle_rect().center().toPoint())
                check('preview_click_preserves_scope_and_does_not_transform',page.selection_model.scope==scope and page.undo_stack.index()==undo_at)
                QTest.keyClick(page.position_overlay,Qt.Key.Key_E)
                wait(lambda: getattr(page,'_caption_draft',None) is not None,10)
                check('preview_translation_e_ignores_original_residue',page._caption_draft.target.layer=='translation'
                      and page.subtitle_edit_input.toPlainText()==p.generation_metadata['translations'][cue.id])
                shot('01b-preview-translation-edit');cancel()
                panel.language.setCurrentIndex(panel.language.findData('original'))
                page.timeline.set_subtitle_layer('translation')
                # A real click in the list supersedes the previous preview /
                # translation target and opens the complete original text.
                index=page.cue_model.index(0,3)
                page.cue_table.scrollTo(index);QTest.qWait(60)
                QTest.mouseClick(page.cue_table.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,
                                 page.cue_table.visualRect(index).center())
                QTest.keyClick(page.cue_table,Qt.Key.Key_E)
                wait(lambda: getattr(page,'_caption_draft',None) is not None,10)
                first=page.cue_model.cue_at(0)
                check('list_original_e_supersedes_translation',page._caption_draft.target.layer=='original'
                      and page._caption_draft.target.cue_id==first.id and page.subtitle_edit_input.toPlainText()==first.text)
                cancel();page._seek(cue.start_ms/1000);QTest.qWait(300)
            # The ordinary sequence is measured on the complete project with
            # bilingual display. No fixture replaces the measured subtitles.
            for i, c in enumerate(p.cues[536:538] if os.environ.get('REVIEW_EDITOR_PROFILE')=='1' else p.cues[536:548]):
                for translation in (True, False):
                    if translation and c.id not in p.generation_metadata['translations']:
                        continue
                    editor, elapsed = edit_key(c, translation)
                    before = editor.toPlainText()
                    t = clock(); QTest.keyClicks(editor, 'q')
                    check('input_'+c.id+str(translation), editor.toPlainText() == before+'q')
                    result['samples'].append(dict(cue=c.id, layer='translation' if translation else 'original',
                        e_input_ms=elapsed, input_ms=(clock()-t)*1000))
                    cancel(); QTest.qWait(60)
            if not baseline:
                from ..subtitle_rules.current_issues import current_issue_view, invalidate
                candidate_issue = next((r for r in current_issue_view(p).records if r.disposition == 'actionable' and r.layer == 'original' and r.suggestions), None)
                restore_qc = None
                result['candidate_origin'] = 'current stored evidence'
                if candidate_issue is None:
                    # This original project has no reliable current lexical
                    # patch after neighbor-context correction. Explicitly seed
                    # ONE offline interaction fixture; never call it real ASR.
                    from ..subtitle_rules.studio_qc import QCResult,QCIssue,QCSeverity,QCCategory,QCEvidence
                    restore_qc = p._qc_result
                    fixture_cue = page._cue_lookup['544']
                    candidate_text = fixture_cue.text.replace('voi','noi',1)
                    fixture = QCIssue('model_disagreement',QCSeverity.WARNING,QCCategory.ASR,fixture_cue.id,
                        '离线交互夹具','只用于核验局部替换与取消，不代表原片错字。',
                        (QCEvidence('离线交互夹具',candidate_text),),source='offline-editor-fixture')
                    p._qc_result = QCResult({**restore_qc.issues_by_cue,fixture_cue.id:(fixture,)})
                    invalidate(p)
                    candidate_issue = next(r for r in current_issue_view(p).for_cue(fixture_cue.id) if r.suggestions)
                    result['candidate_origin'] = 'explicit offline fixture on copied cue 544; QC restored afterwards'
                check('valid_local_candidate_is_available', candidate_issue is not None)
                if candidate_issue:
                    c = page._cue_lookup[candidate_issue.cue_id]
                    page._seek(c.start_ms/1000); QTest.qWait(300)
                    editor, _ = edit_key(c, False)
                    bar = page.caption_suggestion_text
                    wait(lambda: bool(page._caption_draft.suggestions))
                    suggestion = page._caption_draft.suggestions[0]
                    expected = suggestion.apply(c.text)
                    t=clock()
                    if hasattr(bar, 'candidate_button'):
                        QTest.mouseClick(bar.candidate_button(0,0),Qt.MouseButton.LeftButton)
                    else:
                        layout = bar._layout(bar.contentsRect().width())
                        chip = layout.marks[0].chips[0]
                        pt = chip.rect.center()+QPointF(bar.contentsRect().left(), bar.contentsRect().top()+bar._offset(layout))
                        QTest.mouseClick(bar,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,pt.toPoint())
                    click_ms=(clock()-t)*1000
                    check('real_candidate_click_updates_draft_only', editor.toPlainText() == expected and c.text == candidate_issue.text)
                    shot('02-real-candidate-applied')
                    cancel(); editor,_=edit_key(c,False)
                    wait(lambda: bool(page._caption_draft.suggestions), 5)
                    QTest.keyClick(editor,Qt.Key.Key_W,Qt.KeyboardModifier.ShiftModifier)
                    t=clock(); QTest.keyClick(QApplication.focusWidget(),Qt.Key.Key_R,Qt.KeyboardModifier.ShiftModifier)
                    result['candidate_ms'] = dict(click=click_ms, shift_r=(clock()-t)*1000)
                    check('shift_r_equals_click_stays_open', editor.toPlainText() == expected and page._canvas_editor is editor)
                    cancel()
                if restore_qc is not None:
                    p._qc_result=restore_qc;invalidate(p)
                # A real Chinese translation with a pronoun, chosen without
                # inferring anyone's gender from the video.
                from ..subtitle_rules.pronouns import pronoun_positions
                text_by_id=p.generation_metadata['translations']
                pronoun_cue=next(c for c in p.cues if pronoun_positions(text_by_id.get(c.id,'')))
                editor,_=edit_key(pronoun_cue,True)
                text=editor.toPlainText(); at=pronoun_positions(text)[0]
                from ..studio.caption_editor import qt_position
                cursor=editor.textCursor();cursor.setPosition(qt_position(text,at));editor.setTextCursor(cursor)
                t=clock();QTest.keyClick(editor,Qt.Key.Key_P,Qt.KeyboardModifier.ShiftModifier)
                result['pronoun_ms']=(clock()-t)*1000
                check('shift_p_changes_only_target_pronoun', editor.toPlainText()!=text and text_by_id[pronoun_cue.id]==text)
                page.caption_pronoun_button.setFocus()
                QTest.keyClick(page.caption_pronoun_button,Qt.Key.Key_P,Qt.KeyboardModifier.ShiftModifier)
                check('operation_focus_shift_p_toggles_back', editor.toPlainText()==text)
                editor.setFocus();QTest.keyClicks(editor,'p')
                check('text_focus_p_is_literal', 'p' in editor.toPlainText())
                cancel()
                editor,_=edit_key(cue,True)
                original=cue.text;before=editor.toPlainText();value=before+' [验收]'
                editor.setPlainText(value)
                # Changing the active selection must not change the bound
                # destination, even while preview tasks are in flight.
                page.select_cue(p.cues[600].id)
                t=clock();QTest.keyClick(editor,Qt.Key.Key_Return)
                result['submit_ms']=(clock()-t)*1000
                check('enter_commits_bound_translation', p.generation_metadata['translations'][cue.id]==value and cue.text==original)
                page.undo_stack.undo();check('undo_restores_translation',p.generation_metadata['translations'][cue.id]==before)
                page.undo_stack.redo();check('redo_restores_translation',p.generation_metadata['translations'][cue.id]==value)
                # A formal save must include the translation and stable layer
                # identity before reporting durable success.
                source_rows=[(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id) for c in p.cues]
                t=clock();save_beat=len(heartbeat)
                if os.environ.get('REVIEW_EDITOR_PROFILE') == '1':
                    import cProfile,pstats
                    from ..projects import studio_save
                    original_save=studio_save.save_project_revision
                    def profiled_writer(*args,**kwargs):
                        profile=cProfile.Profile()
                        try:return profile.runcall(original_save,*args,**kwargs)
                        finally:
                            with (output/'profile-save-worker.txt').open('w',encoding='utf8') as stream:
                                pstats.Stats(profile,stream=stream).sort_stats('cumtime').print_stats(45)
                    studio_save.save_project_revision=profiled_writer
                    profile=cProfile.Profile()
                    try:profile.runcall(page.save)
                    finally:
                        studio_save.save_project_revision=original_save
                        with (output/'profile-save-gui.txt').open('w',encoding='utf8') as stream:
                            pstats.Stats(profile,stream=stream).sort_stats('cumtime').print_stats(40)
                else:
                    page.save()
                result['save_ms']=(clock()-t)*1000
                result['save_heartbeat_ms']=heartbeat[save_beat:]
                saved_path=page.project_path
                disk=json.loads(Path(saved_path).read_text(encoding='utf8'))
                check('save_is_durable_before_return',disk['generation_metadata']['translations'][cue.id]==value and page.undo_stack.isClean())
                shot('03-after-transactions')
                worker=getattr(page,'_qc_worker',None)
                result['qc_workers']=[]
                if worker and worker.snapshot()['pid']:result['qc_workers'].append(worker.snapshot()['pid'])
                # Closing with an uncommitted draft revokes delayed preview and
                # suggestion callbacks. Reopening is the same real input copy.
                editor,_=edit_key(cue,True);editor.setPlainText('不能写入重开的工程')
                old_generation=page.session.generation
                # The probe must not retain the entire closed project while
                # measuring normal reopening and object retirement.
                p=None;restore_qc=None
                t=clock();page._close_project_session('review-editor-audit');page.open_project(saved_path)
                wait(lambda: page.project is not None and page.session.generation>old_generation and page._readiness.ready,120)
                result['hot_reopen_ms']=(clock()-t)*1000
                restored=page.project
                wait(lambda: hasattr(restored,'_qc_result'),120)
                check('reopen_preserves_source_identity_and_timing',[(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id)for c in restored.cues]==source_rows)
                check('reopen_preserves_bound_translation',restored.generation_metadata['translations'][cue.id]==value)
                check('late_editor_callback_does_not_restore_draft',getattr(page,'_caption_draft',None) is None)
                worker=getattr(page,'_qc_worker',None)
                # Close while a fresh real QC request is still owned by this
                # page. No provider/model request is involved.
                page._start_chunked_qc_scan()
                QTest.qWait(20)
                worker=getattr(page,'_qc_worker',None)
                result['qc_worker_before_close']=worker.snapshot() if worker else None
                if worker and worker.snapshot()['pid']:result['qc_workers'].append(worker.snapshot()['pid'])
                result['closed_with_fresh_qc_request']=True
            from .blank_project_audit import _provider_calls
            check('no_provider_requests',not _provider_calls)
            result['heartbeat_ms'] = heartbeat
            result['passed'] = all(x['passed'] for x in result['checks']) if not baseline else True
        except BaseException:
            result['error']=traceback.format_exc()
            result['passed']=False
        finally:
            timer.stop();receipt()
            def stopped():
                result['gui_shutdown']=True;receipt()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.result_exit_code=0 if result['passed'] else 1
            # The audit restores all committed changes. Normal close is still
            # responsible for saving session state and process teardown.
            window.close()
    QTimer.singleShot(150,execute)
