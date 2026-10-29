"""Style tab background toggle / recolor and the label grid in the real app (2026-10-17).

Usage: python scripts/verify_style_background_grid_headed.py --output tmp/<fresh dir> [--exe path\\to\\2ByteASR.exe]
       [--theme grape|warm]
Runs on a private Windows desktop with isolated user data; see
twobyteasr/acceptance/style_background_grid_audit.py for the checks.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _ffmpeg(*arguments):
    subprocess.run([str(ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'), '-y', '-v', 'error', *arguments],
                   check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--theme', default='grape')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    if args.exe and not args.exe.resolve().is_file():
        parser.error('--exe must identify an existing executable')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, default_style, save_project

    fixture = output / 'projects' / 'style-background-grid' / 'style-background-grid.2byteproj'
    fixture.parent.mkdir(parents=True)
    media = fixture.parent / 'style-background-grid.mp4'
    _ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=8',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=8',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '30', '-c:a', 'aac', '-shortest', str(media))
    save_project(SubtitleProject(
        media=StudioMedia(path=str(media), display_name='样式页背景检查', duration_ms=8_000, width=1280, height=720),
        styles=[default_style()],
        cues=[StudioCue('c0', 0, 2400, '沟通结果推荐'), StudioCue('c1', 2600, 5000, '感觉推荐给')],
    ), fixture)

    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='style-background-grid',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_STYLE_AUDIT_THEME=args.theme,
               QT_QPA_PLATFORM='windows', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='127.0.0.1,localhost')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=600)
    receipt = output / 'result.json'
    deadline = time.monotonic() + 60
    result = {}
    while time.monotonic() < deadline:  # launchers may return before the GUI finishes
        try:
            result = json.loads(receipt.read_text('utf8'))
            if result.get('gui_shutdown'):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    result['launcher_exit'] = code
    result['passed'] = bool(result.get('passed') and code == 0 and result.get('gui_shutdown'))
    import psutil
    pid = result.get('pid')
    if pid and psutil.pid_exists(pid):
        try:
            result['child_exit'] = psutil.Process(pid).wait(timeout=25)
            result['passed'] = bool(result['passed'] and result['child_exit'] == 0)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            result['passed'] = False
            result['error'] = 'Owned style-background-grid GUI did not exit after normal close'
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    failed = [c['name'] for c in result.get('checks', []) if not c['passed']]
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), failed=failed,
                          launcher_exit=code, error=(result.get('error') or '')[-800:],
                          executable=result.get('executable'), output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
