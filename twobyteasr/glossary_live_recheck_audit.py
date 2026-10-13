"""Opt-in actual Studio glossary AI review; no ASR or response replay.

Only audit-owned copies are opened/saved. Model calls remain the ordinary
configured production calls, observed at both submission and CLI dispatch.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

_guard = None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wire_contexts(messages):
    contexts = []
    for message in messages:
        if message.get('role') != 'user' or not isinstance(message.get('content'), str):
            continue
        try:
            value = json.loads(message['content'])
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            contexts.append({key: value[key] for key in ('content_scene', 'prompt_version') if key in value})
    return contexts


class RequestBudget:
    """Reserve before delegation, including failed calls and JSON repairs."""
    def __init__(self, maximum=2):
        if type(maximum) is not int or not 1 <= maximum <= 2:
            raise ValueError('Explicit Studio review budget must be one or two model requests')
        self.maximum = maximum
        self.armed = False
        self.lock = threading.RLock()
        self.rows = {'submit': [], 'cli': []}
        self.rejections = []

    def reserve(self, kind, metadata):
        if kind not in self.rows:
            raise ValueError('Unknown model dispatch boundary')
        with self.lock:
            reason = ('Only the actual visible Studio AI preview button may request a model'
                      if not self.armed else 'Finite Studio AI review request budget exhausted')
            if not self.armed or len(self.rows[kind]) >= self.maximum:
                self.rejections.append(dict(kind=kind, armed=self.armed, reason=reason,
                    requested_number=len(self.rows[kind])+1, maximum=self.maximum))
                raise RuntimeError(reason+'; no additional model request dispatched')
            row = dict(number=len(self.rows[kind])+1, **metadata)
            self.rows[kind].append(row)
            return row

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(dict(maximum_requests=self.maximum, armed=self.armed,
                provider_submissions=self.rows['submit'], actual_cli_model_calls=self.rows['cli'],
                rejections=self.rejections))


def review_coverage(receipt, cue_ids):
    """Execution coverage and unresolved quality are independent facts."""
    segments = receipt.get('segments', [])
    actual = [row.get('cue_id') for row in segments]
    expected = list(cue_ids)
    quality = {}
    counts = {key: 0 for key in ('recall_gaps', 'unreviewed_suspects', 'new_suspects',
                                 'rejected_edits', 'invalid_suspect_receipts')}
    pending_cues = []
    for row in segments:
        detail = row.get('detail') or {}
        state = str(detail.get('quality_state') or 'not_recorded')
        quality[state] = quality.get(state, 0)+1
        for key in ('recall_gaps', 'unreviewed_suspects', 'new_suspects', 'rejected_edits'):
            counts[key] += len(detail.get(key) or [])
        counts['invalid_suspect_receipts'] += sum(
            item.get('validation_state') == 'invalid' for item in detail.get('suspect_results', []))
        if (state.startswith('pending') or state == 'term_review_needed'
                or any(detail.get(key) for key in ('recall_gaps', 'unreviewed_suspects', 'new_suspects', 'rejected_edits'))
                or any(item.get('disposition') in ('review', 'missing_candidate')
                       or item.get('validation_state') == 'invalid'
                       for item in detail.get('suspect_results', []))):
            pending_cues.append(row.get('cue_id'))
    unassigned = receipt.get('unassigned_new_suspects') or []
    optional = receipt.get('pending_optional_metadata') or {}
    pending_quality = bool(pending_cues or unassigned or optional.get('status') == 'pending_review')
    return dict(expected_cue_count=len(expected), receipt_cue_count=len(actual),
        exact_cue_coverage=len(actual) == len(set(actual)) and set(actual) == set(expected),
        successful_cues=receipt.get('successful_cues'), fallback_cues=receipt.get('fallback_cues'),
        all_cues_received_without_fallback=receipt.get('successful_cues') == len(expected)
            and receipt.get('fallback_cues') == 0,
        proposed_cues=receipt.get('proposed_cues'), quality_states=quality,
        pending_cue_ids=pending_cues, pending_cue_count=len(pending_cues), **counts,
        unassigned_new_suspect_rows=len(unassigned),
        invalid_unassigned_new_suspect_rows=sum(row.get('validation_state') == 'invalid' for row in unassigned),
        pending_optional_metadata=optional, pending_quality=pending_quality,
        audio_verified=receipt.get('audio_verified'),
        execution_success_is_not_acoustic_or_quality_verification=True)


class LiveGuard:
    def __init__(self, output):
        from .glossary_live_resources import BorrowedResources, validate_manifest, MANIFEST_ENV
        from .asr_provider_snapshot import resolve_provider_snapshot, snapshot_in_settings, POLISH_PROMPT_VERSION
        from .provider_service import ProviderService
        from .ai_providers import CLIProvider
        from .provider_diagnostics import redact_diagnostics
        from .cache import add_run_event_observer
        self.output = Path(output).resolve()
        self.inputs = json.loads((self.output/'recheck-input.json').read_text('utf8'))
        self.evidence = self.output/'recheck-evidence'
        self.evidence.mkdir(exist_ok=True)
        self.resources = BorrowedResources(validate_manifest(os.environ[MANIFEST_ENV], self.output), self.output)
        settings = json.loads(Path(self.inputs['settings']).read_text('utf-8-sig'))
        self.provider = resolve_provider_snapshot(settings, stage='polish').public_identity()
        if self.provider['transport'] != 'grok_cli' or self.provider['model'] != self.inputs['expected_model']:
            raise ValueError('Normal UI-saved current Grok CLI/model does not match the requested live review')
        self.prompt_version = POLISH_PROMPT_VERSION
        self.budget = RequestBudget(self.inputs.get('maximum_requests', 2))
        self.handles = []
        self.events = []
        self.original_submit, self.original_complete = ProviderService.submit, CLIProvider.complete
        self.restored = False
        guard = self

        def submit(service, selected, stage, messages, **options):
            # Production passes the frozen typed identity through
            # execution_settings(), not a persisted provider profile. Honor
            # that same marker as endpoint/transport resolution before
            # considering a legacy settings migration.
            selected_snapshot = snapshot_in_settings(selected) or resolve_provider_snapshot(selected, stage='polish')
            identity = selected_snapshot.public_identity()
            if (stage != 'polish' or options.get('_adapter_stage') != 'polished'
                    or options.get('operation_kind') != 'polish'
                    or any(identity[key] != guard.provider[key] for key in (
                        'provider', 'model', 'transport', 'endpoint_identity',
                        'profile_id', 'profile_revision', 'fingerprint'))):
                raise RuntimeError('Only the unchanged configured Studio text-polish role is permitted')
            row = guard.budget.reserve('submit', dict(stage=stage, adapter_stage=options.get('_adapter_stage'),
                submitted_monotonic=time.monotonic(), provider=identity,
                message_characters=sum(len(str(m.get('content', ''))) for m in messages)))
            with guard.budget.lock:
                row['wire_contexts'] = wire_contexts(messages)
            guard.save(f"actual-submit-{row['number']:02d}.json", dict(**row, messages=messages, schema=options.get('schema')))
            try:
                handle = guard.original_submit(service, selected, stage, messages, **options)
            except BaseException as exc:
                with guard.budget.lock:
                    row['submit_error'] = str(exc)
                raise
            with guard.budget.lock:
                row.update(request_id=handle.request_id, provider_id=handle.provider_id)
                guard.handles.append((row, handle))
            return handle

        def complete(adapter, messages, **options):
            if adapter.provider_id != guard.provider['provider'] or adapter.model != guard.provider['model']:
                raise RuntimeError('Different provider/model CLI is outside this review')
            row = guard.budget.reserve('cli', dict(started_monotonic=time.monotonic(),
                provider_id=adapter.provider_id, model=adapter.model, stage=options.get('stage')))
            guard.save(f"actual-cli-request-{row['number']:02d}.json", dict(**row, messages=messages))
            try:
                response = guard.original_complete(adapter, messages, **options)
                guard.save(f"actual-cli-response-{row['number']:02d}.json", dict(response=response))
                with guard.budget.lock:
                    row['returned_characters'] = len(response)
                return response
            except BaseException as exc:
                with guard.budget.lock:
                    row['error'] = str(exc)
                raise
            finally:
                with guard.budget.lock:
                    row.update(finished_monotonic=time.monotonic(),
                        trace=copy.deepcopy(getattr(adapter, 'last_invocation_trace', {})))
                guard.save(f"actual-cli-trace-{row['number']:02d}.json", row)

        ProviderService.submit, CLIProvider.complete = submit, complete

        def event(name, payload):
            row = dict(event=name, **payload)
            with guard.budget.lock:
                guard.events.append(row)
                with (guard.evidence/'actual-events.jsonl').open('a', encoding='utf8') as stream:
                    stream.write(json.dumps(redact_diagnostics(row), ensure_ascii=False, default=str)+'\n')
        self.event_observer = add_run_event_observer(event)

    def save(self, name, value):
        from .provider_diagnostics import redact_diagnostics
        (self.evidence/name).write_text(json.dumps(redact_diagnostics(value), ensure_ascii=False,
            indent=2, default=str), 'utf8')

    def snapshot(self):
        with self.budget.lock:
            for row, handle in self.handles:
                row.update(completed=handle._event.is_set(), error=str(handle._error) if handle._error else '',
                    trace=copy.deepcopy(handle.trace))
            return self.budget.snapshot()

    def restore(self):
        if self.restored:
            return
        from .provider_service import ProviderService
        from .ai_providers import CLIProvider
        from .cache import remove_run_event_observer
        ProviderService.submit, CLIProvider.complete = self.original_submit, self.original_complete
        remove_run_event_observer(self.event_observer)
        self.resources.restore()
        self.restored = True


def install(output):
    """Called by the dedicated acceptance switch before MainWindow construction."""
    global _guard
    output = Path(output).resolve()
    if (os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') != 'glossary-live-recheck'
            or Path(os.environ.get('TWOBYTEASR_TEST_ROOT', '')).resolve() != output):
        raise ValueError('Live Studio guard requires its explicitly isolated acceptance profile')
    if _guard is None:
        _guard = LiveGuard(output)
    elif _guard.output != output:
        raise ValueError('Live Studio guard belongs to another profile')
    return _guard


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QToolButton
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_find_replace import FindReplaceDialog
    from .studio_project import load_project
    from .studio_text_tools import SCOPE_ALL
    from .studio_subtitle_export import verify_subtitle_artifact
    from .terminology import snapshot_glossaries
    from .recognition_result import input_graph_identity

    guard = install(output)
    inputs, output = guard.inputs, guard.output
    receipt_path = output/'result.json'
    project_path = Path(inputs['project_copy']).resolve()

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = dict(passed=False, checks=[], screenshots=[],
                scope='Actual current-cue Studio AI text preview of copied cold Home project; retained original ASR evidence; no ASR/replay/search',
                inputs=inputs, executable=sys.executable, pid=os.getpid(), identity=load_build_identity().to_dict(),
                expected_prompt_version=guard.prompt_version, expected_provider=guard.provider)
            self.started = time.monotonic()
            self.deadline = self.started+300
            self.waiting = 0
            self.busy = self.finished = False
            self.deferred_error = None
            self.steps = self.run()
            self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(50)
            self.modal_timer = QTimer(self); self.modal_timer.timeout.connect(self.watch_modals); self.modal_timer.start(60)
            self.expected_export_notice = False
            self.write()

        def write(self):
            self.result['requests'] = guard.snapshot()
            receipt_path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2, default=str), 'utf8')

        def check(self, name, value, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
            self.write()
            if not value:
                raise AssertionError(name+': '+str(detail))

        def shot(self, name, surface=None):
            path = guard.evidence/(name+'.png')
            _capture(surface or window, path)
            self.result['screenshots'].append(str(path)); self.write()

        def click(self, control):
            self.check('visible enabled control: '+(control.text() or control.toolTip()), control.isVisible() and control.isEnabled())
            QTest.mouseClick(control, Qt.LeftButton)

        def defer(self, callback):
            def invoke():
                try:
                    if not self.finished:
                        callback()
                except BaseException:
                    self.deferred_error = traceback.format_exc()
                    modal = QApplication.activeModalWidget()
                    if modal is not None:
                        modal.reject()
                    popup = QApplication.activePopupWidget()
                    if popup is not None:
                        popup.close()
            QTimer.singleShot(0, invoke)

        def watch_modals(self):
            modal = QApplication.activeModalWidget()
            if not isinstance(modal, QMessageBox):
                return
            if self.finished and Path(str(self.page.project_path)).resolve() == project_path:
                button = modal.button(QMessageBox.Discard)
                if button:
                    self.result['owned_close_choice'] = 'Normal Discard for owned copy after audit'; self.write()
                    QTest.mouseClick(button, Qt.LeftButton); return
            if self.expected_export_notice and modal.button(QMessageBox.Ok):
                self.result.setdefault('export_notices', []).append(modal.text()+' '+modal.informativeText())
                QTest.mouseClick(modal.button(QMessageBox.Ok), Qt.LeftButton); return
            self.deferred_error = 'Unexpected normal UI message: '+modal.text()+' '+modal.informativeText()
            modal.reject()

        def tick(self):
            if self.busy or self.finished:
                return
            self.busy = True
            try:
                if self.deferred_error:
                    raise RuntimeError(self.deferred_error)
                if time.monotonic() > self.deadline:
                    raise TimeoutError('Bounded actual Studio AI review exceeded 300 seconds')
                if callable(self.waiting):
                    if not self.waiting(): return
                elif time.monotonic() < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else time.monotonic()+float(step)
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except BaseException:
                self.result['error'] = traceback.format_exc()
                try: self.shot('failure')
                except Exception: self.result['capture_error'] = traceback.format_exc()
                self.finish()
            finally:
                self.busy = False

        def ready(self):
            return self.page.project is not None and self.page._readiness.ready and not self.page._readiness.active

        def cue_rows(self, project):
            return [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id, c.original_text, list(c.evidence_refs)) for c in project.cues]

        def run(self):
            yield self.ready
            yield .3
            page = self.page
            self.check('ordinary startup opens only the exact owned project copy', Path(page.project_path).resolve() == project_path)
            baseline = load_project(project_path)
            self.check('ordinary Studio loaded the exact cold Home body', self.cue_rows(page.project) == self.cue_rows(baseline))
            self.baseline = baseline
            self.baseline_rows = self.cue_rows(baseline)
            self.baseline_evidence = copy.deepcopy(baseline.asr_evidence)
            self.baseline_reference = copy.deepcopy(baseline.generation_metadata.get('recognition_result'))
            self.baseline_graph = input_graph_identity(baseline)
            self.check('current cue and original ASR evidence counts are distinguished', len(baseline.cues) == inputs['expected_cues']
                and len(baseline.asr_evidence) == inputs['expected_asr_evidence'], dict(cues=len(baseline.cues), original_asr_evidence=len(baseline.asr_evidence)))
            self.result['review_scope'] = dict(current_cues=len(baseline.cues), original_asr_evidence=len(baseline.asr_evidence),
                cue_ids=[c.id for c in baseline.cues], evidence_ids=list(baseline.asr_evidence),
                referenced_evidence_ids=sorted({ref for c in baseline.cues for ref in c.evidence_refs}),
                project_id=baseline.project_id, source_project_sha256=inputs['project_source_sha256'])
            self.check('current cues retain references to all original ASR records',
                set(self.result['review_scope']['referenced_evidence_ids']) == set(baseline.asr_evidence))
            snapshot = snapshot_glossaries(window.legacy, window._enabled_glossary_ids())
            self.snapshot = snapshot
            self.check('normal enabled glossary has the exact saved revision', any(lib.id == inputs['glossary_id']
                and str(lib.revision) == str(inputs['expected_revision']) for lib in snapshot.libraries), snapshot.summary())
            self.result['current_glossary_snapshot'] = snapshot.to_dict()
            from .asr_provider_snapshot import resolve_provider_snapshot
            actual_provider = resolve_provider_snapshot(window.legacy.RUNTIME_SETTINGS, stage='polish').public_identity()
            self.result['actual_normal_ui_provider'] = actual_provider
            self.check('normal boot loaded the exact saved Grok CLI/model before any AI request',
                all(actual_provider[key] == guard.provider[key] for key in ('provider', 'model', 'transport', 'endpoint_identity')),
                dict(saved=guard.provider, actual=actual_provider))
            self.shot('01-normal-studio-actual-project-copy')
            button = page.studio_find_replace_button
            if button.isVisible():
                self.defer(lambda: self.click(button))
            else:
                overflow = next(c for c in page.studio_toolbar.findChildren(QToolButton)
                    if c.property('commandSource') == '更多工作区操作')
                self.defer(lambda: self.click(overflow))
                yield lambda: overflow.menu().isVisible()
                menu = overflow.menu()
                action = next(a for a in menu.actions() if a.text() == button.text())
                rect = menu.actionGeometry(action)
                self.check('normal visible More menu reaches text tools', action.isEnabled() and action.isVisible() and not rect.isEmpty())
                self.shot('02-visible-more-text-tools', menu)
                self.defer(lambda: QTest.mouseClick(menu, Qt.LeftButton, pos=rect.center()))
            yield lambda: isinstance(QApplication.activeModalWidget(), FindReplaceDialog)
            dialog = QApplication.activeModalWidget()
            QTest.mouseClick(dialog.tabs.tabBar(), Qt.LeftButton, pos=dialog.tabs.tabBar().tabRect(3).center())
            self.check('normal glossary tab uses all current cues', dialog.terms_scope.currentData() == SCOPE_ALL)
            for i in range(dialog.terms_libraries.count()):
                item = dialog.terms_libraries.item(i)
                desired = Qt.Checked if str(item.data(Qt.UserRole)) in window._enabled_glossary_ids() else Qt.Unchecked
                if item.checkState() != desired:
                    dialog.terms_libraries.scrollToItem(item)
                    QTest.mouseClick(dialog.terms_libraries.viewport(), Qt.LeftButton,
                        pos=dialog.terms_libraries.visualItemRect(item).center())
                    QTest.keyClick(dialog.terms_libraries, Qt.Key_Space)
                self.check('normal glossary checkbox: '+str(item.data(Qt.UserRole)), item.checkState() == desired)
            self.shot('03-normal-current-glossary-ai-controls', dialog)
            guard.budget.armed = True
            self.click(dialog.terms_ai_button)
            yield .1
            self.check('ordinary AI button started the actual review thread', dialog._glossary_review_worker is not None)
            self.shot('04-real-review-in-progress', dialog)
            yield lambda: dialog._glossary_review_worker is None
            # Let the queued completion label and preview paint before the
            # result screenshot; worker termination alone is not paint truth.
            yield .2
            receipt = copy.deepcopy(dialog._glossary_review_receipt)
            self.result['actual_status_label'] = dialog.status_label.text()
            self.result['actual_review_receipt'] = receipt
            self.shot('05-actual-review-preview-result', dialog)
            self.check('actual preview returns a review receipt', isinstance(receipt, dict), dialog.status_label.text())
            coverage = review_coverage(receipt, [c.id for c in baseline.cues])
            self.result['receipt_coverage'] = coverage
            self.result['quality_state'] = 'text_review_succeeded_with_pending' if coverage['pending_quality'] else 'text_review_succeeded_audio_unverified'
            self.result['quality_all_pass_claimed'] = False
            self.check('receipt covers each current cue exactly once', coverage['exact_cue_coverage'], coverage)
            self.check('real AI received every cue without fallback', coverage['all_cues_received_without_fallback'], coverage)
            self.check('review performs no ASR, search or acoustic verification', receipt.get('asr_run') is False
                and receipt.get('web_search_run') is False and receipt.get('audio_verified') is False)
            self.check('preview leaves original project text and evidence unchanged', self.cue_rows(page.project) == self.baseline_rows
                and page.project.asr_evidence == self.baseline_evidence)
            self.check('receipt uses the actual current glossary snapshot', receipt.get('snapshot_summary', {}).get('snapshot_digest') == snapshot.digest)
            version = (receipt.get('provider', {}).get('prompt_versions') or {}).get('polished')
            self.check('receipt records loaded production prompt version', version == guard.prompt_version, dict(expected=guard.prompt_version, actual=version))
            contexts = [body for row in guard.budget.rows['submit'] for body in row['wire_contexts'] if 'content_scene' in body]
            revisions = {lib.id: str(lib.revision) for lib in snapshot.libraries}
            self.result['actual_wire_contexts'] = contexts
            self.check('actual outgoing scene/version uses enabled-library metadata and saved revisions', bool(contexts) and all(
                body.get('prompt_version') == guard.prompt_version and body.get('content_scene', {}).get('domain') == inputs['glossary_id']
                and body.get('content_scene', {}).get('source') == 'enabled_glossary_metadata'
                and {k: str(v) for k, v in body.get('content_scene', {}).get('glossary_versions', {}).items()} == revisions for body in contexts), contexts)
            budget = guard.snapshot()
            self.check('finite request allowance includes actual CLI dispatch and repair', 1 <= len(budget['actual_cli_model_calls']) <= budget['maximum_requests']
                and 1 <= len(budget['provider_submissions']) <= budget['maximum_requests']
                and not any(row['armed'] for row in budget['rejections']), budget)
            hits = list(dialog._preview_hits)
            self.result['actual_proposals'] = [asdict(hit) for hit in hits]
            expected_text = {c.id: c.text for c in baseline.cues}
            checked_hits = dialog._checked_hits()
            self.check('ordinary checked preview contains only actual generated proposals', {h.cue_id for h in checked_hits} == {h.cue_id for h in hits})
            if hits:
                for hit in checked_hits: expected_text[hit.cue_id] = hit.replacement
                self.click(dialog.all_button)
                yield .15
                self.check('ordinary Apply persists review lineage in memory', page.project.generation_metadata.get('glossary_review_jobs', [])[-1]['job_id'] == receipt['job_id'])
            else:
                self.result['zero_suggestions'] = dict(valid_success=True, applied=False,
                    receipt_saved_in_audit=True, production_receipt_persistence='No Apply: ordinary zero-hit review receipt exists only on dialog; no generation_metadata injected')
            dialog.reject()
            yield .15
            self.check('only actual selected proposals changed subtitle text', {c.id: c.text for c in page.project.cues} == expected_text)
            self.check('original times, speakers, original text and evidence references preserved',
                [row[:1]+row[2:] for row in self.cue_rows(page.project)] == [row[:1]+row[2:] for row in self.baseline_rows])
            self.check('all original ASR evidence and media graph preserved', page.project.asr_evidence == self.baseline_evidence
                and input_graph_identity(page.project) == self.baseline_graph)
            if page.save_button.isEnabled():
                self.click(page.save_button)
                self.result['normal_save_action'] = 'Visible enabled Save button'
            else:
                page.cue_table.setFocus(); QTest.keyClick(page.cue_table, Qt.Key_S, Qt.ControlModifier)
                self.result['normal_save_action'] = 'Normal Ctrl+S; unchanged zero-hit copy may require no write'
            yield .2
            saved = load_project(project_path)
            self.check('saved owned copy agrees with normal UI body and original evidence', {c.id: c.text for c in saved.cues} == expected_text
                and saved.asr_evidence == self.baseline_evidence)
            self.check('ordinary Save does not restamp the earlier recognition reference',
                saved.generation_metadata.get('recognition_result') == self.baseline_reference)
            self.result['saved_project'] = dict(path=str(project_path), sha256=sha(project_path), project_id=saved.project_id,
                cue_count=len(saved.cues), asr_evidence_count=len(saved.asr_evidence), applied_cues=len(hits))
            self.shot('06-normal-studio-result-saved-copy')
            self.click(page.studio_render_button)
            yield lambda: page.export_workspace is not None
            yield .3
            ui = page.export_workspace
            for control in ui.subtitle_format_checks.values():
                if not control.isChecked(): self.click(control)
            if not ui.subtitle_speaker_modes['combined'].isChecked(): self.click(ui.subtitle_speaker_modes['combined'])
            folder = guard.evidence/'exports'; folder.mkdir()
            original = QFileDialog.getExistingDirectory
            QFileDialog.getExistingDirectory = lambda *args, **kwargs: str(folder)
            try: self.click(ui.subtitle_custom_choose)
            finally: QFileDialog.getExistingDirectory = original
            self.expected_export_notice = True
            self.defer(lambda: self.click(ui.subtitle_export_button))
            yield lambda: len(getattr(ui, '_last_subtitle_artifacts', ())) == 4
            artifacts = ui._last_subtitle_artifacts
            self.check('normal export controls produced four actual formats', {a.format for a in artifacts} == {'srt', 'ass', 'txt', 'json'})
            self.result['exports'] = []
            for artifact in artifacts:
                checked = verify_subtitle_artifact(artifact, saved)
                self.check('parser validates exported '+artifact.format+' against saved actual body', checked.valid, asdict(checked))
                self.result['exports'].append(dict(path=str(artifact.path), sha256=sha(artifact.path), format=artifact.format, validation=asdict(checked)))
            self.shot('07-normal-four-format-exports')
            self.check('UI-saved glossary bytes remain unchanged', sha(inputs['store']) == inputs['store_sha256'])
            self.check('immutable original cold Home project remains unchanged', sha(inputs['project_source']) == inputs['project_source_sha256'])
            self.check('no request rejected after the actual AI button armed the scope', not any(row['armed'] for row in guard.budget.rejections))

        def finish(self):
            if self.finished: return
            self.finished = True; self.timer.stop()
            self.result['wall_seconds'] = time.monotonic()-self.started
            self.result['borrowed_protection'] = guard.resources.protection()
            unchanged = all(row['unchanged'] for row in self.result['borrowed_protection'])
            self.result['passed'] = bool(self.result['passed'] and unchanged)
            window.result_exit_code = 0 if self.result['passed'] else 1
            self.write()
            def stopped():
                self.modal_timer.stop()
                self.result['gui_shutdown'] = True
                self.write()
                guard.restore()
            QApplication.instance().aboutToQuit.connect(stopped)
            modal = QApplication.activeModalWidget()
            if isinstance(modal, FindReplaceDialog): modal.reject()
            def close_when_worker_stopped():
                if isinstance(modal, FindReplaceDialog) and modal._glossary_review_worker is not None:
                    QTimer.singleShot(100, close_when_worker_stopped); return
                window.close()
            QTimer.singleShot(100, close_when_worker_stopped)

    window._glossary_live_recheck_audit = Audit()
