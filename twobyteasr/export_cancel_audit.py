"""Opt-in real export-button cancellation audit, shared by source and frozen UI.

The UI correctly rejects an existing target. This audit introduces a copied
old output at that same target only after HTML composition has really begun;
it never disables validation or changes the render job's overwrite policy.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
import traceback


def _sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def start(window, output):
    import psutil
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    from .build_identity import load_build_identity

    output = Path(output).resolve()
    config = json.loads((output/'cancel-config.json').read_text('utf8'))
    target = output/'cancelled-target.mp4'
    seed = output/'old-output-copy.mp4'
    if not seed.is_file() or target.exists():
        raise ValueError('Cancellation audit needs its copied seed and an absent target')

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.started = time.perf_counter()
            self.ui = None
            self.original_trace = None
            self.owned = {}
            self.application_children = {}
            self.baseline = set()
            self.events = []
            self.event_lock = threading.Lock()
            self.composition = threading.Event()
            self.cancel_at = None
            self.cancel_signal_at = None
            self.success = []
            self.failures = []
            self.result = dict(passed=False, build=vars(load_build_identity()), checks={},
                real_user_click=False, user_verified=False,
                entry='normal Studio render button -> normal export button -> safe cancel button',
                fixture='An old output copy is created at the accepted target after HTML composition begins.')
            self.sequence = self.run()
            self.waiting = 0.
            self.cleaning_until = None
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(25)

        def check(self, name, value):
            self.result['checks'][name] = bool(value)
            if not value:
                raise AssertionError(name)

        def descendants(self):
            rows = {}
            for process in psutil.Process().children(recursive=True):
                try:
                    key = (process.pid, process.create_time())
                    command = process.cmdline()
                    manifests = []
                    is_renderer = any(Path(arg).name == 'render-overlays.mjs' for arg in command)
                    if is_renderer:
                        for argument in command:
                            candidate = Path(argument.split('=', 1)[-1])
                            if not candidate.is_absolute(): continue
                            try:
                                resolved = candidate.resolve()
                            except OSError:
                                continue  # Device pipes are not filesystem manifests.
                            if resolved.is_relative_to(output):
                                relative = resolved.relative_to(output)
                                if any(part.startswith('2byteasr-advanced-') for part in relative.parts[:-1]):
                                    manifests.append(str(relative))
                    render_root = bool(manifests and is_renderer)
                    rows[key] = dict(pid=process.pid, created=key[1], name=process.name(), parent=process.ppid(),
                        export_root=render_root, export_arguments=manifests)
                except psutil.Error:
                    continue
            return rows

        def collect_owned(self):
            rows = self.descendants()
            self.application_children.update(rows)
            for key, row in rows.items():
                if row['export_root'] and key not in self.baseline:
                    self.owned[key] = row
            # Do not classify a warm Studio service as this export merely
            # because it started after the export button was clicked.
            while True:
                live_parents = {pid for pid, created in self.owned if (pid, created) in rows}
                added = {key: row for key, row in rows.items()
                         if key not in self.owned and row['parent'] in live_parents}
                if not added: break
                self.owned.update(added)

        def alive_owned(self):
            rows = []
            for (pid, created), row in self.owned.items():
                try:
                    process = psutil.Process(pid)
                    if process.create_time() == created and process.is_running():
                        rows.append(row)
                except psutil.Error:
                    pass
            return rows

        def click(self, button, label):
            self.check(label+'_reachable', button.isVisible() and button.isEnabled())
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.result.setdefault('clicks', []).append(dict(button=label, at=time.perf_counter()-self.started))

        def observe_trace(self, event, value=None, **fields):
            self.original_trace(event, value, **fields)
            record = dict(at=time.perf_counter()-self.started, event=event, value=value, **fields)
            with self.event_lock:
                self.events.append(record)
            if event == 'html_renderer_stage' and isinstance(value, dict) and value.get('type') == 'composition':
                self.composition.set()

        def cancelled(self):
            self.cancel_signal_at = time.perf_counter()

        def terminal(self):
            return self.cancel_signal_at is not None or bool(self.success) or bool(self.failures)

        def tick(self):
            try:
                if self.cleaning_until is not None:
                    if not self.ui or not self.ui._worker or not self.ui._worker.is_alive():
                        self.finish()
                    elif time.perf_counter() >= self.cleaning_until:
                        self.result['cleanup_timeout'] = True
                        self.finish()
                    return
                if time.perf_counter()-self.started > float(config['timeout_seconds']):
                    raise TimeoutError('Normal export cancellation deadline')
                if self.ui is not None and self.ui._running:
                    self.collect_owned()
                if callable(self.waiting):
                    if not self.waiting(): return
                elif time.perf_counter() < self.waiting:
                    return
                step = next(self.sequence)
                self.waiting = step if callable(step) else time.perf_counter()+step
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                if self.ui is not None and self.ui._running:
                    # Failure cleanup uses the same existing cancellation path.
                    self.ui._cancel_export()
                    self.cleaning_until = time.perf_counter()+15
                else:
                    self.finish()

        def run(self):
            page = self.page
            yield lambda: (page.project is not None and not page._readiness.active
                           and page.video.controller and page.video.controller.running)
            self.check('project_is_isolated', Path(page.project_path).resolve().is_relative_to(output))
            self.check('media_is_copied', Path(page.project.media.path).resolve().is_relative_to(output))
            page.video.set_paused(True)
            page.video.controller.set_volume(0)
            window.raise_()
            window.activateWindow()
            yield .2
            self.click(page.studio_render_button, 'open_export')
            yield lambda: page.export_workspace is not None and page.export_workspace.isVisible()
            self.ui = ui = page.export_workspace
            ui.directory.setText(str(output))
            ui.filename.setText(target.stem)
            ui.extension.setCurrentIndex(ui.extension.findData('mp4'))
            encoder = ui.encoder.findData('h264_nvenc')
            if encoder >= 0: ui.encoder.setCurrentIndex(encoder)
            self.check('target_is_isolated', ui.export_target().full_path.resolve() == target)
            self.check('target_absent_at_validation', not target.exists())
            self.result['old_sha256'] = _sha256(seed)
            self.original_trace = ui._export_trace
            ui._export_trace = self.observe_trace
            ui.render_cancelled.connect(self.cancelled)
            ui.render_succeeded.connect(self.success.append)
            ui.render_failed.connect(self.failures.append)
            self.baseline = set(self.descendants())
            ui.grab().save(str(output/'export-setup.png'))
            ui.preview_scroll.ensureWidgetVisible(ui.export_button)
            yield .1
            self.click(ui.export_button, 'start_export')
            yield lambda: self.composition.is_set() or self.terminal()
            self.check('real_html_composition', self.composition.is_set())
            self.check('normal_worker_running', ui._running and ui._worker.is_alive())
            self.check('normal_no_overwrite_policy', not ui._last_job.overwrite_existing)
            self.collect_owned()
            self.check('html_renderer_process_owned', any('node' in row['name'].lower() for row in self.owned.values()))
            self.check('target_not_published_before_cancel', not target.exists())
            # Exclusive creation avoids overwriting any unexpected renderer result.
            with seed.open('rb') as source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)
            self.result['competing_copy_sha256'] = _sha256(target)
            self.check('same_target_old_copy_created', self.result['competing_copy_sha256'] == self.result['old_sha256'])
            self.result['temporary_dirs_during_render'] = [str(path.relative_to(output)) for path in output.rglob('2byteasr-advanced-*') if path.is_dir()]
            self.check('real_temporary_render_directory', bool(self.result['temporary_dirs_during_render']))
            ui.grab().save(str(output/'html-composition-before-cancel.png'))
            buttons = [button for button in ui.exporting_page.findChildren(QPushButton) if button.text() == '安全取消']
            self.check('single_cancel_button', len(buttons) == 1)
            self.cancel_at = time.perf_counter()
            self.click(buttons[0], 'safe_cancel')
            yield lambda: self.terminal() and not ui._worker.is_alive()
            self.check('cancel_signal_received', self.cancel_signal_at is not None)
            self.result['cancel_return_ms'] = (self.cancel_signal_at-self.cancel_at)*1000
            self.check('cancel_latency', self.result['cancel_return_ms'] <= float(config['cancel_limit_ms']))
            yield .5
            self.check('no_success_signal', not self.success)
            self.check('no_failure_signal', not self.failures)
            self.check('owned_tree_exited', not self.alive_owned())
            self.check('old_output_preserved', target.is_file() and _sha256(target) == self.result['old_sha256'])
            self.check('seed_preserved', _sha256(seed) == self.result['old_sha256'])
            self.check('no_success_receipt', not ui._last_job.completion_metadata)
            self.check('cancelled_setup_shown', ui.pages.currentWidget() is ui.setup_page and '取消' in ui.status.text())
            self.check('no_success_page', ui.pages.currentWidget() is not ui.success_page)
            leftovers = [str(path.relative_to(output)) for path in output.rglob('2byteasr-advanced-*') if path.is_dir()]
            self.result['temporary_render_dirs'] = leftovers
            self.check('no_temporary_render_dirs', not leftovers)
            preview = Path(ui._last_job.completion_preview_path)
            self.check('no_completion_thumbnail', not preview.exists())
            ui.grab().save(str(output/'cancelled-setup.png'))
            self.result['passed'] = True

        def finish(self):
            self.timer.stop()
            self.result.update(elapsed_seconds=time.perf_counter()-self.started,
                owned=list(self.owned.values()), alive=self.alive_owned(), success_signals=self.success,
                failure_signals=self.failures, application_children=list(self.application_children.values()))
            if self.ui is not None:
                job = self.ui._last_job
                self.result['receipt'] = dict(job.completion_metadata) if job else None
                self.ui.grab().save(str(output/'final-ui.png'))
                if self.original_trace is not None:
                    self.ui._export_trace = self.original_trace
            with self.event_lock:
                (output/'export-events.json').write_text(json.dumps(self.events, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            page = self.page
            page.undo_stack.setClean()
            QTimer.singleShot(200, window.close)

    window._export_cancel_audit = Audit()
