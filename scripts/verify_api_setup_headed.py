"""Real-window check of the 「申请与设置 API」 dialog on a private desktop (2026-10-14).

Starts the real app (source, or ``--exe``) with an isolated data folder, opens
the dialog for MOSS Pro, 百炼, Qwen Cloud and 讯飞 and checks the step cards,
upload route, address display and offline checks (see
``twobyteasr/api_setup_audit.py``). Offline: no provider is contacted and no
web page is opened. Screenshots and ``result.json`` land in ``--output``.
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
    parser.add_argument('--scale', default='1')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    profile = out / 'profile'
    # The acceptance framework requires its own project and app data under the output.
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(profile)
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import StudioMedia, SubtitleProject, save_project
    fixture = out / 'projects' / 'startup-empty' / 'startup-empty.2byteproj'
    fixture.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='Startup empty', duration_ms=0)), fixture)
    local, roaming = out / 'local', out / 'roaming'
    local.mkdir()
    roaming.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_STARTUP_PROJECT=str(fixture))
    env.update(TWOBYTEASR_TEST_ROOT=str(profile), PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               PYTHONFAULTHANDLER='1', TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='api-setup',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
               QT_SCALE_FACTOR=args.scale, NO_PROXY='127.0.0.1,localhost')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    path = out / 'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=bool(result.get('passed')) and code == 0, exit=code, shutdown=result.get('gui_shutdown'),
                   checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                   errors=result.get('errors'), error=(result.get('error') or '')[-1500:])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
