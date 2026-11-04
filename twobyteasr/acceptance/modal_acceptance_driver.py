"""Opt-in acceptance scheduling and diagnostics for actual nested Qt dialogs."""
from __future__ import annotations

import faulthandler
import json
import os
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication


class ModalAcceptanceDriver(QObject):
    """Keep generator advancement outside every action which may enter exec()."""

    def __init__(self, window, output, stem, *, timeout):
        super().__init__(window)
        self.output = Path(output)
        self.stem = stem
        self.window = window
        self.dialog = None
        self.busy = False
        self.finished = False
        self.waiting = 0
        self.started = time.monotonic()
        self.timeout = timeout
        self.deadline = self.started + timeout
        self.phase_name = 'constructed'
        self.events = []
        self.inflight = []
        self.pending = []
        self.result = dict(passed=False, checks=[], screenshots=[])
        self.steps = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        # A separate timer remains observable if an accidental tick enters exec.
        self.heartbeat = QTimer(self)
        self.heartbeat.timeout.connect(self.pulse)
        self.stack_file = (self.output / (stem + '-thread-stacks.log')).open('w', encoding='utf8')
        faulthandler.dump_traceback_later(15, repeat=True, file=self.stack_file)
        self.progress('constructed')

    def begin(self, steps):
        # The dialog observer must already be installed before either timer runs.
        self.steps = steps
        self.progress('begin')
        self.timer.start(50)
        self.heartbeat.start(250)

    def phase(self, name):
        self.phase_name = name
        self.progress('phase')

    @staticmethod
    def _widget(widget):
        if widget is None:
            return None
        from shiboken6 import isValid
        if not isValid(widget):
            return dict(deleted=True)
        return dict(class_name=widget.metaObject().className(), object_name=widget.objectName(),
                    title=widget.windowTitle(), visible=widget.isVisible(),
                    geometry=list(widget.geometry().getRect()))

    def progress(self, event, detail=None):
        now = time.monotonic()
        if event != 'tick' and event != 'heartbeat':
            self.events.append(dict(event=event, phase=self.phase_name,
                                    elapsed=round(now-self.started, 3), detail=detail))
            self.events = self.events[-64:]
        frame = getattr(self.steps, 'gi_frame', None)
        payload = dict(pid=os.getpid(), phase=self.phase_name, event=event,
            elapsed=round(now-self.started, 3), deadline_remaining=round(self.deadline-now, 3),
            busy=self.busy, finished=self.finished, timer_active=self.timer.isActive(),
            heartbeat_active=self.heartbeat.isActive(), pending=list(self.pending), inflight=list(self.inflight),
            waiting='condition' if callable(self.waiting) else self.waiting,
            generator_line=frame.f_lineno if frame is not None else None,
            active_modal=self._widget(QApplication.activeModalWidget()),
            active_window=self._widget(QApplication.activeWindow()), observed_dialog=self._widget(self.dialog),
            dialog_parent=self._widget(self.dialog.parentWidget()) if self.dialog is not None else None,
            visible_windows=[self._widget(w) for w in QApplication.topLevelWidgets() if w.isVisible()][:24],
            checks=len(self.result['checks']), last_check=self.result['checks'][-1:] or None,
            error=self.result.get('error'), events=list(self.events))
        self._write(self.stem + '-progress.json', payload)

    def _write(self, name, payload):
        target = self.output / name
        part = target.with_suffix(target.suffix + '.part')
        part.write_text(json.dumps(payload, ensure_ascii=False, indent=2), 'utf8')
        try:os.replace(part, target)
        except PermissionError:
            # A read-only observer can momentarily hold Windows' destination
            # without FILE_SHARE_DELETE. Keep the last complete snapshot and
            # retry publication on the next ordinary tick, never block the UI.
            self.result.setdefault('diagnostic_publish_retries',0)
            self.result['diagnostic_publish_retries']+=1

    def checkpoint(self):
        self.result['phase'] = self.phase_name
        self.result['diagnostics'] = dict(progress=self.stem+'-progress.json',
                                         thread_stacks=self.stem+'-thread-stacks.log')
        self._write(self.stem + '-result.json', self.result)

    def check(self, name, value, detail=None):
        self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        self.progress('check', name)
        self.checkpoint()
        if not value:
            raise AssertionError(name + ': ' + str(detail))

    def queue_action(self, name, action):
        self.pending.append(name)
        self.progress('action-scheduled', name)

        def perform():
            self.pending.remove(name)
            if self.finished:
                return
            self.inflight.append(name)
            self.progress('action-enter', name)
            try:
                action()
            except Exception:
                self.fail(traceback.format_exc())
            finally:
                self.inflight.remove(name)
                self.progress('action-return', name)
        QTimer.singleShot(0, perform)

    def tick(self):
        self.progress('tick')
        if self.finished or self.busy:
            return
        self.busy = True
        try:
            if time.monotonic() > self.deadline:
                raise TimeoutError('Normal UI condition timed out in phase ' + self.phase_name)
            if callable(self.waiting):
                if not self.waiting():
                    return
            elif time.monotonic() < self.waiting:
                return
            step = next(self.steps)
            self.waiting = step if callable(step) else time.monotonic()+step
            self.deadline = time.monotonic()+self.timeout
            self.progress('step-yield')
        except StopIteration:
            self.result['passed'] = True
            self.finish()
        except Exception:
            self.fail(traceback.format_exc())
        finally:
            self.busy = False

    def pulse(self):
        self.progress('heartbeat')
        if not self.finished and time.monotonic() > self.deadline:
            self.fail('TimeoutError: Normal UI condition timed out in phase ' + self.phase_name)

    def fail(self, error):
        if self.finished:
            return
        self.result['error'] = error
        # Preserve the actual exception before even attempting dialog shutdown.
        self.checkpoint()
        self.finish()

    def stop(self):
        self.finished = True
        self.timer.stop()
        self.heartbeat.stop()
        self.progress('finish')

    def close_diagnostics(self):
        faulthandler.cancel_dump_traceback_later()
        if not self.stack_file.closed:
            self.stack_file.close()

    def finish(self):
        raise NotImplementedError


def cancel_without_settings_save_prompt(dialog):
    """Cancel audit-initialization changes without entering a second save dialog."""
    if hasattr(dialog, '_values'):
        dialog._saved_values = dialog._values()
    dialog.reject()
