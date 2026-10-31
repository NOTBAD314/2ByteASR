"""Select usable ASR rows separately from a provider's remote SUCCESS state.

Selections are sample-clock artifacts of one audio/language identity. They
never overwrite raw provider responses or settings, and never call a cloud API.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

KEY = 'transcript_acceptance'
VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf8')).hexdigest()


def _save(path, value):
    from ..storage.atomic_files import write_text_atomic
    write_text_atomic(Path(path), json.dumps(value, ensure_ascii=False, indent=2))


def identity_for(audio, language, media_identity=None):
    import numpy as np
    return dict(version=VERSION, requested_language=language, sample_rate=16000, samples=len(audio),
                pcm_sha256=hashlib.sha256(np.asarray(audio, dtype='<f4').tobytes()).hexdigest(),
                media_fingerprint=(media_identity or {}).get('fingerprint', ''))


def pending_ranges(state):
    return [r for r in (state or {}).get('ranges', []) if r.get('status') != 'accepted']


def _inside(row, start, end):
    return float(row['end'])*16000 > start and float(row['start'])*16000 < end


def _raw_conflicts(audit, identity, rows):
    selected = []
    for region in audit.get('regions', []):
        code = (region.get('transcript') or {}).get('language')
        if not code or code == identity['requested_language']:
            continue
        start = max(0, round(float(region['start'])*16000))
        end = min(identity['samples'], round(float(region['end'])*16000))
        if end <= start:
            continue
        selected.append(dict(id=digest([identity, start, end])[:24], start_sample=start, end_sample=end,
            start=start/16000, end=end/16000, status='pending', reason='text_language_conflict',
            requested_language=identity['requested_language'],
            transcript_language=code, acoustic_language=None,
            remote_task_id=region.get('remote_task_id'), remote_status='SUCCESS' if region.get('remote_task_id') else None,
            raw_result_path=region.get('raw_result_path'),
            raw_rows=[copy.deepcopy(r) for r in rows if _inside(r, start, end)],
            attempts=[], selected_attempt=None))
    return selected


def _selection_language(region,state,metadata=None):
    attempt=region.get('selected_attempt') or {}
    return (region.get('requested_language') or (attempt.get('policy') or {}).get('language')
        or attempt.get('request_language') or (state.get('identity') or {}).get('requested_language')
        or ((metadata or {}).get('language') or {}).get('requested'))


def _include_uncovered_conflicts(state,audit,raw):
    identity=state['identity']
    for region in _raw_conflicts(audit,identity,raw):
        uncovered=[(region['start_sample'],region['end_sample'])]
        for selected in state['ranges']:
            pieces=[]
            for lo,hi in uncovered:
                a,b=selected['start_sample'],selected['end_sample']
                if a<=lo+16 and b>=hi-16:continue
                if b<=lo or a>=hi:pieces.append((lo,hi));continue
                if lo<a:pieces.append((lo,a))
                if b<hi:pieces.append((b,hi))
            uncovered=pieces
        for lo,hi in uncovered:
            piece=copy.deepcopy(region)
            piece.update(id=digest([identity,lo,hi])[:24],start_sample=lo,end_sample=hi,start=lo/16000,end=hi/16000)
            state['ranges'].append(piece)


def recovered_rows(candidate, *, speaker_intervals=()):
    """Coarse ASR windows; speaker support comes only from audio-time overlap.

    Uncertain labels stay explicit. There is no list-position, transcript-
    similarity or tutorial/single-speaker assumption.
    """
    rows = []
    for value in candidate['rows']:
        row = {k: copy.deepcopy(value[k]) for k in ('start', 'end', 'text', 'language') if k in value}
        support = {}
        for old in speaker_intervals:
            overlap = min(row['end'], float(old['end']))-max(row['start'], float(old['start']))
            if overlap > 0 and old.get('speaker'):
                support[old['speaker']] = support.get(old['speaker'], 0)+overlap
        total = sum(support.values())
        best = max(support, key=support.get) if support else None
        certain = bool(best and support[best]/max(total, .001) >= .85
                       and support[best] >= (row['end']-row['start'])*.45)
        row.update(source='qwen_local_language_recovery', timestamp_source='vad_window',
            timing_precision='window', speaker=best if certain else 'RECOVERY_UNCONFIRMED',
            speaker_assignment=dict(basis='audio_interval_overlap', support=support, confirmed=certain),
            recognition_attempt_id=candidate['attempt_id'], request_language=candidate['policy']['language'])
        rows.append(row)
    if rows:
        rows[0]['asr_language_receipt'] = dict(source='selected_local_attempt', start=rows[0]['start'],
            end=rows[-1]['end'], request_language=candidate['policy']['language'],
            provider_detected_language=None, language_control='forced',
            transcript=candidate.get('language_evidence') or {})
    return rows


def register_candidate(state, conflict_id, candidate, *, speaker_intervals=(), require_acoustic=True):
    """Return a new selection. Forced output language is not acoustic evidence."""
    result = copy.deepcopy(state)
    row = next(r for r in result['ranges'] if r['id'] == conflict_id)
    if row.get('status') == 'accepted':
        return result
    probes = candidate.get('acoustic_samples') or []
    requested = result['identity']['requested_language']
    from ..subtitle_rules.language_rules import normalize_language
    detected = [normalize_language(p.get('language')) for p in probes if p.get('request_language') is None and p.get('text')]
    sound_agrees = len(detected) >= 2 and all(code == requested for code in detected)
    attempt = dict(id=candidate['attempt_id'], backend='qwen_local', model=candidate['model'],
        raw_payload=candidate.get('raw_payload'), policy=candidate['policy'],
        identity=candidate['identity'], acoustic_languages=detected,
        status='accepted' if sound_agrees or not require_acoustic else 'acoustic_unconfirmed')
    row['attempts'].append(attempt)
    if require_acoustic and not sound_agrees:
        row.update(status='pending', reason='acoustic_language_unconfirmed')
        return result
    converted = recovered_rows(candidate, speaker_intervals=speaker_intervals or row.get('raw_rows', []))
    if not converted:
        raise ValueError('替代结果为空，不能清除待恢复范围')
    if (round(converted[0]['start']*16000) != row['start_sample']
            or round(converted[-1]['end']*16000) != row['end_sample']):
        raise ValueError('替代结果范围与冲突范围不一致')
    row.update(status='accepted', reason='local_asr_acoustically_checked', acoustic_language=requested,
               selected_attempt=attempt, accepted_rows=converted, accepted_rows_sha256=digest(converted))
    return result


def apply_selection(raw_rows, state):
    """Old raw/cache rows never outrank a validated accepted selection."""
    rows = copy.deepcopy(raw_rows)
    for region in (state or {}).get('ranges', []):
        rows = [r for r in rows if not _inside(r, region['start_sample'], region['end_sample'])]
        if region.get('status') == 'accepted':
            accepted = region.get('accepted_rows') or []
            if digest(accepted) != region.get('accepted_rows_sha256'):
                raise ValueError('已选转写结果身份损坏，不能回退为旧错误原文')
            rows.extend(copy.deepcopy(accepted))
    return sorted(rows, key=lambda r: (float(r['start']), float(r['end'])))


def project_selection(context,audio):
    """Replay a project's accepted range only with the same graph and sources."""
    snapshot=context.recognition_snapshot or {}
    project=snapshot.get('project') or {}
    state=(project.get('generation_metadata') or {}).get(KEY) or {}
    if not state.get('audio_graph_digest') or not state.get('source_identities'):
        return None
    if digest(snapshot.get('audio_graph') or {}) != state['audio_graph_digest']:
        return None
    from .recognition_result import media_identity_for_task
    for path,expected in state['source_identities'].items():
        if not expected.get('sha256') or media_identity_for_task(path,context).get('sha256')!=expected['sha256']:
            return None
    offset=(snapshot.get('range_ms') or [0])[0]/1000
    limit=offset+len(audio)/16000
    cues={str(c['id']):c for c in project.get('cues',[])}
    accepted=[]
    from ..subtitle_rules.language_rules import normalize_language
    requested=normalize_language(context.requested_language)
    for region in state.get('ranges',[]):
        if region.get('status')!='accepted' or region['start']<offset or region['end']>limit+.001:
            continue
        saved_language=_selection_language(region,state,project.get('generation_metadata'))
        # Reusing the same audio does not authorize relabelling a previous
        # task's accepted text with a new explicit (or automatic) language.
        if not saved_language or normalize_language(saved_language)!=requested:
            continue
        selected=[cues[cid] for cid in region.get('accepted_cue_ids',[]) if cid in cues]
        if not selected:continue
        rows=[dict(start=c['start_ms']/1000-offset,end=c['end_ms']/1000-offset,text=c['text'],
                   speaker=c['speaker_id'],source='accepted_project_range',timestamp_source='recovered_aligned_cue') for c in selected]
        item=copy.deepcopy(region)
        item.update(start=region['start']-offset,end=region['end']-offset,
                    start_sample=round((region['start']-offset)*16000),
                    end_sample=min(len(audio),round((region['end']-offset)*16000)),
                    accepted_rows=rows,accepted_rows_sha256=digest(rows))
        accepted.append(item)
    if not accepted:return None
    return dict(version=VERSION,identity=identity_for(audio,context.requested_language,context.media_identity),ranges=accepted)


def gate_primary(payload, audio, context, legacy, cache_context, audit):
    """Quarantine conflicts before alignment; local recovery requires task opt-in."""
    raw = copy.deepcopy(payload.get('segments', []))
    policy = (context.recognition_snapshot or {}).get('language_recovery_policy') or {}
    if (context.recognition_snapshot.get('language_recovery_policy') or {}).get('explicit_local_range'):
        # This explicit range task has already selected and acoustically checked
        # its local attempt in the primary adapter; do not reset that receipt.
        if not context.transcript_acceptance.get('ranges'):
            saved = next((r.get('transcript_acceptance_receipt') for r in raw if r.get('transcript_acceptance_receipt')), None)
            if not saved:
                raise ValueError('本地范围缓存缺少接受回执，请明确重试该范围；未回用旧MOSS原文')
            import numpy as np
            checksum = hashlib.sha256(np.asarray(audio,dtype='<f4').tobytes()).hexdigest()
            if any((r.get('selected_attempt') or {}).get('identity',{}).get('pcm_sha256') != checksum
                   for r in saved.get('ranges',[]) if r.get('status')=='accepted'):
                raise ValueError('本地接受回执与当前音频不匹配')
            context.transcript_acceptance = copy.deepcopy(saved)
        return payload
    if policy.get('explicit_range') and not audit.get('conflicts') and raw:
        # An explicitly chosen existing alternative is allowed; it is never
        # selected or uploaded automatically by this recovery mechanism.
        selected = copy.deepcopy(raw)
        identity = identity_for(audio, context.requested_language, context.media_identity)
        endpoint = context.asr_endpoint_snapshot or {}
        attempt = dict(backend=getattr(legacy,'PRIMARY_ASR_BACKEND','unknown'),model=endpoint.get('model'),
                       request_language=endpoint.get('filetrans_language'),status='accepted',
                       basis='explicit_user_alternative_and_matching_transcript')
        context.transcript_acceptance = dict(version=VERSION,identity=identity,ranges=[dict(
            id=policy.get('conflict_id') or digest(identity)[:24],start_sample=0,end_sample=len(audio),
            start=0.,end=len(audio)/16000,status='accepted',acoustic_language=None,
            selected_attempt=attempt,accepted_rows=selected,accepted_rows_sha256=digest(selected),attempts=[attempt])])
        return payload
    path = Path(cache_context['cache_dir'])/f'primary-selection-{context.requested_language}.json'
    carried=project_selection(context,audio)
    if carried:
        # Still quarantine any newly conflicting scope not covered by a prior
        # accepted choice, rather than treating one recovery as a blanket pass.
        _include_uncovered_conflicts(carried,audit,raw)
        _save(path,carried)
        context.transcript_acceptance=carried
        if not pending_ranges(carried):
            context.review_items[:]=[r for r in context.review_items if r.get('category')!='转写语言需要核对']
        selected=apply_selection(raw,carried)
        return dict(payload,segments=selected,references=selected)
    if not audit.get('conflicts') and not path.is_file():
        context.transcript_acceptance = dict(version=VERSION, ranges=[])
        return payload
    identity = identity_for(audio, context.requested_language, context.media_identity)
    saved = json.loads(path.read_text('utf8')) if path.is_file() else {}
    state = saved if saved.get('identity') == identity else dict(version=VERSION, identity=identity, ranges=[])
    from ..subtitle_rules.language_rules import normalize_language
    invalid=[r for r in state['ranges'] if r.get('status')=='accepted'
        and normalize_language(_selection_language(r,state))!=normalize_language(context.requested_language)]
    if invalid:
        state.setdefault('invalidated_selections',[]).extend(copy.deepcopy(invalid))
        state['ranges']=[r for r in state['ranges'] if r not in invalid]
    _include_uncovered_conflicts(state,audit,raw)
    if not state['ranges']:
        if invalid:_save(path,state)
        context.transcript_acceptance = state
        return payload
    state['selection_store'] = str(path)
    # The raw cache remains evidence. Persist the pending scope before any
    # optional local attempt, so cancellation/restart cannot hide it.
    _save(path, state)
    if policy.get('allow_local_once'):
        from .local_language_recovery import recognize_range
        from .service import CancelledError
        for region in pending_ranges(state):
            if region.get('attempts') and not policy.get('explicit_retry'):
                continue
            start, end = region['start_sample'], region['end_sample']
            span = end-start
            probes = []
            for fraction in (.05, .5, .9):
                left = max(start, min(end-8*16000, start+round(span*fraction)))
                right = min(end, left+12*16000)
                if right-left >= 6*16000:
                    probes.append((left, right))
            try:
                candidate = recognize_range(audio, start, end, language=context.requested_language,
                    cache_root=Path(cache_context['cache_dir'])/'local-language',
                    token=context.cancellation_token,
                    progress=lambda e: legacy.record_run_event('language_recovery_progress', **{
                        'worker_state' if k == 'event' else k: v for k, v in e.items()}),
                    acoustic_samples=probes, source_identity=context.media_identity,
                    retry=bool(policy.get('explicit_retry')))
                state = register_candidate(state, region['id'], candidate)
            except CancelledError:
                _save(path, state)
                raise
            except Exception as exc:
                target = next(r for r in state['ranges'] if r['id'] == region['id'])
                target['attempts'].append(dict(status='failed', backend='qwen_local', reason=str(exc)[:500]))
            _save(path, state)
    context.transcript_acceptance = state
    accepted = apply_selection(raw, state)
    result = dict(payload, segments=accepted, references=accepted)
    pending = pending_ranges(state)
    if not pending:
        context.review_items[:] = [r for r in context.review_items if r.get('category') != '转写语言需要核对']
    context.asr_provisional_cues = [r for r in context.asr_provisional_cues if not any(
        r.get('end_ms', 0) > p['start']*1000 and r.get('start_ms', 0) < p['end']*1000 for p in state['ranges'])]
    context.language_evidence['application_acceptance'] = dict(pending=len(pending), accepted=len(state['ranges'])-len(pending),
        selection_path=str(path), remote_status_preserved=True)
    legacy.record_run_event('transcript_acceptance', pending_ranges=[{k:r[k] for k in ('id','start','end','reason')} for r in pending],
                            accepted_ranges=len(state['ranges'])-len(pending), selection_path=str(path))
    return result
