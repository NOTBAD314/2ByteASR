"""Real-window audit: MOSS Pro returns sentences timed outside a request's audio (2026-10-25).

User report (0.8.4, an English singing stream): ``MOSS Pro 句段时间越出提交的音频``
every time. One sentence past the request's audio failed the whole task, and
every new start read the same finished MOSI task and failed again.

Runs inside the real application (source or frozen EXE) on a private desktop
with an isolated profile (``scripts/verify_mosi_failure_headed.py --scenario
mosi-timing``). A loopback MOSI stand-in answers with synthetic content: no
key, no network, no paid call.

1. 61+ minutes of audio go to MOSI as three requests. Request 1 ends with a
   long run-on line that runs 40 s past its audio; request 2 has a line after
   its audio and one with start and end swapped. The task finishes: the
   run-on line is cut at the end of request 1, the other two are not in the
   subtitles, and no subtitle runs past the media.
2. 查看原因 shows 「MOSS Pro 有几句时间超出上传的音频，已截短或去掉」 with the parts and
   counts, as "affects quality" (sentences were left out).
3. Starting the file again from the home page uploads nothing.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

RUN_ON = ' '.join(['la la la, singing for you'] * 8)
AFTER = 'THIS LINE COMES AFTER THE AUDIO'
SWAPPED = 'THIS LINE HAS ITS TIMES SWAPPED'


def start_standin():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state = {'posts': [], 'polls': {}}
    rows = [{'speaker': 'S01', 'text': 'Hello everyone, welcome back.', 'start': 1.0, 'end': 2.6},
            {'speaker': 'S01', 'text': 'This part came back fine.', 'start': 3.0, 'end': 4.8}]

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
            post = next((post for post in state['posts'] if post['task'] == task), None)
            if post is None:
                return self._send(404, {'error': {'code': 'task_not_found'}})
            count = state['polls'][task] = state['polls'].get(task, 0) + 1
            if count < 2:
                return self._send(200, {'id': task, 'status': 'PENDING', 'retry_after': 2})
            seconds = post['seconds']
            segments = rows + [{'speaker': 'S01', 'text': 'This part is over.', 'start': seconds - 12.0,
                                'end': seconds - 9.0}]
            if task == 'seg-1':
                segments.append({'speaker': 'S01', 'text': RUN_ON, 'start': seconds - 4.0, 'end': seconds + 40.0})
            if task == 'seg-2':
                segments += [{'speaker': 'S01', 'text': SWAPPED, 'start': 9.0, 'end': 7.0},
                             {'speaker': 'S01', 'text': AFTER, 'start': seconds + 5.0, 'end': seconds + 9.0}]
            self._send(200, {'id': task, 'status': 'SUCCESS', 'text': ' '.join(r['text'] for r in segments),
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
    server, standin = start_standin()
    result = dict(passed=False, checks=[], screenshots=[], dialogs=[], pid=os.getpid(),
                  executable=sys.executable, build=load_build_identity().to_dict(), delivery=delivery,
                  asr_url=f'http://127.0.0.1:{server.server_port}/v1')
    unexpected = []

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
        repaired = [row for row in report.get('events') or () if row.get('event') == 'cloud_asr_timing_repaired']
        return item, repaired, list(getattr(project, 'cues', None) or ())

    def diagnosis(label, rule):
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
                card = next((card for card in dialog.cards if card.finding.rule_id == rule), None)
                if card is not None:
                    seen['title'] = card.title_label.text()
                    seen['specific'] = card.specific_label.text() if card.specific_label is not None else ''
                    seen['severity'] = card.finding.severity
                    seen['actions'] = list(card.action_buttons)
                shot(f'{label}-diagnosis', dialog)
            except Exception:
                box['error'] = traceback.format_exc()
            if dialog.isVisible():
                dialog.reject()
        box['deadline'] = time.monotonic() + 20
        QTimer.singleShot(150, inside)
        window._completion_action('diagnose', window._open_completion_diagnosis)
        pump(.5)
        end = time.monotonic() + 20
        while 'rules' not in seen and 'error' not in box and time.monotonic() < end:
            pump(.2)
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

            # ---- 1. odd times are clipped or left out; the task finishes ----
            start_run()
            wait_idle(1800)
            item, repaired, cues = completion('first-run')
            posts = standin['posts']
            check('three requests uploaded once, in order', [p['task'] for p in posts] == ['seg-1', 'seg-2', 'seg-3'],
                  posts)
            result['repair_events'] = repaired
            by_part = {tuple(row.get('segment') or ()): row for row in repaired}
            first, second = by_part.get((1, 3), {}), by_part.get((2, 3), {})
            check('the report records request 1: the run-on line clipped',
                  first.get('clipped') == 1 and first.get('outside', 0) + first.get('reversed', 0) == 0, first)
            check('the report records request 2: one line after the audio, one swapped',
                  second.get('outside') == 1 and second.get('reversed') == 1 and second.get('clipped') == 0, second)
            check('request 3 needed no change', (3, 3) not in by_part, sorted(by_part))
            media_end_ms = float(delivery['minutes']) * 60 * 1000
            cut = (first.get('end') or 0) * 1000
            texts = ' '.join(cue.text for cue in cues)
            ordered = sorted(cues, key=lambda cue: cue.start_ms)
            run_on = [cue for cue in ordered if 'singing for you' in cue.text]
            after = [cue for cue in ordered if run_on and cue.start_ms >= run_on[-1].end_ms - 1]
            result['cues'] = dict(total=len(cues), run_on=[(cue.start_ms, cue.end_ms, cue.text[:60]) for cue in run_on],
                                  next_start_ms=after[0].start_ms if after else None,
                                  last_end_ms=max((cue.end_ms for cue in cues), default=0), request_1_end_ms=cut)
            # Cut at request 1's end (MOSI said 40 s later). The last subtitle may
            # then close the small gap to the next one, never overlap it.
            check('the run-on line is kept at the end of request 1, not run on into request 2',
                  run_on and all(cut - 4500 <= cue.start_ms and cue.end_ms <= cut + 2000 for cue in run_on)
                  and after and run_on[-1].end_ms <= after[0].start_ms + 1, result['cues'])
            check('the lines outside the audio or swapped are not in the subtitles',
                  AFTER.lower() not in texts.lower() and SWAPPED.lower() not in texts.lower())
            check('no subtitle runs past the media', all(cue.end_ms <= media_end_ms + 1 for cue in cues),
                  result['cues']['last_end_ms'])
            check('the rest has subtitles', len(cues) >= 9, len(cues))
            shown = [label.text() for label in window.findChildren(QLabel)
                     if label.isVisible() and '超出上传的音频' in label.text()]
            result['completion_labels'] = shown

            # ---- 2. 查看原因 names the parts and counts ----
            seen = diagnosis('first-run', 'cloud_asr_timing_repaired')
            specific = seen.get('specific', '')
            check('查看原因 shows the clipped / left-out sentences as affecting quality',
                  seen.get('title') == 'MOSS Pro 有几句时间超出上传的音频，已截短或去掉' and seen.get('severity') == 'quality'
                  and specific.startswith('所在的段：') and '1 句结尾超出上传的音频' in specific
                  and '2 句的时间不在这段音频里' in specific and seen.get('actions') == ['studio'], seen)
            check('no failure reason is shown', 'cloud_asr_failed' not in (seen.get('rules') or [])
                  and 'cloud_asr_timing_rejected' not in (seen.get('rules') or []), seen.get('rules'))

            # ---- 3. again from the home page: nothing uploaded ----
            start_run()
            wait_idle(1800)
            item, repaired, cues_again = completion('second-run')
            check('starting again uploads nothing', len(standin['posts']) == 3, standin['posts'])
            check('the same subtitles again', [cue.text for cue in cues_again] == [cue.text for cue in cues],
                  (len(cues_again), len(cues)))
            result['passed'] = all(row['passed'] for row in result['checks'])
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
