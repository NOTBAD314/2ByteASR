"""Run caption placement and Chinese grouping through an installed native app."""
from pathlib import Path
import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_blank_project_macos import audit_boundary, blank_environment
from scripts.macos_caret_split_smoke import prepare_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scenario', choices=['stable-captions', 'chinese-complete-expression'], required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('Native Apple Silicon macOS is required')
    output, invoker = audit_boundary(args.output)
    executable = args.app.resolve() / 'Contents/MacOS/2ByteASR'
    if not executable.is_file():
        raise ValueError('An installed 2ByteASR.app is required')
    output.mkdir(parents=True)
    ffmpeg = args.app.resolve() / 'Contents/Resources/tools/ffmpeg/bin/ffmpeg'
    if not ffmpeg.is_file():
        ffmpeg = args.app.resolve() / 'Contents/Frameworks/tools/ffmpeg/bin/ffmpeg'
    result = dict(passed=False, scenario=args.scenario, expected_executable=str(executable))
    process = None
    try:
        target = prepare_fixture(output, ffmpeg)
        env = blank_environment(output, invoker, target)
        env['TWOBYTEASR_ACCEPTANCE_SCENARIO'] = args.scenario
        with (output / 'caption-policy.log').open('wb') as stream:
            process = subprocess.Popen([str(executable), str(target)], cwd=invoker, env=env,
                stdout=stream, stderr=stream, start_new_session=True)
            result['process_exit'] = process.wait(timeout=660)
        audit = json.loads((output / 'result.json').read_text('utf8'))
        identity = json.loads((output / 'local/2ByteASR/logs/build_identity.json').read_text('utf8'))
        checks = audit.get('checks', [])
        expected_checks = 50 if args.scenario == 'stable-captions' else 17
        result.update(application_result=audit, identity=identity, checks=len(checks))
        result['passed'] = (result['process_exit'] == 0 and audit.get('passed') is True
            and len(checks) >= expected_checks and all(row['passed'] for row in checks)
            and identity.get('packaged') is True
            and Path(identity.get('executable_path', '')).resolve() == executable)
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        from scripts.macos_desktop_smoke import preserve_diagnostics
        preserve_diagnostics(output)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
        (output / 'caption-policy-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], checks=result.get('checks'))))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
