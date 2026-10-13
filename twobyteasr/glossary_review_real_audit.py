"""Replay measured real text results through the ordinary Studio preview UI.

No model request is made in this phase. The owned audit replays the previously
measured production response at the correction adapter, then exercises actual
threading, preview binding, selected application, undo, save and SRT export.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .studio_commands import MutationOrigin, SetCueFieldsCommand
    from .studio_find_replace import FindReplaceDialog
    from .studio_project import load_project
    from .studio_subtitle_export import SubtitleExportOptions, export_subtitle_artifacts, verify_subtitle_artifact
    from .studio_edit_sequence import projected_cues
    from .runtime import get_runtime_context
    from . import polishing

    output = Path(output)
    plan = json.loads((output / 'studio-replay-plan.json').read_text('utf8'))
    source = Path(plan['source_receipt']).resolve()
    if not source.is_relative_to(output.parent) or not source.is_file():
        raise ValueError('Measured source receipt must remain inside this task tmp directory')
    if hashlib.sha256(source.read_bytes()).hexdigest() != plan['source_receipt_sha256']:
        raise ValueError('Measured source receipt identity changed')
    if plan.get('kind') != 'measured_production_polish_response_replay':
        raise ValueError('Expected a measured production response replay plan')
    originals = {str(row['cue_id']): row for row in plan['cues']}
    live = os.environ.get('TWOBYTEASR_ACCEPTANCE_SCENARIO') == 'glossary-review-live'
    main_thread = threading.get_ident()
    actual_correction = polishing.call_correction_api

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = {'passed': False, 'checks': [], 'screenshots': [], 'exports': [],
                           'executable': sys.executable, 'identity': load_build_identity().to_dict(),
                           'verification': ('normal Studio button, current saved provider, at most two real text calls; no ASR'
                                            if live else 'actual project and measured real production outputs, replayed; no new model/ASR call'),
                           'source_receipt': str(source), 'source_receipt_sha256': plan['source_receipt_sha256'],
                           'recorded_provider': plan['provider'], 'adapter_replay_calls': []}
            self.waiting = 0
            self.deadline = time.monotonic() + 40
            self.busy = False
            self.gate = threading.Event()
            self.entered = threading.Event()
            self.steps = self.run()
            self.timer = QTimer(self)
            self.timer.setInterval(40)
            self.timer.timeout.connect(self.tick)
            self.timer.start()
            if not live:
                polishing.call_correction_api = self.replay

        def replay(self, rows, *_args, **_kwargs):
            self.entered.set()
            token = get_runtime_context().cancellation_token
            while not self.gate.wait(.03):
                token.raise_if_cancelled()
            token.raise_if_cancelled()
            # The service assigns cue-order IDs to its copied project. Scope is
            # fixed to all cues for this audit; names and timing come from it.
            values, details = {}, {}
            for row in rows:
                cue = self.baseline.cues[row.segment_id - 1]
                expected = originals[cue.id]
                if row.text != expected['input_text']:
                    raise AssertionError(f'Replay input differs for cue {cue.id}: {row.text!r}')
                values[row.segment_id] = expected['final_text']
                details[row.segment_id] = copy.deepcopy(expected.get('detail', {}))
            self.result['adapter_replay_calls'].append({'cue_count': len(rows),
                'background_thread': threading.get_ident() != main_thread,
                'cue_ids': [self.baseline.cues[row.segment_id - 1].id for row in rows]})
            return polishing.PolishBatchResult(values, details=details)

        def check(self, name, passed, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(passed), 'detail': detail})
            if not passed:
                raise AssertionError(f'{name}: {detail}')

        def shot(self, name, surface=None):
            _capture(surface or window, output / (name + '.png'))
            self.result['screenshots'].append(name + '.png')

        def tick(self):
            if self.busy:
                return
            self.busy = True
            try:
                now = time.monotonic()
                if now > self.deadline:
                    raise TimeoutError('Studio replay audit phase timed out')
                if callable(self.waiting):
                    if not self.waiting():
                        return
                elif now < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else now + float(step)
                self.deadline = now + 40
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                try:
                    self.shot('studio-replay-failure')
                except Exception:
                    pass
                self.finish()
            finally:
                self.busy = False

        def dialog_ready(self):
            return isinstance(QApplication.activeModalWidget(), FindReplaceDialog)

        def open_dialog(self):
            QTimer.singleShot(0, lambda: QTest.mouseClick(self.page.studio_find_replace_button, Qt.LeftButton))

        def start_preview(self, dialog):
            self.entered.clear()
            self.gate.clear()
            QTest.mouseClick(dialog.terms_ai_button, Qt.LeftButton)

        def run(self):
            window.open_studio_project(Path(os.environ['TWOBYTEASR_STARTUP_PROJECT']),
                                       mode='edit', source='measured-glossary-review')
            yield lambda: self.page.project is not None and self.page._readiness.ready and not self.page._readiness.active
            yield .3
            project = self.page.project
            self.check('actual project identity', project.project_id == plan['project_id'], project.project_id)
            self.check('mapped actual cue set', {cue.id for cue in project.cues} == set(originals))
            self.baseline = type(project).from_dict(copy.deepcopy(project.to_dict()))
            baseline_rows = [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id, c.original_text) for c in project.cues]
            before_evidence = copy.deepcopy(project.asr_evidence)
            self.shot('studio-real-result-before-preview')

            if not live:
                self.open_dialog()
                yield self.dialog_ready
                dialog = QApplication.activeModalWidget()
                dialog.tabs.setCurrentIndex(3)
                self.start_preview(dialog)
                yield self.entered.is_set
                self.check('preview worker leaves UI timer responsive', dialog._glossary_review_worker.isRunning())
                dialog.reject()
                yield lambda: dialog._glossary_review_worker is None
                self.check('cancelled thread closes dialog', not dialog.isVisible())
                self.check('cancelled preview leaves all text unchanged',
                           [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id, c.original_text) for c in project.cues] == baseline_rows)

                self.open_dialog()
                yield self.dialog_ready
                dialog = QApplication.activeModalWidget()
                dialog.tabs.setCurrentIndex(3)
                self.start_preview(dialog)
                yield self.entered.is_set
                cue = project.cues[0]
                self.page.undo_stack.push(SetCueFieldsCommand(project, cue.id,
                    {'text': '人工确认保留文字'}, 'Manual protection audit',
                    changed=self.page._changed, origin=MutationOrigin.USER_EDIT))
                self.gate.set()
                yield lambda: dialog._glossary_review_worker is None
                self.check('new manual edit rejects old threaded result',
                           cue.text == '人工确认保留文字' and dialog.preview.count() == 0)
                self.check('stale result is explained', '已改变' in dialog.status_label.text(), dialog.status_label.text())
                dialog.reject()
                self.page.undo_stack.undo()
                yield .1
                self.check('manual-protection fixture undone',
                           [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id, c.original_text) for c in project.cues] == baseline_rows)

            self.open_dialog()
            yield self.dialog_ready
            dialog = QApplication.activeModalWidget()
            dialog.tabs.setCurrentIndex(3)
            self.gate.set()
            QTest.mouseClick(dialog.terms_ai_button, Qt.LeftButton)
            if live:
                yield .1
                self.check('actual UI starts background review', dialog._glossary_review_worker is not None)
                self.shot('studio-live-model-request-in-progress', dialog)
            yield lambda: dialog._glossary_review_worker is None
            measured_hits = {hit.cue_id: hit.replacement for hit in dialog._preview_hits}
            expected_changes = (measured_hits if live else {
                cue.id: originals[cue.id]['final_text'] for cue in project.cues
                if originals[cue.id]['final_text'] != cue.text
                and originals[cue.id]['final_text'] != (cue.original_text or cue.text)})
            self.check('measured outputs displayed as actual diffs',
                       {hit.cue_id: hit.replacement for hit in dialog._preview_hits} == expected_changes,
                       {'expected': expected_changes, 'actual': {hit.cue_id: hit.replacement for hit in dialog._preview_hits}})
            self.check('preview is nonmutating',
                       [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id, c.original_text) for c in project.cues] == baseline_rows)
            if live:
                self.check('real provider has no fallback cues', dialog._glossary_review_receipt is not None
                           and dialog._glossary_review_receipt['fallback_cues'] == 0)
                self.result['live_review_receipt'] = copy.deepcopy(dialog._glossary_review_receipt)
                for cue_id, row in originals.items():
                    if row['final_text'] != row['input_text']:
                        self.check('previous measured sample still corrected ' + cue_id,
                                   measured_hits.get(cue_id, next(c.text for c in project.cues if c.id == cue_id)) == row['final_text'])
            self.shot('studio-measured-ai-threaded-diffs', dialog)
            self.check('measured sample produces changes', bool(expected_changes))
            before_undo_count = self.page.undo_stack.index()
            QTest.mouseClick(dialog.all_button, Qt.LeftButton)
            yield .2
            self.check('single apply is one undo step', self.page.undo_stack.index() == before_undo_count + 1)
            expected_final = {cue.id: expected_changes.get(cue.id, cue.text) for cue in self.baseline.cues}
            self.check('chosen measured outputs applied exactly', {cue.id: cue.text for cue in project.cues} == expected_final)
            self.check('speaker timing and original transcription preserved',
                       [(c.id, c.start_ms, c.end_ms, c.speaker_id, c.original_text) for c in project.cues]
                       == [(r[0], r[2], r[3], r[4], r[5]) for r in baseline_rows])
            self.check('original ASR evidence never overwritten', project.asr_evidence == before_evidence)
            receipt = project.generation_metadata['glossary_review_jobs'][-1]
            self.check('applied receipt records project and selected cue IDs',
                       receipt['project_id'] == project.project_id and set(receipt['applied_cue_ids']) == set(expected_changes))
            self.page.undo_stack.undo()
            self.check('one undo restores all raw project text',
                       [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id, c.original_text) for c in project.cues] == baseline_rows)
            self.page.undo_stack.redo()
            dialog.reject()
            QTest.mouseClick(self.page.save_button, Qt.LeftButton)
            yield .2
            reopened = load_project(self.page.project_path)
            self.check('saved and reopened text agrees with applied UI', {cue.id: cue.text for cue in reopened.cues} == expected_final)
            self.check('review lineage persists after reopen', reopened.generation_metadata['glossary_review_jobs'][-1] == receipt)
            window.open_studio_project(self.page.project_path, mode='edit', source='measured-glossary-replay-reopen')
            yield lambda: self.page._readiness.ready and not self.page._readiness.active
            yield .3
            self.check('fresh Studio project agrees with saved file', {cue.id: cue.text for cue in self.page.project.cues} == expected_final)
            self.shot('studio-real-result-saved-reopened')
            exported = export_subtitle_artifacts(reopened, output / 'exports',
                '上海冠军赛实际校对结果', SubtitleExportOptions(frozenset({'srt'}), 'both'))
            projected = projected_cues(reopened, domain='timeline')
            for artifact in exported:
                ordered = sorted([c for c in projected if not artifact.speaker_id or c.speaker_id == artifact.speaker_id],
                                 key=lambda c: (c.start_ms, c.end_ms, c.id))
                expected_export = copy.copy(reopened)
                expected_export.cues = ordered
                verification = verify_subtitle_artifact(artifact, expected_export)
                self.check('parser-backed exported artifact ' + artifact.path.name, verification.valid)
                blocks = [block for block in artifact.path.read_text('utf8').strip().split('\n\n') if block]
                texts = ['\n'.join(block.splitlines()[2:]) for block in blocks]
                self.check('SRT text equals same saved speaker projection ' + artifact.path.name,
                           texts == [c.text for c in ordered])
                self.result['exports'].append({'path': str(artifact.path), 'speaker_id': artifact.speaker_id,
                                               'cue_count': artifact.cue_count})
            if live:
                requests = list((output / 'requests').glob('*-request-body.json'))
                metadata = [json.loads(path.read_text('utf8')) for path in (output / 'requests').glob('*-response-metadata.json')]
                self.result['actual_http_request_count'] = len(requests)
                self.result['actual_http_responses'] = metadata
                self.check('bounded actual two HTTP calls', len(requests) == 2)
                self.check('both actual calls return 200', len(metadata) == 2 and all(row['http_status'] == 200 for row in metadata))
                replay_plan = copy.deepcopy(plan)
                replay_plan['source_receipt'] = str(output / 'studio-replay-result.json')
                replay_plan['source_receipt_sha256'] = None  # Filled after the receipt and shutdown are final.
                replay_plan['provider'] = copy.deepcopy(receipt['provider'])
                replay_plan['cues'] = [{'cue_id': row['cue_id'], 'input_text': row['input_text'],
                                       'final_text': row['final_text'], 'detail': row['detail']}
                                      for row in receipt['segments']]
                self.result['frozen_replay_plan'] = replay_plan
            else:
                from . import blank_project_audit
                self.result['provider_calls_attempted'] = blank_project_audit._provider_calls
                self.check('no fresh model call during measured replay', self.result['provider_calls_attempted'] == 0)
                self.check('all replays execute on background threads',
                           all(row['background_thread'] for row in self.result['adapter_replay_calls']))
            self.result['final_cues'] = [{'cue_id': c.id, 'text': c.text, 'speaker_id': c.speaker_id,
                                          'start_ms': c.start_ms, 'end_ms': c.end_ms} for c in reopened.cues]

        def finish(self):
            self.timer.stop()
            self.gate.set()
            polishing.call_correction_api = actual_correction
            target = output / 'studio-replay-result.json'
            def write():
                target.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf8')
            write()
            def stopped():
                self.result['gui_shutdown'] = True
                write()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.result_exit_code = 0 if self.result['passed'] else 1
            window.close()

    window._acceptance_audit = Audit()
