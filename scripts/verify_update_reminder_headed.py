"""Start-up update reminder in the real window: three starts, one profile (2026-10-24).

User request: check for updates every time the program opens, pop up a newer
version by itself, and let the user turn the pop-up off in the settings.

Starts the real program (source, or the frozen EXE with ``--exe``) three times
on a private desktop with one isolated profile; ``UPDATE_REMINDER_PHASE`` tells
``twobyteasr/acceptance/update_reminder_audit.py`` which start it is. The update
answer is a stand-in inside the program: no network, no feed.

usage: python scripts/verify_update_reminder_headed.py --output tmp/<new dir> [--exe <frozen>]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
PHASES = ('first', 'second', 'third')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp') or output.exists():
        raise ValueError('Choose a fresh output directory under repository tmp')
    output.mkdir(parents=True)
    for key in [key for key in os.environ if re.search(r'(API_?KEY|_TOKEN|ACCESS_?KEY)', key, re.IGNORECASE)]:
        os.environ.pop(key)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.storage import settings as settings_module
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    settings = copy.deepcopy(settings_module.DEFAULT_SETTINGS)
    settings_path = settings_module.project_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    entry = save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), output / 'entry.2byteproj')
    env = os.environ.copy()
    # One spelling per variable: the root launcher (.NET) refuses duplicates.
    for key in [key for key in env if key.startswith('TWOBYTEASR_STARTUP_') or key.lower() in
                {'http_proxy', 'https_proxy', 'no_proxy', 'all_proxy'}]:
        env.pop(key)
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='update-reminder',
               TWOBYTEASR_STARTUP_PROJECT=str(entry), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows', PYTHONUTF8='1',
               CUDA_VISIBLE_DEVICES='-1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', NO_PROXY='127.0.0.1,localhost')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    summary = dict(output=str(output), phases={})
    for phase in PHASES:
        started = time.monotonic()
        code = run_on_desktop(command, cwd=ROOT, env=dict(env, UPDATE_REMINDER_PHASE=phase),
                              output=output / f'process-{phase}', timeout=600)
        path = output / f'result-{phase}.json'
        result = json.loads(path.read_text('utf8')) if path.is_file() else {}
        summary['phases'][phase] = dict(passed=bool(code == 0 and result.get('passed') and result.get('gui_shutdown')),
                                        exit_code=code, wall_s=round(time.monotonic() - started, 1),
                                        checks=len(result.get('checks', [])), error=result.get('error'),
                                        failed=[c['name'] for c in result.get('checks', []) if not c['passed']])
        if not summary['phases'][phase]['passed']:
            break
    summary['passed'] = len(summary['phases']) == len(PHASES) and all(p['passed'] for p in summary['phases'].values())
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
