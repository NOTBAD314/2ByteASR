"""Real-window check of the 2026-10-22 split report through the normal desktop entry.

Copies the user's project into a fresh owned tmp directory, isolates all app
data there, and runs the in-process `ja-split-report` scenario
(twobyteasr/acceptance/ja_split_report_audit.py) on a private Windows desktop.
The project's media is only read. Use --exe for a frozen candidate.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# The user's two cuts in 《日常》第10话 (pointer positions from their diagnostics).
CASES = [
    dict(text='なになに私に対してのこの遅刻制裁は', pointer_ms=204641,
         left='なになに私に対してのこの遅刻', right='制裁は'),
    dict(text='後ろからこっそり入ればいいじゃないですか', pointer_ms=211117,
         left='後ろからこっそり', right='入ればいいじゃないですか'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    project = out / 'split-report.2byteproj'
    shutil.copy2(args.project, project)
    media = json.loads(project.read_text('utf-8-sig')).get('media', {}).get('path', '')
    before = Path(media).stat() if media and Path(media).is_file() else None
    (out / 'input.json').write_text(json.dumps(dict(cases=CASES, project=str(project), source=str(args.project)),
                                               ensure_ascii=False, indent=2), 'utf-8')
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'),
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='ja-split-report',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'),
               TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    sys.path.insert(0, str(root / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    if args.exe and (args.exe.resolve() == root / '2ByteASR.exe'
                     or (args.exe.resolve().parent / 'dist/2ByteASR/2ByteASR.exe').is_file()):
        # The repository-root launcher returns at once; wait for the real GUI process.
        command = [sys.executable, str(root / 'scripts/verify_desktop_entry_bridge.py'), str(out), json.dumps(command)]
    code = run_on_desktop(command, cwd=root, env=env, output=out / 'process', timeout=args.timeout)
    result = json.loads((out / 'result.json').read_text('utf-8')) if (out / 'result.json').exists() else dict(passed=False)
    after = Path(media).stat() if media and Path(media).is_file() else None
    result['process_exit'] = code
    result['media_unchanged'] = bool(before and after and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns))
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(output=str(out), checks=[(x['name'], x['passed']) for x in result.get('checks', [])],
                          cases=[{k: c.get(k) for k in ('pointer_ms', 'cut_ms', 'left', 'right', 'left_translation',
                                                        'right_translation', 'status')} for c in result.get('cases', [])],
                          error=(result.get('error') or '')[-1500:], exit=code,
                          media_unchanged=result['media_unchanged']), ensure_ascii=False, indent=1))
    return 0 if result.get('passed') and code == 0 and result.get('gui_shutdown') else 1


if __name__ == '__main__':
    raise SystemExit(main())
