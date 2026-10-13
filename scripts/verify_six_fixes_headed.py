"""Real-window checks for the 2026-10-11 six usage fixes (one phase per run).

Copies a project into a fresh owned tmp directory, isolates all app data
(LOCALAPPDATA, APPDATA, user-data root, Qt settings, network) there, and runs
the in-process `six-fixes` scenario (twobyteasr/six_fixes_audit.py) on a
private Windows desktop. Use --exe for a frozen candidate or the root launcher.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--spec', type=Path, required=True, help='phase parameters (JSON)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    project = out / 'project' / 'six-fixes.2byteproj'
    project.parent.mkdir()
    shutil.copy2(args.project, project)
    spec = json.loads(args.spec.read_text('utf-8'))
    spec.update(phase=args.phase, project=str(project), source=str(args.project))
    (out / 'input.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), 'utf-8')
    env = os.environ.copy()
    for name in ('2BYTEASR_MODEL_ROOT',):
        env.pop(name, None)
    env.update(TWOBYTEASR_TEST_ROOT=str(out), LOCALAPPDATA=str(out / 'local'), APPDATA=str(out / 'roaming'),
               **{'2BYTEASR_USER_DATA_ROOT': str(out / 'local')},
               TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'),
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='six-fixes',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'),
               TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='127.0.0.1,localhost',
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    for leaf in ('local', 'roaming'):
        (out / leaf).mkdir()
    sys.path.insert(0, str(root / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    if args.exe and args.exe.resolve() == root / '2ByteASR.exe':
        command = [sys.executable, str(root / 'scripts/verify_desktop_entry_bridge.py'), str(out), json.dumps(command)]
    code = run_on_desktop(command, cwd=root, env=env, output=out / 'process', timeout=args.timeout)
    result = json.loads((out / 'result.json').read_text('utf-8')) if (out / 'result.json').exists() else dict(passed=False)
    result['process_exit'] = code
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(output=str(out), checks=[(x['name'], x['passed']) for x in result.get('checks', [])],
                          error=result.get('error'), exit=code), ensure_ascii=False, indent=1))
    return 0 if result.get('passed') and code == 0 and result.get('gui_shutdown') else 1


if __name__ == '__main__':
    raise SystemExit(main())
