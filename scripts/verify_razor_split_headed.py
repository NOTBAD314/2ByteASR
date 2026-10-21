"""Real-window razor word-split check through the normal desktop entry.

Copies a project into a fresh owned tmp directory, isolates all app data
there, and runs the in-process `razor-word-split` scenario
(twobyteasr/acceptance/razor_split_audit.py) on a private Windows desktop. Use --exe for
a frozen candidate or the root launcher (bridged to the real GUI process).
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path


SPEC = dict(
    text='主播投的是对面的没挡眼睛的哥哥',
    min_measured=63,
    positions=[5300, 6448, 6580, 7560],
    click_ms=6448,
    second_ms=7000,
    ripple=[1000, 1500],
    ripple_probe_ms=5300,
    ripple_expect_left='主播投的是',
    edited_text='主播投的是对面那个',
    edited_probe_ms=5800,
    edited_expect_left='主播投的是对',
    merge_first='因为我觉得他看局势',
    merge_second='可能会看得更清楚一些啊',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    project = out / 'razor-project.2byteproj'
    shutil.copy2(args.project, project)
    (out / 'input.json').write_text(json.dumps(dict(SPEC, project=str(project), source=str(args.project)),
                                               ensure_ascii=False, indent=2), 'utf-8')
    env = os.environ.copy()
    env.update(TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_STARTUP_TRACE=str(out / 'startup.jsonl'),
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='razor-word-split',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_SEEK_CACHE_ROOT=str(out / 'seek-cache'),
               TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    sys.path.insert(0, str(root / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    if args.exe and args.exe.resolve() == root / '2ByteASR.exe':
        command = [sys.executable, str(root / 'scripts/verify_desktop_entry_bridge.py'), str(out), json.dumps(command)]
    code = run_on_desktop(command, cwd=root, env=env, output=out / 'process', timeout=900)
    result = json.loads((out / 'result.json').read_text('utf-8')) if (out / 'result.json').exists() else dict(passed=False)
    result['process_exit'] = code
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(output=str(out), checks=[(x['name'], x['passed']) for x in result.get('checks', [])],
                          error=result.get('error'), exit=code), ensure_ascii=False, indent=1))
    return 0 if result.get('passed') and code == 0 and result.get('gui_shutdown') else 1


if __name__ == '__main__':
    raise SystemExit(main())
