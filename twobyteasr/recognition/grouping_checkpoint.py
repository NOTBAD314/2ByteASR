"""Persist the verified source draft and independently validated grouping ranges."""
from __future__ import annotations

import copy
import time

from .delivery_checkpoint import dependency as delivery_dependency
from .run_context import sync_legacy_runtime
from .task_journal import digest
from ..subtitle_rules.grouping_contract import capture_grouping_source


CONTEXT_FIELDS = (
    "task_language", "language_evidence", "language_mode", "language_decision",
    "review_items", "polishing_summary", "terminology_status", "speech_coverage",
    "speaker_recovery", "transcript_acceptance", "independent_asr_runs",
)


def _key(context):
    return f"pre-grouping:{context.media_index}"


def _source_dependency(context):
    dependency = delivery_dependency(context)
    # A grouping change invalidates its outputs, not the adopted ASR draft.
    del dependency["rules"]["group_cache"], dependency["rules"]["group_prompt"], dependency["rules"]["timing"]
    return dependency


def save(context, legacy, segments, tokens, regions, *, seconds, fps, stage,
         use_ai, cache_context):
    journal = context.task_journal
    if journal is None or context.recognition_snapshot or context.shard_id:
        return
    source = capture_grouping_source(segments, job_id=context.job_id)
    binding = _source_dependency(context)
    payload = {
        "version": 1, "state": "pre_grouping_draft", "media": context.media_identity,
        "source": source.identity(), "segments": legacy.serialize_segments(segments),
        "tokens": list(tokens), "regions": list(regions), "seconds": seconds, "fps": fps,
        "stage": stage, "use_ai": use_ai, "cache_identity": cache_context["identity"],
        "ai_workers": getattr(context.execution_budget, "ai_requests", None),
        "context": {key: copy.deepcopy(getattr(context, key)) for key in CONTEXT_FIELDS},
        "configuration": binding,
    }
    path = journal.publish(_key(context), payload, binding)
    legacy.record_run_event("grouping_checkpoint_saved", path=str(path), source_rows=len(segments),
                            source_sha256=source.fingerprint, status="pre_grouping_draft")


def load(context, *, cache_context=None):
    if not context.task_journal or not context.resume or context.recognition_snapshot:
        return None
    binding = _source_dependency(context)
    payload = context.task_journal.load_artifact(_key(context), binding)
    if payload:
        source = capture_grouping_source(payload["segments"], job_id=context.job_id)
        if (payload.get("version") == 1 and digest(payload.get("configuration")) == digest(binding)
                and payload.get("media") == context.media_identity
                and payload.get("source") == source.identity()
                and (cache_context is None or payload.get("cache_identity") == cache_context["identity"])):
            return payload
    artifacts = context.task_journal.record["task"]["artifacts"]
    if not payload and _key(context) in artifacts and 'firered_evidence' in binding['rules']:
        # Only retire a pre-admission draft whose remaining dependencies still
        # match. The normal pipeline can reuse the original ASR and PCM.
        previous = copy.deepcopy(binding)
        del previous['rules']['firered_evidence']
        if context.task_journal.load_artifact(_key(context), previous):
            return None
    if payload or _key(context) in artifacts:
        raise ValueError("断句恢复检查点与当前素材、配置或缓存不相符，已保留原稿。")
    return None


def range_dependency(context, dependency_data, snapshot):
    from ..providers.asr_provider_snapshot import GROUP_CACHE_VERSION
    return {"input": context.media_identity.get("fingerprint"), "rules": GROUP_CACHE_VERSION,
            "provider": snapshot.fingerprint if snapshot else "", "range": dependency_data}


def range_key(context, index):
    return f"grouping:{context.media_index}:{context.shard_id}:{index}"


def resume(payload, *, context, legacy, cache_context, file_index, file_total, started=None):
    """Enter the production grouping and delivery stages from the frozen source."""
    from .pipeline_runtime import complete_media_run, finalize_cues
    from .speech_coverage import checkpoint
    from ..subtitle_rules.display_timing import protect_runtime_display_tails
    from ..providers.asr_provider_snapshot import task_provider_snapshot

    for field in CONTEXT_FIELDS:
        setattr(context, field, copy.deepcopy(payload["context"][field]))
    sync_legacy_runtime(legacy, context)
    rows = legacy.deserialize_segments(payload["segments"])
    tokens, regions = payload["tokens"], payload["regions"]
    seconds, fps = payload["seconds"], payload["fps"]
    stage = payload["stage"]
    use_ai = payload["use_ai"]
    snapshot = task_provider_snapshot("group") if use_ai else None
    context.provider_snapshot = snapshot
    if payload.get("ai_workers"):
        from dataclasses import replace
        from ..system.task_resources import task_budget
        context.execution_budget = replace(task_budget(), ai_requests=payload["ai_workers"])
    legacy.record_run_event("grouping_checkpoint_resumed", source_rows=len(rows),
                            repeated_asr_calls=0, repeated_polish_calls=0)
    legacy.record_run_event("task_audio_ready", seconds=round(seconds, 3))
    cues = legacy.run_timed_stage(stage, stage + 2, "全文断句（由校对恢复稿继续）", "断句",
        lambda: legacy.group_subtitles(rows, tokens, regions, cache_context=cache_context,
                                       use_ai=use_ai, provider_snapshot=snapshot))
    checkpoint(context.speech_coverage, "segmentation", cues)
    cues = legacy.run_timed_stage(stage + 1, stage + 2, "锁定最终字幕时间轴", "CPU+帧量化",
        lambda: finalize_cues(list(cues), rows, tokens, regions, seconds, fps, legacy))
    protect_runtime_display_tails(cues, rows)
    return complete_media_run(cues=cues, segments=rows, file_index=file_index, file_total=file_total,
        started=started if started is not None else time.perf_counter(), audio_seconds=seconds,
        txt_path="", srt_path="", stage_index=stage + 2, stage_total=stage + 2,
        legacy=legacy, runtime_context=context, include_srt=False)
