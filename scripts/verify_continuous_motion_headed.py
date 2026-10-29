"""Verify the same motion workflow in source and a frozen daily executable."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from isolated_windows_desktop import run_on_desktop

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a fresh directory under tmp/')
    out.mkdir(parents=True)
    sys.path.insert(0, str(ROOT))
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out/'data')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    fixture = save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), out/'fixture.2byteproj')
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'color=c=0x203344:s=960x540:r=60:d=24',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(out/'source.mp4')], check=True)
    env = dict(os.environ, QT_QPA_PLATFORM='windows', PYTHONUTF8='1',
        TWOBYTEASR_TEST_ROOT=str(out/'data'), TWOBYTEASR_ACCEPTANCE_DIR=str(out),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='continuous-motion', TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for key in list(env):
        if key.startswith('TWOBYTEASR_STARTUP_'): env.pop(key)
    env['TWOBYTEASR_STARTUP_PROJECT'] = str(fixture)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out/'process', timeout=180)
    path = out/'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else {}
    passed = code == 0 and result.get('passed') and result.get('gui_shutdown')
    print(json.dumps(dict(passed=bool(passed), checks=len(result.get('checks', [])), exit=code,
                         error=result.get('error')), ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
