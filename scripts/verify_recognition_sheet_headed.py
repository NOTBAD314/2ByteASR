"""Real-window check of the Studio 「识别字幕」 sheet with 高级配置 open (2026-10-22).

Starts the real app (source, or ``--exe``) on a private desktop with an
isolated data folder, opens a small fixture project in Studio and runs the
``recognition-sheet`` acceptance scenario
(``twobyteasr/acceptance/recognition_sheet_audit.py``): the sheet at full and
at minimum card height, 高级配置 expanded, every row at its full height, the last
button reachable by scrolling. Screenshots and ``result.json`` land in
``--output``.

    python -X utf8 scripts/verify_recognition_sheet_headed.py --output tmp/<new folder> [--scale 1.75] [--theme grape]
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
    parser.add_argument('--scale', default='1.75')
    parser.add_argument('--theme', default='grape')
    parser.add_argument('--timeout', type=int, default=600)
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
    from verify_ui_polish_headed import _fixture
    fixture = _fixture(out)
    local, roaming = out / 'local', out / 'roaming'
    local.mkdir()
    roaming.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_TEST_ROOT=str(profile), PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONFAULTHANDLER='1',
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='recognition-sheet',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
               QT_ENABLE_HIGHDPI_SCALING='0', QT_FONT_DPI='96', QT_SCALE_FACTOR=args.scale,
               NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
               TWOBYTEASR_RECOGNITION_SHEET_THEME=args.theme)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    path = out / 'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=bool(result.get('passed')) and code == 0 and bool(result.get('gui_shutdown')), exit=code,
                   shutdown=result.get('gui_shutdown'), executable=result.get('executable'),
                   checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                   errors=[e[-800:] for e in result.get('errors', [])])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
