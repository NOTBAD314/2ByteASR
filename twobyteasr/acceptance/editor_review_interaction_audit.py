"""Opt-in normal MainWindow verification; all media and data belong to the runner."""
import json, os, time, traceback
from pathlib import Path

def start(window, output):
    from PySide6.QtCore import QEvent, QTimer, Qt
    from PySide6.QtGui import QKeyEvent, QInputMethodEvent, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..studio.caption_editor import qt_position
    app = QApplication.instance(); output = Path(output)
    result = dict(passed=False, checks={}, limitations=['Owned synthetic video and evidence, no cloud/model calls',
        'Qt IME events, not physical input method; process scale, not physical multi-monitor DPI'])
    def save(): (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    def check(name, value):
        result['checks'][name] = bool(value); save()
        if not value: raise AssertionError(name)
    def wait(predicate, seconds=60):
        end = time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate(): return
            app.processEvents(); time.sleep(.003)
        raise TimeoutError('editor review readiness')
    def focus(widget):
        QApplication.setActiveWindow(widget.window()); widget.setFocus(); app.processEvents()
    def shift(widget, key): QTest.keyClick(widget, key, Qt.ShiftModifier)
    def select(editor, start, end=None):
        cursor = editor.textCursor(); text = editor.toPlainText()
        cursor.setPosition(qt_position(text, start))
        if end is not None: cursor.setPosition(qt_position(text,end), QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
    def open_editor(page, layer='original', cue='a'):
        page._open_caption_editor(cue,layer); page._lock_caption_editor()
        focus(page.subtitle_edit_input); QTest.qWait(80); focus(page.subtitle_edit_input)
        return page.subtitle_edit_input
    def run():
        try:
            from ..design.theme_manager import apply_theme
            from ..projects.studio_project import save_project, load_project
            page = window.studio_page; window._switch_page(page)
            page.project_controller.open_project_entry(os.environ['TWOBYTEASR_STARTUP_PROJECT'],
                single_shot_fn=QTimer.singleShot,skip_dirty_guard=True)
            wait(lambda:page.project is not None and page._readiness.ready)
            wait(lambda:not page._readiness.overlay.isVisible())
            page.video.set_paused(True)
            result['dpr'] = page.devicePixelRatioF()
            before = page.project.cues[0].text
            from ..recognition import cue_word_alignment
            from ..timeline import studio_timing
            page.select_cue('a')
            cue = page.project.cues[0]
            previous_timing = (cue.start_ms, cue.end_ms)
            measured = studio_timing.measured_words
            studio_timing.measured_words = lambda project, item: ((
                cue_word_alignment.AlignedWord('她', 0, 1, 650, 800, 'audit'),
                cue_word_alignment.AlignedWord('西', 6, 7, 4200, 4300, 'audit'),
            ), 'exact_token_text')
            try:
                index = page.undo_stack.index()
                page._smart_align_current()
                check('smart alignment follows measured words and preserves text',
                      (cue.start_ms, cue.end_ms) == (650, 4420) and cue.text == before
                      and page.undo_stack.index() == index + 1)
                page.undo_stack.undo()
                check('smart alignment is reversible with a single undo',
                      (cue.start_ms, cue.end_ms) == previous_timing)
            finally:
                studio_timing.measured_words = measured
            page._seek(4.5)
            wait(lambda: 4300 <= page.timeline.playhead_ms < 5000)
            page.select_cue('a')
            page._remember_canvas_edit_target('a', 'original')
            page.video.set_paused(False)
            wait(lambda: 5200 <= page.timeline.playhead_ms < 9000, seconds=15)
            focus(page.timeline)
            QTest.keyClick(page.timeline, Qt.Key_E)
            wait(lambda: page._caption_draft is not None, seconds=5)
            check('E follows true playback on first opening',
                  page._caption_draft.target.cue_id == 'b'
                  and page.subtitle_edit_input.toPlainText() == page.project.cues[1].text)
            page.subtitle_edit_dock.grab().save(str(output/'e-playhead-caption.png'))
            page._cancel_canvas_inline_edit()
            page._seek(6.0)
            wait(lambda: 5900 <= page.timeline.playhead_ms <= 6100)
            page.select_cue('a')
            page._remember_canvas_edit_target('a', 'translation')
            focus(page.timeline)
            QTest.keyClick(page.timeline, Qt.Key_E)
            wait(lambda: page._caption_draft is not None, seconds=5)
            check('E preserves fresh explicit translation selection',
                  page._caption_draft.target.cue_id == 'a'
                  and page._caption_draft.target.layer == 'translation')
            page._cancel_canvas_inline_edit()
            page.timeline.set_subtitle_layer('original')
            for theme in ('sand','midnight'):
                apply_theme(theme,app)
                for at in (0,len(before),7):
                    e = open_editor(page); select(e,at); pos=e.textCursor().position()
                    for value in '它他她':
                        shift(e,Qt.Key_F)
                        result['last_focus'] = dict(caret=e.textCursor().position(),expected=pos,
                            selection=e.textCursor().selectedText(),focused=e.hasFocus(),
                            focus=type(QApplication.focusWidget()).__name__,active=type(QApplication.activeWindow()).__name__)
                        check(f'{theme} caret {at} immediate {value}',e.toPlainText()==value+before[1:])
                        check(f'{theme} caret {at} focus {value}',e.hasFocus() and e.textCursor().position()==pos and not e.textCursor().hasSelection())
                    page.subtitle_edit_dock.grab().save(str(output/f'editor-{theme}-{at}.png'))
                    QTest.keyClick(e,Qt.Key_Escape)
                    check(f'{theme} cancelled {at}',page.project.cues[0].text==before and page._caption_draft is None)
            for owner in ('body','toolbar','candidate','review'):
                e=open_editor(page);select(e,7);shift(e,Qt.Key_F);expected=e.toPlainText()
                if owner=='toolbar':target=page.caption_pronoun_button
                elif owner=='candidate':
                    page._show_editor_pronouns();target=QApplication.focusWidget()
                    shift(target,Qt.Key_D);target=QApplication.focusWidget()
                elif owner=='review':
                    page._review_all_explicit=(page.project.project_id,page.session.generation)
                    page._set_review_mode(True);target=page.review_mode_button
                else:target=e
                focus(target);shift(target,Qt.Key_E)
                check(owner+' single confirm',page._caption_draft is None and not page.subtitle_edit_dock.isVisible() and page.project.cues[0].text==expected)
                e=open_editor(page);check(owner+' reopen',e.toPlainText()==expected)
                page._cancel_canvas_inline_edit();page.undo_stack.undo()
                if page._review_mode:page._set_review_mode(False)
            # The real modal opens from the normal E editor shortcut.
            from ..studio.studio_find_replace import FindReplaceDialog
            from PySide6.QtGui import QKeySequence
            from ..studio.shortcut_registry import platform_defaults
            for shortcut in ('find', 'find_replace'):
                keys = QKeySequence(platform_defaults()[shortcut])[0]
                editor = open_editor(page)
                select(editor, len(editor.toPlainText()))
                editor.insertPlainText('新')
                select(editor, 0, 2)
                modal_result = {}

                def read_modal():
                    dialog = QApplication.activeModalWidget()
                    if not isinstance(dialog, FindReplaceDialog) or not dialog.isVisible():
                        return
                    modal_result.update(
                        find=dialog.find_edit.text(),
                        replacement=dialog.replace_edit.text(),
                        focus=dialog.focusWidget() is dialog.replace_edit,
                        committed=page.project.cues[0].text,
                        draft_closed=page._caption_draft is None,
                        screenshot=dialog.grab().save(str(output/f'editor-{shortcut}.png')),
                    )
                    dialog.reject()

                poll = QTimer()
                poll.setInterval(30)
                poll.timeout.connect(read_modal)
                poll.start()
                try:
                    QTest.keyClick(editor, keys.key(), keys.keyboardModifiers())
                    wait(lambda: bool(modal_result), seconds=8)
                    check(f'{shortcut} opens find with selection', modal_result['find'] == before[:2])
                    check(f'{shortcut} focuses empty replacement', modal_result['focus'] and not modal_result['replacement'])
                    check(f'{shortcut} commits and closes draft', modal_result['committed'] == before+'新' and modal_result['draft_closed'])
                    check(f'{shortcut} captured real modal', modal_result['screenshot'])
                    page.undo_stack.undo()
                    check(f'{shortcut} committed draft undoes once', page.project.cues[0].text == before)
                finally:
                    poll.stop()
            for trigger in ('enter','shift_e','button'):
                e=open_editor(page);shift(e,Qt.Key_F);expected=e.toPlainText();index=page.undo_stack.index()
                if trigger=='enter':QTest.keyClick(e,Qt.Key_Return)
                elif trigger=='shift_e':shift(e,Qt.Key_E)
                else:page.caption_confirm_button.click()
                check(trigger+' equivalent confirm',page._caption_draft is None and page.project.cues[0].text==expected and page.undo_stack.index()==index+1)
                page.undo_stack.undo();check(trigger+' undo',page.project.cues[0].text==before)
                page.undo_stack.redo();check(trigger+' redo',page.project.cues[0].text==expected)
                page.undo_stack.undo()
            original_translation=page.project.generation_metadata['translations']['a']
            e=open_editor(page,'translation');select(e,len(e.toPlainText()));shift(e,Qt.Key_F)
            check('translation plural and original isolated',e.toPlainText()=='它们会来吗' and page.project.cues[0].text==before)
            shift(e,Qt.Key_E)
            check('translation committed alone',page.project.generation_metadata['translations']['a']=='它们会来吗' and page.project.cues[0].text==before)
            page.undo_stack.undo()
            e=open_editor(page,cue='b');select(e,3,4);shift(e,Qt.Key_F);select(e,len(e.toPlainText()))
            shift(e,Qt.Key_F);check('multi target remains one plural',e.toPlainText().startswith('他告诉他们'))
            select(e,0,1);shift(e,Qt.Key_F);check('explicit target changes only one',e.toPlainText().startswith('她告诉他们'))
            page._cancel_canvas_inline_edit()
            e=open_editor(page);e.setPlainText('其他人弹吉他');select(e,4);shift(e,Qt.Key_F)
            check('no valid pronoun quiet ignore',e.toPlainText()=='其他人弹吉他')
            e.setPlainText(before);select(e,7);shift(e,Qt.Key_F);value=e.toPlainText()
            QApplication.sendEvent(e,QKeyEvent(QEvent.KeyPress,Qt.Key_F,Qt.ShiftModifier,'F',True))
            check('auto repeat ignored',e.toPlainText()==value)
            shift(e,Qt.Key_S);shift(e,Qt.Key_S)
            check('S always returns without inserting letters',e.toPlainText()==value and e.hasFocus())
            QApplication.sendEvent(e,QInputMethodEvent('ni',[]));shift(e,Qt.Key_F)
            check('preedit preserves text',e._preediting and e.toPlainText()==value)
            shift(e,Qt.Key_E);check('preedit confirm does not submit draft',page._caption_draft is not None)
            page._cancel_canvas_inline_edit()
            # Known offline recognizer alternatives exercise the actual card,
            # hit testing, command, QC refresh and undo paths.
            from ..studio import studio_review_ui
            from ..subtitle_rules.studio_qc import QCCandidate
            page.cue_controller.set_text('a','坏猫在这里等错狗')
            original_candidates=studio_review_ui.review_candidates
            studio_review_ui.review_candidates=lambda project,cue:(QCCandidate(cue.text,('Current',)),
                QCCandidate('可爱猫在这里等好狗',())) if cue.id=='a' else (QCCandidate(cue.text,('Current',)),)
            try:
                page._refresh_review_risks(sync=True)
                page._review_all_explicit=(page.project.project_id,page.session.generation)
                page._set_review_mode(True);page.select_cue('a');page._refresh_review_summary_strip();QTest.qWait(120)
                card=page._review_inline_card;clock=page.timeline.playhead_ms
                page.review_dock_scroll.verticalScrollBar().setValue(8)
                scroll=page.review_dock_scroll.verticalScrollBar().value()
                stale=page._review_suggestions_binding
                window.grab().save(str(output/'review-before.png'))
                def red_click():
                    rect=card.text_label.chip_rects()[(0,0)]
                    point=card.text_label.mapTo(card,rect.center().toPoint())
                    QTest.mouseClick(card,Qt.LeftButton,Qt.NoModifier,point)
                    app.processEvents()
                    return point
                first_point=red_click()
                check('red click local text',page.project.cues[0].text=='可爱猫在这里等错狗')
                check('red click stays review without editor',page._review_mode and page._caption_draft is None and not page.subtitle_edit_dock.isVisible())
                check('review card scroll clock stable',page._review_inline_card is card and page.selected_cue_id=='a' and page.timeline.playhead_ms==clock and page.review_dock_scroll.verticalScrollBar().value()==scroll)
                check('length change remaining offset',len(page._review_suggestions)==1 and page._review_suggestions[0].start==7)
                index=page.undo_stack.index();check('stale click ignored',not page._apply_review_suggestion(0,binding=stale) and page.undo_stack.index()==index)
                QTest.mouseClick(card,Qt.LeftButton,Qt.NoModifier,first_point);app.processEvents()
                QTest.mouseDClick(card,Qt.LeftButton,Qt.NoModifier,first_point);app.processEvents()
                check('repeated first red pixel does not confirm or advance',page.undo_stack.index()==index and page.selected_cue_id=='a' and page.project.cues[0].text=='可爱猫在这里等错狗')
                last_point=red_click();check('last suggestion keeps surface',page.project.cues[0].text=='可爱猫在这里等好狗' and not page._review_suggestions and page._review_inline_card is card and not page.subtitle_edit_dock.isVisible())
                index=page.undo_stack.index();QTest.mouseClick(card,Qt.LeftButton,Qt.NoModifier,last_point);app.processEvents()
                QTest.mouseDClick(card,Qt.LeftButton,Qt.NoModifier,last_point);app.processEvents()
                check('repeated last red pixel does not confirm or advance',page.undo_stack.index()==index and page.selected_cue_id=='a' and page.project.cues[0].text=='可爱猫在这里等好狗')
                window.grab().save(str(output/'review-last.png'))
                page.undo_stack.undo();check('red undo one patch',page.project.cues[0].text=='可爱猫在这里等错狗')
                page.undo_stack.redo();check('red redo one patch',page.project.cues[0].text=='可爱猫在这里等好狗')
                for pending in (False,True):
                    if pending:page.undo_stack.undo()
                    for trigger in ('enter','shift_e','button','esc','header','window','return'):
                        e=open_editor(page);baseline=e.toPlainText();e.insertPlainText('改')
                        if trigger=='enter':QTest.keyClick(e,Qt.Key_Return)
                        elif trigger=='shift_e':shift(e,Qt.Key_E)
                        elif trigger=='button':page.caption_confirm_button.click()
                        elif trigger=='esc':QTest.keyClick(e,Qt.Key_Escape)
                        elif trigger=='header':page.caption_close_button.click()
                        elif trigger=='window':page.subtitle_edit_dock.close()
                        else:page._set_review_mode(False)
                        check(f'manual {pending} {trigger} closes',page._caption_draft is None and not page.subtitle_edit_dock.isVisible())
                        if trigger in ('enter','shift_e','button'):
                            check(f'manual {pending} {trigger} commits',page.project.cues[0].text!=baseline)
                            page.undo_stack.undo()
                        else:check(f'manual {pending} {trigger} cancels',page.project.cues[0].text==baseline)
                        if not page._review_mode:page._set_review_mode(True)
                page._step_cue(1);check('navigate after final or pending',page.selected_cue_id=='b')
                focus(page.review_mode_button)
                shift(page.review_mode_button,Qt.Key_F);shift(page.review_mode_button,Qt.Key_F)
                check('review controls cycle one target without editor',page.project.cues[1].text.startswith('它告诉她们') and page._caption_draft is None)
                mark=next(i for i,row in enumerate(page._review_suggestions) if row.kind=='pronoun' and row.start==3)
                pronoun_card=page._review_inline_card
                rect=pronoun_card.text_label.chip_rects()[(mark,-1)]
                QTest.mouseClick(pronoun_card,Qt.LeftButton,Qt.NoModifier,pronoun_card.text_label.mapTo(pronoun_card,rect.center().toPoint()))
                focus(page.review_mode_button);shift(page.review_mode_button,Qt.Key_F)
                check('review click retargets stable next F',page.project.cues[1].text.startswith('它告诉她们'))
                check('review target visibly marked',pronoun_card.text_label._active_pronoun==3)
                focus(page.review_mode_button);QTest.keyClick(page.review_mode_button,Qt.Key_Escape)
                check('review escape from controls',not page._review_mode)
            finally:studio_review_ui.review_candidates=original_candidates
            path=save_project(page.project,output/'saved.2byteproj')
            check('saved reopen exact texts',[c.text for c in load_project(path).cues]==[c.text for c in page.project.cues])
            check('retired shortcut cannot commit',not page._caption_editor_key(QKeyEvent(QEvent.KeyPress,Qt.Key_E,Qt.ShiftModifier,'E')))
            page.save();wait(lambda:not page.project_controller.dirty_guard.is_dirty())
            check('normal save clears dirty guard',not page.project_controller.dirty_guard.is_dirty())
            from threading import Event
            from ..studio import studio_realign
            from ..timeline.studio_caption_timeline import ensure_independent_captions
            ensure_independent_captions(page.project)
            first, next_cue = page.project.cues[:2]
            page.select_cue(first.id)
            original = (first.start_ms, first.end_ms)
            other = (next_cue.start_ms, next_cue.end_ms)
            expected = (original[0] + 600, original[1] - 480)
            allow_worker = Event()
            measured_backend = studio_realign.measure
            audio_basis = studio_realign.alignment_audio_basis

            def measure_fixture(project, targets, *, cancelled):
                if not allow_worker.wait(10) or cancelled() or targets != [first.id]:
                    raise RuntimeError('Smart alignment fixture did not receive its original target')
                return {first.id: {'status': 'aligned', 'text': first.text, 'words': [{
                    'text': first.text, 'char_start': 0, 'char_end': len(first.text),
                    'start_ms': expected[0], 'end_ms': expected[1] - 120, 'evidence_ref': 'realign:a',
                }]}}

            studio_realign.measure = measure_fixture
            studio_realign.alignment_audio_basis = lambda project, cue_id: next(
                (item.text, item.start_ms, item.end_ms) for item in project.cues if item.id == cue_id)
            try:
                check('background timing fixture starts without existing words',
                      not studio_timing.measured_words(page.project, first)[0])
                index = page.undo_stack.index()
                page._smart_align_current()
                page.select_cue(next_cue.id)
                allow_worker.set()
                wait(lambda: page.cue_controller._smart_align_measuring is None, seconds=15)
                check('background measurement applies only to the original caption',
                      (first.start_ms, first.end_ms) == expected and (next_cue.start_ms, next_cue.end_ms) == other)
                check('background measurement and timing make one undo step',
                      page.undo_stack.index() == index + 1 and bool(studio_timing.measured_words(page.project, first)[0]))
                page.undo_stack.undo()
                check('one undo removes the measured receipt and restores timing',
                      (first.start_ms, first.end_ms) == original and not studio_timing.measured_words(page.project, first)[0])
                window.grab().save(str(output/'smart-align-window.png'))
            finally:
                allow_worker.set()
                studio_realign.measure = measured_backend
                studio_realign.alignment_audio_basis = audio_basis
            page.save();wait(lambda:not page.project_controller.dirty_guard.is_dirty())
            result['passed']=True;save();window.close();QTimer.singleShot(200,app.quit)
        except Exception:
            result['error']=traceback.format_exc();save()
            try:window.grab().save(str(output/'failure.png'))
            except Exception:pass
            app.exit(1)
    QTimer.singleShot(350,run)
