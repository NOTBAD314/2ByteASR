"""Task-PCM speech coverage, independent of transport and language admission.

This module is stdlib-only so the isolated MOSS worker can load it by file
path without importing the GUI's native libraries.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from difflib import SequenceMatcher

KEY = 'speech_coverage'
POLICY = 'speech-coverage-v2'
TOLERANCE = .25
MIN_GAP = 1.0
AUTO_CONFIDENCE = .85


def recovery_speaker(label):
    return str(label).startswith(('UNCONFIRMED_', 'RECOVERY_', 'LOCAL_'))


def automatic_speech(region, *, anomalous=False):
    if region.get('processing_only') or region.get('confidence_bounds_verified') is False:
        return False
    if region.get('kind') in {'silence', 'music', 'effect', 'non_speech'}:
        return False
    if region.get('speech_verified'):
        return True
    # A single VAD posterior measures its own detector, not independent proof
    # that a missing transcript contains target speech (music can score high).
    return bool(region.get('speech_corroborated'))


def union(ranges, *, tolerance=0.0):
    ordered = []
    for value in ranges:
        start, end = (value['start'], value['end']) if isinstance(value, dict) else value
        start, end = float(start), float(end)
        if math.isfinite(start) and math.isfinite(end) and end > start:
            ordered.append((start, end))
    result = []
    for start, end in sorted(ordered):
        if result and start <= result[-1][1] + tolerance:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def subtract(ranges, covered, *, tolerance=0.0, minimum=0.0):
    """Subtract a union with a moving cursor, including nested/overlapping rows."""
    covered = union(covered)
    result, index = [], 0
    for start, end in union(ranges):
        cursor = start
        while index < len(covered) and covered[index][1] + tolerance <= start:
            index += 1
        scan = index
        while scan < len(covered) and covered[scan][0] - tolerance < end:
            low, high = covered[scan]
            if low - tolerance > cursor:
                result.append((cursor, min(end, low - tolerance)))
            cursor = max(cursor, high + tolerance)
            if cursor >= end:
                break
            scan += 1
        if cursor < end:
            result.append((cursor, end))
    return [(a, b) for a, b in result if b - a >= minimum]


def text_ranges(rows):
    ranges = []
    for row in rows:
        if isinstance(row, dict):
            text, start, end = row.get('text'), row.get('start'), row.get('end')
        else:
            text, start, end = row.text, row.start, row.end
        if str(text or '').strip():
            ranges.append((start, end))
    return union(ranges)


def pending(state):
    return [gap for gap in (state or {}).get('gaps', [])
            if gap.get('status') not in {'recovered', 'excluded', 'non_speech'}]


def classify_state(state):
    """Reclassify legacy derived status without changing original receipts."""
    state = copy.deepcopy(state or {})
    for gap in pending(state):
        evidence = gap.get('evidence') or {}
        failed = gap.get('error_category') or any(a.get('error') not in (None, '', 'no_usable_captions')
                                                 for a in gap.get('attempts', ()))
        reliable = evidence.get('speech_verified') or evidence.get('speech_corroborated')
        classification = gap.get('classification')
        if failed or classification == 'processing_failure':
            classification = 'processing_failure'
        elif reliable:
            classification = 'supported_speech_gap'
        else:
            classification = 'uncertain_speech'
        gap['classification'] = classification
        if classification == 'uncertain_speech':
            gap['status'] = 'needs_confirmation'
        elif classification == 'processing_failure':
            gap['status'] = 'failed'
    state['classification_policy'] = POLICY
    return state


def counts(state):
    rows = pending(classify_state(state))
    return dict(speech_gap_count=sum(g['classification'] == 'supported_speech_gap' for g in rows),
                speech_failure_count=sum(g['classification'] == 'processing_failure' for g in rows),
                speech_confirmation_count=sum(g['classification'] == 'uncertain_speech' for g in rows))


def _overlaps(a, b):
    return min(a[1], b[1]) > max(a[0], b[0])


def make_state(speech, rows, *, duration, windows=(), excluded=(), source='vad', identity=''):
    """Unknown/energy-only VAD stays review-only. Explicit non-speech is omitted."""
    execution = getattr(speech, 'execution', {})
    detections = list(execution.get('detected_regions', ()))
    for shard in execution.get('shards', ()):
        detections.extend(shard.get('detected_regions', ()))
    regions = [dict(r) for r in [*speech, *detections] if not r.get('processing_only')
               and r.get('kind', 'speech') not in {'silence', 'music', 'effect', 'non_speech'}]
    spans = [(max(0.0, float(r['start'])), min(duration, float(r['end']))) for r in regions]
    failures = [w for w in windows if w.get('error') or w.get('error_category')
                or (not w.get('complete', True) and w.get('truncation_reasons'))]
    targets = spans + [(float(w['start']), float(w['end'])) for w in failures]
    missing = subtract(subtract(targets, excluded), text_ranges(rows), tolerance=TOLERANCE, minimum=MIN_GAP)
    gaps = []
    for start, end in missing:
        evidence = [r for r in regions if _overlaps((start, end), (float(r['start']), float(r['end'])))]
        affected = [w for w in windows if _overlaps((start, end), (float(w['start']), float(w['end'])))]
        anomalies = [w for w in affected if not w.get('complete', True)]
        confidence = max((float(r.get('confidence') or 0) for r in evidence), default=0)
        trained = any(r.get('detector') == 'firered_vad' for r in evidence)
        recoverable = bool(evidence) and all(automatic_speech(r, anomalous=bool(anomalies)) for r in evidence)
        reason = ','.join(sorted({reason for w in anomalies for reason in w.get('truncation_reasons', [])}))
        failed = [w for w in failures if w in affected]
        classification = ('processing_failure' if failed else
                          'supported_speech_gap' if recoverable else 'uncertain_speech')
        gap_id = hashlib.sha256(json.dumps([identity, round(start*16000), round(end*16000)]).encode()).hexdigest()[:24]
        gaps.append(dict(id=gap_id, start=start, end=end, reason=reason or 'speech_without_transcript',
            first_missing_stage='parsed_response', classification=classification,
            status='failed' if failed else 'pending' if recoverable else 'needs_confirmation',
            evidence=dict(source=source, confidence=confidence or None, trained_vad=trained,
                          anomalous_window=bool(anomalies), regions=copy.deepcopy(evidence),
                          speech_verified=any(r.get('speech_verified') for r in evidence),
                          speech_corroborated=any(r.get('speech_corroborated') for r in evidence)),
            processing_errors=[{k: w[k] for k in ('index', 'error', 'error_category', 'truncation_reasons') if k in w}
                               for w in failed],
            window_ids=[w.get('index', w.get('request_id')) for w in affected],
            attempts=[], recovery_source=None, recovered_ranges=[], remaining_ranges=[[start, end]]))
    return dict(policy=POLICY, clock='task_pcm_zero', duration=duration, identity=identity,
                speech_ranges=[list(r) for r in union(spans)], excluded_ranges=[list(r) for r in union(excluded)],
                gaps=gaps, stages=[])


def checkpoint(state, stage, rows, *, excluded=()):
    """Record the first downstream loss without treating a later stage as ASR."""
    ranges = text_ranges(rows)
    previous = state.get('stages', [])
    if previous:
        lost = subtract(previous[-1]['ranges'], ranges, tolerance=TOLERANCE, minimum=MIN_GAP)
        # Broad paragraph timestamps also contain pauses. Only independent
        # speech evidence can turn a timing contraction into a speech gap.
        lost = [(max(a, c), min(b, d)) for a, b in lost
                for c, d in state.get('speech_ranges', []) if min(b, d)-max(a, c) >= MIN_GAP]
        lost = subtract(lost, excluded)
        for start, end in lost:
            # Existing upstream gaps retain the earlier cause.
            if any(_overlaps((start, end), (g['start'], g['end'])) for g in state['gaps']):
                continue
            gap_id = hashlib.sha256(f'{state.get("identity")}/{stage}/{start}/{end}'.encode()).hexdigest()[:24]
            state['gaps'].append(dict(id=gap_id, start=start, end=end, reason='downstream_text_loss',
                first_missing_stage=stage, status='needs_confirmation', attempts=[],
                recovery_source='retained_upstream', recovered_ranges=[], remaining_ranges=[[start, end]]))
    state.setdefault('stages', []).append(dict(stage=stage, ranges=[list(r) for r in ranges]))
    return state


def update_gap(gap, rows, *, source, elapsed=0.0, error='', request_count=1):
    target = gap.get('remaining_ranges') or [[gap['start'], gap['end']]]
    coverage = text_ranges(rows)
    remaining = [list(r) for r in subtract(target, coverage, tolerance=TOLERANCE, minimum=MIN_GAP)]
    recovered = subtract(target, remaining)
    gap.setdefault('attempts', []).append(dict(source=source, elapsed_seconds=round(elapsed, 3),
        request_count=request_count, error=error, covered_ranges=[list(r) for r in coverage], remaining_ranges=remaining))
    gap['recovered_ranges'] = [list(r) for r in union([*gap.get('recovered_ranges', []), *recovered])]
    gap['remaining_ranges'] = remaining
    gap['recovery_source'] = source
    gap['status'] = ('recovered' if not remaining else 'failed' if error else
                     'partial' if gap['recovered_ranges'] else 'needs_confirmation')
    if error:
        gap['classification'] = 'processing_failure'
    elif not rows and remaining:
        gap['classification'] = 'uncertain_speech'
        gap['automatic_retry_stopped'] = 'empty_success'


def merge_rows(existing, candidates, ranges):
    """Keep originals and true repetitions. Suppress only concurrent matching text."""
    result = [copy.deepcopy(r) for r in existing]
    accepted = []
    for candidate in sorted(candidates, key=lambda r: (float(r['start']), float(r['end']))):
        row = copy.deepcopy(candidate)
        if row.get('cloud_gap'):
            continue
        start, end = float(row['start']), float(row['end'])
        if not str(row.get('text') or '').strip() or not math.isfinite(start + end) or end <= start:
            continue
        # A context line wholly outside the requested hole never changes a good region.
        center = (start + end) / 2
        if not any(a <= center <= b for a, b in ranges):
            continue
        duplicate = False
        for old in result:
            overlap = min(end, float(old['end'])) - max(start, float(old['start']))
            shorter = min(end-start, float(old['end'])-float(old['start']))
            if overlap > 0 and overlap / max(.01, shorter) >= .65:
                similar = SequenceMatcher(None, str(old['text']).strip(), str(row['text']).strip()).ratio()
                if similar >= .9:
                    duplicate = True
                    break
        if not duplicate:
            result.append(row)
            accepted.append(row)
    return sorted(result, key=lambda r: (float(r['start']), float(r['end']))), accepted


def recover(state, rows, runner, *, source, cancel=lambda: None, max_requests=24, max_audio_seconds=1800,
            max_elapsed_seconds=900, window_seconds=90, context_seconds=2):
    """A callback receives absolute task-PCM bounds and returns global rows.

    Only independently supported gaps auto-run. Refusal exceptions stop this
    gap and retain their category. Confirmed UI range retries use the normal
    recognition transaction instead of editing a project here.
    """
    started, requests, audio_used = time.monotonic(), 0, 0.0
    cancel()
    result = list(rows)
    for gap in state['gaps']:
        if any(d.get('status') == 'non_speech' and d.get('source_identity') == state.get('identity')
               and float(d.get('start', gap['start'])) <= gap['start']
               and float(d.get('end', gap['end'])) >= gap['end']
               for key, d in (state.get('decisions') or {}).items()
               if key == gap['id'] or 'start' in d and 'end' in d):
            continue
        if (gap['status'] != 'pending' or gap.get('automatic_retry_stopped')
                or gap.get('first_missing_stage') not in {'parsed_response', 'response_generation'}):
            continue
        target = list(gap['remaining_ranges'])
        for low, high in target:
            cursor = low
            while cursor < high:
                cancel()
                end = min(high, cursor + window_seconds)
                a, b = max(0, cursor-context_seconds), min(state['duration'], end+context_seconds)
                if requests >= max_requests or audio_used + b-a > max_audio_seconds or time.monotonic()-started >= max_elapsed_seconds:
                    state['budget_exhausted'] = True
                    break
                before = time.monotonic()
                error, candidates = '', []
                requests += 1
                audio_used += b-a
                try:
                    candidates = runner(a, b)
                    refused = next((row['cloud_gap'] for row in candidates if row.get('cloud_gap')), None)
                    if refused:
                        error = str(refused.get('detail') or refused.get('reason') or 'content_blocked')[:300]
                        gap['error_category'] = refused.get('reason', 'content_blocked')
                except Exception as exc:
                    if type(exc).__name__ == 'CancelledError':
                        raise
                    error = str(exc)[:300]
                    gap['error_category'] = getattr(exc, 'category', type(exc).__name__)
                result, accepted = merge_rows(result, candidates, [(cursor, end)])
                update_gap(gap, accepted, source=source, elapsed=time.monotonic()-before, error=error)
                if error or not accepted:
                    break
                cursor = end
            if state.get('budget_exhausted') or gap.get('error_category'):
                break
    state['recovery_cost'] = dict(request_count=requests, audio_seconds=round(audio_used, 3),
                                 elapsed_seconds=round(time.monotonic()-started, 3))
    return result


def audit_primary(payload, speech, context, *, duration, legacy, runner=None, source=''):
    """Shared local/cloud entry after raw responses and before admission/alignment."""
    execution = payload.get('execution') or {}
    refused = [(g['start'], g['end']) for g in payload.get('cloud_gaps', [])]
    state = make_state(speech, payload.get('segments', []), duration=duration, excluded=refused,
        windows=execution.get('windows', []), identity=context.media_identity.get('fingerprint', context.job_id), source=source)
    # Service refusals have already had their permitted local fallback. Keep
    # their category and outcome, never send them back through remote retries.
    state['gaps'].extend(copy.deepcopy(payload.get('speech_gap_results', [])))
    state['excluded_ranges'] = []
    worker_history = []
    for chunk in (payload.get('chunks', []) if source == 'moss' else []):
        recovery = chunk.get('recovery') or {}
        if not recovery:
            continue
        offset = float(chunk['offset'])
        attempts = []
        for index, original in enumerate(recovery.get('attempts', []), 1):
            attempt = {key: copy.deepcopy(original[key]) for key in ('complete', 'generation_attempts',
                'generated_tokens', 'end_reason', 'elapsed_seconds', 'accepted_segments', 'error', 'error_category')
                if key in original}
            attempt.update(source='moss_worker', request_id=f"W{chunk['chunk_id']}:R{index}",
                           start=offset+float(original['start']), end=offset+float(original['end']),
                           clock='task_pcm_zero', measurement_origin='retained_window_output')
            attempts.append(attempt)
        targets = [[offset+a, offset+b] for a,b in recovery.get('target_ranges', recovery.get('remaining_ranges', []))]
        remaining = [[offset+a, offset+b] for a,b in recovery.get('remaining_ranges', [])]
        history = dict(window_id=chunk['chunk_id'], targets=targets, remaining_ranges=remaining,
            reason=list(recovery.get('reason', [])), first_missing_stage='parsed_response',
            recovery_source='moss_worker', attempts=attempts,
            result='partial' if remaining else 'recovered', range_kind='audio_target_with_independent_speech_audit')
        worker_history.append(history)
        for gap in state['gaps']:
            related = [attempt for attempt in attempts
                       if _overlaps((gap['start'], gap['end']), (attempt['start'], attempt['end']))]
            if related:
                gap['attempts'].extend(copy.deepcopy(related))
                gap['recovery_source'] = 'moss_worker'
    state['worker_recovery'] = worker_history
    state['provider'] = source
    endpoint = getattr(context, 'asr_endpoint_snapshot', {}) or {}
    state['execution_identity'] = dict(backend=source, model=payload.get('model') or endpoint.get('model'),
                                     provider=endpoint.get('provider'), protocol=endpoint.get('protocol'))
    snapshot = getattr(context, 'recognition_snapshot', {}) or {}
    previous = ((snapshot.get('project') or {}).get('generation_metadata') or {}).get(KEY) or {}
    if previous.get('identity') == state.get('identity'):
        state['decisions'] = copy.deepcopy(previous.get('decisions') or {})
    state['input_sequence'] = copy.deepcopy(snapshot.get('sequence'))
    state['input_offset_ms'] = (snapshot.get('range_ms') or [0])[0]
    raw_rows = [dict(row, start=float(chunk['offset'])+float(row['start']),
                          end=float(chunk['offset'])+float(row['end']))
                for chunk in payload.get('chunks', []) for row in chunk.get('segments', [])]
    for gap in state['gaps']:
        if gap.get('service_gaps'):
            continue
        if any(_overlaps((gap['start'], gap['end']), span) for span in text_ranges(raw_rows)):
            gap.update(first_missing_stage='window_merge', reason='parsed_text_lost_in_merge',
                       recovery_source='retained_upstream', status='needs_confirmation')
        elif 'token_limit' in gap['reason'] or 'unexpected_stop' in gap['reason']:
            gap['first_missing_stage'] = 'response_generation'
        before = [row for row in payload.get('segments', []) if float(row['end']) <= gap['start']]
        after = [row for row in payload.get('segments', []) if float(row['start']) >= gap['end']]
        gap['previous_text'] = str(max(before, key=lambda r: float(r['end']))['text'])[:240] if before else ''
        gap['next_text'] = str(min(after, key=lambda r: float(r['start']))['text'])[:240] if after else ''
        gap['request_receipts'] = [copy.deepcopy(row['asr_language_receipt']) for row in payload.get('segments', [])
            if row.get('asr_language_receipt') and _overlaps((gap['start'], gap['end']),
                (float(row['asr_language_receipt']['start']), float(row['asr_language_receipt']['end'])))]
    checkpoint(state, 'parsed_response', payload.get('segments', []))
    if runner is not None:
        old = payload.get('segments', [])
        cancel = getattr(context.cancellation_token, 'raise_if_cancelled', lambda: None)
        spent = execution.get('recovery_cost') or {}
        payload['segments'] = recover(state, old, runner, source=source, cancel=cancel,
            max_requests=max(0, 24-int(spent.get('request_count') or 0)),
            max_audio_seconds=max(0, 1800-float(spent.get('audio_seconds') or 0)),
            max_elapsed_seconds=max(0, 900-float(spent.get('elapsed_seconds') or 0)))
        state['worker_recovery_cost'] = copy.deepcopy(spent)
        added = [row for row in payload['segments'] if row not in old]
        payload.setdefault('references', []).extend(copy.deepcopy(added))
    context.speech_coverage = state
    legacy.record_run_event('speech_coverage', **state, pending_gap_count=len(pending(state)))
    return state


def finalize(context, cues, legacy):
    state = getattr(context, KEY, {})
    if not state:
        return
    checkpoint(state, 'final_cues', cues, excluded=state.get('excluded_ranges', []))
    for gap in pending(classify_state(state)):
        label = ('语音处理失败' if gap['classification'] == 'processing_failure' else
                 '语音缺口待恢复' if gap['classification'] == 'supported_speech_gap' else '疑似语音待试听确认')
        legacy.add_review_item(gap['start'], label,
            f"{gap['start']:.3f}–{gap['end']:.3f}s · {gap['first_missing_stage']} · {gap['reason']}",
            priority=3, severity='warning')
    legacy.record_run_event('speech_coverage_final', **state, pending_gap_count=len(pending(state)))
