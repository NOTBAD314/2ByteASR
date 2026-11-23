"""Recover recognition fallback windows against the open project's source evidence."""

import json
from pathlib import Path

def _repair_key(row):
    return (row.get('content_start'), row.get('content_end'), row.get('origin'),
            tuple(row.get('before', ())), tuple(row.get('after', ())))


def recover_grouping_windows(project, report=None):
    """Return one receipt per historic window. Historic row indices are evidence only."""
    from subtitle_core import content_exact
    if report is None:
        if not project.report_path:
            return []
        try:
            report = json.loads(Path(project.report_path).read_bytes())
        except (OSError, ValueError):
            return []
    metadata = project.generation_metadata
    identity = metadata.get('media_identity', {})
    result = report.get('result', {}).get('outputs', {})
    try:
        ref = json.loads(result.get('result_ref_json') or '{}')
    except (TypeError, ValueError):
        return []
    if (not ref.get('project_id') or ref['project_id'] != project.project_id
            or not identity.get('fingerprint') or identity['fingerprint'] != ref.get('media_fingerprint')
            or report.get('job_id') != metadata.get('job_id')):
        return []
    traces = {}
    for event in report.get('events', []):
        if event.get('event') == 'grouping_trace' and event.get('job_id') == report['job_id']:
            traces.setdefault(str(event.get('batch_id')), []).append(event)
    current = metadata.get('segmentation_source_spans', {}).get('cues', {})
    receipts = []
    for event in report.get('events', []):
        if event.get('event') not in {'grouping_minimal_fallback', 'grouping_source_range_retained'} or event.get('job_id') != report['job_id']:
            continue
        a, b = event['content_start'], event['content_end']
        matches = [trace for trace in traces.get(str(event['batch_id']), ())
                   if any(_repair_key(repair) == _repair_key(event) for repair in trace.get('boundary_receipts', ()))]
        trace = matches[0] if len(matches) == 1 else {}
        sources = set(trace.get('source_segment_ids', ()))
        historical_text = []
        historic_times = []
        cursor = 0
        for edge, cue in zip(trace.get('final_boundaries', ()), trace.get('cues', ())):
            if cursor < b and a < edge:
                historical_text.append(cue['text'])
                historic_times.extend((round(cue['start']*1000), round(cue['end']*1000)))
            cursor = edge
        matched = []
        if historical_text:
            left, right = min(historic_times), max(historic_times)
            for cue in project.cues:
                if cue.start_ms >= right + 350 or cue.end_ms <= left - 350:
                    continue
                info = current.get(cue.id, {})
                old = info.get('boundary_receipt', {})
                if (set(part.get('source_id') for part in info.get('parts', ())) & sources
                        and any(_repair_key(repair) == _repair_key(event) for repair in old.get('repairs', ()))):
                    matched.append(cue)
            if content_exact(''.join(c.text for c in matched)) != content_exact(''.join(historical_text)):
                matched = []
        receipts.append(dict(project_id=project.project_id, media_fingerprint=identity['fingerprint'],
            job_id=report['job_id'], batch_id=event['batch_id'], index_unit=trace.get('index_unit'),
            range_id=f"history:{report['job_id']}:{event['batch_id']}:{a}:{b}",
            source_ids=sorted(sources), source_span=[a, b], input_text=''.join(historical_text),
            start_ms=min(historic_times, default=None), end_ms=max(historic_times, default=None),
            category=event.get('reason'), status='matched' if matched else 'unmapped',
            last_candidate=event.get('after', []), cue_ids=[cue.id for cue in matched]))
    return receipts


def import_grouping_history(project):
    """Keep the verified source windows with the project after the report moves."""
    state = project.studio_state.get('ai_sentence_refine', {})
    if state.get('historical_windows') or not project.generation_metadata.get('job_id'):
        return
    windows = recover_grouping_windows(project)
    if windows:
        project.studio_state.setdefault('ai_sentence_refine', {})['historical_windows'] = windows


def map_grouping_window(project, window, candidates=None):
    from subtitle_core import content_exact

    start, end = window.get('start_ms'), window.get('end_ms')
    if start is None or end is None:
        return ()
    expected = content_exact(window.get('input_text', ''))
    if not expected:
        return ()
    spans = project.generation_metadata.get('segmentation_source_spans', {}).get('cues', {})
    sources = set(window.get('source_ids', ()))
    eligible = []
    for cue in project.cues if candidates is None else candidates:
        if cue.start_ms >= end + 350 or cue.end_ms <= start - 350:
            continue
        parts = spans.get(cue.id, {}).get('parts', ())
        source_ids = {part.get('source_id') for part in parts}
        for ref in cue.evidence_refs:
            row = project.asr_evidence.get(ref, {})
            if row.get('segment_id') is not None:
                source_ids.add(row['segment_id'])
            if str(ref).startswith(('segment-', 'segment:')) and str(ref)[8:].isdigit():
                source_ids.add(int(str(ref)[8:]))
        if sources.intersection(source_ids):
            eligible.append(cue)
    # Without a unique full-text match keep the historical range unassigned.
    # Split and merged cues can own the whole range plus adjacent source text.
    eligible.sort(key=lambda cue: (cue.start_ms, cue.end_ms, cue.id))
    hits = []
    for i in range(len(eligible)):
        combined = ''
        for j in range(i, len(eligible)):
            combined += content_exact(eligible[j].text)
            if combined == expected:
                hits.append(tuple(eligible[i:j+1]))
                break
            if not expected.startswith(combined):
                break
    if len(hits) == 1:
        return hits[0]
    if hits:
        return ()
    combined = ''.join(content_exact(cue.text) for cue in eligible)
    if (eligible and combined.count(expected) == 1 and eligible[0].start_ms <= start + 350
            and eligible[-1].end_ms >= end - 350):
        return tuple(eligible)
    return ()
