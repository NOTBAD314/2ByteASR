"""Paid, real-model rerun of a task's Chinese grouping stage (2026-11-22).

Rebuilds the corrected source sentences of a recognition task JSON from its
``grouping_request_contract`` events (text, speaker, source seconds and the
provider word times) and runs the current ``group_subtitles`` with the
configured grouping provider. Only the grouping stage is sent; no audio, no
ASR and no proofreading. Run it only when the user has authorized paid
requests. Output: the final cues and every recorded grouping event.

    python -X utf8 -m twobyteasr.acceptance.grouping_live_replay task.json out.json
"""
from __future__ import annotations

import json
import sys
import time


def source_segments(report):
    from ..recognition.transcript_data import SpeechSegment, WordUnit
    rows, seen = [], set()
    for event in report.get('events', ()):
        if event.get('event') != 'grouping_request_contract':
            continue
        body = event['request_body']
        timing = {t['source_id']: t for t in body.get('source_timing', ())}
        for seg in body.get('segments', ()):
            if seg['id'] in seen:
                continue
            seen.add(seg['id'])
            t = timing.get(seg['id'], {})
            measured = list(t.get('words') or [])
            words = [WordUnit(w['start_ms']/1000, w['end_ms']/1000, w['text'], .9) for w in measured]
            segment = SpeechSegment(seg['id'], float(seg['start']), float(seg['end']), seg['text'], .9, words,
                                    speaker=seg.get('speaker') or 'S00')
            segment.caption_arbitration = dict(word_timing=dict(basis=t.get('basis', 'source_segment'),
                                                                measured_words=measured))
            rows.append(segment)
    rows.sort(key=lambda s: (s.start, s.segment_id))
    return rows


def run(report_path, out_path, *, settings=None, model=None, thinking=None, pauses=True, editor=False):
    import subtitle_core as legacy
    from ..recognition.run_context import RuntimeContext, activate_runtime_context
    from ..subtitle_rules.language_rules import language_scope
    from ..providers.asr_provider_snapshot import resolve_provider_snapshot
    from ..subtitle_rules import grouping
    with open(report_path, encoding='utf-8-sig') as handle:
        report = json.load(handle)
    segments = source_segments(report)
    import copy
    settings = copy.deepcopy(settings or legacy.RUNTIME_SETTINGS)
    settings.setdefault('switches', {})['grouping_ai_editor'] = bool(editor)
    snapshot = resolve_provider_snapshot(settings, stage='group')
    if model or thinking is not None:
        import dataclasses
        endpoint = dict(snapshot._endpoint)
        if model:
            endpoint['model'] = model
        snapshot = dataclasses.replace(snapshot, model=model or snapshot.model,
            enable_thinking=snapshot.enable_thinking if thinking is None else bool(thinking),
            _endpoint=tuple(endpoint.items()))
    events = []
    original = grouping.record_run_event

    def record(name, **data):
        events.append(dict(event=name, **data))
        try:
            original(name, **data)
        except Exception:
            pass

    grouping.record_run_event = record
    started = time.perf_counter()
    try:
        context = RuntimeContext(task_language='zh', requested_language='zh', enable_domain_terms=False,
                                 asr_settings_snapshot=settings, provider_snapshots={'group': snapshot})
        with language_scope('zh'), activate_runtime_context(context, legacy=legacy):
            if pauses:
                from ..subtitle_rules.pause_marks import mark_pause_spaces
                segments = mark_pause_spaces(segments, snapshot, record=record)
            cues = grouping.group_subtitles(segments, use_ai=True, provider_snapshot=snapshot)
    finally:
        grouping.record_run_event = original
    result = dict(source=str(report_path), job_id=report.get('job_id'), model=snapshot.model,
                  elapsed_seconds=round(time.perf_counter()-started, 1),
                  cues=[dict(start=round(c.start, 3), end=round(c.end, 3), text=c.text, speaker=c.speaker,
                             origin=getattr(c, 'grouping_origin', '')) for c in cues],
                  usage=[e for e in events if e['event'] == 'api_usage'],
                  events=[e for e in events if e['event'] in {
                      'grouping_trace', 'grouping_quality_retry', 'grouping_partial', 'grouping_model_quality',
                      'pause_marks_applied', 'grouping_editor', 'grouping_editor_change',
                      'grouping_editor_failed'}])
    with open(out_path, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False)
    return result


if __name__ == '__main__':
    output = run(sys.argv[1], sys.argv[2])
    print(len(output['cues']), 'cues', output['elapsed_seconds'], 's', output['model'])
