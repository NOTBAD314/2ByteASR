"""Opt-in real Home → worker → exact result → Studio → ordinary exports.

The glossary already exists from normal controls in a prior process. This audit
never injects a snapshot, result, term or response and never calls ASR directly.
"""
from __future__ import annotations
import copy
from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QTimer, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QScrollArea
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .provider_diagnostics import redact_diagnostics
    from .provider_service import ProviderService
    from .recognition_result import verify_result_reference, cue_identity, input_graph_identity
    from .recognition_outcome import normalize_recognition_outcome
    from .studio_project import load_project
    from .studio_subtitle_export import verify_subtitle_artifact
    from .terminology import GlossarySnapshot
    from .asr_provider_snapshot import POLISH_PROMPT_VERSION
    from .glossary_live_resources import install as install_resources

    output = Path(output)
    inputs = json.loads((output/'live-home-input.json').read_text('utf8'))
    evidence = output/'live-home-evidence'
    receipt = output/'live-home-result.json'
    previous = json.loads(Path(inputs['normal_ui_restore_receipt']).read_text('utf8'))
    saved_snapshot = GlossarySnapshot.from_dict(previous['snapshot'])
    expected_pairs = [('球球', 'CHIOCHOO'), ('奥特曼', 'autumn')]
    sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    borrowed = install_resources(output)

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.started = time.monotonic()
            self.deadline = self.started+850
            self.result = dict(passed=False, checks=[], screenshots=[], requests=[], inputs=inputs,
                pid=os.getpid(), executable=sys.executable, identity=load_build_identity().to_dict(),
                scope=inputs['scope'], inference_run=True, local_cache_condition='Fresh recognition artifacts in a reused normally-saved glossary profile; model process newly launched; GPU thermal/cache state not certified')
            self.result['borrowed_resources'] = borrowed.receipt()
            self.result['expected_production_polish_prompt_version'] = POLISH_PROMPT_VERSION
            self.queue_result = None
            self.worker_error = None
            self.request_handles = []
            self.request_lock = threading.Lock()
            self.original_submit = ProviderService.submit
            audit = self
            def observed_submit(service, settings, stage, messages, **kwargs):
                from .llm_config import endpoint_from_settings
                endpoint = endpoint_from_settings(dict(settings), stage)
                with audit.request_lock:
                    number = len(audit.result['requests'])+1
                    if number > 2:
                        audit.result['cloud_budget_rejected'] = dict(
                            requested_number=number, maximum_model_requests=2,
                            reason='Normal Home share of the explicitly authorized ten-request audit budget exhausted')
                        audit.write()
                        raise RuntimeError('Finite normal Home cloud budget exhausted; no extra model request sent')
                    row = dict(number=number, stage=stage, adapter_stage=kwargs.get('_adapter_stage'),
                        submitted_monotonic=time.monotonic(), endpoint={key: endpoint.get(key) for key in ('provider', 'model', 'transport', 'protocol')},
                        message_characters=sum(len(str(message.get('content', ''))) for message in messages),
                        origin='Actual production ProviderService.submit messages, before adapter serialization')
                    payloads = []
                    for message in messages:
                        if message.get('role') != 'user' or not isinstance(message.get('content'), str):
                            continue
                        try:
                            payload = json.loads(message['content'])
                        except (ValueError, TypeError):
                            continue
                        if isinstance(payload, dict):
                            payloads.append({key: payload.get(key) for key in ('content_scene', 'resolved_context', 'prompt_version') if key in payload})
                    row['actual_user_payload_contexts'] = payloads
                    audit.result['requests'].append(row)
                    (evidence/f'actual-request-{number:02d}.json').write_text(json.dumps(redact_diagnostics(dict(
                        **row, messages=messages, schema=kwargs.get('schema'))), ensure_ascii=False, indent=2), 'utf8')
                # Observe the selected transport faithfully; do not replace it,
                # alter its payload, shorten timeouts or replay a response.
                handle = audit.original_submit(service, settings, stage, messages, **kwargs)
                with audit.request_lock:
                    row.update(request_id=handle.request_id, provider_id=handle.provider_id)
                    audit.request_handles.append((row, handle))
                return handle
            ProviderService.submit = observed_submit
            self.steps = self.run()
            self.waiting = 0.
            self.busy = False
            self.modal_failure = None
            self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(100)
            self.modal_timer = QTimer(self); self.modal_timer.timeout.connect(self.watch_modals); self.modal_timer.start(120)
            self.write()

        def write(self):
            receipt.write_text(json.dumps(redact_diagnostics(self.result), ensure_ascii=False, indent=2,
                default=lambda value: asdict(value) if is_dataclass(value) else str(value)), 'utf8')

        def check(self, name, passed, detail=None, *, required=True):
            self.result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))
            self.write()
            if required and not passed:
                raise AssertionError(name+': '+str(detail))

        def shot(self, name):
            path = evidence/(name+'.png')
            _capture(window, path)
            self.result['screenshots'].append(str(path))
            self.write()

        def watch_modals(self):
            notification = getattr(window, '_completion_dialog', None)
            if notification and notification.isVisible():
                QTest.mouseClick(notification.confirm_button, Qt.MouseButton.LeftButton)
            modal = QApplication.activeModalWidget()
            if not isinstance(modal, QMessageBox):
                return
            if modal.standardButtons() & QMessageBox.StandardButton.Save:
                path = Path(str(getattr(window.studio_page, 'project_path', '') or '')).resolve()
                if path.is_relative_to(evidence) and modal.button(QMessageBox.StandardButton.Save):
                    QTest.mouseClick(modal.button(QMessageBox.StandardButton.Save), Qt.MouseButton.LeftButton)
                    return
            self.modal_failure = modal.text()+' '+modal.informativeText()
            self.result.setdefault('unexpected_modals', []).append(self.modal_failure)
            try:
                self.shot('unexpected-modal')
            finally:
                modal.reject()

        def tick(self):
            if self.busy:
                return
            self.busy = True
            try:
                if time.monotonic() > self.deadline:
                    raise TimeoutError('Actual Home recognition/export audit exceeded its 850s bound')
                if self.modal_failure:
                    raise RuntimeError('Normal flow requested user action: '+self.modal_failure)
                if self.worker_error:
                    raise RuntimeError('Actual worker failed: '+self.worker_error)
                if callable(self.waiting):
                    if not self.waiting():
                        return
                elif time.monotonic() < self.waiting:
                    return
                wait = next(self.steps)
                self.waiting = wait if callable(wait) else time.monotonic()+float(wait)
            except StopIteration:
                self.result['passed'] = all(row['passed'] for row in self.result['checks'])
                self.finish()
            except BaseException:
                self.result['error'] = traceback.format_exc()
                try:
                    self.shot('failure')
                except Exception:
                    self.result['capture_error'] = traceback.format_exc()
                self.finish()
            finally:
                self.busy = False

        def reveal(self, control):
            parent = control.parentWidget()
            while parent is not None:
                if isinstance(parent, QScrollArea):
                    parent.ensureWidgetVisible(control)
                parent = parent.parentWidget()
            QApplication.processEvents()

        def click(self, control):
            self.reveal(control)
            self.check('normal control visible and enabled: '+control.text(), control.isVisible() and control.isEnabled())
            QTest.mouseClick(control, Qt.MouseButton.LeftButton)

        def enter(self, field, value):
            self.reveal(field)
            self.check('normal editable field visible and enabled', field.isVisible() and field.isEnabled(), field.objectName())
            edit = field.lineEdit() if hasattr(field, 'lineEdit') else field
            edit.setFocus(); QTest.keyClick(edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            event = QInputMethodEvent(); event.setCommitString(str(value)); QApplication.sendEvent(edit, event)
            QTest.keyClick(edit, Qt.Key.Key_Return); QTest.keyClick(edit, Qt.Key.Key_Tab)

        def choose(self, control, value):
            self.reveal(control)
            self.check('normal export selector visible and enabled', control.isVisible() and control.isEnabled(), control.objectName())
            index = control.findData(value)
            self.check('ordinary export option available: '+value, index >= 0)
            control.showPopup()
            view = control.view()
            item = control.model().index(index, control.modelColumn())
            view.scrollTo(item)
            QApplication.processEvents()
            target = view.visualRect(item)
            self.check('ordinary export popup item is reachable: '+value, target.isValid())
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=target.center())
            self.check('popup selected actual export value: '+value, control.currentData() == value)

        def ready(self):
            page = window.studio_page
            return page.project is not None and page._readiness.ready and not page._readiness.active

        def run(self):
            window._return_to_settings()
            window.resize(1440, 900)
            yield .4
            self.check('ordinary Home is active', window.pages.currentIndex() == 0)
            self.check('normal UI-saved glossary bytes retained before recognition', sha(inputs['store']) == previous['store_sha256'])
            self.check('task reports remain within owned profile', Path(window.legacy.task_reporting.REPORT_ROOT).resolve().is_relative_to(output))
            self.check('Home domain terms enabled normally', window.terms.isChecked())
            self.check('optional online terminology verification remains disabled', not window.term_search.isChecked())
            self.check('existing model selection is three local models', window._asr_values().get('primary_asr_backend') == 'moss'
                and window._asr_values().get('firered_asr_backend') == 'local'
                and window._asr_values().get('qwen_asr_backend') == 'local', window._asr_values())
            self.result['home_enabled_glossaries'] = list(window._enabled_glossary_ids())
            self.shot('01-normal-home-saved-profile')
            picker = QFileDialog.getOpenFileNames
            QFileDialog.getOpenFileNames = lambda *args, **kwargs: ([inputs['media']], '')
            try:
                self.click(window.choose_media_button)
            finally:
                QFileDialog.getOpenFileNames = picker
            yield lambda: len(window.media_paths) == 1 and Path(window.media_paths[0]).resolve() == Path(inputs['media']).resolve()
            self.check('normal file-add consumed the immutable copied media', sha(window.media_paths[0]) == inputs['protected_before'][inputs['media']])
            yield lambda: window.start_button.isEnabled()
            self.shot('02-normal-home-media-added')
            self.click(window.start_button)
            self.check('Start created the actual production worker', window.worker is not None and window.worker.isRunning(), getattr(window, '_run_block_reason', ''))
            window.worker.result_ready.connect(lambda result: setattr(self, 'queue_result', result))
            window.worker.unexpected_error.connect(lambda error: setattr(self, 'worker_error', str(error)))
            options = window._last_run_options
            actual_snapshot = GlossarySnapshot.from_dict(json.loads(options.glossary_snapshot_json))
            self.check('normal Start froze the already committed UI snapshot', actual_snapshot.digest == saved_snapshot.digest,
                dict(saved=saved_snapshot.summary(), task=actual_snapshot.summary()))
            aliases = {(alias, term.canonical) for library in actual_snapshot.libraries for term in library.terms if term.confirmed for alias in term.aliases}
            self.check('actual task snapshot contains exact human-confirmed target spellings', set(expected_pairs) <= aliases)
            self.result['actual_task_options'] = asdict(options)
            self.result['actual_snapshot_summary'] = actual_snapshot.summary()
            self.result['actual_job_id'] = options.job_id
            self.shot('03-real-worker-running')
            yield lambda: self.queue_result is not None and not window._run_in_progress
            self.result['queue_result'] = asdict(self.queue_result)
            self.check('actual worker emitted one task-owned terminal result', len(self.queue_result.results) == 1 and self.queue_result.job_id == options.job_id)
            item = self.queue_result.results[0]
            report = json.loads(Path(item.report_json_path).read_text('utf-8-sig'))
            self.actual_report = report
            shutil.copy2(item.report_json_path, evidence/'actual-terminal-report.json')
            self.result['stages'] = report.get('stages')
            self.result['elapsed_seconds_actual_file'] = report.get('result', {}).get('elapsed_seconds')
            self.result['elapsed_seconds_actual_audio'] = report.get('result', {}).get('audio_seconds')
            self.result['cache'] = report.get('cache')
            self.result['actual_profile_sent'] = report.get('settings', {}).get('content_profile')
            self.result['polishing_summary'] = report.get('polishing_summary')
            self.result['terminology_summary'] = report.get('terminology_summary')
            outcome = normalize_recognition_outcome(report)
            self.result['actual_outcome'] = asdict(outcome)
            self.check('fresh recognition has no task cache hit', report.get('cache', {}).get('hits') == [], required=False)
            models = report.get('result', {}).get('model_statuses', {})
            for name in ('moss', 'firered', 'qwen3-asr'):
                self.check('actual local model completed: '+name, bool(models.get(name, {}).get('completed')) and not models.get(name, {}).get('failed'), models.get(name), required=False)
            self.check('cloud correction succeeded without fallback', outcome.polish_status == 'completed' and outcome.fallback_records == 0, asdict(outcome), required=False)
            groups = [stage for stage in report.get('stages', []) if '断句' in stage.get('label', '')]
            group_receipts = [event for event in report.get('events', []) if event.get('event') == 'cloud_batch_completed'
                and event.get('stage') == 'grouped']
            self.check('actual AI grouping completed without local fallback', bool(groups)
                and groups[-1].get('status') == 'completed' and bool(group_receipts)
                and all(row.get('result_origin') == 'ai'
                    and row.get('validator_result') == 'exact_text_and_boundaries' for row in group_receipts),
                dict(stages=groups, receipts=group_receipts), required=False)
            self.check('online terminology stage truly not requested', report.get('terminology_summary', {}).get('requested') is False,
                report.get('terminology_summary'), required=False)
            contexts = [payload for row in self.result['requests'] for payload in row['actual_user_payload_contexts']
                if row.get('stage') == 'polish' and 'content_scene' in payload]
            self.result['actual_polish_wire_contexts'] = contexts
            self.result['actual_wire_prompt_versions'] = [payload.get('prompt_version') for row in self.result['requests']
                for payload in row['actual_user_payload_contexts'] if 'prompt_version' in payload]
            expected_revisions = {library.id: str(library.revision) for library in actual_snapshot.libraries}
            self.check('real cloud correction request sent enabled-library scene and exact revisions', bool(contexts) and all(
                payload.get('prompt_version') == POLISH_PROMPT_VERSION
                and payload.get('content_scene', {}).get('domain') == '瓦罗兰特'
                and payload.get('content_scene', {}).get('source') == 'enabled_glossary_metadata'
                and {key: str(value) for key, value in payload.get('content_scene', {}).get('glossary_versions', {}).items()} == expected_revisions
                for payload in contexts), dict(expected=expected_revisions, actual=contexts), required=False)
            self.check('actual committed project is isolated', Path(item.project_path).resolve().is_relative_to(output))
            project = verify_result_reference(item.result_ref_json, project_path=item.project_path)
            self.original_committed_sha = sha(item.project_path)
            self.result['actual_reference'] = json.loads(item.result_ref_json)
            self.result['actual_project_before_studio'] = dict(path=item.project_path, sha256=self.original_committed_sha,
                project_id=project.project_id, cues=cue_identity(project), input_graph=input_graph_identity(project))
            self.shot('04-real-completion-default-summary')
            self.click(window.open_studio_result_button)
            yield self.ready
            page = window.studio_page
            verify_result_reference(item.result_ref_json, project=page.project, project_path=page.project_path)
            self.check('normal completion card delivered the exact committed object to Studio', page.project.project_id == project.project_id
                and cue_identity(page.project) == cue_identity(project) and input_graph_identity(page.project) == input_graph_identity(project))
            self.verify_names(page.project, report)
            self.shot('05-real-studio-canonical-result')
            copy_path = evidence/'ordinary-export-copy.2byteproj'
            shutil.copy2(item.project_path, copy_path)
            window.open_studio_project(copy_path, mode='edit', source='ordinary_live_export_copy')
            yield self.ready
            self.check('export copy retains actual final body and timing', cue_identity(page.project) == cue_identity(project))
            self.click(page.studio_render_button)
            yield lambda: page.export_workspace is not None
            yield .4
            ui = page.export_workspace
            yield from self.subtitle_exports(ui, project)
            if inputs.get('burn_requested'):
                yield from self.burn_export(ui, page.project)
            else:
                self.result['burn_not_run'] = 'Explicit driver --skip-burn; no encoded-video validation claimed'
            self.check('immutable actual committed reference bytes preserved', sha(item.project_path) == self.original_committed_sha)
            self.result['glossary_sha256_after'] = sha(inputs['store'])
            self.result['glossary_bytes_unchanged'] = self.result['glossary_sha256_after'] == previous['store_sha256']
            shutil.copy2(inputs['store'], evidence/'glossary-after-normal-task.json')
            self.check('normal recognition preserved UI-confirmed target records', all(
                any(row.get('from') == alias and row.get('to') == canonical for library in json.loads(Path(inputs['store']).read_text('utf-8-sig')).get('games', {}).values()
                    for row in library.get('mappings', [])) for alias, canonical in expected_pairs))

        def verify_names(self, project, report):
            compact = lambda value: re.sub(r'\s+', '', str(value))
            rows = [dict(row, id=key) for key, row in project.asr_evidence.items() if any(target in row.get('text', '') for _, target in expected_pairs)]
            self.result['canonical_asr_evidence'] = rows
            for alias, canonical in expected_pairs:
                self.check('real final subtitles contain user spelling: '+canonical, any(canonical in cue.text for cue in project.cues), required=False)
                evidence_rows = [row for row in rows if canonical in row.get('text', '')]
                self.check('real canonical words match body: '+canonical, bool(evidence_rows) and all(
                    compact(row['text']) == compact(''.join(word.get('text', '') for word in row.get('words', []))) for row in evidence_rows), evidence_rows, required=False)
                proofs = [span for event in report.get('events', []) if event.get('event') == 'terminology_applied'
                    for change in event.get('changes', []) for span in change.get('span_mappings', [])
                    if span.get('source') == alias and span.get('canonical') == canonical]
                self.result.setdefault('canonical_span_proofs', {})[canonical] = proofs
                if proofs:
                    self.check('normalization keeps original pronunciation span: '+canonical, all(
                        span.get('acoustic_verified_spelling') is False and span.get('source_words')
                        and abs(float(span['audio_start'])-min(float(word['start']) for word in span['source_words'])) < 1e-6
                        and abs(float(span['audio_end'])-max(float(word['end']) for word in span['source_words'])) < 1e-6 for span in proofs), proofs, required=False)
                else:
                    self.result.setdefault('canonical_span_not_applied', {})[canonical] = dict(
                        native_canonical_body_present=bool(evidence_rows),
                        reason='No actual literal alias→canonical replacement was reported for this live result. A source-span mapping is not fabricated; retained-input replay separately verifies manual normalization spans.')

        def subtitle_exports(self, ui, project):
            for control in ui.subtitle_format_checks.values():
                if not control.isChecked():
                    self.click(control)
            if not ui.subtitle_speaker_modes['combined'].isChecked():
                self.click(ui.subtitle_speaker_modes['combined'])
            folder = evidence/'subtitles'; folder.mkdir(exist_ok=True)
            picker = QFileDialog.getExistingDirectory
            QFileDialog.getExistingDirectory = lambda *args, **kwargs: str(folder)
            try:
                self.click(ui.subtitle_custom_choose)
            finally:
                QFileDialog.getExistingDirectory = picker
            self.click(ui.subtitle_export_button)
            yield .2
            artifacts = getattr(ui, '_last_subtitle_artifacts', ())
            self.check('ordinary subtitle export wrote all four actual formats', {artifact.format for artifact in artifacts} == {'srt', 'ass', 'txt', 'json'},
                [asdict(artifact) for artifact in artifacts])
            self.result['subtitle_exports'] = []
            for artifact in artifacts:
                validation = verify_subtitle_artifact(artifact, project)
                self.check('ordinary exported '+artifact.format+' parses back to actual final subtitles', validation.valid, asdict(validation))
                self.result['subtitle_exports'].append(dict(path=str(artifact.path), format=artifact.format, sha256=sha(artifact.path), validation=asdict(validation)))
                if artifact.format in {'srt', 'txt'}:
                    text = artifact.path.read_text('utf-8-sig')
                    self.check(artifact.format+' includes both exact user canonical spellings', all(target in text for _, target in expected_pairs), required=False)
            self.shot('06-normal-four-format-subtitle-export')

        def burn_export(self, ui, project):
            self.enter(ui.filename, 'ordinary-live-15-28')
            self.enter(ui.filename_prefix, ''); self.enter(ui.filename_suffix, '')
            self.enter(ui.directory, str(evidence/'video'))
            if not ui.advanced_panel.isVisible():
                self.click(ui.advanced_button)
            for control, value in ((ui.preset, 'custom'), (ui.quality, 'custom'), (ui.extension, 'mp4'), (ui.codec, 'h264'),
                    (ui.rate_control, 'crf'), (ui.encoder_preset, 'balanced'), (ui.audio, 'aac'), (ui.encoder, 'libx264')):
                self.choose(control, value)
            self.enter(ui.quality_value, '20')
            for field, value in zip(ui.project_range_bar.fields, ('00:00:15.000', '00:00:28.000')):
                self.enter(field, value)
            self.choose(ui.export_range, 'in_out')
            self.check('ordinary video range fields show 15–28s', ui._range_seconds() == (15., 13., 13.), ui._range_seconds())
            self.click(ui.export_button)
            yield lambda: ui._last_job is not None
            job = ui._last_job
            self.check('real video worker freezes actual AV graph and13s range', job.start_seconds == 15. and job.duration_seconds == 13.
                and bool(job.video_graph) and bool(job.export_project_data))
            yield lambda: not ui._running
            self.check('ordinary production video export completes', ui.pages.currentWidget() == ui.success_page,
                dict(failure=ui._last_failure, receipt=job.completion_metadata))
            path = Path(job.output_path)
            self.check('real production encoded output remains isolated', path.is_file() and path.resolve().is_relative_to(evidence))
            self.result['burn_export'] = dict(path=str(path), sha256=sha(path), ass_path=job.ass_path,
                context=job.export_context, receipt=copy.deepcopy(job.completion_metadata), start_seconds=15., duration_seconds=13.)
            self.shot('07-production-burn-completed')
            from .platform_media import ffmpeg_tool
            from .processes import run_hidden_subprocess
            ffmpeg = ffmpeg_tool(); ffprobe = ffmpeg.with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
            probe = run_hidden_subprocess([str(ffprobe), '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,codec_name,width,height',
                '-of', 'json', str(path)], purpose='normal Home actual burned video probe', capture_output=True, text=True, encoding='utf8', timeout=20, check=True)
            self.result['burn_export']['probe'] = json.loads(probe.stdout)
            self.check('decoded production container is13s with video and audio', abs(float(self.result['burn_export']['probe']['format']['duration'])-13.) < .1
                and {row['codec_type'] for row in self.result['burn_export']['probe']['streams']} >= {'video', 'audio'})
            for _, canonical in expected_pairs:
                cue = next((cue for cue in project.cues if canonical in cue.text and 15000 <= (cue.start_ms+cue.end_ms)/2 < 28000), None)
                self.check('burn range actually covers '+canonical, cue is not None, required=False)
                if cue is None:
                    continue
                seconds = (cue.start_ms+cue.end_ms)/2000-15
                frame = evidence/('burned-'+canonical+'.png')
                run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-ss', str(seconds), '-i', str(path), '-frames:v', '1', '-y', str(frame)],
                    purpose='normal Home actual canonical burned frame', capture_output=True, text=True, encoding='utf8', timeout=20, check=True)
                self.result['burn_export'].setdefault('frames', []).append(dict(canonical=canonical, source_seconds=seconds+15,
                    encoded_seconds=seconds, path=str(frame), sha256=sha(frame), visual_review_pending=True))

        def finish(self):
            self.timer.stop()
            ProviderService.submit = self.original_submit
            with self.request_lock:
                for row, handle in self.request_handles:
                    row.update(completed=handle._event.is_set(), cancelled=handle.cancelled,
                        error=str(handle._error) if handle._error else '', trace=copy.deepcopy(handle.trace))
            self.result['provider_submit_attempts'] = len(self.result['requests'])
            self.result['provider_requests_queued'] = len(self.request_handles)
            self.result['wall_seconds'] = time.monotonic()-self.started
            self.result['glossary_sha256_at_shutdown'] = sha(inputs['store'])
            self.result['borrowed_resources_protection'] = borrowed.protection()
            unchanged = all(row['unchanged'] for row in self.result['borrowed_resources_protection'])
            self.result['checks'].append(dict(name='read-only borrowed source SHA guards remain unchanged', passed=unchanged))
            self.result['passed'] = bool(self.result['passed'] and unchanged)
            window.result_exit_code = 0 if self.result['passed'] else 1
            self.write()
            def stopped():
                self.modal_timer.stop()
                borrowed.restore()
                self.result['gui_shutdown'] = True
                self.write()
            QApplication.instance().aboutToQuit.connect(stopped)
            # Cancellation remains the real production mechanism if an audit
            # deadline is reached while a worker is still active.
            if getattr(window, '_run_in_progress', False):
                window._cancel_run()
            window.close()

    window._glossary_live_home_audit = Audit()
