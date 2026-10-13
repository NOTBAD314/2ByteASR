# SPDX-License-Identifier: GPL-3.0-only
"""Verify normal frozen macOS blank-project creation, save and reopen controls."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def audit_boundary(value: Path) -> tuple[Path, Path]:
    if not value.is_absolute():
        raise ValueError('Select a new absolute disposable tmp output')
    output = value.resolve()
    if output.exists():
        raise ValueError('The blank-project output must be fresh')
    for parent in output.parents:
        if parent.name.casefold() == 'tmp':
            return output, parent.parent
    raise ValueError('The blank-project output must remain within a tmp boundary')


def blank_environment(output: Path, invoker: Path, fixture: Path) -> dict:
    """Preserve window-server essentials and explicitly isolate writable data."""
    env = {key: os.environ[key] for key in ('HOME', 'LANG', 'LC_ALL', 'DISPLAY') if key in os.environ}
    env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', PYTHONNOUSERSITE='1', PYTHONUTF8='1',
               TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_INVOKER_CWD=str(invoker),
               TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='blank-project',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               LOCALAPPDATA=str(output/'local'), APPDATA=str(output/'roaming'),
               TEMP=str(output/'temp'), TMP=str(output/'temp'), TMPDIR=str(output/'temp'),
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    return env


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True, help='Installed or relocated real 2ByteASR.app')
    parser.add_argument('--output', type=Path, required=True, help='Fresh absolute tmp audit directory')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('Native Apple Silicon macOS is required for real blank-project GUI acceptance')
    output, invoker = audit_boundary(args.output)
    app = args.app.resolve()
    executable = app/'Contents/MacOS/2ByteASR'
    if app.name != '2ByteASR.app' or not executable.is_file():
        raise ValueError('--app must identify an actual frozen 2ByteASR.app')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.studio_project import StudioMedia, SubtitleProject, save_project
    fixture = output/'projects'/'existing-zero'/'existing-zero.2byteproj'
    fixture.parent.mkdir(parents=True)
    save_project(SubtitleProject(media=StudioMedia(path='', display_name='Existing empty', duration_ms=0)), fixture)
    # Preserve only the window-server essentials. No host provider keys,
    # Python/runtime overrides or model/cache registration enter this launch.
    env = blank_environment(output, invoker, fixture)
    summary = dict(passed=False, expected_executable=str(executable), minimal_path=env['PATH'],
                   output=str(output), normal_application_entry=True)
    log = output/'blank-project.log'
    receipt = output/'result.json'
    process = None
    try:
        with log.open('wb') as stream:
            process = subprocess.Popen([str(executable)], env=env, cwd=invoker,
                                       stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            summary['launcher_pid'] = process.pid
            summary['launcher_exit'] = process.wait(timeout=180)
        result = json.loads(receipt.read_text('utf8'))
        summary['application_result'] = result
        summary['identity'] = identity = result.get('identity', {})
        checks = result.get('checks', [])
        summary['checks'] = len(checks)
        summary['passed'] = bool(summary['launcher_exit'] == 0 and result.get('passed') is True
                                 and result.get('gui_shutdown') is True and len(checks) >= 36
                                 and all(check.get('passed') is True for check in checks)
                                 and result.get('provider_calls') == 0
                                 and not result.get('external_connections_blocked')
                                 and identity.get('packaged') is True
                                 and Path(identity.get('executable_path', '')).resolve() == executable
                                 and Path(result.get('executable', '')).resolve() == executable)
        if not summary['passed']:
            summary['error'] = 'Normal frozen blank-project checks, shutdown or exact identity did not pass'
    except Exception:
        summary['error'] = traceback.format_exc()
        if receipt.is_file():
            try:
                summary['application_result'] = json.loads(receipt.read_text('utf8'))
                summary['identity'] = summary['application_result'].get('identity', {})
            except (OSError, ValueError):
                pass
    finally:
        if process is not None and process.poll() is None:
            # Only this audit's fresh session/process group can be stopped.
            summary['normal_exit'] = False
            try:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=15)
            except Exception:
                summary['cleanup_error'] = traceback.format_exc()
        else:
            summary['normal_exit'] = bool(process is not None and process.returncode == 0)
        (output/'blank-project-summary.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2)+'\n', 'utf8')
    print(json.dumps(dict(passed=summary['passed'], checks=summary.get('checks'),
                          launcher_exit=summary.get('launcher_exit'), identity=summary.get('identity'),
                          output=str(output)), ensure_ascii=False))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
