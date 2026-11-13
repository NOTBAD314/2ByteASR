"""Run normal application acceptance in a private Windows desktop."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path); args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'): raise ValueError('Use fresh source/tmp output')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    project = output / 'blank.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), project)
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='multilingual-terms',
        TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        QT_QPA_PLATFORM='windows', PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TWOBYTEASR_STARTUP_SIZE='1440x960')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=180)
    receipt = output / 'multilingual-terms.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.exists() else dict(passed=False, error='No GUI receipt')
    result['process_exit'] = code; result['passed'] = result['passed'] and code == 0
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
