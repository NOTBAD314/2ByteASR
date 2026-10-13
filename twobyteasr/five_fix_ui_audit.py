"""Real normal-window name-edit and completion-layout acceptance.

Input method event delivery is explicit protocol coverage, not a physical IME
claim. Saved report playback never counts as a new recognition run.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QToolButton
    from . import blank_project_audit
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .service import MediaResult, QueueResult
    from .studio_project import load_project
    from .studio_speaker_manager import SpeakerManagerDialog
    from .theme_manager import apply_theme

    output = Path(output)
    inputs = json.loads((output/'input.json').read_text('utf8'))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.started = time.monotonic()
            self.result = dict(passed=False, checks=[], screenshots=[], geometry=[], inputs=inputs,
                identity=load_build_identity().to_dict(), executable=sys.executable, pid=__import__('os').getpid(),
                dpr=window.devicePixelRatioF(), entry='frozen' if getattr(sys, 'frozen', False) else 'quick_start.main',
                pixel_source='PrintWindow of production Qt windows on a private Windows desktop',
                ime_scope=inputs['ime_scope'], terminal_scope=inputs['terminal_scope'])
            self.steps = self.run()
            self.waiting = 0
            self.deadline = self.started+50
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(50)

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

        def check(self, name, value, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
            self.write()
            if not value:
                raise AssertionError(name+': '+str(detail))

        def shot(self, name, widget=None):
            path = output/(name+'.png')
            _capture(widget or window, path)
            self.result['screenshots'].append(str(path))
            self.write()

        def tick(self):
            try:
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox):
                    error = modal.text()+' '+modal.informativeText()
                    self.shot('unexpected-dialog', modal)
                    modal.reject()
                    raise RuntimeError(error)
                now = time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now > self.deadline:
                            raise TimeoutError('Normal GUI step timed out')
                        return
                elif now < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else time.monotonic()+float(step)
                self.deadline = time.monotonic()+50
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                try:
                    self.shot('failure-window', QApplication.activeModalWidget() or window)
                except Exception:
                    pass
                self.finish()

        def ready(self):
            p = self.page
            return bool(p.project is not None and p._readiness.ready and not p._readiness.active and p._project_view_state == 'open')

        def click(self, control):
            self.check('native target visible and enabled: '+control.text(), control.isVisible() and control.isEnabled())
            QTest.mouseClick(control, Qt.LeftButton)

        def names(self):
            return {speaker.id: speaker.name for speaker in self.page.project.speakers}

        def ascii_edit(self, manager, value):
            manager.name_edit.setFocus()
            QTest.keyClick(manager.name_edit, Qt.Key_A, Qt.ControlModifier)
            if value:
                QTest.keyClicks(manager.name_edit, value)
            else:
                QTest.keyClick(manager.name_edit, Qt.Key_Backspace)

        def layout(self, phase):
            scroll = window.pages.widget(2)
            viewport = scroll.viewport()
            def rect(widget):
                point = widget.mapTo(viewport, QPoint())
                return dict(x=point.x(), y=point.y(), width=widget.width(), height=widget.height())
            summary = rect(window.result_summary_card)
            cards = window.result_action_grid.cards
            supporting = window.result_action_grid.secondary_actions
            columns = window.result_action_grid.columns
            header_bottom = window.app_header.mapTo(window, QPoint()).y()+window.app_header.height()
            navigation_gap = window.result_summary_card.mapTo(window, QPoint()).y()-header_bottom
            geometry = dict(phase=phase, window=rect(window), viewport=dict(width=viewport.width(), height=viewport.height()),
                summary=summary, cards=[rect(card) for card in cards], secondary=[rect(button) for button in supporting],
                columns=columns, dpr=window.devicePixelRatioF(), scroll_max=scroll.verticalScrollBar().maximum(),
                navigation_gap=navigation_gap, content_viewport_width_ratio=window.result_content.width()/viewport.width(),
                summary_title_font_pixels=window.result_title.font().pixelSize(),
                primary_title_font_pixels=[card.title_font().pixelSize() for card in cards],
                primary_body_font_pixels=[card.description_font().pixelSize() for card in cards],
                secondary_font_pixels=[button.font().pixelSize() for button in supporting])
            self.result['geometry'].append(geometry)
            self.check(phase+': actual navigation to summary gap is 24 to 32 logical pixels', 24 <= navigation_gap <= 32, geometry)
            self.check(phase+': common body width is 85 to 90 percent of viewport', .85 <= geometry['content_viewport_width_ratio'] <= .90, geometry)
            self.check(phase+': readable summary and operation fonts', 28 <= window.result_title.font().pixelSize() <= 32
                and all(21 <= card.title_font().pixelSize() <= 24 and 14 <= card.description_font().pixelSize() <= 16 for card in cards)
                and all(15 <= button.font().pixelSize() <= 17 for button in supporting), geometry)
            self.check(phase+': no horizontal overflow', scroll.horizontalScrollBar().maximum() == 0, geometry)
            self.check(phase+': supporting actions use the same grid', window.result_secondary_layout is window.result_action_grid.grid)
            self.check(phase+': main and support column edges agree', all(abs(card.x()-button.x()) <= 1
                and abs(card.width()-button.width()) <= 1 for card, button in zip(cards, supporting)))
            self.check(phase+': all supporting labels fit', all(button.fontMetrics().horizontalAdvance(button.text())+40 <= button.width() for button in supporting))
            self.check(phase+': main and supporting heights match within their rows', len({card.height() for card in cards}) == 1 and len({button.height() for button in supporting}) == 1)
            title, arrow = window.result_more_button.content_rects()
            self.check(phase+': popup arrow vertically centered', abs(arrow.center().y()-window.result_more_button.height()/2) <= 1)
            for header in (window.result_files_toggle, window.result_log_toggle):
                self.check(phase+': disclosure owns full content width '+header.text(), header.width() == window.result_content.width())
            if columns == 3:
                self.check(phase+': three equal columns and normal row spacing', max(card.width() for card in cards)-min(card.width() for card in cards) <= 1
                    and supporting[0].y()-cards[0].geometry().bottom()-1 == 16)
            else:
                controls = cards+supporting
                self.check(phase+': narrow operations stack and scroll', all(left.geometry().bottom() < right.geometry().top() for left, right in zip(controls, controls[1:]))
                    and scroll.verticalScrollBar().maximum() > 0)

        def run(self):
            p = self.page
            apply_theme('grape')
            window.showNormal()
            window.resize(1440, 900)
            yield .3
            self.check('normal initial Home with no automatically opened project', p.project is None)
            self.shot('01-home-before')
            self.click(window.subtitle_studio_button)
            yield .2
            self.check('normal Home to Studio library route', window.pages.currentWidget() is p and p.studio_empty.isVisible())
            picker = QFileDialog.getOpenFileName
            QFileDialog.getOpenFileName = lambda *args, **kwargs: (inputs['project'], '2ByteASR project')
            try:
                self.click(p.project_import_button)
            finally:
                QFileDialog.getOpenFileName = picker
            yield self.ready
            yield .3
            self.check('real imported project has at least two independent speakers', len(p.project.speakers) >= 2)
            self.check('imported project remains inside isolated output', Path(p.project_path).resolve().is_relative_to(output))
            before_names = self.names()
            before_ids = list(before_names)
            before_cues = [(cue.id, cue.text, cue.start_ms, cue.end_ms, cue.speaker_id, copy.deepcopy(cue.appearance_override)) for cue in p.project.cues]
            initial_undo = p.undo_stack.count()
            self.shot('02-studio-before-names')
            from .asr_evidence_audit import review_ui_checks
            self.result['asr_evidence_ui'] = yield from review_ui_checks(p, output/'evidence-ui')
            if p.speaker_manager_button.isVisible():
                QTimer.singleShot(0, lambda: self.click(p.speaker_manager_button))
            else:
                overflow = next(button for button in p.findChildren(QToolButton)
                    if button.isVisible() and button.menu() and button.toolTip() == '更多工作区操作')
                QTimer.singleShot(0, lambda: QTest.mouseClick(overflow, Qt.LeftButton))
                yield lambda: overflow.menu().isVisible()
                menu = overflow.menu()
                action = next(action for action in menu.actions() if action.text() == p.speaker_manager_button.text())
                QTimer.singleShot(0, lambda: QTest.mouseClick(menu, Qt.LeftButton, pos=menu.actionGeometry(action).center()))
            yield lambda: isinstance(QApplication.activeModalWidget(), SpeakerManagerDialog)
            manager = QApplication.activeModalWidget()
            manager.tabs.setCurrentIndex(1)
            yield .15
            select_all = next(button for button in manager.findChildren(QPushButton) if button.text() == '全选筛选结果')
            self.click(select_all)
            first_id, second_id = before_ids[:2]
            checked = manager._selected_ids()
            self.ascii_edit(manager, 'Edited One')
            self.check('typing adds no undo entries and Ctrl+A stays in the name input', p.undo_stack.count() == initial_undo and manager._selected_ids() == checked)
            QTest.keyClick(manager.name_edit, Qt.Key_Return)
            yield .15
            self.check('Enter changes only current stable identity', self.names()[first_id] == 'Edited One'
                and all(self.names()[identity] == before_names[identity] for identity in before_ids[1:]) and list(self.names()) == before_ids)
            self.check('Enter name edit is exactly one undo command and keeps batch checks', p.undo_stack.count() == initial_undo+1 and manager._selected_ids() == checked)
            self.check('name reaches normal cue and timeline display lookup', p._studio_speaker_name(first_id) == 'Edited One'
                and p.timeline.project.speakers[0].name == 'Edited One')
            self.shot('03-manager-enter', manager)
            self.ascii_edit(manager, '')
            QApplication.sendEvent(manager.name_edit, QInputMethodEvent('zhang', []))
            self.check('IME protocol preedit is not committed as a name', not manager._commit_name()
                and self.names()[first_id] == 'Edited One' and p.undo_stack.count() == initial_undo+1)
            committed = QInputMethodEvent('', [])
            committed.setCommitString('张三')
            QApplication.sendEvent(manager.name_edit, committed)
            manager.color_button.setFocus()
            yield .15
            self.check('IME committed Chinese survives immediate focus loss', self.names()[first_id] == '张三'
                and manager._selected_ids() == checked and p.undo_stack.count() == initial_undo+2)
            self.ascii_edit(manager, 'Row Switch')
            second_row = next(row for row in range(manager.table.rowCount()) if manager.table.item(row,1).data(Qt.UserRole) == second_id)
            QTest.mouseClick(manager.table.viewport(), Qt.LeftButton, pos=manager.table.visualItemRect(manager.table.item(second_row,2)).center())
            yield .15
            self.check('switching rows submits previous draft to the previous identity', self.names()[first_id] == 'Row Switch'
                and manager._editor_speaker_id == second_id and manager._selected_ids() == checked and p.undo_stack.count() == initial_undo+3)
            self.ascii_edit(manager, 'Close Saved')
            manager.close()
            yield .15
            self.check('closing manager submits only the active draft', self.names()[second_id] == 'Close Saved' and p.undo_stack.count() == initial_undo+4)
            p.undo_stack.undo()
            yield .1
            self.check('one undo restores only the final rename', self.names()[second_id] == before_names[second_id] and self.names()[first_id] == 'Row Switch')
            p.undo_stack.redo()
            yield .1
            self.click(p.save_button)
            yield .15
            saved_path = Path(p.project_path)
            saved = load_project(saved_path)
            self.check('saved real project retains both display names and stable IDs', {speaker.id:speaker.name for speaker in saved.speakers} == self.names() and list(self.names()) == before_ids)
            self.check('rename preserves cue text/time/speaker and manual layout', before_cues == [(cue.id, cue.text, cue.start_ms, cue.end_ms, cue.speaker_id, copy.deepcopy(cue.appearance_override)) for cue in p.project.cues])
            self.shot('04-studio-after-save')
            self.click(p.studio_back_button)
            yield .2
            window.open_studio_project(saved_path, source='five_fix_ui_saved_reopen')
            yield self.ready
            yield .15
            self.check('normal save/reopen keeps renamed speakers', self.names()[first_id] == 'Row Switch' and self.names()[second_id] == 'Close Saved')
            self.shot('05-studio-reopened')
            self.click(p.studio_back_button)
            yield .2
            completion_project = Path(inputs.get('completion_project') or saved_path)
            if inputs.get('report'):
                report = json.loads(Path(inputs['report']).read_text('utf8'))
                media_path, status = report['media']['path'], report['status']
                elapsed = float(report.get('result', {}).get('elapsed_seconds', 0))
            else:
                media_path, status, elapsed = str(saved.media.path), 'success', 0
            item = MediaResult(media_path, status, project_path=str(completion_project), report_json_path=inputs.get('report',''), elapsed_seconds=elapsed)
            window._handle_result(QueueResult((item,), elapsed))
            yield .3
            notification = getattr(window, '_completion_dialog', None)
            if notification is not None and notification.isVisible():
                self.click(notification.confirm_button)
            yield .2
            self.layout('normal-1440x900')
            self.shot('06-completion-top')
            summary_y = window.result_summary_card.mapTo(window.pages.widget(2).viewport(), QPoint()).y()
            cards_y = window.result_action_grid.mapTo(window.result_content, QPoint()).y()
            self.click(window.result_files_toggle)
            yield .2
            self.check('expanding task details only pushes lower content', window.result_files.isVisible()
                and window.result_action_grid.mapTo(window.result_content, QPoint()).y() > cards_y
                and window.result_summary_card.mapTo(window.pages.widget(2).viewport(), QPoint()).y() == summary_y)
            self.shot('07-completion-expanded')
            self.click(window.result_files_toggle)
            yield .15
            self.check('collapsing details restores the operation rows', window.result_action_grid.mapTo(window.result_content, QPoint()).y() == cards_y)
            window.resize(740, 620)
            yield .25
            self.layout('narrow-740x620')
            self.shot('08-completion-narrow-top')
            scroll = window.pages.widget(2)
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            yield .2
            for button in window.result_action_grid.secondary_actions:
                scroll.ensureWidgetVisible(button)
                yield .1
                point = button.mapTo(scroll.viewport(), QPoint())
                self.check('narrow supporting operation reachable '+button.text(), point.y() >= 0 and point.y()+button.height() <= scroll.viewport().height())
            self.shot('09-completion-narrow-bottom')
            window.resize(1440,900)
            scroll.verticalScrollBar().setValue(0)
            yield .2
            self.layout('restored-1440x900')
            self.shot('10-completion-restored')
            self.check('no provider request made', blank_project_audit._provider_calls == 0)

        def finish(self):
            self.timer.stop()
            self.result['provider_calls'] = blank_project_audit._provider_calls
            self.result['elapsed_seconds'] = round(time.monotonic()-self.started, 3)
            self.result['original_files_unchanged'] = all(Path(path).is_file() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha
                for path, sha in inputs['original_files'].items())
            window.result_exit_code = 0 if self.result['passed'] else 1
            self.write()
            def stopped():
                self.result['gui_shutdown'] = True
                self.write()
            QApplication.instance().aboutToQuit.connect(stopped)
            modal = QApplication.activeModalWidget()
            if isinstance(modal, SpeakerManagerDialog):
                modal._name_preedit = False
                modal.name_edit.setText(modal._editor_speaker_id or 'audit')
                modal.reject()
            window.close()

    window._five_fix_ui_audit = Audit()
