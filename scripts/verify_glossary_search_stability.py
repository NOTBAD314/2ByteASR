"""Verify normal source or frozen glossary search on an isolated Windows desktop."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dpr', type=float, default=1)
    parser.add_argument('--idle-seconds', type=float, default=30)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use a fresh output under source/tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    project = output / 'blank.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), project)
    native_scale = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(output),
               TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-search-stability',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
               QT_SCALE_FACTOR=str(args.dpr / native_scale), PYTHONUTF8='1',
               TWOBYTEASR_GLOSSARY_DIAGNOSTICS='1', GLOSSARY_SEARCH_IDLE_SECONDS=str(args.idle_seconds),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TWOBYTEASR_STARTUP_SIZE='1440x900')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=180 + args.idle_seconds * 7)
    receipt = output / 'search-stability.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.is_file() else dict(passed=False, error='No GUI receipt')
    result.update(process_exit=code, requested_dpr=args.dpr, native_scale=native_scale)
    result['passed'] = bool(result['passed'] and result.get('gui_shutdown') and code == 0 and abs(result['dpr'] - args.dpr) < .02)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], error=result.get('error'), dpr=result.get('dpr'), output=str(output)), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
