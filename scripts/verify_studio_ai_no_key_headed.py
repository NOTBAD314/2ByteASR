"""Real window: user-clicked AI actions without an API key (2026-10-15).

Studio's 「AI 断句」 menu entries, the AI 词库校对 page's 「AI 校对」 and the
result page's 「AI 词库校对…」 entry, first with no key anywhere (each shows
「这个功能要用 AI，需要先填 API Key」 and sends nothing), then with a key for a
loopback stand-in (they run as before). See
twobyteasr/acceptance/ai_actions_no_key_audit.py for the checks.

User data is redirected to the output folder; key variables are removed from
the environment; only loopback connections are allowed; no paid call.

usage: python scripts/verify_studio_ai_no_key_headed.py --output tmp/<new dir> [--exe <frozen candidate>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


def _ffmpeg(*arguments):
    subprocess.run([str(ROOT / 'tools' / 'ffmpeg' / 'bin' / 'ffmpeg.exe'), '-y', '-v', 'error', *arguments],
                   check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    if args.exe and not args.exe.resolve().is_file():
        parser.error('--exe must identify an existing executable')
    output.mkdir(parents=True)
    # No key may come from the environment (DEEPSEEK_API_KEY, DASHSCOPE_API_KEY, ...).
    removed = sorted(key for key in os.environ if re.search(r'(API_?KEY|_TOKEN|ACCESS_?KEY)', key, re.IGNORECASE))
    for key in removed:
        os.environ.pop(key)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()   # LOCALAPPDATA / APPDATA / user data root inside the output folder
    import subtitle_core as legacy
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
    from twobyteasr.recognition.recognition_result import (committed_result_reference, media_identity_for_task,
                                                           stamp_result)

    library = legacy.create_learned_content('原神', create_new=True)
    for term in ('芙宁娜', '那维莱特'):
        legacy.add_learned_mapping(library, term, term, category='角色', origin='手动')
    legacy.add_learned_mapping(library, '芙宁那', '芙宁娜', category='角色', origin='手动')

    job_id = 'ai-no-key-job'
    folder = output / 'projects' / f'ai-no-key__{job_id}_1'
    for child in ('subtitles', 'reports', 'source', 'autosave', 'cache', 'preview', 'backup', 'renders', 'exports'):
        (folder / child).mkdir(parents=True, exist_ok=True)
    media = folder / 'source' / 'ai-no-key.mp4'
    _ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=12',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=12',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '30', '-c:a', 'aac', '-shortest', str(media))
    project_path = folder / 'ai-no-key.2byteproj'
    project = SubtitleProject(
        media=StudioMedia(path=str(media), display_name='没填 Key 的 AI 功能', duration_ms=12_000, width=1280, height=720),
        cues=[StudioCue('c0', 1000, 3500, '然后她来到了那维莱特的家，大家一起吃饭聊天'),
              StudioCue('c1', 4500, 6500, '芙宁那说她马上到'),
              StudioCue('c2', 8000, 9500, '最后一句')],
        glossary_ids=[library])
    # As if an earlier AI 断句 left one caption unfinished: 「仅重试失败范围」 is enabled.
    project.studio_state['ai_sentence_refine'] = {'failed_cue_ids': ['c1'], 'last_status': 'failed'}
    save_project(project, project_path)
    stamped = load_project(project_path)
    stamp_result(stamped, project_path, job_id=job_id, media_identity=media_identity_for_task(str(media)))
    save_project(stamped, project_path)
    reference = committed_result_reference(load_project(project_path), project_path)
    (output / 'delivery.json').write_text(json.dumps(dict(
        project_path=str(project_path), result_ref_json=json.dumps(reference, ensure_ascii=False), job_id=job_id,
        media_path=str(media), library=library), ensure_ascii=False, indent=2), 'utf8')

    env = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE',
                'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
        env.pop(key, None)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='ai-actions-no-key',
               TWOBYTEASR_STARTUP_PROJECT=str(project_path), TWOBYTEASR_STARTUP_RAISE='1',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SEEK_CACHE_ROOT=str(output / 'seek'),
               QT_QPA_PLATFORM='windows', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='127.0.0.1,localhost')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    started = time.monotonic()
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=900)
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
    result['wall_s'] = round(time.monotonic() - started, 1)
    result['environment_keys_removed'] = removed
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
            result['error'] = 'Owned ai-actions-no-key GUI did not exit after normal close'
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    failed = [c['name'] for c in result.get('checks', []) if not c['passed']]
    print(json.dumps(dict(passed=result['passed'], checks=len(result.get('checks', [])), failed=failed,
                          launcher_exit=code, error=(result.get('error') or '')[-1500:],
                          blocked=result.get('blocked_external_connections'),
                          screenshots=result.get('screenshots'), output=str(output)), ensure_ascii=False), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
