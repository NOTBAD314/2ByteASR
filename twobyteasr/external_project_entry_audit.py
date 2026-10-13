"""Opt-in normal-entry checks, with only temporary projects and offline guards."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt, QEventLoop
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .blank_project_audit import _capture
    from .external_open import path_identity
    from .studio_project import load_project

    plan = json.loads((output/'entry-plan.json').read_text('utf8'))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.deadline = time.monotonic()+150
            self.step = 0
            self.children = []
            self.received = []
            self.pending_choice = None
            self.choice_answered = False
            self.request = None
            self.result = {'passed': False, 'checks': [], 'screenshots': [],
                           'gui_pid': os.getpid(), 'gui_executable': sys.executable,
                           'argv': sys.argv, 'source': 'normal GUI command-line and existing-instance IPC',
                           'pixel_source': 'native HWND PrintWindow on isolated desktop'}
            # Observe the real receiver after its connected intake callback
            # returns. Launcher exit alone is not receipt/dirty-guard completion.
            QApplication.instance()._instance_guard.paths_received.connect(
                self.received_paths, Qt.ConnectionType.QueuedConnection)
            self.timer = QTimer(self)
            self.timer.setInterval(100)
            self.timer.timeout.connect(self.tick)
            self.timer.start()
            QApplication.instance().aboutToQuit.connect(self.stopped)

        def check(self, value, name):
            self.result['checks'].append({'name': name, 'passed': bool(value)})
            if not value:
                raise AssertionError(name)

        def shot(self, name):
            _capture(window, output/name)
            self.result['screenshots'].append(name)

        def write(self):
            (output/'entry-result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2)+'\n','utf8')

        def stopped(self):
            self.result['gui_shutdown'] = True
            self.write()

        def send(self, paths):
            command = list(plan['command'])+list(map(str,paths))
            env = os.environ.copy()
            # This process must send its argv through the production mutex and
            # local socket, and cannot acquire its own acceptance profile.
            child = subprocess.Popen(command, cwd=plan['invoker_cwd'], env=env,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            self.children.append(child)
            if self.pending_choice is None:self.choice_answered = False
            self.request = {'paths': [path_identity(p) for p in paths],
                            'received_after': len(self.received), 'child': child}

        def received_paths(self, paths):
            self.received.append([path_identity(p) for p in paths])

        def request_done(self):
            request = self.request
            if request is None:return False
            if request.get('done'):return True
            if request['child'].poll() is None:return False
            if not any(paths == request['paths'] for paths in self.received[request['received_after']:]):return False
            intake = window._desktop_intake
            if intake.active or intake.requests:return False
            if self.pending_choice is not None and not self.choice_answered:return False
            self.check(request['child'].returncode == 0, 'request entry exited zero and actual receiver completed matching paths')
            self.result.setdefault('handled_requests', []).append({
                'paths': request['paths'], 'entry_process_pid': request['child'].pid,
                'entry_process_exit': request['child'].returncode,
                'receiver_callback_completed': True,
                'dirty_choice': self.pending_choice.name if self.pending_choice is not None else None,
                'dirty_choice_answered': self.choice_answered})
            request['done'] = True
            self.pending_choice = None
            return True

        def digest(self, path):
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()

        def wait_ui(self, predicate):
            if predicate():return True
            loop = QEventLoop(); poll = QTimer(); limit = QTimer()
            poll.setInterval(25); poll.timeout.connect(lambda: loop.quit() if predicate() else None)
            limit.setSingleShot(True); limit.timeout.connect(loop.quit)
            self.timer.stop(); poll.start(); limit.start(5000)
            try:loop.exec()
            finally:poll.stop(); limit.stop(); self.timer.start()
            return bool(predicate())

        def edit_text(self, text):
            cue = self.page.project.cues[0]
            if not self.page.video.playback_position_snapshot().paused:
                QTest.mouseClick(self.page.play_button,Qt.MouseButton.LeftButton)
            self.check(self.wait_ui(lambda:self.page.video.playback_position_snapshot().paused),
                       'ordinary play control pauses before text editing')
            self.page.timeline.seek_requested.emit((cue.start_ms+min(100,(cue.end_ms-cue.start_ms)//2))/1000.0)
            self.check(self.wait_ui(lambda: cue.start_ms <=
                       self.page.video.playback_position_snapshot().presentation_media_ms < cue.end_ms),
                       'normal timeline seek establishes the target cue before E editing')
            self.page.select_cue(cue.id)
            self.page.timeline.setFocus()
            QTest.keyClick(self.page.timeline, Qt.Key.Key_E)
            editor = self.page.subtitle_edit_input
            self.check(getattr(self.page, '_canvas_editor', None) is editor,
                       'ordinary subtitle editor opened for owned temporary project')
            self.check(editor.toPlainText()==cue.text,'ordinary E editor resolves exact intended cue text')
            editor.selectAll()
            event = QInputMethodEvent(); event.setCommitString(text)
            QApplication.sendEvent(editor, event)
            QTest.keyClick(editor, Qt.Key.Key_Return)
            self.check(self.wait_ui(lambda:self.page.project.cues[0].text == text and not self.page.undo_stack.isClean()),
                       'normal text edit makes a real changed project dirty')

        def choose(self, button):
            self.pending_choice = button
            self.choice_answered = False
            def click():
                if self.pending_choice != button or self.choice_answered:return
                if time.monotonic()>self.deadline:return
                for widget in QApplication.instance().topLevelWidgets():
                    if isinstance(widget,QMessageBox) and widget.isVisible():
                        buttons = widget.standardButtons()
                        required = (QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                                    QMessageBox.StandardButton.Cancel)
                        if buttons != required or widget.window() is not widget:continue
                        target = widget.button(button)
                        if target is not None:
                            name = 'dirty-'+button.name.lower()+'.png'
                            _capture(widget,output/name)
                            self.result['screenshots'].append(name)
                            self.result.setdefault('dirty_dialogs', []).append({
                                'button':button.name, 'text':widget.text(), 'observed':True})
                            QTest.mouseClick(target,Qt.MouseButton.LeftButton)
                            self.choice_answered = True
                            return
                QTimer.singleShot(50,click)
            QTimer.singleShot(50,click)

        def tick(self):
            try:
                if time.monotonic()>self.deadline:
                    raise TimeoutError(f'entry acceptance timed out at step {self.step}')
                gate = getattr(self.page,'_readiness',None)
                if gate is not None and gate.active:
                    return
                case = plan['case']
                if self.step == 0:
                    if plan.get('bridge')=='startup':
                        guard = QApplication.instance()._instance_guard
                        if not guard._seen_requests:return
                        if window._desktop_intake.active or window._desktop_intake.requests:return
                        # Consume the queued observer before issuing another
                        # identical path, so the startup request cannot stand in
                        # for our later duplicate-open request.
                        if guard._receiver_ready and not self.received:
                            if not getattr(self,'startup_observer_turn',False):
                                self.startup_observer_turn=True
                                return
                        self.result['startup_forward_request_accepted']=True
                    self.check(window.pages.currentWidget() is self.page if case=='library' else
                               (window.pages.currentWidget() is window.settings_scroll if case=='home' else self.page.project is not None), 'startup page and explicit project precedence')
                    self.check(not hasattr(window,'ai_panel') if case in {'library','project'} else hasattr(window,'ai_panel'), 'recognition controls are deferred for project/library startup')
                    if case in {'library','home'}:
                        self.shot('01-startup.png')
                        if case=='library':
                            window._return_to_settings()
                            self.check(hasattr(window,'ai_panel') and window.pages.currentWidget() is window.settings_scroll,'recognition page builds when requested')
                            self.shot('02-home-after-library.png')
                        self.finish()
                        return
                    expected = load_project(plan['project'])
                    self.check(path_identity(self.page.session.project_path)==path_identity(plan['project']),'external project path loaded')
                    self.check([(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id) for c in self.page.project.cues] ==
                               [(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id) for c in expected.cues], 'timeline and subtitle tracks loaded exactly')
                    self.check(self.page.project.styles==expected.styles and self.page.project.media.path==expected.media.path,'styles and media identity loaded')
                    self.original = self.page.project
                    self.baseline_sha = self.digest(plan['project'])
                    self.baseline_text = self.original.cues[0].text
                    self.other_sha = self.digest(plan['other_project'])
                    self.generation = self.page.session.generation
                    self.shot('01-external-project.png')
                    self.send([plan['project']])
                    self.step = 1
                    return
                if self.step == 1:
                    if not self.request_done():return
                    self.check(self.page.project is self.original and self.page.session.generation==self.generation,'duplicate open activates existing project without reload')
                    self.edit_text(self.baseline_text+' (cancel audit)')
                    self.choose(QMessageBox.StandardButton.Cancel)
                    self.send([plan['other_project']])
                    self.step = 2
                    return
                if self.step == 2:
                    if not self.request_done():return
                    self.check(self.page.project is self.original and not self.page.undo_stack.isClean(),'dirty Cancel preserves the current project')
                    self.check(self.digest(plan['project'])==self.baseline_sha,'dirty Cancel does not write old project')
                    self.saved_text = self.baseline_text+' (saved audit)'
                    self.edit_text(self.saved_text)
                    self.choose(QMessageBox.StandardButton.Save)
                    self.send([plan['other_project']])
                    self.step = 20
                    return
                if self.step == 20:
                    if not self.request_done():return
                    if path_identity(self.page.session.project_path)!=path_identity(plan['other_project']):return
                    saved = load_project(plan['project'])
                    self.saved_sha = self.digest(plan['project'])
                    self.check(self.saved_sha!=self.baseline_sha and saved.cues[0].text==self.saved_text,
                               'dirty Save writes real text to owned old project before replacement')
                    self.check(self.digest(plan['other_project'])==self.other_sha,
                               'dirty Save leaves incoming project bytes unchanged')
                    self.shot('02-save-opens-incoming.png')
                    self.send([plan['project']]);self.step = 21
                    return
                if self.step == 21:
                    if not self.request_done():return
                    if path_identity(self.page.session.project_path)!=path_identity(plan['project']):return
                    self.check(self.page.project.cues[0].text==self.saved_text,
                               'saved old project reopens with exact changed text')
                    self.edit_text(self.baseline_text+' (discard audit)')
                    self.choose(QMessageBox.StandardButton.Discard)
                    self.send([plan['other_project']]);self.step = 22
                    return
                if self.step == 22:
                    if not self.request_done():return
                    if path_identity(self.page.session.project_path)!=path_identity(plan['other_project']):return
                    self.check(self.digest(plan['project'])==self.saved_sha and
                               load_project(plan['project']).cues[0].text==self.saved_text,
                               'dirty Discard replaces project without writing old project')
                    self.shot('03-discard-opens-incoming.png')
                    self.send([plan['project']]);self.step = 23
                    return
                if self.step == 23:
                    if not self.request_done():return
                    if path_identity(self.page.session.project_path)!=path_identity(plan['project']):return
                    self.check(self.page.project.cues[0].text==self.saved_text,
                               'discarded edit is absent after real project reopen')
                    self.original = self.page.project
                    self.send([plan['broken_project']])
                    self.step = 3
                    return
                if self.step == 3:
                    if self.request is not None and not self.request_done():return
                    if not gate or not gate.profile.get('error'):return
                    self.check(self.page.project is self.original,'corrupt external project preserves old usable project')
                    self.check('could not read project' in gate.profile['error']['message'],'corrupt project has loader error rather than media format error')
                    self.shot('02-corrupt-keeps-current.png')
                    QTest.mouseClick(gate.back,Qt.MouseButton.LeftButton)
                    self.check(not gate.overlay.isVisible() and self.page.project is self.original,'failure dismissal returns to current workspace')
                    self.send([plan['future_project']])
                    self.step = 4
                    return
                if self.step == 4:
                    if self.request is not None and not self.request_done():return
                    if not gate or not gate.profile.get('error'):return
                    self.check('schema_version' in gate.profile['error']['message'],'newer project has version-specific error')
                    self.check(self.page.project is self.original,'newer project preserves current project')
                    QTest.mouseClick(gate.back,Qt.MouseButton.LeftButton)
                    self.send([plan['other_project']])
                    self.step = 5
                    return
                if self.step == 5:
                    if self.request is not None and not self.request_done():return
                    if not self.page.project or path_identity(self.page.session.project_path)!=path_identity(plan['other_project']):return
                    self.check(self.page.relink_button.isVisible(),'missing media opens editable project with relink action')
                    self.shot('03-missing-media.png')
                    self.result['child_exit_codes'] = [p.poll() for p in self.children]
                    self.check(all(p.poll()==0 for p in self.children),'all owned request entry processes exit zero')
                    self.result['save_discard_checks'] = {'owned_project':plan['project'],
                        'initial_sha256':self.baseline_sha,'saved_sha256':self.saved_sha,
                        'saved_text':self.saved_text,'discard_kept_sha256':self.digest(plan['project'])}
                    self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.timer.stop()
                self.write()
                self.deadline = time.monotonic()+5
                self.choose(QMessageBox.StandardButton.Discard)
                window.close()

        def finish(self):
            self.result['passed'] = True
            self.timer.stop()
            self.write()
            window.close()

    window._external_entry_audit = Audit()
