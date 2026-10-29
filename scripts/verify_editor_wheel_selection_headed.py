"""Two editor feedback paths through the normal app on a private Windows desktop."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--theme', choices=['warm', 'grape'], default='warm')
    parser.add_argument('--exe', type=Path, help='Frozen candidate or the existing desktop launcher')
    args = parser.parse_args()
    if args.exe and not args.exe.resolve().is_file():
        parser.error('--exe must identify an existing executable')
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/'tmp') or output.exists():
        parser.error('Choose a new directory under this checkout/tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import (
        StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, SubtitleStyle, save_project)
    from twobyteasr.recognition.speaker_roles import decide
    media = output/'fixture.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=c=0x343B42:s=640x360:r=10:d=120',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(media)], check=True)
    project = SubtitleProject(
        media=StudioMedia(str(media), duration_ms=120_000, width=640, height=360),
        styles=[SubtitleStyle('default', 'Default', font_size=48, primary_color='#FFFFFFFF', shadow=0),
                SubtitleStyle('second', 'Second', font_size=72, font_family='Arial',
                              primary_color='#FF99CCFF', outline_color='#FF884422', shadow=0)],
        speakers=[StudioSpeaker('S01', '主讲'), StudioSpeaker('S02', '角色甲'),
                  StudioSpeaker('S03', '角色乙'), StudioSpeaker('S04', '其他轨道')],
        cues=[StudioCue('a', 0, 1800, '主讲字幕', speaker_id='S01'),
              StudioCue('b', 2000, 3800, '角色甲字幕', speaker_id='S02', style_id='second'),
              StudioCue('c', 4000, 5800, '角色乙字幕', speaker_id='S03'),
              StudioCue('d', 6000, 7800, '其他轨道字幕', speaker_id='S04')],
    )
    project.studio_state['speaker_roles'] = decide(
        project, manual={'S01':'main', 'S02':'secondary', 'S03':'secondary', 'S04':'own'})
    fixture = save_project(project, output/'fixture.2byteproj')
    paths = ['studio/studio_timeline.py', 'studio/studio_cue_controller.py',
             'caption_style/studio_style_controller.py', 'caption_style/style_field_patch.py', 'caption_style/scoped_style.py']
    def hashes():
        return {name: hashlib.sha256((ROOT/'twobyteasr'/name).read_bytes()).hexdigest() for name in paths}
    before = hashes()
    env = dict(os.environ, QT_QPA_PLATFORM='windows', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='editor-wheel-selection',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STYLE_AUDIT_THEME=args.theme,
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='localhost,127.0.0.1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for key in ('TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO',
                'TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE'):
        env.pop(key, None)
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT,
                          env=env, output=output/'process', timeout=240)
    receipt = output/'result.json'
    result = {}
    deadline = time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            result=json.loads(receipt.read_text('utf8'))
            if result.get('gui_shutdown'):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    if not result:
        result={'error':'No GUI result'}
    import psutil
    pid=result.get('pid')
    if pid and psutil.pid_exists(pid):
        try:
            result['child_exit']=psutil.Process(pid).wait(timeout=25)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            result['error']='Owned audit GUI did not exit after normal close'
    result.update(launcher_exit=code, source_hashes=before, source_unchanged=before == hashes())
    result['passed'] = bool(result.get('passed') and code == 0 and result.get('gui_shutdown')
                            and result['source_unchanged'] and result.get('child_exit',0)==0 and 'error' not in result)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({key: result.get(key) for key in ('passed', 'launcher_exit', 'gui_shutdown', 'error')},
                     ensure_ascii=False), flush=True)
    print('checks:', len(result.get('checks', [])), 'output:', output)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
