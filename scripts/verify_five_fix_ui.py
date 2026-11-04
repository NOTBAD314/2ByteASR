"""Normal private-desktop source/frozen UI audit, using copied real projects."""
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
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--completion-project', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--scale', choices=('1', '1.25', '1.5'), default='1')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a fresh output directory under repository tmp')
    if not args.project.is_file():
        parser.error('The real speaker project is required')
    if args.report and not args.completion_project:
        parser.error('--report requires its own --completion-project so separate tasks cannot be conflated')
    output.mkdir(parents=True)
    fixture = output/'inputs'
    fixture.mkdir()
    inputs = dict(requested_scale=args.scale, original_files={},
        ime_scope='QInputMethodEvent preedit/commit delivered to the real QLineEdit; physical Windows IME not exercised',
        terminal_scope='retained report replay' if args.report else 'controlled success callback from an existing project; no new ASR')
    for key, source in (('project', args.project), ('completion_project', args.completion_project), ('report', args.report)):
        if source is None:
            continue
        if not source.is_file():
            parser.error('Every supplied input must be an existing file')
        source = source.resolve()
        target = fixture/(key+source.suffix)
        shutil.copy2(source, target)
        inputs[key] = str(target)
        inputs['original_files'][str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    (output/'input.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2), 'utf8')
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='five-fix-ui',
        TWOBYTEASR_STARTUP_PROJECT=inputs['project'], TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'),
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING='0',
        QT_FONT_DPI='96', QT_SCALE_FACTOR_ROUNDING_POLICY='PassThrough', PYTHONUTF8='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output/'process', timeout=240)
    receipt = output/'result.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.is_file() else dict(passed=False, error='No normal GUI receipt')
    result.update(process_exit=code, normal_entry_command=command)
    result['original_file_hashes_unchanged'] = all(Path(path).is_file() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha
        for path, sha in inputs['original_files'].items())
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0
        and result['original_file_hashes_unchanged'] and result.get('provider_calls') == 0)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], output=str(output), error=result.get('error')), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
