"""Run normal Home glossary controls twice with isolated read-only source copies."""
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
    parser.add_argument('--glossary', type=Path, required=True)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use a new task tmp output directory')
    sources = [args.project.resolve(), args.glossary.resolve()]
    if args.settings:
        sources.append(args.settings.resolve())
    protected = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    output.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output),
        TWOBYTEASR_STARTUP_TRACE=str(output / 'driver-startup.jsonl'))
    from twobyteasr.test_isolation import install
    install()
    store = output / 'local/2ByteASR/learned_game_terms.json'
    store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.glossary, store)
    if args.settings:
        shutil.copy2(args.settings, store.parent / '2byteasr_settings.json')
        from twobyteasr.storage.settings import project_settings_path
        stable_settings = project_settings_path()
        stable_settings.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.settings, stable_settings)
        (output / 'settings-seed.json').write_text(json.dumps({
            'source': str(args.settings.resolve()),
            'source_sha256': protected[str(args.settings.resolve())],
            'isolated_stable_path': str(stable_settings),
            'isolated_sha256_before_gui': hashlib.sha256(stable_settings.read_bytes()).hexdigest(),
        }, ensure_ascii=False, indent=2), 'utf8')
    project = output / 'original-project.2byteproj'
    shutil.copy2(args.project, project)
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_STARTUP_TRACE=str(output / 'startup.jsonl'),
        QT_QPA_PLATFORM='windows', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    result = {'passed': False, 'normal_entry_command': command, 'profile': str(output),
              'scope': 'normal glossary UI save/enable/second process; no new ASR'}
    for scenario, name in [('glossary-chain', 'chain-result.json'),
                           ('glossary-chain-restore', 'chain-restore-result.json')]:
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO'] = scenario
        try:
            code = run_on_desktop(command, cwd=ROOT, env=env, output=output / (scenario + '-process'), timeout=90)
        except TimeoutError as exc:
            result[scenario] = {'passed': False, 'error': str(exc)}
            break
        receipt = output / name
        data = json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed': False, 'error': 'No GUI receipt'}
        data['process_exit'] = code
        data['passed'] = bool(data.get('passed') and data.get('gui_shutdown') and code == 0)
        result[scenario] = data
        if not data['passed']:
            break
    result['source_protection'] = [{'path': path, 'sha256_before': digest,
        'sha256_after': hashlib.sha256(Path(path).read_bytes()).hexdigest()} for path, digest in protected.items()]
    result['passed'] = all(result.get(key, {}).get('passed') for key in ('glossary-chain', 'glossary-chain-restore')) and all(
        item['sha256_before'] == item['sha256_after'] for item in result['source_protection'])
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({'passed': result['passed'], 'output': str(output)}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
