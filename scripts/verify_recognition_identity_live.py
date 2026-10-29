"""Finite production recognition on a copied real input, with owned outputs.

Prepare is read-only with respect to source assets/configuration/accounts.
--run executes the complete saved plan, without substituting models or roles.
Local weights/environments are borrowed read-only; all mutable state is tmp.
The caller serializes this run with GUI/build/model work.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--media', type=Path, required=True)
    p.add_argument('--source-data', type=Path, required=True)
    p.add_argument('--settings', type=Path)
    p.add_argument('--glossary-snapshot', type=Path, required=True)
    p.add_argument('--model-root', type=Path, default=ROOT/'models')
    p.add_argument('--grok-home', type=Path,
                   help='Read-only existing official Grok CLI home; mutable home is owned tmp')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--job-id', default='')
    p.add_argument('--run', action='store_true')
    p.add_argument('--enable-term-search', action='store_true',
                   help='Enable the existing optional online check; capability guard stays active')
    p.add_argument('--max-seconds', type=int, default=900)
    args = p.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a fresh output under repository tmp')
    media = args.media.resolve()
    if not media.is_relative_to(ROOT/'tmp') or not media.is_file():
        raise ValueError('Use the preserved real media copy under repository tmp')
    source_data = args.source_data.resolve()
    settings_path = (args.settings or source_data/'2byteasr_settings.json').resolve()
    secrets_path = source_data/'secrets.dat'
    registry_path = source_data/'runtimes/registry.json'
    source_cli = (args.grok_home or source_data.parents[2]/'.grok').resolve()
    cli_auth_source, cli_config_source = source_cli/'auth.json', source_cli/'config.toml'
    snapshot_path = args.glossary_snapshot.resolve()
    sources = [media, settings_path, snapshot_path, *[f for f in (secrets_path, registry_path) if f.is_file()]]
    before = {str(f):sha_file(f) for f in sources}
    raw_settings = json.loads(settings_path.read_text('utf-8-sig'))
    active_cli = raw_settings.get('models', {}).get('ai_service') == 'grok_account'
    isolated_auth = None
    if active_cli:
        if not cli_auth_source.is_file():
            raise ValueError('Existing Grok OAuth source is unavailable; no login is performed')
        auth = json.loads(cli_auth_source.read_text('utf-8-sig'))
        isolated_auth = {}
        for identity, row in auth.items():
            if not isinstance(row, dict) or not row.get('key') or row.get('auth_mode') != 'oidc':
                continue
            expires = str(row.get('expires_at') or '')
            iso = re.sub(r'(\.\d{6})\d+(?=[+-])', r'\1', expires.replace('Z', '+00:00'))
            expiry = datetime.fromisoformat(iso).timestamp()
            if expiry-time.time() <= args.max_seconds+300:
                raise ValueError('Existing Grok access credential expires inside the audit; no refresh is performed')
            isolated_auth[identity] = {k:v for k,v in row.items() if k != 'refresh_token'}
        if not isolated_auth:
            raise ValueError('No presently valid Grok OAuth access credential; no account change is performed')
        sources += [cli_auth_source, *([cli_config_source] if cli_config_source.is_file() else [])]
        before.update({str(f):sha_file(f) for f in sources if str(f) not in before})
    snapshot = json.loads(snapshot_path.read_text('utf-8-sig'))
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('libraries'), list):
        raise ValueError('Use a production GlossarySnapshot.to_dict() document')
    registry = json.loads(registry_path.read_text('utf-8-sig')).get('runtimes', {}) if registry_path.is_file() else {}
    role_dirs = {'main':'.venv-main', 'moss':'.venv-moss', 'firered_llm':'.venv-firered-llm',
                 'glm_asr':'.venv-glm-asr', 'canary':'.venv-canary'}
    borrowed_roles = {}
    for role, folder in role_dirs.items():
        row = registry.get(role, {})
        base = Path(row.get('root') or ROOT/folder)
        entry = base/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if entry.is_file() and (base/'pyvenv.cfg').is_file():
            borrowed_roles[role] = str(entry.resolve())
    if 'main' not in borrowed_roles:
        raise ValueError('Existing Main environment is required; no repair/download is allowed')
    model_root = args.model_root.resolve()
    if not model_root.is_dir():
        raise ValueError('Existing verified model root required')
    out.mkdir(parents=True)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'),
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup-trace.jsonl'),
        TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', PYTHONDONTWRITEBYTECODE='1',
        QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1')
    from twobyteasr.test_isolation import install
    install()
    private_cli = out/'private-cli'
    auth_copy = private_cli/'auth.json'
    if active_cli:
        private_cli.mkdir()
        os.environ['GROK_HOME'] = str(private_cli)
        if cli_config_source.is_file():
            (private_cli/'config.toml').write_bytes(cli_config_source.read_bytes())
    from twobyteasr.storage import settings as settings_module
    from twobyteasr.providers import llm_config
    settings, warnings = settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS, raw_settings)
    secret_reader = llm_config._read_secrets
    llm_config._read_secrets = lambda **_: secret_reader(read_only_path=secrets_path)
    # Supplying explicit config disables legacy settings import/migration.
    settings_module.stable_settings_root = lambda: out/'profile/config'
    settings_module.load_runtime_settings = lambda *a, **k: (copy.deepcopy(settings), str(settings_path), list(warnings))
    settings_module.save_runtime_settings(settings, out/'profile/config')
    # No role is repaired or installed. The real preflight still verifies the
    # borrowed interpreter against the production dependency lock.
    from twobyteasr.system import runtime_registry
    runtime_registry.resolve_runtime_python = lambda role, **_: borrowed_roles.get(role, '')
    from twobyteasr.runtime_paths import MODEL_ROOT_ENV, reset_runtime_paths
    os.environ[MODEL_ROOT_ENV] = str(model_root)
    reset_runtime_paths()
    import subtitle_core as core
    from twobyteasr.recognition.service import CancellationToken, RunOptions, run_media_queue
    from twobyteasr.recognition.recognition_result import validate_job_id, verify_result_reference
    from twobyteasr.glossary.terminology import GlossarySnapshot
    core.adopt_profile_runtime_settings(settings, warnings)
    catalog = GlossarySnapshot.from_dict(snapshot)
    if not catalog.libraries:
        raise ValueError('Real local glossary snapshot required')
    job_id = validate_job_id(args.job_id or uuid.uuid4().hex)
    options = replace(RunOptions.from_legacy(core), job_id=job_id, content_name=catalog.libraries[0].name,
        enable_domain_terms=True, enabled_glossary_ids=tuple(x.id for x in catalog.libraries),
        glossary_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        settings_snapshot_json=json.dumps(settings, ensure_ascii=False),
        enable_term_search=args.enable_term_search)
    def write(name, payload):
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        encoded = core.redact_runtime_secrets(encoded)
        (out/name).write_text(encoded+'\n', 'utf8')
    write('scope.json', dict(job_id=job_id, media=str(media), media_sha256=before[str(media)],
        source_hashes=before, settings_warnings=warnings, models=settings.get('models', {}),
        switches=settings.get('switches', {}), glossary=catalog.summary(), borrowed_roles=borrowed_roles,
        model_root=str(model_root), mutable_root=str(out), full_saved_plan=True, run_requested=args.run,
        task_options={k:getattr(options,k) for k in ('expected_speakers','dialogue_coverage_mode',
            'enable_domain_terms','enable_term_search','recognition_purpose')},
        no_model_downloads=True, cli_source_read_only=True, cli_refresh_disabled=True,
        cli_access_copy_ephemeral=args.run and active_cli, private_cli_home=str(private_cli),
        max_seconds=args.max_seconds))
    if not args.run:
        write('preparation.json', {'prepared':True,'inference_requests':0,'cloud_requests':0,
            'source_unchanged': all(sha_file(f)==before[str(f)] for f in sources)})
        print(json.dumps({'prepared':True,'job_id':job_id,'requests':0}))
        return 0
    token = CancellationToken()
    timer = threading.Timer(args.max_seconds, token.cancel)
    timer.daemon = True
    timer.start()
    started = time.perf_counter()
    payload = {'passed':False, 'job_id':job_id, 'source_unchanged':False}
    try:
        if active_cli:
            # Never link to the original: even an official CLI may rotate auth.
            # Refresh capability is removed; existing valid access is enough
            # for this bounded run. No credential goes in public audit receipts.
            auth_copy.write_text(json.dumps(isolated_auth), 'utf8')
        result = run_media_queue([str(media)], options, cancel_token=token)
        payload.update(queue=asdict(result), elapsed_seconds=time.perf_counter()-started)
        if len(result.successes)==1:
            item = result.successes[0]
            project = verify_result_reference(item.result_ref_json)
            for path in (item.project_path, item.report_json_path, item.report_text_path):
                if path and not Path(path).resolve().is_relative_to(out):
                    raise RuntimeError('A recognition output escaped the owned audit directory')
            payload.update(project_id=project.project_id, cue_count=len(project.cues),
                media_fingerprint=item.media_fingerprint, result_revision=item.result_revision,
                project_path=item.project_path)
            payload['passed'] = True
    except Exception as exc:
        payload['error'] = core.redact_runtime_secrets(str(exc))
        payload['error_type'] = type(exc).__name__
    finally:
        timer.cancel()
        if active_cli:
            for private_file in private_cli.glob('auth.json*'):
                if private_file.is_file():
                    private_file.unlink()
            payload['private_access_removed'] = not auth_copy.exists()
        payload['elapsed_seconds'] = time.perf_counter()-started
        payload['source_after_hashes'] = {str(f):sha_file(f) for f in sources}
        payload['source_unchanged'] = before == payload['source_after_hashes']
        payload['passed'] = bool(payload['passed'] and payload['source_unchanged'])
        write('result.json', payload)
    print(json.dumps({k:payload.get(k) for k in ('passed','job_id','elapsed_seconds','cue_count','source_unchanged','error_type')}, ensure_ascii=False))
    return 0 if payload['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
