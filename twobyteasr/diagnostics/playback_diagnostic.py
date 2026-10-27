"""Run the shipped cadence collector with the application's own Python runtime."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import uuid


def runner_command(script):
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--playback-diagnostic']
    return [sys.executable, '-X', 'utf8', str(script)]


def output_root():
    value = os.environ.get('TWOBYTEASR_DIAGNOSTIC_OUTPUT_ROOT')
    root = Path(value).resolve() if value else Path(tempfile.gettempdir()).resolve() / '2ByteASR-playback-diagnostics' / 'tmp'
    if root.name != 'tmp' or root.parent.name != '2ByteASR-playback-diagnostics':
        raise ValueError('Invalid dedicated playback diagnostics directory')
    return root


def main(argv=None):
    args = list(sys.argv[2:] if argv is None else argv)
    frozen = bool(getattr(sys, 'frozen', False))
    root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[2]
    script = root / 'scripts' / 'verify_playback_cadence.py'
    if not script.is_file():
        raise RuntimeError('随包播放诊断脚本缺失：' + str(script))
    # Keep --help a side-effect-free capability check.
    help_only = '--help' in args or '-h' in args
    if not help_only:
        if not args:
            args = ['--generate-media', '--seconds', '20', '--repeat', '3']
        if '--output' not in args:
            folder = output_root() if frozen else root / 'tmp' / 'playback-diagnostics'
            args += ['--output', str(folder / uuid.uuid4().hex)]
        if frozen:
            if '--source' in args:
                raise ValueError('打包诊断只运行实际 EXE；源码对照请使用开发环境。')
            if '--exe' not in args:
                args += ['--exe', sys.executable]
        if '--capture' not in args:
            capture = root / 'tools' / 'diagnostics' / 'capture_desktop_cadence.exe'
            if capture.is_file():
                args += ['--capture', str(capture)]
        # The coordinator also imports project/media helpers. Isolate it before
        # those imports, just as each audited GUI child isolates its own profile.
        from ..test_isolation import install
        diagnostic_root = output_root()
        os.environ['TWOBYTEASR_DIAGNOSTIC_OUTPUT_ROOT'] = str(diagnostic_root)
        coordinator = diagnostic_root / ('coordinator-' + uuid.uuid4().hex)
        os.environ['TWOBYTEASR_TEST_ROOT'] = str(coordinator)
        install()
    old_argv = sys.argv
    sys.argv = [str(script), *args]
    sys.path.insert(0, str(script.parent))
    try:
        spec = importlib.util.spec_from_file_location('_shipped_playback_diagnostic', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.main()
    finally:
        sys.argv = old_argv
        if sys.path[0] == str(script.parent):
            sys.path.pop(0)
