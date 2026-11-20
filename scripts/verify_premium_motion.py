"""Launch the premium motion audit on the normal isolated Windows app entry."""
import argparse
import os
from pathlib import Path
import sys

from audit_launch_bridge import run_audit_on_desktop


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--scale', default='1')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root / 'tmp'):
        raise ValueError('Choose a fresh output folder under source tmp/')
    output.mkdir(parents=True)
    project = output / 'startup.2byteproj'
    project.write_text('{}', 'utf-8')
    profile = output / 'profile'
    local, roaming = profile / 'local', profile / 'roaming'
    local.mkdir(parents=True)
    roaming.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_TEST_ROOT=str(profile), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_ACCEPTANCE_SCENARIO='premium-motion',
               TWOBYTEASR_STARTUP_PROJECT=str(project), TWOBYTEASR_INVOKER_CWD=str(root), PYTHONUTF8='1', PYTHONPATH='', QT_QPA_PLATFORM='windows',
               QT_SCALE_FACTOR=args.scale, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    return run_audit_on_desktop(command, cwd=root, env=env, output=output,
                                timeout=110, receipt=output / 'result.json')


if __name__ == '__main__':
    raise SystemExit(main())
