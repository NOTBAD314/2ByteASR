"""Real-window audit: MOSI's content safety review stops one request of a split MOSS Pro task (2026-10-24).

User report (0.8.4): the 2nd of 5 requests of an English game stream ended
FAILED with MOSI's {"error_code": 17001, "error_msg": "safety policy error",
"internal_error_code": 111111004, "internal_error_msg": "safety guardrail
blocked"}. The task failed, the rest was never sent, and the window advised
重试失败项, which uploads the same audio unchanged.

Runs inside the real application (source or frozen EXE) on a private desktop
with an isolated profile (``scripts/verify_mosi_failure_headed.py --scenario
mosi-blocked [--fill-model sensevoice --main-runtime <python>]``). A loopback
MOSI stand-in answers with synthetic content: no key, no network, no paid call.

1. 61+ minutes of audio go to MOSI as three requests; request 2 comes back
   FAILED with the user's error. The task still finishes: all three requests
   were sent once, the completion page names the gap, and 查看原因 leads with
   it — filled by the real local SenseVoice (``fill_model``) or left empty
   (no local model) — with 切成小段再交 MOSI… as the second button.
2. 切成小段再交 MOSI… asks first (blocked minutes, cost, uncertain outcome,
   取消 the default); declined, nothing is uploaded.
3. Accepted: only request 2 goes again, as pieces of about 3 minutes; the
   stand-in stops the second piece again. The task finishes with that piece
   as the only gap, and no further 切成小段 is offered.
4. Starting the file again from the home page uploads nothing.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

ERROR = {'error_code': 17001, 'error_msg': 'safety policy error', 'internal_error_code': 111111004,
         'internal_error_msg': 'safety guardrail blocked'}
REASON = 'safety policy error；safety guardrail blocked（17001，111111004）'
# Uploads the stand-in stops: request 2, then the second piece of it.
# Pieces are about 3 minutes; each cut moves up to 30 s to a quiet second.
BLOCKED = {'seg-2', 'seg-5'}


def start_standin():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state = {'posts': [], 'polls': {}}
    rows = [{'speaker': 'S01', 'text': '大家好，今天继续。', 'start': 1.0, 'end': 2.6},
            {'speaker': 'S01', 'text': '这一段识别成功了。', 'start': 3.0, 'end': 4.8}]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/v1/models':
                return self._send(200, {'object': 'list', 'data': [{'id': 'moss-transcribe-diarize-pro'}]})
            if not self.path.startswith('/v1/audio/tasks/'):
                return self._send(404, {'error': {'code': 'not_found'}})
            task = self.path.rsplit('/', 1)[-1]
            if task not in {post['task'] for post in state['posts']}:
                return self._send(404, {'error': {'code': 'task_not_found'}})
            count = state['polls'][task] = state['polls'].get(task, 0) + 1
            # The first three are held until all three are uploaded: with MOSI at once.
            if count < 3 or len(state['posts']) < 3:
                return self._send(200, {'id': task, 'status': 'PENDING' if count == 1 else 'PROCESSING', 'retry_after': 2})
            if task in BLOCKED:
                return self._send(200, {'id': task, 'status': 'FAILED', 'error': ERROR})
            # A closing sentence near the request's end, so a finished request
            # covers its audio like MOSI's real answers do.
            seconds = next(post['seconds'] for post in state['posts'] if post['task'] == task)
            segments = rows + [{'speaker': 'S01', 'text': '这一段说完了。', 'start': max(5.0, seconds - 3.0),
                                'end': max(6.0, seconds - 1.0)}]
            self._send(200, {'id': task, 'status': 'SUCCESS', 'text': ''.join(r['text'] for r in segments),
                             'segments': segments})

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            received = 0
            while received < length:
                block = self.rfile.read(min(1 << 20, length - received))
                if not block:
                    break
                received += len(block)
            task = f'seg-{len(state["posts"]) + 1}'
            state['posts'].append({'task': task, 'bytes': received, 'seconds': round((received - 1000) / 32000, 1)})
            self._send(200, {'id': task, 'task_id': task, 'status': 'PENDING', 'retry_after': 2})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name='mosi-standin').start()
    return server, state


def start(window, out):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox
    from ..diagnostics.build_identity import load_build_identity

    out = Path(out)
    delivery = json.loads((out / 'delivery.json').read_text('utf8'))
    fill_model = str(delivery.get('fill_model') or '')
    filled = bool(fill_model)
    server, standin = start_standin()
    result = dict(passed=False, checks=[], screenshots=[], dialogs=[], pid=os.getpid(), fill_model=fill_model,
                  executable=sys.executable, build=load_build_identity().to_dict(), delivery=delivery,
                  asr_url=f'http://127.0.0.1:{server.server_port}/v1')
    unexpected, resplit = [], {'accept': False, 'seen': []}

    def save():
        result['standin'] = standin
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        save()
        if not ok:
            raise AssertionError(name)

    def pump(seconds=.05):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(.005)

    def shot(name, widget=None):
        path = out / f'{len(result["screenshots"]) + 1:02d}-{name}.png'
        (widget or window).grab().save(str(path))
        result['screenshots'].append(path.name)

    def modal_guard():
        modal = QApplication.activeModalWidget()
        if not isinstance(modal, QMessageBox):
            return
        text = modal.windowTitle() + ' | ' + modal.text() + ' ' + modal.informativeText()
        result['dialogs'].append(text)
        if modal.windowTitle() == '切成小段再交 MOSI？':
            default = modal.defaultButton()
            resplit['seen'].append(dict(text=modal.text(), buttons=[b.text() for b in modal.buttons()],
                                        default=default.text() if default is not None else ''))
            shot(f'resplit-confirmation-{len(resplit["seen"])}', modal)
            role = QMessageBox.ButtonRole.AcceptRole if resplit['accept'] else QMessageBox.ButtonRole.RejectRole
            next(b for b in modal.buttons() if modal.buttonRole(b) == role).click()
            return
        accept = next((b for b in modal.buttons() if modal.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole), None)
        if accept is not None and '上传' in text:
            accept.click()
            return
        unexpected.append(text)
        modal.reject()

    def close_dialogs(name=None):
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog, QDialog) and dialog.isVisible():
                if name:
                    shot(name, dialog)
                dialog.close()
        pump(.5)

    def wait_idle(seconds):
        end = time.monotonic() + seconds
        while (getattr(window, '_run_in_progress', False) or (window.worker is not None and window.worker.isRunning())) \
                and time.monotonic() < end:
            pump(.25)
            if unexpected:
                raise AssertionError('unexpected dialog: ' + unexpected[-1])
        pump(1.0)

    def wait_started(seconds=60):
        end = time.monotonic() + seconds
        while not getattr(window, '_run_in_progress', False) and time.monotonic() < end:
            pump(.2)

    def start_run():
        window._return_to_settings()
        pump(.5)
        end = time.monotonic() + 40
        while not window.start_button.isEnabled() and time.monotonic() < end:
            pump()
        QTest.mouseClick(window.start_button, Qt.LeftButton)
        pump(.3)
        check(f'recognition started ({len(standin["posts"])} uploads so far)', window.worker is not None)

    def completion(label):
        close_dialogs(f'{label}-notice')
        window._switch_page(2)
        pump(1.0)
        shot(f'{label}-completion-page')
        tasks = getattr(window, '_completion_tasks', [])
        check(f'{label}: the task finished', len(tasks) == 1 and tasks[0][0].status in {'success', 'degraded_success'},
              [(item.status, str(item.error)[:300]) for item, _ in tasks])
        item, project = tasks[0]
        evidence = window._completion_task_evidence.get(window._completion_task_key(item), {})
        window._completion_diagnosis(item, evidence)
        report = evidence.get('diagnosis_report') or {}
        gap_events = [row for row in report.get('events') or () if row.get('event') == 'cloud_asr_gap_fill']
        cues = list(getattr(project, 'cues', None) or ())
        return item, gap_events[-1] if gap_events else {}, cues

    def diagnosis(label, *, click=None):
        seen, box = {}, {}

        def inside():
            dialog = getattr(window, '_run_diagnosis_dialog', None)
            if dialog is None or not dialog.isVisible():
                if time.monotonic() < box['deadline']:
                    QTimer.singleShot(100, inside)
                return
            try:
                pump(.6)
                seen['rules'] = [card.finding.rule_id for card in dialog.cards]
                card = dialog.cards[0]
                seen['title'] = card.title_label.text()
                seen['specific'] = card.specific_label.text() if card.specific_label is not None else ''
                seen['actions'] = list(card.action_buttons)
                seen['buttons'] = [button.text() for button in card.action_buttons.values()]
                shot(f'{label}-diagnosis', dialog)
                if click and click in card.action_buttons:
                    card.action_buttons[click].click()
                    return
            except Exception:
                box['error'] = traceback.format_exc()
            if dialog.isVisible():
                dialog.reject()
        box['deadline'] = time.monotonic() + 20
        QTimer.singleShot(150, inside)
        window._completion_action('diagnose', window._open_completion_diagnosis)
        pump(.5)
        result[f'{label}_diagnosis'] = dict(seen, error=box.get('error'))
        return seen

    guard = QTimer(window)

    def run():
        try:
            guard.timeout.connect(modal_guard)
            guard.start(200)
            window.showNormal()
            window.resize(1440, 900)
            window._return_to_settings()
            pump(.5)
            index = window.qwen_asr_api_provider.findData('mosi_moss_pro')
            check('MOSS Pro cloud provider available', index >= 0)
            window.qwen_asr_api_provider.setCurrentIndex(index)
            window.qwen_asr_api_model.setText('moss-transcribe-diarize-pro')
            window.qwen_asr_api_url.setText(result['asr_url'])
            window.qwen_asr_api_key.setText('sk-loopback-test')
            for name, value in dict(primary_asr_backend='api', qwen_asr_backend='off', firered_asr_backend='off').items():
                combo = getattr(window, name)
                position = combo.findData(value)
                check('available ' + name, position >= 0)
                combo.setCurrentIndex(position)
            window.ai_polish.setChecked(False)
            window.ai_grouping.setChecked(False)
            window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] = []
            window.legacy.RUNTIME_SETTINGS['models']['speaker_source'] = 'single'
            check('save cloud ASR configuration', window._save_asr_configuration(show_feedback=False))
            source = str(Path(delivery['media']).resolve())
            window.import_media([source], replace=True)
            end = time.monotonic() + 60
            while not (window.media_paths == [source] and window.start_button.isEnabled()) and time.monotonic() < end:
                pump()
            check('media imported', window.media_paths == [source])

            # ---- 1. request 2 is stopped; the task still finishes ----
            start_run()
            wait_idle(1800)
            item, gap, cues = completion('first-run')
            check('three requests uploaded once, in order',
                  [p['task'] for p in standin['posts']] == ['seg-1', 'seg-2', 'seg-3'], standin['posts'])
            result['first_gap_event'] = gap
            ranges = gap.get('ranges') or []
            check('the report has the gap of request 2 (about 20 minutes)',
                  len(ranges) == 1 and 1000 < ranges[0][0] < 1400 and 2200 < ranges[0][1] < 2600
                  and gap.get('resplittable') is True, gap)
            inside_gap = [cue for cue in cues if ranges and ranges[0][0] <= cue.start_ms / 1000 < ranges[0][1]]
            result['first_run_cues'] = dict(total=len(cues), in_gap=len(inside_gap),
                                            sample=[cue.text for cue in inside_gap[:5]])
            if filled:
                check('the gap is filled by the local SenseVoice', gap.get('filled') is True
                      and gap.get('backend') == 'sensevoice' and gap.get('rows', 0) > 0 and inside_gap, result['first_run_cues'])
            else:
                check('without a local model the gap stays empty', gap.get('filled') is False
                      and gap.get('reason') == 'no_local_model' and not inside_gap, result['first_run_cues'])
            check('the rest has subtitles', len(cues) - len(inside_gap) >= 4, len(cues))
            shown = [label.text() for label in window.findChildren(QLabel) if label.isVisible() and '拦下' in label.text()]
            result['completion_labels'] = shown
            expected = ('有一段被在线识别的内容审查拦下，已用本地模型补上' if filled
                        else '有一段被在线识别的内容审查拦下，这一段没有字幕')
            check('the completion page names the gap', any(expected in text for text in shown), shown)

            # ---- 2. 查看原因, then 切成小段再交 MOSI…, declined ----
            seen = diagnosis('first-run', click='mosi_resplit')
            first_button = 'studio' if filled else 'model_workshop'
            check('查看原因 leads with the gap, re-split is the second button',
                  (seen.get('rules') or [None])[0] == ('cloud_asr_gap_filled' if filled else 'cloud_asr_gap_unfilled')
                  and seen.get('actions') == [first_button, 'mosi_resplit'] and '被拦下的时间：' in seen.get('specific', ''),
                  seen)
            end = time.monotonic() + 20
            while not resplit['seen'] and time.monotonic() < end:
                pump(.2)
            pump(1.0)
            asked = resplit['seen'][0] if resplit['seen'] else {}
            result['resplit_dialog'] = asked
            check('the re-split confirmation states minutes, cost and uncertainty, 取消 by default',
                  '被内容审查拦下的 1 段' in asked.get('text', '') and '约 3 分钟' in asked.get('text', '')
                  and '会再次计费' in asked.get('text', '') and '能不能通过不确定' in asked.get('text', '')
                  and asked.get('default') == '取消', asked)
            check('declining uploads nothing', len(standin['posts']) == 3 and not getattr(window, '_run_in_progress', False))

            # ---- 3. accepted: only request 2 goes again, in pieces ----
            resplit['accept'] = True
            QTimer.singleShot(0, window._resplit_blocked_cloud_segments)
            wait_started()
            wait_idle(1800)
            item, gap, cues = completion('resplit-run')
            pieces = standin['posts'][3:]
            result['pieces'] = pieces
            check('request 2 went again as pieces of about 3 minutes, nothing else',
                  len(pieces) == 7 and all(140 <= piece['seconds'] <= 215 for piece in pieces), pieces)
            ranges = gap.get('ranges') or []
            result['resplit_gap_event'] = gap
            check('only the stopped piece is a gap now', len(ranges) == 1 and 140 <= ranges[0][1] - ranges[0][0] <= 215
                  and gap.get('resplittable') is False, gap)
            if filled:
                check('the piece is filled locally again', gap.get('filled') is True, gap)
            seen = diagnosis('resplit-run')
            check('no further 切成小段 is offered',
                  'mosi_resplit' not in (seen.get('actions') or []) and not window._cloud_gap_resplit(item), seen)

            # ---- 4. again from the home page: nothing uploaded ----
            start_run()
            wait_idle(1800)
            item, gap, cues = completion('third-run')
            check('the third run uploads nothing and keeps the same gap',
                  len(standin['posts']) == 10 and gap.get('ranges') == ranges, dict(posts=len(standin['posts']), gap=gap))
            result['passed'] = all(item['passed'] for item in result['checks'])
        except Exception:
            result['error'] = traceback.format_exc()
            try:
                shot('failure')
            except Exception:
                pass
        finally:
            guard.stop()
            result['unexpected_dialogs'] = unexpected
            server.shutdown()
            save()
            QTimer.singleShot(300, close)

    def close():
        result['gui_shutdown'] = True
        save()
        window.result_exit_code = 0
        window.close()
        QApplication.instance().quit()

    QTimer.singleShot(2500, run)
