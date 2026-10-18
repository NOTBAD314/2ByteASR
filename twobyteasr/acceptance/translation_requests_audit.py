"""Real dialog audit, isolated data and synthetic HTTP answers (no paid call)."""
from __future__ import annotations
import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def install_guards() -> None:
    """Disable incidental probes while keeping the audited provider path real."""
    from ..ui import EndpointEditor
    from ..studio_ai_flow import StudioAIFlowMixin
    from ..test_isolation import install_pytest_network_guard
    EndpointEditor._queue_model_discovery = lambda *a, **kw: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *a, **kw: None
    install_pytest_network_guard()


def start(window, output: Path) -> None:
    """Run inside the normal source/frozen application and exit naturally."""
    import os
    import sys
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..build_identity import load_build_identity

    def execute():
        code = run(output)
        path = output / 'result.json'
        result = json.loads(path.read_text('utf8'))
        result.update(entry='frozen' if getattr(sys, 'frozen', False) else 'quick_start.main',
                      executable=sys.executable, pid=os.getpid(),
                      identity=load_build_identity().to_dict())
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        window.close()
        QApplication.instance().exit(code)

    QTimer.singleShot(300, execute)


def run(output: Path) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QUndoStack
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..test_isolation import install_pytest_network_guard
    from ..studio_ai import GLOBAL_PROVIDER_REGISTRY
    from ..theme_manager import apply_application_theme
    from ..studio_theme import build_secondary_surface_qss
    from .. import llm_config
    from ..studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
    from ..studio_translation_dialog import SubtitleTranslationDialog
    install_pytest_network_guard()
    app = QApplication.instance() or QApplication([])
    theme = apply_application_theme(app, 'grape')
    base = 'https://generativelanguage.googleapis.com/v1beta/openai'
    llm_config.save_api_key_for('gemini', base, 'fixture-key')
    settings = {'models': {'polish_provider': 'gemini', 'polish_base_url': base,
                          'polish_model': 'gemini-3.8-flash'}}
    checks, calls = [], []
    mode = ['failure']

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)

    class Response:
        headers = {}
        def __init__(self, body):
            self.status_code = 400 if mode[0] == 'failure' else 200
            self.text = 'invalid parameter, API_KEY=fixture-secret' if self.status_code == 400 else ''
            self.body = body
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.text)
        def json(self):
            request = json.loads(self.body['messages'][-1]['content'])
            items = [{'id': row['id'], 'translation': '我们得把门打开。'} for row in request['lines'] if row['translate']]
            return {'choices': [{'message': {'content': json.dumps({'items': items})}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 500, 'completion_tokens': 100, 'total_tokens': 600}}

    def post(url, **kwargs):
        calls.append(kwargs['json'])
        time.sleep(.15)
        return Response(kwargs['json'])

    p = SubtitleProject(media=StudioMedia(path='synthetic.mp4', duration_ms=120000),
                        cues=[StudioCue(f'c{i}', i*1000, i*1000+900, 'We need to open the door.') for i in range(91)])
    p.generation_metadata['language'] = {'code':'en'}
    p.validate()
    source = copy.deepcopy(p.cues)
    page = SimpleNamespace(project=p, selected_cue_ids=lambda: ['c0'], undo_stack=QUndoStack())

    def wait_done(dialog):
        deadline = time.monotonic() + 40
        while dialog._thread is not None and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(20)
        app.processEvents()
        check('worker finished', dialog._thread is None)

    def capture(dialog, name):
        app.processEvents()
        QTest.qWait(120)
        check(name + ' screenshot', dialog.grab().save(str(output / (name + '.png'))))
        check(name + ' buttons inside', dialog.rect().contains(dialog.cancel_button.geometry()))
        check(name + ' screen fits', dialog.height() <= dialog.screen().availableGeometry().height())

    try:
        with patch.object(GLOBAL_PROVIDER_REGISTRY, 'settings', return_value=settings), \
             patch('twobyteasr.network_policy.post', post):
            dialog = SubtitleTranslationDialog(page)
            dialog.setStyleSheet(build_secondary_surface_qss(theme))
            dialog.show()
            app.processEvents()
            check('start enabled', dialog.start_button.isEnabled())
            capture(dialog, 'ready')
            QTest.mouseClick(dialog.start_button, Qt.LeftButton)
            wait_done(dialog)
            check('91 failed', len(dialog._result.failed) == 91)
            check('reason visible', 'HTTP 400' in dialog.status.text())
            check('secret hidden', 'fixture-secret' not in dialog.request_log.toPlainText())
            capture(dialog, 'failed')
            # Invoke the same clipboard action directly: keep the host clipboard
            # untouched by replacing only Qt's clipboard object in this audit.
            copied = []
            with patch.object(QApplication, 'clipboard', return_value=SimpleNamespace(setText=copied.append)):
                QTest.mouseClick(dialog.copy_log_button, Qt.LeftButton)
            log = ''.join(copied)
            check('copy contains request and failure', '"messages"' in log and 'HTTP 400' in log)
            check('copied secrets redacted', 'fixture-secret' not in log and 'fixture-key' not in log)
            (output / 'copied-failure-log.jsonl').write_text(log, encoding='utf8')
            mode[0] = 'success'
            QTest.mouseClick(dialog.start_button, Qt.LeftButton)
            wait_done(dialog)
            check('retry 91 succeeded', len(dialog._result.translations) == 91 and not dialog._result.failed)
            check('source unchanged', p.cues == source)
            check('wire reasoning low', all(body.get('reasoning_effort') == 'low' for body in calls))
            check('live batch usage', '600' in dialog.request_log.toPlainText())
            capture(dialog, 'success')
            saved = output / 'translated.2byteproj'
            save_project(p, saved)
            check('reopen translation', len(load_project(saved).generation_metadata['translations']) == 91)
            # The last undo is the display-mode change, followed by translations.
            page.undo_stack.undo()
            page.undo_stack.undo()
            check('undo restores failed records', not p.generation_metadata.get('translations'))
            page.undo_stack.redo()
            check('redo restores 91', len(p.generation_metadata['translations']) == 91)
            dialog.close()
            app.processEvents()
    except Exception as exc:
        checks.append({'name': str(exc), 'passed': False})
        if 'dialog' in locals():
            dialog.grab().save(str(output / 'unexpected.png'))
    finally:
        report = {'checks':checks, 'passed':sum(row['passed'] for row in checks),
                  'failed':sum(not row['passed'] for row in checks), 'http_standin_calls':len(calls),
                  'real_api_calls':0, 'transport':'synthetic stand-in; real dialog/provider service'}
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(report, ensure_ascii=False))
    return int(bool(report['failed']))
