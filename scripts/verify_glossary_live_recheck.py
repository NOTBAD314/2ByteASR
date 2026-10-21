"""Prepare an isolated, normally configured Studio text review of real Home output.

Execution requires a separately authorized bounded cloud allowance. Preparation
never runs ASR, rewrites original results, repairs a project or injects responses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_inputs(args):
    profile, output = args.profile.resolve(), args.output.resolve()
    source, home_receipt = args.project.resolve(), args.home_receipt.resolve()
    if not profile.is_relative_to(ROOT/'tmp') or not profile.is_dir():
        raise ValueError('Use an existing normally UI-saved task tmp profile')
    if output.exists() or not output.is_relative_to(ROOT/'tmp'):
        raise ValueError('Use a NEW task tmp output; previous attempts are preserved')
    if type(args.maximum_requests) is not int or not 1 <= args.maximum_requests <= 2:
        raise ValueError('Cloud allowance must be one or two requests including JSON repair')
    for path in (source, home_receipt):
        if not path.is_file() or not path.is_relative_to(ROOT/'tmp'):
            raise ValueError('Actual retained Home input must be an owned tmp file: '+str(path))
    restore = profile/'chain-restore-result.json'
    ui_receipt = json.loads(restore.read_text('utf8'))
    if not ui_receipt.get('passed') or not ui_receipt.get('gui_shutdown'):
        raise ValueError('Current glossary profile must have passed normal UI save/enable/restart')
    original = json.loads(home_receipt.read_text('utf8'))
    actual = original.get('actual_project_before_studio') or {}
    if (not original.get('inference_run') or not original.get('actual_reference')
            or Path(str(actual.get('path') or '')).resolve() != source
            or actual.get('sha256') != sha(source)):
        raise ValueError('Exact original cold Home committed project/reference provenance is required')
    data = json.loads(source.read_text('utf-8-sig'))
    cues, evidence = data.get('cues', []), data.get('asr_evidence', {})
    if len(cues) != args.expected_cues or len(evidence) != args.expected_asr_evidence:
        raise ValueError('Actual current cue and original ASR evidence counts differ from declared scope')
    store = profile/'local/2ByteASR/learned_game_terms.json'
    local_settings = profile/'local/2ByteASR/2byteasr_settings.json'
    settings = profile/'config/2byteasr_settings.json'
    if not store.is_file() or not settings.is_file() or not local_settings.is_file():
        raise ValueError('Missing normally saved glossary/settings bytes')
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_STARTUP_TRACE=str(output/'recheck-evidence/driver-startup.jsonl'))
    output.mkdir(parents=True)
    local = output/'local/2ByteASR'; local.mkdir(parents=True)
    config = output/'config'; config.mkdir()
    copied_store, copied_settings = local/store.name, config/settings.name
    copied_local_settings = local/local_settings.name
    project_copy = output/'original-project.2byteproj'
    for old, new in ((store, copied_store), (settings, copied_settings),
                     (local_settings, copied_local_settings), (source, project_copy)):
        shutil.copy2(old, new)
        if sha(old) != sha(new):
            raise ValueError('Source changed while creating immutable input copy')
    protected = {str(p): sha(p) for p in (source, home_receipt, restore, store, settings, local_settings)}
    # Follow the existing result reference read-only. Never restamp it for the
    # copied project path or pretend the earlier failed polish was successful.
    reference = original['actual_reference']
    for name in ('report_path', 'report_artifact_path'):
        value = reference.get(name)
        if value and Path(value).is_file(): protected[str(Path(value).resolve())] = sha(value)
    inputs = dict(project_copy=str(project_copy), project_source=str(source), project_source_sha256=sha(source),
        source_home_receipt=str(home_receipt), source_home_passed=original.get('passed'),
        source_home_outcome=original.get('actual_outcome'), exact_original_result_reference=reference,
        normal_ui_restore_receipt=str(restore), source_profile=str(profile),
        settings=str(copied_settings), local_settings=str(copied_local_settings),
        settings_source=str(settings), settings_sha256=sha(copied_settings),
        store=str(copied_store), store_sha256=sha(copied_store),
        source_store_sha256=sha(store), maximum_requests=args.maximum_requests,
        expected_model=args.expected_model, expected_revision=args.expected_revision,
        glossary_id=args.glossary_id, expected_cues=len(cues), expected_asr_evidence=len(evidence),
        expected_cue_ids=[row['id'] for row in cues], expected_evidence_ids=list(evidence),
        protected_before=protected,
        scope='Normal Studio all-current-cue AI glossary review of an exact copied real Home project; original ASR evidence retained; no new recognition/grouping; original failed Home result remains unchanged')
    (output/'recheck-input.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2)+'\n', 'utf8')
    return inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--project', type=Path, required=True, help='Exact original committed cold Home project; read only')
    parser.add_argument('--home-receipt', type=Path, required=True, help='Actual previous live-home-result.json, even when passed=false')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--borrowed-resources', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--environment', type=Path)
    parser.add_argument('--expected-model', default='grok-4.7')
    parser.add_argument('--expected-revision', default='57')
    parser.add_argument('--glossary-id', default='瓦罗兰特')
    parser.add_argument('--expected-cues', type=int, default=57)
    parser.add_argument('--expected-asr-evidence', type=int, default=50)
    parser.add_argument('--maximum-requests', type=int, choices=(1, 2), default=2,
                        help='Separately authorized total allowance, including every JSON repair/retry')
    parser.add_argument('--prepare-only', action='store_true', help='Create owned inputs only; no GUI or model execution')
    args = parser.parse_args()
    inputs = prepare_inputs(args)
    output = args.output.resolve()
    from twobyteasr.acceptance.glossary_live_resources import validate_manifest, MANIFEST_ENV
    validated = validate_manifest(args.borrowed_resources, output)
    protected = {**inputs['protected_before'], **validated['protected']}
    if args.prepare_only:
        print(json.dumps(dict(prepared=True, executed=False, inputs=str(output/'recheck-input.json'),
            maximum_requests=args.maximum_requests), ensure_ascii=False))
        return 0
    overrides = {}
    if args.environment:
        path = args.environment.resolve()
        if not path.is_relative_to(ROOT/'tmp'):
            raise ValueError('Environment overrides must be owned tmp data')
        overrides = json.loads(path.read_text('utf8'))
        overrides = overrides.get('environment', overrides)
        if not isinstance(overrides, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in overrides.items()):
            raise ValueError('Environment overrides must contain strings')
    os.environ.update(overrides)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_INVOKER_CWD=str(ROOT),
        TWOBYTEASR_STARTUP_TRACE=str(output/'recheck-evidence/driver-startup.jsonl'))
    from twobyteasr.test_isolation import install
    install()
    from twobyteasr.recognition.recognition_result import verify_result_reference
    verify_result_reference(json.dumps(inputs['exact_original_result_reference']), project_path=inputs['project_source'])
    environment = os.environ.copy()
    for key in ('TWOBYTEASR_STARTUP_RAISE', 'TWOBYTEASR_STARTUP_LEAVE_STUDIO',
                'TWOBYTEASR_STARTUP_EXIT_AFTER_INTERACTIVE', 'TWOBYTEASR_STARTUP_OPEN_PATHS'):
        environment.pop(key, None)
    environment.update(TWOBYTEASR_TEST_ROOT=str(output), TWOBYTEASR_ACCEPTANCE_DIR=str(output),
        TWOBYTEASR_ACCEPTANCE_SCENARIO='glossary-live-recheck', TWOBYTEASR_STARTUP_PROJECT=inputs['project_copy'],
        TWOBYTEASR_STARTUP_OPEN_STUDIO='1', TWOBYTEASR_STARTUP_TRACE=str(output/'recheck-evidence/gui-startup.jsonl'),
        TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', TWOBYTEASR_RUNTIME_REGISTRY_READ_ONLY='1',
        TWOBYTEASR_INVOKER_CWD=str(ROOT), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
        QT_QPA_PLATFORM='windows', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    environment[MANIFEST_ENV] = validated['manifest_path']
    from verify_glossary_live_home import prepare_private_cli, cleanup_private_cli
    from isolated_windows_desktop import run_on_desktop
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-B', str(ROOT/'quick_start.py')]
    private = None
    code, error = None, None
    try:
        private = prepare_private_cli(validated, output, json.loads(Path(inputs['settings']).read_text('utf-8-sig')))
        if private: environment['GROK_HOME'] = str(private)
        code = run_on_desktop(command, cwd=ROOT, env=environment, output=output/'process', timeout=360)
    except BaseException:
        error = traceback.format_exc()
    finally:
        removed = cleanup_private_cli(private, output)
    path = output/'result.json'
    result = json.loads(path.read_text('utf8')) if path.is_file() else dict(passed=False, error='No normal GUI receipt')
    result.update(process_exit=code, normal_entry_command=command, private_cli_credentials_removed=removed,
        driver_protection=[dict(path=p, before=digest, after=sha(p)) for p, digest in protected.items()])
    if error: result['driver_error'] = error
    result['passed'] = bool(result.get('passed') and result.get('gui_shutdown') and code == 0 and not error
        and removed and all(row['before'] == row['after'] for row in result['driver_protection']))
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str)+'\n', 'utf8')
    print(json.dumps(dict(passed=result['passed'], error=result.get('error'), receipt=str(path)), ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
