"""Real-window check: a click on a home-page dropdown row chooses it (2026-10-28).

Starts the real app (source, or ``--exe`` for a frozen candidate) on a private
desktop with an isolated data folder and runs the ``home-dropdown-click``
acceptance scenario (``twobyteasr/acceptance/home_dropdown_click_audit.py``):
标点 and 字幕显示 rows chosen by native mouse messages, routed the Windows way
and by the window under the pointer; a press outside, a click on the open list's box, and a
press on a long list's scroll bar. Offline; no AI. Nothing is read from or
written to the real user data. ``--old-check`` puts the outside-click check
from before 2026-10-28 back, to show on the same code what it did.

    python -X utf8 scripts/verify_home_dropdown_click_headed.py --output tmp/<new folder> [--theme grape] [--old-check]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--zoom', type=int, default=120)
    parser.add_argument('--theme', default='grape')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--old-check', action='store_true', help='the outside-click check before 2026-10-28')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    profile = out / 'profile'
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(profile)
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.app import ui_zoom
    ui_zoom.set_zoom_percent(args.zoom)   # isolated QSettings shared with the app (same test root)
    from verify_ui_polish_headed import _fixture
    fixture = _fixture(out)   # the acceptance runner requires its own copied project
    local, roaming = out / 'local', out / 'roaming'
    local.mkdir()
    roaming.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_TEST_ROOT=str(profile), PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONFAULTHANDLER='1',
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='home-dropdown-click',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
               NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
               TWOBYTEASR_HOME_AI_THEME=args.theme)
    if args.old_check:
        env['TWOBYTEASR_DROPDOWN_OLD_CHECK'] = '1'
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    path = out / 'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=bool(result.get('passed')) and code == 0 and bool(result.get('gui_shutdown')), exit=code,
                   shutdown=result.get('gui_shutdown'), executable=result.get('executable'),
                   checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                   failed=[c for c in result.get('checks', []) if not c['passed']],
                   errors=[e[-1500:] for e in result.get('errors', [])])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
