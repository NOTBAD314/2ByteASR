"""Task-PCM speech coverage, independent of transport and language admission.

This module is stdlib-only so the isolated MOSS worker can load it by file
path without importing the GUI's native libraries.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import time
import unicodedata
from bisect import bisect_left,bisect_right
from difflib import SequenceMatcher

KEY = 'speech_coverage'
POLICY = 'speech-coverage-v3-text-identity'
TOLERANCE = .25
MIN_GAP = 1.0
AUTO_CONFIDENCE = .85


def recovery_speaker(label):
    return str(label).startswith(('UNCONFIRMED_', 'RECOVERY_', 'LOCAL_'))


def fold_recovery_lanes(payload):
    """Speakers turned off: recovered rows join the primary's one lane.

    2026-11-22 (user): with Qwen Audio 3.1 speakers off, each recovered gap
    still opened its own ``RECOVERY_<sample>`` lane. The original label stays
    in ``recovered_speaker``; returns how many primary rows were moved.
    """
    rows = payload.get('segments') or []
    labels = {str(r.get('speaker') or 'S00') for r in rows if not recovery_speaker(r.get('speaker') or 'S00')}
    if len(labels) > 1:
        return 0
    lane = labels.pop() if labels else 'S00'
    moved = 0
    for field in ('segments', 'references'):
        for row in payload.get(field) or []:
            if isinstance(row, dict) and recovery_speaker(row.get('speaker') or ''):
                row['recovered_speaker'] = row['speaker']
                row['speaker'] = lane
                moved += field == 'segments'
    return moved


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


def _content(text):
    return ''.join(c.casefold() for c in unicodedata.normalize('NFC',str(text or ''))
                   if unicodedata.category(c)[0] in 'LN')


def _text_snapshot(rows):
    result=[]
    for row in rows:
        get=row.get if isinstance(row,dict) else lambda k,d=None:getattr(row,k,d)
        text=_content(get('text',''))
        if not text:continue
        start=get('start',None);end=get('end',None)
        start=float(start if start is not None else get('start_ms',0)/1000)
        end=float(end if end is not None else get('end_ms',0)/1000)
        namespace='segment' if get('segment_id',None) is not None else 'cue' if get('cue_id',get('id',None)) is not None else 'derived'
        identity=get('segment_id',get('cue_id',get('id','')))
        if identity in ('',None):
            identity='asr-'+hashlib.sha256(json.dumps([get('speaker','S00'),start,end,text],ensure_ascii=False).encode()).hexdigest()[:20]
        result.append(dict(id=identity,namespace=namespace,raw_text=str(get('text','')),
            start=start,end=end,text=text,
            speaker=str(get('speaker',get('speaker_id','S00')) or 'S00'),
            source_spans=copy.deepcopy(get('source_spans',[]))))
    return result


def _part_chars(part):
    start=part.get('char_start');raw=part.get('raw_text')
    if type(start) is not int or not isinstance(raw,str):return None
    return {start+i:(_content(c) or c) for i,c in enumerate(raw) if unicodedata.category(c)[0] in 'LNM'}


def _retention_index(current):
    speakers={};direct={};mapped={};characters={};has_parts=set();segment_speakers=set();trusted_speakers=set()
    for item in current:
        speaker=item['speaker'];speakers.setdefault(speaker,[]).append(item)
        direct.setdefault((speaker,item.get('namespace'),str(item['id'])),[]).append(item)
        if item.get('namespace')=='segment':segment_speakers.add(speaker)
        parts=item.get('source_spans') or []
        if not isinstance(parts,list):parts=[]
        if parts:has_parts.add(speaker)
        keys=set()
        for part in parts:
            if isinstance(part,dict):keys.add(str(part.get('source_id')))
        for key in keys:mapped.setdefault((speaker,key),[]).append(item)
        valid=bool(parts) and all(isinstance(p,dict) and _part_chars(p) is not None for p in parts)
        if valid and _content(''.join(p['raw_text'] for p in parts))==item['text']:
            trusted_speakers.add(speaker)
            for part in parts:characters.setdefault((speaker,str(part.get('source_id'))),{}).update(_part_chars(part))
    intervals={}
    for speaker,items in speakers.items():
        items.sort(key=lambda r:(r['start'],r['end'],str(r['id'])))
        maximum=float('-inf');prefix=[]
        for item in items:maximum=max(maximum,item['end']);prefix.append(maximum)
        intervals[speaker]=(items,[r['start'] for r in items],prefix)
    return dict(intervals=intervals,direct=direct,mapped=mapped,characters=characters,
                has_parts=has_parts,segment_speakers=segment_speakers,trusted_speakers=trusted_speakers)


def text_retained(row, current, *, index=None):
    """Prefer exact source characters, with one shared local interval index."""
    index=index or _retention_index(current);speaker=row['speaker']
    items,starts,prefix=index['intervals'].get(speaker,([],[],[]))
    low,high=row['start']-.5,row['end']+.5
    local=[r for r in items[bisect_right(prefix,low):bisect_left(starts,high)] if r['end']>low]
    unlinked=[r for r in local if not r.get('source_spans') and (r['text'] in row['text'] or row['text'] in r['text'])]
    if unlinked and ''.join(r['text'] for r in local).count(row['text'])==1:return True
    expected=row.get('source_spans') or ([dict(source_id=row['id'],char_start=0,raw_text=row.get('raw_text',''))]
                                       if row.get('namespace')=='segment' else [])
    complete=all(isinstance(p,dict) and isinstance(p.get('raw_text'),str) for p in expected) and _content(''.join(p['raw_text'] for p in expected))==row['text']
    if expected and complete and speaker in index['trusted_speakers'] and all(_part_chars(p) is not None for p in expected):
        for part in expected:
            wanted=_part_chars(part);offered=index['characters'].get((speaker,str(part.get('source_id'))),{})
            if any(offered.get(pos)!=char for pos,char in wanted.items()):return False
        return True
    if row.get('namespace')=='segment':
        mapped=index['mapped'].get((speaker,str(row['id'])),[])
        if not mapped and speaker in index['has_parts']:return False
        if not mapped and speaker in index['segment_speakers']:
            mapped=index['direct'].get((speaker,'segment',str(row['id'])),[])
            if not mapped:return False
        if mapped:
            return ''.join(r['text'] for r in sorted(mapped,key=lambda r:(r['start'],r['end'],str(r['id'])))).count(row['text'])==1
    return bool(row['text'] and ''.join(r['text'] for r in local).count(row['text'])==1)


def checkpoint(state, stage, rows, *, excluded=()):
    """Compare text identity separately from timing contraction at each boundary."""
    rows=list(rows)
    ranges = text_ranges(rows)
    current=_text_snapshot(rows)
    previous = state.get('stages', [])
    if previous:
        prior=previous[-1]
        index=_retention_index(current)
        decisions=[(r,text_retained(r,current,index=index)) for r in prior.get('text_rows',[])]
        retained=[r for r,kept in decisions if kept]
        missing=[r for r,kept in decisions if not kept]
        lost = subtract(prior['ranges'], ranges, tolerance=TOLERANCE, minimum=MIN_GAP)
        # Proven text retention resolves the loss claim, not the acoustic
        # accuracy of the newly tightened timing. Keep that distinction.
        contractions=subtract(lost,[(r['start'],r['end']) for r in missing]) if retained else []
        lost = subtract(lost,[(r['start'],r['end']) for r in retained])
        lost = [(max(a, c), min(b, d)) for a, b in lost
                for c, d in state.get('speech_ranges', []) if min(b, d)-max(a, c) >= MIN_GAP]
        lost = subtract(lost, excluded)
        # Losing characters with unchanged timestamps is still downstream
        # loss; an interval-only comparison previously missed it altogether.
        for row in missing if stage in {'segmentation','final_cues'} else []:
            if not any(_overlaps((row['start'],row['end']),v) for v in lost):
                lost.extend(subtract([(row['start'],row['end'])],excluded))
        for start, end in lost:
            if any(_overlaps((start, end), (g['start'], g['end'])) for g in state['gaps']):
                continue
            affected=[r for r in missing if _overlaps((start,end),(r['start'],r['end']))]
            gap_id = hashlib.sha256(f'{state.get("identity")}/{stage}/{start}/{end}'.encode()).hexdigest()[:24]
            state['gaps'].append(dict(id=gap_id, start=start, end=end, reason='downstream_text_loss',
                first_missing_stage=stage, status='needs_confirmation', attempts=[],
                text_evidence=affected, comparison='text_and_source_identity' if affected else 'legacy_interval_only',
                recovery_source='retained_upstream', recovered_ranges=[], remaining_ranges=[[start, end]]))
        if contractions:
            state.setdefault('timing_diagnostics',[]).append(dict(stage=stage,reason='text_retained_timing_contracted',
                ranges=contractions,source_ids=[r['id'] for r in retained]))
    changes=[];removed=[];added=[];owner_changes=[]
    if previous and stage=='prepared_source':
        prior_by_id={(r.get('namespace'),str(r['id'])):r for r in previous[-1].get('text_rows',[])}
        current_by_id={(r.get('namespace'),str(r['id'])):r for r in current}
        removed=[r['id'] for key,r in prior_by_id.items() if key not in current_by_id]
        added=[r['id'] for key,r in current_by_id.items() if key not in prior_by_id]
        for item in current:
            old=prior_by_id.get((item.get('namespace'),str(item['id'])))
            if old and old['speaker']!=item['speaker']:owner_changes.append(dict(source_id=item['id'],before=old['speaker'],after=item['speaker'],acoustic_identity='not_confirmed_by_this_trace'))
            if old and old.get('raw_text',old['text'])!=item['raw_text']:
                changes.append(dict(source_id=item['id'],before=old.get('raw_text',old['text']),after=item['raw_text'],
                    effect='formatting_only' if old['text']==item['text'] else 'upstream_source_text_change',
                    meaning='upstream source processing; not a segmentation deletion verdict'))
    state.setdefault('stages', []).append(dict(stage=stage, ranges=[list(r) for r in ranges],text_rows=current,source_changes=changes,removed_source_ids=removed,added_source_ids=added,source_owner_changes=owner_changes))
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


class RecoveryWindowRows(list):
    cache_hit = False


def transcribe_recovery_window(backend, media_path, pcm, start, end, cache_context, owner, legacy):
    """Recognize local-clock PCM. Translate validated rows back exactly once."""
    import hashlib
    import json
    import time
    from pathlib import Path
    from .alignment_audio import pcm_digest
    from .cache import atomic_write_json

    left = max(0, round(start * 16000))
    right = min(len(pcm), round(end * 16000))
    if right <= left:
        return []
    audio = pcm[left:right]
    duration = len(audio) / 16000
    digest = pcm_digest(audio)
    identity = dict(version=1, backend=backend, pcm_sha256=digest, samples=len(audio),
                    start_sample=left, end_sample=right, language=owner.requested_language,
                    media=owner.media_identity.get('fingerprint'))
    settings = owner.asr_settings_snapshot or getattr(legacy, 'RUNTIME_SETTINGS', {})
    context = legacy.build_qwen_asr_context(media_path) if backend == 'api' else ''
    key = hashlib.sha256(json.dumps([identity, settings, owner.asr_endpoint_snapshot, context],
        ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    path = Path(cache_context['cache_dir'])/'speech-recovery'/f'{key}.json'
    rows = None
    try:
        saved = json.loads(path.read_bytes())
        if (saved['key'] == key and isinstance(saved['rows'], list)
                and (saved['rows'] or saved.get('outcome') == 'empty_success')):
            rows = saved['rows']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    reused = rows is not None
    started = time.monotonic()
    work_id = f'speech-recovery:{left}-{right}'
    if not reused:
        legacy.record_run_event('pipeline_work_progress', work_id=work_id, label='补识别：局部音频',
            phase='speech_recovery', state='running', done=0, total=1)
        try:
            rows = legacy.transcribe_primary_reference(backend, media_path,
                [dict(start=0., end=duration)], audio, duration)
        except Exception as exc:
            from .service import CancelledError
            from ..providers.provider_diagnostics import redact_diagnostics
            problem = getattr(exc, 'problem', None)
            problem = problem if isinstance(problem, dict) else {}
            cancelled = isinstance(exc, CancelledError)
            empty_failure = 'ASR_RESPONSE_HAVE_NO_WORDS' in str(exc)
            category = problem.get('category') or getattr(exc, 'category', None) or (
                'provider_empty_response_failure' if empty_failure else type(exc).__name__)
            error = problem.get('message') or str(exc).partition('\n')[0] or category
            legacy.record_run_event('speech_recovery_window', **identity, cache_key=key,
                exact_window_cache_hit=False, outcome='cancelled' if cancelled else 'failed',
                error_category=category, provider_code=problem.get('code'),
                provider_request_id=problem.get('request_id'),
                error=redact_diagnostics(error)[:300], elapsed_seconds=round(time.monotonic()-started, 3))
            legacy.record_run_event('pipeline_work_progress', work_id=work_id, label='补识别：局部音频',
                phase='speech_recovery', state='cancelled' if cancelled else 'failed', done=1, total=1)
            if empty_failure and not cancelled:
                # Preserve the failure with this window so the other gaps and
                # the independent-recognizer pass can still run.
                result = RecoveryWindowRows()
                result.failure = dict(category=category, error=redact_diagnostics(error)[:300])
                return result
            raise
    if any(not 0 <= float(r['start']) < float(r['end']) <= duration + .002 for r in rows):
        raise ValueError('缺口识别返回时间超出实际音频窗口')
    if not reused and not any(r.get('cloud_gap') for r in rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, dict(key=key, rows=rows, outcome='transcribed' if rows else 'empty_success'))
    if not reused:
        legacy.record_run_event('pipeline_work_progress', work_id=work_id, label='补识别：局部音频',
            phase='speech_recovery', state='completed', done=1, total=1)
    legacy.record_run_event('speech_recovery_window', **identity, cache_key=key,
        exact_window_cache_hit=reused, source_offset=left/16000, elapsed_seconds=round(time.monotonic()-started, 3),
        outcome='blocked' if any(row.get('cloud_gap') for row in rows) else 'transcribed' if rows else 'empty_success',
        returned_rows=[dict(start=r['start'], end=r['end'], text=r.get('text','')) for r in rows])
    result = RecoveryWindowRows()
    result.cache_hit = reused
    for r in rows:
        offset = left / 16000
        shifted = dict(r, start=offset+float(r['start']), end=offset+float(r['end']),
                       speaker=f"RECOVERY_{left}_{r.get('speaker') or 'UNKNOWN'}")
        def global_words(words):
            return [dict(w, start=float(w['start'])+offset, end=float(w['end'])+offset)
                    for w in words]
        for field in ('words', 'tokens'):
            if r.get(field):
                shifted[field] = global_words(r[field])
        if r.get('provider_source'):
            evidence = shifted['provider_source'] = dict(r['provider_source'])
            for field in ('source_start', 'source_end', 'request_offset'):
                if field in evidence:
                    evidence[field] += offset
            if evidence.get('valid_word_times'):
                evidence['valid_word_times'] = global_words(evidence['valid_word_times'])
        result.append(shifted)
    return result


def recover(state, rows, runner, *, source, cancel=lambda: None, max_requests=24, max_audio_seconds=1800,
            max_elapsed_seconds=900, window_seconds=90, context_seconds=2):
    """A callback receives absolute task-PCM bounds and returns global rows.

    Only independently supported gaps auto-run. Refusal exceptions stop this
    gap and retain their category. Confirmed UI range retries use the normal
    recognition transaction instead of editing a project here.
    """
    started, requests, audio_used = time.monotonic(), 0, 0.0
    cache_hits = 0
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
                    failure = getattr(candidates, 'failure', None)
                    if failure:
                        error = failure['error']
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
                reused = bool(getattr(candidates, 'cache_hit', False))
                if reused:
                    requests -= 1
                    audio_used -= b-a
                    cache_hits += 1
                update_gap(gap, accepted, source=source, elapsed=time.monotonic()-before,
                           error=error, request_count=int(not reused))
                gap['attempts'][-1].update(window=[a, b], exact_window_cache_hit=reused)
                if getattr(candidates, 'failure', None):
                    gap['attempts'][-1]['error_category'] = candidates.failure['category']
                if error or not accepted:
                    break
                cursor = end
            if state.get('budget_exhausted') or gap.get('error_category'):
                break
    state['recovery_cost'] = dict(request_count=requests, cached_windows=cache_hits, audio_seconds=round(audio_used, 3),
                                 elapsed_seconds=round(time.monotonic()-started, 3))
    return result


# 2026-11-19: an independent recognizer (FireRedASR2-AED, run alongside an
# online primary) that wrote real words inside a VAD-only gap is the second,
# independent source the VAD posterior lacks. In the reported job MOSS Pro's
# one response stopped at 642.65 s of 667.44 s while FireRed heard 88
# characters there; the four tail gaps had 3–66 FireRed characters, every
# other gap 0–1 (an edge character of the neighbouring line).
MIN_INDEPENDENT_CHARS = 3
FILL_SOURCE = 'firered_evidence'
FILL_ROW_SOURCE = 'firered-gap-fill'
TAIL_SECONDS = 2.0


def _token_mid(token):
    return (float(token['start'])+float(token['end']))/2


def _usable_tokens(tokens):
    from .asr_schema import firered_text
    result = []
    for token in tokens or ():
        try:
            start, end = float(token['start']), float(token['end'])
        except (KeyError, TypeError, ValueError):
            continue
        text = firered_text(token.get('text'))
        if len(text) > 64 or end-start > max(4., len(text)*1.5):
            continue  # A window or oversized token cannot anchor new speech.
        if math.isfinite(start) and math.isfinite(end) and end > start and _content(text):
            result.append(dict(text=text, start=start, end=end,
                               confidence=token.get('confidence')))
    kept = []
    for token in sorted(result, key=lambda t: (t['start'], t['end'])):
        # Overlapping recognition windows hear the seam twice (五五十十六六).
        if kept and _content(kept[-1]['text']) == _content(token['text']):
            previous = kept[-1]
            overlap = min(previous['end'], token['end'])-max(previous['start'], token['start'])
            if overlap > .5*max(.01, min(token['end']-token['start'], previous['end']-previous['start'])):
                continue
        kept.append(token)
    return kept


def corroborate(state, tokens, *, source='firered'):
    """Promote VAD-only gaps an independent recognizer actually transcribed."""
    tokens = _usable_tokens(tokens)
    promoted = []
    for gap in pending(state):
        if gap.get('classification') != 'uncertain_speech' or gap.get('first_missing_stage') != 'parsed_response':
            continue
        inside = [t for t in tokens if gap['start'] <= _token_mid(t) <= gap['end']]
        text = ''.join(t['text'] for t in inside)
        if len(_content(text)) < MIN_INDEPENDENT_CHARS:
            continue
        evidence = gap.setdefault('evidence', {})
        evidence['speech_corroborated'] = True
        evidence['independent_text'] = dict(source=source, characters=len(_content(text)), text=text[:120],
                                            basis='independent_asr_words_inside_gap')
        gap.update(classification='supported_speech_gap', status='pending')
        promoted.append(gap['id'])
    return promoted


def _fill_rows(tokens, low, high, label):
    rows, current = [], []
    for token in tokens:
        if not low <= _token_mid(token) <= high:
            continue
        # A short pause, a long line or a long stretch starts a new row; the
        # grouping stage re-segments these like any primary sentence.
        if current and (token['start']-current[-1]['end'] >= .35 or len(current) >= 16
                        or token['end']-current[0]['start'] > 6.):
            rows.append(current)
            current = []
        current.append(token)
    if current:
        rows.append(current)
    result = []
    for part in rows:
        start, end = part[0]['start'], max(t['end'] for t in part)
        if end <= start:
            end = start+.01
        scores = [float(t['confidence']) for t in part if isinstance(t.get('confidence'), (int, float))]
        result.append(dict(text=''.join(t['text'] for t in part), start=round(start, 3), end=round(end, 3),
                           speaker=label, confidence=round(sum(scores)/len(scores), 3) if scores else .6,
                           source=FILL_ROW_SOURCE, timestamp_source='firered_aed_characters'))
    return result


def fill_from_independent(state, rows, tokens, *, duration):
    """Fill corroborated gaps the primary could not recover with the independent words.

    The words of the whole hole between the neighbouring primary lines are
    used, so short speech between two gap pieces is not dropped. Each filled
    gap keeps a review item: the text came from the evidence model.
    """
    tokens = _usable_tokens(tokens)
    result = list(rows)
    filled = []
    for gap in pending(state):
        independent = (gap.get('evidence') or {}).get('independent_text')
        if not independent or not gap.get('remaining_ranges'):
            continue
        target = [list(r) for r in gap['remaining_ranges']]
        # Rows an earlier gap's hole already filled (a tail hole reaches the end).
        used = [r for r in filled if any(_overlaps((float(r['start']), float(r['end'])), tuple(t)) for t in target)]
        covered = text_ranges(result)
        candidates, holes = [], []
        for low, high in subtract(target, text_ranges(used), tolerance=TOLERANCE, minimum=MIN_GAP):
            before = max((b for a, b in covered if b <= low+TOLERANCE), default=0.0)
            after = min((a for a, b in covered if a >= high-TOLERANCE), default=duration)
            hole = (before+TOLERANCE if before else 0.0, after-TOLERANCE if after < duration else duration)
            if hole[1] <= hole[0]:
                continue
            holes.append(hole)
            label = f'RECOVERY_{round(low*16000)}_FIRERED'
            candidates.extend(_fill_rows(tokens, hole[0], hole[1], label))
        accepted = []
        if candidates:
            result, accepted = merge_rows(result, candidates, holes)
            filled.extend(accepted)
        if not used and not accepted:
            continue
        update_gap(gap, [*used, *accepted], source=FILL_SOURCE, request_count=0)
        gap['independent_fill'] = dict(source=independent.get('source'), target_ranges=target,
                                       holes=[list(h) for h in holes], rows=len(accepted),
                                       shared_rows=len(used),
                                       characters=sum(len(_content(r['text'])) for r in accepted),
                                       review='listen_and_confirm')
        # VAD edges outside the words (breath, trailing room tone): the model
        # that heard this hole wrote nothing there. The fill's own review
        # item covers the hole; do not report the same stretch twice.
        rest = gap.get('remaining_ranges') or []
        if rest and not any(a <= _token_mid(t) <= b for a, b in rest for t in tokens):
            gap['independent_fill']['unworded_ranges'] = [list(r) for r in rest]
            gap.update(remaining_ranges=[], status='recovered')
    return result


def discard_independent_fill(state, payload):
    """Undo the fill when the task language rules out the evidence model."""
    def keep(row):
        return row.get('source') != FILL_ROW_SOURCE
    for key in ('segments', 'references'):
        if isinstance(payload.get(key), list):
            payload[key] = [row for row in payload[key] if keep(row)]
    if (state or {}).get('overlap_fill'):
        state['overlap_fill'] = dict(state['overlap_fill'], rows=[], discarded='task_language')
    for gap in (state or {}).get('gaps', []):
        fill = gap.pop('independent_fill', None)
        if (gap.get('evidence') or {}).pop('independent_text', None):
            gap['evidence']['speech_corroborated'] = False
            if gap.get('status') == 'pending':
                gap.update(status='needs_confirmation', classification='uncertain_speech')
        if fill:
            gap['remaining_ranges'] = fill['target_ranges']
            gap['recovered_ranges'] = [list(r) for r in subtract(gap.get('recovered_ranges', []), fill['target_ranges'])]
            gap['recovery_source'] = None
            gap.update(status='needs_confirmation', classification='uncertain_speech',
                       independent_fill_discarded='task_language')


def tail_gaps(gaps, duration):
    """Primary-response gaps after the last primary line, when speech reaches the end."""
    tail = [g for g in gaps if g.get('first_missing_stage') == 'parsed_response'
            and 'next_text' in g and not g.get('next_text')]
    if not tail or float(duration or 0)-max(g['end'] for g in tail) > TAIL_SECONDS:
        return []
    return tail


FOREIGN_RUN_LETTERS = 8
_CJK = re.compile(r'[㐀-鿿]')
_LATIN = re.compile(r'[A-Za-z]')


def without_foreign_runs(tokens):
    """Drop runs of 8+ Latin letters with no Chinese character among them.

    2026-11-22 (user, 1 h Chinese stream): FireRed heard background English
    lyrics (feel it in my body feel it in my feet) where the primary wrote
    nothing; they corroborated a speech gap and were filled into the
    subtitles for the user to delete. Short English (OK, try again) stays.
    Only called for a Chinese task.
    """
    tokens = list(tokens or ())
    keep = [True]*len(tokens)
    run = []

    def close():
        if sum(len(_LATIN.findall(str(tokens[i].get('text') or ''))) for i in run) >= FOREIGN_RUN_LETTERS:
            for i in run:
                keep[i] = False
        run.clear()

    for index, token in enumerate(tokens):
        text = str(token.get('text') or '')
        if _LATIN.search(text) and not _CJK.search(text):
            if run and float(token.get('start', 0)) - float(tokens[run[-1]].get('end', 0)) > 1.:
                close()
            run.append(index)
        elif _CJK.search(text):
            close()
    close()
    return [token for token, kept in zip(tokens, keep) if kept]


def audit_primary(payload, speech, context, *, duration, legacy, runner=None, source='',
                  independent=(), fill_independent=False):
    """Shared local/cloud entry after raw responses and before admission/alignment.

    ``independent``: global word rows of an evidence recognizer that already
    finished (FireRed beside an online primary). Their words corroborate VAD
    gaps (which then get the normal primary retry) and, with
    ``fill_independent``, fill what the retry did not recover.
    """
    language = str(getattr(context, 'task_language', '') or getattr(context, 'requested_language', '') or '')
    if independent and language.split('-')[0] == 'zh':
        independent = without_foreign_runs(independent)
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
    if independent:
        promoted = corroborate(state, independent)
        if promoted:
            state['independent_evidence'] = dict(source='firered', corroborated_gap_ids=promoted)
    if runner is not None:
        old = payload.get('segments', [])
        cancel = getattr(context.cancellation_token, 'raise_if_cancelled', lambda: None)
        spent = execution.get('recovery_cost') or {}
        payload['segments'] = recover(state, old, runner, source=source, cancel=cancel,
            context_seconds=0 if source == 'api' else 2,
            max_requests=max(0, 24-int(spent.get('request_count') or 0)),
            max_audio_seconds=max(0, 1800-float(spent.get('audio_seconds') or 0)),
            max_elapsed_seconds=max(0, 900-float(spent.get('elapsed_seconds') or 0)))
        state['worker_recovery_cost'] = copy.deepcopy(spent)
        added = [row for row in payload['segments'] if row not in old]
        payload.setdefault('references', []).extend(copy.deepcopy(added))
    if independent and fill_independent:
        old = payload.get('segments', [])
        payload['segments'] = fill_from_independent(state, old, independent, duration=duration)
        added = [row for row in payload['segments'] if row not in old]
        if added:
            payload.setdefault('references', []).extend(copy.deepcopy(added))
            state.setdefault('independent_evidence', dict(source='firered'))['filled_rows'] = len(added)
    context.speech_coverage = state
    legacy.record_run_event('speech_coverage', **state, pending_gap_count=len(pending(state)))
    return state


def finalize(context, cues, legacy):
    state = getattr(context, KEY, {})
    if not state:
        return
    checkpoint(state, 'final_cues', cues, excluded=state.get('excluded_ranges', []))
    rows = pending(classify_state(state))
    tail = tail_gaps(rows, state.get('duration'))
    if tail:
        # 2026-11-19: speech running to the end of the media with no line
        # after it is one obvious problem, not one more warning among dozens
        # of short VAD blips (39 in the reported job). One item names it.
        start, end = min(g['start'] for g in tail), max(g['end'] for g in tail)
        legacy.add_review_item(start, '片尾语音没有字幕',
            f"{start:.3f}–{end:.3f}s · 主力转写在 {start:.1f}s 后没有文字，结尾还有人声；请试听，或框选这段重新识别",
            priority=1, severity='warning')
    tail_ids = {g['id'] for g in tail}
    for gap in rows:
        if gap['id'] in tail_ids:
            continue
        detail = f"{gap['start']:.3f}–{gap['end']:.3f}s · {gap['first_missing_stage']} · {gap['reason']}"
        label = ('语音处理失败' if gap['classification'] == 'processing_failure' else
                 '语音缺口待恢复' if gap['classification'] == 'supported_speech_gap' else '疑似语音待试听确认')
        # 2026-11-22: voice activity alone, with no words from either
        # recognizer, is a note (180 of 303 "problems" in a 1 h stream).
        legacy.add_review_item(gap['start'], label, detail, priority=3,
                               severity='info' if gap['classification'] == 'uncertain_speech' else 'warning')
    for gap in state.get('gaps', []):
        fill = gap.get('independent_fill')
        if fill and fill.get('rows'):
            low = min(h[0] for h in fill['holes']) if fill.get('holes') else gap['start']
            high = max(h[1] for h in fill['holes']) if fill.get('holes') else gap['end']
            legacy.add_review_item(low, 'FireRed 补字待试听',
                f"{low:.3f}–{high:.3f}s · 主力转写没有这段文字，已用 FireRedASR2 识别结果补上 {fill.get('characters', 0)} 字；请试听确认",
                priority=2, severity='warning')
    # 2026-11-20: a second voice under one primary speaker's line.
    for row in (state.get('overlap_fill') or {}).get('rows', []):
        if row.get('inserted') is False:
            # Speakers turned off: one lane, so the second voice stays out.
            legacy.add_review_item(row['start'], '叠话待试听',
                f"{row['start']:.3f}–{row['end']:.3f}s · 说话人区分已关闭，未另开轨道；"
                f"FireRedASR2 在这段还听到：{row.get('text', '')}。需要时请试听后手动加入",
                row.get('text', ''), priority=2, severity='info')
            continue
        legacy.add_review_item(row['start'], '叠话补字待试听',
            f"{row['start']:.3f}–{row['end']:.3f}s · 主力转写这段只有 {row.get('primary_speaker') or '一位说话人'}，"
            f"FireRedASR2 还听到另一段话，已补上 {row.get('characters', 0)} 字；请试听确认说话人和文字",
            priority=2, severity='warning')
    legacy.record_run_event('speech_coverage_final', **state, pending_gap_count=len(pending(state)))


def reconcile_legacy_text_loss(project):
    """Recheck derived interval-only claims; retain receipts, never label silence."""
    state=project.generation_metadata.get(KEY)
    raw=(project.generation_metadata.get('speaker_recovery') or {}).get('raw_segments',[])
    if not isinstance(state,dict) or not raw:
        return []
    before=_text_snapshot(raw)
    after=_text_snapshot(project.cues)
    index=_retention_index(after)
    resolved=[]
    for gap in pending(state):
        if gap.get('reason')!='downstream_text_loss' or gap.get('comparison')=='text_and_source_identity':
            continue
        parents=[r for r in before if _overlaps((r['start'],r['end']),(gap['start'],gap['end']))]
        if parents and all(text_retained(row,after,index=index) for row in parents):
            gap['text_reconciliation']=dict(rule=POLICY,previous_status=gap.get('status'),
                reason='text_retained_timing_contracted',source_ids=[r['id'] for r in parents],
                acoustic_verification='not_performed',request_count=0)
            gap['status']='excluded'
            resolved.append(gap['id'])
    return resolved
