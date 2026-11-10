"""Native-window audit of the actual editor, timeline, render preparation and persistence."""
import copy
import json
import os
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt, QEvent, QPoint
    from PySide6.QtGui import QInputMethodEvent, QKeyEvent, QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..studio.caption_editor import qt_position
    app = QApplication.instance()
    output = Path(output)
    result = dict(passed=False, checks={}, split_ms=[], scope='normal MainWindow, native Windows Qt, synthetic 7000 cues over 5h50m; 16s synthetic media')

    def receipt():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def check(name, value):
        result['checks'][name] = bool(value)
        receipt()
        if not value:
            raise AssertionError(name)

    def wait(predicate, timeout=60):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            if predicate():
                return
            app.processEvents()
            time.sleep(.003)
        raise TimeoutError('caption split audit wait')

    def place(page, text, at):
        editor = page.subtitle_edit_input
        editor.setPlainText(text)
        cursor = editor.textCursor()
        cursor.setPosition(qt_position(text, at))
        editor.setTextCursor(cursor)
        QApplication.setActiveWindow(page.subtitle_edit_dock)
        editor.setFocus()

    def click_split(page):
        start = time.perf_counter()
        QTest.mouseClick(page.subtitle_edit_card.split_button, Qt.MouseButton.LeftButton)
        result['split_ms'].append((time.perf_counter()-start)*1000)
        app.processEvents()

    def run():
        page = window.studio_page
        try:
            window.setWindowTitle('兔白 Studio · 光标切割验收')
            window._switch_page(page)
            page.project_controller.open_project_entry(os.environ['CARET_SPLIT_PROJECT'], single_shot_fn=QTimer.singleShot, skip_dirty_guard=True)
            wait(lambda: page.project is not None and page._readiness.ready, 100)
            wait(lambda: page._readiness.loading.state == 'ready' and not page._readiness.overlay.isVisible(), 30)
            page.video.set_paused(True)
            check('7000 caption project visibly opened', len(page.project.cues)==7000 and page.timeline.isVisible())
            result['dpr'] = page.devicePixelRatioF()
            page.select_cue('cue-0')
            page._open_caption_editor('cue-0', 'original')
            page._lock_caption_editor()
            card = page.subtitle_edit_card
            from ..subtitle_rules.review_suggestions import ReviewSuggestion, SuggestionOption
            text = page.subtitle_edit_input.toPlainText()
            start = text.index('ここ')
            page._caption_draft.suggestions = (
                ReviewSuggestion(start, start + 2, 'ここ',
                                 (SuggestionOption('此処'), SuggestionOption('ここ')), 'model'),
                ReviewSuggestion(text.index('明日'), text.index('明日') + 2, '明日',
                                 (SuggestionOption('あす'),), 'model'),
            )
            page._caption_draft.suggestion_text = text
            page._refresh_editor_suggestions()
            QTest.qWait(150)
            check('cream card and action strip visible', card.face.isVisible() and card.strip.isVisible())
            check('one candidate bubble row visible', card.bubble.isVisible() and
                  sum(not frame.isHidden() for frame in card.suggestions._frames) == 1)
            check('suspect words highlighted', len(card.editor.extraSelections()) == 2)
            for above in (False, True):
                card.set_strip_above(above)
                card.layout().activate()
                card.place_bubble()
                card.layout().activate()
                card.place_bubble()
                editor_top = card.editor.mapToGlobal(QPoint()).y()
                editor_bottom = card.editor.mapToGlobal(QPoint(0, card.editor.height())).y()
                bubble_top = card.suggestions.mapToGlobal(QPoint()).y()
                bubble_bottom = card.suggestions.mapToGlobal(QPoint(0, card.suggestions.height())).y()
                check(f'candidate bubble clears draft strip_above={above}',
                      bubble_top >= editor_bottom if above else bubble_bottom <= editor_top)
            page.subtitle_edit_dock.fit_to_workspace()
            QTest.qWait(100)
            page.subtitle_edit_dock.grab().save(str(output/'candidate-card.png'))
            QTest.keyClick(card.editor, Qt.Key_W, Qt.ShiftModifier)
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_D, Qt.ShiftModifier)
            check('candidate keyboard advances options', card.suggestions.selected == (0, 1))
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_D, Qt.ShiftModifier)
            check('candidate keyboard advances bubble row', card.suggestions.selected == (1, 0))
            QTest.keyClick(QApplication.focusWidget(), Qt.Key_Space)
            check('candidate applies to draft only', 'あす' in card.editor.toPlainText() and
                  page.project.cues[0].text == text)
            page._cancel_canvas_inline_edit()
            check('candidate cancellation preserves cue', page.project.cues[0].text == text)
            original = copy.deepcopy(page.project.cues[:4])
            index = page.undo_stack.index()
            resets, track_rebuilds, manual_saves = [], [], []
            page.cue_model.modelReset.connect(lambda: resets.append(True))
            timeline_type = type(page.timeline)
            reindex = timeline_type.reindex_project
            def observed_reindex(timeline, **kwargs):
                track_rebuilds.append(True)
                return reindex(timeline, **kwargs)
            timeline_type.reindex_project = observed_reindex
            controller_type = type(page.project_controller)
            save = controller_type.save
            def observed_save(controller, *args, **kwargs):
                manual_saves.append(True)
                return save(controller, *args, **kwargs)
            controller_type.save = observed_save
            for number, at in enumerate((8, 14, 6, 6)):
                cue = next(c for c in page.project.cues if c.id == f'cue-{number}')
                page._seek((cue.start_ms+100)/1000)
                wait(lambda: abs(page.timeline.playhead_ms-(cue.start_ms+100))<200, 15)
                wait(lambda: getattr(getattr(page, '_caption_seek_preparation', None), 'pending', None) is None, 30)
                page.select_cue(cue.id)
                page._open_caption_editor(cue.id, 'original')
                page._lock_caption_editor()
                text = cue.text
                place(page, text, at)
                click_split(page)
                QTest.qWait(100)
                page.subtitle_edit_dock.fit_to_workspace()
                panel = page.subtitle_edit_card
                result.setdefault('part_labels', []).append(dict(
                    text=panel.split_part.text(), width=panel.split_part.width(),
                    required=panel.split_part.sizeHint().width()))
                check(f'language {number} complete split part label',
                      panel.split_part.width() >= panel.split_part.sizeHint().width())
                parts = [c for c in page.project.cues if c.id==cue.id or c.id.startswith(cue.id+'-split-')]
                check(f'language {number} exact text', len(parts)==2 and ''.join(c.text for c in parts)==text)
                check(f'language {number} edit second part', page.subtitle_edit_input.toPlainText()==text[at:] and page.selected_cue_id==parts[1].id)
                wait(lambda: page.cue_model.row_for_cue_id(parts[1].id)>=0)
                check(f'language {number} timeline updated', parts[1].id in page.timeline._timeline_cue_by_id)
                page._seek((parts[1].start_ms+50)/1000)
                wait(lambda: page._prepared_caption(parts[1].id) is not None and
                     page._prepared_caption(parts[1].id).snapshot.text == text[at:], 30)
                check(f'language {number} render prepared', True)
                wait(lambda: getattr(getattr(page, '_caption_seek_preparation', None), 'pending', None) is None, 30)
                from ..rendering.caption_scene import complete_scene_for_seek
                wait(lambda: parts[1].start_ms <= page._caption_sample_ms() < parts[1].end_ms and
                     complete_scene_for_seek(page._caption_scene, parts[1].id, page.video._playback_clock.generation), 30)
                check(f'language {number} expected scene actually published', True)
                frame = output/f'native-preview-{number}.png'
                page.video.controller.screenshot_to_file(str(frame), mode='window', fast=True)
                wait(frame.is_file, 10)
                from PIL import Image, ImageStat
                pixels = Image.open(frame).convert('RGB')
                check(f'language {number} native preview has ink', max(ImageStat.Stat(pixels).var)>5)
                if number==0:
                    check('measured label', '字词对齐切点' in page.subtitle_edit_card.split_status.text())
                else:
                    check(f'language {number} estimated label', '估算切点' in page.subtitle_edit_card.split_status.text())
                page.subtitle_edit_dock.grab().save(str(output/f'editor-{number}.png'))
                page.grab().save(str(output/f'workspace-{number}.png'))
                page._cancel_canvas_inline_edit()
                check(f'language {number} cancel exact cue', next(c for c in page.project.cues if c.id==cue.id)==original[number])
            check('no table model resets', not resets)
            check('no track rebuilds', not track_rebuilds)
            check('no formal save per split', not manual_saves)
            cue = page.project.cues[0]
            from ..subtitle_rules.subtitle_translation import set_manual, records_of
            set_manual(page.project, cue.id, '今天就到这里。明天见。')
            translation_before = copy.deepcopy(page.project.generation_metadata)
            page._open_caption_editor(cue.id, 'original')
            page._lock_caption_editor()
            editor = page.subtitle_edit_input
            place(page, '甲乙丙丁戊己', 2)
            QTest.keyClicks(editor, 'c')
            check('normal c typed', editor.toPlainText()=='甲乙c丙丁戊己')
            place(page, '甲乙丙丁戊己', 2)
            QTest.keyClick(editor, Qt.Key_C, Qt.ShiftModifier)
            check('Shift+C cuts with C mode off', len(page.project.cues)==7001 and
                  editor.toPlainText()=='丙丁戊己')
            page._undo_caption_split()
            check('Shift+C cut can be undone locally', len(page.project.cues)==7000)
            place(page, '甲乙丙丁戊己', 2)
            card = page.subtitle_edit_card
            QTest.mouseClick(card.more_button, Qt.MouseButton.LeftButton)
            wait(card.more_menu.isVisible, 5)
            action = next(action for action in card.more_menu.actions() if action.text() == 'C 键直接切割')
            QTest.mouseClick(card.more_menu, Qt.MouseButton.LeftButton,
                             pos=card.more_menu.actionGeometry(action).center())
            check('More menu enables C mode', card.split_mode.isChecked())
            check('mode toggle retains draft', page._caption_draft is not None and editor.textCursor().position()==2)
            QTest.keyClick(editor, Qt.Key_C, Qt.ControlModifier)
            check('Ctrl+C preserves structure', len(page.project.cues)==7000)
            QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
            check('Shift+Enter keeps newline', '\n' in editor.toPlainText())
            place(page, '甲乙丙丁戊己', 2)
            for preedit, commit_text in [('ni','你'), ('に','日')]:
                QApplication.sendEvent(editor, QInputMethodEvent(preedit, []))
                QTest.keyClick(editor, Qt.Key_C)
                check(f'preedit {preedit} safe', len(page.project.cues)==7000)
                event = QInputMethodEvent(); event.setCommitString(commit_text)
                QApplication.sendEvent(editor, event)
                QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyPress,Qt.Key_C,Qt.NoModifier,'c'))
                check(f'commit {preedit} safe', len(page.project.cues)==7000 and commit_text in editor.toPlainText())
                QTest.qWait(5)
            place(page, '甲乙丙丁戊己', 2)
            QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyPress,Qt.Key_C,Qt.NoModifier,'c'))
            for _ in range(4):
                QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyPress,Qt.Key_C,Qt.NoModifier,'c',True))
            QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyRelease,Qt.Key_C,Qt.NoModifier,'c'))
            check('C press/repeat cuts once', len(page.project.cues)==7001)
            place(page, editor.toPlainText(), 2)
            QTest.keyClick(editor, Qt.Key_C)
            check('second C cuts into three', len(page.project.cues)==7002)
            QTest.mouseClick(page.subtitle_edit_card.split_undo, Qt.MouseButton.LeftButton)
            check('window undo cut', len(page.project.cues)==7001 and editor.toPlainText()=='丙丁戊己')
            QTest.mouseClick(page.subtitle_edit_card.split_redo, Qt.MouseButton.LeftButton)
            check('window redo cut', len(page.project.cues)==7002)
            page._navigate_split_part(-1)
            place(page, '丙丁修改', 4)
            page._navigate_split_part(1)
            check('translation retained once', sum(bool(r.get('text')) for key,r in records_of(page.project).items()
                                                   if key in page._caption_split_session.ids)==1)
            page._caption_trigger_commit('audit')
            check('one project undo step', page.undo_stack.index()==index+1)
            after = copy.deepcopy(page.project.cues[:3])
            page.undo_stack.undo()
            check('project undo complete', page.project.cues[:4]==original and page.project.generation_metadata==translation_before)
            page.undo_stack.redo()
            check('project redo complete', page.project.cues[:3]==after)
            # Persist through the ordinary asynchronous manual-save entry, then reopen independently.
            timeline_type.reindex_project = reindex
            controller_type.save = save
            page.save()
            from ..projects.persistence_queue import queue_for
            wait(lambda: not queue_for(page).busy, 45)
            from ..projects.studio_project import load_project
            loaded = load_project(page.project_path)
            check('saved split reopens with same cues', loaded.cues[:3]==after and len(loaded.cues)==7002)
            page.select_cue(after[1].id)
            page._open_caption_editor(after[1].id, 'original')
            page._lock_caption_editor()
            place(page, after[1].text, 2)
            page.subtitle_edit_dock.setWindowTitle('字幕编辑 · 光标切割验收')
            page.subtitle_edit_dock.grab().save(str(output/'final-editor.png'))
            result['passed'] = all(result['checks'].values())
            result['hold_ready'] = True
            receipt()
            hold = int(os.environ.get('CARET_SPLIT_HOLD_SECONDS','0'))
            end = time.monotonic()+hold
            while time.monotonic()<end and not (output/'continue.txt').exists():
                app.processEvents()
                time.sleep(.05)
        except Exception:
            result['error'] = traceback.format_exc()
            result['passed'] = False
        finally:
            if 'reindex' in locals(): timeline_type.reindex_project = reindex
            if 'save' in locals(): controller_type.save = save
            receipt()
            page._cancel_canvas_inline_edit()
            page.undo_stack.setClean()
            page.project_dirty = False
            window.close()
    app.aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
    QTimer.singleShot(1200, run)
