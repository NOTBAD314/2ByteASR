"""Run real blank-project controls through normal source/frozen launch."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--scale', default='1')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    if args.exe and not args.exe.resolve().is_file():
        parser.error('--exe must identify an existing executable')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import StudioMedia, SubtitleProject, save_project
    fixture = output/'projects'/'existing-zero'/'existing-zero.2byteproj'
    fixture.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='Existing empty', duration_ms=0)), fixture)

    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='blank-project',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale,
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output/'process', timeout=180)
    receipt = output/'result.json'
    deadline = time.monotonic() + 60
    result = {}
    # Daily launchers may return before the owned frozen GUI finishes.
    while time.monotonic() < deadline:
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
            child_code = psutil.Process(pid).wait(timeout=25)
            result['child_exit'] = child_code
            result['passed'] = bool(result['passed'] and child_code == 0)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            result['passed'] = False
            result['error'] = 'Owned blank-project GUI did not exit after normal close'
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])),
                         launcher_exit=code, error=result.get('error'),
                         executable=result.get('executable'), output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
