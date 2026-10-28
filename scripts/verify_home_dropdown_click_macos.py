# SPDX-License-Identifier: GPL-3.0-only
"""Real clicks on the home-page dropdowns of a frozen macOS app (2026-10-28).

Mac user: the dropdowns opened and highlighted their rows, but a click chose
nothing. Launches the installed or relocated real 2ByteASR.app through its
normal executable with isolated data and runs the ``home-dropdown-click``
acceptance scenario (``twobyteasr/acceptance/home_dropdown_click_audit.py``):
Quartz mouse events posted to the window server choose 标点 and 字幕显示 rows,
press outside, click the open list's box and press a long list's scroll bar.
``--old-check`` puts the outside-click check from before 2026-10-28 back in the
same app, to show what it did. Offline; no AI.

    python scripts/verify_home_dropdown_click_macos.py --app /Applications/2ByteASR.app --output <abs tmp dir> [--old-check]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True, help='Installed or relocated real 2ByteASR.app')
    parser.add_argument('--output', type=Path, required=True, help='Fresh absolute tmp audit directory')
    parser.add_argument('--old-check', action='store_true', help='the outside-click check before 2026-10-28')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        raise SystemExit('macOS is required for real Quartz clicks')
    from verify_blank_project_macos import audit_boundary, blank_environment
    output, invoker = audit_boundary(args.output)
    app = args.app.resolve()
    executable = app / 'Contents/MacOS/2ByteASR'
    if app.name != '2ByteASR.app' or not executable.is_file():
        raise ValueError('--app must identify an actual frozen 2ByteASR.app')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
    fixture = output / 'projects' / 'existing-zero' / 'existing-zero.2byteproj'
    fixture.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='Existing empty', duration_ms=0)), fixture)
    env = blank_environment(output, invoker, fixture)
    env['TWOBYTEASR_ACCEPTANCE_SCENARIO'] = 'home-dropdown-click'
    if args.old_check:
        env['TWOBYTEASR_DROPDOWN_OLD_CHECK'] = '1'
    summary = dict(passed=False, old_check=args.old_check, expected_executable=str(executable),
                   host=dict(release=platform.mac_ver()[0], machine=platform.machine()), output=str(output))
    process = None
    try:
        with (output / 'dropdown-click.log').open('wb') as stream:
            process = subprocess.Popen([str(executable)], env=env, cwd=invoker, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            summary['exit'] = process.wait(timeout=240)
        result = json.loads((output / 'result.json').read_text('utf8'))
        summary.update(mouse=result.get('mouse'), shutdown=result.get('gui_shutdown'),
                       executable=result.get('executable'), errors=[e[-1500:] for e in result.get('errors', [])],
                       checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                       failed=[c for c in result.get('checks', []) if not c['passed']],
                       records=result.get('records'))
        summary['passed'] = bool(summary['exit'] == 0 and result.get('passed') is True
                                 and result.get('gui_shutdown') is True
                                 and Path(result.get('executable', '')).resolve() == executable)
    except Exception:
        summary['error'] = traceback.format_exc()
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=15)
            except Exception:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except Exception:
                    pass
            summary['killed'] = True
        (output / 'dropdown-click-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                                                            'utf8')
    print(json.dumps({k: summary.get(k) for k in ('passed', 'old_check', 'exit', 'mouse')}, ensure_ascii=False))
    print(json.dumps(summary.get('checks'), ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
