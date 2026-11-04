"""Run saved actual captions through the normal source/frozen Studio entry."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output, plan_path = args.output.resolve(), args.plan.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a fresh task output under repository tmp')
    if not plan_path.is_file() or not plan_path.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a reviewed data plan under repository tmp')
    plan = json.loads(plan_path.read_text('utf8'))
    source = Path(plan['project_path']).resolve()
    if not source.is_relative_to(ROOT/'tmp') or not source.is_file():
        raise ValueError('Use an existing isolated project')
    if hashlib.sha256(source.read_bytes()).hexdigest() != plan['project_sha256']:
        raise ValueError('Reviewed project identity changed')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    startup = output/'startup-copy.2byteproj'
    shutil.copy2(source, startup)
    shutil.copy2(plan_path, output/'review-plan.json')
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='overlap-review-real',
        TWOBYTEASR_STARTUP_PROJECT=str(startup), TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'),
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', PYTHONUTF8='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output/'process', timeout=180)
    receipt = output/'overlap-review-result.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed': False, 'error': 'Missing GUI receipt'}
    result.update(process_exit=code, normal_entry_command=command)
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', 'utf8')
    print(json.dumps({'passed': result['passed'], 'output': str(output), 'error': result.get('error')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
