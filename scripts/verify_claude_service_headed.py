"""The Claude AI service (2026-10-18) in the real app (scenario ``claude-service``).

Usage: python scripts/verify_claude_service_headed.py --output tmp/<fresh dir> [--exe path\\to\\2ByteASR.exe]
       [--theme grape|warm]
Runs on a private Windows desktop with isolated user data; see
twobyteasr/acceptance/claude_service_audit.py for the checks.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LONG_NAME = "录制-企鹅带带北极熊-2026_10_15-20_24_05-异环明音！抽卡看剧情！_1"
LINES = ["大家好欢迎回到直播间", "今天我们继续玩", "先去城堡找一下派蒙", "这里的风景真漂亮", "下一关要小心一点",
         "好的我们出发吧", "谢谢大家的支持", "这个怪有点难打", "我们换个装备试试", "终于打过去了"]


def _ffmpeg(*arguments):
    subprocess.run([str(ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'), '-y', '-v', 'error', *arguments],
                   check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--theme', default='grape')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    if args.exe and not args.exe.resolve().is_file():
        parser.error('--exe must identify an existing executable')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                                    default_style, save_project)

    fixture = output / 'projects' / LONG_NAME / f'{LONG_NAME}.2byteproj'
    fixture.parent.mkdir(parents=True)
    media = fixture.parent / 'claude-service.mp4'
    _ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=8',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=8',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '30', '-c:a', 'aac', '-shortest', str(media))
    cues = []
    for index in range(24):
        start = 200 + index * 320
        # Every third caption runs into the next one (another speaker): something to re-layout.
        cues.append(StudioCue(f'c{index:02d}', start, start + (600 if index % 3 == 0 else 300),
                              LINES[index % len(LINES)], speaker_id='S00' if index % 3 else 'S01'))
    project = SubtitleProject(
        media=StudioMedia(path=str(media), display_name=LONG_NAME, duration_ms=8_000, width=1280, height=720),
        speakers=[StudioSpeaker('S00', 'S00'), StudioSpeaker('S01', 'S01')], styles=[default_style()], cues=cues)
    # Saved with both side panels hidden and dragged down to nothing.
    project.studio_state['layout'] = {'upper_sizes': [0, 1500, 0], 'context_collapsed': True,
                                      'cue_list_visible': False, 'context_visible': False}
    save_project(project, fixture)

    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='claude-service',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_CLAUDE_AUDIT_THEME=args.theme,
               QT_QPA_PLATFORM='windows', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='127.0.0.1,localhost')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    sys.path.insert(0, str(ROOT / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=600)
    receipt = output / 'result.json'
    deadline = time.monotonic() + 60
    result = {}
    while time.monotonic() < deadline:  # launchers may return before the GUI finishes
        try:
            result = json.loads(receipt.read_text('utf8'))
            if result.get('gui_shutdown'):
                break
        except (OSError, ValueError):
            pass
        time.sleep(.2)
    result['launcher_exit'] = code
    result['passed'] = bool(result.get('passed') and code == 0 and result.get('gui_shutdown'))
    import psutil
    pid = result.get('pid')
    if pid and psutil.pid_exists(pid):
        try:
            result['child_exit'] = psutil.Process(pid).wait(timeout=25)
            result['passed'] = bool(result['passed'] and result['child_exit'] == 0)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            result['passed'] = False
            result['error'] = 'Owned claude-service GUI did not exit after normal close'
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    failed = [c['name'] for c in result.get('checks', []) if not c['passed']]
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), failed=failed,
                          launcher_exit=code, error=(result.get('error') or '')[-800:],
                          executable=result.get('executable'), output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
