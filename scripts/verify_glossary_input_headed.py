"""Two normal application processes verify fresh local glossary input."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use a fresh output under repository tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    project = output / 'blank.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), project)
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_STARTUP_PROJECT=str(project),
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_STARTUP_TRACE=str(output / 'startup.jsonl'),
        QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    result = {'passed': False, 'scope': 'fresh isolated local input; no original user data/AI/ASR/media'}
    phases = [('glossary-input', 'input-result.json'), ('glossary-input-restore', 'input-restore-result.json')]
    for scenario, name in phases:
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO'] = scenario
        code = run_on_desktop(command, cwd=ROOT, env=env, output=output / (scenario + '-process'), timeout=90)
        receipt = output / name
        check = json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed': False, 'error': 'No GUI receipt'}
        check['process_exit'] = code
        check['passed'] = bool(check.get('passed') and check.get('gui_shutdown') and code == 0)
        result[scenario] = check
        if not check['passed']:
            break
    result['passed'] = all(result.get(scenario, {}).get('passed') for scenario, _ in phases)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'passed': result['passed'], 'output': str(output)}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
