"""Real-window check that nothing in AI 文字服务设置 is cut off at the right (2026-10-25).

Starts the real app (source, or ``--exe`` for a frozen candidate) on a private
desktop with an isolated data folder and runs the ``ai-dialog-width``
acceptance scenario (``twobyteasr/acceptance/ai_dialog_width_audit.py``):
DeepSeek API connected (a fake key in the isolated store and a remembered
passed test), then for each interface language the main window maximized and
at 1366 x 760, the dialog plain, with 更多选项 open, and with 断句另用一个服务.
Offline; no AI. Nothing is read from or written to the real user data.

    python -X utf8 scripts/verify_ai_dialog_width_headed.py --output tmp/<new folder> [--zoom 120] [--languages zh,en]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

# The user's recognition plan (MOSS Pro 云端), so the home page looks like theirs.
SETTINGS = {"schema_version": 1, "models": {
    "primary_asr_backend": "api", "qwen_asr_api_provider": "mosi_moss_pro",
    "qwen_asr_api_protocol": "mosi_transcriptions", "qwen_asr_api_model": "moss-transcribe-diarize-pro",
    "qwen_asr_api_url": "https://api.mosi.cn/v1", "firered_asr_backend": "qwen_aligner", "qwen_asr_backend": "off"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--zoom', type=int, default=120)
    parser.add_argument('--theme', default='warm')
    parser.add_argument('--languages', default='zh')
    parser.add_argument('--state', choices=('ready', 'no_key'), default='ready',
                        help="ready: DeepSeek API connected (the user's); no_key: a first start")
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
               TWOBYTEASR_ACCEPTANCE_DIR=str(out), TWOBYTEASR_ACCEPTANCE_SCENARIO='ai-dialog-width',
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', QT_QPA_PLATFORM='windows',
               NO_PROXY='127.0.0.1,localhost', HTTP_PROXY='http://127.0.0.1:9', HTTPS_PROXY='http://127.0.0.1:9',
               TWOBYTEASR_AI_WIDTH_THEME=args.theme, TWOBYTEASR_AI_WIDTH_LANGUAGES=args.languages,
               TWOBYTEASR_AI_WIDTH_STATE=args.state)
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop(command, cwd=ROOT, env=env, output=out / 'process', timeout=args.timeout)
    path = out / 'result.json'
    result = json.loads(path.read_text('utf-8')) if path.exists() else dict(passed=False, error='no result')
    summary = dict(passed=bool(result.get('passed')) and code == 0 and bool(result.get('gui_shutdown')), exit=code,
                   shutdown=result.get('gui_shutdown'), executable=result.get('executable'),
                   checks=[(c['name'], c['passed']) for c in result.get('checks', [])],
                   failed=[c for c in result.get('checks', []) if not c['passed']],
                   errors=[e[-1500:] for e in result.get('errors', [])])
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
