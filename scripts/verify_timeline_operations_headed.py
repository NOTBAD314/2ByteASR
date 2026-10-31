"""Real 573-cue project copy; normal entry, source or frozen, private desktop."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-source', type=Path)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--theme', default='warm')
    parser.add_argument('--scale-factor', default='0.5714285714')
    args = parser.parse_args(); out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        raise ValueError('Use a fresh source/tmp output')
    out.mkdir(parents=True)
    checksum = hashlib.sha256(args.project.read_bytes()).hexdigest()
    payload = json.loads(args.project.read_text('utf-8-sig'))
    payload.pop('autosave', None)
    # Only the copied fixture changes its save/report locations.
    payload['report_path'] = str(out/'reports')
    project = out/'project.2byteproj'
    project.write_text(json.dumps(payload, ensure_ascii=False), 'utf-8')
    (out/'input.json').write_text(json.dumps(dict(project=str(project), theme=args.theme,
        baseline=bool(args.baseline_source), source_sha256=checksum), indent=2), 'utf-8')
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(out), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='timeline-operations', TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_STARTUP_SIZE='1840x1050',
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale_factor, PYTHONUTF8='1', PYTHONFAULTHANDLER='1')
    if args.baseline_source:
        env['TIMELINE_BASELINE_SOURCE'] = str(args.baseline_source.resolve())
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root/'scripts/timeline_operations_entry.py')]
    code = run_on_desktop(command, cwd=root, env=env, output=out/'process', timeout=900)
    result_file = out/'result.json'
    result = json.loads(result_file.read_text('utf-8')) if result_file.exists() else {}
    result.update(process_exit=code, input_unchanged=hashlib.sha256(args.project.read_bytes()).hexdigest()==checksum)
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code==0 and result['input_unchanged'])
    result_file.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    print(json.dumps({k:result.get(k) for k in ('passed','process_exit','error','timings','failures')},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
