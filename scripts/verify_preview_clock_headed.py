"""Exercise production Studio clocks on a private Windows desktop.

The optional display override simulates a monitor reporting the wrong refresh
rate. It is applied only in this verification process, never in user settings.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--display-fps', type=float, default=0)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--normal-entry', action='store_true')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.baseline and (args.exe or args.normal_entry):
        parser.error('--baseline is only for the standalone source counterfactual')
    if args.exe and not args.exe.resolve().is_file():
        parser.error('--exe must identify an existing executable')
    out = args.output.resolve()
    if not out.is_relative_to(root / 'tmp'):
        raise ValueError('Evidence must be inside repository tmp')
    if args.child:
        from twobyteasr.acceptance.preview_clock_audit import run
        return run(out, baseline=args.baseline, display_fps=args.display_fps)
    if out.exists():
        raise ValueError('Use a fresh evidence directory')
    out.mkdir(parents=True)
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1')
    from isolated_windows_desktop import run_on_desktop
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child',
               '--output', str(out), '--display-fps', str(args.display_fps)]
    if args.baseline:
        command.append('--baseline')
    normal = bool(args.exe or args.normal_entry)
    if normal:
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
        fixture = out/'entry.2byteproj'
        save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), fixture)
        env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='preview-clock',
                   TWOBYTEASR_PREVIEW_DISPLAY_FPS=str(args.display_fps), TWOBYTEASR_INVOKER_CWD=str(root),
                   TWOBYTEASR_STARTUP_PROJECT=str(fixture))
        command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root/'quick_start.py')]
    code = run_on_desktop(command, cwd=root, env=env, output=out/'process', timeout=150)
    result = json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    if normal:
        deadline = time.monotonic() + 45
        while not result.get('gui_shutdown') and time.monotonic() < deadline:
            time.sleep(.2)
            result = json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
        if result.get('pid'):
            import psutil
            try:
                child_code = psutil.Process(result['pid']).wait(timeout=20)
                if child_code not in (0, None): code = child_code
            except psutil.NoSuchProcess:
                pass
            except psutil.TimeoutExpired:
                code = 1
        if not result.get('gui_shutdown'): code = 1
    print(json.dumps(dict(output=str(out), exit_code=code, passed=result.get('passed', False),
                         cases=[{k:v for k,v in row.items() if k not in {'samples', 'subtitle_visibility'}}
                                for row in result.get('cases', [])], error=result.get('error'))))
    return 0 if code == 0 and result.get('passed') and result.get('shutdown') else 1


if __name__ == '__main__':
    raise SystemExit(main())
