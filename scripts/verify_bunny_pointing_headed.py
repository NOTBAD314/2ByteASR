"""Verify live Rabbit UI guidance through the normal Windows entry."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from audit_launch_bridge import run_audit_on_desktop


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--theme', choices=('sand', 'midnight'), default='sand')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(root / 'tmp') or output.exists():
        parser.error('Choose a fresh directory inside repository tmp')
    output.mkdir(parents=True)
    startup = output / 'startup.2byteproj'
    startup.write_text('{}', encoding='utf8')
    env = dict(os.environ, QT_QPA_PLATFORM='windows', PYTHONPATH='', PYTHONUTF8='1',
               TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_ACCEPTANCE_DIR=str(output),
               TWOBYTEASR_ACCEPTANCE_SCENARIO='bunny-pointing', TWOBYTEASR_STARTUP_PROJECT=str(startup),
               TWOBYTEASR_INVOKER_CWD=str(root), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_DIAGNOSTIC_NO_PLAYER='1', TWOBYTEASR_POINT_AUDIT_THEME=args.theme,
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(root / 'quick_start.py')]
    return run_audit_on_desktop(command, cwd=root, env=env, output=output,
                                timeout=240, receipt=output / 'result.json')


if __name__ == '__main__':
    raise SystemExit(main())
