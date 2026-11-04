"""Normal Windows entry with isolated data and a moving, grayscale media fixture."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--baseline-source', type=Path)
    parser.add_argument('--scale', default='0.7142857143')
    parser.add_argument('--entry', action='store_true')
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    if args.entry:
        product = Path(os.environ.get('PLAYHEAD_BASELINE_SOURCE') or root)
        sys.path.insert(0, str(product))
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.acceptance import studio_acceptance_audit as entry
        from twobyteasr.acceptance.blank_project_audit import install_offline_guards
        install_offline_guards()
        spec = importlib.util.spec_from_file_location('playhead_audit', root/'twobyteasr/acceptance/playhead_selection_audit.py')
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        entry.start_acceptance = lambda window: audit.start(window, entry.audit_directory())
        sys.argv = [str(product/'quick_start.py')]
        runpy.run_path(str(product/'quick_start.py'), run_name='__main__')
        return
    if not args.output:
        parser.error('--output is required')
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root/'tmp'):
        parser.error('Use a fresh directory under this source/tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out/'runner-profile')
    sys.path.insert(0, str(root))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
    media = out/'motion.mp4'
    subprocess.run([str(root/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-f', 'lavfi',
        '-i', 'testsrc2=size=640x360:rate=30:duration=24', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=24',
        '-vf', 'hue=s=0', '-c:a', 'aac', '-c:v', 'libx264', '-preset', 'ultrafast',
        '-pix_fmt', 'yuv420p', '-shortest', str(media)], check=True,
        creationflags=0x08000000)
    project = SubtitleProject(StudioMedia(str(media), duration_ms=24000, width=640, height=360),
        speakers=[StudioSpeaker('S1', 'Speaker')], cues=[
            StudioCue('a', 0, 12000, 'Playback and selection', 'S1'),
            StudioCue('b', 14000, 22000, 'Second caption', 'S1')])
    save_project(project, out/'fixture.2byteproj')
    env = dict(os.environ, TWOBYTEASR_TEST_ROOT=str(out/'profile'),
        TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='playhead-selection',
        TWOBYTEASR_STARTUP_PROJECT=str(out/'fixture.2byteproj'), TWOBYTEASR_STARTUP_OPEN_STUDIO='1',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_SIZE='1600x980',
        TWOBYTEASR_INVOKER_CWD=str(root), QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale,
        PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1')
    if args.baseline_source:
        env['PLAYHEAD_BASELINE_SOURCE'] = str(args.baseline_source.resolve())
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(Path(__file__).resolve()), '--entry']
    code = run_on_desktop(command,
        cwd=root, env=env, output=out/'process', timeout=180)
    result = json.loads((out/'result.json').read_text('utf8')) if (out/'result.json').exists() else {}
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({k:result.get(k) for k in ('passed', 'process_exit', 'failures', 'error')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
