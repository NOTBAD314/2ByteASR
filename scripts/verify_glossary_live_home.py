"""Real Home recognition using a profile already saved/enabled by normal UI."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import re
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_private_cli(validated, profile, settings):
    """Borrow current access credentials without refresh or source writes."""
    models = settings.get('models', {})
    active = models.get('ai_service') == 'grok_account' or any(
        models.get(stage+'_transport') == 'grok_cli' for stage in ('polish', 'group'))
    if not active:
        return None
    cli = validated['manifest'].get('grok_home')
    if not cli:
        raise ValueError('Current UI settings use Grok CLI: explicitly hashed existing Grok home is required')
    source = Path(cli['path']).resolve()
    rows = json.loads((source/'auth.json').read_text('utf-8-sig'))
    isolated = {}
    for identity, row in rows.items():
        if not isinstance(row, dict) or row.get('auth_mode') != 'oidc' or not row.get('key'):
            continue
        iso = re.sub(r'(\.\d{6})\d+(?=[+-])', r'\1', str(row.get('expires_at') or '').replace('Z', '+00:00'))
        if datetime.fromisoformat(iso).timestamp()-time.time() <= 1200:
            raise ValueError('Existing Grok access credential expires inside the 900s audit plus safety margin; no refresh is performed')
        isolated[identity] = {key: value for key, value in row.items() if key != 'refresh_token'}
    if not isolated:
        raise ValueError('No currently valid existing Grok OIDC access credential; no login is performed')
    private = profile/'live-home-private-cli'
    if private.exists():
        raise ValueError('Private CLI target already exists; preserve prior attempt')
    private.mkdir()
    try:
        if cli.get('config_sha256'):
            shutil.copy2(source/'config.toml', private/'config.toml')
        (private/'auth.json').write_text(json.dumps(isolated), 'utf8')
    except Exception:
        cleanup_private_cli(private, profile)
        raise
    return private


def cleanup_private_cli(private, profile):
    if private is None:
        return True
    target, boundary = private.resolve(), profile.resolve()
    if target != boundary/'live-home-private-cli' or not target.is_relative_to(boundary) or private.is_symlink():
        raise ValueError('Private CLI cleanup target failed owned absolute boundary verification')
    shutil.rmtree(target)
    return not target.exists()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', type=Path, required=True, help='Existing normal glossary save/enable/restart audit profile')
    parser.add_argument('--media', type=Path, required=True, help='Actual retained original media or immutable owned copy')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--environment', type=Path, help='Root-prepared owned JSON environment overrides; no credentials are printed')
    parser.add_argument('--borrowed-resources', type=Path, required=True, help='Owned explicitly hashed existing runtime/model/secrets/OAuth source manifest')
    parser.add_argument('--skip-burn', action='store_true', help='Explicitly mark production burn verification not run')
    args = parser.parse_args()
    profile = args.profile.resolve()
    if not profile.is_relative_to(ROOT/'tmp') or not profile.is_dir():
        raise ValueError('Profile must be an existing owned repository tmp directory')
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(profile), TWOBYTEASR_STARTUP_TRACE=str(profile/'live-home-evidence/driver-startup.jsonl'),
        TWOBYTEASR_INVOKER_CWD=str(ROOT))
    restore = json.loads((profile/'chain-restore-result.json').read_text('utf8'))
    if not restore.get('passed') or not restore.get('gui_shutdown'):
        raise ValueError('Normal UI save/enable/restart must already have passed')
    store = profile/'local/2ByteASR/learned_game_terms.json'
    settings = profile/'local/2ByteASR/2byteasr_settings.json'
    startup_project = profile/'original-project.2byteproj'
    for required in (store, settings, startup_project, args.media):
        if not required.is_file():
            raise ValueError('Missing required retained input: '+str(required))
    receipt = profile/'live-home-result.json'
    if receipt.exists() or (profile/'live-home-process').exists():
        raise ValueError('This existing UI-saved profile already has a live Home attempt; preserve it and use another normally-created profile')
    media_source = args.media.resolve()
    media_dir = profile/'live-home-media'
    media_dir.mkdir(exist_ok=True)
    media = media_dir/media_source.name
    if media.exists() and sha(media) != sha(media_source):
        raise ValueError('Owned media target conflicts with source bytes')
    if not media.exists():
        shutil.copy2(media_source, media)
    before = {str(path): sha(path) for path in (store, settings, startup_project, media_source, media)}
    from twobyteasr.acceptance.glossary_live_resources import validate_manifest, MANIFEST_ENV
    validated = validate_manifest(args.borrowed_resources, profile)
    before.update(validated['protected'])
    evidence = profile/'live-home-evidence'
    evidence.mkdir()
    shutil.copy2(store, evidence/'ui-saved-glossary-before.json')
    shutil.copy2(settings, evidence/'ui-saved-settings-before.json')
    overrides = {}
    if args.environment:
        env_path = args.environment.resolve()
        if not env_path.is_relative_to(ROOT/'tmp'):
            raise ValueError('Prepared environment must be owned task tmp data')
        overrides = json.loads(env_path.read_text('utf8'))
        overrides = overrides.get('environment', overrides)
        if not isinstance(overrides, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in overrides.items()):
            raise ValueError('Prepared environment must contain string values')
    (profile/'live-home-input.json').write_text(json.dumps(dict(media=str(media), source_media=str(media_source),
        store=str(store), settings=str(settings), startup_project=str(startup_project), protected_before=before,
        normal_ui_restore_receipt=str(profile/'chain-restore-result.json'), burn_requested=not args.skip_burn,
        scope='Actual Home file-add and Start; no injected snapshot/result; one real local-three-model plus configured cloud run from normally-saved glossary profile',
        environment_keys=sorted(overrides)), ensure_ascii=False, indent=2), 'utf8')
    os.environ.update(overrides)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(profile), TWOBYTEASR_STARTUP_TRACE=str(evidence/'driver-startup.jsonl'))
    from twobyteasr.test_isolation import install
    install()
    environment = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_OPEN_STUDIO', 'TWOBYTEASR_STARTUP_RAISE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_OPEN_PATHS'):
        environment.pop(key, None)
    environment.update(TWOBYTEASR_ACCEPTANCE_DIR=str(profile), TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-live-home',
        TWOBYTEASR_STARTUP_PROJECT=str(startup_project), TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_STARTUP_TRACE=str(evidence/'gui-startup.jsonl'), QT_QPA_PLATFORM='windows',
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        PYTHONDONTWRITEBYTECODE='1', TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1')
    environment[MANIFEST_ENV] = validated['manifest_path']
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    from isolated_windows_desktop import run_on_desktop
    private_cli = None
    code, driver_error = None, None
    try:
        private_cli = prepare_private_cli(validated, profile, json.loads(settings.read_text('utf-8-sig')))
        if private_cli:
            environment['GROK_HOME'] = str(private_cli)
        code = run_on_desktop(command, cwd=ROOT, env=environment, output=profile/'live-home-process', timeout=900)
    except Exception:
        driver_error = traceback.format_exc()
    finally:
        private_cli_cleaned = cleanup_private_cli(private_cli, profile)
    result = json.loads(receipt.read_text('utf8')) if receipt.is_file() else {'passed': False, 'error': 'No actual GUI receipt'}
    if driver_error:
        result['driver_error'] = driver_error
        result['passed'] = False
    result.update(process_exit=code, normal_entry_command=command)
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0)
    result['driver_protection'] = [dict(path=path, sha256_before=digest, sha256_after=sha(path)) for path, digest in before.items()]
    result['borrowed_sources_unchanged'] = all(row['sha256_before'] == row['sha256_after'] for row in result['driver_protection']
        if row['path'] in validated['protected'])
    result['private_cli_credentials_removed'] = private_cli_cleaned
    result['original_media_unchanged'] = all(row['sha256_before'] == row['sha256_after'] for row in result['driver_protection']
        if row['path'] in {str(media_source), str(media), str(startup_project)})
    result['passed'] = result['passed'] and result['original_media_unchanged'] and result['borrowed_sources_unchanged'] and private_cli_cleaned
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps(dict(passed=result['passed'], error=result.get('error'), receipt=str(receipt)), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
