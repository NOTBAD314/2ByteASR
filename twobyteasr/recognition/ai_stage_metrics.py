"""Measure the AI proofreading / grouping stages of one task journal, and compare two.

2026-11-18 (review of the 鳴潮 special): every prompt or policy change to these stages was
judged by reading one journal by hand. These are the counters that review used, read from
the events the pipeline already records, so a change can be checked against the same
material before and after (`scripts/ai_stage_metrics.py old.json new.json`).

Only recorded facts are counted; a counter whose events are absent is None, never 0.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Iterable

METRICS_VERSION = "ai-stage-metrics-v1"


def _events(report: dict) -> list[dict]:
    return [row for row in report.get('events') or () if isinstance(row, dict)]


def _named(events: Iterable[dict], name: str) -> list[dict]:
    return [row for row in events if row.get('event') == name]


def _stage_seconds(events: list[dict], label_part: str) -> float | None:
    started = completed = None
    for row in events:
        label = str(row.get('label') or '')
        if label_part not in label:
            continue
        if row.get('event') == 'stage_started' and started is None:
            started = row.get('monotonic_seconds')
        elif row.get('event') == 'stage_completed':
            completed = row.get('monotonic_seconds')
    if isinstance(started, (int, float)) and isinstance(completed, (int, float)):
        return round(completed - started, 1)
    return None


def _escalation_seconds(events: list[dict], stage: str) -> float | None:
    total, found, opened = 0.0, False, None
    for row in _named(events, 'ai_escalation_round'):
        if row.get('stage') != stage:
            continue
        if row.get('state') == 'started':
            opened = row.get('monotonic_seconds')
        elif row.get('state') == 'completed' and isinstance(opened, (int, float)):
            total += float(row.get('monotonic_seconds', opened)) - float(opened)
            found, opened = True, None
    return round(total, 1) if found else None


def _usage(events: list[dict]) -> dict:
    rows: dict[str, Counter] = {}
    for row in _named(events, 'api_usage'):
        stage = str(row.get('stage') or 'unknown')
        counter = rows.setdefault(stage, Counter())
        counter['requests'] += 1
        for key in ('input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens'):
            counter[key] += int(row.get(key) or 0)
        try:
            counter['cost_usd_micro'] += round(float((row.get('estimated_cost') or {}).get('high') or 0) * 1e6)
        except (TypeError, ValueError):
            pass
    return {stage: dict(counter) for stage, counter in sorted(rows.items())}


def measure(report: dict) -> dict[str, Any]:
    """Counters for one journal (the task JSON the app saves next to the project)."""
    events = _events(report)
    polish_details = [row.get('details') or {} for row in _named(events, 'terminology_polish_detail')]
    accepted = Counter(edit.get('rule_id') or edit.get('type') or 'unknown'
                       for detail in polish_details for edit in detail.get('accepted_edits') or ())
    rejected = Counter(edit.get('rule_id') or 'unknown'
                       for detail in polish_details for edit in detail.get('rejected_edits') or ())
    dispositions = Counter(row.get('disposition') for detail in polish_details
                           for row in detail.get('suspect_results') or ())
    polish_fallbacks = _named(events, 'polishing_api_fallback')
    group_fallbacks = _named(events, 'grouping_api_fallback')
    local_terms = _named(events, 'terminology_applied')
    skipped_reasons = Counter()
    replaced = 0
    for row in local_terms[:1]:      # the first pass sees the transcript before proofreading
        replaced = int(row.get('replacement_count') or 0)
        for segment in row.get('matches') or ():
            for hit in segment.get('matches') or ():
                if hit.get('reason') not in (None, '', 'already_canonical', 'confirmed_alias', 'case_normalization'):
                    skipped_reasons[hit['reason']] += 1
    review_categories = Counter(str(item.get('category')) for item in report.get('review_items') or ()
                                if isinstance(item, dict))
    return {
        'metrics_version': METRICS_VERSION,
        'job_id': report.get('job_id'),
        'media': (report.get('media') or {}).get('name'),
        'polish': {
            'stage_seconds': _stage_seconds(events, '校对'),
            'batches': sum(1 for row in _named(events, 'cloud_batch_completed') if row.get('stage') == 'polished'),
            'retries': sum(1 for row in _named(events, 'llm_request_retry') if row.get('stage') == 'polished'),
            'format_splits': len(_named(events, 'llm_structured_batch_split')),
            'shape_regrouped': len(_named(events, 'polishing_response_shape_regrouped')),
            'field_aliases': len(_named(events, 'polishing_response_field_alias')),
            'span_repairs': len(_named(events, 'polishing_edit_span_repaired')),
            'fallback_events': len(polish_fallbacks),
            'fallback_cues': sum(len(row.get('cue_ids') or ()) for row in polish_fallbacks),
            'fallback_categories': dict(Counter(row.get('category') for row in polish_fallbacks)),
            'escalation_seconds': _escalation_seconds(events, 'polished'),
            'accepted_edits': dict(accepted),
            'rejected_edits': dict(rejected),
            'suspect_dispositions': dict(dispositions),
        },
        'grouping': {
            'stage_seconds': _stage_seconds(events, '断句'),
            'batches': sum(1 for row in _named(events, 'cloud_batch_completed') if row.get('stage') == 'grouped'),
            'retries': sum(1 for row in _named(events, 'llm_request_retry') if row.get('stage') == 'grouped'),
            'fallback_events': len(group_fallbacks),
            'fallback_categories': dict(Counter(row.get('category') for row in group_fallbacks)),
            'escalation_seconds': _escalation_seconds(events, 'grouped'),
            'local_hard_repairs': len(_named(events, 'grouping_local_repair')),
            'short_tail_merges': len(_named(events, 'grouping_short_span_repair')),
            'short_tails_kept': len(_named(events, 'grouping_short_span_retained')),
            'turn_breaks_added': len(_named(events, 'grouping_turn_mandatory_breaks_added')),
            'marked_picks_snapped': sum(int(row.get('moved_count') or 0)
                                        for row in _named(events, 'grouping_marked_boundaries_snapped')),
        },
        'terminology': {
            'local_replacements_first_pass': replaced if local_terms else None,
            'local_skipped_by_reason': dict(skipped_reasons),
            'libraries_blocked_by_scene': [lib.get('library_name') for row in _named(events, 'terminology_library_domain_blocked')
                                           for lib in row.get('libraries') or ()],
        },
        'usage': _usage(events),
        'review_items': dict(review_categories),
    }


def compare(before: dict, after: dict) -> list[tuple[str, Any, Any]]:
    """(path, before, after) for every numeric counter that differs, in a stable order."""
    rows = []

    def walk(path, a, b):
        if isinstance(a, dict) or isinstance(b, dict):
            a, b = a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {}
            for key in sorted(set(a) | set(b), key=str):
                walk(f'{path}.{key}' if path else str(key), a.get(key), b.get(key))
        elif a != b and (isinstance(a, (int, float)) or isinstance(b, (int, float))):
            rows.append((path, a, b))
    walk('', {k: v for k, v in before.items() if k not in ('job_id', 'media')},
         {k: v for k, v in after.items() if k not in ('job_id', 'media')})
    return rows


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))
