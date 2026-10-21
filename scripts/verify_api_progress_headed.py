"""Live progress and token usage of online API steps in the real window (2026-10-15).

Runs one Home recognition in an isolated profile on a private desktop:

* MOSS Pro cloud recognition (upload -> queue -> processing -> result), served
  by a loopback stand-in that reads the upload slowly and answers several polls;
* AI proofreading and AI segmentation through an OpenAI-compatible endpoint
  served by a loopback stand-in that streams its answers slowly, reports usage
  numbers and rate-limits one proofreading request once.

Both stand-ins return synthetic content and synthetic usage on 127.0.0.1: no
key, no network, no paid call. While each API step runs the driver samples the
step card's facts, the newest-text preview and screenshots, then compares the
task report's usage with what the stand-in sent.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


# ---------------------------------------------------------------- stand-ins

def start_asr_standin(segments, *, polls=('PENDING', 'PENDING', 'PROCESSING', 'PROCESSING', 'SUCCESS')):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state = {'uploads': [], 'polls': 0}

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
            if self.path.startswith('/v1/audio/tasks/'):
                status = polls[min(state['polls'], len(polls) - 1)]
                state['polls'] += 1
                if status != 'SUCCESS':
                    return self._send(200, {'id': 'loop', 'status': status, 'retry_after': 2})
                return self._send(200, {'id': 'loop', 'status': 'SUCCESS',
                                        'text': ''.join(s['text'] for s in segments), 'segments': segments})
            self._send(404, {'error': {'code': 'not_found'}})

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            received = 0
            while received < length:  # a slow uplink: the app's upload progress has something to show
                block = self.rfile.read(min(65536, length - received))
                if not block:
                    break
                received += len(block)
                time.sleep(.03)
            state['uploads'].append({'bytes': received})
            self._send(200, {'id': 'loop', 'task_id': 'loop', 'status': 'PENDING', 'retry_after': 2})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name='asr-standin').start()
    return server, state


def start_chat_standin():
    """OpenAI-compatible chat completions: valid no-edit proofreading, segmentation at the
    source boundaries, slow streams, synthetic usage, one 429 on the second proofreading call."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    state = {'requests': [], 'sent_usage': {}, 'rate_limited': 0}
    lock = threading.Lock()

    def answer(body):
        request = None
        # The first user message carries the request; a repair retry appends plain text after it.
        for message in body.get('messages') or []:
            if message.get('role') != 'user':
                continue
            try:
                request = json.loads(message.get('content'))
                break
            except (TypeError, ValueError):
                continue
        if request is None:
            return 'other', '2ByteASR_OK'
        if isinstance(request, dict) and isinstance(request.get('cues'), list):
            ids = [cue['id'] for cue in request['cues']]
            return 'polish', json.dumps({'checked_ids': ids, 'cues': [{'id': i, 'edits': []} for i in ids],
                                         'suspect_results': []}, ensure_ascii=False)
        if isinstance(request, dict) and 'source_segment_offsets' in request:
            total = int(request.get('total_length') or 0)
            offsets = set(request['source_segment_offsets']) | set(request.get('hard_break_character_offsets') or ())
            return 'group', json.dumps({'boundaries': sorted(o for o in offsets if 0 < o < total)})
        return 'other', '{}'

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def _json(self, code, payload, extra=()):
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            for key, value in extra:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.endswith('/models'):
                return self._json(200, {'object': 'list', 'data': [{'id': 'loopback-chat'}]})
            self._json(404, {'error': {'message': 'not found'}})

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            body = json.loads(raw)
            kind, content = answer(body)
            with lock:
                index = len(state['requests'])
                polish_seen = sum(row['kind'] == 'polish' for row in state['requests'])
                limited = kind == 'polish' and polish_seen == 1 and not state['rate_limited']
                state['rate_limited'] += int(limited)
                state['requests'].append({'kind': kind, 'stream': bool(body.get('stream')),
                                          'stream_options': body.get('stream_options'), 'status': 429 if limited else 200})
            if limited:
                return self._json(429, {'error': {'message': 'rate limited (stand-in)', 'type': 'rate_limit'}},
                                  (('Retry-After', '1'),))
            prompt = max(1, len(raw) // 4)
            usage = {'prompt_tokens': prompt, 'completion_tokens': len(content) // 3 + 5,
                     'prompt_tokens_details': {'cached_tokens': prompt // 2 if index >= 2 else 0}}
            usage['total_tokens'] = usage['prompt_tokens'] + usage['completion_tokens']
            send_usage = not body.get('stream') or bool((body.get('stream_options') or {}).get('include_usage'))
            if send_usage:
                with lock:
                    tally = state['sent_usage'].setdefault(kind, {'calls': 0, 'input': 0, 'output': 0, 'cached': 0})
                    tally['calls'] += 1
                    tally['input'] += usage['prompt_tokens']
                    tally['output'] += usage['completion_tokens']
                    tally['cached'] += usage['prompt_tokens_details']['cached_tokens']
            delay = 1.2 + 1.3 * (index % 3)
            if not body.get('stream'):
                time.sleep(delay)
                return self._json(200, {'id': f'r{index}', 'model': 'loopback-chat', 'choices': [
                    {'index': 0, 'message': {'role': 'assistant', 'content': content}, 'finish_reason': 'stop'}],
                    **({'usage': usage} if send_usage else {})})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()

            def event(packet):
                self.wfile.write(('data: ' + json.dumps(packet, ensure_ascii=False) + '\n\n').encode('utf-8'))
                self.wfile.flush()
            pieces = [content[i:i + max(1, len(content) // 4)] for i in range(0, len(content), max(1, len(content) // 4))]
            for piece in pieces:
                time.sleep(delay / max(1, len(pieces)))
                event({'id': f'r{index}', 'model': 'loopback-chat',
                       'choices': [{'index': 0, 'delta': {'content': piece}, 'finish_reason': None}]})
            event({'id': f'r{index}', 'model': 'loopback-chat', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})
            if send_usage:
                event({'id': f'r{index}', 'model': 'loopback-chat', 'choices': [], 'usage': usage})
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
            self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name='chat-standin').start()
    return server, state


# ---------------------------------------------------------------- outer

def build_media(output: Path, repeat: int):
    """Synthetic speech repeated ``repeat`` times, so proofreading has several batches."""
    from timing_benchmark import build_synthetic
    reference = json.loads(build_synthetic(output / 'synthetic').read_text(encoding='utf-8'))
    ffmpeg = ROOT / 'tools' / 'ffmpeg' / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    duration = float(reference['duration_s'])
    segments = []
    for copy in range(repeat):
        for row in reference['utterances']:
            segments.append({'speaker': 'S01', 'text': row['text'], 'start': round(row['start_s'] + copy * duration, 3),
                             'end': round(row['end_s'] + copy * duration, 3)})
    media = output / 'api-progress-test.mp4'
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x2b3a4a:s=640x360:r=30',
                    '-stream_loop', str(repeat - 1), '-i', reference['audio'], '-shortest', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', str(media)], check=True)
    (output / 'segments.json').write_text(json.dumps(segments, ensure_ascii=False, indent=1), encoding='utf-8')
    return media


def outer(args) -> int:
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    output.mkdir(parents=True)
    build_media(output, args.repeat)
    env = os.environ.copy()
    for key in [key for key in env if key.startswith('TWOBYTEASR_STARTUP_')]:
        env.pop(key)
    env.update(TWOBYTEASR_TEST_ROOT=str(output), QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale,
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1', CUDA_VISIBLE_DEVICES='-1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', NO_PROXY='127.0.0.1,localhost',
               HTTP_PROXY='', HTTPS_PROXY='', http_proxy='', https_proxy='')
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--inner', '--output', str(output)]
    if args.language:
        command += ['--language', args.language]
    started = time.monotonic()
    if args.visible:
        code = subprocess.run(command, cwd=ROOT, env=env, timeout=1500).returncode
    else:
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=1500)
    try:
        result = json.loads((output / 'result.json').read_text('utf8'))
    except (OSError, ValueError):
        result = {}
    result.update(launcher_exit=code, wall_s=round(time.monotonic() - started, 1))
    result['passed'] = bool(result.get('passed') and code == 0)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({k: result.get(k) for k in ('passed', 'task_status', 'launcher_exit', 'wall_s', 'error',
                                                 'checks', 'screenshots')}, ensure_ascii=False, indent=1), flush=True)
    return 0 if result['passed'] else 1


# ---------------------------------------------------------------- inner

def inner(args) -> int:
    output = args.output.resolve()
    from twobyteasr.test_isolation import install
    install()
    segments = json.loads((output / 'segments.json').read_text(encoding='utf-8'))
    asr_server, asr_state = start_asr_standin(segments)
    chat_server, chat_state = start_chat_standin()
    chat_url = f'http://127.0.0.1:{chat_server.server_port}/v1'
    # Text AI: a custom OpenAI-compatible service on loopback (needs no key).
    import copy
    from twobyteasr.storage import settings as settings_module
    from twobyteasr.providers.llm_config import activate_ai_service, update_active_profile
    settings = copy.deepcopy(settings_module.DEFAULT_SETTINGS)
    activate_ai_service(settings, 'custom')
    update_active_profile(settings, base_url=chat_url, model='loopback-chat')
    settings['switches'].update(enable_ai_polish=True, use_ai_grouping=True, unified_glm_processing=True)
    settings['models']['speaker_source'] = 'single'
    settings_path = settings_module.project_settings_path()  # <test root>/config in an isolated run
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.language:
        from twobyteasr.i18n import save_language
        save_language(args.language)

    from PySide6.QtCore import QSettings, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(output / 'qsettings'))
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    from twobyteasr.app.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.design.theme_manager import apply_application_theme
    apply_application_theme(app)
    _register_bundled_fonts()
    app.setFont(_app_font())
    import subtitle_core as legacy
    import moss_firered_pipeline as pipeline
    window = MainWindow([], legacy, pipeline, legacy.run_startup_self_test())
    window.resize(1440, 900)
    window.show()
    QTest.qWait(800)
    result = dict(passed=False, checks={}, samples=[], screenshots=[], events=[], paid_calls=0,
                  chat_url=chat_url, asr_url=f'http://127.0.0.1:{asr_server.server_port}/v1')
    errors, received = [], []

    def save():
        result['standin'] = dict(asr=asr_state, chat=dict(chat_state, requests=chat_state['requests'][-200:]))
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, value):
        result['checks'][name] = bool(value)
        save()
        if not value:
            raise AssertionError(name)

    def pump(seconds=.05):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(.005)

    def shot(name):
        path = output / f'{len(result["screenshots"]) + 1:02d}-{name}.png'
        window.grab().save(str(path))
        result['screenshots'].append(path.name)

    def sample():
        facts = window.stage_metrics.metrics()
        rows = [row[1] for row in window.recognition_preview.rows()]
        usage = window.stage_usage_label.text() if not window.stage_usage_label.isHidden() else ''
        title = window.progress_stage
        # Width of the step title in characters of its own font: long values in
        # the facts column once squeezed it to one character per line.
        title_chars = round(title.width() / max(1, title.fontMetrics().horizontalAdvance('字')), 1)
        return dict(t=round(time.monotonic() - started, 1), step=window.stage_step_label.text(),
                    action=title.text(), facts=facts, usage=usage, title_chars=title_chars,
                    preview_source=window.preview_source.text(), preview=rows[-3:])

    guard = QTimer(window)

    def modal_guard():
        modal = QApplication.activeModalWidget()
        if isinstance(modal, QMessageBox):
            start = next((b for b in modal.buttons() if modal.buttonRole(b) == QMessageBox.ButtonRole.AcceptRole), None)
            result.setdefault('dialogs', []).append(modal.text() + ' ' + modal.informativeText())
            if start is not None and '上传' in modal.windowTitle() + modal.text():
                start.click()
                return
            errors.append(modal.text() + ' ' + modal.informativeText())
            modal.reject()
    started = time.monotonic()
    try:
        guard.timeout.connect(modal_guard)
        guard.start(200)
        window._return_to_settings()
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
        window.ai_polish.setChecked(True)
        window.ai_grouping.setChecked(True)
        window.legacy.RUNTIME_SETTINGS['glossary']['enabled_glossary_ids'] = []
        window.legacy.RUNTIME_SETTINGS['models']['speaker_source'] = 'single'
        check('save cloud ASR configuration', window._save_asr_configuration(show_feedback=False))
        check('save text AI configuration', window._save_ai_configuration(show_feedback=False))
        from twobyteasr.providers.llm_config import active_service_values
        values = active_service_values(window.legacy.RUNTIME_SETTINGS)
        result['text_ai'] = {k: values.get(k) for k in ('provider', 'base_url', 'model')}
        check('text AI points at the loopback stand-in', str(values.get('base_url') or '').startswith(chat_url))
        source = str((output / 'api-progress-test.mp4').resolve())
        window.import_media([source], replace=True)
        end = time.monotonic() + 40
        while not (window.media_paths == [source] and window.start_button.isEnabled()) and time.monotonic() < end:
            pump()
        check('media imported', window.media_paths == [source])
        from dataclasses import asdict
        original = window._handle_event

        def observe(event):
            result['events'].append(dict(kind=event.kind, stage=event.stage_index, label=event.label,
                                         payload={k: v for k, v in event.payload.items() if k not in ('cues', 'rows')}))
            original(event)
        window._handle_event = observe
        QTest.mouseClick(window.start_button, Qt.LeftButton)
        pump(.2)
        check('recognition started', window.worker is not None)
        worker = window.worker
        worker.result_ready.connect(received.append)
        worker.unexpected_error.connect(errors.append)
        taken, last = set(), None
        deadline = time.monotonic() + 900
        while not received and not errors and time.monotonic() < deadline:
            pump(.25)
            current = sample()
            if current != last and current['facts']:
                result['samples'].append(current)
                last = dict(current)
            facts = dict(current['facts'])
            phase = facts.get('云端阶段', '')
            if '上传' in phase and '已上传' in facts and 'asr-upload' not in taken:
                taken.add('asr-upload'); shot('asr-uploading')
            if ('排队' in phase or '识别中' in phase) and 'asr-queue' not in taken:
                taken.add('asr-queue'); shot('asr-queue-or-processing')
            if 'AI 正在校对' in current['action'] and '正在处理' in facts and '输入' in current['usage'] \
                    and current['preview_source'] == 'AI 校对结果' and 'polish' not in taken:
                taken.add('polish'); shot('proofreading-midway')
                # The newest-text preview sits under the record; scroll it into view as a user would.
                window.progress_left_column.ensureWidgetVisible(window.recognition_preview)
                pump(.2); shot('proofreading-midway-preview')
            if 'AI 正在校对' in current['action'] and '重试' in facts and 'polish-retry' not in taken:
                taken.add('polish-retry'); shot('proofreading-retry')
            if 'AI 正在全文断句' in current['action'] and 'group' not in taken:
                taken.add('group'); shot('segmentation-running')
            save()
        check('recognition finished without errors', bool(received) and not errors)
        end = time.monotonic() + 30
        while worker.isRunning() and time.monotonic() < end:
            pump()
        pump(1.0)
        from PySide6.QtWidgets import QDialog
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog, QDialog) and dialog.isVisible():
                dialog.close()
        window._switch_page(1)  # back to the progress page, as "查看详细进度" does
        pump(1.0)
        result['final'] = sample()
        shot('finished')
        outcome = received[0]
        result['task_status'] = outcome.successes[0].status if outcome.successes else ''
        check('task delivered', result['task_status'] in {'success', 'degraded_success'})
        report_path = Path(outcome.successes[0].report_json_path)
        report = json.loads(report_path.read_text(encoding='utf-8'))
        usage = report.get('api_usage') or {}
        result['report_api_usage'] = usage
        result['report_text_usage'] = [line for line in Path(outcome.successes[0].report_text_path).read_text(
            encoding='utf-8').splitlines() if 'API 用量' in line or line.startswith('- 合计') or line.startswith('- 模型')]
        samples = result['samples']
        asr_phases = {dict(s['facts']).get('云端阶段', '') for s in samples}
        uploaded = [dict(s['facts']).get('已上传', '') for s in samples
                    if dict(s['facts']).get('云端阶段') == '正在上传音频' and dict(s['facts']).get('已上传', '').endswith(' MB')]
        result['upload_values'] = list(dict.fromkeys(uploaded))
        check('upload progress shown and moving', len(result['upload_values']) >= 2)
        check('queue and processing states shown', '排队中' in asr_phases and '云端识别中' in asr_phases)
        polish = [s for s in samples if 'AI 正在校对' in s['action']]
        check('proofreading shows batches done/total', any('已完成批次' in dict(s['facts']) for s in polish))
        check('proofreading shows batches being processed', any('正在处理' in dict(s['facts']) for s in polish))
        check('proofreading shows its token usage while running',
              any(s['usage'].startswith('本步用量：输入') for s in polish))
        check('the step title keeps at least four characters per line',
              all(s['title_chars'] >= 4 for s in samples if s['facts']))
        check('proofreading text appears before the step ends',
              any(s['preview_source'] == 'AI 校对结果' and s['preview'] for s in polish))
        check('the stand-in rate limit shows as a retry', any('重试' in dict(s['facts']) for s in polish))
        check('streaming requests asked for usage',
              all(row['stream_options'] == {'include_usage': True} for row in chat_state['requests'] if row['stream']))
        check('the finished page keeps the API usage', result['final']['usage'].startswith('API 用量：输入'))
        sent = chat_state['sent_usage']
        stages = usage.get('api_stages') or {}
        check('report proofreading tokens equal what the provider sent',
              stages.get('polished', {}).get('input_tokens') == sent.get('polish', {}).get('input')
              and stages.get('polished', {}).get('output_tokens') == sent.get('polish', {}).get('output')
              and stages.get('polished', {}).get('cached_input_tokens', 0) == sent.get('polish', {}).get('cached'))
        check('report segmentation tokens equal what the provider sent',
              stages.get('grouped', {}).get('input_tokens') == sent.get('group', {}).get('input'))
        check('cloud recognition without usage is counted as not reported',
              stages.get('asr_primary', {}).get('calls') == 1 and stages['asr_primary']['reported_calls'] == 0)
        result['passed'] = True
    except Exception as exc:  # noqa: BLE001 - recorded as evidence
        import traceback
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['traceback'] = traceback.format_exc()
        try:
            shot('failure')
        except Exception:
            pass
    finally:
        guard.stop()
        save()
        window.close()
        app.quit()
    return 0 if result['passed'] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--scale', default='1')
    parser.add_argument('--language', default='')
    parser.add_argument('--visible', action='store_true', help='run on the current desktop instead of a private one')
    parser.add_argument('--inner', action='store_true')
    args = parser.parse_args()
    return inner(args) if args.inner else outer(args)


if __name__ == '__main__':
    raise SystemExit(main())
