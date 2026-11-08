"""Offline normal-entry check for speech-gap UI, partial save and undo/redo."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--launcher', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root/'tmp'):
        raise ValueError('Use a fresh directory inside this source tmp')
    output.mkdir(parents=True)
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(output), QT_QPA_PLATFORM='windows',
        TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='speech-coverage',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_SIZE='1440x900',
        TWOBYTEASR_STARTUP_PROJECT=str(output/'fixture.2byteproj'), TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_STARTUP_TRACE=str(output/'startup-trace.jsonl'), TWOBYTEASR_INVOKER_CWD=str(root),
        PYTHONUTF8='1')
    # Install isolation before importing project storage or QSettings.
    os.environ.update(env)
    sys.path.insert(0, str(root))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import SubtitleProject, StudioCue, StudioMedia, save_project
    from twobyteasr.recognition.speech_coverage import make_state, KEY
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions
    media = output/'fixture.mp4'
    subprocess.run([str(root/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y', '-nostdin',
        '-f', 'lavfi', '-i', 'color=c=0x171923:s=640x360:r=10', '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono',
        '-t', '30', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'aac', str(media)],
        check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    project = SubtitleProject(media=StudioMedia(path=str(media), duration_ms=30000, width=640, height=360),
        cues=[StudioCue('before', 1000, 3000, '前方人工字幕', 'HOST', original_text='原来文字'),
              StudioCue('after', 25000, 27000, '后方正常字幕', 'HOST')])
    project.generation_metadata[KEY] = make_state([dict(start=10, end=20, speech_verified=True)], [], duration=30)
    ensure_independent_captions(project)
    save_project(project, output/'fixture.2byteproj')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root/'quick_start.py')]
    if args.launcher:
        (output/'entry-plan.json').write_text(json.dumps(dict(command=[str(args.launcher.resolve())],
            case='project', project=str(output/'fixture.2byteproj'), bridge='root-launcher', invoker_cwd=str(root))), 'utf8')
        bridge = output/'launch_bridge.py'
        bridge.write_text((root/'scripts/external_entry_launch_bridge.py').read_text('utf8').replace(
            "'entry-result.json'", "'result.json'"), 'utf8')
        command = [sys.executable, '-B', str(bridge), str(output)]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=root, env=env, output=output/'process', timeout=180)
    result_path = output/'result.json'
    result = json.loads(result_path.read_text('utf8')) if result_path.is_file() else dict(passed=False, error='No GUI receipt')
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and code == 0)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
