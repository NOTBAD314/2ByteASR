"""Replay a report's successful text records through the production cache engine.

No ASR, provider request, user project/glossary write or original-cache mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if not output.is_relative_to((ROOT / 'tmp').resolve()):
        raise ValueError('verification output must be inside repository tmp')
    output.mkdir(parents=True, exist_ok=False)
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output / 'isolated')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from twobyteasr.test_isolation import install
    install()
    import subtitle_core
    from twobyteasr.recognition import cache
    from twobyteasr.providers import ai_providers
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.providers.asr_provider_snapshot import ProviderSnapshot, TimeoutPolicy

    original_path = Path(args.report).resolve()
    original_bytes = original_path.read_bytes()
    report = json.loads(original_bytes.decode('utf-8-sig'))
    snapshot_row = next(row for row in report['events'] if
        row.get('event') == 'asr_provider_snapshot' and row.get('stage') == 'polished')
    fields = {key: snapshot_row[key] for key in ProviderSnapshot.__dataclass_fields__
              if key in snapshot_row and key not in {'timeout_policy', 'prompt_versions', 'capabilities'}}
    fields.update(timeout_policy=TimeoutPolicy(**snapshot_row['timeout_policy']),
        prompt_versions=tuple(sorted(snapshot_row['prompt_versions'].items())),
        capabilities=tuple(snapshot_row['capabilities']),
        _endpoint=tuple({'provider': snapshot_row['provider'], 'model': snapshot_row['model'],
            'base_url': snapshot_row['endpoint_identity'], 'protocol': snapshot_row['protocol']}.items()))
    snapshot = ProviderSnapshot(**fields)
    texts = {str(row['cue_id']): row['details']['final_text'] for row in report['events']
             if row.get('event') == 'terminology_polish_final'}
    summary = report['polishing_summary']
    if len(texts) != summary['success_cues'] or summary['fallback_cues']:
        raise ValueError('this replay requires complete successful text coverage')
    if not texts:
        raise ValueError('report has no successful final text records')
    cache_dir = output / 'cache'
    cache_dir.mkdir()
    cache_context = {'cache_dir': str(cache_dir), 'identity': {
        'report_sha256': hashlib.sha256(original_bytes).hexdigest(), 'provenance': 'report_final_text_replay'}}
    owner = RuntimeContext(provider_snapshot=snapshot, event_log_path=str(output / 'events.jsonl'))
    owner.polishing_summary = dict(summary)
    owner.terminology_status = dict(report['terminology_summary'])
    events, calls = [], []
    def no_requests(*a, **kw):
        raise RuntimeError('report-cache replay must not invoke any provider')
    ai_providers.provider_for_stage = no_requests
    def replay_text():
        calls.append(1)
        return dict(texts)
    with activate_runtime_context(owner, legacy=subtitle_core), cache.run_event_observer(
            lambda event, payload: events.append({'event': event, **payload})):
        first = cache.run_cached_stage('polished', cache_context, replay_text,
            extra_signature={'report_sha256': cache_context['identity']['report_sha256']})
        owner.enable_term_search = True
        second = cache.run_cached_stage('polished', cache_context, replay_text,
            extra_signature={'report_sha256': cache_context['identity']['report_sha256']})
    payload = json.loads((cache_dir / 'polished.json').read_text(encoding='utf-8'))
    checks = {
        'input_report_unchanged': original_bytes == original_path.read_bytes(),
        'successful_text_records_preserved': first == second == texts,
        'successful_text_cache_reused_after_search_choice_change': len(calls) == 1,
        'no_optional_failure_marks_text_fallback': not any(row.get('event') == 'cache_skip_fallback' for row in events),
        'cache_does_not_claim_search_success': 'terminology_status' not in payload and
            'terminology' not in payload['polishing_summary'],
        'production_cache_write_and_hit': any(row.get('event') == 'cache_write' for row in events) and
            any(row.get('event') == 'cache_hit' for row in events),
    }
    receipt = {'passed': all(checks.values()), 'checks': checks,
        'report_sha256': cache_context['identity']['report_sha256'],
        'started_at': report['started_at'], 'provider': snapshot.provider, 'model': snapshot.model,
        'successful_processing_records': len(texts), 'final_subtitle_count': report['result']['cue_count'],
        'fallback_records': summary['fallback_cues'], 'runner_calls': len(calls),
        'asr_or_provider_requests': 0, 'user_project_or_glossary_writes': 0,
        'provenance': 'existing successful report text replay; no new recognition or API completion'}
    (output / 'result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
