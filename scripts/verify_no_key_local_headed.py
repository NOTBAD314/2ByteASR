"""Real window: subtitles with no API key anywhere (2026-10-15).

User feedback: people who do not want to fill in an API key could not get
subtitles out. This drives the ordinary Home flow on a private desktop with
the saved defaults (AI 校对 and AI 断句 switched on) and no key in the profile
or the environment:

Home → local recognition on this computer's models (MOSS + FireRed + Qwen3-ASR
by default) → no “AI 配置未保存” → the task runs the local line-break rules and
skips AI proofreading → 完成页「导出字幕」 writes SRT/ASS/TXT/JSON → Studio edit, cut, save, reopen
→ four subtitle formats → video export (``home_release_flow_audit.py`` with
``text_ai: "saved"``).

User data is redirected to the output folder; the models and runtimes are the
repository's (read only). Nothing is uploaded and no paid service is called.

usage: python scripts/verify_no_key_local_headed.py --output tmp/<new dir>
       [--asr moss,local,local] [--exe <frozen candidate> --main-python <python> [--moss-python <python>]
        --model-root <folder>]

A frozen candidate in a fresh profile has no registered model runtime or model
folder; ``--main-python`` / ``--moss-python`` / ``--model-root`` point it at
existing ones on this computer (read only).
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
    parser.add_argument('--asr', default='moss,local,local', help='primary,timeline,review backends')
    parser.add_argument('--main-python', type=Path, help='with --exe: an existing main model runtime python')
    parser.add_argument('--moss-python', type=Path, help='with --exe: an existing MOSS runtime python')
    parser.add_argument('--model-root', type=Path, help='with --exe: an existing model folder (read only)')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    output.mkdir(parents=True)
    local, roaming = output / 'local', output / 'roaming'
    local.mkdir()
    roaming.mkdir()
    # Before anything imports the app: every user-data path points into the output folder.
    os.environ.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)})
    from timing_benchmark import build_synthetic
    reference_path = build_synthetic(output / 'synthetic')
    reference = json.loads(reference_path.read_text(encoding='utf-8'))
    media = output / 'no-key-test.mp4'
    ffmpeg = ROOT / 'tools' / 'ffmpeg' / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    subprocess.run([str(ffmpeg), '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=0x33445a:s=640x360:r=30',
                    '-i', reference['audio'], '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-b:a', '128k', str(media)], check=True)
    primary, timeline, review = (args.asr.split(',') + ['off', 'off'])[:3]
    config = {'media': str(media), 'timeout': 1500, 'text_ai': 'saved', 'speaker_source': 'single',
              'asr': {'primary_asr_backend': primary, 'firered_asr_backend': timeline, 'qwen_asr_backend': review},
              'accept_status': ['success', 'degraded_success']}
    (output / 'home-flow.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    fixture = output / 'projects' / 'startup-empty' / 'startup-empty.2byteproj'
    fixture.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='Startup empty', duration_ms=0)), fixture)
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE', 'TWOBYTEASR_TEST_ROOT',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO', 'CUDA_VISIBLE_DEVICES'):
        env.pop(key, None)
    # No key may come from the environment either (DEEPSEEK_API_KEY, DASHSCOPE_API_KEY, ...).
    removed = sorted(key for key in env if re.search(r'(API_?KEY|_TOKEN|ACCESS_?KEY)', key, re.IGNORECASE))
    for key in removed:
        env.pop(key)
    env.update(TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_ACCEPTANCE_DIR=str(output),
               TWOBYTEASR_ACCEPTANCE_SCENARIO='home-release-flow', TWOBYTEASR_INVOKER_CWD=str(ROOT),
               QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale, TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', NO_PROXY='127.0.0.1,localhost')
    if args.main_python:
        env['TWOBYTEASR_MAIN_PYTHON'] = str(args.main_python.resolve())
    if args.moss_python:
        env['TWOBYTEASR_MOSS_PYTHON'] = str(args.moss_python.resolve())
    if args.model_root:
        env['2BYTEASR_MODEL_ROOT'] = str(args.model_root.resolve())
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    started = time.monotonic()
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=2400)
    result = {}
    try:
        result = json.loads((output / 'result.json').read_text('utf8'))
    except (OSError, ValueError):
        pass
    result['launcher_exit'] = code
    result['wall_s'] = round(time.monotonic() - started, 1)
    result['environment_keys_removed'] = removed
    result['passed'] = bool(result.get('passed') and code == 0)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    summary = {k: result.get(k) for k in ('passed', 'task_status', 'launcher_exit', 'wall_s', 'error', 'home_ai',
                                          'text_ai_local_roles', 'report_switches', 'completion_export',
                                          'subtitle_artifacts', 'video_output', 'recognized_text')}
    summary['checks'] = result.get('checks')
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
