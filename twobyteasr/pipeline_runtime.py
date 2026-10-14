"""Reusable orchestration helpers for the media pipeline.

This module deliberately contains no ASR or subtitle-editing rules.  It owns the
thread coordination, final-stage call order, and transactional hand-off only.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from twobyteasr.runtime import get_runtime_context
from twobyteasr.segmentation import merge_split_interjections_in_cues


def run_parallel_stages(legacy, runners, *, thread_name_prefix, cancel_poll=None):
    """Run named stage callables and merge their thread-local review items.

    ``cancel_poll`` is invoked between completion polls; it should raise the
    queue's cancellation exception (e.g. ``CancelledError``) to stop waiting.
    On cancellation not-yet-started futures are cancelled and running stage
    coordinators are joined before the queue can reset its runtime context.
    Stage bodies must poll cancellation and terminate their owned processes.
    A stage *failure* also waits for siblings to finish,
    because callers rely on the sibling releasing its GPU/CPU resources before
    the serial fallback retries.
    """

    from twobyteasr.service import CancelledError

    def captured(runner):
        with legacy.capture_review_items() as review_items:
            value = runner()
        return value, review_items

    results = {}
    reviews = []
    if cancel_poll is not None:
        cancel_poll()
    pool = ThreadPoolExecutor(
        max_workers=len(runners), thread_name_prefix=thread_name_prefix
    )
    futures = {
        name: pool.submit(captured, runner) for name, runner in runners.items()
    }
    pending = dict(futures)
    try:
        while pending:
            if cancel_poll is not None:
                cancel_poll()
            done = [name for name, future in pending.items() if future.done()]
            if not done:
                time.sleep(0.1)
                continue
            # Preserve caller order in logs and deterministic review aggregation.
            for name in done:
                future = pending.pop(name)
                value, stage_reviews = future.result()
                results[name] = value
                reviews.extend(stage_reviews)
    except (CancelledError, KeyboardInterrupt):
        # Never reset the shared context while a local stage can still write.
        for future in pending.values():
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    except BaseException:
        # 阶段失败路径：等兄弟阶段结束再抛，调用方显存回退依赖此顺序。
        for name, future in pending.items():
            value, stage_reviews = future.result()
            results[name] = value
            reviews.extend(stage_reviews)
        pool.shutdown(wait=True)
        raise
    else:
        pool.shutdown(wait=True)
    legacy.extend_review_items(reviews)
    return results


def _apply_intra_phrase_spacing_to_cues(cues):
    """Apply the intra-phrase spacing layout to finalized cue texts in place."""
    try:
        from .intra_phrase_spacing import apply_intra_phrase_spacing
    except Exception:
        return cues
    for cue in cues:
        text = getattr(cue, "text", "")
        if not text or " " in text:
            continue
        words = getattr(cue, "words", None) or None
        try:
            spaced = apply_intra_phrase_spacing(text, words)
        except Exception:
            continue
        if spaced and spaced != text:
            try:
                cue.text = spaced
            except Exception:
                pass
    return cues


def normalize_delivered_cue_text(cues, legacy=None):
    """The one deterministic format cleanup before cues become the project.

    2026-10-12: recognition results carried format junk such as the trailing
    space of "这里怎么办 " (Stage 9 boundary residue, also replayed from
    cached grouped/final_timing artifacts).  This runs on the final cue list
    of every path immediately before ``create_studio_outputs`` builds the
    project and stamps its delivery reference, so the saved project, the
    result digest, the workbench, proofreading, reopen and export all see the
    same text.  Only format whitespace changes
    (``text_rules.normalize_format_whitespace``); content characters never
    move, and project word alignment is content-indexed.  Idempotent.
    """
    from .text_rules import normalize_format_whitespace
    changed = []
    for cue in cues:
        text = getattr(cue, "text", None)
        if not isinstance(text, str):
            continue
        cleaned = normalize_format_whitespace(text)
        if cleaned != text and cleaned.strip():
            cue.text = cleaned
            changed.append({"cue_id": getattr(cue, "cue_id", None), "before": text, "after": cleaned})
    record = getattr(legacy, "record_run_event", None)
    if changed and callable(record):
        record("cue_format_whitespace_normalized", count=len(changed), samples=changed[:20])
    return changed


def finalize_cues(    cues,
    segments,
    firered_tokens,
    speech_regions,
    audio_seconds,
    timeline_fps,
    legacy,
    *,
    _streaming_partition=False,
):
    """Finalize display timing, then recheck content and numeric events."""
    from .language_rules import is_english
    if is_english() and not any(str(getattr(s, 'primary_source', '')).startswith('vibevoice_') for s in segments):
        return finalize_english_cues(cues, segments, speech_regions, audio_seconds, timeline_fps, legacy)
    if not _streaming_partition and any(str(getattr(s,'primary_source','')).startswith('vibevoice_') for s in segments):
        from .optional_timing import finalize_streaming
        return finalize_streaming(cues,segments,firered_tokens,speech_regions,audio_seconds,timeline_fps,legacy,finalize_cues)
    import copy
    grouped_cues = copy.deepcopy(cues)
    def boundary_phase(name, rows):
        legacy.record_run_event('display_boundary_phase', phase=name, fps=timeline_fps,
            frame_ms=1000 / max(1, float(timeline_fps or 30)), half_open=True,
            cues=[dict(id=c.cue_id, speaker=c.speaker, text=c.text,
                       start_ms=round(c.start*1000), end_ms=round(c.end*1000)) for c in rows])
    boundary_phase('grouped_before_display', grouped_cues)
    # 语气词防拆：成片前把“哎 呦”等白名单拆分形态合并回“哎呦”
    # （与人工校对稿一致；组合不在白名单的保持原样）
    cues = merge_split_interjections_in_cues(cues)
    finalized = legacy.repair_overlong_cues_from_source(
        cues,
        segments,
        firered_tokens,
    )
    finalized = legacy.normalize_cue_times(finalized, timeline_fps)
    text_differences = legacy.final_text_conservation_differences(
        finalized,
        segments,
    )
    if text_differences:
        print(
            "   [文字守恒自愈] 云端断句/超限恢复发生调序，"
            "回退到本地源段重建；不会重新请求云端模型。"
        )
        legacy.record_run_event(
            "final_text_conservation_recovery",
            differences=text_differences,
            previous_cue_count=len(finalized),
        )
        finalized = legacy.build_local_source_cues(
            segments,
            firered_tokens,
        )
        finalized = legacy.normalize_cue_times(finalized, timeline_fps)
    finalized = legacy.validate_final_cues(finalized, segments, audio_seconds)
    finalized = legacy.apply_isolated_single_character_rules_safely(finalized)
    # 2026-09-20：句内空格排版（用户既定规则）——独立语气词/重复应答/整句
    # 重复用 U+0020 分隔。幂等；守恒校验走 content_only（忽略空白）不受影响；
    # 无词级证据时只拆纯语气词（嗯/啊…），"好像还不错"等实词开头不拆。
    finalized = _apply_intra_phrase_spacing_to_cues(finalized)
    finalized = legacy.merge_consecutive_short_repeated_cues(finalized)
    # Cleanup can legitimately merge two short fragments back into a readable
    # phrase, but that new phrase must still obey the five-second export limit.
    finalized = legacy.repair_overlong_cues_from_source(
        finalized,
        segments,
        firered_tokens,
    )
    finalized = legacy.normalize_cue_times(finalized, timeline_fps)
    finalized = legacy.snap_cue_starts_to_vad_onsets(
        finalized,
        speech_regions,
        timeline_fps,
    )
    boundary_phase('normalized_and_vad_onsets', finalized)
    finalized = legacy.extend_cue_tails_by_speaker(
        finalized,
        audio_seconds,
        timeline_fps,
    )
    boundary_phase('speaker_reading_tail', finalized)
    finalized = legacy.bridge_short_display_gaps(
        finalized,
        audio_seconds,
        timeline_fps,
    )
    boundary_phase('short_gap_bridge', finalized)
    finalized = legacy.validate_final_cues(
        finalized,
        segments,
        audio_seconds,
        validate_text=False,
    )
    legacy.collect_review_items(
        segments,
        finalized,
        speech_regions,
        firered_tokens,
    )
    from .display_timing import protect_runtime_display_tails
    from .subtitle_fidelity import recover_final_content
    finalized = recover_final_content(finalized, grouped_cues, segments, firered_tokens, legacy)
    boundary_phase('validated_and_content_recovered', finalized)
    overlap_audit = protect_runtime_display_tails(finalized, segments)
    legacy.record_run_event('display_overlap_protection', policy_version=4, pairs=overlap_audit)
    if segments:
        finalized.sort(key=lambda c:(c.start,c.end,c.speaker))
        for index,cue in enumerate(finalized,1):cue.cue_id=index
    boundary_phase('final_half_open_display', finalized)
    return finalized


def finalize_english_cues(cues, segments, speech_regions, audio_seconds, timeline_fps, legacy):
    """English display timing (2026-10-14): the cues are already cut between words.

    The Chinese finalize re-splits any cue over 16 letters, merges single
    characters and repeated short cues and measures reading time in Chinese
    characters; none of that applies to English. Here: frame quantizing, a
    reading-time floor in English characters per second, at most 6 seconds,
    no overlap inside one speaker, then the shared text-free steps (start at
    the voice onset, reading tail, short-gap bridge, display-tail protection).
    Text is never changed.
    """
    from .display_timing import protect_runtime_display_tails
    from .english_text import RULES, display_length
    fps = float(timeline_fps or 30)
    frame = 1.0 / fps
    finalized = [cue for cue in sorted(cues, key=lambda c: (c.start, c.end, c.speaker)) if str(cue.text or "").strip()]
    if not finalized:
        raise RuntimeError("断句后没有可用字幕。")
    for cue in finalized:
        start = max(0.0, float(cue.start))
        floor = max(RULES.min_seconds, display_length(cue.text) / RULES.warning_cps)
        end = min(max(float(cue.end), start + floor), start + RULES.max_seconds)
        if audio_seconds:
            end = min(end, float(audio_seconds))
        cue.start = round(start * fps) / fps
        cue.end = max(round(end * fps) / fps, cue.start + frame)
    last_by_speaker = {}
    for cue in finalized:
        previous = last_by_speaker.get(cue.speaker)
        if previous is not None and previous.end > cue.start:
            previous.end = max(previous.start + frame, cue.start)
        last_by_speaker[cue.speaker] = cue
    finalized = legacy.snap_cue_starts_to_vad_onsets(finalized, speech_regions, timeline_fps)
    finalized = legacy.extend_cue_tails_by_speaker(finalized, audio_seconds, timeline_fps)
    finalized = legacy.bridge_short_display_gaps(finalized, audio_seconds, timeline_fps)
    for cue in finalized:
        if cue.end - cue.start > RULES.max_seconds:
            cue.end = cue.start + RULES.max_seconds
        if cue.end <= cue.start:
            cue.end = cue.start + frame
    overlap_audit = protect_runtime_display_tails(finalized, segments)
    legacy.record_run_event('display_overlap_protection', policy_version=4, pairs=overlap_audit)
    finalized.sort(key=lambda c: (c.start, c.end, c.speaker))
    for index, cue in enumerate(finalized, 1):
        cue.cue_id = index
    lengths = sorted(display_length(cue.text) for cue in finalized)
    within = sum(length <= RULES.max_chars for length in lengths) / len(lengths)
    print(f"[完成] 英文断句：{len(finalized)} 条，中位 {lengths[len(lengths) // 2]} 字符，"
          f"{within:.0%} 不超过 {RULES.max_chars} 字符（按单词断开，单词完整）。")
    legacy.record_run_event('english_cues_finalized', count=len(finalized), median_chars=lengths[len(lengths) // 2],
                            within_max=round(within, 4))
    return finalized


def _punctuation_default(runtime_context, legacy) -> str:
    """The home-page choice frozen in this task's settings snapshot."""
    from .punctuation_style import default_mode_for_new_tasks
    settings = getattr(runtime_context, "asr_settings_snapshot", None) or getattr(legacy, "RUNTIME_SETTINGS", {}) or {}
    return default_mode_for_new_tasks(settings)


def complete_media_run(
    *,
    cues,
    segments,
    file_index,
    file_total,
    started,
    audio_seconds,
    txt_path,
    srt_path,
    stage_index,
    stage_total,
    legacy,
    runtime_context=None,
    include_srt=True,
    model_statuses=None,
    review_classification=None,
    real_three_source_cues=None,
    cache_owners=None,
):
    """Write outputs transactionally, finish the report, and return public paths."""
    review_items = legacy.print_review_summary()
    runtime_context = runtime_context or get_runtime_context()
    # Before the project and its delivery digest exist: never a later rewrite.
    normalize_delivered_cue_text(cues, legacy)
    output_details = {}
    # Recognition persists its project and report. File export is an explicit
    # user operation; even legacy saved output switches must not write siblings
    # next to the media, nor claim stale SRT files as this run's output.
    txt_path = ""
    srt_path = ""
    include_srt = False

    # Japanese -> Chinese, when chosen before the task: written with the project.
    translation_metadata = {}
    from twobyteasr.service import CancelledError
    try:
        from twobyteasr.recognition_translation import translate_runtime_cues
        translation_metadata = translate_runtime_cues(cues, runtime_context, legacy)
    except CancelledError:
        raise
    except Exception as exc:  # the recognition result is still delivered
        legacy.add_review_item(0.0, "翻译未完成", f"识别结果已保存；可在工作台重新翻译：{exc}"[:200],
                               priority=2, severity="warning")
        legacy.record_run_event("subtitle_translation_failed", error=f"{type(exc).__name__}: {exc}"[:300])

    def write_studio_project():
        try:
            from twobyteasr.studio_project import create_studio_outputs
    
            media_path = str(getattr(runtime_context, "media_path", "") or "")
            if not media_path:
                # Existing RuntimeContext versions do not own the media path. Derive it
                # only when the legacy report has an active media record.
                active_report = getattr(legacy.task_reporting, "_active_report", None) or {}
                media_path = str(active_report.get("media", {}).get("path") or "")
            if media_path:
                from .recognition_result import media_identity_for_task
                input_sources = {source: media_identity_for_task(source, runtime_context)
                    for source in (runtime_context.recognition_snapshot.get("sources") or {media_path: {}})}
                token = getattr(runtime_context, "cancellation_token", None)
                if token is not None:
                    token.raise_if_cancelled()
                report_json_path, _report_text_path = legacy.task_reporting.report_paths_for_media(
                    media_path
                )
                output_details.update(
                    create_studio_outputs(
                        media_path,
                        cues,
                        txt_path=txt_path,
                        srt_path=srt_path if include_srt else "",
                        report_path=report_json_path,
                        segments=segments,
                        generation_metadata={
                            "job_id": runtime_context.job_id,
                            "media_identity": dict(runtime_context.media_identity),
                            "input_source_identities": input_sources,
                            "models": {**dict((runtime_context.asr_settings_snapshot or getattr(legacy, "RUNTIME_SETTINGS", {})).get("models", {})),
                                       "speaker_source": runtime_context.speaker_source},
                            "model_statuses": dict(model_statuses or {}),
                            "created_by": "2ByteASR recognition pipeline",
                            "recognition_purpose": str(getattr(runtime_context, "recognition_purpose", "final") or "final"),
                            "analysis_transcript": str(getattr(runtime_context, "recognition_purpose", "final") or "final") == "analysis",
                            "asr_manifest_key": str(getattr(runtime_context, "asr_manifest_key", "") or ""),
                            "asr_provisional_cues": list(getattr(runtime_context, "asr_provisional_cues", ()) or ()),
                            "speaker_recovery": dict(getattr(runtime_context, "speaker_recovery", {}) or {}),
                            "terminology_status": dict(getattr(runtime_context,"terminology_status",{}) or {}),
                            "polishing_summary": dict(getattr(runtime_context,"polishing_summary",{}) or {}),
                            "terminology_snapshot": (runtime_context.glossary_snapshot.to_dict()
                                if getattr(runtime_context, "glossary_snapshot", None) is not None else {}),
                            # Spoken language of the media (not of any speaker) and how it was decided.
                            "language": {
                                "code": str(getattr(runtime_context, "task_language", "") or "zh"),
                                "requested": str(getattr(runtime_context, "requested_language", "auto") or "auto"),
                                "evidence": dict(getattr(runtime_context, "language_evidence", {}) or {}),
                            },
                            "subtitle_output": {
                                "mode": str(getattr(runtime_context, "subtitle_output", "original") or "original"),
                                "translation_script": str(getattr(runtime_context, "translation_script", "zh-Hans") or "zh-Hans"),
                            },
                            # New-task punctuation default (2026-10-13); applied to the project's
                            # display/export only, the recognized text is stored unchanged.
                            "subtitle_punctuation": {
                                "mode": _punctuation_default(runtime_context, legacy),
                            },
                            **translation_metadata,
                        },
                        glossary_ids=getattr(runtime_context, "enabled_glossary_ids", ()),
                        target_project_path=str(
                            getattr(runtime_context, "studio_project_path", "") or ""
                        ),
                        recognition_snapshot=getattr(runtime_context, "recognition_snapshot", None),
                        decoded_audio_seconds=audio_seconds,
                    )
                )
                if token is not None:
                    token.raise_if_cancelled()
                runtime_context.committed_result_ref = __import__("json").loads(output_details.get("result_ref_json") or "{}")
                print(f"   [Subtitle Studio] {output_details['project']}")
                provisional = list(getattr(runtime_context, "asr_provisional_cues", ()) or ())
                if provisional:
                    from twobyteasr.studio_project import load_project
    
                    completed_project = load_project(output_details["project"])
                    legacy.record_run_event(
                        "cue_delta",
                        source_path=media_path,
                        manifest_key=str(getattr(runtime_context, "asr_manifest_key", "") or ""),
                        backend=str(getattr(legacy, "PRIMARY_ASR_BACKEND", "") or ""),
                        chunk_index=-1,
                        state="final",
                        reused=False,
                        cues=[
                            {
                                "id": cue.id,
                                "start_ms": cue.start_ms,
                                "end_ms": cue.end_ms,
                                "text": cue.text,
                                "speaker_id": cue.speaker_id,
                                "style_id": cue.style_id,
                                "state": "final",
                            }
                            for cue in completed_project.cues
                        ],
                        replacement_mapping=dict(
                            completed_project.generation_metadata.get("asr_replacement_mapping", {})
                        ),
                    )
        except Exception as exc:
            token = getattr(runtime_context, "cancellation_token", None)
            if token is not None:
                token.raise_if_cancelled()
            print(f"   [警告] 识别结果工程保存失败，识别缓存与报告可用于恢复：{exc}")
            output_details['project_error'] = str(exc)
            output_details['project'] = ''
            legacy.record_run_event("studio_project_failed", error=str(exc))

    def deliver_outputs():
        legacy.record_run_event("studio_project_saving", project_path=str(getattr(runtime_context, "studio_project_path", "") or ""))
        write_studio_project()
        if not output_details.get("project"):
            raise RuntimeError("识别结果工程保存失败：" + str(output_details.get("project_error") or "unknown"))
        if output_details.get("project"):
            legacy.record_run_event("studio_project_saved", project_path=output_details["project"], cue_count=len(cues),
                **{k: v for k, v in runtime_context.committed_result_ref.items() if k not in {"path", "cue_count"}})

    legacy.run_timed_stage(
        stage_index,
        stage_total,
        "保存识别结果与工程",
        "磁盘",
        deliver_outputs,
    )
    elapsed = time.perf_counter() - started
    degraded = bool(output_details.get('project_error')) or any(
        legacy.review_item_severity(item) in {"error", "warning"}
        for item in review_items
        if isinstance(item, dict)
    )
    report_json_path, report_text_path = legacy.finish_media_report(
        "degraded_success" if degraded or getattr(runtime_context, "speaker_recovery", {}).get("needs_confirmation") else "success",
        elapsed_seconds=round(elapsed, 3),
        audio_seconds=round(audio_seconds, 3),
        cue_count=len(cues),
        segment_count=len(segments),
        review_items=review_items,
        model_statuses=dict(model_statuses or {}),
        review_classification=dict(review_classification or {}),
        real_three_source_cues=list(real_three_source_cues or ()),
        cache_owners=dict(cache_owners or {}),
        optional_models=dict(runtime_context.media_identity.get('optional_models',{})),
        outputs={**output_details},
    )
    print(
        f"\n[文件完成 {file_index}/{file_total}] {legacy.format_elapsed(elapsed)}"
        f"\n   工程：{output_details.get('project', '')}"
    )
    if report_text_path:
        print(f"   任务报告：{report_text_path}\n   结构化报告：{report_json_path}")
    return txt_path, (srt_path if include_srt else ""), elapsed
