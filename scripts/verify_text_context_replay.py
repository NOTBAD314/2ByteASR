"""Finite old/new production text replay; prepare is zero-request and read-only.

Uses a normal Home glossary save/restart receipt and actual retained ASR rows.
--run dispatches the saved selected account through the real provider adapter.
No ASR, web term search, cache hit, model substitution, login or OAuth refresh.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def write(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', 'utf-8')


def validate_firered_tokens(path, aligned):
    """A combined MOSS-primary cache is not a raw independent FireRed table."""
    if path is None:
        return None
    payload = read(path)
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError('FireRed tokens must be the retained raw word table')
    combined = Path(aligned).resolve().parent.parent/'firered_primary.json'
    if combined.is_file():
        rows = read(combined).get('data', [])
        primary_words = [word for row in rows for word in row.get('words', [])]
        has_moss_primary = any(str(row.get('primary_source', '')).startswith('moss-') for row in rows)
        if has_moss_primary and payload == primary_words:
            raise ValueError('Supplied tokens are MOSS-primary words from combined firered_primary cache, '
                'not independent FireRed tokens; omit in both arms or supply the original FireRed word table')
    return combined if combined.is_file() else None


def child(args):
    out, source = args.output.resolve(), args.source.resolve()
    plan = read(out.parent/'scope.json')
    profile = Path(plan['normal_profile'])
    out.mkdir()
    for folder in ('config', 'local/2ByteASR', 'qsettings'):
        original = profile/folder
        if original.is_dir():
            shutil.copytree(original, out/'profile'/folder)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out/'profile'),
        TWOBYTEASR_STARTUP_TRACE=str(out/'startup.jsonl'),
        TWOBYTEASR_CHILD_PROCESS_LOG=str(out/'processes.jsonl'),
        TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1', PYTHONDONTWRITEBYTECODE='1',
        QT_QPA_PLATFORM='offscreen', PYTHONIOENCODING='utf-8')
    # The subprocess imports exactly one source tree; no parent product imports.
    sys.path[:] = [str(source), *[entry for entry in sys.path if entry and
        Path(entry).resolve() not in (ROOT, ROOT/'scripts')]]
    from twobyteasr.test_isolation import install
    install()
    auth_source = Path(plan['grok_home'])/'auth.json'
    private_cli = out/'private-cli'; private_cli.mkdir()
    os.environ['GROK_HOME'] = str(private_cli)
    auth = read(auth_source)
    valid = {}
    for key, record in auth.items():
        if not isinstance(record, dict) or record.get('auth_mode') != 'oidc' or not record.get('key'):
            continue
        expires = re.sub(r'(\.\d{6})\d+(?=[+-])', r'\1', str(record.get('expires_at') or '').replace('Z', '+00:00'))
        if datetime.fromisoformat(expires).timestamp() - time.time() < args.max_seconds + 180:
            continue
        valid[key] = {field: value for field, value in record.items() if field != 'refresh_token'}
    if not valid:
        raise ValueError('No sufficiently long-lived existing access credential; no refresh/login performed')
    cli_config = auth_source.parent/'config.toml'
    if cli_config.is_file():
        shutil.copyfile(cli_config, private_cli/'config.toml')
    from twobyteasr.storage import settings as settings_module
    from twobyteasr.providers import llm_config
    settings, warnings = settings_module._merge_known_settings(settings_module.DEFAULT_SETTINGS, read(plan['settings_path']))
    settings_module.stable_settings_root = lambda: out/'profile/config'
    settings_module.load_runtime_settings = lambda *a, **k: (copy.deepcopy(settings), str(out/'profile/config/2byteasr_settings.json'), warnings)
    settings_module.save_runtime_settings(settings, out/'profile/config')
    secret_source = Path(plan['source_data'])/'secrets.dat'
    if secret_source.is_file():
        owned_secret = out/'profile/local/2ByteASR/secrets.dat'
        owned_secret.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(secret_source, owned_secret)
        prior = llm_config._read_secrets
        llm_config._read_secrets = lambda **_: prior(read_only_path=owned_secret)
    import subtitle_core as core
    from twobyteasr.subtitle_rules import polishing, grouping
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.service import CancellationToken
    from twobyteasr.glossary.terminology import GlossarySnapshot, apply_to_segments
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot, POLISH_PROMPT_VERSION, GROUP_PROMPT_VERSION
    from twobyteasr.providers.provider_service import ProviderService, GLOBAL_PROVIDER_SERVICE
    from twobyteasr.providers.provider_diagnostics import redact_diagnostics
    if Path(core.__file__).resolve().parent != source:
        raise RuntimeError('Source import isolation failed')
    core.adopt_profile_runtime_settings(settings, warnings)
    receipt = read(plan['glossary_receipt'])
    catalog = GlossarySnapshot.from_dict(receipt['snapshot'])
    token = CancellationToken()
    context = RuntimeContext(game_name='', enable_domain_terms=bool(catalog.libraries),
        enabled_glossary_ids=[library.id for library in catalog.libraries], glossary_snapshot=catalog,
        cancellation_token=token, enable_term_search=False, event_log_path=str(out/'events.jsonl'),
        asr_settings_snapshot=settings, media_path=plan['media_title'])
    providers = {stage: resolve_provider_snapshot(settings, stage=stage) for stage in ('polish', 'group')}
    for provider in providers.values():
        if provider.transport != 'grok_cli' or provider.model != 'grok-4.7':
            raise ValueError('Saved selected service is not Grok4.7; no substitution is permitted')
    context.provider_snapshots = providers
    rows = core.deserialize_segments(read(plan['aligned']))
    raw_before = core.serialize_segments(rows)
    vad = read(plan['vad'])['data']
    # Only retained source timing is used. Missing raw FireRed token tables are
    # explicit and identical in both arms, never synthesized from MOSS words.
    tokens = read(plan['firered_tokens']) if plan.get('firered_tokens') else []
    submitted, dispatched, lock = [], [], threading.Lock()
    limits = {'polish': 1, 'group': 5 if args.arm == 'old' else 1}
    counts = dict.fromkeys(limits, 0)
    prior_submit, prior_execute = ProviderService.submit, ProviderService._execute
    def save_dispatched():
        # Generic diagnostic redaction reparses embedded JSON strings. Preserve
        # prompt whitespace byte-for-byte except actual credential patterns.
        from twobyteasr.providers.provider_diagnostics import _PATTERNS
        public = redact_diagnostics(dispatched)
        for original, record in zip(dispatched, public):
            exact = copy.deepcopy(original['messages'])
            for message in exact:
                content = message.get('content')
                if isinstance(content, str):
                    for pattern in _PATTERNS:
                        content = pattern.sub('[REDACTED]', content)
                    message['content'] = content
            record['messages'] = exact
        write(out/'actually-dispatched.json', public)
    def submit(service, config, stage, messages, **kwargs):
        handle = prior_submit(service, config, stage, messages, **kwargs)
        with lock:
            submitted.append((handle, kwargs.get('request_diagnostics', {})))
        return handle
    def execute(service, request):
        kind = request.kwargs.get('operation_kind')
        with lock:
            if kind not in limits or counts[kind] >= limits[kind]:
                raise RuntimeError('Finite audit dispatch budget exhausted; no extra cloud request sent')
            counts[kind] += 1
            record = {'request_id': request.handle.request_id, 'operation': kind,
                'batch_index': request.kwargs.get('batch_index'), 'started_monotonic': time.monotonic(),
                'messages': copy.deepcopy(request.messages), 'schema': copy.deepcopy(request.schema),
                'message_content_characters': sum(len(str(message.get('content', ''))) for message in request.messages),
                'message_content_sha256': hashlib.sha256(''.join(str(message.get('content', ''))
                    for message in request.messages).encode('utf-8')).hexdigest()}
            dispatched.append(record)
            save_dispatched()
        started = time.perf_counter()
        try:
            return prior_execute(service, request)
        finally:
            record['wall_seconds'] = time.perf_counter()-started
            record['diagnostics'] = copy.deepcopy(request.kwargs.get('request_diagnostics', {}))
            record['trace'] = copy.deepcopy(request.handle.trace)
            save_dispatched()
    ProviderService.submit, ProviderService._execute = submit, execute
    timer = threading.Timer(args.max_seconds, token.cancel); timer.daemon = True
    result = {'passed': False, 'arm': args.arm, 'asr_requests': 0, 'web_term_search': False,
        'cache_used': False, 'source': str(source), 'prompt_versions': {'polish': POLISH_PROMPT_VERSION, 'group': GROUP_PROMPT_VERSION},
        'snapshot': catalog.summary(), 'local_timing_reference': 'retained_source_only', 'raw_firered_tokens_present': bool(tokens)}
    started = time.perf_counter()
    try:
        (private_cli/'auth.json').write_text(json.dumps(valid), 'utf-8')
        timer.start()
        with activate_runtime_context(context, legacy=core):
            apply_to_segments(rows, catalog, legacy=core)
            local_rows = core.serialize_segments(rows)
            start = time.perf_counter()
            polished = polishing.polish_subtitles(rows, plan['media_title'], cache_context=None)
            result['polish_wall_seconds'] = time.perf_counter()-start
            start = time.perf_counter()
            cues = grouping.group_subtitles(polished, firered_tokens=tokens, speech_regions=vad,
                cache_context=None, use_ai=True)
            result['group_wall_seconds'] = time.perf_counter()-start
            result['text_conservation_differences'] = core.final_text_conservation_differences(cues, polished)
            write(out/'input-asr.json', raw_before)
            write(out/'local-normalized.json', local_rows)
            write(out/'polished.json', core.serialize_segments(polished))
            write(out/'grouped.json', core.serialize_cues(cues))
            result['polishing_summary'] = copy.deepcopy(context.polishing_summary)
            result['cue_count'] = len(cues)
            result['canonical_occurrences'] = {name: sum(name in cue.text for cue in cues) for name in catalog.canonical_terms}
            events = [json.loads(line) for line in (out/'events.jsonl').read_text('utf-8').splitlines() if line]
            groups = [event for event in events if event.get('event') == 'cloud_batch_completed' and event.get('stage') == 'grouped']
            result['group_validation'] = groups
            result['all_requested_ai_completed'] = (context.polishing_summary.get('success_cues') == len(rows)
                and not context.polishing_summary.get('fallback_cues') and len(groups) == limits['group']
                and all(event.get('result_origin') == 'ai' and event.get('validator_result') == 'exact_text_and_boundaries' for event in groups))
            result['outstanding_suspects'] = [dict(cue_id=row.segment_id,
                quality_state=row.caption_arbitration.get('terminology_polish', {}).get('quality_state'),
                unreviewed=row.caption_arbitration.get('terminology_polish', {}).get('unreviewed_suspects', []),
                adjudications=row.caption_arbitration.get('terminology_polish', {}).get('suspect_results', [])) for row in polished]
            result['passed'] = (not result['text_conservation_differences'] and result['all_requested_ai_completed']
                and counts == limits)
    except Exception as exc:
        result.update(error=core.redact_runtime_secrets(str(exc)), error_type=type(exc).__name__)
    finally:
        timer.cancel()
        GLOBAL_PROVIDER_SERVICE.wait_for_idle(15)
        for item in private_cli.glob('auth.json*'):
            if item.is_file(): item.unlink()
        result.update(elapsed_seconds=time.perf_counter()-started, dispatch_counts=counts,
            private_access_removed=not (private_cli/'auth.json').exists(),
            handles=[{'request_id': handle.request_id, 'trace': handle.trace,
                'diagnostics': diagnostics, 'error': str(handle._error or '')} for handle, diagnostics in submitted])
        write(out/'result.json', redact_diagnostics(result))
    return 0 if result['passed'] else 1


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--normal-profile', type=Path)
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--source-data', type=Path)
    parser.add_argument('--grok-home', type=Path)
    parser.add_argument('--aligned', type=Path)
    parser.add_argument('--vad', type=Path)
    parser.add_argument('--firered-tokens', type=Path)
    parser.add_argument('--baseline-source', type=Path)
    parser.add_argument('--current-source', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-seconds', type=int, default=480)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--arm', choices=['old', 'new'])
    args = parser.parse_args()
    if args.child: return child(args)
    out = args.output.resolve()
    if not out.is_relative_to(ROOT/'tmp') or out.exists():
        raise ValueError('Choose a fresh audit directory under repository tmp')
    required = (args.normal_profile, args.settings, args.source_data, args.grok_home,
        args.aligned, args.vad, args.baseline_source)
    if any(value is None for value in required): raise ValueError('All source arguments are required')
    profile = args.normal_profile.resolve()
    glossary_receipt = profile/'chain-restore-result.json'
    receipt = read(glossary_receipt)
    if not receipt.get('passed') or not receipt.get('gui_shutdown') or not receipt.get('snapshot', {}).get('libraries'):
        raise ValueError('A passed normal UI save/restart receipt is required')
    if not any(item['name'] == 'terms enabled for actual batch' and item.get('passed') for item in receipt['checks']):
        raise ValueError('No real normal Home enabled-set evidence')
    store = profile/'local/2ByteASR/learned_game_terms.json'
    if sha(store) != receipt['store_sha256']: raise ValueError('Normal saved library changed after receipt')
    paths = [args.settings.resolve(), glossary_receipt, store, args.aligned.resolve(), args.vad.resolve(),
        args.grok_home.resolve()/'auth.json', *profile.glob('qsettings/*.ini')]
    cli_config = args.grok_home.resolve()/'config.toml'
    if cli_config.is_file(): paths.append(cli_config)
    if args.firered_tokens:
        provenance = validate_firered_tokens(args.firered_tokens, args.aligned)
        paths.append(args.firered_tokens.resolve())
        if provenance: paths.append(provenance)
    secret = args.source_data.resolve()/'secrets.dat'
    if secret.is_file(): paths.append(secret)
    settings = read(args.settings)
    if settings.get('models', {}).get('ai_service') != 'grok_account':
        raise ValueError('Saved selected service must already be Grok; no audit substitution')
    before = {str(path): sha(path) for path in paths}
    out.mkdir(parents=True)
    scope = {'normal_profile': str(profile), 'settings_path': str(args.settings.resolve()),
        'source_data': str(args.source_data.resolve()), 'grok_home': str(args.grok_home.resolve()),
        'glossary_receipt': str(glossary_receipt), 'aligned': str(args.aligned.resolve()),
        'vad': str(args.vad.resolve()), 'firered_tokens': str(args.firered_tokens.resolve()) if args.firered_tokens else '',
        'baseline_source': str(args.baseline_source.resolve()), 'current_source': str(args.current_source.resolve()),
        'media_title': 'GE_vs_EDG retained 67.6533125s', 'source_before_hashes': before,
        'same_ui_saved_snapshot_both_arms': True, 'asr_run': False, 'web_term_search': False,
        'cloud_requested': args.run, 'finite_dispatch_plan': {'old': {'polish':1, 'group':5}, 'new': {'polish':1, 'group':1}},
        'historical299_seconds_is_different_snapshot_not_comparison_baseline': True,
        'raw_firered_token_table_missing': not bool(args.firered_tokens), 'max_seconds_per_arm': args.max_seconds}
    write(out/'scope.json', scope)
    if not args.run:
        write(out/'preparation.json', {'prepared': True, 'cloud_requests': 0, 'source_unchanged': all(sha(path)==before[str(path)] for path in paths)})
        print(json.dumps({'prepared': True, 'output': str(out), 'cloud_requests': 0}))
        return 0
    results = {}
    try:
        for arm, source in [('old', args.baseline_source), ('new', args.current_source)]:
            command = [sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--child',
                '--arm', arm, '--source', str(source.resolve()), '--output', str(out/arm), '--max-seconds', str(args.max_seconds)]
            with (out/f'{arm}-stdout.txt').open('w', encoding='utf-8') as log:
                process = subprocess.Popen(command, cwd=out, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                try:
                    exit_code = process.wait(timeout=args.max_seconds+45)
                except subprocess.TimeoutExpired:
                    import psutil
                    own = psutil.Process(process.pid)
                    if own.ppid() != os.getpid():
                        raise RuntimeError('Timed out subprocess ownership is unverified')
                    family = own.children(recursive=True) + [own]
                    identities = [(item, item.create_time()) for item in family]
                    for item, stamp in identities:
                        if item.is_running() and item.create_time() == stamp: item.terminate()
                    _, alive = psutil.wait_procs(family, timeout=3)
                    for item in alive:
                        stamp = next(stamp for known, stamp in identities if known.pid == item.pid)
                        if item.is_running() and item.create_time() == stamp: item.kill()
                    exit_code = process.wait(timeout=5)
            results[arm] = {'exit_code': exit_code, 'result': read(out/arm/'result.json') if (out/arm/'result.json').is_file() else {}}
    finally:
        for arm in ('old', 'new'):
            private = out/arm/'private-cli'
            if private.is_dir():
                for item in private.glob('auth.json*'):
                    if item.is_file() and item.resolve().is_relative_to(out): item.unlink()
        after = {str(path): sha(path) for path in paths}
        write(out/'comparison.json', {'arms': results, 'source_after_hashes': after,
            'source_unchanged': before == after, 'same_ui_saved_snapshot': True,
            'passed': before == after and len(results) == 2 and all(row['exit_code']==0 and row['result'].get('passed') for row in results.values())})
    return 0 if before == after and len(results) == 2 and all(row['exit_code']==0 for row in results.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
