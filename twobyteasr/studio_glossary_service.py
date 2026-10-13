"""Service boundary for a new, immutable text-only glossary review job.

The recognition correction API and safety adjudicator are reused. Existing
projects and ASR caches are never mutated here; Studio applies chosen diffs.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GlossaryReviewPreview:
    hits: tuple
    receipt: dict[str, Any]


def _optional_metadata_review(details, unassigned):
    scoped = [row for detail in details for row in detail.get('new_suspects', ())]
    return {'status': 'pending_review' if scoped or unassigned else 'none',
        'unassigned_rows': len(unassigned), 'scoped_new_suspect_rows': len(scoped),
        'invalid_scoped_new_suspect_rows': sum(row.get('validation_state') == 'invalid' for row in scoped)}


def preview_glossary_correction(project, cue_ids, snapshot, settings, *, cancel_token=None, use_ai=True, progress=None):
    import subtitle_core  # Initialize the legacy facade before its correction re-exports.
    from .service import CancellationToken
    from .runtime import RuntimeContext, activate_runtime_context
    from .asr_provider_snapshot import resolve_provider_snapshot
    from .models import SpeechSegment
    from concurrent.futures import ThreadPoolExecutor
    from .polishing import call_correction_api, correction_batches, correction_task_budget, prepare_correction_request
    from .terminology import TermResolver, GlossarySnapshot
    from .studio_text_tools import TextOccurrence, cue_locked
    from .correction import split_items_for_api
    from .cue_evidence_slice import cue_evidence

    token = cancel_token or CancellationToken()
    token.raise_if_cancelled()
    frozen = copy.deepcopy(settings)
    provider = None
    request_error = ''
    if use_ai:
        try:
            provider = resolve_provider_snapshot(frozen, stage="polish")
        except Exception as exc:
            request_error = str(exc)
    context = RuntimeContext(enable_domain_terms=bool(snapshot.libraries),
        enabled_glossary_ids=[x.id for x in snapshot.libraries], glossary_snapshot=snapshot,
        cancellation_token=token, asr_settings_snapshot=frozen,
        provider_snapshots={"polish": provider} if provider else {})
    from .content_scene import resolve_content_scene
    previous_scene = (project.generation_metadata.get('runtime_profile') or {}).get('resolved_context') or {}
    if previous_scene.get('source') == 'user_selected':
        context.game_name = str(previous_scene.get('domain') or '')
    scene = resolve_content_scene(context, snapshot)
    wanted = set(cue_ids)
    locked = set((project.studio_state or {}).get("locked_cue_ids", ()))
    cues = [c for c in project.cues if c.id in wanted and not cue_locked(c, locked)]
    resolver = TermResolver(snapshot)
    segments = []
    local_normalizations = {}
    for index, cue in enumerate(cues, 1):
        # Current editable text is the review baseline. Original ASR remains
        # independent evidence, never a way to overwrite intervening edits.
        raw = cue.text
        normalized = resolver.resolve(raw, scene=scene)
        if normalized.hits:
            local_normalizations[index] = {'cue_id': cue.id, 'source': raw,
                'result': normalized.text, 'hits': [hit.to_dict() for hit in normalized.hits],
                'kind': 'confirmed_local_name_normalization', 'acoustic_verified': False}
        evidence = [project.asr_evidence.get(ref, {}) for ref in cue.evidence_refs]
        field = lambda key: cue_evidence(project, cue, key)
        segments.append(SpeechSegment(index, cue.start_ms/1000, cue.end_ms/1000,
            normalized.text, .0, [], speaker=cue.speaker_id,
            primary_source=next((str(row.get('primary_source')) for row in evidence
                                 if row.get('primary_source')), 'project-original'),
            moss_text=field("moss_text"), firered_text=field("firered_text"),
            qwen_asr_text=field("qwen_asr_text"), firered_llm_text=field("firered_llm_text")))
    receipt = {"job_id": context.job_id, "kind": "current_glossary_text_review",
        "project_id": project.project_id, "parent_snapshot_digest":
            GlossarySnapshot.from_dict(project.generation_metadata.get("terminology_snapshot") or {}).digest,
        "snapshot": snapshot.to_dict(), "snapshot_summary": snapshot.summary(),
        "resolved_context": scene.to_dict(),
        "provider": provider.public_identity() if provider else None, "asr_run": False, "audio_verified": False,
        "web_search_run": False, "successful_cues": 0, "fallback_cues": 0, "segments": [],
        'unassigned_new_suspects': [], 'mode':'current_committed_selected_libraries',
        'ai_requested':bool(use_ai), 'request_errors':[request_error] if request_error else [],
        'requested_cues':len(wanted), 'checked_cues':len(cues),
        'locked_or_out_of_scope':len(wanted)-len(cues), 'pending_rows':[], 'failed_cues':[]}
    receipt['local_normalizations'] = list(local_normalizations.values())
    receipt['local_normalization_count'] = sum(len(row['hits']) for row in local_normalizations.values())
    proposed = {}
    details = {}
    with activate_runtime_context(context):
        batches = correction_batches(segments) if provider else []
        # One task deadline for the sequential batches below (ADR 0083).
        retry_budget = correction_task_budget(provider.timeout_policy, len(batches)) if provider else None
        report = progress if callable(progress) else (lambda *_args: None)
        report(0, len(batches))
        evidence = snapshot.evidence()

        def request_args(batch):
            first, last = batch[0].segment_id-1, batch[-1].segment_id
            return (batch, list(snapshot.canonical_terms),
                "".join(s.text for s in segments[max(0, first-20):first])[-300:],
                "".join(s.text for s in segments[last:last+20])[:300],
                project.media.display_name or project.media.path, "", [], [], [])

        def prepare(args):
            # Best effort: a failure here is rebuilt and reported by the real call.
            try:
                prepare_correction_request(*args, glossary_evidence=evidence)
            except Exception:
                pass

        # The next batch's request is built while the current one is with the
        # provider; call_correction_api then reuses it instead of rebuilding.
        preparer = ThreadPoolExecutor(max_workers=1, thread_name_prefix='glossary-review-prepare')
        pending = None
        try:
            for number, batch in enumerate(batches, 1):
                token.raise_if_cancelled()
                if number > 1:
                    report(number - 1, len(batches))
                args = request_args(batch)
                if pending is None:
                    prepare(args)
                else:
                    pending.result()
                pending = (preparer.submit(prepare, request_args(batches[number]))
                           if number < len(batches) else None)
                try:
                    result = call_correction_api(*args,
                        glossary_evidence=evidence, batch_index=number, batch_total=len(batches),
                        _retry_budget=retry_budget)
                except Exception as exc:
                    token.raise_if_cancelled()
                    receipt['request_errors'].append(str(exc))
                    receipt['fallback_cues'] += len(batch)
                    continue
                proposed.update(result)
                receipt["successful_cues"] += len(getattr(result,"succeeded",set(result)))
                receipt["fallback_cues"] += len(getattr(result,"failures",{}))
                receipt['failed_cues'].extend({'cue_id':cues[index-1].id,'reason':str(reason)}
                    for index,reason in getattr(result,'failures',{}).items() if type(index) is int and 1<=index<=len(cues))
                receipt['unassigned_new_suspects'].extend({**copy.deepcopy(row),
                    'source_review_kind': receipt['kind'], 'source_batch_index': number,
                    'source_processing_ids': [segment.segment_id for segment in batch],
                    'source_project_cue_ids': [cues[segment.segment_id-1].id for segment in batch]}
                    for row in getattr(result, 'unassigned_new_suspects', ()))
                details.update(getattr(result,"details",{}))
        finally:
            if pending is not None:
                pending.cancel()
            preparer.shutdown(wait=True)
        report(len(batches), len(batches))
        token.raise_if_cancelled()
    from .terminology_retrieval import retrieve_candidates
    from .terminology_support import recall_gaps, suspicious_spans
    from .studio_glossary_review import (diff_occurrences, recover_review_edits, local_review_candidates,
                                         transplant_model_edits)
    original_segments = copy.deepcopy(segments)
    for segment,cue in zip(original_segments,cues):
        segment.text=cue.text
    candidates=retrieve_candidates(snapshot,original_segments,scene=scene)
    gaps=recall_gaps(original_segments,candidates,snapshot=snapshot)
    suspects=suspicious_spans(original_segments,candidates,gaps)
    hits = []
    for segment, cue in zip(segments, cues):
        model_text=proposed.get(segment.segment_id,segment.text)
        # 2026-10-12: the service answers in clean_subtitle_text space (spaces
        # collapsed/stripped, ordinary punctuation deleted) even when the model
        # made no edit or the request fell back. Only the model's own edits,
        # re-applied onto the editable text, may become an AI proposal.
        ai_draft=transplant_model_edits(segment.text,model_text)
        transplanted=ai_draft is not None
        if ai_draft is None:ai_draft=model_text
        # A model's unchanged/failed response cannot erase confirmed local normalization.
        final=resolver.resolve(ai_draft,scene=scene).text
        local_only=final==segment.text
        manual=bool(cue.original_text and cue.text!=cue.original_text)
        source='local_confirmed' if local_only else 'ai_accepted'
        reason='当前词库本地确认名称规范化（未核验原音）' if local_only else 'AI 校对建议'
        if manual and not local_only:reason+='；已有人工修改，需确认'
        hits.extend(diff_occurrences(cue,final,reason=reason,source=source,
            selected=local_only or not manual,missing='未核验原音',
            ignore_format_only=not local_only))
        detail=details.get(segment.segment_id,{})
        review,invalid=recover_review_edits(cue,segment.text,detail,snapshot,scene)
        cue_candidates=[row for row in candidates if any(m.get('cue_id')==segment.segment_id for m in row['matches'])]
        review.extend(local_review_candidates(cue,cue.text,cue_candidates,scene,
            processing_id=segment.segment_id))
        for hit in review:
            if not any(h.cue_id==hit.cue_id and h.span==hit.span and h.replacement==hit.replacement for h in hits):hits.append(hit)
        for suspect in (row for row in suspects if row['cue_id']==segment.segment_id):
            if any(hit.cue_id==cue.id and hit.span[0]<=suspect['start'] and suspect['end']<=hit.span[1] for hit in hits):continue
            if any(term.confirmed and (term.canonical.casefold()==suspect['surface'].casefold()
                    or any(alias.casefold()==suspect['surface'].casefold() for alias in term.aliases))
                   for library in snapshot.libraries for term in library.terms):continue
            verdict=next((row for row in detail.get('suspect_results',()) if row.get('suspect_id')==suspect['suspect_id']),{})
            options=[row['canonical'] for row in candidates if row['candidate_id'] in suspect['candidate_ids']]
            receipt['pending_rows'].append({'cue_id':cue.id,'start_ms':cue.start_ms,'original':cue.text,
                'surface':suspect['surface'],'span':[suspect['start'],suspect['end']],
                'state':'missing_alias_or_candidate','canonical_options':options,
                'reason':verdict.get('evidence') or '当前词库没有已确认关联；请选择规范词或明确新增',
                'library_ids':[library.id for library in snapshot.libraries]})
        for rejected in invalid:
            receipt['pending_rows'].append({'cue_id':cue.id,'start_ms':cue.start_ms,'original':cue.text,
                'surface':str(rejected.get('from') or ''),'state':'invalid_output',
                'reason':rejected.get('review_state'),'canonical_options':[]})
        receipt['segments'].append({'cue_id':cue.id,'original_baseline':cue.text,'original_asr':cue.original_text,
            'input_text':segment.text,'local_draft':segment.text,'ai_draft':ai_draft,
            'ai_model_text':model_text,'ai_edits_transplanted':transplanted,
            'ai_response_edits':copy.deepcopy(detail.get('returned_edits',())), 'final_text':final,
            'local_normalization':local_normalizations.get(segment.segment_id),'detail':detail,
            'retrieved_candidates':cue_candidates,'final_diff':[{'span':list(h.span),'from':h.original,
                'to':h.replacement,'source':h.source,'default_selected':h.default_selected} for h in hits if h.cue_id==cue.id]})
    receipt["proposed_cues"] = len({h.cue_id for h in hits})
    receipt['proposed_changes']=len(hits)
    receipt['automatic_changes']=sum(h.default_selected for h in hits)
    receipt['confirmation_changes']=sum(not h.default_selected for h in hits)
    receipt['rejected_changes']=sum(len(row.get('rejected_edits',())) for row in details.values())
    receipt['ai_returned_changes']=sum(len(row.get('returned_edits',())) for row in details.values())
    receipt['ai_accepted_changes']=sum(len(row.get('accepted_edits',())) for row in details.values())
    receipt['missing_associations']=sum(row['state']=='missing_alias_or_candidate' for row in receipt['pending_rows'])
    receipt['empty_state']=('request_failed' if receipt['request_errors'] or receipt['fallback_cues'] and not receipt['successful_cues'] else 'library_read_error' if any(not x.found for x in snapshot.libraries)
        else 'needs_confirmation' if receipt['confirmation_changes'] else 'missing_associations' if receipt['missing_associations']
        else 'invalid_output' if any(row['state']=='invalid_output' for row in receipt['pending_rows'])
        else 'changes_ready' if hits else 'no_changes')
    receipt['pending_optional_metadata'] = _optional_metadata_review(
        [row['detail'] for row in receipt['segments']], receipt['unassigned_new_suspects'])
    from .runtime_paths import user_data_root
    from .cache import atomic_write_json
    diagnostic=user_data_root()/'logs'/'glossary-review'/f'{context.job_id}.json'
    receipt['diagnostic_path']=str(diagnostic)
    receipt = json.loads(json.dumps(receipt, ensure_ascii=False))
    try:
        diagnostic.parent.mkdir(parents=True,exist_ok=True)
        atomic_write_json(str(diagnostic),receipt)
        from .storage_service import register_cache
        register_cache(diagnostic,'log',producer='studio_glossary_review',rebuild='local')
    except OSError as exc:
        receipt['diagnostic_error']=str(exc)
    return GlossaryReviewPreview(tuple(hits), receipt)
