"""Real-window audit: 排查原因 on the completion page and in recognition history (2026-10-23).

Runs inside the real application on a private desktop with an isolated
profile (``scripts/verify_run_diagnosis_headed.py``). For each prepared task
report (a failed one whose result carries no report path, a degraded one, a
cloud failure) the completion page must show the likely cause on the result
card, and 「查看原因与解决办法」 must open the window with the local findings,
nothing clipped. Then the AI part: without a key it offers 「设置 API Key…」,
which opens the AI settings and comes back to the window when they close;
with a key for a DeepSeek-shaped loopback stand-in (no paid call) the answer
streams in, and 复制排查报告 carries it. Every connection outside the loopback
is refused and recorded.
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
STANDIN_ANSWER = (
    "**结论**：这次失败的直接原因是数字在断句时被切开；根本原因是没有字级时间轴、也没开 AI 断句。\n\n"
    "**依据**\n- `final_content_conservation_recovery`：原文没有数字，断句后读出 2\n"
    "- `settings.models.firered_asr_backend = off`\n\n"
    "**怎么做**\n1. 首页把「字幕语言」改成中文\n2. 打开字幕时间轴（FireRedASR2-AED）\n3. 重新识别"
)


def install_guards() -> None:
    """Loopback only; background model discovery off."""
    import ipaddress
    import socket
    from ..app.ui import EndpointEditor

    EndpointEditor._queue_model_discovery = lambda *a, **kw: None

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
            raise RuntimeError('External network prohibited in the run-diagnosis audit')

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
    """OpenAI-compatible chat completions on 127.0.0.1 answering in small streamed pieces."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    requests: list[dict] = []

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
            messages = body.get('messages') or []
            system = next((m.get('content') for m in messages if m.get('role') == 'system'), '')
            user = next((m.get('content') for m in messages if m.get('role') == 'user'), '')
            requests.append(dict(stream=bool(body.get('stream')), authorization=bool(self.headers.get('Authorization')),
                                 system_chars=len(str(system)), user_chars=len(str(user)),
                                 catalog='[fidelity_numbers]' in str(system), digest='```json' in str(user),
                                 findings='fidelity_numbers' in str(user)))
            content = STANDIN_ANSWER if '排错助手' in str(system) else '2ByteASR_OK'
            usage = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}
            if not body.get('stream'):
                return self._json(200, {'id': 'r', 'model': 'deepseek-chat', 'usage': usage, 'choices': [
                    {'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}]})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            pieces = [content[index:index + 24] for index in range(0, len(content), 24)]
            for piece in pieces:
                packet = {'choices': [{'index': 0, 'delta': {'content': piece}, 'finish_reason': None}]}
                self.wfile.write(('data: ' + json.dumps(dict(packet, id='r', model='deepseek-chat'), ensure_ascii=False)
                                  + '\n\n').encode('utf-8'))
                self.wfile.flush()
                time.sleep(0.06)
            for packet in ({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}, {'choices': [], 'usage': usage}):
                self.wfile.write(('data: ' + json.dumps(dict(packet, id='r', model='deepseek-chat')) + '\n\n').encode('utf-8'))
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
            self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name='run-diagnosis-standin').start()
    return server, requests


def clipped_widgets(root):
    """Visible labels and buttons whose text does not fit the space they got."""
    from PySide6.QtWidgets import QAbstractButton, QLabel
    problems = []
    for label in root.findChildren(QLabel):
        if not label.isVisible() or not label.text() or label.width() <= 0:
            continue
        if label.wordWrap():
            need = label.heightForWidth(label.width())
            if need > label.height() + 2:
                problems.append(dict(kind='label', name=label.objectName(), text=label.text()[:60],
                                     need=need, height=label.height()))
        elif label.textFormat() != 1 and label.fontMetrics().horizontalAdvance(label.text()) > label.width() + 2 \
                and '<' not in label.text():
            problems.append(dict(kind='label-line', name=label.objectName(), text=label.text()[:60],
                                 need=label.fontMetrics().horizontalAdvance(label.text()), width=label.width()))
    for button in root.findChildren(QAbstractButton):
        if not button.isVisible() or not button.text() or button.text() in ('×',):
            continue
        hint = button.sizeHint()
        if hint.width() > button.width() + 4 or hint.height() > button.height() + 4:
            problems.append(dict(kind='button', name=button.objectName(), text=button.text()[:60],
                                 hint=[hint.width(), hint.height()], size=[button.width(), button.height()]))
    return problems


def overflowing(dialog):
    """Cards wider than the scroll viewport: their right part is cut off."""
    width = dialog.scroll.viewport().width()
    widgets = list(dialog.cards) + [dialog.ai_panel]
    return [dict(name=widget.objectName(), width=widget.width(), viewport=width)
            for widget in widgets if widget.isVisible() and widget.width() > width + 1]


def start(window, out):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QScrollArea
    from ..diagnostics.build_identity import load_build_identity
    from ..recognition.service import MediaResult, QueueResult

    out = Path(out)
    delivery = json.loads((out / 'delivery.json').read_text('utf8'))
    result = dict(passed=False, checks=[], screenshots=[], pid=os.getpid(), executable=sys.executable,
                  build=load_build_identity().to_dict(), delivery=delivery)

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

    def wait(test, seconds=30):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            pump(.025)
            if test():
                return True
        return False

    shot = [0]

    def capture(label, *above):
        """The main window with top-level dialogs pasted where they are (PrintWindow)."""
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
        except Exception as exc:
            result.setdefault('capture_errors', []).append(f'{label}: {exc}')
        return target

    def with_dialog(opener, body, seconds=20):
        """Open the 排查原因 window (its exec() blocks) and run ``body`` while it shows."""
        state = {}

        def inside():
            dialog = getattr(window, '_run_diagnosis_dialog', None)
            if dialog is None or not dialog.isVisible():
                if time.monotonic() < state['deadline']:
                    QTimer.singleShot(100, inside)
                else:
                    state['error'] = 'dialog did not open'
                return
            try:
                pump(.6)
                body(dialog)
            except Exception:
                state['error'] = traceback.format_exc()
            finally:
                # A button that left the window already closed it.
                if dialog.isVisible() and not dialog.chosen_action:
                    dialog.reject()
        state['deadline'] = time.monotonic() + seconds
        QTimer.singleShot(150, inside)
        opener()
        pump(.5)
        return state

    def show_task(case):
        media = case['media']
        item = MediaResult(media, case['status'], error=case.get('error', ''), job_id=case['job_id'],
                           report_json_path=case.get('report_json_path', ''))
        window._committed_job_ids = set()  # the same task shown again
        window._handle_result(QueueResult((item,), 1.0, job_id=case['job_id']))
        window._switch_page(2)
        pump(1.0)

    def run():
        from ..design.theme_manager import apply_theme
        try:
            window.showNormal()
            width, height = delivery.get('window', [1536, 824])
            window.resize(int(width), int(height))
            apply_theme(delivery.get('theme', 'grape'))
            pump(1.0)
            if delivery.get('language', 'zh') != 'zh':
                from ..i18n import save_language
                save_language(delivery['language'])
                pump(.5)
            for case in delivery['cases']:
                label = case['label']
                show_task(case)
                hint = window.result_diagnosis_hint
                capture(f'result-{label}')
                expected = case['expect_top']
                card = window.result_summary_card
                inside = card.rect().contains(hint.geometry().translated(hint.parentWidget().mapTo(card, hint.pos()) - hint.pos()))
                check(f'{label}: the result card names the likely cause',
                      not hint.isHidden() and hint.finding is not None and hint.finding.rule_id == expected and inside,
                      dict(finding=getattr(hint.finding, 'rule_id', None), text=hint.text_label.text(),
                           cause=hint.cause_label.text(), button=hint.open_button.text(), inside_card=inside))
                check(f'{label}: nothing on the result card is clipped', not clipped_widgets(card), clipped_widgets(card))
                seen = {}

                def inspect(dialog, label=label, case=case):
                    scroll = dialog.findChild(QScrollArea, 'diagScroll')
                    seen['rules'] = [card.finding.rule_id for card in dialog.cards]
                    seen['clipped'] = clipped_widgets(dialog) + overflowing(dialog)
                    seen['size'] = [dialog.width(), dialog.height()]
                    seen['inside_window'] = window.frameGeometry().contains(dialog.frameGeometry())
                    capture(f'dialog-{label}', dialog)
                    toggle = getattr(dialog.cards[0], 'evidence_toggle', None) if dialog.cards else None
                    if toggle is not None:
                        toggle.click()
                        pump(.4)
                        seen['evidence_shown'] = dialog.cards[0].evidence_label.isVisible()
                    if scroll is not None:
                        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                        pump(.4)
                    seen['clipped_after'] = clipped_widgets(dialog) + overflowing(dialog)
                    capture(f'dialog-{label}-bottom', dialog)

                outcome = with_dialog(lambda: window._completion_action('diagnose', window._open_completion_diagnosis), inspect)
                check(f'{label}: 查看原因 opens the window with the local findings, nothing clipped',
                      not outcome.get('error') and seen.get('rules', [None])[0] == expected
                      and not seen.get('clipped') and not seen.get('clipped_after') and seen.get('inside_window'),
                      dict(seen=seen, error=outcome.get('error')))

            # ---- the AI part on the first case --------------------------------------------
            case = delivery['cases'][0]
            show_task(case)
            seen = {}

            def no_key(dialog):
                panel = dialog.ai_panel
                seen['no_key'] = dict(ready=panel.ready, setup=getattr(panel, 'setup_button', None) is not None,
                                      task=dialog.task_name)
                dialog.scroll.ensureWidgetVisible(panel)
                pump(.4)
                capture('ai-no-key', dialog)
                panel.setup_button.click()

            settings_seen = {}

            def watch_settings():
                current = getattr(window, '_ai_settings_dialog', None)
                if current is not None and current.isVisible() and not settings_seen:
                    pump(.8)
                    settings_seen['open'] = True
                    capture('ai-settings-from-diagnosis', current)
                    QTimer.singleShot(200, current.reject)
                elif not settings_seen:
                    QTimer.singleShot(150, watch_settings)

            QTimer.singleShot(400, watch_settings)

            # The reopened window runs its own modal loop (inside our wait): a
            # timer records it and closes it, as the user would.
            reopened = {}

            def watch_reopen():
                dialog = getattr(window, '_run_diagnosis_dialog', None)
                if settings_seen.get('open') and dialog is not None and dialog.isVisible():
                    pump(.5)
                    reopened.update(task=dialog.task_name, ready=dialog.ai_panel.ready)
                    capture('reopened-after-settings', dialog)
                    dialog.reject()
                elif not reopened:
                    QTimer.singleShot(150, watch_reopen)

            QTimer.singleShot(300, watch_reopen)
            outcome = with_dialog(lambda: window._completion_action('diagnose', window._open_completion_diagnosis), no_key)
            wait(lambda: bool(reopened), 20)
            pump(.6)
            check('no key: the AI part offers 设置 API Key…; it opens the AI settings and the window comes back after',
                  seen.get('no_key', {}).get('setup') and not seen['no_key']['ready'] and settings_seen.get('open')
                  and reopened.get('task') == seen['no_key'].get('task'),
                  dict(seen=seen, settings=settings_seen, reopened=reopened, error=outcome.get('error')))

            server, requests = start_standin()
            from ..app.ui import persist_ai_configuration
            endpoint = dict(service='deepseek', provider='deepseek', transport='openai_compatible',
                            model='deepseek-chat', base_url=f'http://127.0.0.1:{server.server_address[1]}/v1',
                            protocol='auto', key='sk-loopback-stand-in', json_mode=True, structured_output=True)
            persist_ai_configuration(window.legacy, dict(endpoint), dict(endpoint), unified=True, share_key=False,
                                     require_ready=True)
            ai = {}

            def with_key(dialog):
                panel = dialog.ai_panel
                ai['ready'] = panel.ready
                ai['intro'] = panel.intro.text() if panel.ready else ''
                dialog.scroll.ensureWidgetVisible(panel)
                panel.run_button.click()
                streamed = wait(lambda: len(panel.output.toPlainText()) > 20, 20)
                ai['streaming_seen_while_running'] = streamed and panel.running
                dialog.scroll.ensureWidgetVisible(panel.output)
                capture('ai-streaming', dialog)
                wait(lambda: not panel.running, 30)
                pump(.4)
                dialog.scroll.verticalScrollBar().setValue(dialog.scroll.verticalScrollBar().maximum())
                pump(.3)
                ai['answer'] = panel.answer
                ai['status'] = panel.status.text()
                ai['clipped'] = clipped_widgets(dialog) + overflowing(dialog)
                capture('ai-answer', dialog)
                dialog.copy_button.click()
                pump(.2)
                ai['clipboard'] = QApplication.clipboard().text()

            outcome = with_dialog(lambda: window._completion_action('diagnose', window._open_completion_diagnosis), with_key, 60)
            check('with a key: the answer streams in from the configured AI and fills the window',
                  ai.get('ready') and 'DeepSeek' in ai.get('intro', '') and ai.get('streaming_seen_while_running')
                  and '根本原因' in ai.get('answer', '') and not ai.get('clipped'),
                  dict(ai={k: v for k, v in ai.items() if k != 'clipboard'}, error=outcome.get('error')))
            check('the request carried the catalog, the redacted digest and the local findings; one request, with the key',
                  len(requests) == 1 and all(row['catalog'] and row['digest'] and row['findings'] and row['authorization']
                                             and row['stream'] for row in requests),
                  requests)
            check('复制排查报告 carries the local findings and the AI answer',
                  'fidelity_numbers' in ai.get('clipboard', '') and '根本原因' in ai.get('clipboard', ''),
                  ai.get('clipboard', '')[:400])
            server.shutdown()

            # ---- recognition history ---------------------------------------------------
            history = window.history_page
            hist = {}
            if history is not None:
                window._switch_page(history)
                history.refresh()
                pump(1.5)
                from ..recognition.recognition_history import RecognitionHistoryDetail, parse_recognition_report
                record = parse_recognition_report(Path(delivery['cases'][0]['report_path']))
                detail = RecognitionHistoryDetail(record)
                hist['button'] = detail.diagnose_button.text()
                detail.diagnose_requested.connect(history.diagnose_requested.emit)

                def from_history(dialog):
                    hist['rules'] = [card.finding.rule_id for card in dialog.cards]
                    hist['task_actions'] = sorted({a for card in dialog.cards for a in card.action_buttons} & {'retry', 'recover', 'studio'})
                    capture('history-dialog', dialog)

                outcome = with_dialog(detail.diagnose_button.click, from_history)
                detail.deleteLater()
                hist['error'] = outcome.get('error')
            check('recognition history: 排查原因 opens the same window without the completion-page-only buttons',
                  hist.get('rules', [None])[0] == delivery['cases'][0]['expect_top'] and not hist.get('task_actions'),
                  hist)
            check('no connection left the computer', not _blocked, _blocked)
            result['passed'] = all(item['passed'] for item in result['checks'])
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            save()
            QTimer.singleShot(300, close)

    def close():
        result['gui_shutdown'] = True
        save()
        window.result_exit_code = 0  # the failed tasks shown above are fixtures, not this run
        window.close()
        QApplication.instance().quit()

    QTimer.singleShot(2500, run)
