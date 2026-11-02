"""Project-side recovery ranges and provenance, using the existing range splice."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from functools import lru_cache

from .transcript_acceptance import KEY, VERSION, digest, pending_ranges


@lru_cache(maxsize=64)
def _request_timings(path, size, mtime_ns, job_key):
    """Keep only validated durations, not the large report/evidence tree."""
    try:
        report = json.loads(Path(path).read_text('utf8'))
        if report.get('job_id') != json.loads(job_key):
            return None
        phases = [r for r in report.get('events', []) if r.get('event') == 'asr_phase_timing'
                  and r.get('provider') == 'mosi_moss_pro' and r.get('audio_seconds')]
        unique = {int(r['request_index']): r for r in phases if 'request_index' in r}
        if unique and sorted(unique) == list(range(len(unique))):
            return tuple(float(unique[i]['audio_seconds']) for i in sorted(unique))
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def _project_request_timings(project):
    try:
        path = Path(project.report_path)
        stamp = path.stat()
        return _request_timings(str(path), stamp.st_size, stamp.st_mtime_ns,
                                json.dumps(project.generation_metadata.get('job_id'), sort_keys=True))
    except (OSError, ValueError, TypeError):
        return None


def project_pending(project, *, include_legacy=True):
    if project is None:
        return []
    state = project.generation_metadata.get(KEY)
    if isinstance(state, dict):
        return pending_ranges(state)
    return []


def legacy_observations(project):
    if project is None:return []
    requested = (project.generation_metadata.get('language') or {}).get('requested', 'auto')
    from ..subtitle_rules.language_rules import normalize_language,TASK_LANGUAGES
    requested=normalize_language(requested)
    if requested not in TASK_LANGUAGES:
        return []
    from .language_diagnostics import primary_language_regions
    rows = [dict(start=c.start_ms/1000, end=c.end_ms/1000, text=c.text, speaker=c.speaker_id)
            for c in project.cues]
    # Old reports retain the real request durations even when old primary
    # rows have no request receipt. Use them only for this exact project job.
    timings = _project_request_timings(project)
    if timings:
        from .language_diagnostics import transcript_language_sample
        cursor = 0
        regions = []
        for seconds in timings:
            end = cursor+round(seconds*16000)
            text = [r['text'] for r in rows if r['end'] > cursor/16000 and r['start'] < end/16000]
            regions.append(dict(start=cursor/16000, end=end/16000,
                                transcript=transcript_language_sample(text), source='original_task_request_timing'))
            cursor = end
    else:
        regions = primary_language_regions(rows)
    return [dict(id=digest([project.project_id, r['start'], r['end'], requested])[:24],
        start=r['start'], end=r['end'], start_sample=round(r['start']*16000), end_sample=round(r['end']*16000),
        status='observation', reason='suspected_legacy_text_language', review_required=True, requested_language=requested,
        transcript_language=r['transcript']['language'], acoustic_language=None,
        source=r.get('source'), attempts=[]) for r in regions
        if r['transcript'].get('language') not in {None, '', requested}]


def project_review_ranges(project):
    """Include actionable observations without labelling them pending output."""
    if project is None:return []
    state=project.generation_metadata.get(KEY) or {}
    if not state:return legacy_observations(project)
    return [*project_pending(project),*[r for r in state.get('observed_ranges',[]) if r.get('review_required') and not r.get('resolved')]]


def review_scope(project):
    """An explicit review action also works when auto/text-only checks saw no conflict.

    Saved project captions are labelled as reference, never promoted to original
    ASR candidates or used to bypass PCM identity checks.
    """
    if project is None:return None
    state=project.generation_metadata.get(KEY) or {}
    saved=state.get('candidate_rows') or []
    rows=copy.deepcopy(saved) if isinstance(saved,list) else []
    origin='saved_asr_candidates' if rows else 'project_subtitles'
    if not rows:
        rows=[dict(start=c.start_ms/1000,end=c.end_ms/1000,text=c.text,speaker=c.speaker_id,
            source='saved_project_subtitle',timestamp_source='saved_project_timing') for c in project.cues]
    if not rows:return None
    from ..timeline.studio_edit_sequence import timeline_duration_ms
    end=timeline_duration_ms(project)/1000
    if end<=0:return None
    reusable=bool(saved and (state.get('identity') or {}).get('pcm_sha256')
                  and state.get('input_pcm') and state.get('source_identities'))
    remote=next(((r.get('asr_language_receipt') or {}).get('remote_task_id') for r in rows
                 if (r.get('asr_language_receipt') or {}).get('remote_task_id')),None)
    return dict(id=digest([project.project_id,origin,rows])[:24],start=0.,end=end,start_sample=0,
        end_sample=round(end*16000),status='reference',reason='user_requested_review',
        raw_rows=rows,raw_origin=origin,reusable=reusable,remote_task_id=remote,
        requested_language=(project.generation_metadata.get('language') or {}).get('requested','auto'))


def merge_acceptance(project, plan):
    """Resolve covered project-clock scopes; retain raw and previous attempts."""
    state = copy.deepcopy(project.generation_metadata.get(KEY) or dict(version=VERSION, ranges=project_pending(project)))
    start, end = plan.window
    run_acceptance = plan.acceptance
    # The written range project carries the parent archive. Its original
    # identity can still say en while the newly reviewed range says de.
    # Use this run's receipt, not the parent's initial language or an older
    # accepted range. Do not recursively nest the complete parent history.
    history = plan.acceptance.get('range_results') or []
    if history and list(history[-1].get('window_ms') or []) == list(plan.window):
        run_acceptance = history[-1].get('acceptance') or run_acceptance
    completed = [r for r in run_acceptance.get('ranges', []) if r.get('status') == 'accepted']
    attempt = copy.deepcopy(completed[0].get('selected_attempt') or {}) if completed else {}
    from .transcript_acceptance import _selection_language
    from ..subtitle_rules.language_rules import normalize_language
    decision=run_acceptance.get('language_decision') or {}
    accepted_language=decision.get('adopted_language') or (normalize_language(_selection_language(completed[0],run_acceptance)) if completed else None)
    requested_choice=decision.get('requested_language') or accepted_language
    if completed:
        accepted_rows = [dict(start=c.start_ms/1000,end=c.end_ms/1000,text=c.text,speaker=c.speaker_id,
                             source='accepted_range_result',timestamp_source='recovered_aligned_cue')
                         for c in project.cues if c.id in set(plan.inserted_ids)]
        covered = False
        for row in state.get('ranges', []):
            if start <= row['start']*1000+1 and end >= row['end']*1000-1:
                covered = True
                row.update(status='accepted', reason='range_replaced_with_selected_asr',
                    selected_attempt=copy.deepcopy(completed[0].get('selected_attempt')),
                    accepted_cue_ids=list(plan.inserted_ids),
                    archive_cue_ids=list(plan.removed_ids), accepted_rows=copy.deepcopy(accepted_rows),
                    accepted_rows_sha256=digest(accepted_rows))
                if accepted_language:row['requested_language']=accepted_language
        if not covered:
            item = copy.deepcopy(completed[0])
            item.update(start=start/1000,end=end/1000,start_sample=start*16,end_sample=end*16,
                        accepted_cue_ids=list(plan.inserted_ids), archive_cue_ids=list(plan.removed_ids),
                        accepted_rows=copy.deepcopy(accepted_rows),accepted_rows_sha256=digest(accepted_rows))
            state.setdefault('ranges',[]).append(item)
            if accepted_language:item['requested_language']=accepted_language
        from ..playback.audio_graph import capture_audio_graph
        state['audio_graph_digest'] = digest(capture_audio_graph(project))
        state['source_identities'] = copy.deepcopy(project.generation_metadata.get('input_source_identities') or {})
    else:
        # A range can itself still be pending; never clear the parent's gap.
        state.setdefault('last_unsuccessful_attempt', copy.deepcopy(plan.acceptance))
    for row in state.get('observed_ranges',[]):
        if start<=row['start']*1000+1 and end>=row['end']*1000-1 and not run_acceptance.get('observed_ranges'):
            row.update(resolved=True,review_required=False)
    state.setdefault('range_results', []).append(dict(window_ms=list(plan.window), cue_ids=list(plan.inserted_ids),
        backend=attempt.get('backend'), model=attempt.get('model'), acceptance=copy.deepcopy(run_acceptance)))
    from .transcript_delivery import acceptance_counts
    from .transcript_acceptance import apply_selection
    raw = state.get('candidate_rows') or []
    if raw:
        state['counts'] = acceptance_counts(raw, apply_selection(raw, state), state)
        state['counts']['final_cue_count'] = len(project.cues)
    if raw and not pending_ranges(state) and accepted_language:
        covered = all(any(r.get('status') == 'accepted' and r['start'] <= row['start']+.001
            and r['end'] >= row['end']-.001 and r.get('requested_language', accepted_language) == accepted_language
            for r in state.get('ranges', [])) for row in raw)
        if covered:
            language = copy.deepcopy(project.generation_metadata.get('language') or {})
            language.setdefault('original_choice', {k:language.get(k) for k in ('code','requested','evidence')})
            language.update(code=accepted_language,requested=requested_choice,mode=decision.get('mode','manual'),decision=copy.deepcopy(decision),
                evidence=dict(decided_by='explicit_candidate_review',acoustic_language_verified=False))
            project.generation_metadata['language'] = language
    project.generation_metadata[KEY] = state
    # Speaker restore and postprocessing retries must not resurrect archived
    # Italian captions merely because their old raw provider result remains.
    removed = set(plan.removed_ids)
    cache = (project.generation_metadata.get('speaker_recovery') or {}).get('cue_cache')
    if isinstance(cache,dict):
        replaced = removed | set(plan.inserted_ids)
        for label,rows in list(cache.items()):
            cache[label] = [r for r in rows if str(r.get('id')) not in replaced]
        from dataclasses import asdict
        for cue in project.cues:
            if cue.id in set(plan.inserted_ids):
                cache.setdefault(cue.speaker_id,[]).append(asdict(cue))
    states = project.generation_metadata.get('asr_cue_states')
    if isinstance(states,dict):
        for cid in removed:states.pop(cid,None)
        states.update({cid:'final' for cid in plan.inserted_ids})
    superseded = set(project.generation_metadata.get('superseded_asr_evidence') or [])
    superseded.update(ref for row in plan.replaced_snapshot for ref in row.get('evidence_refs',[]))
    project.generation_metadata['superseded_asr_evidence'] = sorted(superseded)
    # A portable project remains authoritative even when its originating cache
    # is absent. Only update an existing, matching store owned by this profile.
    persist_selection_state(state)


def persist_selection_state(state):
    path = Path(state.get('selection_store') or '')
    if state.get('selection_store'):
        from ..runtime_paths import user_data_root
        if path.resolve().is_relative_to((user_data_root()/'cache').resolve()) and path.is_file():
            try:
                saved = json.loads(path.read_text('utf8'))
                if saved.get('identity') == state.get('identity'):
                    from .transcript_acceptance import _save
                    _save(path,state)
            except (OSError,ValueError,TypeError) as exc:
                state['selection_cache_write_error'] = str(exc)[:200]


def inherit_range_appearance(project, plan):
    """Retain time-local formatting without applying old text-indexed markup."""
    old = [c for c in project.cues if c.id in set(plan.removed_ids)]
    wanted = set(plan.inserted_ids)
    for cue in plan.cues:
        if cue.id not in wanted:
            continue
        overlaps = [c for c in old if c.end_ms > cue.start_ms and c.start_ms < cue.end_ms]
        styled = [c for c in overlaps if c.appearance_override]
        basis = max(styled or overlaps, key=lambda c: min(c.end_ms,cue.end_ms)-max(c.start_ms,cue.start_ms), default=None)
        if basis is None:
            continue
        cue.style_id = basis.style_id
        cue.base_preset_id = basis.base_preset_id
        cue.effect_id = basis.effect_id
        cue.transform = copy.deepcopy(basis.transform)
        override = copy.deepcopy(basis.appearance_override)
        override.pop('text_marks', None)
        override.pop('translation_group', None)
        if isinstance(override.get('translation'), dict):
            override['translation'].pop('text_marks', None)
        cue.appearance_override = override
        cue.appearance_generation = basis.appearance_generation
    from dataclasses import asdict
    current = {c.id:c for c in plan.cues if c.id in wanted}
    plan.archive[:] = [asdict(current[r['id']]) if r.get('id') in current else r for r in plan.archive]
