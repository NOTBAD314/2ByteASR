"""Real-window check of the home AI card and the one-page AI settings (2026-10-22, design B).

Starts the real app (source, or ``--exe`` for a frozen candidate) on a private
desktop with an isolated data folder and runs the ``home-ai-card`` acceptance
scenario (``twobyteasr/acceptance/home_ai_card_audit.py``): no key → a click
on the frosted 内容与术语 → the AI settings (simple, 高级设置, a second
service, cancel) → key saved but untested → failed → connected → AI off → a
short window → the light theme. Every state is made with a fake key in the
isolated store and a remembered test result. Offline; no AI. Nothing is read
from or written to the real user data.

    python -X utf8 scripts/verify_home_ai_card_headed.py --output tmp/<new folder> [--zoom 120] [--theme grape]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

# The user's recognition plan (MOSS Pro 云端), so the model cards look like theirs.
SETTINGS = {"schema_version": 1, "models": {
    "primary_asr_backend": "api", "qwen_asr_api_provider": "mosi_moss_pro",
    "qwen_asr_api_protocol": "mosi_transcriptions", "qwen_asr_api_model": "moss-transcribe-diarize-pro",
    "qwen_asr_api_url": "https://api.mosi.cn/v1", "firered_asr_backend": "qwen_aligner", "qwen_asr_backend": "off"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--zoom', type=int, default=120)
    parser.add_argument('--theme', default='grape')
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT / 'tmp'):
        raise ValueError('A fresh output directory under the repository tmp/ is required')
    out.mkdir(parents=True)
    profile = out / 'profile'
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(profile)
    sys.path.insert(0, str(ROOT))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.app import ui_zoom
    ui_zoom.set_zoom_percent(args.zoom)   # isolated QSettings shared with the app (same test root)
    from verify_ui_polish_headed import _fixture
    fixture = _fixture(out)   # the acceptance runner requires its own copied project
    local, roaming = out / 'local', out / 'roaming'
    local.mkdir()
    roaming.mkdir()
    # The app's test isolation keeps its data under the test root.
    settings = profile / 'local' / '2ByteASR' / '2byteasr_settings.json'
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(SETTINGS, ensure_ascii=False, indent=2), 'utf-8')
    env = {k: v for k, v in os.environ.items() if not k.startswith('TWOBYTEASR_')}
    env.update(LOCALAPPDATA=str(local), APPDATA=str(roaming), **{'2BYTEASR_USER_DATA_ROOT': str(local)},
               TWOBYTEASR_STARTUP_PROJECT=str(fixture), TWOBYTEASR_TEST_ROOT=str(profile), PYTHONUTF8='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONFAULTHANDLER='1',
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='home-ai-card',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
               NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
               TWOBYTEASR_HOME_AI_THEME=args.theme)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    path = out / 'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=bool(result.get('passed')) and code == 0 and bool(result.get('gui_shutdown')), exit=code,
                   shutdown=result.get('gui_shutdown'), executable=result.get('executable'),
                   checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                   failed=[c for c in result.get('checks', []) if not c['passed']],
                   skipped=result.get('skipped'), errors=[e[-1500:] for e in result.get('errors', [])])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
