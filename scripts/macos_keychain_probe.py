# SPDX-License-Identifier: GPL-3.0-only
"""Real macOS Keychain round trip for the provider-key store (2026-10-13).

Runs the production code (``llm_config`` -> ``macos_keychain`` -> ``security``)
with an isolated user-data folder, so the keychain item is a separate test
item (see ``macos_keychain.service_name``) and never the user's daily one.
Checks: save, read back after clearing the session cache, no plaintext copy
under the data folder, delete. The probe value is random and not a real key.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.output.resolve()
    if 'tmp' not in {part.lower() for part in out.parts}:
        raise SystemExit('--output must be under a tmp directory')
    out.mkdir(parents=True, exist_ok=True)
    data = out / 'user-data'
    data.mkdir(exist_ok=True)
    os.environ['2BYTEASR_USER_DATA_ROOT'] = str(data)
    os.environ['LOCALAPPDATA'] = str(data)
    # Importing twobyteasr under TWOBYTEASR_TEST_ROOT (set for the whole CI job)
    # moves HOME into the isolated folder, where `security` finds no keychain.
    # The item name is still the separate test item (2026-10-14).
    real_home = os.environ.get('HOME', '')
    sys.path.insert(0, str(ROOT))
    from twobyteasr import llm_config, macos_keychain
    if real_home and os.environ.get('HOME') != real_home:
        import subprocess
        original_run = macos_keychain._run

        def run_with_real_home(args, *, input_text=None, runner=None):
            if runner is not None:
                return original_run(args, input_text=input_text, runner=runner)
            return subprocess.run([macos_keychain.SECURITY, *args], input=input_text, capture_output=True,
                                  text=True, timeout=20, env=dict(os.environ, HOME=real_home))
        macos_keychain._run = run_with_real_home
    result = {'platform': sys.platform, 'service_is_daily_item': macos_keychain.service_name() == macos_keychain.SERVICE,
              'steps': []}
    probe = 'sk-2byteasr-keychain-probe-' + secrets.token_hex(8)
    url = 'https://api.deepseek.com'
    try:
        result['available'] = macos_keychain.available()
        result['keychain_enabled'] = llm_config.keychain_storage_enabled()
        result['notice'] = llm_config.credential_storage_notice('zh')
        if result['service_is_daily_item']:
            raise RuntimeError('refusing to touch the daily keychain item')
        llm_config.save_api_key_for('deepseek', url, probe)
        result['steps'].append('saved')
        llm_config.clear_session_secrets()
        value, source = llm_config.read_api_key('deepseek', url)
        result['read_back_matches'] = value == probe
        result['read_source'] = source
        result['steps'].append('read_back')
        plaintext = [str(path.relative_to(out)) for path in out.rglob('*')
                     if path.is_file() and probe.encode() in path.read_bytes()]
        result['plaintext_copies'] = plaintext
        macos_keychain.delete()
        llm_config.clear_session_secrets()
        result['deleted'] = macos_keychain.read() is None
        result['steps'].append('deleted')
    except Exception as exc:  # recorded, not hidden
        result['error'] = f'{type(exc).__name__}: {exc}'.replace(probe, '<probe>')
    result['passed'] = bool(result.get('available') and result.get('keychain_enabled')
                            and result.get('read_back_matches') and result.get('plaintext_copies') == []
                            and result.get('deleted') and not result.get('error'))
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
