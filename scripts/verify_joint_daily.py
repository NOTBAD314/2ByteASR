"""Run combined UI or collision verification from source, a candidate, or the original launcher."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['ui', 'collision'], default='ui')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--legacy-fixture', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a new source/tmp output')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    startup = output/'startup.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='')), startup)
    if args.mode == 'ui':
        subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=0x334155:s=960x540:r=30:d=7', '-c:v', 'libx264', '-preset', 'ultrafast',
                        str(output/'ui-media.mp4')], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    env = dict(os.environ, QT_QPA_PLATFORM='windows', TWOBYTEASR_TEST_ROOT=str(output/'profile'),
               LOCALAPPDATA=str(output/'profile/local'), APPDATA=str(output/'profile/roaming'),
               TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='joint-daily',
               TWOBYTEASR_STARTUP_PROJECT=str(startup), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_JOINT_AUDIT_MODE=args.mode, TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    if args.mode == 'collision':
        if not args.legacy_fixture:
            parser.error('collision mode requires the preserved legacy fixture')
        shutil.copy2(args.legacy_fixture.resolve(), output/'legacy-layout.2byteproj')
        env['TWOBYTEASR_COLLISION_LEGACY_FIXTURE'] = str(output/'legacy-layout.2byteproj')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code = run_audit_on_desktop(command, cwd=ROOT, env=env, output=output,
                              timeout=240, receipt=output/'result.json')
    (output/'process-exit.json').write_text(json.dumps(dict(exit_code=code)), 'utf8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
