"""Real-window cloud-only flow on a private desktop (2026-10-13).

Home → recognize with a cloud recognizer (MOSS Pro cloud shape, served by an
in-process loopback stand-in) → Studio edit, cut, undo/redo, save, reopen →
four subtitle formats → video export. Runtime discovery is limited to the
output directory, so no local model environment exists, and PyTorch sees no
CUDA device. The stand-in returns a synthetic script; this verifies the app's
paths, not recognition quality, and makes no paid call.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--scale', default='1')
    parser.add_argument('--align', action='store_true', help='also run the local aligner (needs a model runtime)')
    parser.add_argument('--main-python', type=Path,
                        help='--align with --exe: existing model runtime python (a frozen candidate has none registered)')
    parser.add_argument('--model-root', type=Path, help='--align with --exe: read-only folder with Qwen3-ForcedAligner-0.6B')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    output.mkdir(parents=True)
    from timing_benchmark import build_synthetic
    reference_path = build_synthetic(output / 'synthetic')
    reference = json.loads(reference_path.read_text(encoding='utf-8'))
    media = output / 'cloud-only-test.mp4'
    ffmpeg = ROOT / 'tools' / 'ffmpeg' / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x33445a:s=640x360:r=30',
                    '-i', reference['audio'], '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '128k', str(media)], check=True)
    config = {'media': str(media), 'timeout': 600, 'loopback_mosi_reference': str(reference_path),
              'asr': {'primary_asr_backend': 'api', 'qwen_asr_backend': 'off',
                      'firered_asr_backend': 'qwen_aligner' if args.align else 'off'},
              # Multiple speakers always ask for confirmation, by design.
              'accept_status': ['success', 'degraded_success']}
    (output / 'home-flow.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import StudioMedia, SubtitleProject, save_project
    fixture = output / 'projects' / 'startup-empty' / 'startup-empty.2byteproj'
    fixture.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='Startup empty', duration_ms=0)), fixture)
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    local, roaming = output / 'local', output / 'roaming'
    local.mkdir(exist_ok=True); roaming.mkdir(exist_ok=True)
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_STARTUP_PROJECT=str(fixture))
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='home-release-flow',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale,
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1', CUDA_VISIBLE_DEVICES='-1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', NO_PROXY='127.0.0.1,localhost')
    if args.align:
        # The aligner needs the local model runtime; allow only that one.
        env.pop('TWOBYTEASR_TEST_ROOT', None)
        # 2026-10-14: a frozen candidate in an isolated profile has no registered
        # runtime or model folder; point it at existing ones (read only).
        if args.main_python:
            env['TWOBYTEASR_MAIN_PYTHON'] = str(args.main_python.resolve())
        if args.model_root:
            env['2BYTEASR_MODEL_ROOT'] = str(args.model_root.resolve())
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    started = time.monotonic()
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=1500)
    result = {}
    try:
        result = json.loads((output / 'result.json').read_text('utf8'))
    except (OSError, ValueError):
        pass
    result['launcher_exit'] = code
    result['wall_s'] = round(time.monotonic() - started, 1)
    result['passed'] = bool(result.get('passed') and code == 0)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    summary = {k: result.get(k) for k in ('passed', 'task_status', 'launcher_exit', 'wall_s', 'error', 'loopback',
                                          'subtitle_artifacts', 'video_output')}
    summary['checks'] = result.get('checks')
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
