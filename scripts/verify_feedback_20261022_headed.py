"""Real-window check of the 2026-10-22 night feedback round through the normal desktop entry.

Copies the user's project library (read only) into a fresh owned tmp directory,
isolates all app data there with the user's look (grape theme, 120 % zoom,
maximized), and runs the in-process `feedback-20261022` scenario
(twobyteasr/acceptance/feedback_20261022_audit.py) on a private Windows desktop.
Use --exe for a frozen candidate.

    python -X utf8 scripts/verify_feedback_20261022_headed.py --library <Projects> --project <relative .2byteproj> --output tmp/<new> [--exe ...]
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

QSETTINGS = "[appearance]\ntheme=grape\n\n[ui]\nzoom_percent=120\n\n[mainWindow]\nmaximized=true\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--project', required=True, help='path of the project inside the library')
    parser.add_argument('--settings', type=Path, help='a 2byteasr_settings.json to copy')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    library = out / 'local/2ByteASR/Projects'
    shutil.copytree(args.library, library)
    project = library / args.project
    assert project.is_file(), project
    if args.settings:
        (out / 'config').mkdir(parents=True)
        shutil.copy2(args.settings, out / 'config/2byteasr_settings.json')
    (out / 'qsettings').mkdir(parents=True)
    (out / 'qsettings/2ByteASR_2ByteASR-9e7a661e4b.ini').write_text(QSETTINGS, 'utf-8')
    media = json.loads(project.read_text('utf-8-sig')).get('media', {}).get('path', '')
    before = Path(media).stat() if media and Path(media).is_file() else None
    (out / 'input.json').write_text(json.dumps(dict(project=str(project)), ensure_ascii=False, indent=2), 'utf-8')
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'),
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='feedback-20261022',
               TWOBYTEASR_STARTUP_PROJECT=str(project),
               TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'), TWOBYTEASR_INVOKER_CWD=str(root),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', QT_QPA_PLATFORM='windows', PYTHONUTF8='1',
               QT_ENABLE_HIGHDPI_SCALING='0', QT_FONT_DPI='96', QT_SCALE_FACTOR='1.75')
    sys.path.insert(0, str(root / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    if args.exe and (args.exe.resolve() == root / '2ByteASR.exe'
                     or (args.exe.resolve().parent / 'dist/2ByteASR/2ByteASR.exe').is_file()):
        command = [sys.executable, str(root / 'scripts/verify_desktop_entry_bridge.py'), str(out), json.dumps(command)]
    code = run_on_desktop(command, cwd=root, env=env, output=out / 'process', timeout=args.timeout)
    result = json.loads((out / 'result.json').read_text('utf-8')) if (out / 'result.json').exists() else dict(passed=False)
    after = Path(media).stat() if media and Path(media).is_file() else None
    result['process_exit'] = code
    result['media_unchanged'] = bool(before and after and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns))
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    shutil.rmtree(library, ignore_errors=True)   # the 680 MB library copy
    print(json.dumps(dict(output=str(out), passed=result.get('passed'), exit=code,
                          checks=[(x['name'], x['passed']) for x in result.get('checks', [])],
                          metrics=result.get('metrics'), error=(result.get('error') or '')[-800:]),
                     ensure_ascii=False, indent=1))
    return 0 if result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
