"""Verify support through the normal source, frozen or daily launcher entry."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scale', default='1')
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():
        raise ValueError('Choose a fresh directory under repository tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    fixture = out/'guard.2byteproj'
    fixture.write_text('{}', 'utf-8')
    from isolated_windows_desktop import run_on_desktop
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='support-entry',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale,
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    for restarting in (False, True):
        env['TWOBYTEASR_SUPPORT_RESTART'] = '1' if restarting else '0'
        code = run_on_desktop(command, cwd=ROOT, env=env,
                              output=out/('restart-process' if restarting else 'process'), timeout=210)
        receipt = out/('restart-result.json' if restarting else 'result.json')
        deadline = time.monotonic() + 210
        result = {}
        # The root launcher delegates to a child EXE and can exit before its UI.
        while time.monotonic() < deadline:
            try:
                result = json.loads(receipt.read_text('utf-8'))
                if result.get('gui_shutdown'):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.2)
        result.setdefault('passed', False)
        result['launcher_exit'] = code
        result['passed'] = bool(result['passed'] and code == 0 and result.get('gui_shutdown'))
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
                result['error'] = 'Owned GUI did not exit after shutdown'
        receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])),
                             dpr=result.get('dpr'), error=result.get('error'), restart=restarting,
                             executable=result.get('executable')), ensure_ascii=False), flush=True)
        if not result['passed']:
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
