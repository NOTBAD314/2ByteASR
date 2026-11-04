"""Use the normal application entry and isolated actual user-data copies."""
import argparse
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
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    original = args.original.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp') or not original.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use copied originals and a new output directory under repository tmp')
    projects = list(original.glob('*.2byteproj'))
    if len(projects) != 1:
        raise ValueError('Originals must contain exactly one actual copied project')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    store = output / 'local/2ByteASR/learned_game_terms.json'
    store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original / 'learned_game_terms.json', store)
    project = output / projects[0].name
    shutil.copy2(projects[0], project)
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-manual-case',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_STARTUP_TRACE=str(output / 'startup-trace.jsonl'),
               QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    result = {'passed': False, 'sample': 'actual copied project/glossary; no generated media or new ASR'}
    for scenario, receipt_name in [('glossary-manual-case', 'case-result.json'),
                                   ('glossary-manual-case-restore', 'case-restore-result.json')]:
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO'] = scenario
        try:
            code = run_on_desktop(command, cwd=ROOT, env=env, output=output / (scenario + '-process'), timeout=60)
        except TimeoutError as exc:
            result[scenario] = {'passed': False, 'error': str(exc)}
            break
        receipt = output / receipt_name
        check = json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed': False, 'error': 'No app receipt'}
        check['process_exit'] = code
        check['passed'] = bool(check.get('passed') and check.get('gui_shutdown') and code == 0)
        result[scenario] = check
        if not check['passed']:
            break
    result['passed'] = all(result.get(scenario, {}).get('passed') for scenario in
                           ['glossary-manual-case', 'glossary-manual-case-restore'])
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'passed': result['passed'], 'output': str(output)}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
