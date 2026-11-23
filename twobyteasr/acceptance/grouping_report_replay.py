"""Offline replay of a recognition task's Chinese grouping retries (2026-11-22).

A task JSON keeps, per batch, the exact request (source text, legal marks,
protected cuts, pause hints), the model's first answer and every window
retry answer. ``extract`` keeps only those parts; ``replay`` rebuilds the
boundary check from them and runs the current retry loop with a stand-in
provider, so changes to the retry gate are measured on a real job without
network, accounts or media.

The stand-in answers a window with the AI answer recorded for the same
window and round when there is one, otherwise with the window's reference
answer, otherwise with the current lines. Recorded answers for windows that
no longer exist cannot be replayed; the stand-in is a measurement aid, not a
model.
"""
from __future__ import annotations

import json
from collections import Counter
from types import SimpleNamespace


def extract(report):
    """The grouping inputs and recorded answers of a task JSON (dict or path)."""
    if not isinstance(report, dict):
        with open(report, encoding='utf-8-sig') as handle:
            report = json.load(handle)
    events = report.get('events', ())
    requests = {e['batch_id']: e['request_body'] for e in events
                if e.get('event') == 'grouping_request_contract' and e.get('batch_id') is not None}
    traces = {e['batch_id']: e for e in events if e.get('event') == 'grouping_trace'}
    retries = {}
    for e in events:
        if e.get('event') == 'grouping_quality_retry' and e.get('request_dispatched'):
            retries.setdefault(e['batch_id'], []).append(dict(
                round=e['round'], content_start=e['content_start'], content_end=e['content_end'],
                candidate=e['candidate_boundaries'], status=e['status']))
    batches = []
    for batch_id in sorted(traces):
        if batch_id not in requests:
            continue
        body, trace = requests[batch_id], traces[batch_id]
        batches.append(dict(
            batch_id=batch_id, source_text=body['source_text'], total_length=body['total_length'],
            allowed=body['allowed_boundaries'], required=sorted(
                set(body.get('hard_break_character_offsets', ())) | set(body.get('protected_source_offsets', ()))),
            pauses={str(h['offset']): h['gap_ms']/1000 for h in body.get('pause_hints', ())},
            source_offsets=body.get('source_segment_offsets', []),
            model_boundaries=trace['model_boundaries'], final_boundaries=trace['final_boundaries'],
            retries=retries.get(batch_id, [])))
    return dict(job_id=report.get('job_id'), batches=batches)


def quality_of(batch):
    from ..subtitle_rules.grouping_quality import BoundaryQuality
    quality = BoundaryQuality(batch['source_text'], required=batch['required'],
                              pauses={int(k): v for k, v in batch['pauses'].items()})
    quality.allowed = sorted(set(batch['allowed']) | {quality.total})
    quality.strict_model_boundaries = True
    return quality


def _first_answer(quality, model):
    from ..subtitle_rules.ai_boundary_policy import break_candidates, place_on_marks, snap_offset_errors
    boundaries, _ = place_on_marks(list(model), break_candidates(quality), right=quality.total)
    boundaries, _ = snap_offset_errors(quality, boundaries)
    return sorted(set(boundaries) | quality.required | {quality.total})


def replay_batch(batch, *, rounds_answer='recorded'):
    """Run the current retry loop on one batch; returns (quality, first, final, events)."""
    from ..subtitle_rules.grouping import GROUPING_SCHEMA
    from ..subtitle_rules.grouping_quality_request import QualityRetryBudget, retry_quality_windows
    quality = quality_of(batch)
    first = _first_answer(quality, batch['model_boundaries'])
    recorded = {(r['round'], r['content_start'], r['content_end']): r['candidate'] for r in batch['retries']}
    events = []

    def complete(messages, **_kwargs):
        request = json.loads(messages[1]['content'])
        rows = []
        for window in request['windows']:
            left, right = window['body_range']
            answer = recorded.get((request['round'], left, right)) if rounds_answer == 'recorded' else None
            if answer is None and window.get('reference_answer'):
                answer = window['reference_answer']['boundaries']
            if answer is None:
                answer = window['current_boundaries']
            rows.append(dict(id=window['id'], boundaries=answer))
        return json.dumps(dict(windows=rows))

    from ..providers.asr_provider_snapshot import TimeoutPolicy
    snapshot = SimpleNamespace(max_output_tokens=10000, enable_thinking=False, thinking_protocol='auto',
                               timeout_policy=TimeoutPolicy())
    final = retry_quality_windows(quality, first, first, provider=SimpleNamespace(complete=complete),
        snapshot=snapshot, schema=GROUPING_SCHEMA, budget=QualityRetryBudget(),
        record=lambda name, **data: events.append(dict(event=name, **data)), batch_index=batch['batch_id'])
    return quality, first, final, events


def metrics(quality, first, final):
    """Line statistics and how much of the first AI answer survived."""
    from ..subtitle_rules.ai_boundary_policy import inspect, blocking_issues
    edges = [0, *final]
    lengths = [b-a for a, b in zip(edges, final)]
    inner_first = set(first) - {quality.total}
    kept = inner_first & set(final)
    return dict(lines=len(final), first_cuts=len(inner_first), kept_first_cuts=len(kept),
                near_limit_lines=sum(1 for n in lengths if quality.max_chars-1 <= n <= quality.max_chars),
                over_limit_lines=sum(1 for n in lengths if n > quality.max_chars),
                blocking=len(blocking_issues(inspect(quality, final))))


def replay(report, *, rounds_answer='recorded'):
    data = report if isinstance(report, dict) and 'batches' in report else extract(report)
    total = Counter()
    rows = []
    for batch in data['batches']:
        quality, first, final, events = replay_batch(batch, rounds_answer=rounds_answer)
        row = metrics(quality, first, final)
        row['merges_of_fitting_lines'] = sum(
            1 for e in events if e['event'] == 'grouping_quality_retry' and e['status'] == 'improved'
            and all(len(x) <= quality.max_chars for x in e['before']) and len(e['after']) < len(e['before']))
        row['batch_id'] = batch['batch_id']
        rows.append(row)
        total.update({k: v for k, v in row.items() if k != 'batch_id'})
    total = dict(total)
    total['kept_first_ratio'] = round(total['kept_first_cuts']/max(1, total['first_cuts']), 3)
    total['near_limit_ratio'] = round(total['near_limit_lines']/max(1, total['lines']), 3)
    return dict(total=total, batches=rows)


if __name__ == '__main__':
    import sys
    print(json.dumps(replay(sys.argv[1], rounds_answer=sys.argv[2] if len(sys.argv) > 2 else 'recorded')['total'],
                     ensure_ascii=False, indent=1))
