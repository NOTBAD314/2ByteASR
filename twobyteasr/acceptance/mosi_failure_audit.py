"""Real-window audit: a split MOSS Pro task whose second request waits long and then fails (2026-10-23).

Runs inside the real application (source or frozen EXE) on a private desktop
with an isolated profile (``scripts/verify_mosi_failure_headed.py``). A
loopback MOSI stand-in answers with synthetic content: no key, no network, no
paid call. The frozen app uploads through its own ``--asr-api-worker``.

1. 61+ minutes of audio go to MOSI as three requests of about 20 minutes,
   uploaded in order and with MOSI at the same time (2026-10-23); requests 1
   and 3 succeed, request 2 stays PROCESSING. The step card lists several
   segments at once, then 已返回批次 2 / 3, 当前分段 2 / 3 and 本段已等
   without a warning; then 安全取消.
2. The saved task's submission is moved back 25 minutes and the file is
   started again: the task is resumed without uploading and the card warns
   that the wait is far beyond the usual.
3. The stand-in answers FAILED with a reason: the stored error, the
   completion page, 查看原因与解决办法 and the 重新提交 confirmation name the
   segment, the task id and MOSI's reason, with no progress-event lines. The
   confirmation is declined and nothing is uploaded again.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

REASON = 'task exceeded the processing time limit (stand-in)'
REASON_CODE = 'processing_timeout'


def start_standin():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state = {'posts': [], 'polls': {}, 'fail': False}
    rows = [{'speaker': 'S01', 'text': '大家好，今天继续。', 'start': 1.0, 'end': 2.6},
            {'speaker': 'S01', 'text': '这一段是第一段请求。', 'start': 3.0, 'end': 4.8}]

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
            count = state['polls'][task] = state['polls'].get(task, 0) + 1
            if task in ('seg-1', 'seg-3'):
                # Held until all three requests are uploaded: they are with MOSI at once.
                if count < 3 or len(state['posts']) < 3:
                    return self._send(200, {'id': task, 'status': 'PENDING' if count == 1 else 'PROCESSING', 'retry_after': 2})
                return self._send(200, {'id': task, 'status': 'SUCCESS', 'text': ''.join(r['text'] for r in rows),
                                        'segments': rows})
            if task == 'seg-2':
                if state['fail']:
                    return self._send(200, {'id': task, 'status': 'FAILED',
                                            'error': {'code': REASON_CODE, 'message': REASON}})
                return self._send(200, {'id': task, 'status': 'PENDING' if count == 1 else 'PROCESSING', 'retry_after': 2})
            self._send(404, {'error': {'code': 'task_not_found'}})

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            received = 0
            while received < length:
                block = self.rfile.read(min(1 << 20, length - received))
                if not block:
                    break
                received += len(block)
            task = f'seg-{len(state["posts"]) + 1}'
            state['posts'].append({'task': task, 'bytes': received})
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
    server, standin = start_standin()
    result = dict(passed=False, checks=[], samples=[], screenshots=[], dialogs=[], pid=os.getpid(),
                  executable=sys.executable, build=load_build_identity().to_dict(), delivery=delivery,
                  asr_url=f'http://127.0.0.1:{server.server_port}/v1')
    unexpected, resubmit, shots_taken = [], {}, set()

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

    def sample():
        note = window.stage_note.text() if not window.stage_note_row.isHidden() else ''
        return dict(t=round(time.monotonic() - began, 1), step=window.stage_step_label.text(),
                    action=window.progress_stage.text(), facts=window.stage_metrics.metrics(), note=note)

    def modal_guard():
        modal = QApplication.activeModalWidget()
        if not isinstance(modal, QMessageBox):
            return
        text = modal.windowTitle() + ' | ' + modal.text() + ' ' + modal.informativeText()
        result['dialogs'].append(text)
        if '重新提交' in modal.windowTitle():
            # Seen, then declined: this audit never uploads again.
            resubmit['text'] = modal.text()
            shot('resubmit-confirmation', modal)
            next(b for b in modal.buttons() if modal.buttonRole(b) == QMessageBox.ButtonRole.RejectRole).click()
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
                    result.setdefault('closed_dialogs', []).append(
                        [label.text() for label in dialog.findChildren(QLabel) if label.text().strip()])
                dialog.close()
        pump(.5)

    def run_until(condition, seconds, label):
        end = time.monotonic() + seconds
        last = None
        while time.monotonic() < end:
            pump(.25)
            current = sample()
            if current != last and current['facts']:
                result['samples'].append(dict(current, run=label))
                last = dict(current)
                if ', ' in dict(current['facts']).get('当前分段', '') and 'several-segments-at-once' not in shots_taken:
                    shots_taken.add('several-segments-at-once')
                    shot('several-segments-at-once')
            if condition(current):
                return current
            if unexpected:
                raise AssertionError('unexpected dialog: ' + unexpected[-1])
        raise AssertionError(f'{label}: timed out')

    def wait_idle(seconds=120):
        end = time.monotonic() + seconds
        while (getattr(window, '_run_in_progress', False) or (window.worker is not None and window.worker.isRunning())) \
                and time.monotonic() < end:
            pump(.25)
        pump(1.0)

    def start_run():
        window._return_to_settings()
        pump(.5)
        end = time.monotonic() + 40
        while not window.start_button.isEnabled() and time.monotonic() < end:
            pump()
        QTest.mouseClick(window.start_button, Qt.LeftButton)
        pump(.3)
        check(f'recognition started ({len(standin["posts"])} uploads so far)', window.worker is not None)

    guard = QTimer(window)
    began = time.monotonic()

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

            # ---- 1. request 2 waits: segment and wait shown, no warning yet ----
            start_run()

            def second_waiting(s):
                facts = dict(s['facts'])
                return facts.get('当前分段') == '2 / 3' and facts.get('本段已等', '') >= '00:06'
            current = run_until(second_waiting, 900, 'first')
            shot('segment-2-waiting')
            facts = dict(current['facts'])
            several = [dict(s['facts']).get('当前分段') for s in result['samples'] if ', ' in dict(s['facts']).get('当前分段', '')]
            result['several_at_once'] = several[:5]
            check('first run: several segments were with MOSI at once', bool(several), several[:5])
            check('first run: segment 2 of 3 and its wait are shown, no warning',
                  facts.get('云端阶段') in {'排队中', '云端识别中'} and facts.get('已返回批次') == '2 / 3'
                  and not current['note'], current)
            check('first run: three requests uploaded once, in order',
                  [p['task'] for p in standin['posts']] == ['seg-1', 'seg-2', 'seg-3'], standin['posts'])
            QTest.mouseClick(window.cancel_run_button, Qt.LeftButton)
            wait_idle()
            close_dialogs('first-run-ended')

            # ---- 2. the saved task waited 25 minutes: resumed, warned ----
            from ..runtime_paths import user_data_root
            saved = [p for p in (Path(user_data_root()) / 'cache' / 'asr-jobs').rglob('request-*/task.json')
                     if json.loads(p.read_text('utf8')).get('task_id') == 'seg-2']
            check('request 2 task saved for resuming', len(saved) == 1, [str(p) for p in saved])
            state = json.loads(saved[0].read_text('utf8'))
            result['saved_state_after_cancel'] = {k: state.get(k) for k in ('task_id', 'status', 'local_cancel_requested')}
            check('cancel kept the task id', state.get('task_id') == 'seg-2' and state.get('status') in {'PENDING', 'PROCESSING'},
                  result['saved_state_after_cancel'])
            state['submitted_at'] = float(state['submitted_at']) - 25 * 60
            saved[0].write_text(json.dumps(state, ensure_ascii=False), 'utf8')
            start_run()
            current = run_until(lambda s: bool(s['note']) and dict(s['facts']).get('当前分段') == '2 / 3', 600, 'second')
            shot('overdue-note')
            facts = dict(current['facts'])
            check('second run: the long wait is counted from the original submission',
                  facts.get('本段已等', '') >= '25:00' and current['note'].startswith('这一段在云端已等 2'), current)
            window.stage_note_more.click()
            pump(.6)
            detail = window.stage_note_detail.text()
            result['note_detail'] = detail
            shot('overdue-note-detail')
            check('the note explains waiting and safe cancel',
                  window.stage_note_detail.isVisible() and '不会重新上传或重复计费' in detail, detail)
            check('second run resumed without uploading', len(standin['posts']) == 3, standin['posts'])

            # ---- 3. MOSI fails the request: reason everywhere, no event lines ----
            standin['fail'] = True
            wait_idle(300)
            close_dialogs('completion-notice')
            window._switch_page(2)
            pump(1.0)
            shot('completion-page')
            tasks = getattr(window, '_completion_tasks', [])
            check('the task failed', len(tasks) == 1 and tasks[0][0].status == 'failed')
            error = str(tasks[0][0].error)
            result['stored_error'] = error
            reason_text = f'MOSI 返回的原因：{REASON}（{REASON_CODE}）'
            check('stored error names segment, task id and MOSI reason',
                  '第 2 / 3 段' in error and '任务编号 seg-2' in error and reason_text in error, error[:400])
            check('stored error carries no progress-event lines', '[2BYTEASR_API] ' not in error and 'cue_delta' not in error)
            shown = [label.text() for label in window.findChildren(QLabel) if label.isVisible() and 'MOSI' in label.text()]
            result['completion_labels'] = shown
            check('the completion page shows the reason', any(reason_text in text for text in shown), shown)

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
                    if getattr(card, 'evidence_toggle', None) is not None:
                        card.evidence_toggle.click()
                        pump(.4)
                    seen['evidence'] = card.evidence_label.text() if card.evidence_label is not None else ''
                    shot('diagnosis-window', dialog)
                except Exception:
                    box['error'] = traceback.format_exc()
                finally:
                    if dialog.isVisible():
                        dialog.reject()
            box['deadline'] = time.monotonic() + 20
            QTimer.singleShot(150, inside)
            window._completion_action('diagnose', window._open_completion_diagnosis)
            pump(.5)
            result['diagnosis'] = dict(seen, error=box.get('error'))
            check('查看原因 names the resubmit cause with the MOSI reason as evidence',
                  seen.get('rules', [None])[0] == 'cloud_asr_resubmit' and reason_text in seen.get('evidence', ''),
                  result['diagnosis'])

            QTimer.singleShot(0, window._retry_failed_items)
            end = time.monotonic() + 20
            while 'text' not in resubmit and time.monotonic() < end:
                pump(.2)
            pump(1.0)
            result['resubmit_dialog'] = resubmit.get('text', '')
            check('the 重新提交 confirmation quotes the reason', reason_text in resubmit.get('text', ''), resubmit)
            check('declining uploads nothing', len(standin['posts']) == 3 and not getattr(window, '_run_in_progress', False))
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
        window.result_exit_code = 0  # the failed task above is the scenario, not this run
        window.close()
        QApplication.instance().quit()

    QTimer.singleShot(2500, run)
