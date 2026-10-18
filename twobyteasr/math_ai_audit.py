"""Real-window check: AI features keep math formulas; a term library's note to AI (2026-10-16, ADR 0124 stage 1B).

Runs in the real application on a private desktop with isolated data, only loopback connections, no paid call
(``scripts/verify_math_ai_headed.py``). In the 术语库 page it writes a library's 「给 AI 的说明」 from the
math example and reopens it; then, with an OpenAI-compatible stand-in on 127.0.0.1 saved as the AI service,
it runs 查找替换 「按当前词库生成 AI 校对预览」 and 「AI 清理」 and 字幕翻译 on a project whose math switch is on,
and checks every request the stand-in received: formulas only as ⟦Fn⟧, the formula rule and the user's note
present, and the project's LaTeX unchanged.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path


_blocked: list[str] = []


def install_guards() -> None:
    """Loopback only; no background model discovery or provider probe. Self-contained so the check
    also runs in builds without the ai-actions-no-key audit."""
    import ipaddress
    import socket

    def silence(module_name, class_name, method):
        try:
            module = __import__(module_name, fromlist=[class_name])
            setattr(getattr(module, class_name), method, lambda *a, **kw: None)
        except (ImportError, AttributeError):
            pass

    package = __name__.rpartition('.')[0].rpartition('.')[0] or 'twobyteasr'
    for module_name, class_name, method in (
            (f'{package}.app.ui', 'EndpointEditor', '_queue_model_discovery'),
            (f'{package}.ui', 'EndpointEditor', '_queue_model_discovery'),
            (f'{package}.studio.studio_ai_flow', 'StudioAIFlowMixin', '_start_ai_provider_probe'),
            (f'{package}.studio_ai_flow', 'StudioAIFlowMixin', '_start_ai_provider_probe')):
        silence(module_name, class_name, method)

    def local(address):
        if not isinstance(address, tuple):
            return
        host = address[0].decode('ascii', 'replace') if isinstance(address[0], bytes) else str(address[0])
        try:
            ok = ipaddress.ip_address(host).is_loopback
        except ValueError:
            ok = host.lower() == 'localhost'
        if not ok:
            _blocked.append(str(address))
            raise RuntimeError('External network prohibited in the math-ai audit')

    original_connect, original_create = socket.socket.connect, socket.create_connection

    def connect(sock, address, *args, **kwargs):
        local(address)
        return original_connect(sock, address, *args, **kwargs)

    def create_connection(address, *args, **kwargs):
        local(address)
        return original_create(address, *args, **kwargs)

    socket.socket.connect = connect
    socket.create_connection = create_connection


def start_standin():
    """Answers like the services expect and records every request's messages."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    requests: list[dict] = []

    def answer(body):
        messages = body.get('messages') or []
        user = next((m.get('content') for m in reversed(messages) if m.get('role') == 'user'), '')
        try:
            request = json.loads(user)
        except (TypeError, ValueError):
            return 'other', '2ByteASR_OK'
        if isinstance(request, dict) and 'output_ids' in request:
            lines = {line['id']: line.get('text', '') for line in request.get('lines', ())}
            return 'translate', json.dumps({'items': [
                {'id': i, 'translation': 'Line ' + ' '.join(re.findall(r'⟦F\d+⟧', lines.get(i, '')))}
                for i in request['output_ids']]})
        if isinstance(request, dict) and 'tasks' in request:
            return 'cleanup', json.dumps({'changes': []})
        cues = request.get('cues') if isinstance(request, dict) else None
        if isinstance(cues, list):
            ids = [cue['id'] for cue in cues]
            return 'polish', json.dumps({'checked_ids': ids, 'cues': [{'id': i, 'edits': []} for i in ids],
                                         'suspect_results': []})
        return 'other', '2ByteASR_OK'

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def _json(self, code, payload):
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.endswith('/models'):
                return self._json(200, {'object': 'list', 'data': [{'id': 'deepseek-chat'}]})
            self._json(404, {'error': {'message': 'not found'}})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
            kind, content = answer(body)
            requests.append({'kind': kind, 'messages': body.get('messages') or []})
            usage = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}
            if not body.get('stream'):
                return self._json(200, {'id': 'r', 'model': 'deepseek-chat', 'usage': usage, 'choices': [
                    {'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}]})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            for packet in ({'choices': [{'index': 0, 'delta': {'content': content}, 'finish_reason': None}]},
                           {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
                           {'choices': [], 'usage': usage}):
                self.wfile.write(('data: ' + json.dumps(dict(packet, id='r', model='deepseek-chat')) + '\n\n')
                                 .encode('utf-8'))
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
            self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name='math-ai-standin').start()
    return server, requests


def start(window, out):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QPlainTextEdit, QPushButton
    from .build_identity import load_build_identity
    from .math_text import FORMULA_RULE
    from .polishing import USER_GLOSSARY_NOTES_RULE

    out = Path(out)
    spec = json.loads((out / 'input.json').read_text('utf8'))
    legacy = window.legacy
    result = dict(passed=False, checks=[], screenshots=[], pid=os.getpid(), executable=sys.executable,
                  build=load_build_identity().to_dict())

    def save():
        result['blocked_external_connections'] = list(_blocked)
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')

    def check(label, ok, detail=None):
        result['checks'].append(dict(name=label, passed=bool(ok), detail=detail))
        save()
        return bool(ok)

    def pump(seconds=.25):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(.005)

    def wait(test, seconds=60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            pump(.025)
            if test():
                return True
        return False

    shot = [0]

    def capture(label, *above):
        shot[0] += 1
        target = out / f'{shot[0]:02d}-{label}.png'
        try:
            import ctypes
            from ctypes import wintypes as W
            from scripts.capture_process_window import print_window

            def grab(widget):
                rect = W.RECT()
                ctypes.windll.user32.GetWindowRect(W.HWND(int(widget.winId())), ctypes.byref(rect))
                return rect, print_window(int(widget.winId()), (rect.left, rect.top, rect.right, rect.bottom))

            base, image = grab(window)
            for widget in above:
                rect, part = grab(widget)
                image.paste(part, (rect.left - base.left, rect.top - base.top))
            image.save(target)
            result['screenshots'].append(target.name)
        except Exception as exc:  # a missing screen is reported, not fatal
            result.setdefault('capture_errors', []).append(f'{label}: {exc}')

    def with_dialog(cls, act, opener):
        """``opener`` shows a modal ``cls``; ``act(dialog)`` runs inside it, then it closes."""
        done = {'tries': 0}

        def drive():
            dialog = next((w for w in QApplication.topLevelWidgets() if isinstance(w, cls) and w.isVisible()), None)
            if dialog is None:
                done['tries'] += 1
                if done['tries'] < 100:
                    QTimer.singleShot(100, drive)
                return
            try:
                pump(.6)
                act(dialog)
            except Exception:
                done['error'] = traceback.format_exc()
            finally:
                done['closed'] = True
                dialog.reject()

        QTimer.singleShot(200, drive)
        opener()
        wait(lambda: 'closed' in done, 120)
        pump(.3)
        return done

    def run():
        try:
            library = spec['library']
            # ---- 术语库页: 「给 AI 的说明」 ------------------------------------------
            window._manage_terms()
            pump(.8)
            page = window.term_library_page._ensure_library()
            page.add_game_item(spec['library_name'], library_id=library, select=True)
            page.refresh_current_game()
            pump(.8)
            QTest.mouseClick(page.more_button, Qt.MouseButton.LeftButton)  # 2026-10-17: the 「⋯」 menu
            pump(.3)
            button = page.ai_note_button
            check('术语库页 has the 「给 AI 的说明」 button for the selected library',
                  button.isVisible() and button.isEnabled() and button.text() == '给 AI 的说明', button.text())
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            wait(lambda: getattr(page, '_ai_note_sheet', None) is not None and page._ai_note_sheet.isVisible(), 10)
            sheet = page._ai_note_sheet
            editor = sheet.findChild(QPlainTextEdit, 'termAiNoteEditor')
            examples = sheet.findChild(QComboBox, 'termAiNoteExamples')
            template = type(page).AI_NOTE_TEMPLATES[0][1]
            examples.setCurrentIndex(1)
            pump(.4)
            check('the math example is inserted into the editor', editor.toPlainText() == template,
                  editor.toPlainText())
            capture('ai-note-sheet')
            save_button = next(b for b in sheet.findChildren(QPushButton) if b.text() == '保存')
            QTest.mouseClick(save_button, Qt.MouseButton.LeftButton)
            pump(1.0)
            check('saving writes the note and marks the button',
                  legacy.learned_content_note(library) == template and button.text() == '给 AI 的说明（已写）',
                  dict(button=button.text()))
            capture('ai-note-saved')
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            wait(lambda: page._ai_note_sheet is not None and page._ai_note_sheet.isVisible(), 10)
            reopened = page._ai_note_sheet.findChild(QPlainTextEdit, 'termAiNoteEditor').toPlainText()
            check('reopening shows the saved note', reopened == template)
            next(b for b in page._ai_note_sheet.findChildren(QPushButton) if b.text() == '取消').click()
            pump(.5)

            # ---- a loopback AI service, saved like 保存 AI 配置 ---------------------------
            server, requests = start_standin()
            from .ui import persist_ai_configuration
            endpoint = dict(service='deepseek', provider='deepseek', transport='openai_compatible',
                            model='deepseek-chat', base_url=f'http://127.0.0.1:{server.server_address[1]}/v1',
                            protocol='auto', key='sk-loopback-stand-in', json_mode=True, structured_output=True)
            persist_ai_configuration(legacy, dict(endpoint), dict(endpoint), unified=True, share_key=False,
                                     require_ready=True)

            # ---- Studio: 查找替换 AI 校对预览 and AI 清理, 字幕翻译 -------------------------
            window.open_studio_project(spec['project'], mode='edit', source='math_ai_audit')
            studio = window.studio_page
            wait(lambda: studio.project is not None and studio._readiness.ready and not studio._readiness.active, 120)
            pump(1.0)
            if not studio.video._paused:
                studio._toggle_playback()
                pump(.3)
            before = [cue.text for cue in studio.project.cues]
            from .studio_find_replace import FindReplaceDialog
            seen = {}

            def terms_and_cleanup(dialog):
                dialog.tabs.setCurrentIndex(3)
                pump(.5)
                seen['libraries'] = dialog._selected_library_ids()
                QTest.mouseClick(dialog.terms_ai_button, Qt.MouseButton.LeftButton)
                wait(lambda: any(r['kind'] == 'polish' for r in requests) and dialog.terms_ai_button.isEnabled(), 120)
                pump(.8)
                seen['terms_status'] = dialog.status_label.text()
                capture('find-replace-terms', dialog)
                dialog.tabs.setCurrentIndex(2)
                pump(.4)
                QTest.mouseClick(dialog.ai_run_button, Qt.MouseButton.LeftButton)
                wait(lambda: any(r['kind'] == 'cleanup' for r in requests), 60)
                pump(.8)
                seen['cleanup_status'] = dialog.status_label.text()
                capture('find-replace-cleanup', dialog)

            outcome = with_dialog(FindReplaceDialog, terms_and_cleanup, studio._open_find_replace)
            check('查找替换 ran AI 校对预览 and AI 清理 with the project library',
                  library in seen.get('libraries', ()) and any(r['kind'] == 'polish' for r in requests)
                  and any(r['kind'] == 'cleanup' for r in requests), dict(seen=seen, error=outcome.get('error')))
            from .studio_translation_dialog import SubtitleTranslationDialog

            def translate(dialog):
                QTest.mouseClick(dialog.start_button, Qt.MouseButton.LeftButton)
                wait(lambda: any(r['kind'] == 'translate' for r in requests) and dialog.start_button.isEnabled(), 90)
                pump(.8)
                seen['translate_status'] = dialog.status.text()
                capture('translation', dialog)

            outcome = with_dialog(SubtitleTranslationDialog, translate, studio._open_translation_dialog)
            check('字幕翻译 sent a request', any(r['kind'] == 'translate' for r in requests),
                  dict(status=seen.get('translate_status'), error=outcome.get('error')))

            # ---- what the AI actually received ------------------------------------------
            def texts(kind, role):
                return [m.get('content') or '' for r in requests if r['kind'] == kind for m in r['messages']
                        if m.get('role') == role]

            for kind in ('polish', 'cleanup', 'translate'):
                # Subtitles travel in the user message; the system prompt holds the rule (and the
                # user's own note, which may quote LaTeX such as the math example's $\frac{1}{2}$).
                sent = texts(kind, 'user')
                check(f'{kind}: formulas only as placeholders, with the formula rule',
                      sent and any('⟦F1⟧' in text for text in sent) and not any('\\frac' in text or '$\\' in text
                                                                               for text in sent)
                      and any(FORMULA_RULE in text for text in texts(kind, 'system')),
                      dict(samples=[text[:300] for text in sent if '⟦F' in text][:2]))
            polish_system = next((m['content'] for r in requests if r['kind'] == 'polish' for m in r['messages']
                                  if m.get('role') == 'system'), '')
            check('AI 校对 received the library note as the user\'s instructions',
                  USER_GLOSSARY_NOTES_RULE in polish_system and template in polish_system
                  and f'【{spec["library_name"]}】' in polish_system)
            check('the project keeps its LaTeX (nothing applied)', [cue.text for cue in studio.project.cues] == before
                  and before == spec['texts'], before)
            check('only loopback connections', not _blocked, list(_blocked))
            result['standin_requests'] = [dict(kind=r['kind'], roles=[m.get('role') for m in r['messages']])
                                          for r in requests]
            (out / 'standin-requests.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2), 'utf8')
            server.shutdown()
            result['passed'] = all(item['passed'] for item in result['checks'])
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            save()
            QTimer.singleShot(300, close)

    def close():
        result['gui_shutdown'] = True
        save()
        studio = window.built_page('studio')
        if studio is not None and studio.project is not None and not studio.undo_stack.isClean():
            studio.undo_stack.setClean()
        window.close()
        QApplication.instance().quit()

    QTimer.singleShot(2500, run)
