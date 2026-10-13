"""Acceptance: a subtitle job that uses only a cloud recognizer (2026-10-13).

Runs the real recognition queue (``service.run_media_queue``) on a generated
test video with isolated user data and CUDA hidden from PyTorch, then loads
the saved project and checks what the run actually used.

Modes
-----
``--cloud loopback`` (default): a local stand-in for the MOSI transcription API
    on 127.0.0.1 that returns the synthetic script's sentences with their real
    utterance times and speakers. It proves the app's request/poll/parse/save
    path and the absence of local-runtime dependencies; it is NOT a recognition
    accuracy test and NOT a real MOSI call.
``--cloud mosi`` / ``--cloud bailian``: real services, read-only use of the
    key saved in the real app (``--real-secrets``); uploads ~90 s of synthetic
    speech and costs money. Only run with the owner's explicit permission.

``--no-model-runtime`` restricts runtime discovery to the isolated test root,
so no local Python model environment exists (cloud-only computer).
``--align`` selects the local Qwen3-ForcedAligner timeline (CPU when CUDA is
hidden) on top of the cloud transcript; ``--align-backend mlx_qwen_aligner``
uses the Apple Silicon MLX aligner instead (runtime from TWOBYTEASR_MLX_PYTHON).
``--worker-exe`` runs the cloud worker through an installed app executable
(``<exe> --asr-api-worker``), the way the frozen app launches it.
``--speech say`` builds the test speech with macOS ``say`` (utterance times
only) instead of the Windows synthetic word-timing set.
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


def _prepare_environment(out: Path, *, no_model_runtime: bool, main_python: str) -> None:
    user_data = out / 'user-data'
    user_data.mkdir(parents=True, exist_ok=True)
    os.environ['2BYTEASR_USER_DATA_ROOT'] = str(user_data)
    os.environ['LOCALAPPDATA'] = str(user_data)
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'          # PyTorch sees no GPU
    os.environ['QT_QPA_PLATFORM'] = os.environ.get('QT_QPA_PLATFORM', 'offscreen')
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['TWOBYTEASR_ALIGNER_DEVICE'] = 'cpu'
    if no_model_runtime:
        # Runtime discovery is limited to this boundary: no model environment.
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    elif main_python:
        os.environ['TWOBYTEASR_MAIN_PYTHON'] = main_python
    sys.path.insert(0, str(ROOT))


SAY_SCRIPT = (
    ('M1', 'Tingting', '今天我们测试兔白字幕的云端识别流程。'),
    ('F1', 'Meijia', '这一段由第二位说话人朗读，用来检查说话人分段。'),
    ('M1', 'Tingting', '最后保存工程，再导出字幕文件。'),
)


def _say_reference(directory: Path) -> Path:
    """Utterance-level reference from macOS ``say`` (no word times)."""
    import wave
    import numpy as np
    directory.mkdir(parents=True, exist_ok=True)
    gap = np.zeros(int(0.6 * 16000), dtype=np.int16)
    pieces, utterances, cursor = [gap], [], len(gap)
    for index, (speaker, voice, text) in enumerate(SAY_SCRIPT):
        part = directory / f'part{index}.wav'
        command = ['say', '-v', voice, '--data-format=LEI16@16000', '-o', str(part), text]
        if subprocess.run(command, capture_output=True).returncode or not part.is_file():
            subprocess.run(['say', '--data-format=LEI16@16000', '-o', str(part), text], check=True)
            voice = 'default'
        with wave.open(str(part), 'rb') as stream:
            if stream.getframerate() != 16000 or stream.getnchannels() != 1:
                raise RuntimeError('say did not produce 16 kHz mono PCM')
            samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2')
        utterances.append({'speaker': speaker, 'voice': voice, 'text': text,
                           'start_s': cursor / 16000, 'end_s': (cursor + len(samples)) / 16000})
        pieces += [samples, gap]
        cursor += len(samples) + len(gap)
    audio = directory / 'say-speech.wav'
    with wave.open(str(audio), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(np.concatenate(pieces).tobytes())
    reference = directory / 'reference.json'
    reference.write_text(json.dumps({'audio': str(audio), 'utterances': utterances, 'timing': 'utterance_only',
                                     'origin': 'macOS say on this machine'}, ensure_ascii=False, indent=2),
                         encoding='utf-8')
    return reference


def _make_media(out: Path, *, speech: str = 'synthetic', ffmpeg: str = '') -> tuple[Path, dict]:
    sys.path.insert(0, str(ROOT / 'scripts'))
    if speech == 'say':
        reference_path = _say_reference(out / 'say')
    else:
        from timing_benchmark import build_synthetic
        reference_path = build_synthetic(out / 'synthetic')
    reference = json.loads(reference_path.read_text(encoding='utf-8'))
    video = out / 'cloud-only-test.mp4'
    ffmpeg = Path(ffmpeg) if ffmpeg else ROOT / 'tools' / 'ffmpeg' / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x33445a:s=640x360:r=30',
                    '-i', reference['audio'], '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '128k', str(video)], check=True)
    return video, reference


def _loopback_mosi(reference: dict):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    speakers = {'M1': 'S01', 'F1': 'S02', 'F2': 'S03'}
    state = {'uploads': []}

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
                segments = [{'speaker': speakers[u['speaker']], 'text': u['text'], 'start': u['start_s'],
                             'end': u['end_s']} for u in reference['utterances']]
                return self._send(200, {'id': 'loop', 'status': 'SUCCESS',
                                        'text': ''.join(u['text'] for u in reference['utterances']),
                                        'segments': segments})
            self._send(404, {'error': {'code': 'not_found'}})

        def do_POST(self):
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length)
            state['uploads'].append({'bytes': len(body), 'auth': self.headers.get('Authorization', '')[:7]})
            self._send(200, {'id': 'loop', 'task_id': 'loop', 'status': 'PENDING', 'retry_after': 2})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def _configure(cloud: str, url: str, key: str, *, align: bool, real_secrets: Path | None,
               align_backend: str = 'qwen_aligner'):
    import subtitle_core as legacy
    from twobyteasr import llm_config
    models = legacy.RUNTIME_SETTINGS.setdefault('models', {})
    switches = legacy.RUNTIME_SETTINGS.setdefault('switches', {})
    if cloud in {'loopback', 'mosi'}:
        provider, protocol, model = 'mosi_moss_pro', 'mosi_transcriptions', 'moss-transcribe-diarize-pro'
    else:
        provider, protocol, model = 'qwen31_filetrans', 'dashscope_filetrans', 'qwen3-asr-flash-filetrans'
    models.update(primary_asr_backend='api', qwen_asr_backend='off',
                  firered_asr_backend=align_backend if align else 'off',
                  qwen_asr_api_provider=provider, qwen_asr_api_protocol=protocol, qwen_asr_api_model=model,
                  qwen_asr_api_url=url)
    switches.update(enable_ai_polish=False, use_ai_grouping=False, unified_glm_processing=False,
                    enable_qwen_asr_reference=False)
    if real_secrets is not None:
        payload = llm_config._read_secrets(read_only_path=real_secrets)
        key = llm_config.read_api_key(provider, url)[0] if False else ''
        for name, value in payload.items():
            if isinstance(value, str) and name.startswith('API__') and provider in name:
                key = value
        if cloud == 'bailian':
            models.update({k: v for k, v in json.loads((real_secrets.parent / '2byteasr_settings.json')
                                                       .read_text(encoding='utf-8'))['models'].items()
                           if k.startswith('oss_')})
            ident, secret = payload.get('OSS_ACCESS_KEY_ID', ''), payload.get('OSS_ACCESS_KEY_SECRET', '')
            if ident and secret:
                llm_config.save_oss_credentials(ident, secret)
    if not key:
        raise SystemExit('No API key available for this mode.')
    llm_config.save_api_key_for(provider, url, key)   # isolated DPAPI store under the test root
    legacy.configure_runtime_asr(models)
    return legacy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--cloud', choices=['loopback', 'mosi', 'bailian'], default='loopback')
    parser.add_argument('--no-model-runtime', action='store_true')
    parser.add_argument('--align', action='store_true')
    parser.add_argument('--main-python', default='')
    parser.add_argument('--real-secrets', default='')
    parser.add_argument('--align-backend', choices=['qwen_aligner', 'mlx_qwen_aligner'], default='qwen_aligner')
    parser.add_argument('--worker-exe', default='', help='installed app executable for the cloud worker')
    parser.add_argument('--speech', choices=['synthetic', 'say'], default='synthetic')
    parser.add_argument('--ffmpeg', default='')
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if 'tmp' not in {part.lower() for part in out.parts}:
        raise SystemExit('--out must be under a tmp directory')
    out.mkdir(parents=True, exist_ok=True)
    _prepare_environment(out, no_model_runtime=args.no_model_runtime, main_python=args.main_python)
    if args.ffmpeg:
        # 2026-10-14: a CI checkout has no tools/ffmpeg; the queue (project save
        # probes the media) must use the given ffmpeg/ffprobe (the installed app's).
        from twobyteasr import platform_media
        given = Path(args.ffmpeg).resolve()
        platform_media.ffmpeg_tool = lambda name='ffmpeg', *, root=None: given.with_name(
            platform_media.executable_name(name))
    video, reference = _make_media(out, speech=args.speech, ffmpeg=args.ffmpeg)
    if args.worker_exe:
        from twobyteasr import cloud_api_worker
        executable = str(Path(args.worker_exe).resolve())
        cloud_api_worker.cloud_worker_command = lambda install_root=None: [executable, '--asr-api-worker']
    server = state = None
    if args.cloud == 'loopback':
        server, state = _loopback_mosi(reference)
        url, key = f'http://127.0.0.1:{server.server_port}/v1', 'sk-loopback'
    elif args.cloud == 'mosi':
        url, key = 'https://api.mosi.cn/v1', ''
    else:
        settings = json.loads((Path(args.real_secrets).parent / '2byteasr_settings.json').read_text(encoding='utf-8'))
        from twobyteasr.api_endpoints import filetrans_endpoint
        url, key = filetrans_endpoint(settings['models']['qwen_asr_api_url']), ''
    legacy = _configure(args.cloud, url, key, align=args.align,
                        real_secrets=Path(args.real_secrets) if args.real_secrets else None,
                        align_backend=args.align_backend)
    from twobyteasr.service import RunOptions, run_media_queue
    from twobyteasr.speaker_strategy import resolve
    events = []
    options = RunOptions(settings_snapshot_json=json.dumps(legacy.RUNTIME_SETTINGS, ensure_ascii=False),
                         speaker_source=resolve(legacy.RUNTIME_SETTINGS), recognition_language='zh')
    started = time.perf_counter()
    result = run_media_queue([str(video)], options, event_sink=lambda event: events.append(event))
    elapsed = time.perf_counter() - started
    if server is not None:
        server.shutdown()
    media = result.results[0]
    receipt = {'mode': args.cloud, 'no_model_runtime': args.no_model_runtime, 'align': args.align,
               'align_backend': args.align_backend if args.align else 'off', 'speech': args.speech,
               'worker_exe': args.worker_exe or None, 'platform': sys.platform,
               'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES'), 'elapsed_s': round(elapsed, 1),
               'exit_code': result.exit_code, 'status': media.status, 'error': media.error,
               'srt': media.srt_path, 'project': getattr(media, 'project_path', '') or '',
               'loopback_uploads': state['uploads'] if state else None, 'result_ref': media.result_ref_json}
    report_events = _report_events(media)
    receipt.update(report_events)
    if media.srt_path and Path(media.srt_path).is_file():
        receipt['srt_cues'] = Path(media.srt_path).read_text(encoding='utf-8-sig').count(' --> ')
    receipt['project_check'] = _project_check(media)
    # The queue saves a project (SRT export is a separate step).
    receipt['passed'] = bool(result.exit_code == 0 and receipt['project_check'].get('cues')
                             and (not args.align or receipt['project_check'].get('cues_with_measured_words')))
    (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'result.json').write_text(json.dumps({'passed': receipt['passed'], 'mode': args.cloud,
                                                 'align_backend': receipt['align_backend']}, indent=2),
                                     encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if result.exit_code == 0 else 1


def _report_events(media) -> dict:
    """What actually ran, from the job's own run report."""
    found = {'cloud_worker_launch': None, 'gpu_status': None, 'model_workers': [], 'aligner_device': None,
             'vad_backend': None, 'review_items': []}
    report = None
    for candidate in (getattr(media, 'report_json_path', ''),):
        if candidate and str(candidate).endswith('.json') and Path(candidate).is_file():
            report = json.loads(Path(candidate).read_text(encoding='utf-8'))
    if report is None:
        txt = Path(str(media.txt_path or ''))
        for path in sorted(txt.parent.glob('*任务报告.json')) if txt.parent.is_dir() else []:
            report = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(report, dict):
        return found
    # Stage failures and skips, in the receipt itself (2026-10-14: on the Mac
    # runner the MLX timeline "did not complete" and the report was not kept).
    found['stage_problems'] = [
        {key: event.get(key) for key in ('event', 'kind', 'stage', 'model_id', 'role', 'backend', 'reason',
                                         'error', 'error_type', 'detail', 'skip_reason') if event.get(key)}
        for event in report.get('events') or report.get('run_events') or []
        if any(word in str(event.get('event') or event.get('kind') or '').lower()
               for word in ('fail', 'error', 'skip', 'unavailable', 'not_ready', 'degrad'))][:30]
    for event in report.get('events') or report.get('run_events') or []:
        kind = event.get('kind') or event.get('event')
        if kind == 'cloud_worker_launch':
            found['cloud_worker_launch'] = event.get('launcher')
        elif kind == 'GPU_STATUS':
            found['gpu_status'] = event.get('status')
        elif kind == 'asr_worker_started':
            found['model_workers'].append({'model': event.get('model_id'), 'runtime': event.get('runtime')})
        elif kind == 'forced_alignment':
            found['aligner_device'] = event.get('device') or found['aligner_device']
        elif kind in {'vad_backend_selected', 'stage_completed'} and event.get('backend'):
            found['vad_backend'] = found['vad_backend'] or event.get('backend')
    found['review_items'] = [item.get('category') or item.get('title') for item in report.get('review_items') or []][:20]
    return found


def _project_check(media) -> dict:
    path = getattr(media, 'project_path', '') or ''
    if not path:
        ref = getattr(media, 'result_ref_json', '')
        try:
            path = json.loads(ref).get('project_path', '') if ref else ''
        except ValueError:
            path = ''
    if not path or not Path(path).is_file():
        return {'found': False}
    from twobyteasr.studio_project import load_project
    project = load_project(path)
    cues = list(project.cues)
    speakers = sorted({cue.speaker_id for cue in cues})
    from twobyteasr.cue_word_alignment import cue_words
    measured = 0
    for cue in cues:
        try:
            words, _reason = cue_words(project, cue)
        except Exception:
            words = ()
        if words:
            measured += 1
    return {'found': True, 'path': path, 'cues': len(cues), 'speakers': speakers,
            'cues_with_measured_words': measured}


if __name__ == '__main__':
    raise SystemExit(main())
