"""Retry failed optional stages from preserved processing records, as proposals.

No recognition queue, result schema migration, project save, or automatic edit.
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path


def processing_records(project):
    """Restore the persisted segment:N records, never the projected cue IDs."""
    from ..recognition.transcript_data import SpeechSegment, WordUnit
    records = []
    for reference, original in project.asr_evidence.items():
        if not str(reference).startswith('segment:') or not isinstance(original, dict):
            continue
        suffix = str(reference).partition(':')[2]
        if not suffix.isdigit():
            continue
        row = copy.deepcopy(original)
        record_id = int(suffix)
        words = [WordUnit(float(word['start_ms']) / 1000, float(word['end_ms']) / 1000,
            str(word.get('text') or ''), float(word.get('probability', 0) or 0))
            for word in row.get('words') or () if isinstance(word, dict) and
            'start_ms' in word and 'end_ms' in word]
        segment = SpeechSegment(record_id, float(row.get('start_ms', 0)) / 1000,
            float(row.get('end_ms', 0)) / 1000, str(row.get('text') or row.get('final_text') or ''),
            float(row.get('confidence', 0) or 0), words, speaker=str(row.get('speaker_id') or 'S00'),
            caption_arbitration=copy.deepcopy(row.get('caption_arbitration') or {}))
        for field in ('primary_source', 'moss_text', 'firered_text', 'qwen_asr_text', 'firered_llm_text',
                      'alternate_text', 'moss_start', 'moss_end', 'firered_start', 'firered_end'):
            if field in row:
                setattr(segment, field, row[field])
        records.append(segment)
    records.sort(key=lambda row: (row.start, row.segment_id))
    if not records:
        raise ValueError('此工程未保留原处理记录，不能以最终字幕条数代替失败范围。')
    return records


def _retry_options(project, report, options):
    from ..recognition.service import RunOptions
    settings = json.loads(options.settings_snapshot_json) if options and options.settings_snapshot_json else {
        'models': copy.deepcopy(project.generation_metadata.get('models') or report.get('settings', {}).get('models') or {}),
        'switches': copy.deepcopy(report.get('settings', {}).get('switches') or {})}
    models = settings.setdefault('models', {})
    prefix = 'group' if settings.get('switches', {}).get('unified_glm_processing', False) else 'polish'
    snapshots = [row for row in report.get('events') or () if row.get('event') == 'asr_provider_snapshot']
    polish = next((row for row in reversed(snapshots) if row.get('stage') == 'polished'), None)
    complete_role = all(prefix + '_' + key in models for key in ('provider', 'model', 'transport', 'base_url'))
    explicit_profile = bool(options and options.settings_snapshot_json and models.get('ai_service'))
    if polish:
        # An explicitly selected legacy profile outranks stale flattened fields,
        # exactly as it did during recognition. Validate that resolved identity
        # before filling the report's frozen role, without changing providers.
        if explicit_profile and not complete_role:
            from ..providers.asr_provider_snapshot import resolve_provider_snapshot
            selected = resolve_provider_snapshot(settings, stage='polish')
            for key in ('provider', 'model', 'transport', 'protocol', 'endpoint_identity'):
                if polish.get(key) and str(getattr(selected, key)) != str(polish[key]):
                    raise ValueError('工程与原任务的文字服务身份不一致，请从正确任务重新打开。')
        for key in ('provider', 'model', 'transport', 'protocol'):
            if key not in polish:
                raise ValueError('原任务文字服务身份信息不完整，不能猜测请求配置。')
            existing = models.get(prefix + '_' + key) if complete_role else None
            if existing and str(existing) != str(polish[key]):
                raise ValueError('工程与原任务的文字服务身份不一致，请从正确任务重新打开。')
            models[prefix + '_' + key] = polish[key]
        if not complete_role:
            models[prefix + '_base_url'] = report.get('settings', {}).get('models', {}).get(prefix + '_base_url', '') or (
                selected.endpoint().get('base_url', '') if explicit_profile else '')
        if polish.get('endpoint_identity'):
            from ..providers.asr_provider_snapshot import endpoint_identity
            if endpoint_identity(models[prefix + '_base_url']) != str(polish['endpoint_identity']):
                raise ValueError('工程与原任务的文字服务地址不一致，请从正确任务重新打开。')
        complete_role = all(prefix + '_' + key in models for key in ('provider', 'model', 'transport', 'base_url'))
    if not complete_role and not explicit_profile:
        raise ValueError('原任务未保留完整文字服务快照；请使用当前词库创建新的校对预览。')
    saved_glossary = project.generation_metadata.get('terminology_snapshot') or {}
    if options is None:
        profile = report.get('settings', {}).get('content_profile') or {}
        options = RunOptions(content_name=str(profile.get('game') or ''),
            enable_domain_terms=bool(profile.get('domain_terms')), enabled_glossary_ids=tuple(project.glossary_ids))
    return replace(options, settings_snapshot_json=json.dumps(settings, ensure_ascii=False),
        glossary_snapshot_json=json.dumps(saved_glossary, ensure_ascii=False),
        force_refresh_polish=False, force_refresh_group=False)


def _project_proposals(project, proposals, stage):
    from ..recognition.cue_evidence_slice import slice_evidence
    from ..studio.studio_text_tools import TextOccurrence, cue_locked
    hits, pending = [], []
    locked = set((project.studio_state or {}).get('locked_cue_ids', ()))
    for record_id, after in proposals.items():
        reference = 'segment:' + str(record_id)
        original = project.asr_evidence.get(reference) or {}
        before = str(original.get('text') or '')
        if not after or before == after:
            continue
        proposed = {**copy.deepcopy(original), 'retry_proposed_text': after}
        mapped = False
        for cue in project.cues:
            if reference not in cue.evidence_refs or cue_locked(cue, locked):
                continue
            old = slice_evidence(original, cue, 'text')
            new = slice_evidence(proposed, cue, 'retry_proposed_text')
            if not old or not new or old == new or cue.text.count(old) != 1:
                continue
            # The preview carries the exact current cue text. The normal
            # PreviewBinding rejects late/manual edits before any application.
            replacement = cue.text.replace(old, new, 1)
            reason = '失败文字校对重试建议（未核验原音）' if stage == 'polish' else '联网术语核验建议（未核验原音）'
            hits.append(TextOccurrence(cue.id, cue.start_ms, cue.text, replacement,
                (0, len(cue.text)), reason=reason))
            mapped = True
        if not mapped:
            pending.append({'processing_id': record_id, 'before': before, 'after': after,
                'reason': '原处理记录无法唯一映射到当前字幕，或已有人工修改/锁定；未应用'})
    by_cue = {}
    for hit in hits:
        prior = by_cue.get(hit.cue_id)
        if prior is not None and prior.replacement != hit.replacement:
            pending.append({'cue_id': hit.cue_id, 'reason': '多条原处理建议投影冲突；未应用'})
            by_cue[hit.cue_id] = None
        elif hit.cue_id not in by_cue:
            by_cue[hit.cue_id] = hit
    return tuple(hit for hit in by_cue.values() if hit is not None), pending


def completion_retry_preview(project, report, options=None, *, stage='polish', cancel_token=None, cache_context=None):
    """Return Studio-compatible hits/receipt for one explicitly selected retry."""
    if stage not in {'polish', 'terminology'}:
        raise ValueError('未知的可重试阶段')
    import subtitle_core as core
    from ..recognition.service import CancellationToken
    from ..recognition.run_context import activate_runtime_context
    from ..providers.asr_provider_snapshot import resolve_provider_snapshot
    from ..glossary.studio_glossary_service import GlossaryReviewPreview, _optional_metadata_review
    from ..subtitle_rules.polishing import retry_failed_polish
    from ..glossary.domain_terms import retry_pending_term_verification
    token = cancel_token or CancellationToken()
    token.raise_if_cancelled()
    rows = processing_records(project)
    configured = _retry_options(project, report, options)
    settings = json.loads(configured.settings_snapshot_json)
    context = configured.create_runtime_context(core, cancellation_token=token)
    context.asr_settings_snapshot = settings
    provider = resolve_provider_snapshot(settings, stage='polish')
    context.provider_snapshots = {'polish': provider}
    if cache_context is None:
        directory = str((report.get('cache') or {}).get('directory') or '')
        if directory and Path(directory).is_dir():
            cache_context = {'cache_dir': directory, 'identity': {
                'project_id': project.project_id, 'parent_started_at': report.get('started_at'),
                'operation': 'failed_stage_retry'}}
    receipt = {'job_id': context.job_id, 'kind': 'failed_stage_retry', 'stage': stage,
        'project_id': project.project_id, 'parent_started_at': report.get('started_at'),
        'source_processing_records': len(rows), 'projected_subtitles': len(project.cues),
        'scope_unit': 'processing_record', 'provider': provider.public_identity(),
        'asr_run': False, 'audio_verified': False, 'user_project_or_glossary_saved': False,
        'unassigned_new_suspects': []}
    with activate_runtime_context(context):
        if stage == 'polish':
            previous = dict(report.get('polishing_summary') or project.generation_metadata.get('polishing_summary') or {})
            final_failures = [row.segment_id for row in rows if
                (row.caption_arbitration.get('terminology_polish') or {}).get('response_state') == 'fallback']
            if not previous.get('fallback_ids') and final_failures:
                previous['fallback_ids'] = final_failures
            result = retry_failed_polish(rows, project.media.display_name or project.media.path, previous, cache_context)
            proposals = dict(result)
            receipt.update(scope_ids=sorted(set(previous.get('fallback_ids') or ())),
                successful_ids=sorted(result.succeeded), failed_ids=sorted(result.failures),
                successful_cues=len(result.succeeded), fallback_cues=len(result.failures),
                details=result.details, web_search_run=False)
            # The retry result merges child batches. Preserve the real retry
            # scope without inventing an original batch or projected cue ID.
            receipt['unassigned_new_suspects'] = [{**copy.deepcopy(row),
                'source_review_kind': receipt['kind'], 'source_batch_index': None,
                'source_batch_scope': 'merged_failed_retry_batches',
                'source_processing_ids': receipt['scope_ids']}
                for row in getattr(result, 'unassigned_new_suspects', ())]
        else:
            previous = dict(report.get('terminology_summary') or project.generation_metadata.get('terminology_status') or {})
            result = retry_pending_term_verification(rows, project.media.display_name or project.media.path,
                                                    previous, cache_context)
            proposals = {}
            for mapping in result:
                for record_id in mapping['source_ids']:
                    row = next((row for row in rows if row.segment_id == record_id), None)
                    if row is not None:
                        proposals[record_id] = proposals.get(record_id, row.text).replace(mapping['from'], mapping['to'])
            receipt.update(terminology_summary=dict(context.terminology_status),
                scope_ids=list(context.terminology_status.get('scope_ids') or ()),
                successful_ids=sorted(result.checked_ids), failed_ids=sorted(result.failures),
                successful_cues=len(result.checked_ids), fallback_cues=len(result.failures),
                web_search_run=bool(result.evidence))
        token.raise_if_cancelled()
    hits, pending = _project_proposals(project, proposals, stage)
    receipt.update(proposed_cues=len(hits), pending_projection=pending)
    receipt['pending_optional_metadata'] = _optional_metadata_review(
        list(receipt.get('details', {}).values()), receipt['unassigned_new_suspects'])
    return GlossaryReviewPreview(hits, receipt)
