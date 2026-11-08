"""Normal Studio entry with owned synthetic media/project and native Windows UI."""
import argparse
import ctypes
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
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument('--foreground', action='store_true')
    execution.add_argument('--launcher', type=Path)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--hold-seconds', type=int, default=0)
    parser.add_argument('--dpr', type=float, default=1)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        parser.error('fresh output under source/tmp required')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project
    media = output / 'fixture.mp4'
    subprocess.run([str(ROOT/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-y',
                    '-f', 'lavfi', '-i', 'color=c=0x283d4e:s=960x540:r=25:d=16',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', str(media)], check=True)
    texts = ['今日はここまで。また明日ね。', 'Hello world.  See you tomorrow.', '你好，世界。明天见。', '😀Cafe\u0301 家庭👨‍👩‍👧‍👦 继续']
    cues = [StudioCue(f'cue-{i}', i*3000, i*3000+2800, texts[i % len(texts)]) for i in range(7000)]
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=21_000_000, width=960, height=540), cues=cues)
    project.asr_evidence['aligned'] = dict(words=[dict(text=c, start_ms=i*200, end_ms=i*200+100)
                                               for i,c in enumerate(texts[0])])
    cues[0].evidence_refs = ['aligned']
    target = save_project(project, output/'fixture.2byteproj')
    blank = save_project(SubtitleProject(StudioMedia('')), output/'entry.2byteproj')
    native = ctypes.windll.shcore.GetScaleFactorForDevice(0)/100
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(output),
               TWOBYTEASR_ACCEPTANCE_SCENARIO='caption-caret-split',
               TWOBYTEASR_STARTUP_PROJECT=str(blank), CARET_SPLIT_PROJECT=str(target),
               CARET_SPLIT_HOLD_SECONDS=str(args.hold_seconds),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_MAIN_PYTHON=sys.executable,
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_STARTUP_SIZE='1440x900',
               TWOBYTEASR_MPV=str(ROOT/'tools/mpv/mpv.exe'), QT_QPA_PLATFORM='windows',
               QT_SCALE_FACTOR=str(args.dpr/native), PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    if args.foreground:
        startup = subprocess.STARTUPINFO()
        startup.lpDesktop = 'WinSta0\\Default'
        with (output/'foreground.log').open('wb') as log:
            code = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=log,
                                  startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
                                  timeout=360+args.hold_seconds).returncode
    elif args.launcher:
        from audit_launch_bridge import run_audit_on_desktop
        code = run_audit_on_desktop([str(args.launcher.resolve())], cwd=ROOT, env=env,
                                   output=output, timeout=360, receipt=output/'result.json')
    else:
        from isolated_windows_desktop import run_on_desktop
        code = run_on_desktop(command, cwd=ROOT, env=env, output=output/'process', timeout=360)
    receipt = output/'result.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.exists() else dict(passed=False, error='missing GUI receipt')
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
