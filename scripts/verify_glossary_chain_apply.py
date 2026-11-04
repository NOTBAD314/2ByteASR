"""Reuse the exact UI-saved profile for an isolated authored Studio sample."""
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
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    profile, output = args.profile.resolve(), args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp') or not profile.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use existing task tmp profile and a new task tmp output directory')
    receipt = json.loads((profile / 'chain-result.json').read_text('utf8'))
    if not receipt.get('passed') or not receipt.get('gui_shutdown'):
        raise ValueError('Profile must come from a completed normal glossary UI audit')
    source = profile / 'original-project.2byteproj'
    store = profile / 'local/2ByteASR/learned_game_terms.json'
    protected = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, store)}
    output.mkdir(parents=True)
    project = profile / 'apply-project-copies' / (output.name + '.2byteproj')
    project.parent.mkdir(parents=True, exist_ok=True)
    if project.exists():
        raise ValueError('Apply project copy name already exists')
    shutil.copy2(source, project)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(profile), TWOBYTEASR_STARTUP_TRACE=str(output / 'driver-startup.jsonl'))
    from twobyteasr.test_isolation import install
    install()
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(profile), TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_GLOSSARY_APPLY_OUTPUT=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-chain-apply',
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_STARTUP_TRACE=str(output / 'startup.jsonl'),
        QT_QPA_PLATFORM='windows', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=120)
    receipt_path = output / 'result.json'
    result = json.loads(receipt_path.read_text('utf8')) if receipt_path.is_file() else {'passed': False, 'error': 'No GUI receipt'}
    result['normal_entry_command'] = command
    result['process_exit'] = code
    result['protection'] = [{'path': path, 'before': digest, 'after': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        for path, digest in protected.items()]
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0 and all(
        row['before'] == row['after'] for row in result['protection']))
    receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({'passed': result['passed'], 'output': str(output)}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
