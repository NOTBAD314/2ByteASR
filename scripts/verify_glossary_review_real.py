"""Run actual-project Studio acceptance with recorded production responses."""
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
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--glossary', type=Path, required=True)
    parser.add_argument('--replay-plan', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--settings-source', type=Path)
    parser.add_argument('--credential-source', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Choose a new output under repository tmp')
    for supplied in (args.project, args.glossary, args.replay_plan):
        if not supplied.resolve().is_relative_to(ROOT / 'tmp') or not supplied.is_file():
            raise ValueError('Use actual-data copies and measured plans under repository tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    project = output / args.project.name
    shutil.copy2(args.project, project)
    store = output / 'local/2ByteASR/learned_game_terms.json'
    store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.glossary, store)
    shutil.copy2(args.replay_plan, output / 'studio-replay-plan.json')
    if args.live:
        if args.exe or not args.settings_source or not args.credential_source:
            raise ValueError('Live source verification requires the existing settings and readonly credential paths')
        if args.settings_source.name != '2byteasr_settings.json' or args.credential_source.name != 'secrets.dat':
            raise ValueError('Unexpected application settings or credential file')
    if args.settings_source:
        if args.settings_source.name != '2byteasr_settings.json':
            raise ValueError('Unexpected application settings file')
        shutil.copy2(args.settings_source, output / 'config/2byteasr_settings.json')
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-review-real',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_STARTUP_TRACE=str(output / 'startup-trace.jsonl'),
               QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    if args.live:
        env.update(TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-review-live',
                   TWOBYTEASR_ACCEPTANCE_SETTINGS_SOURCE=str(args.settings_source.resolve()),
                   TWOBYTEASR_ACCEPTANCE_CREDENTIAL_SOURCE=str(args.credential_source.resolve()))
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    try:
        code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=60)
    except TimeoutError as exc:
        code = None
        (output / 'driver-timeout.txt').write_text(str(exc), encoding='utf8')
    receipt = output / 'studio-replay-result.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed': False, 'error': 'No app receipt'}
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    if args.live and result.get('passed'):
        import hashlib
        plan = result['frozen_replay_plan']
        plan['source_receipt_sha256'] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        (output / 'frozen-replay-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'passed': result['passed'], 'output': str(output), 'error': result.get('error')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
