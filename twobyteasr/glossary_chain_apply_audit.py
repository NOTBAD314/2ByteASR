"""User-authored third alias through Studio controls; no acoustic claim."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, profile):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QToolButton
    from .studio_cards import _SubtitleEditCardEditor
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_find_replace import FindReplaceDialog
    from .studio_export_ui import SubtitleExportDialog
    from .studio_project import load_project
    from .studio_subtitle_export import SubtitleExportArtifact, verify_subtitle_artifact
    from .terminology import snapshot_glossaries
    from .studio_acceptance_audit import audit_tmp_root
    output = Path(os.environ['TWOBYTEASR_GLOSSARY_APPLY_OUTPUT']).resolve()
    if not output.is_relative_to(audit_tmp_root()):
        raise ValueError('Glossary apply artifacts must stay under task tmp')
    project_path = Path(os.environ['TWOBYTEASR_STARTUP_PROJECT']).resolve()
    profile = Path(profile)
    output.mkdir(parents=True, exist_ok=True)

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = {'passed': False, 'checks': [], 'screenshots': [], 'pid': os.getpid(),
                'executable': sys.executable, 'identity': load_build_identity().to_dict(),
                'scope': 'existing UI-saved glossary; third alias is user-authored Studio text, not spoken ASR evidence',
                'alias': '星星七号', 'canonical': 'Sable7Alias'}
            self.result['progress'] = 'waiting_for_normal_startup_studio'
            self.write()
            self.steps = self.run()
            self.waiting = 0
            self.deadline = time.monotonic() + 60
            self.busy = False
            self.deferred_error = None
            self.finished = False
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(50)

        def check(self, name, value, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(value), 'detail': detail})
            self.result['progress'] = name
            self.write()
            if not value:
                raise AssertionError(f'{name}: {detail}')

        def click(self, button):
            self.check('visible enabled control ' + (button.text() or button.toolTip()), button.isVisible() and button.isEnabled())
            QTest.mouseClick(button, Qt.LeftButton)

        def checked_item(self, listing, item, desired):
            if item.checkState() != desired:
                listing.scrollToItem(item)
                QApplication.processEvents()
                rect = listing.visualItemRect(item)
                QTest.mouseClick(listing.viewport(), Qt.LeftButton, pos=rect.center())
                QTest.keyClick(listing, Qt.Key_Space)
            self.check('normal checkbox state matches ' + item.text(), item.checkState() == desired,
                {'checked': item.checkState().value, 'expected': desired.value})

        def preview_state(self, dialog, cue_id):
            from .studio_runtime_state import state_for
            from .studio_find_replace import PreviewBinding
            project = self.page.session.project
            runtime = state_for(project)
            binding = dialog._preview_binding
            cue = next(cue for cue in project.cues if cue.id == cue_id)
            current_snapshot = snapshot_glossaries(window.legacy, dialog._preview_library_ids or ())
            return {'status_label': dialog.status_label.text(),
                'page_project_is_session_project': self.page.project is project,
                'project_id': project.project_id, 'project_revision': runtime.revision,
                'document_fingerprint': PreviewBinding._document_fingerprint(project),
                'binding_revision': binding.revision if binding else None,
                'binding_document_fingerprint': binding.document_fingerprint if binding else None,
                'binding_matches': bool(binding and binding.matches(project)),
                'preview_snapshot_digest': dialog._preview_snapshot_digest,
                'current_snapshot': current_snapshot.summary(),
                'last_delta': {'action_id': runtime.last_delta.action_id,
                    'dirty': int(runtime.last_delta.dirty), 'revision': runtime.last_delta.revision}
                    if runtime.last_delta else None,
                'undo_count': self.page.session.undo_stack.count(),
                'undo_index': self.page.session.undo_stack.index(),
                'actual_cue': {'id': cue.id, 'text': cue.text, 'start_ms': cue.start_ms,
                    'end_ms': cue.end_ms, 'speaker_id': cue.speaker_id, 'transform': cue.transform},
                'checked_rows': [{'text': dialog.preview.item(i).text(),
                    'checked': dialog.preview.item(i).checkState().value}
                    for i in range(dialog.preview.count())]}

        def defer(self, callback, delay=0):
            def invoke():
                if self.finished or self.deferred_error is not None:
                    return
                try:
                    callback()
                except Exception:
                    self.deferred_error = traceback.format_exc()
                    self.result['deferred_error'] = self.deferred_error
                    self.write()
                    # A nested exec must unwind so the audit watchdog can
                    # finish with the original error instead of timing out.
                    popup = QApplication.activePopupWidget()
                    if popup is not None:
                        popup.close()
                    modal = QApplication.activeModalWidget()
                    if modal is not None:
                        modal.reject()
            QTimer.singleShot(delay, invoke)

        def shot(self, name, surface=None):
            _capture(surface or window, output / (name + '.png'))
            self.result['screenshots'].append(name + '.png')
            self.write()

        def write(self):
            (output / 'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

        def tick(self):
            if self.busy:
                return
            self.busy = True
            try:
                now = time.monotonic()
                if self.deferred_error is not None:
                    raise RuntimeError('Deferred UI callback failed:\n' + self.deferred_error)
                if now > self.deadline:
                    raise TimeoutError('Studio custom alias phase timeout')
                if callable(self.waiting):
                    if not self.waiting():
                        return
                elif now < float(self.waiting):
                    return
                step = next(self.steps)
                if self.deferred_error is not None:
                    raise RuntimeError('Deferred UI callback failed:\n' + self.deferred_error)
                self.waiting = step if callable(step) else now + float(step)
                self.deadline = now + 60
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                try:
                    self.shot('failure')
                except Exception:
                    pass
                self.finish()
            finally:
                self.busy = False

        def ready(self):
            page = self.page
            return page.project is not None and page._readiness.ready and not page._readiness.active

        def run(self):
            yield self.ready
            yield .4
            page = self.page
            store = Path(window.legacy.LEARNED_TERMS_PATH)
            self.store_sha = hashlib.sha256(store.read_bytes()).hexdigest()
            snapshot = snapshot_glossaries(window.legacy, window._enabled_glossary_ids())
            expected = json.loads((profile / 'chain-result.json').read_text('utf8'))
            self.check('third mapping comes from earlier normal UI save', snapshot.digest == expected['snapshot_summary']['snapshot_digest'])
            self.check('third canonical is in enabled snapshot', 'Sable7Alias' in snapshot.canonical_terms)
            self.result['snapshot_summary'] = snapshot.summary()
            self.result['project_path'] = str(page.project_path)
            self.click(page.cue_filter_buttons['all'])
            yield .15
            index = page.cue_model.index(0, 3)
            selected_id = page.cue_model.cue_at(0).id
            page.cue_table.scrollTo(index)
            QTest.mouseClick(page.cue_table.viewport(), Qt.LeftButton, pos=page.cue_table.visualRect(index).center())
            QTest.mouseDClick(page.cue_table.viewport(), Qt.LeftButton, pos=page.cue_table.visualRect(index).center())
            yield .15
            editor = QApplication.focusWidget()
            self.check('actual subtitle edit card is focused for selected row',
                isinstance(editor, _SubtitleEditCardEditor) and editor is page.subtitle_edit_input
                and editor is page._canvas_editor and editor.isVisible()
                and (page._review_edit_lock or {}).get('cue_id') == selected_id,
                {'editor': type(editor).__name__, 'cue_id': selected_id,
                 'edit_lock': page._review_edit_lock})
            QTest.keyClick(editor, Qt.Key_A, Qt.ControlModifier)
            event = QInputMethodEvent()
            event.setCommitString('星星七号上场了')
            QApplication.sendEvent(editor, event)
            QTest.keyClick(editor, Qt.Key_Return)
            yield .25
            authored = next(cue for cue in page.project.cues if cue.id == selected_id)
            cue_id = authored.id
            self.check('normal user edit committed third alias', authored.text == '星星七号上场了', authored.text)
            baseline = [(cue.id, cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in page.project.cues]
            self.result['user_authored_baseline'] = {'cue_id': cue_id, 'text': authored.text,
                'start_ms': authored.start_ms, 'end_ms': authored.end_ms, 'speaker_id': authored.speaker_id}
            self.shot('01-user-authored-third-alias')
            button = page.studio_find_replace_button
            if button.isVisible():
                self.defer(lambda: self.click(button))
            else:
                overflow = next(control for control in page.studio_toolbar.findChildren(QToolButton)
                    if control.property('commandSource') == '更多工作区操作')
                self.defer(lambda: self.click(overflow))
                yield lambda: overflow.menu().isVisible()
                menu = overflow.menu()
                action = next(action for action in menu.actions() if action.text() == button.text())
                rect = menu.actionGeometry(action)
                self.check('visible enabled overflow action opens text tools',
                    action.isVisible() and action.isEnabled() and not rect.isEmpty(), action.text())
                self.shot('01b-visible-text-tools-menu', menu)
                self.defer(lambda: QTest.mouseClick(menu, Qt.LeftButton, pos=rect.center()))
            yield lambda: isinstance(QApplication.activeModalWidget(), FindReplaceDialog)
            dialog = QApplication.activeModalWidget()
            QTest.mouseClick(dialog.tabs.tabBar(), Qt.LeftButton, pos=dialog.tabs.tabBar().tabRect(3).center())
            for i in range(dialog.terms_libraries.count()):
                item = dialog.terms_libraries.item(i)
                desired = Qt.Checked if str(item.data(Qt.UserRole)) in window._enabled_glossary_ids() else Qt.Unchecked
                self.checked_item(dialog.terms_libraries, item, desired)
            self.check('all library check states match actual enabled set',
                {str(dialog.terms_libraries.item(i).data(Qt.UserRole)) for i in range(dialog.terms_libraries.count())
                 if dialog.terms_libraries.item(i).checkState() == Qt.Checked} == set(window._enabled_glossary_ids()))
            self.click(dialog.preview_button)
            yield .15
            self.check('third alias appears in actual glossary diff', any('Sable7Alias' in dialog.preview.item(i).text() for i in range(dialog.preview.count())),
                [dialog.preview.item(i).text() for i in range(dialog.preview.count())])
            # The original report can have other alias hits; only this authored
            # third cue is selected, so it cannot rewrite unrelated real text.
            for i in range(dialog.preview.count()):
                item = dialog.preview.item(i)
                wanted = 'Sable7Alias' in item.text()
                self.checked_item(dialog.preview, item, Qt.Checked if wanted else Qt.Unchecked)
            self.check('only authored third cue is checked',
                {str(dialog.preview.item(i).data(Qt.UserRole)) for i in range(dialog.preview.count())
                 if dialog.preview.item(i).checkState() == Qt.Checked} == {cue_id})
            self.result['before_apply'] = self.preview_state(dialog, cue_id)
            self.check('actual binding is current after normal preview selection',
                self.result['before_apply']['binding_matches'], self.result['before_apply'])
            self.shot('02-third-alias-diff', dialog)
            clicked = []
            dialog.all_button.clicked.connect(lambda: clicked.append(True))
            self.click(dialog.all_button)
            yield .2
            self.result['after_apply'] = self.preview_state(dialog, cue_id)
            self.result['actual_apply_button_clicked_count'] = len(clicked)
            self.shot('02b-after-actual-apply', dialog)
            self.check('actual apply button delivered clicked signal once', len(clicked) == 1, len(clicked))
            self.check('actual apply preserves exact third canonical',
                self.result['after_apply']['actual_cue']['text'] == 'Sable7Alias上场了',
                self.result['after_apply'])
            dialog.reject()
            yield .1
            self.check('apply preserves all times and speakers', [(cue.id, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in page.project.cues] ==
                [(row[0], *row[2:]) for row in baseline])
            self.check('unchecked other real text remains', all(cue.text == dict((row[0],row[1]) for row in baseline)[cue.id]
                for cue in page.project.cues if cue.id != cue_id))
            page.cue_table.setFocus()
            QTest.keyClick(page.cue_table, Qt.Key_Z, Qt.ControlModifier)
            yield .15
            self.check('normal Ctrl+Z restores authored alias in one step', [(cue.id, cue.text, cue.start_ms, cue.end_ms, cue.speaker_id) for cue in page.project.cues] == baseline)
            QTest.keyClick(page.cue_table, Qt.Key_Y, Qt.ControlModifier)
            yield .15
            self.check('normal Ctrl+Y restores canonical', next(cue for cue in page.project.cues if cue.id == cue_id).text == 'Sable7Alias上场了')
            page.video.seek((authored.start_ms+150)/1000)
            yield .5
            self.shot('03-studio-applied-third-canonical')
            self.click(page.save_button)
            yield .25
            reopened = load_project(page.project_path)
            self.check('normal Save persists canonical', next(cue for cue in reopened.cues if cue.id == cue_id).text == 'Sable7Alias上场了')
            self.result['saved_third_cue'] = next(cue for cue in reopened.to_dict()['cues'] if cue['id'] == cue_id)
            export_directory = output / 'exports'
            export_directory.mkdir()
            original_picker = QFileDialog.getExistingDirectory
            QFileDialog.getExistingDirectory = lambda *_args, **_kwargs: str(export_directory)
            configured = [False]
            deadline = time.monotonic() + 45
            def export_controls():
                if time.monotonic() > deadline:
                    return
                modal = QApplication.activeModalWidget()
                if isinstance(modal, SubtitleExportDialog) and not configured[0]:
                    for box in modal.format_checks.values():
                        if not box.isChecked():
                            QTest.mouseClick(box, Qt.LeftButton)
                    QTest.mouseClick(modal.speaker_modes['combined'], Qt.LeftButton)
                    choose = next(button for button in modal.findChildren(QPushButton) if button.text() == '选择文件夹')
                    QTest.mouseClick(choose, Qt.LeftButton)
                    self.shot('04-normal-export-controls', modal)
                    configured[0] = True
                    button = next(button for button in modal.findChildren(QPushButton) if button.text() == '导出字幕')
                    QTest.mouseClick(button, Qt.LeftButton)
                elif isinstance(modal, QMessageBox):
                    button = modal.button(QMessageBox.Ok)
                    if button is not None:
                        QTest.mouseClick(button, Qt.LeftButton)
                        return
                self.defer(export_controls, 25)
            self.defer(export_controls, 25)
            try:
                self.click(page.studio_export_button)
            finally:
                QFileDialog.getExistingDirectory = original_picker
            yield .3
            files = sorted(export_directory.iterdir())
            self.check('normal export produces four selected formats', {file.suffix for file in files} == {'.srt','.ass','.txt','.json'})
            self.result['exports'] = []
            for file in files:
                artifact = SubtitleExportArtifact(file, file.suffix[1:], '', len(reopened.cues))
                verified = verify_subtitle_artifact(artifact, reopened)
                self.check('export verified ' + file.suffix, verified.valid,
                    {'cue_count': verified.cue_count, 'timestamps_valid': verified.timestamps_valid,
                     'speaker_mapping_valid': verified.speaker_mapping_valid, 'unicode_valid': verified.unicode_valid})
                self.check('export contains exact third canonical ' + file.suffix, 'Sable7Alias上场了' in file.read_text('utf8'))
                self.result['exports'].append({'path': str(file), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
            self.check('UI saved glossary bytes unchanged during downstream phase', hashlib.sha256(store.read_bytes()).hexdigest() == self.store_sha)
            from . import blank_project_audit
            self.check('no ASR/AI model calls for authored sample', blank_project_audit._provider_calls == 0)
            self.shot('05-studio-after-normal-export')

        def finish(self):
            self.finished = True
            self.timer.stop()
            window.result_exit_code = 0 if self.result['passed'] else 1
            def write():
                (output / 'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')
            write()
            def stopped():
                self.result['gui_shutdown'] = True
                write()
            QApplication.instance().aboutToQuit.connect(stopped)
            modal = QApplication.activeModalWidget()
            if modal is not None:
                modal.reject()
            # Only this audit-owned copy may be discarded on a failed step.
            # Use the real dirty-guard control; never clear dirty state or
            # suppress the application's ordinary save confirmation.
            close_deadline = time.monotonic() + 10
            def close_controls():
                if time.monotonic() > close_deadline:
                    return
                current = QApplication.activeModalWidget()
                current_path = Path(str(getattr(self.page, 'project_path', '') or '')).resolve()
                if isinstance(current, QMessageBox) and current_path == project_path:
                    button = current.button(QMessageBox.StandardButton.Discard)
                    if button is not None:
                        self.result['owned_copy_close_choice'] = 'normal Discard control'
                        self.write()
                        QTest.mouseClick(button, Qt.LeftButton)
                        return
                QTimer.singleShot(25, close_controls)
            if not self.result['passed']:
                editor = getattr(self.page, '_canvas_editor', None)
                if isinstance(editor, _SubtitleEditCardEditor) and editor.isVisible():
                    QTest.keyClick(editor, Qt.Key_Escape)
            QTimer.singleShot(25, close_controls)
            window.close()
    window._glossary_chain_apply_audit = Audit()
