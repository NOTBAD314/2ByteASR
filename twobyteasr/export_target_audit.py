"""Opt-in normal Studio export acceptance on a copied real project.

Only start() imports Qt. Helpers can be checked without opening a window or
encoding. Every render goes through the production export/queue controls.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def short_target_cases(encoder_plan='mixed'):
    if encoder_plan not in {'mixed', 'software', 'auto'}:
        raise ValueError('Unknown encoder plan')
    encoders = ('libx264', 'libx264', 'auto') if encoder_plan == 'mixed' else (
        ('libx264',)*3 if encoder_plan == 'software' else ('auto',)*3)
    return tuple((target, encoder, blur) for (target, blur), encoder in zip(
        ((5000, False), (10000, True), (20000, False)), encoders))


def active_main_encoding(directory):
    """Read actual Popen lifecycle events; preparation and finished encodes fail."""
    if not directory:
        return None
    try:
        records = [json.loads(line) for line in (Path(directory)/'processes.jsonl').read_text('utf-8').splitlines() if line]
    except (OSError, ValueError, TypeError):
        return None
    exited = {row.get('payload', {}).get('process_id') for row in records if row.get('event') == 'process_exited'}
    for row in reversed(records):
        payload = row.get('payload', {})
        if (row.get('event') == 'process_started' and payload.get('process_id') not in exited
                and payload.get('pid') and payload.get('purpose') in
                {'ffmpeg studio render', 'advanced preview/render child'}
                and payload.get('actual_encoder') == 'libx264'):
            return payload
    return None


def prepare_variant(payload, variant):
    """Render-route fixtures preserve all authored speech and source evidence."""
    result = copy.deepcopy(payload)
    if variant == 'native':
        result['style_recipes'] = {}
    elif variant == 'alpha':
        recipes = result.get('style_recipes', {})
        if not recipes:
            raise ValueError('Alpha case requires a real authored advanced style')
        for recipe in recipes.values():
            # A deliberately derived fixture, never claimed as the user design.
            recipe.pop('visualGraph', None)
            recipe['motion'] = dict(entry=dict(type='fade', duration=240),
                exit=dict(type='fade', duration=180))
            recipe['background'] = dict(enabled=True, color='#90000000')
            recipe['engine'] = 'remotion'
    elif variant != 'authored':
        raise ValueError('Unknown render-route fixture')
    return result


def validate_video_receipt(receipt, target_kbps, duration_seconds, *, fps=60,
                           width=1920, height=1080):
    """Validate actual packet measurement, separately from container bitrate."""
    measured = receipt.get('video_bitrate') or {}
    streams = receipt.get('streams') or []
    video = next((row for row in streams if row.get('codec_type') == 'video'), {})
    rate = measured.get('average_bitrate_bps')
    reliable = measured.get('reliable') is True
    target = target_kbps * 1000
    finite = isinstance(rate, (int, float)) and not isinstance(rate, bool) and math.isfinite(rate)
    difference = abs(rate-target)/target if finite and target > 0 else None
    seconds = measured.get('duration_seconds')
    try:
        duration_ok = abs(float(seconds)-duration_seconds) <= max(.05, 2/fps)
        fraction = str(video.get('avg_frame_rate', '0')).split('/')
        actual_fps = float(fraction[0])/float(fraction[1]) if len(fraction) == 2 else float(fraction[0])
        frames_ok = abs(int(video['nb_frames'])-round(duration_seconds*fps)) <= 1
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        duration_ok, actual_fps, frames_ok = False, 0, False
    checks = {
        'packet_measurement_reliable': reliable and int(measured.get('packet_count', 0) or 0) > 0,
        'requested_video_target_preserved': receipt.get('requested_video_bitrate_bps') == target,
        'video_target_within_ten_percent': reliable and difference is not None and difference <= .10,
        'dimensions_preserved': video.get('width') == width and video.get('height') == height,
        'duration_preserved': duration_ok,
        'frame_rate_and_count_preserved': abs(actual_fps-fps) < .01 and frames_ok,
        'actual_software_x264': receipt.get('actual_encoder') == 'libx264',
        'actual_target_control': str(receipt.get('actual_rate_control', '')).startswith('target'),
    }
    return dict(passed=all(checks.values()), checks=checks, measured_video_kbps=rate/1000 if finite else None,
        target_kbps=target_kbps, relative_error=difference, receipt=receipt)


def validate_process_diagnostics(directory, frozen_context, target_kbps):
    """Match production Popen records to the job; probes never count as encoding."""
    path = Path(directory)
    try:
        manifest = json.loads((path/'manifest.json').read_text('utf-8'))
        events = [json.loads(line) for line in (path/'processes.jsonl').read_text('utf-8').splitlines() if line]
    except (OSError, ValueError, TypeError) as exc:
        return dict(passed=False, checks={'actual_process_log_readable': False}, error=type(exc).__name__)
    started = [row.get('payload', {}) for row in events if row.get('event') == 'process_started']
    exited = {row.get('payload', {}).get('process_id'): row.get('payload', {}).get('returncode')
        for row in events if row.get('event') == 'process_exited'}
    finals = [row for row in started if row.get('purpose') in
        {'ffmpeg studio render', 'advanced preview/render child'} and row.get('actual_encoder') == 'libx264']
    final = finals[-1] if finals else {}
    argv = final.get('argv') or []
    value = argv[argv.index('-b:v')+1] if '-b:v' in argv and argv.index('-b:v')+1 < len(argv) else None
    stderr_name = final.get('stderr_log')
    stderr_path = path/str(stderr_name) if stderr_name else None
    stderr_retained = bool(stderr_path and stderr_path.is_file() and stderr_path.stat().st_size > 0)
    successful = lambda purpose: any(row.get('purpose') == purpose
        and exited.get(row.get('process_id')) == 0 for row in started)
    checks = dict(
        actual_process_log_readable=True,
        job_identity_matches=bool(frozen_context.get('job_id')) and all(
            row.get('job_id') == frozen_context.get('job_id') for row in events),
        frozen_request_matches_manifest=all(manifest.get(key) == frozen_context.get(key)
            for key in ('job_id', 'project_revision', 'requested_encoder', 'requested_settings')),
        requested_video_target_matches_manifest=manifest.get('target_video_bitrate_bps') == target_kbps*1000,
        actual_final_encode_exited_successfully=bool(final) and exited.get(final.get('process_id')) == 0,
        actual_bitrate_argument_matches_target=value == f'{target_kbps}k',
        actual_target_command_excludes_quality_control=not any(flag in argv for flag in
            ('-crf', '-cq', '-qp', '-qp_i', '-global_quality')) and bool(final),
        complete_encoder_stderr_retained=stderr_retained,
        complete_production_decode_exited_successfully=successful('complete staged export decode'),
        video_packet_probe_exited_successfully=successful('export v:0 packet bitrate measurement'),
        published_job_finish_recorded=any(row.get('event') == 'job_finished'
            and row.get('payload', {}).get('published') is True for row in events),
    )
    return dict(passed=all(checks.values()), checks=checks, manifest_path=str(path/'manifest.json'),
        processes_path=str(path/'processes.jsonl'), actual_final_process=final,
        encoder_stderr_path=str(stderr_path) if stderr_path else None)


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QLineEdit, QInputDialog, QDialogButtonBox, QFileDialog
    from .blank_project_audit import _capture
    from . import blank_project_audit
    from .build_identity import load_build_identity
    from .studio_project import load_project
    from .theme_manager import apply_theme

    output = Path(output)
    inputs = json.loads((output/'input.json').read_text('utf-8'))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.ui = None
            self.queue = None
            self.started = time.monotonic()
            self.result = dict(passed=False, checks=[], exports=[], screenshots=[],
                identity=load_build_identity().to_dict(), executable=sys.executable,
                entry='frozen' if getattr(sys, 'frozen', False) else 'quick_start.main',
                pid=os.getpid(), inputs=inputs, scope=inputs['scope'], variant=inputs['variant'])
            self.steps = self.run()
            self.waiting, self.deadline = 0, time.monotonic()+90
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.write()
            self.timer.start(40)

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False,
                indent=2, default=str), 'utf-8')

        def check(self, name, passed, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))
            self.write()
            if not passed:
                raise AssertionError(name+': '+str(detail))

        def tick(self):
            try:
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox):
                    raise RuntimeError('Unexpected modal: '+modal.text()+' '+modal.informativeText())
                now = time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now > self.deadline:
                            raise TimeoutError('Normal export GUI step timed out')
                        return
                elif now < self.waiting:
                    return
                step = next(self.steps)
                if isinstance(step, tuple):
                    self.waiting, timeout = step
                else:
                    self.waiting, timeout = step, 90
                if not callable(self.waiting):
                    self.waiting = time.monotonic()+float(self.waiting)
                self.deadline = time.monotonic()+timeout
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def ready(self):
            p = self.page
            return bool(p.project and p._readiness.ready and not p._readiness.active
                and p._project_view_state == 'open')

        def shot(self, name):
            target = output/(name+'.png')
            _capture(window, target)
            self.result['screenshots'].append(str(target))
            self.write()

        def visible(self, widget):
            QApplication.processEvents()
            if self.ui is not None and self.ui.settings_scroll.widget().isAncestorOf(widget):
                # Expansion/custom-mode signals can queue another layout pass.
                # Settle it before positioning the actual mouse target.
                for _ in range(2):
                    self.ui.settings_scroll.ensureWidgetVisible(widget, 8, 20)
                    QApplication.processEvents()
                viewport = self.ui.settings_scroll.viewport()
                center = widget.mapTo(viewport, widget.rect().center())
                self.check('control center inside real scroll viewport', viewport.rect().contains(center),
                    dict(control=widget.objectName(), center=[center.x(), center.y()],
                         viewport=[viewport.width(), viewport.height()]))
            QApplication.processEvents()
            self.check('control enabled: '+widget.objectName(), widget.isVisible() and widget.isEnabled())

        def click(self, widget):
            self.visible(widget)
            QTest.mouseClick(widget, Qt.LeftButton)

        def combo(self, widget, data):
            self.visible(widget)
            self.check('real combo option exists', widget.findData(data) >= 0, data)
            widget.setFocus()
            QTest.keyClick(widget, Qt.Key_F4)
            QApplication.processEvents()
            view = widget.view()
            index = widget.findData(data)
            item = widget.model().index(index, widget.modelColumn(), widget.rootModelIndex())
            view.scrollTo(item)
            QApplication.processEvents()
            # Background capability refreshes may replace the encoder rows.
            # Select from the live popup model after its geometry has settled.
            index = widget.findData(data)
            item = widget.model().index(index, widget.modelColumn(), widget.rootModelIndex())
            rect = view.visualRect(item)
            visible_rect = rect.intersected(view.viewport().rect())
            actual = view.indexAt(visible_rect.center())
            def snapshot():
                rows = [dict(index=i, data=widget.itemData(i), text=widget.itemText(i)) for i in range(widget.count())]
                geometry = view.window().geometry()
                detail = dict(target=data, current_data=widget.currentData(), current_index=widget.currentIndex(),
                    selection_mode='actual popup keyboard Home/Down/Return',
                    view_current_data=view.currentIndex().data(Qt.UserRole),
                    view_has_focus=view.hasFocus(),
                    options=rows, requested_index=index, item_data=item.data(Qt.UserRole),
                    click_item_data=actual.data(Qt.UserRole), item_rect=[rect.x(), rect.y(), rect.width(), rect.height()],
                    click_rect=[visible_rect.x(), visible_rect.y(), visible_rect.width(), visible_rect.height()],
                    popup_rect=[geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                    popup_visible=view.isVisible())
                if self.ui is not None and widget is self.ui.encoder:
                    from .studio_render import load_encoder_capabilities
                    cached = load_encoder_capabilities(self.ui.ffmpeg) or {}
                    detail['capability_cache'] = {key: cached.get(key) for key in ('schema', 'scanned_at', 'available_by_codec', 'ffmpeg')}
                    detail['advanced_checked'] = self.ui.advanced_button.isChecked()
                return detail
            before = snapshot()
            self.result.setdefault('combo_events', []).append(dict(before=before))
            self.check('real combo popup item visible', index >= 0 and view.isVisible()
                and not visible_rect.isEmpty() and actual.data(Qt.UserRole) == data, before)
            view.setFocus()
            QTest.keyClick(view, Qt.Key_Home)
            for _ in range(index):
                QTest.keyClick(view, Qt.Key_Down)
            self.check('real popup keyboard highlighted requested item',
                view.currentIndex().data(Qt.UserRole) == data, snapshot())
            QTest.keyClick(view, Qt.Key_Return)
            QApplication.processEvents()
            after = snapshot()
            self.result['combo_events'][-1]['after'] = after
            if widget.currentData() != data:
                self.shot('combo-failed-'+str(len(self.result['combo_events'])))
            self.check('real combo popup selection', widget.currentData() == data and not view.isVisible(), after)

        def edit(self, widget, text, *, blur=True):
            self.visible(widget)
            widget.setFocus()
            QTest.keyClick(widget, Qt.Key_A, Qt.ControlModifier)
            if str(text):
                QTest.keyClicks(widget, str(text))
            else:
                QTest.keyClick(widget, Qt.Key_Backspace)
            if blur:
                QTest.keyClick(widget, Qt.Key_Tab)

        def settings(self, target, encoder, *, blur):
            ui = self.ui
            self.combo(ui.codec, 'h264')
            self.combo(ui.quality, 'recommended')
            if not ui.advanced_button.isChecked():
                self.click(ui.advanced_button)
            self.combo(ui.encoder, encoder)
            self.combo(ui.rate_control, 'target')
            self.combo(ui.audio, inputs['audio'])
            self.edit(ui.bitrate.lineEdit(), target, blur=blur)
            # Do not call _render_settings here: it could commit the unblurred
            # spinbox and hide a lost-draft defect before the real Start click.
            self.result['last_ui_draft'] = dict(target=target, encoder_dropdown=ui.encoder.currentData(),
                quality=ui.quality.currentData(), rate_control=ui.rate_control.currentData(),
                line_edit_text=ui.bitrate.lineEdit().text(), focused=ui.bitrate.lineEdit().hasFocus(),
                blur_requested=blur)
            self.check('spinbox blur condition exercised',
                bool(ui.bitrate.lineEdit().hasFocus()) != blur, self.result['last_ui_draft'])

        def destination(self, name):
            self.edit(self.ui.directory, str(output/'exports'))
            self.edit(self.ui.filename, name)
            self.edit(self.ui.filename_prefix.lineEdit(), '')
            self.edit(self.ui.filename_suffix.lineEdit(), '')

        def set_range(self, start, seconds):
            for field, value in zip(self.ui.project_range_bar.fields, (start, start+seconds)):
                whole, ms = divmod(round(value*1000), 1000)
                minutes, sec = divmod(whole, 60)
                hours, minute = divmod(minutes, 60)
                self.edit(field, f'{hours:02}:{minute:02}:{sec:02}.{ms:03}')
            # The production range dropdown reflects actual range points. An
            # in/out selection with both points empty immediately resets all.
            self.combo(self.ui.export_range, 'in_out')
            self.check('production range equals authored request',
                abs(self.ui._range_seconds()[0]-start) < .001
                and abs(self.ui._range_seconds()[2]-seconds) < .001)

        def job_check(self, job, target, encoder):
            context = getattr(job, 'export_context', {})
            self.check('frozen target settings', job.settings.quality_mode == 'target'
                and job.settings.bitrate_kbps == target, asdict(job.settings))
            self.check('frozen requested encoder', context.get('requested_encoder') == encoder, context)
            self.check('job identity and project revision recorded', bool(context.get('job_id'))
                and str(context.get('project_revision', '')).startswith('sha256:'), context)

        def actual_receipt(self, job, target, seconds, case):
            measured = validate_video_receipt(copy.deepcopy(job.completion_metadata), target, seconds,
                fps=inputs['expected_fps'], width=inputs['width'], height=inputs['height'])
            measured.update(case=case, output=job.output_path, settings=asdict(job.settings),
                frozen_context=copy.deepcopy(getattr(job, 'export_context', {})))
            self.result['exports'].append(measured)
            self.write()
            for name, passed in measured['checks'].items():
                self.check(case+': '+name, passed)
            audio_streams = [row for row in measured['receipt'].get('streams', []) if row.get('codec_type') == 'audio']
            self.check(case+': requested audio presence preserved',
                bool(audio_streams) == (inputs['audio'] != 'none'),
                dict(requested=inputs['audio'], streams=audio_streams))
            diagnostics = measured['receipt'].get('diagnostics_path')
            self.check(case+': independent process diagnostics retained',
                bool(diagnostics) and Path(diagnostics).is_dir()
                and Path(diagnostics).resolve().is_relative_to((output/'diagnostics').resolve()),
                diagnostics)
            processes = validate_process_diagnostics(diagnostics, measured['frozen_context'], target)
            measured['process_diagnostics'] = processes
            self.write()
            for name, passed in processes['checks'].items():
                self.check(case+': '+name, passed)

        def direct(self, target, encoder, blur, seconds, name):
            self.destination(name)
            self.set_range(inputs['start_seconds'], seconds)
            self.settings(target, encoder, blur=blur)
            self.shot(name+'-before-start')
            self.click(self.ui.export_button)
            yield .05
            self.check('actual direct worker began', self.ui._running and self.ui._last_job is not None,
                self.ui.failure_reason.text())
            job = self.ui._last_job
            self.job_check(job, target, encoder)
            self.result.setdefault('frozen_jobs', []).append(dict(case=name,
                output=job.output_path, settings=asdict(job.settings), context=getattr(job, 'export_context', {})))
            yield (lambda: not self.ui._running, inputs['job_timeout'])
            yield .15
            self.check(name+': normal success page', self.ui.pages.currentWidget() == self.ui.success_page,
                self.ui.failure_reason.text())
            self.actual_receipt(job, target, seconds, name)
            self.shot(name+'-success')
            self.ui._return_to_settings()
            yield .1

        def preferences(self):
            """Actual settings persist after submitting an export; save/reopen."""
            ui = self.ui
            self.click(ui.findChild(QPushButton, 'exportBackButton'))
            self.ui = None
            yield .1
            self.click(self.page.save_button)
            yield .1
            path = Path(self.page.project_path)
            self.check('saved copied project retains manual edits',
                load_project(path).studio_state.get('manual_caption_text', {}) == self.manual_before)
            self.click(self.page.studio_back_button)
            yield .1
            window.open_studio_project(path, source='export_target_saved_reopen')
            yield self.ready
            self.click(self.page.studio_render_button)
            yield lambda: self.page.export_workspace is not None
            self.ui = self.page.export_workspace
            yield .1
            self.check('normal save/reopen restores target preferences',
                self.ui.rate_control.currentData() == 'target' and self.ui.bitrate.value() == 10000)

        def preset_roundtrip(self):
            """Drive the actual menu and actual modal, with no dialog monkeypatch."""
            ui = self.ui
            QTimer.singleShot(0, lambda: self.click(ui.preset_menu_button))
            yield lambda: QApplication.activePopupWidget() is not None
            menu = ui.preset_menu_button.menu()
            action = next(item for item in menu.actions() if '另存为' in item.text())
            QTimer.singleShot(0, lambda: QTest.mouseClick(menu, Qt.LeftButton,
                pos=menu.actionGeometry(action).center()))
            yield lambda: isinstance(QApplication.activeModalWidget(), QInputDialog)
            dialog = QApplication.activeModalWidget()
            self.edit(dialog.findChild(QLineEdit), 'audit target 20000')
            self.click(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok))
            yield .1
            preset_id = ui.preset.currentData()
            self.check('actual saved user preset selected', str(preset_id).startswith('user-'))
            self.combo(ui.preset, 'recommended')
            self.combo(ui.preset, preset_id)
            job = ui._job(output/'exports'/'preset-not-encoded.mp4')
            self.check('saved user preset restores target and manual bitrate',
                job.settings.quality_mode == 'target' and job.settings.bitrate_kbps == 20000,
                asdict(job.settings))

        def queued(self):
            from .studio_render_queue import get_render_queue
            self.destination('queue-10000')
            seconds = inputs['short_seconds']
            self.set_range(inputs['start_seconds'], seconds)
            self.settings(10000, 'libx264', blur=False)
            self.queue = get_render_queue(self.ui.ffmpeg)
            before_count = len(self.queue.jobs())
            self.click(self.ui.queue_button)
            yield .05
            self.check('real queue button submitted', len(self.queue.jobs()) == before_count+1, self.ui.status.text())
            submitted = self.queue.jobs()[-1]
            frozen = copy.deepcopy(submitted.job.export_project_data)
            context = copy.deepcopy(getattr(submitted.job, 'export_context', {}))
            self.job_check(submitted.job, 10000, 'libx264')
            cue = self.page.project.cues[0]
            text = cue.text
            undo_before = self.page.undo_stack.index()
            # One production edit command on the copied project; restored by
            # Undo below. This is labelled separately from keyboard UI input.
            self.page.cue_controller.set_text(cue.id, text+' [queue freeze audit]')
            self.settings(5000, 'libx264', blur=True)
            self.set_range(inputs['start_seconds']+1, max(1, seconds-2))
            again = self.queue.jobs()[-1]
            self.check('queue snapshot survives live text/settings/range changes',
                again.job.export_project_data == frozen and getattr(again.job, 'export_context', {}) == context
                and again.job.settings.bitrate_kbps == 10000 and again.job.duration_seconds == seconds)
            while self.page.undo_stack.index() > undo_before:
                self.page.undo_stack.undo()
            yield (lambda: self.queue.jobs()[-1].status in ('Completed', 'Failed'), inputs['job_timeout'])
            final = self.queue.jobs()[-1]
            self.check('actual queued export completed', final.status == 'Completed', final.error)
            # jobs() intentionally omits ephemeral completion metadata from its
            # persisted DTO. Read the actual worker-owned job after completion.
            with self.queue._condition:
                live_job = next(row.job for row in self.queue._jobs if row.id == final.id)
            self.actual_receipt(live_job, 10000, seconds, 'queue')
            self.result['queue'] = dict(id=final.id, status=final.status, context=context,
                frozen_project_hash=content_hash(frozen), edit_scope='production cue edit command on tmp copy then Undo')
            self.queue.stop(timeout=.01)

        def run(self):
            p = self.page
            apply_theme('grape')
            window.showNormal()
            window.resize(1480, 980)
            yield .3
            self.check('normal initial Home with no automatically opened project', p.project is None)
            self.shot('01-home-before-import')
            self.click(window.subtitle_studio_button)
            yield .2
            self.check('normal Home to Studio library route',
                window.pages.currentWidget() is p and p.studio_empty.isVisible())
            # Only the native file choice is supplied by the driver. The real
            # import button still owns loading, readiness and library routing.
            picker = QFileDialog.getOpenFileName
            QFileDialog.getOpenFileName = lambda *args, **kwargs: (inputs['project'], '2ByteASR project')
            try:
                self.click(p.project_import_button)
            finally:
                QFileDialog.getOpenFileName = picker
            yield self.ready
            yield .3
            self.check('imported project remains inside isolated output',
                Path(p.project_path).resolve().is_relative_to(output))
            self.shot('02-studio-after-import')
            self.page.video.set_paused(True)
            self.manual_before = copy.deepcopy(self.page.project.studio_state.get('manual_caption_text', {}))
            self.speech_before = [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id) for c in self.page.project.cues]
            self.check('normal project includes original manual edits', len(self.manual_before) == inputs['manual_caption_count'])
            self.click(self.page.studio_render_button)
            yield lambda: self.page.export_workspace is not None
            self.ui = self.page.export_workspace
            yield .2
            scope = inputs['scope']
            if scope == 'controls':
                self.destination('controls-not-encoded')
                self.set_range(inputs['start_seconds'], inputs['short_seconds'])
                for target, blur in ((5000, False), (10000, True), (20000, False)):
                    self.settings(target, 'libx264', blur=blur)
                    job = self.ui._job(output/'exports'/f'controls-{target}.mp4')
                    self.job_check(job, target, 'libx264')
                    self.result.setdefault('control_jobs', []).append(dict(target=target, settings=asdict(job.settings),
                        context=getattr(job, 'export_context', {}), scope='real controls through production job preparation; no encode'))
                self.shot('controls-target')
                yield from self.preset_roundtrip()
            elif scope == 'short':
                for target, encoder, blur in short_target_cases(inputs.get('encoder_plan', 'mixed')):
                    yield from self.direct(target, encoder, blur, inputs['short_seconds'], f'short-{target}-{encoder}')
            elif scope == 'full':
                inputs['start_seconds'] = 0
                yield from self.direct(10000, 'libx264', False, inputs['full_seconds'], 'full-10000')
                yield from self.preferences()
            elif scope == 'queue':
                yield from self.queued()
            elif scope == 'edges':
                yield from self.direct(10000, 'libx264', False, inputs['short_seconds'], 'same-name')
                existing = Path(self.ui._last_job.output_path)
                existing_sha = file_sha256(existing)
                self.destination('same-name')
                self.settings(10000, 'libx264', blur=True)
                self.click(self.ui.export_button)
                yield .1
                self.check('same-name protection refuses existing product',
                    not self.ui._running and self.ui.pages.currentWidget() == self.ui.failure_page)
                self.check('same-name protection preserves original product bytes',
                    existing.is_file() and file_sha256(existing) == existing_sha,
                    dict(path=str(existing), sha256_before=existing_sha,
                         sha256_after=file_sha256(existing) if existing.is_file() else None))
                self.ui._return_to_settings()
                self.destination('cancelled')
                self.set_range(inputs['start_seconds'], inputs['short_seconds'])
                self.settings(10000, 'libx264', blur=False)
                self.click(self.ui.export_button)
                yield lambda: self.ui._running
                def encoding():
                    context = getattr(self.ui._last_job, 'export_context', {})
                    return self.ui._running and active_main_encoding(context.get('diagnostics_path')) is not None
                yield (encoding, inputs['job_timeout'])
                context = self.ui._last_job.export_context
                self.result['cancellation'] = dict(job_id=context.get('job_id'),
                    diagnostics_path=context.get('diagnostics_path'),
                    actual_started_process=active_main_encoding(context.get('diagnostics_path')))
                self.check('cancel waits for actual active main encoding process',
                    self.result['cancellation']['actual_started_process'] is not None, self.result['cancellation'])
                yield .25
                cancel = next(b for b in self.ui.exporting_page.findChildren(QPushButton) if '取消' in b.text())
                QTest.mouseClick(cancel, Qt.LeftButton)
                yield (lambda: not self.ui._running, 90)
                self.check('cancelled render is not published', not (output/'exports'/'cancelled.mp4').exists())
                yield from self.direct(10000, 'libx264', True, inputs['short_seconds'], 'retry-after-cancel')
            self.check('manual caption map preserved by export', self.page.project.studio_state.get('manual_caption_text', {}) == self.manual_before)
            self.check('copied authored speech preserved by export',
                [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id) for c in self.page.project.cues] == self.speech_before)
            self.check('provider calls remain zero', blank_project_audit._provider_calls == 0)

        def finish(self):
            self.timer.stop()
            self.result['elapsed_seconds'] = round(time.monotonic()-self.started, 3)
            self.result['provider_calls'] = blank_project_audit._provider_calls
            try:
                self.shot('final-window')
            except Exception:
                pass
            if self.ui is not None and self.ui._running:
                self.ui._cancel_export()
            if self.queue is not None:
                self.queue.stop(cancel_current=True, timeout=.01)
            self.write()
            def close_when_stopped():
                running = self.ui is not None and self.ui._running
                queue_alive = self.queue is not None and self.queue._thread is not None and self.queue._thread.is_alive()
                if running or queue_alive:
                    QTimer.singleShot(100, close_when_stopped)
                    return
                self.page.undo_stack.setClean()
                window.result_exit_code = 0 if self.result['passed'] else 1
                window.close()
            def stopped():
                self.result['gui_shutdown'] = True
                self.write()
            QApplication.instance().aboutToQuit.connect(stopped)
            close_when_stopped()

    window._export_target_audit = Audit()
