"""Review replay and the frameless main window in the real app, source or frozen (2026-10-15).

Usage: python scripts/verify_review_window_headed.py --output tmp/<fresh dir> [--exe path\\to\\2ByteASR.exe]
Runs on a private Windows desktop with isolated user data and every monitor
of this PC; see twobyteasr/review_window_audit.py for the checks.
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
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
    from twobyteasr.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    fixture = output / 'projects' / 'review-window' / 'review-window.2byteproj'
    fixture.parent.mkdir(parents=True)
    media = fixture.parent / 'review-window.mp4'
    subprocess.run([str(ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'), '-y', '-v', 'error',
                    '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=24',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=24',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '30', '-c:a', 'aac', '-shortest', str(media)],
                   check=True)
    # Neighbouring captions 100-200 ms apart: the old replay ran into them.
    save_project(SubtitleProject(
        media=StudioMedia(path=str(media), display_name='审核重听检查', duration_ms=24_000, width=1280, height=720),
        cues=[StudioCue('c0', 1000, 2500, '第一句审核字幕'), StudioCue('c1', 2700, 4200, '第二句紧跟其后'),
              StudioCue('c2', 4300, 6000, '第三句也很近'), StudioCue('c3', 8000, 9500, '第四句隔两秒'),
              StudioCue('c4', 9600, 11000, '第五句')],
    ), fixture)

    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='review-window',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
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
            result['error'] = 'Owned review-window GUI did not exit after normal close'
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    failed = [c['name'] for c in result.get('checks', []) if not c['passed']]
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), failed=failed,
                          launcher_exit=code, error=(result.get('error') or '')[-800:],
                          executable=result.get('executable'), output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
