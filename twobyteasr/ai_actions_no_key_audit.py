"""Real-window audit: user-clicked AI actions without an API key (2026-10-15).

Runs inside the real application on a private desktop with an isolated
profile and no key anywhere (``scripts/verify_studio_ai_no_key_headed.py``):

no key — 术语库 「AI 完整建库」 shows 「这个功能要用 AI，需要先填 API Key」 →
result page → 「AI 词库校对…」 opens and matches locally without an error →
「AI 校对」 shows the note: 取消 sends nothing; 「API Key 是什么？」 opens the
picture explainer and its 「我要用 AI：一步步教我」 opens 申请与设置 API →
Studio → the cue menu's three 「AI 断句」 entries, AI 设计 「生成字幕设计」,
查找替换 「生成 AI 预览」 and 「按当前词库生成 AI 校对预览」 and 字幕翻译
「开始翻译」 each show the same note and send nothing; 剪辑助手 「分析录播」
gives its local candidates and says “没填 API Key”, without a request.

with a key — a DeepSeek-shaped endpoint on a loopback stand-in (synthetic
answers on 127.0.0.1, no paid call) is saved through
``persist_ai_configuration`` like 保存 AI 配置: 「AI 断句 · 全工程执行」,
字幕翻译, AI 清理 and 「AI 校对」 run as before, without the note.

Every connection outside the loopback is refused and recorded.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

_blocked: list[str] = []
_submits: list[str] = []


def install_guards() -> None:
    """Loopback only, no background model discovery; provider calls are counted, not denied."""
    import ipaddress
    import socket
    from .ui import EndpointEditor
    from .provider_service import ProviderService
    from .studio_ai_flow import StudioAIFlowMixin

    EndpointEditor._queue_model_discovery = lambda *a, **kw: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *a, **kw: None

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
            raise RuntimeError('External network prohibited in the ai-actions-no-key audit')

    original_connect, original_create = socket.socket.connect, socket.create_connection

    def connect(sock, address, *args, **kwargs):
        local(address)
        return original_connect(sock, address, *args, **kwargs)

    def create_connection(address, *args, **kwargs):
        local(address)
        return original_create(address, *args, **kwargs)

    socket.socket.connect = connect
    socket.create_connection = create_connection
    original_submit = ProviderService.submit

    def submit(self, settings, stage, *args, **kwargs):
        _submits.append(str(stage))
        return original_submit(self, settings, stage, *args, **kwargs)

    ProviderService.submit = submit


def start_standin():
    """OpenAI-compatible chat completions on 127.0.0.1: every AI 断句 cue kept, no proofreading edit."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    requests: list[dict] = []

    def answer(body):
        for message in body.get('messages') or []:
            if message.get('role') != 'user':
                continue
            try:
                request = json.loads(message.get('content'))
            except (TypeError, ValueError):
                continue
            cues = request.get('cues') if isinstance(request, dict) else None
            if isinstance(request, dict) and 'output_ids' in request:
                return 'translate', json.dumps({'items': [{'id': i, 'translation': 'A line from the stand-in.'}
                                                          for i in request['output_ids']]})
            if isinstance(request, dict) and 'tasks' in request:
                return 'cleanup', json.dumps({'changes': []})
            if isinstance(cues, list) and cues and 'cue_id' in cues[0]:
                return 'refine', json.dumps({'results': [{'cue_id': cue['cue_id'], 'action': 'keep',
                                                          'split_after_chars': [], 'space_after_chars': [],
                                                          'reason': 'stand-in'} for cue in cues]})
            if isinstance(cues, list):
                ids = [cue['id'] for cue in cues]
                return 'polish', json.dumps({'checked_ids': ids, 'cues': [{'id': i, 'edits': []} for i in ids],
                                             'suspect_results': []})
            break
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
            requests.append({'kind': kind, 'stream': bool(body.get('stream')),
                             'authorization': bool(self.headers.get('Authorization'))})
            time.sleep(.3)
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
    threading.Thread(target=server.serve_forever, daemon=True, name='ai-actions-standin').start()
    return server, requests


def start(window, out):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QPushButton
    from .build_identity import load_build_identity

    out = Path(out)
    delivery = json.loads((out / 'delivery.json').read_text('utf8'))
    result = dict(passed=False, checks=[], notes=[], screenshots=[], pid=os.getpid(), executable=sys.executable,
                  build=load_build_identity().to_dict())

    def save():
        result['blocked_external_connections'] = list(_blocked)
        result['provider_submits'] = list(_submits)
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
        """The main window with any top-level popups (menu, note, dialog) pasted where they are."""
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
        return target

    # One watcher answers every note / explainer / setup guide the actions open.
    plan = {'note': 'cancel', 'label': ''}
    handled: set[int] = set()

    def watch():
        from .api_key_explainer import ApiKeyExplainerDialog
        from .api_setup_dialog import ApiSetupDialog
        for widget in QApplication.topLevelWidgets():
            if not widget.isVisible() or id(widget) in handled:
                continue
            if isinstance(widget, QMessageBox) and widget.objectName() == 'apiKeyNeeded':
                handled.add(id(widget))
                pump(.3)
                result['notes'].append(dict(at=plan['label'], title=widget.windowTitle(), text=widget.text(),
                                            buttons=[button.text() for button in widget.buttons()],
                                            answer=plan['note']))
                dialogs = [w for w in QApplication.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()
                           and w is not widget and w is not window]
                capture(f'note-{plan["label"]}', *dialogs, widget)
                name = 'apiKeyNeededExplain' if plan['note'] == 'explain' else 'apiKeyNeededCancel'
                QTimer.singleShot(0, widget.findChild(QPushButton, name).click)
            elif isinstance(widget, ApiKeyExplainerDialog):
                handled.add(id(widget))
                pump(.8)
                result['explainer'] = dict(title=widget.windowTitle(), setup=widget.setup_button.text())
                capture('explainer', widget)
                QTimer.singleShot(0, widget.setup_button.click)   # 我要用 AI：一步步教我
            elif isinstance(widget, ApiSetupDialog):
                handled.add(id(widget))
                pump(.8)
                result['setup_guide'] = dict(title=widget.windowTitle(), kind=getattr(widget, 'kind', None))
                capture('api-setup-guide', widget)
                QTimer.singleShot(0, widget.reject)

    watcher = QTimer(window)
    watcher.setInterval(80)
    watcher.timeout.connect(watch)

    def notes_at(label):
        return [note for note in result['notes'] if note['at'] == label]

    def open_proofread():
        window._switch_page(2)
        pump(.3)
        window._completion_action_last_by_name = {}
        QTest.mouseClick(window.repolish_current_glossary_button, Qt.MouseButton.LeftButton)
        opened = wait(lambda: getattr(window, 'glossary_proofread_page', None) is not None
                      and window.pages.currentWidget() is window.glossary_proofread_page, 20)
        review = window.glossary_proofread_page
        finished = wait(lambda: not review.checks_running(), 120)
        pump(.5)
        return review, opened and finished

    def click_ai_proofread(review, label, answer):
        plan.update(note=answer, label=label)
        before = len(_submits)
        QTest.mouseClick(review.ai_button, Qt.MouseButton.LeftButton)
        wait(lambda: notes_at(label) and not any(isinstance(w, QMessageBox) and w.isVisible()
                                                 for w in QApplication.topLevelWidgets()), 20)
        if answer == 'explain':
            wait(lambda: 'setup_guide' in result, 20)
        pump(.6)
        return len(_submits) - before

    def run_menu(page, text, label, answer='cancel'):
        """Open the cue ⋯ menu like a user, pick ``text``."""
        plan.update(note=answer, label=label)
        picked = {}

        def pick():
            menu = QApplication.activePopupWidget()
            if not isinstance(menu, QMenu):
                QTimer.singleShot(100, pick)
                return
            pump(.2)
            action = next((a for a in menu.actions() if a.text() == text), None)
            picked.update(found=action is not None, enabled=bool(action and action.isEnabled()),
                          entries=[a.text() for a in menu.actions() if a.text()])
            if label.endswith('selection'):
                capture('cue-menu', menu)
            menu.close()
            if action is not None and action.isEnabled():
                QTimer.singleShot(0, action.trigger)

        QTimer.singleShot(250, pick)
        QTest.mouseClick(page.cue_more_button, Qt.MouseButton.LeftButton)
        wait(lambda: 'found' in picked, 10)
        pump(.3)
        return picked

    def press(button):
        """A real click when the button is on screen (drawers may keep it scrolled away)."""
        if button.isVisible():
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        else:
            button.click()

    def with_dialog(cls, act, opener):
        """``opener`` shows a modal ``cls`` (exec); ``act(dialog)`` runs inside it, then it closes."""
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
        wait(lambda: 'closed' in done, 30)
        pump(.3)
        return done

    def run():
        try:
            from .studio_project import load_project
            from .llm_config import text_ai_key_missing
            from .service import MediaResult, QueueResult
            from .settings import load_runtime_settings
            legacy = window.legacy
            project_path = str(Path(delivery['project_path']).resolve())
            check('no API key in the profile or the environment',
                  text_ai_key_missing(legacy.RUNTIME_SETTINGS, 'polish')
                  and text_ai_key_missing(legacy.RUNTIME_SETTINGS, 'group')
                  and not [key for key in os.environ if 'API_KEY' in key.upper()])
            watcher.start()

            # ---- 术语库 「AI 完整建库」 without a key ----------------------------------
            window._manage_terms()
            have_library = wait(lambda: window.term_library_page.library is not None, 30)
            library = window.term_library_page.library
            pump(1.0)
            items = [library.game_list.item(i) for i in range(library.game_list.count())]
            chosen = (next((item for item in items if item.data(Qt.ItemDataRole.UserRole + 1) == delivery['library']), None)
                      or next((item for item in items if '原神' in item.text()), None))
            if chosen is not None:
                library.game_list.setCurrentItem(chosen)
                pump(.8)
            plan.update(note='cancel', label='glossary-build')
            before = len(_submits)
            press(library.ai_menu_button)  # 2026-10-17: the AI actions live in 「AI 更新 ▾」
            pump(.3)
            press(library.ai_full_button)
            wait(lambda: notes_at('glossary-build'), 10)
            pump(.4)
            manager = getattr(library, '_task_manager', None)
            game = library.state.get('game')
            check('术语库「AI 完整建库」 without a key: the note, no task queued',
                  have_library and len(notes_at('glossary-build')) == 1 and len(_submits) == before and not _blocked
                  and library.ai_update_status.text() == 'AI 建库没有运行：还没填 API Key'
                  and (manager is None or manager.pending_for_game(game) is None),
                  dict(game=game, status=library.ai_update_status.text()))
            capture('glossary-build-no-key')

            # ---- result page ---------------------------------------------------
            delivered = load_project(project_path)
            item = MediaResult(media_path=delivery['media_path'], status='success', project_path=project_path,
                               job_id=delivery['job_id'], project_id=delivered.project_id,
                               result_ref_json=delivery['result_ref_json'], elapsed_seconds=1.0)
            window._ensure_recognition_page()
            window._active_job_id = delivery['job_id']
            window.showMaximized()
            window._handle_result(QueueResult((item,), 1.0, job_id=delivery['job_id']))
            pump(1.0)
            dialog = getattr(window, '_completion_dialog', None)
            if dialog is not None:
                QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
                wait(lambda: getattr(window, '_completion_dialog', None) is None, 5)
                pump(.4)
            check('the result page shows the task', window.pages.currentWidget() is window.pages.widget(2)
                  and window.repolish_current_glossary_button.isEnabled())
            capture('result-page')

            # ---- 完成页「AI 词库校对…」 without a key ----------------------------------
            notes_before = len(result['notes'])
            review, ready = open_proofread()
            status = review.status_label.text()
            check('完成页「AI 词库校对…」 opens and matches locally with no key error',
                  ready and 'API' not in status and '失败' not in status and len(result['notes']) == notes_before, status)
            check('the project library is selected for 「AI 校对」', bool(review._selected_ids()), review._selected_ids())
            capture('proofread-open-no-key')
            sent = click_ai_proofread(review, 'proofread-cancel', 'cancel')
            notes = notes_at('proofread-cancel')
            check('「AI 校对」 without a key: the note, not an error',
                  len(notes) == 1 and notes[0]['text'] == '这个功能要用 AI，需要先填 API Key'
                  and notes[0]['title'] == '需要 API Key'
                  and sorted(notes[0]['buttons']) == sorted(['API Key 是什么？', '取消']), notes)
            check('取消: nothing sent, no AI run, a plain status line',
                  sent == 0 and review._worker is None and not _blocked
                  and review.status_label.text() == 'AI 校对没有运行：还没填 API Key', review.status_label.text())
            capture('proofread-after-cancel')
            sent = click_ai_proofread(review, 'proofread-explain', 'explain')
            check('「API Key 是什么？」 opens the picture explainer', 'explainer' in result, result.get('explainer'))
            check('…whose 「我要用 AI：一步步教我」 opens 申请与设置 API', 'setup_guide' in result, result.get('setup_guide'))
            check('still nothing sent', sent == 0 and review._worker is None and not _blocked)
            QTest.mouseClick(review.back_button, Qt.MouseButton.LeftButton)
            wait(lambda: window.pages.currentWidget() is window.pages.widget(2), 10)

            # ---- Studio 「AI 断句」 without a key --------------------------------------
            window._completion_action_last_by_name = {}
            QTest.mouseClick(window.open_studio_result_button, Qt.MouseButton.LeftButton)
            page = window.studio_page
            ready = wait(lambda: page.project is not None and page._readiness.ready
                         and window.pages.currentWidget() is page, 120)
            check('Studio opens the task', ready)
            page.video.set_paused(True)   # Studio starts playing on open
            pump(.5)
            page.select_cue(page.project.cues[0].id)   # what a click on the first caption does
            pump(.3)
            check('a caption is selected for 「选中范围试跑」', page.selected_cue_id == page.project.cues[0].id)
            state_before = json.dumps(page.project.studio_state.get('ai_sentence_refine'), sort_keys=True)
            entries = (('AI 断句 · 选中范围试跑', 'refine-selection'), ('AI 断句 · 全工程执行', 'refine-project'),
                       ('AI 断句 · 仅重试失败范围', 'refine-retry'))
            for text, label in entries:
                before = len(_submits)
                picked = run_menu(page, text, label)
                wait(lambda: notes_at(label), 10)
                pump(.4)
                notes = notes_at(label)
                check(f'「{text}」 without a key: the note, nothing sent',
                      picked.get('enabled') and len(notes) == 1 and notes[0]['text'] == '这个功能要用 AI，需要先填 API Key'
                      and len(_submits) == before and getattr(page, '_refine_worker', None) is None and not _blocked,
                      dict(picked=picked, notes=notes, save_state=page.save_state.text()))
                check(f'「{text}」: status says it did not run',
                      page.save_state.text() == 'AI 断句没有运行：还没填 API Key', page.save_state.text())
            check('no failed range recorded, nothing marked as processed',
                  json.dumps(page.project.studio_state.get('ai_sentence_refine'), sort_keys=True) == state_before)
            capture('studio-after-no-key')

            # ---- the other Studio AI actions without a key ----------------------------
            from .studio_find_replace import FindReplaceDialog
            from .studio_translation_dialog import SubtitleTranslationDialog
            before = len(_submits)
            page._toggle_drawer(0)   # AI 设计
            pump(.8)
            plan.update(note='cancel', label='design')
            press(page.ai_generate)
            wait(lambda: notes_at('design'), 10)
            pump(.4)
            check('AI 设计「生成字幕设计」 without a key: the note, nothing started',
                  len(notes_at('design')) == 1 and getattr(page, '_ai_preparing_request', None) is None
                  and not getattr(page, '_ai_request_active', False)
                  and len(_submits) == before and not _blocked, page.ai_generate.text())
            found = {}

            def cleanup_and_terms(dialog):
                dialog.tabs.setCurrentIndex(2)   # AI 清理
                pump(.4)
                plan.update(note='cancel', label='cleanup')
                press(dialog.ai_run_button)
                pump(.3)
                found['cleanup'] = dialog.status_label.text()
                dialog.tabs.setCurrentIndex(3)   # 应用术语库
                pump(.4)
                plan.update(note='cancel', label='terms-preview')
                press(dialog.terms_ai_button)
                pump(.3)
                found['terms'] = dialog.status_label.text()
                found['worker'] = dialog._glossary_review_worker is not None

            outcome = with_dialog(FindReplaceDialog, cleanup_and_terms, page._open_find_replace)
            check('查找替换「生成 AI 预览」 without a key: the note, nothing sent',
                  len(notes_at('cleanup')) == 1 and found.get('cleanup') == 'AI 清理没有运行：还没填 API Key'
                  and len(_submits) == before and not _blocked, dict(found=found, error=outcome.get('error')))
            check('查找替换「按当前词库生成 AI 校对预览」 without a key: the note, no review started',
                  len(notes_at('terms-preview')) == 1 and found.get('terms') == 'AI 校对没有运行：还没填 API Key'
                  and not found.get('worker') and len(_submits) == before, found)
            seen = {}

            def translate_without_key(dialog):
                seen.update(service=dialog.service.text(), enabled=dialog.start_button.isEnabled())
                plan.update(note='cancel', label='translate')
                press(dialog.start_button)
                pump(.3)
                seen.update(status=dialog.status.text(), thread=getattr(dialog, '_thread', None) is not None)

            outcome = with_dialog(SubtitleTranslationDialog, translate_without_key, page._open_translation_dialog)
            check('字幕翻译 without a key: says so, 「开始翻译」 shows the note, nothing sent',
                  seen.get('service') == '这个功能要用 AI，需要先填 API Key' and seen.get('enabled')
                  and len(notes_at('translate')) == 1 and seen.get('status') == '翻译没有运行：还没填 API Key'
                  and not seen.get('thread') and len(_submits) == before, dict(seen=seen, error=outcome.get('error')))
            page._toggle_drawer(3)   # 剪辑助手
            pump(.8)
            panel = page.highlight_panel
            plan.update(note='cancel', label='highlight')
            press(panel.analyze_button)
            analysed = wait(lambda: '没填 API Key' in panel.status.text(), 90)
            pump(.5)
            check('剪辑助手「分析录播」 without a key: local result, the reason says 没填 API Key, nothing sent',
                  analysed and not notes_at('highlight') and len(_submits) == before and not _blocked,
                  panel.status.text())
            capture('highlight-no-key')
            page._toggle_drawer(0)

            # ---- with a key: the same entries run as before ---------------------------
            server, requests = start_standin()
            from .ui import persist_ai_configuration
            endpoint = dict(service='deepseek', provider='deepseek', transport='openai_compatible',
                            model='deepseek-chat', base_url=f'http://127.0.0.1:{server.server_address[1]}/v1',
                            protocol='auto', key='sk-loopback-stand-in', json_mode=True, structured_output=True)
            persist_ai_configuration(legacy, dict(endpoint), dict(endpoint), unified=True, share_key=False,
                                     require_ready=True)
            saved = load_runtime_settings()
            saved = saved[0] if isinstance(saved, tuple) else saved
            check('with a saved key the rule no longer applies',
                  not text_ai_key_missing(saved, 'group') and not text_ai_key_missing(legacy.RUNTIME_SETTINGS, 'polish'))
            label = 'refine-with-key'
            picked = run_menu(page, 'AI 断句 · 全工程执行', label)
            done = wait(lambda: getattr(page, '_refine_worker', None) is None
                        and page.save_state.text().startswith('AI 断句完成'), 60)
            refine_requests = [row for row in requests if row['kind'] == 'refine']
            check('with a key 「AI 断句 · 全工程执行」 runs as before (no note, request sent, result applied)',
                  picked.get('enabled') and done and not notes_at(label) and refine_requests
                  and all(row['authorization'] for row in refine_requests) and not _blocked,
                  dict(save_state=page.save_state.text(), requests=requests))
            capture('studio-with-key')
            seen = {}

            def translate_with_key(dialog):
                seen.update(service=dialog.service.text())
                plan.update(note='cancel', label='translate-with-key')
                press(dialog.start_button)
                wait(lambda: any(row['kind'] == 'translate' for row in requests) and dialog.start_button.isEnabled(), 60)
                pump(.6)
                seen.update(status=dialog.status.text())
                capture('translation-with-key', dialog)

            outcome = with_dialog(SubtitleTranslationDialog, translate_with_key, page._open_translation_dialog)
            check('with a key 字幕翻译 runs as before (no note, request sent)',
                  not notes_at('translate-with-key') and any(row['kind'] == 'translate' for row in requests)
                  and seen.get('service', '').startswith('使用已配置的 AI 文字服务') and not _blocked,
                  dict(seen=seen, error=outcome.get('error')))

            def cleanup_with_key(dialog):
                dialog.tabs.setCurrentIndex(2)
                pump(.4)
                plan.update(note='cancel', label='cleanup-with-key')
                press(dialog.ai_run_button)
                pump(.6)
                seen.update(cleanup=dialog.status_label.text())

            outcome = with_dialog(FindReplaceDialog, cleanup_with_key, page._open_find_replace)
            check('with a key AI 清理 runs as before (no note, request sent)',
                  not notes_at('cleanup-with-key') and any(row['kind'] == 'cleanup' for row in requests) and not _blocked,
                  dict(status=seen.get('cleanup'), error=outcome.get('error')))
            if not page.undo_stack.isClean():
                page.project_controller.save()
            page._request_return_home()
            pump(.5)
            review, ready = open_proofread()
            label = 'proofread-with-key'
            plan.update(note='cancel', label=label)
            QTest.mouseClick(review.ai_button, Qt.MouseButton.LeftButton)
            done = wait(lambda: review._worker is None and review.status_label.text().startswith('AI 校对完成'), 90)
            polish_requests = [row for row in requests if row['kind'] == 'polish']
            check('with a key 「AI 校对」 runs as before (no note, request sent, result shown)',
                  ready and done and not notes_at(label) and polish_requests and not _blocked,
                  dict(status=review.status_label.text(), requests=requests))
            capture('proofread-with-key')
            result['standin_requests'] = requests
            server.shutdown()
            result['passed'] = all(item['passed'] for item in result['checks'])
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            watcher.stop()
            save()
            QTimer.singleShot(300, close)

    def close():
        result['gui_shutdown'] = True
        save()
        studio = window.built_page('studio')
        if studio is not None and studio.project is not None and not studio.undo_stack.isClean():
            studio.project_controller.save()
        window.close()
        QApplication.instance().quit()

    QTimer.singleShot(2500, run)
