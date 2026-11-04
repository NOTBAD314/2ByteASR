"""Normal source/frozen entry on a private desktop, using owned fixtures."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--scale', default='natural')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    output.mkdir(parents=True)
    env = os.environ.copy()
    for key in ('2BYTEASR_MODEL_ROOT', '2BYTEASR_USER_DATA_ROOT', '2BYTEASR_INSTALL_ROOT',
                'QT_SCALE_FACTOR', 'QT_ENABLE_HIGHDPI_SCALING', 'QT_FONT_DPI'):
        env.pop(key, None)
    env.update(TWOBYTEASR_TEST_ROOT=str(output/'profile'),
               TWOBYTEASR_STARTUP_TRACE=str(output/'startup.jsonl'),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
               TWOBYTEASR_STARTUP_SIZE='1600x950', TWOBYTEASR_ACCEPTANCE_SCENARIO='user-feedback-editor',
               TWOBYTEASR_ACCEPTANCE_DIR=str(output), QT_QPA_PLATFORM='windows', PYTHONUTF8='1')
    if args.scale != 'natural':
        env.update(QT_SCALE_FACTOR=args.scale, QT_ENABLE_HIGHDPI_SCALING='0')
    fixture_code = '''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from twobyteasr.test_isolation import install
install()
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, project_library_root
out = Path(sys.argv[2]); project_library_root().mkdir(parents=True, exist_ok=True)
p = SubtitleProject(media=StudioMedia(str(out/'source.mp4'), duration_ms=10000, width=640, height=360), cues=[
    StudioCue('a',1000,3000,'第一条字幕',speaker_id='S1'),StudioCue('b',5000,6500,'第二条字幕',speaker_id='S1')])
p.validate(); save_project(p,out/'fixture.2byteproj')
'''
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=640x360:rate=25:duration=10', '-c:v', 'libx264', '-preset', 'ultrafast',
                    str(output/'source.mp4')], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run([sys.executable, '-c', fixture_code, str(ROOT), str(output)], env=env, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    env.update(TWOBYTEASR_STARTUP_PROJECT=str(output/'fixture.2byteproj'),
               LOCALAPPDATA=str(output/'profile/local'), APPDATA=str(output/'profile/roaming'))
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output/'process', timeout=150)
    result_path = output/'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.exists() else {}
    print(json.dumps({'exit_code': code, 'passed': result.get('passed'),
                      'checks': len(result.get('checks', [])), 'result': str(result_path)}, ensure_ascii=False))
    return 0 if code == 0 and result.get('passed') and result.get('gui_shutdown') else 1


if __name__ == '__main__':
    raise SystemExit(main())
