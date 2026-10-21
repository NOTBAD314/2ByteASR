"""Isolated Windows dialog audit: HTTP stand-in, 91 cues, failure/retry/log copy.

No account access or external network. Run with --output tmp/<fresh directory>.
The dialog is real; only the transport response is substituted.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--normal-entry', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp'):
        parser.error('output must be inside repository tmp')
    if args.worker:
        from twobyteasr.acceptance.translation_requests_audit import run
        return run(output)
    if output.exists():
        parser.error('use a fresh output directory')
    output.mkdir(parents=True)
    env = os.environ.copy()
    env['TWOBYTEASR_TEST_ROOT'] = str(output / 'profile')
    env['QT_QPA_PLATFORM'] = 'windows'
    for key in list(env):
        if key.endswith(('_API_KEY', '_ACCESS_TOKEN', '_AUTH_TOKEN')):
            env.pop(key)
    command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()),
               '--worker', '--output', str(output)]
    if args.exe or args.normal_entry:
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
        from twobyteasr.test_isolation import install
        install()
        from twobyteasr.projects.studio_project import StudioMedia, SubtitleProject, save_project
        fixture = output / 'fixture.2byteproj'
        save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), fixture)
        env.update(TWOBYTEASR_TEST_ROOT=str(output), LOCALAPPDATA=str(output / 'local'),
                   APPDATA=str(output / 'roaming'), TWOBYTEASR_ACCEPTANCE_DIR=str(output),
                   TWOBYTEASR_ACCEPTANCE_SCENARIO='translation-requests',
                   TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
                   TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   TWOBYTEASR_STARTUP_TRACE_FILE=str(output / 'startup.log'))
        for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE',
                    'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO'):
            env.pop(key, None)
        command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=150)
    path = output / 'result.json'
    result = json.loads(path.read_text('utf8')) if path.exists() else {}
    passed = code == 0 and result.get('failed') == 0 and result.get('passed', 0) >= 24
    if args.exe:
        passed = passed and result.get('entry') == 'frozen'
    print(json.dumps(dict(passed=bool(passed), checks=result.get('passed'), exit=code,
                         entry=result.get('entry')), ensure_ascii=False))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
