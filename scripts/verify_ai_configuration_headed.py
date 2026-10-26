"""Seven live-save cases, followed by a new process using the same isolated profile."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use a fresh directory under this checkout/tmp')
    out.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(out / 'profile')
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.app import ui_zoom
    ui_zoom.set_zoom_percent(100)
    from verify_ui_polish_headed import _fixture
    fixture = _fixture(out)
    from twobyteasr.acceptance.ai_config_standin import AiConfigStandin
    peer = AiConfigStandin()
    from isolated_windows_desktop import run_on_desktop
    env = dict(os.environ, TWOBYTEASR_ACCEPTANCE_DIR=str(out),
               TWOBYTEASR_ACCEPTANCE_SCENARIO='ai-configuration',
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_INVOKER_CWD=str(ROOT),
               TWOBYTEASR_AI_CONFIG_PEER=peer.url, TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               QT_QPA_PLATFORM='windows', PYTHONUTF8='1', PYTHONFAULTHANDLER='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    summary = {}
    try:
        for phase in ('live', 'restart'):
            env['TWOBYTEASR_AI_CONFIG_PHASE'] = phase
            code = run_on_desktop(command, cwd=ROOT, env=env, output=out / ('process-' + phase), timeout=240)
            path = out / (phase + '-result.json')
            data = json.loads(path.read_text('utf-8')) if path.exists() else {'passed': False, 'errors': ['no result']}
            summary[phase] = {'exit': code, 'passed': data['passed'] and code == 0 and data.get('gui_shutdown', False),
                              'checks': len(data.get('checks', [])), 'errors': data.get('errors', [])}
            print(json.dumps({phase: summary[phase]}, ensure_ascii=False), flush=True)
            if not summary[phase]['passed']:
                break
        summary['requests'] = peer.requests
    finally:
        peer.close()
    summary['passed'] = all(summary.get(phase, {}).get('passed') for phase in ('live', 'restart'))
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
