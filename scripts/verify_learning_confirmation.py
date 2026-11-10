"""Normal source, frozen GUI and original-launcher terminology review checks."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--dpr', type=float, default=1)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use a fresh output under source/tmp')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    media = output / 'fixture.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y',
        '-f', 'lavfi', '-i', 'color=c=0x283d4e:s=960x540:r=25:d=8',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', str(media)], check=True)
    texts = ['今天天气很好', '你好，世界', '那维来特登场', '星见鸦很强', '这把用福宁娜', '又是那维来特']
    project = SubtitleProject(StudioMedia(str(media), duration_ms=8000, width=960, height=540),
        cues=[StudioCue(f'cue-{i}', i*1000, i*1000+900, text) for i, text in enumerate(texts)])
    target = save_project(project, output/'fixture.2byteproj')
    blank = save_project(SubtitleProject(StudioMedia('')), output/'entry.2byteproj')
    native = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='learning-confirmation',
        TWOBYTEASR_STARTUP_PROJECT=str(blank), LEARNING_REVIEW_PROJECT=str(target),
        TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_MAIN_PYTHON=sys.executable,
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_SIZE='1440x900',
        TWOBYTEASR_MPV=str(ROOT/'tools/mpv/mpv.exe'), QT_QPA_PLATFORM='windows',
        QT_SCALE_FACTOR=str(args.dpr/native), PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    from audit_launch_bridge import run_audit_on_desktop
    code = run_audit_on_desktop(command, cwd=ROOT, env=env, output=output,
        timeout=240, receipt=output/'result.json')
    receipt = output/'result.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.exists() else dict(passed=False, error='No GUI receipt')
    result['process_exit'] = code
    result['passed'] = bool(result['passed'] and result.get('gui_shutdown') and code == 0)
    if result['passed']:
        restart = output/'restart'
        restart.mkdir()
        shutil.copy2(blank, restart/'entry.2byteproj')
        restart_env = dict(env, TWOBYTEASR_ACCEPTANCE_DIR=str(restart),
            TWOBYTEASR_ACCEPTANCE_PROFILE_DIR=str(output), TWOBYTEASR_STARTUP_PROJECT=str(restart/'entry.2byteproj'),
            LEARNING_REVIEW_PHASE='restart', LEARNING_REVIEW_STATE=str(output/'restart-state.json'))
        restart_code = run_audit_on_desktop(command, cwd=ROOT, env=restart_env, output=restart,
            timeout=180, receipt=restart/'result.json')
        restarted = json.loads((restart/'result.json').read_text('utf8')) if (restart/'result.json').exists() else dict(passed=False, error='No restart GUI receipt')
        result['restart'] = restarted
        result['passed'] = bool(restarted.get('passed') and restarted.get('gui_shutdown') and restart_code == 0)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), error=result.get('error')), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
