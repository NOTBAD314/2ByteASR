"""Normal Windows app, actual mpv pipes, isolated media and owned faults."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=10)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--launcher', type=Path)
    parser.add_argument('--entry-bridge', type=Path)
    parser.add_argument('--no-faults', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root/'tmp'):
        parser.error('Choose a fresh output below source/tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    sys.path.insert(0, str(root))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    ffmpeg = next((root/'tools/ffmpeg').rglob('ffmpeg.exe'))
    projects = []
    for name, size, encoder, frequency in [('A', '640x360', 'libx264', 440), ('B', '360x640', 'libx265', 880)]:
        media = output/f'{name}.mp4'
        subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', f'testsrc2=size={size}:rate=30:duration=12', '-f', 'lavfi',
            '-i', f'sine=frequency={frequency}:sample_rate=48000:duration=12',
            '-c:v', encoder, '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', str(media)], check=True, creationflags=0x08000000)
        width, height = map(int, size.split('x'))
        project = SubtitleProject(StudioMedia(str(media), duration_ms=12000, width=width, height=height),
            cues=[StudioCue('cue-1', 0, 11000, f'播放器恢复验证 {name}')])
        projects.append(str(save_project(project, output/f'{name}.2byteproj')))
    (output/'input.json').write_text(json.dumps(dict(projects=projects, cycles=args.cycles,
        faults=not args.no_faults, media_note='synthetic H.264/AAC and portrait HEVC/AAC; no Dolby Vision')), 'utf8')
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='player-recovery',
        TWOBYTEASR_STARTUP_PROJECT=projects[0], TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_STARTUP_SIZE='1400x900', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
        TWOBYTEASR_INVOKER_CWD=str(root), QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='0.5714285714',
        PYTHONUTF8='1', HF_HUB_OFFLINE='1')
    command = ([str(args.exe.resolve())] if args.exe else
               [sys.executable, '-B', '-X', 'utf8', str(root/'scripts/player_recovery_entry.py')])
    if args.launcher:
        if not args.exe or not args.entry_bridge:
            parser.error('--launcher needs --exe and --entry-bridge')
        command = [sys.executable,'-B',str(args.entry_bridge.resolve()),'--launcher',str(args.launcher.resolve()),
                   '--gui',str(args.exe.resolve()),'--output',str(output),'--timeout','520']
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=root, env=env, output=output/'process', timeout=540)
    result_file = output/'result.json'
    result = json.loads(result_file.read_text('utf8')) if result_file.exists() else {}
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
    print(json.dumps(dict(passed=result['passed'],process_exit=code,error=result.get('error'),
        checks=len(result.get('checks',[])),faults=result.get('faults',[]),resources=result.get('resources',[])),ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
