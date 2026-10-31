"""Run real MainWindow/mpv interaction checks in an owned test profile."""
from pathlib import Path
import argparse, json, os, shutil, subprocess, sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--media', type=Path)
    parser.add_argument('--theme', default='warm')
    parser.add_argument('--scale', default='1')
    parser.add_argument('--size', default='1680x1000')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--gui', type=Path, help='Expected GUI when --exe is the original launcher')
    parser.add_argument('--entry-bridge', type=Path)
    parser.add_argument('--visible', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('Use a fresh directory below this source/tmp')
    out.mkdir(parents=True)
    clip = out/'ui-verification.mp4'
    ffmpeg = root/'tools/ffmpeg/bin/ffmpeg.exe'
    command = [str(ffmpeg), '-v', 'error', '-y']
    if args.media:
        command += ['-ss', '60', '-i', str(args.media.resolve())]
    else:
        command += ['-f', 'lavfi', '-i', 'testsrc2=size=960x540:rate=25',
                    '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000']
    command += ['-t', '12', '-vf', 'scale=960:540', '-r', '25', '-c:v', 'libx264',
                '-preset', 'ultrafast', '-crf', '23', '-c:a', 'aac', '-ac', '1', str(clip)]
    subprocess.run(command, check=True, capture_output=True, creationflags=0x08000000)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    sys.path.insert(0, str(root))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioMedia, StudioCue, SubtitleProject, save_project, studio_settings_path
    project = SubtitleProject(media=StudioMedia(str(clip), duration_ms=12000, width=960, height=540),
        cues=[StudioCue('a', 0, 1800, '她在第一条字幕'), StudioCue('b', 2200, 4000, '第二条继续跟随'),
              StudioCue('c', 4500, 7000, '第三条保留当前草稿'), StudioCue('d', 8000, 11000, '确认后跟随此刻')])
    recent = []
    for i in range(9):
        path = save_project(project, out/f'最近工程{i+1}.2byteproj')
        recent.append(dict(path=str(path), name=f'最近工程{i+1} · 界面验收副本', cue_count=4,
                           last_opened=f'2026-10-30T{20-i:02d}:00:00+08:00'))
    settings = studio_settings_path();settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(dict(recent_projects=recent), ensure_ascii=False), encoding='utf8')
    spec = dict(theme=args.theme, recent=recent, visible=args.visible,
                media_kind='12s copy from supplied real media' if args.media else 'marked synthetic AV fixture')
    (out/'input.json').write_text(json.dumps(spec, ensure_ascii=False), encoding='utf8')
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='home-timeline-float',
        TWOBYTEASR_STARTUP_PROJECT=recent[0]['path'], TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_STARTUP_SIZE=args.size,
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale,
        PYTHONUTF8='1', HF_HUB_OFFLINE='1')
    cmd = [sys.executable, '-X', 'utf8', '-B', str(root/'scripts/review_editor_entry.py')]
    if args.exe:
        cmd = [str(args.exe.resolve())]
    if args.gui:
        if args.exe is None or args.entry_bridge is None:
            parser.error('--gui requires --exe and --entry-bridge')
        cmd = [sys.executable, '-B', str(args.entry_bridge.resolve()), '--launcher', str(args.exe.resolve()),
               '--gui', str(args.gui.resolve()), '--output', str(out), '--timeout', '260']
    if args.visible:
        with (out/'process.log').open('wb') as log:
            code = subprocess.run(cmd, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=260, creationflags=0x08000000).returncode
    else:
        sys.path.insert(0, str(root/'scripts'))
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(cmd, cwd=root, env=env, output=out/'process', timeout=260)
    file = out/'result.json'
    result = json.loads(file.read_text('utf8')) if file.exists() else {}
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k:result.get(k) for k in ('passed','process_exit','gui_shutdown','error')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
