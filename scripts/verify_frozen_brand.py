"""Launch source or a specified EXE through its normal entry, with a fresh QA profile."""
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
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--theme', default='')
    parser.add_argument('--scale', default='1')
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():
        raise ValueError('Choose a fresh directory under tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out)
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtCore import QSettings
    if args.theme:
        settings = QSettings('2ByteASR', '2ByteASR')
        settings.setValue('appearance/theme', args.theme)
        settings.sync()
    # Required by the shared audit guard; never opened or used as advertising.
    fixture = out/'guard.2byteproj'
    fixture.write_text('{}', 'utf-8')
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='product-brand',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               TWOBYTEASR_BRAND_EXPECT_THEME=args.theme or 'grape', QT_QPA_PLATFORM='windows',
               QT_SCALE_FACTOR=args.scale, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out/'process', timeout=120)
    receipt = out/'result.json'
    result = json.loads(receipt.read_text('utf-8')) if receipt.exists() else {'passed': False, 'error': 'No receipt'}
    result['process_exit'] = code
    result['passed'] = bool(result['passed'] and code == 0)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({'passed': result['passed'], 'checks': len(result.get('checks', [])),
                      'error': result.get('error'), 'identity': result.get('identity')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
