"""Normal-window interaction regressions with owned synthetic projects only."""
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture

    def run():
        from ..diagnostics.build_identity import load_build_identity
        from ..projects.studio_runtime_state import state_for
        from ..studio.studio_find_replace import FindReplaceDialog
        from ..glossary.glossary_proofread import _issue
        result = dict(passed=False, checks=[], snapshots=[], frozen=bool(getattr(sys, 'frozen', False)),
                      identity=load_build_identity().to_dict(), process_executable=sys.executable)
        def save():
            (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        def check(name, value, **detail):
            result['checks'].append(dict(name=name, passed=bool(value), **detail))
            save()
            if not value:
                raise AssertionError(name + ': ' + str(detail))
        def pump(seconds=.2):
            deadline = time.perf_counter() + seconds
            while time.perf_counter() < deadline:
                QApplication.processEvents()
                time.sleep(.005)
        def wait(predicate, seconds=25):
            deadline = time.perf_counter() + seconds
            while time.perf_counter() < deadline:
                pump(.03)
                if predicate():
                    return True
            return False
        def shot(name):
            _capture(window, output/(name+'.png'))
        page = window.studio_page
        review = None
        dialog = None
        record_timer = None
        frames = []
        recording = output/'recording'
        recording.mkdir()
        def record_frame():
            # Live raster of the actual main window and its owned decision
            # dialog. No recreated interface or animated mockup is used.
            from PySide6.QtGui import QPainter
            pixmap = window.grab()
            modal = QApplication.activeModalWidget()
            if modal is not None and modal is not window and modal.isVisible():
                painter = QPainter(pixmap)
                painter.drawPixmap(window.mapFromGlobal(modal.pos()), modal.grab())
                painter.end()
            target = recording/f'{len(frames):05d}.png'
            pixmap.save(str(target))
            frames.append((target.name, time.perf_counter()))
        try:
            window.showMaximized()
            window._switch_page(page)
            page.project_controller.open_project_entry(os.environ['TWOBYTEASR_STARTUP_PROJECT'],
                single_shot_fn=QTimer.singleShot, skip_dirty_guard=True)
            check('startup ready', wait(lambda: page.project is not None and page._project_view_state == 'open'
                                        and not page._readiness.active))
            page.video.set_paused(True)
            project = page.project
            result['dpi'] = window.devicePixelRatioF()
            result['maximized'] = window.isMaximized()
            if os.environ.get('TWOBYTEASR_INTERACTION_REOPEN'):
                expected = json.loads((output/'expected-texts.json').read_text('utf8'))
                check('new process read formally saved text', [c.text for c in project.cues] == expected)
                check('new process starts with clean undo stack', page.undo_stack.isClean())
                shot('reopened-in-new-process')
                result['passed'] = True
                return
            record_timer = QTimer(window)
            record_timer.setInterval(125)
            record_timer.timeout.connect(record_frame)
            record_timer.start()
            def snapshot(label):
                result['snapshots'].append(dict(label=label, project_object=id(page.project),
                    project_id=page.project.project_id, revision=state_for(page.project).revision,
                    texts=[c.text for c in page.project.cues[:4]],
                    loading=page._readiness.active, modal=type(QApplication.activeModalWidget()).__name__,
                    review_busy=review._worker is not None if review else False))
                save()
            def replace(old, new, label):
                nonlocal dialog
                dialog = FindReplaceDialog(page, page)
                dialog.show()
                dialog.text_targets.mode.setCurrentIndex(0)
                dialog.find_edit.setText(old)
                dialog.replace_edit.setText(new)
                pump(.5)
                snapshot(label+' preview')
                count = dialog.preview.count()
                check(label+' hits', count > 0)
                QTest.mouseClick(dialog.all_button, Qt.LeftButton)
                pump(.3)
                snapshot(label+' applied')
                check(label+' text changed', new in project.cues[0].text,
                      status=dialog.status_label.text(), hits=count)
                shot(label)
                dialog.close()
                dialog.deleteLater()
                dialog = None
                pump()
            replace('SHARED', 'CHECKED', '01-before-review')
            window._open_studio_glossary_proofread()
            review = window.glossary_proofread_page
            check('same live document', review._live_project()[0] is project)
            check('matching finished', wait(lambda: review._worker is None and not review._stutter_threads))
            snapshot('review open')
            row = review._by_id['source-0000']
            pos = row['base'].index('Neuvillette')
            row['issues'] = [_issue('term', (pos, pos+len('Neuvillette')), 'Neuvillette', 'NOVA', checked=False)]
            review._apply_filter()
            def click_issue():
                review.list.ensure_visible('source-0000')
                pump(.25)
                box = next(rect for rect, action, key, index in review.list._hit_boxes
                           if action == 'check' and key == 'source-0000' and index == 0)
                QTest.mouseClick(review.list, Qt.LeftButton, pos=box.center().toPoint())
                pump(.8)
            click_issue()
            check('adoption changed current project', 'NOVA' in project.cues[0].text,
                  status=review.status_label.text(), row=review._by_id['source-0000']['base'])
            check('adoption state agrees', review._by_id['source-0000']['issues'][0]['checked'],
                  counts=review.proposal_counts())
            shot('02-adopted')
            click_issue()
            check('same suggestion reverted', 'Neuvillette' in project.cues[0].text)
            shot('03-reverted')
            click_issue()
            QTest.mouseClick(review.back_button, Qt.LeftButton)
            pump(.5)
            check('returned to workbench', window.pages.currentWidget() is page)
            snapshot('returned')
            replace('NOVA', 'AFTER', '04-after-review')
            # Real worker lifecycle with an explicitly offline provider.
            import threading
            from ..glossary.terminology import snapshot_from_pairs
            from ..glossary.studio_glossary_service import preview_glossary_correction
            for mode in ('local', 'success', 'cancel', 'failure', 'leave_pending'):
                window._open_studio_glossary_proofread()
                review = window.glossary_proofread_page
                check(mode+' entry settled', wait(lambda: review._worker is None))
                snapshot_terms = snapshot_from_pairs([('Neuvillette', 'NOVA')])
                review._snapshot = snapshot_terms
                review._selected_ids = lambda: ('owned-fixture',)
                review._read_snapshot = lambda: setattr(review, '_snapshot', snapshot_terms)
                entered, released = threading.Event(), threading.Event()
                def provider(*args, **kwargs):
                    entered.set()
                    if mode in ('cancel', 'leave_pending'):
                        released.wait(10)
                    if mode == 'failure':
                        raise RuntimeError('offline injected provider failure')
                    return preview_glossary_correction(*args, **kwargs, use_ai=False)
                review.ai_stand_in = provider
                review._run(mode != 'local')
                if mode in ('cancel', 'leave_pending'):
                    check(mode+' worker entered', wait(entered.is_set))
                    if mode == 'cancel':
                        QTest.mouseClick(review.cancel_button, Qt.LeftButton)
                        released.set()
                        check(mode+' worker settled', wait(lambda: review._worker is None))
                else:
                    check(mode+' worker settled', wait(lambda: review._worker is None))
                before = [c.text for c in project.cues]
                old_generation = review._generation
                QTest.mouseClick(review.back_button, Qt.LeftButton)
                pump(.3)
                released.set()
                check(mode+' left generation retired', review._generation > old_generation)
                check(mode+' no hidden stack listener', review._stack is None)
                check(mode+' worker stopped after return', wait(lambda: review._worker is None))
                check(mode+' late result preserved text', before == [c.text for c in project.cues])
                old = 'AFTER2' if 'AFTER2' in project.cues[0].text else 'AFTER'
                new = 'AFTER2' if old == 'AFTER' else 'AFTER'
                replace(old, new, '05-'+mode)
            # Save through Studio, then reopen in the same normal loading flow.
            from ..studio import studio_ui
            original_autosave = studio_ui.save_autosave_revision
            entered, released = threading.Event(), threading.Event()
            def held_autosave(*args, **kwargs):
                entered.set()
                released.wait(10)
                return original_autosave(*args, **kwargs)
            check('prior autosave settled', wait(lambda: not page._autosave_worker_running))
            studio_ui.save_autosave_revision = held_autosave
            try:
                page._autosave_timer.stop()
                page._start_autosave_worker(page._autosave_generation)
                check('autosave is in flight', wait(entered.is_set))
                window._open_studio_glossary_proofread()
                review = window.glossary_proofread_page
                review._edit_committed('source-0000', project.cues[0].text+' SAVED-LATEST')
                QTest.mouseClick(review.back_button, Qt.LeftButton)
                released.set()
                check('newer autosave settled', wait(lambda: not page._autosave_worker_running and not page._autosave_timer.isActive()))
                check('recovery save did not mark formal clean', not page.undo_stack.isClean())
            finally:
                released.set()
                studio_ui.save_autosave_revision = original_autosave
            page.project_controller.save()
            from ..projects.studio_project import load_project, save_project, save_autosave
            check('formal save matches live text', [c.text for c in load_project(page.project_path).cues] == [c.text for c in project.cues])
            result['formal_saved_path'] = str(page.project_path)
            (output/'formal-texts.json').write_text(json.dumps([c.text for c in project.cues], ensure_ascii=False), 'utf8')
            from ..projects.project_snapshot import document_snapshot
            from ..projects.project_recovery_dialog import RecoveryDialog
            original_text = project.cues[0].text
            for choice in ('saved', 'recover', 'ignore', 'cancel', 'close', 'delete_failure', 'saved'):
                copy_path = output/('recovery-'+str(len(result['checks']))+'.2byteproj')
                copy = document_snapshot(project)
                copy.cues[0].text = original_text
                save_project(copy, copy_path)
                copy.cues[0].text = 'RECOVERED '+original_text
                candidate = Path(save_autosave(copy, copy_path))
                os.utime(copy_path, ns=(copy_path.stat().st_atime_ns, copy_path.stat().st_mtime_ns-1000000000))
                before_project = page.project
                page.undo_stack.setClean()
                page.project_controller.open_project_entry(copy_path, single_shot_fn=QTimer.singleShot, skip_dirty_guard=True)
                check(choice+' recovery dialog appeared', wait(lambda: getattr(page._readiness, '_recovery_dialog', None) is not None))
                box = page._readiness._recovery_dialog
                check(choice+' loading paused for choice', not page._readiness.timer.isActive() and page._readiness.active)
                pump(.8)
                _capture(box, output/('recovery-'+choice+'.png'))
                if choice == 'cancel':
                    QTest.keyClick(box, Qt.Key_Escape)
                elif choice == 'close':
                    box.close()
                elif choice == 'delete_failure':
                    from ..projects import studio_project as persistence
                    discard = persistence.discard_autosave
                    def fail_delete(_candidate):
                        raise PermissionError('owned recovery delete denied for retry test')
                    persistence.discard_autosave = fail_delete
                    try:
                        QTest.mouseClick(next(b for b in box.buttons() if b.objectName() == 'recovery_ignore'), Qt.LeftButton)
                        check('delete failure offers retry', wait(lambda: getattr(page._readiness, '_recovery_dialog', None) is not None))
                        box = page._readiness._recovery_dialog
                        check('delete failure preserves recovery', candidate.exists() and 'retry test' in box.informativeText())
                        pump(.6)
                    finally:
                        persistence.discard_autosave = discard
                    # Tab/Enter follows the focused button, not always restore.
                    buttons = box.buttons()
                    button = next(b for b in buttons if b.objectName() == 'recovery_saved')
                    box.setFocus()
                    for _ in range(8):
                        if QApplication.focusWidget() is button:
                            break
                        QTest.keyClick(box, Qt.Key_Tab)
                    check('Tab reaches official button', QApplication.focusWidget() is button)
                    QTest.keyClick(button, Qt.Key_Return)
                else:
                    button = next(b for b in box.buttons() if b.objectName() == 'recovery_'+choice)
                    QTest.mouseClick(button, Qt.LeftButton)
                check(choice+' loading returned', wait(lambda: not page._readiness.active))
                if choice in ('cancel', 'close'):
                    check('cancel preserved project and recovery', page.project is before_project and candidate.exists())
                else:
                    expected = ('RECOVERED ' if choice == 'recover' else '')+original_text
                    check(choice+' selected correct text', page.project.cues[0].text == expected)
                    check(choice+' recovery deletion semantics', candidate.exists() == (choice != 'ignore'))
                    check(choice+' formal path retained', Path(page.project_path) == copy_path)
                    project = page.project
                pump(.7)
            check('no invisible modal remains', QApplication.activeModalWidget() is None)
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
            shot('failure')
        finally:
            if record_timer is not None:
                record_timer.stop()
                record_timer.deleteLater()
            if frames:
                lines = ['ffconcat version 1.0']
                for i, (name, stamp) in enumerate(frames):
                    duration = frames[i+1][1]-stamp if i+1 < len(frames) else .125
                    lines += ["file '"+name+"'", 'duration '+str(duration)]
                lines += ["file '"+frames[-1][0]+"'"]
                (recording/'frames.ffconcat').write_text('\n'.join(lines)+'\n', 'utf8')
                result['recording_frames'] = len(frames)
            if dialog is not None:
                dialog.close()
            if review is not None:
                review._save_timer.stop()
                review._cancel_worker()
            page._autosave_timer.stop()
            page.undo_stack.setClean()
            save()
            window._studio_close_finalizing = True
            window.close()
            result['gui_shutdown'] = True
            save()
            QApplication.quit()
    QTimer.singleShot(500, run)
