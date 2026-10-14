"""Theme picker and every theme in the real window, source or frozen (2026-10-14).

Usage: python scripts/verify_theme_gallery_headed.py --output tmp/<fresh dir> [--exe path\\to\\2ByteASR.exe]
Runs on a private Windows desktop with isolated user data; see
twobyteasr/theme_gallery_audit.py for the checks.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--language', help='UI language of the isolated profile (zh, zh-Hant, en, ja, ko…)')
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
    if args.language:
        # Written into the isolated profile only (install() redirected every data root).
        from twobyteasr.settings import load_runtime_settings, save_runtime_settings
        settings, _path, _warnings = load_runtime_settings()
        settings.setdefault('ui', {})['language'] = args.language
        save_runtime_settings(settings)
    from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
    fixture = output / 'projects' / 'theme-fixture' / 'theme-fixture.2byteproj'
    fixture.parent.mkdir(parents=True)
    save_project(SubtitleProject(
        media=StudioMedia(path='', display_name='主题检查', duration_ms=20_000),
        speakers=[StudioSpeaker('S01', '主播'), StudioSpeaker('S02', '嘉宾')],
        cues=[StudioCue(f'c{i}', i * 2500, i * 2500 + 2000, text, speaker_id='S01' if i % 2 == 0 else 'S02')
              for i, text in enumerate(('主题检查第一句', '第二句字幕', '第三句字幕', '第四句字幕'))],
    ), fixture)

    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='theme-gallery',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               QT_QPA_PLATFORM='windows', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='127.0.0.1,localhost')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=420)
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
            result['error'] = 'Owned theme-gallery GUI did not exit after normal close'
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    failed = [c['name'] for c in result.get('checks', []) if not c['passed']]
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), failed=failed,
                          launcher_exit=code, error=(result.get('error') or '')[-600:],
                          executable=result.get('executable'), apply_ms=result.get('apply_ms'),
                          output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
