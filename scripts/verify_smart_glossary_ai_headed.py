"""智能建词 AI 增强 in the real app (scenario ``smart-glossary-ai``, 2026-10-25).

Usage: python scripts/verify_smart_glossary_ai_headed.py --output tmp/<fresh dir> [--exe path\\to\\2ByteASR.exe]
       [--live-secrets %LOCALAPPDATA%\\2ByteASR\\secrets.dat]
Runs on a private Windows desktop with isolated user data; see
twobyteasr/acceptance/smart_glossary_ai_audit.py for the checks. Without ``--live-secrets`` nothing leaves
the machine (a stand-in AI service on 127.0.0.1). ``--live-secrets`` adds one real DeepSeek request
(about 1,000 tokens) using the DeepSeek key in that store, read-only.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--live-secrets', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / 'tmp'):
        raise ValueError('Use a fresh output under repository tmp')
    if args.live_secrets and not args.live_secrets.resolve().is_file():
        parser.error('--live-secrets must name an existing secrets.dat')
    output.mkdir(parents=True)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output)
    from twobyteasr.test_isolation import install
    install()
    # Saved like a user who connected an OpenAI-compatible service: the stand-in on a free loopback
    # port (it starts inside the app), its key in the isolated encrypted store.
    import socket
    from twobyteasr.providers.llm_config import save_api_key_for
    from twobyteasr.storage.settings import load_runtime_settings, save_runtime_settings
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}/v1'
    settings, _path, _warnings = load_runtime_settings()
    models = settings.setdefault('models', {})
    models['ai_service'] = 'custom'
    models.setdefault('provider_profiles', {})['custom'] = {
        'base_url': base_url, 'model': 'standin-flash', 'protocol': 'auto', 'json_mode': True, 'structured_output': True}
    for prefix in ('polish', 'group'):
        models.update({f'{prefix}_provider': 'custom', f'{prefix}_transport': 'openai_compatible',
                       f'{prefix}_base_url': base_url, f'{prefix}_model': 'standin-flash', f'{prefix}_protocol': 'auto'})
    save_runtime_settings(settings)
    save_api_key_for('custom', base_url, 'sk-standin-local')
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, save_project
    project = output / 'blank.2byteproj'
    save_project(SubtitleProject(media=StudioMedia(path='', duration_ms=0)), project)
    env = os.environ.copy()
    env.update(TWOBYTEASR_ACCEPTANCE_DIR=str(output), TWOBYTEASR_STARTUP_PROJECT=str(project),
               TWOBYTEASR_ACCEPTANCE_SCENARIO='smart-glossary-ai', TWOBYTEASR_SMART_GLOSSARY_STANDIN_PORT=str(port),
               TWOBYTEASR_INVOKER_CWD=str(ROOT), TWOBYTEASR_STARTUP_TRACE=str(output / 'startup.jsonl'),
               QT_QPA_PLATFORM='windows', QT_SCALE_FACTOR='1', TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    if args.live_secrets:
        env['TWOBYTEASR_SMART_GLOSSARY_LIVE_SECRETS'] = str(args.live_secrets.resolve())
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT / 'quick_start.py')]
    code = run_on_desktop(command, cwd=ROOT, env=env, output=output / 'process', timeout=300)
    receipt = output / 'result.json'
    result = json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed': False, 'error': 'No GUI receipt'}
    result['process_exit'] = code
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    failed = [c['name'] for c in result.get('checks', []) if not c['passed']]
    print(json.dumps({'passed': result['passed'], 'checks': len(result.get('checks', [])), 'failed': failed,
                      'output': str(output)}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
