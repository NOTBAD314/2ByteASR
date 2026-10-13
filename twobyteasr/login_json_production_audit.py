"""Opt-in normal Studio button acceptance with live production JSON requests.

The caller supplies an isolated project and canonical-only glossary fixture.
No request, ASR evidence, answer or transport is mocked/replayed.
"""
import json
import os
import time
import traceback
from dataclasses import asdict


def start(window, output):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .blank_project_audit import _capture
    from .studio_find_replace import FindReplaceDialog
    from .build_identity import load_build_identity
    from .provider_diagnostics import redact_diagnostics
    from .ai_providers import CLIProvider, OpenAICompatibleProvider
    from .provider_service import ProviderService
    from . import polishing, llm_config

    inputs = json.loads((output/'input.json').read_text('utf8'))
    # Application state stays isolated. Official CLIs use the existing account;
    # this does not change their auth/config files or their global settings.
    os.environ['USERPROFILE'] = inputs['account_home']
    original_read = llm_config._read_secrets
    llm_config._read_secrets = lambda **kwargs: original_read(read_only_path=inputs['secret_path'])
    original_event = polishing.record_run_event
    event_lock = __import__('threading').Lock()
    def capture_event(event, **payload):
        with event_lock:
            with (output/'events.jsonl').open('a', encoding='utf8') as stream:
                stream.write(json.dumps(redact_diagnostics({'event': event, **payload}), ensure_ascii=False)+'\n')
        return original_event(event, **payload)
    polishing.record_run_event = capture_event
    original_complete = CLIProvider._complete_cli_command
    response_number = [0]
    def capture_complete(adapter, *args, **kwargs):
        value = original_complete(adapter, *args, **kwargs)
        with event_lock:
            response_number[0] += 1
            (output/f'final-answer-{response_number[0]}.json').write_text(value, 'utf8')
        return value
    CLIProvider._complete_cli_command = capture_complete
    original_http_complete = OpenAICompatibleProvider.complete
    def capture_http_complete(adapter, *args, **kwargs):
        value = original_http_complete(adapter, *args, **kwargs)
        with event_lock:
            response_number[0] += 1
            (output/f'final-answer-{response_number[0]}.json').write_text(value, 'utf8')
        return value
    OpenAICompatibleProvider.complete = capture_http_complete
    original_submit = ProviderService.submit
    request_number = [0]
    def capture_submit(service, settings, stage, messages, **kwargs):
        with event_lock:
            request_number[0] += 1
            body = dict(stage=stage, messages=messages, options=kwargs)
            # Keep exactly the real request inputs, excluding objects/callbacks
            # and all credential configuration.
            body['options'] = {k: v for k, v in kwargs.items() if isinstance(v, (dict,list,str,int,float,bool,type(None)))}
            (output/f'request-{request_number[0]}.json').write_text(
                json.dumps(redact_diagnostics(body), ensure_ascii=False, indent=2), 'utf8')
        return original_submit(service, settings, stage, messages, **kwargs)
    ProviderService.submit = capture_submit

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = dict(passed=False, live_provider_requests=True, asr_run=False,
                scope=inputs['scope'], service=inputs['service'], screenshots=[], checks=[],
                identity=load_build_identity().to_dict(), elapsed_seconds=None)
            self.steps = self.run()
            self.waiting = 0
            self.deadline = time.monotonic()+40
            self.busy = False
            self.started = time.monotonic()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(50)

        def check(self, name, value, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(value), 'detail': detail})
            if not value:
                raise AssertionError(name+': '+str(detail))

        def shot(self, name, surface=None):
            _capture(surface or window, output/(name+'.png'))
            self.result['screenshots'].append(name+'.png')

        def tick(self):
            if self.busy:
                return
            self.busy = True
            try:
                now = time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now > self.deadline:
                            raise TimeoutError('normal Studio live request exceeded audit budget')
                        return
                elif now < self.waiting:
                    return
                step = next(self.steps)
                self.waiting = step if callable(step) else now+float(step)
                self.deadline = now+(185 if callable(step) else 40)
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                try:
                    self.shot('failed')
                except Exception:
                    pass
                self.finish()
            finally:
                self.busy = False

        def run(self):
            yield lambda: self.page.project is not None and self.page._readiness.ready and not self.page._readiness.active
            yield .4
            page = self.page
            before = [(c.id, c.text, c.start_ms, c.end_ms, c.speaker_id) for c in page.project.cues]
            expected_count = int(inputs.get('expected_cue_count',35))
            self.check('real original cue count', len(before) == expected_count, len(before))
            # Read the fixture through the actual glossary registry and loader.
            import subtitle_core as core
            from .terminology import snapshot_glossaries
            snapshot = snapshot_glossaries(core, page.project.glossary_ids)
            self.check('canonical names retain digit and case', {'BerLIN', 'S0pp', 'Zhe'}.issubset(snapshot.canonical_terms))
            self.check('no wrong-answer aliases', not any(t.aliases for lib in snapshot.libraries for t in lib.terms))
            self.result['snapshot'] = snapshot.to_dict()
            if inputs['scope'] == 'settings':
                yield from self.settings_roundtrip()
                return
            selected = inputs.get('selected_ids', [])
            if selected:
                from .selection_scope import SelectionScope
                page.cue_controller.apply_selection_scope(SelectionScope.explicit(selected, selected[0]))
                self.check('normal selection scope', page.selected_cue_ids() == selected, page.selected_cue_ids())
            QTimer.singleShot(0, lambda: QTest.mouseClick(page.studio_find_replace_button, Qt.LeftButton))
            yield lambda: isinstance(QApplication.activeModalWidget(), FindReplaceDialog)
            dialog = QApplication.activeModalWidget()
            dialog.tabs.setCurrentIndex(3)
            if selected:
                from .studio_text_tools import SCOPE_SELECTED
                dialog.terms_scope.setCurrentIndex(dialog.terms_scope.findData(SCOPE_SELECTED))
            yield .2
            if selected:
                # The initial media-clock sync can finish after the toolbox
                # opens. Select again at the actual submit boundary.
                page.cue_controller.apply_selection_scope(SelectionScope.explicit(selected, selected[0]))
                from .studio_text_tools import scope_cue_ids
                self.check('exact selected scope at submit',
                    scope_cue_ids(page, SCOPE_SELECTED) == selected,
                    scope_cue_ids(page, SCOPE_SELECTED))
            self.shot('before-request', dialog)
            start = time.monotonic()
            QTest.mouseClick(dialog.terms_ai_button, Qt.LeftButton)
            self.check('normal review worker launched', dialog._glossary_review_worker is not None)
            yield lambda: dialog._glossary_review_worker is None
            yield .15
            receipt = dialog._glossary_review_receipt
            self.check('production preview receipt returned', receipt is not None, dialog.status_label.text())
            self.result['request_elapsed_seconds'] = time.monotonic()-start
            self.result['preview_receipt'] = receipt
            self.result['preview_hits'] = [asdict(hit) for hit in dialog._preview_hits]
            (output/'preview.json').write_text(json.dumps({'receipt': receipt, 'hits': self.result['preview_hits']}, ensure_ascii=False, indent=2), 'utf8')
            self.result['status'] = dialog.status_label.text()
            self.shot('complete-preview', dialog)
            count = len(selected) if selected else expected_count
            self.check('all requested cues processed', receipt['successful_cues']+receipt['fallback_cues']==count)
            self.check('all requested cues succeeded without fallback', receipt['successful_cues']==count and receipt['fallback_cues']==0,
                       [receipt['successful_cues'], receipt['fallback_cues']])
            self.check('preview retains original project', before == [(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id) for c in page.project.cues])
            dialog.reject()
            yield .2
            self.shot('studio-after-cancel')
            self.check('cancel leaves original unchanged', before == [(c.id,c.text,c.start_ms,c.end_ms,c.speaker_id) for c in page.project.cues])

        def settings_roundtrip(self):
            from .settings import load_runtime_settings
            from .ui import EndpointEditor
            from .i18n import save_language
            window._open_ai_provider_config()
            yield .4
            self.check('normal AI settings surfaced', window.group_editor.isVisible())
            for wanted in (False, True):
                window.group_editor.json_mode.setChecked(wanted)
                window.group_editor.structured_output.setChecked(wanted)
                window.polish_editor.json_mode.setChecked(wanted)
                window.polish_editor.structured_output.setChecked(wanted)
                QTest.mouseClick(window.save_ai_button, Qt.LeftButton)
                yield .2
                saved, path, warnings = load_runtime_settings()
                self.check('saved JSON flags on disk '+str(wanted), all(
                    saved['models'][stage+'_'+field] is wanted
                    for stage in ('group','polish') for field in ('json_mode','structured_output')),
                    {'path': str(path), 'warnings': warnings})
                reopened = EndpointEditor('保存后重新打开', '#ac4169', 'group', saved)
                reopened.resize(1050,750)
                reopened.show()
                yield .25
                self.check('reopened JSON flags '+str(wanted),
                    reopened.json_mode.isChecked() is wanted and reopened.structured_output.isChecked() is wanted)
                self.shot('reopened-'+str(wanted).lower(), reopened)
                for language in ('en','ja','zh'):
                    save_language(language)
                    yield .1
                    self.check('capability state translated '+language,
                        language=='zh' or '结构化能力' not in reopened.json_capability_status.text(),
                        reopened.json_capability_status.text())
                reopened.close()
            self.check('settings verification sends zero requests', request_number[0] == 0, request_number[0])
            self.result['live_provider_requests'] = False

        def finish(self):
            self.timer.stop()
            self.result['elapsed_seconds'] = time.monotonic()-self.started
            window.result_exit_code = 0 if self.result['passed'] else 1
            def write():
                (output/'result.json').write_text(json.dumps(redact_diagnostics(self.result), ensure_ascii=False, indent=2), 'utf8')
            write()
            modal = QApplication.activeModalWidget()
            if modal is not None:
                modal.reject()
            def stopped():
                self.result['gui_shutdown'] = True
                write()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.close()
    window._login_json_production_audit = Audit()
