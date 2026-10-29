"""Real-window screenshots of the redesigned model download window (2026-10-21).

Starts the real app from source on a private desktop with isolated data and lets
``twobyteasr/acceptance/download_window_audit.py`` open the download window in
each state (PyTorch download, packages, weights, slow, stuck, long load, failed,
done) for the chosen themes. Offline: nothing is downloaded. Screenshots and
``result.json`` land in ``--output`` (a fresh folder under the repository tmp/).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def child() -> None:
    """Inside the private desktop: run the app with the audit queued after startup."""
    output = Path(os.environ['TWOBYTEASR_DOWNLOAD_WINDOW_AUDIT'])
    sys.path.insert(0, str(ROOT))
    sys.argv = [str(ROOT / 'quick_start.py')]
    from twobyteasr.app import ui
    from twobyteasr.acceptance.download_window_audit import start
    ui.after_startup_idle(lambda: start(output))
    import runpy
    runpy.run_path(str(ROOT / 'quick_start.py'), run_name='__main__')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--themes', default='grape,warm')
    parser.add_argument('--scale', default='1')
    parser.add_argument('--timeout', type=int, default=420)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    local, roaming, profile = out / 'local', out / 'roaming', out / 'profile'
    for folder in (local, roaming, profile):
        folder.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_TEST_ROOT=str(profile), TWOBYTEASR_DOWNLOAD_WINDOW_AUDIT=str(out),
               TWOBYTEASR_DOWNLOAD_WINDOW_THEMES=args.themes, TWOBYTEASR_INVOKER_ROOT=str(ROOT),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1', PYTHONFAULTHANDLER='1', HF_HUB_OFFLINE='1',
               QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR=args.scale, HTTP_PROXY='http://127.0.0.1:9',
               HTTPS_PROXY='http://127.0.0.1:9', NO_PROXY='127.0.0.1,localhost')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop([sys.executable, '-B', str(Path(__file__).resolve()), '--child'], cwd=ROOT, env=env,
                          output=out / 'process', timeout=args.timeout)
    path = out / 'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=bool(result.get('passed')), exit=code, shots=result.get('shots'),
                   failed=[c for c in result.get('checks', []) if not c['passed']],
                   checks=len(result.get('checks', [])), error=(result.get('error') or '')[-1500:])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    if '--child' in sys.argv:
        child()
    else:
        raise SystemExit(main())
