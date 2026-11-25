"""Paid, real-model rerun of a task's Japanese grouping stage (2026-11-25).

Rebuilds the corrected source rows of a recognition task JSON from its
``grouping_request_contract`` events and runs the current ``group_subtitles``
with the configured grouping provider, with a real nagisa morphology document
(tagged by an interpreter that has nagisa) installed exactly as the pipeline
does. Only the grouping stage is sent; no audio, ASR or proofreading.

Run only when the user has authorized paid requests. A cost ledger stops a run
before it starts when the authorized budget (USD, from the API's own usage x
saved tariff, the high estimate) would be exceeded.

    python -X utf8 -m twobyteasr.acceptance.japanese_grouping_live task.json out.json \
        --tagger-python PATH --ledger ledger.json --budget-usd 2.5
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

WATCHED = {
    'grouping_request_contract', 'grouping_api_fallback', 'grouping_range_pending_retry', 'llm_request_retry',
    'japanese_grouping_receipt', 'japanese_grouping_candidates', 'grouping_marked_boundaries_snapped',
    'grouping_origin_summary', 'grouping_partial', 'japanese_grouping_repair_failed',
    'japanese_grouping_repair_repeated', 'asr_provider_request', 'api_usage', 'grouping_batch_plan',
    'grouping_trace',
}


def _spent(ledger):
    return sum(float(row.get('usd_high') or 0) for row in ledger.get('runs', ()))


def _usage_usd(events):
    total, unknown = 0.0, 0
    for event in events:
        if event.get('event') != 'api_usage':
            continue
        cost = event.get('estimated_cost') or {}
        if cost.get('known'):
            total += float(cost.get('high') or 0)
        else:
            unknown += 1
    return total, unknown


def summarize(events, cues, hard_max=26):
    from ..subtitle_rules.text_rules import display_length
    batches = {}
    for event in events:
        index = event.get('batch_index', event.get('batch_id'))
        if index is None:
            continue
        row = batches.setdefault(str(index), dict(fallback=False, retries=0, snapped=0, repair_rounds=0,
                                                   counts={}, remaining=[], rejected_repairs=[]))
        name = event['event']
        if name == 'grouping_api_fallback':
            row['fallback'] = True
            row['fallback_error'] = event.get('error')
        elif name == 'llm_request_retry':
            row['retries'] += 1
        elif name == 'grouping_marked_boundaries_snapped':
            row['snapped'] += len(event.get('moved') or ())
        elif name == 'japanese_grouping_receipt':
            row['counts'] = event.get('counts') or {}
            row['repair_rounds'] = event.get('repair_rounds', 0)
            row['remaining'] = event.get('remaining_issues') or []
            row['rejected_repairs'] = [dict(reason=r.get('reason'), kind=(r.get('window') or {}).get('kind'))
                                       for r in event.get('rejected_repairs') or ()]
    over = [dict(text=c.text, units=display_length(c.text), origin=getattr(c, 'grouping_origin', ''))
            for c in cues if display_length(c.text) > hard_max]
    origins = {}
    for cue in cues:
        origin = getattr(cue, 'grouping_origin', '') or ''
        origins[origin] = origins.get(origin, 0) + 1
    clean = [key for key, row in batches.items()
             if not row['fallback'] and not row['counts'].get('local_fallback_split')
             and not row['counts'].get('local_indivisible_retained') and not row['remaining']]
    return dict(batches=batches, clean_batches=sorted(clean, key=lambda k: float(k)), over_limit=over,
                origins=origins, cue_count=len(cues))


def run(report_path, out_path, *, tagger_python, ledger_path, budget_usd, model=None):
    import copy
    import subtitle_core as legacy
    from ..recognition.run_context import RuntimeContext, activate_runtime_context
    from ..subtitle_rules.language_rules import language_scope
    from ..providers.asr_provider_snapshot import resolve_provider_snapshot
    from ..subtitle_rules import grouping, japanese_morphology
    from .grouping_live_replay import source_segments
    from .japanese_grouping_replay import tag_with

    ledger_path = Path(ledger_path)
    ledger = json.loads(ledger_path.read_text('utf-8')) if ledger_path.is_file() else dict(runs=[])
    spent = _spent(ledger)
    if spent >= budget_usd:
        raise SystemExit(f'budget reached: spent ${spent:.4f} of ${budget_usd:.2f}')
    report = json.loads(Path(report_path).read_text('utf-8-sig'))
    segments = source_segments(report)
    texts = [s.text for s in segments]
    document = japanese_morphology.build_document(texts, tag_with(tagger_python, texts))
    settings = copy.deepcopy(legacy.RUNTIME_SETTINGS)
    snapshot = resolve_provider_snapshot(settings, stage='group')
    if model:
        import dataclasses
        endpoint = dict(snapshot._endpoint)
        endpoint['model'] = model
        snapshot = dataclasses.replace(snapshot, model=model, _endpoint=tuple(endpoint.items()))
    events = []

    def record(name, payload):
        if name in WATCHED:
            events.append(dict(event=name, **payload))

    from ..recognition.cache import run_event_observer
    started = time.perf_counter()
    context = RuntimeContext(task_language='ja', requested_language='ja', enable_domain_terms=False,
                             asr_settings_snapshot=settings, provider_snapshots={'group': snapshot},
                             event_log_path=str(Path(out_path).with_suffix('.events.jsonl')))
    context.japanese_phrases = document
    with run_event_observer(record), language_scope('ja'), activate_runtime_context(context, legacy=legacy):
        cues = grouping.group_subtitles(segments, use_ai=True, provider_snapshot=snapshot)
    usd, unknown = _usage_usd(events)
    summary = summarize(events, cues)
    ledger['runs'].append(dict(at=time.strftime('%Y-%m-%dT%H:%M:%S'), report=str(report_path), model=snapshot.model,
                               usd_high=round(usd, 6), unknown_cost_requests=unknown,
                               requests=sum(e['event'] == 'api_usage' for e in events)))
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), 'utf-8')
    result = dict(source=str(report_path), model=snapshot.model, elapsed_seconds=round(time.perf_counter()-started, 1),
                  morphology=document.receipt(), usd_high=round(usd, 6), spent_total_usd=round(_spent(ledger), 6),
                  summary=summary,
                  cues=[dict(start=round(c.start, 3), end=round(c.end, 3), text=c.text, speaker=c.speaker,
                             origin=getattr(c, 'grouping_origin', '')) for c in cues],
                  events=[e for e in events if e['event'] != 'grouping_request_contract'])
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=1), 'utf-8')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('report')
    parser.add_argument('out')
    parser.add_argument('--tagger-python', required=True)
    parser.add_argument('--ledger', required=True)
    parser.add_argument('--budget-usd', type=float, required=True)
    parser.add_argument('--model')
    args = parser.parse_args(argv)
    result = run(args.report, args.out, tagger_python=args.tagger_python, ledger_path=args.ledger,
                 budget_usd=args.budget_usd, model=args.model)
    s = result['summary']
    print(json.dumps(dict(model=result['model'], seconds=result['elapsed_seconds'], usd_run=result['usd_high'],
                          usd_total=result['spent_total_usd'], cues=s['cue_count'], origins=s['origins'],
                          clean=f"{len(s['clean_batches'])}/{len(s['batches'])}", over_limit=len(s['over_limit'])),
                     ensure_ascii=False))
    for key, row in sorted(s['batches'].items(), key=lambda kv: float(kv[0])):
        print(key, json.dumps(dict(fallback=row['fallback'], retries=row['retries'], snapped=row['snapped'],
                                   rounds=row['repair_rounds'], counts=row['counts'],
                                   remaining=len(row['remaining']), rejected=row['rejected_repairs']),
                              ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
