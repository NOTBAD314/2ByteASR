"""Cloud grouping request/response handling and subtitle grouping orchestration."""

import json
import threading
import time

from twobyteasr.ai_providers import provider_for_stage

from subtitle_core import *  # noqa: F401,F403
from twobyteasr.segmentation import (
    firered_pause_character_gaps,
    hard_break_character_offsets,
    indexed_content_for_prompt,
    individual_cue,
    locally_repair_resegmented_cue,
    merge_hanging_attribute_cues,
    merge_isolated_two_character_cues,
    merge_same_speaker_dangling_cues,
    protected_source_boundary_offsets,
    refine_resegmented_texts,
    repair_compact_utterance_boundary_offsets,
    repair_dependent_particle_boundary_offsets,
    repair_dependent_prefix_boundary_offsets,
    repair_hanging_attribute_boundary_offsets,
    repair_incomplete_boundary_offsets,
    repair_latin_predicate_boundary_offsets,
    repair_lexical_boundary_offsets,
    repair_mid_word_adjacent_cues,
    repair_segmenter_word_boundary_offsets,
    segment_content_timeline,
    semantic_restart_boundary_offsets,
    snap_boundaries_away_from_word_interiors,
    snap_internal_cue_boundaries,
    source_segment_character_offsets,
    text_boundary_hints,
    texts_from_boundary_offsets,
)


# Resolve cache-backed helpers lazily. This module is imported through
# subtitle_core during cache initialization, so eager wildcard imports can
# otherwise miss functions defined later in that cycle.
def record_run_event(event, **payload):
    from twobyteasr.cache import record_run_event as implementation

    return implementation(event, **payload)


def redact_runtime_secrets(value):
    from twobyteasr.cache import redact_runtime_secrets as implementation

    return implementation(value)


def _texts_at(text, boundaries):
    """Display-length boundaries of ``text`` as the pieces a reader sees."""
    pieces, cursor, start = [], 0, 0
    wanted = set(boundaries)
    for index, char in enumerate(text):
        cursor += display_length(char)
        if cursor in wanted:
            pieces.append(text[start:index + 1])
            start = index + 1
            wanted.discard(cursor)
    if start < len(text):
        pieces.append(text[start:])
    return pieces


def _timing_basis(seconds, tokens, edge):
    """'firered' when a measured word edge is within 20 ms, else 'estimate'."""
    key = "start" if edge == "start" else "end"
    return "firered" if any(abs(float(token.get(key, -9)) - float(seconds)) <= .02 for token in tokens or ()) else "estimate"


def run_cached_api_batch(*args, **kwargs):
    from twobyteasr.cache import run_cached_api_batch as implementation

    return implementation(*args, **kwargs)


__all__ = [
    "cues_from_resegmented_texts",
    "fallback_group",
    "call_grouping_api",
    "group_subtitles",
]


GROUPING_OUTPUT_TOKENS = 4096
GROUPING_RETRY_OUTPUT_TOKENS = (8192, 16384)
STRUCTURED_SPLIT_MAX_DEPTH = 3
GROUPING_SCHEMA = {
    'type':'object',
    'properties':{'boundaries':{'type':'array','items':{'type':'integer'}}},
    'required':['boundaries'],
}


def _bind_cue_speakers(cues, segments):
    """Assign by immutable character ownership, never by current global state."""
    spans, cursor = [], 0
    for segment in segments:
        length = display_length(segment.text)
        spans.append((cursor, cursor+length, segment.speaker or 'S00'))
        cursor += length
    cursor = 0
    for cue in cues:
        end = cursor + display_length(cue.text)
        owners = {speaker for left, right, speaker in spans if left < end and cursor < right}
        if len(owners) != 1:
            raise ValueError('断句输出跨过了受保护的说话人边界。')
        cue.speaker = owners.pop()
        cursor = end
    if cursor != sum(display_length(segment.text) for segment in segments):
        raise ValueError('断句输出没有覆盖完整来源范围。')
    return cues


def _restore_grouped_source(segments, cues):
    from .asr_provider_snapshot import restore_source_text
    speakers = {segment.speaker or 'S00' for segment in segments}
    return all(restore_source_text([item for item in segments if (item.speaker or 'S00') == speaker],
        [item for item in cues if (item.speaker or 'S00') == speaker]) for speaker in speakers)


def _validate_grouped_sources(segments, cues):
    from .asr_provider_snapshot import validate_grouped_text
    speakers = {segment.speaker or 'S00' for segment in segments}
    return all(validate_grouped_text([item for item in segments if (item.speaker or 'S00') == speaker],
        [item for item in cues if (item.speaker or 'S00') == speaker]) for speaker in speakers)


def _grouping_dependency_segments(segments):
    rows = serialize_segments(segments)
    # Alignment observations are written during a successful conversion. They
    # must not turn the next identical request into a different child cache key.
    for row in rows:
        if 'caption_arbitration' in row:
            row['caption_arbitration'] = {key:value for key,value in row['caption_arbitration'].items()
                                         if key != 'timing_degradation'}
    return rows


def _clear_short_utterance(batch, firered_tokens=()):
    """A finished one-cue phrase has no decision for a remote segmenter."""
    if len(batch) != 1:
        return False
    item = batch[0]
    text = str(item.text or '').strip()
    from .segmentation import INCOMPLETE_BOUNDARY_SUFFIXES, DANGLING_SHORT_FRAGMENTS
    return bool(0 < display_length(text) <= PROTECTED_SOURCE_SHORT_CHARS
        and 0 < item.end-item.start <= MAX_SUBTITLE_SECONDS
        and not hard_break_character_offsets(batch, firered_tokens)
        and content_only(text) not in DANGLING_SHORT_FRAGMENTS
        and not content_only(text).endswith(INCOMPLETE_BOUNDARY_SUFFIXES)
        and (text.endswith(('。','！','？','!','?')) or
             bool(getattr(item, 'timing_locked', False))))

def cues_from_resegmented_texts(
    segment_batch,
    proposed_texts,
    firered_tokens=(),
    speech_regions=(),
    comfort_max_chars=None,
):
    source_exact = content_exact("".join(segment.text for segment in segment_batch))
    output_exact = content_exact("".join(proposed_texts))
    if output_exact != source_exact:
        raise ValueError("Qwen 重切时改动了原文字、英文大小写或顺序。")

    source_content = content_only("".join(segment.text for segment in segment_batch))
    output_content = content_only("".join(proposed_texts))
    if output_content != source_content:
        raise ValueError("Qwen 重切时改动了原文字或顺序。")

    # Local cohesion/timing repair must see only one protected turn. A shared
    # request may carry alternating speakers, but its character boundaries are
    # projected into each turn before those heuristics can merge a handoff.
    turns = []
    for segment in segment_batch:
        if (not turns or (turns[-1][-1].speaker or 'S00') != (segment.speaker or 'S00')
                or segment.start - turns[-1][-1].end > 2.0):
            turns.append([])
        turns[-1].append(segment)
    if len(turns) > 1:
        boundaries, cursor = set(), 0
        for text in proposed_texts:
            cursor += display_length(text)
            boundaries.add(cursor)
        cues, cursor = [], 0
        for turn in turns:
            length = sum(display_length(item.text) for item in turn)
            relative = sorted(offset - cursor for offset in boundaries
                              if cursor < offset < cursor + length) + [length]
            turn_texts = texts_from_boundary_offsets(turn, relative, firered_tokens)
            cues.extend(cues_from_resegmented_texts(turn, turn_texts, firered_tokens,
                         speech_regions, comfort_max_chars=comfort_max_chars))
            cursor += length
        return cues

    proposed_texts = refine_resegmented_texts(
        segment_batch,
        proposed_texts,
        firered_tokens,
    )

    timeline = []
    for segment in segment_batch:
        timeline.extend(segment_content_timeline(segment, firered_tokens))
    if len(timeline) != len(source_content):
        raise ValueError("校对文字与时间单元数量不一致。")

    hard_offsets = hard_break_character_offsets(segment_batch, firered_tokens)
    real_pause_offsets = set(
        firered_pause_character_gaps(segment_batch, firered_tokens)
    )
    preferred_offsets = (
        source_segment_character_offsets(segment_batch) | real_pause_offsets
    )
    locked_ranges = []
    source_cursor = 0
    for segment in segment_batch:
        segment_length = display_length(segment.text)
        if segment.timing_locked and segment_length > 0:
            locked_ranges.append(
                (source_cursor, source_cursor + segment_length)
            )
        source_cursor += segment_length

    def span_is_timing_locked(span_start, span_end):
        return any(
            locked_start <= span_start and span_end <= locked_end
            for locked_start, locked_end in locked_ranges
        )

    cue_end_offsets = set()
    cues = []
    cursor = 0
    for proposed_text in proposed_texts:
        text = clean_subtitle_text(proposed_text)
        length = display_length(text)
        if not text or length <= 0:
            raise ValueError("Qwen 返回了空字幕。")
        units = timeline[cursor : cursor + length]
        if len(units) != length:
            raise ValueError("Qwen 重切范围超出原文。")
        start = units[0].start
        end = max(units[-1].end, start + MIN_SUBTITLE_SECONDS)

        forced_inside = {
            offset - cursor
            for offset in hard_offsets
            if cursor < offset < cursor + length
        }
        preferred_inside = {
            offset - cursor
            for offset in preferred_offsets
            if cursor < offset < cursor + length
        }
        natural_soft_inside = {
            offset - cursor
            for offset in real_pause_offsets
            if cursor < offset < cursor + length
        }
        natural_soft_inside.update(text_boundary_hints(text))
        natural_soft_inside.update(semantic_restart_boundary_offsets(text))
        repair_reasons = []
        if length > COMPLETE_PHRASE_SOFT_MAX_CHARS:
            repair_reasons.append(f"{length} 字")
        elif comfort_max_chars is not None and length > comfort_max_chars:
            # 仅本地回退路径使用：13-16 字的段重切到舒适长度，防止单行折行。
            repair_reasons.append(f"{length} 字（回退舒适长度）")
        # 10 字只是观看舒适目标，不是本地硬切条件。11-16 字若 Qwen 判断语义
        # 尚未说完就保持完整，避免用均匀字时长伪造断点并造成时间轴漂移。
        if end - start > MAX_SUBTITLE_SECONDS + 0.05:
            repair_reasons.append(f"{end - start:.2f} 秒")
        if forced_inside:
            repair_reasons.append("跨真实长停顿")

        if repair_reasons:
            repaired = locally_repair_resegmented_cue(
                text,
                units,
                forced_boundaries=forced_inside,
                preferred_boundaries=preferred_inside,
                comfort_max_chars=comfort_max_chars,
            )
            summary = "/".join(
                f"{display_length(cue.text)}字 {cue.end - cue.start:.2f}秒"
                for cue in repaired
            )
            print(
                f"   [本地修复] 断句结果单条 {'+'.join(repair_reasons)} -> {summary}"
            )
            cues.extend(repaired)
            running_offset = cursor
            for cue in repaired:
                cue_start_offset = running_offset
                running_offset += display_length(cue.text)
                cue.timing_locked = span_is_timing_locked(
                    cue_start_offset,
                    running_offset,
                )
                cue_end_offsets.add(running_offset)
        else:
            cues.append(
                SubtitleCue(
                    0,
                    start,
                    end,
                    text,
                    timing_locked=span_is_timing_locked(
                        cursor,
                        cursor + length,
                    ),
                )
            )
            cue_end_offsets.add(cursor + length)
        cursor += length

    if cursor != len(timeline):
        raise ValueError("Qwen 重切未覆盖完整原文。")
    # 词中硬边界已在本地修复前贴到词边；这里同步期望的句末偏移。
    hard_offsets = set(
        snap_boundaries_away_from_word_interiors(
            "".join(clean_subtitle_text(segment.text) for segment in segment_batch),
            hard_offsets,
        )
    )
    if hard_offsets and not hard_offsets.issubset(cue_end_offsets | {len(timeline)}):
        # 最后再用相邻字幕兜底修一次；仍缺硬边界时才失败。
        cues = repair_mid_word_adjacent_cues(cues, segment_batch, firered_tokens)
        cue_end_offsets = set()
        running = 0
        for cue in cues:
            running += display_length(cue.text)
            cue_end_offsets.add(running)
    if hard_offsets and not hard_offsets.issubset(cue_end_offsets | {len(timeline)}):
        raise ValueError("Qwen 重切跨过了真实长停顿。")
    cues = _bind_cue_speakers(cues, segment_batch)
    cues = repair_mid_word_adjacent_cues(cues, segment_batch, firered_tokens)
    cues = merge_hanging_attribute_cues(cues)
    return snap_internal_cue_boundaries(
        cues,
        segment_batch,
        firered_tokens,
        speech_regions,
    )


def fallback_group(segment_batch, firered_tokens=(), speech_regions=()):
    # A rejected/unavailable cloud model must not make the local result worse.
    # MOSS already emits phrase-level utterances close to the supplied human
    # manuscript; keep them verbatim whenever they satisfy the real hard limits.
    # 13-16 字的段重切到舒适长度：单行放不下会被播放器折行（2026-09-03 用户反馈）。
    source_cues = [individual_cue(segment) for segment in segment_batch]
    if all(
        display_length(cue.text) <= FALLBACK_COMFORT_MAX_CHARS
        and cue.end - cue.start <= MAX_SUBTITLE_SECONDS + 0.05
        and cue.end > cue.start
        for cue in source_cues
    ):
        return source_cues
    try:
        repaired = cues_from_resegmented_texts(
            segment_batch,
            [segment.text for segment in segment_batch],
            firered_tokens,
            speech_regions,
            comfort_max_chars=FALLBACK_COMFORT_MAX_CHARS,
        )
        if _restore_grouped_source(segment_batch, repaired):
            return repaired
        # Time-sorted local repairs can interleave two overlapping source
        # utterances carrying the same unresolved speaker label. Preserve the
        # original utterances and their real overlap instead of redistributing
        # characters across that handoff or weakening the text validator.
        record_run_event("grouping_local_source_boundary_fallback",
            source_segment_ids=[segment.segment_id for segment in segment_batch],
            reason="source_order_changed_by_local_repair")
        add_review_item(segment_batch[0].start, "重叠来源断句待审",
            "本地重切后来源文字顺序发生穿插；保留本批原语音段完整文字、真实重叠时间和原归属，未重切的长句需人工审核。",
            "".join(segment.text for segment in segment_batch),
            priority=3, severity="warning",
            source_segment_ids=[segment.segment_id for segment in segment_batch],
            grouping_origin="local_source_boundary_fallback")
    except Exception:
        pass
    for cue, segment in zip(source_cues, segment_batch):
        cue.text = segment.text
    return source_cues


def call_grouping_api(
    segment_batch,
    protect_all_source_boundaries=False,
    protected_after_segment_ids=(),
    firered_tokens=(),
    speech_regions=(),
    abort_event=None,
    batch_index=None,
    batch_total=None,
    _split_depth=0,
    provider_snapshot=None,
    batch_diagnostics=None,
    _retry_budget=None,
    _messages_only=False,
    _packed=False,
    _cache_context=None,
    _read_only_context=None,
):
    from .provider_input_budget import RetryBudget
    _retry_budget=_retry_budget if _retry_budget is not None else RetryBudget(GROUPING_API_RETRIES-1)
    from .asr_provider_snapshot import (
        task_provider_snapshot, request_record, classify_request_error,
        GroupedBatchResult, validate_grouped_text, restore_source_text,
    )
    from .ai_providers import AIProviderError
    snapshot = provider_snapshot or task_provider_snapshot("group")
    rejected = (_retry_budget.snapshot_rejection('grouped', snapshot.fingerprint)
        if not _messages_only else None)
    if rejected:
        if batch_diagnostics is not None:
            batch_diagnostics['fallback_reason'] = rejected[0]
        record_run_event('grouping_api_fallback', batch_index=batch_index,
            category=rejected[0], error=rejected[1], request_dispatched=False)
        result = fallback_group(segment_batch, firered_tokens, speech_regions)
        if not _restore_grouped_source(segment_batch, result):
            result = [individual_cue(segment) for segment in segment_batch]
            for cue, segment in zip(result, segment_batch):
                cue.text = segment.text
        return GroupedBatchResult(result, origin='fallback', validated=False)
    if abort_event is not None and abort_event.is_set():
        add_review_item(
            segment_batch[0].start,
            "断句回退",
            "云端断句模型已在前一批次被服务端拒绝，本批保留 MOSS 原始自然语句边界",
            segment_batch[0].text,
            priority=3,
            severity="warning",
            batch_index=batch_index,
            batch_total=batch_total,
        )
        return fallback_group(segment_batch, firered_tokens, speech_regions)

    hard_break_offsets = sorted(
        hard_break_character_offsets(segment_batch, firered_tokens)
    )
    source_text = "".join(segment.text for segment in segment_batch)
    total_length = display_length(source_text)
    segment_payload = []
    content_cursor = 0
    for segment in segment_batch:
        length = display_length(segment.text)
        segment_payload.append(
            {
                "id": segment.segment_id,
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "content_start": content_cursor,
                "content_end": content_cursor + length,
                "text": segment.text,
                "speaker": segment.speaker or 'S00',
            }
        )
        content_cursor += length

    source_boundary_offsets = sorted(source_segment_character_offsets(segment_batch))
    protected_source_offsets = set(
        source_segment_character_offsets(segment_batch)
        if protect_all_source_boundaries
        else protected_source_boundary_offsets(segment_batch)
    )
    protected_ids = set(protected_after_segment_ids)
    protected_ids.update(left.segment_id for left, right in zip(segment_batch, segment_batch[1:])
        if (left.speaker or 'S00') != (right.speaker or 'S00') or right.start-left.end > 2.)
    running_offset = 0
    for segment in segment_batch[:-1]:
        running_offset += display_length(segment.text)
        if segment.segment_id in protected_ids:
            protected_source_offsets.add(running_offset)
    protected_source_offsets = sorted(protected_source_offsets)
    pause_hints = [
        {"offset": offset, "gap_ms": int(round(gap * 1000))}
        for offset, gap in sorted(
            firered_pause_character_gaps(segment_batch, firered_tokens).items()
        )
    ]
    source_gap_hints = []
    running_offset = 0
    for segment, following in zip(segment_batch, segment_batch[1:]):
        running_offset += display_length(segment.text)
        gap = following.start - segment.end
        if gap >= 0.12:
            source_gap_hints.append(
                {"offset": running_offset, "gap_ms": int(round(gap * 1000))}
            )
    from .grouping_request import GROUPING_PROMPT_VERSION, grouping_system_prompt
    from .content_scene import runtime_content_scene
    scene = runtime_content_scene()
    prompt = grouping_system_prompt(MAX_SUBTITLE_CHARS, MAX_SUBTITLE_SECONDS)
    request_body = {
        "prompt_version": GROUPING_PROMPT_VERSION,
        "content_scene": scene.to_dict(),
        "total_length": total_length,
        "source_text": source_text,
        "indexed_content": indexed_content_for_prompt(source_text),
        "hard_break_character_offsets": hard_break_offsets,
        "source_segment_offsets": source_boundary_offsets,
        "protected_source_offsets": protected_source_offsets,
        "pause_hints": pause_hints,
        "source_gap_hints": source_gap_hints,
        "segments": segment_payload,
        "read_only_context": _read_only_context or {},
    }
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(request_body, ensure_ascii=False, separators=(',', ':'))},
    ]
    if _messages_only:
        return messages

    def run_child(child, child_id):
        def execute():
            return call_grouping_api(child,
                protect_all_source_boundaries=protect_all_source_boundaries,
                protected_after_segment_ids=protected_after_segment_ids,
                firered_tokens=firered_tokens,speech_regions=speech_regions,
                abort_event=abort_event,batch_index=child_id,batch_total=batch_total,
                _split_depth=_split_depth+1,provider_snapshot=snapshot,
                batch_diagnostics=batch_diagnostics,_retry_budget=_retry_budget,
                _cache_context=_cache_context)
        if _cache_context is None:
            return execute()
        return run_cached_api_batch('grouped',_cache_context,
            {'protocol':'speaker-labelled-protected-boundaries-v2-packed','segments':_grouping_dependency_segments(child),
             'messages':build_messages(child)},execute,
            encoder=serialize_cues,decoder=deserialize_cues,
            fallback_categories=('断句回退',),provider_snapshot=snapshot,
            validator=lambda values:_validate_grouped_sources(child,values))

    def build_messages(child):
        return call_grouping_api(child,
            protect_all_source_boundaries=protect_all_source_boundaries,
            protected_after_segment_ids=protected_after_segment_ids,
            firered_tokens=firered_tokens,speech_regions=speech_regions,
            provider_snapshot=snapshot,_messages_only=True,_retry_budget=_retry_budget)

    if not _packed:
        from .provider_input_budget import pack_items
        packed,rejected=pack_items(segment_batch,build_messages,
            operation='group',max_tokens=GROUPING_OUTPUT_TOKENS,schema=GROUPING_SCHEMA)
        if rejected or len(packed)>1:
            rejected_ids={item.segment_id for item,_ in rejected}
            by_first={batch[0].segment_id:batch for batch in packed}
            combined=[]
            all_validated=not rejected
            child_count=0
            for item in segment_batch:
                if item.segment_id in rejected_ids:
                    add_review_item(item.start,'断句回退','单条完整字幕超过模型预算，仅此条使用本地断句。',
                        item.text,priority=3,severity='warning',batch_index=batch_index,batch_total=batch_total)
                    record_run_event('grouping_api_fallback',batch_index=batch_index,
                        category='request_too_large',source_ids=[item.segment_id],failure_stage='local_budget')
                    combined.extend(fallback_group([item],firered_tokens,speech_regions))
                elif item.segment_id in by_first:
                    child_count+=1
                    child_result=run_child(by_first[item.segment_id],f'{batch_index}.{child_count}')
                    all_validated=all_validated and bool(getattr(child_result,'validated',False))
                    combined.extend(child_result)
            if not _restore_grouped_source(segment_batch,combined):
                raise ValueError('分批断句未保持完整正文与顺序。')
            return GroupedBatchResult(combined,validated=all_validated,origin='ai' if all_validated else 'fallback')
    group_settings = snapshot.endpoint()
    provider = provider_for_stage(snapshot.execution_settings(), "group", sender=post_chat_completion)
    print(
        f"   [断句] {snapshot.provider}/{snapshot.model} · {snapshot.transport}（数字 boundaries，原文不可变）"
    )
    last_error = None
    last_category = "request_error"
    working_messages = list(messages)
    for attempt in range(1, GROUPING_API_RETRIES + 1):
        content = ""
        diag = request_record(snapshot, stage="grouped", batch_id=batch_index,
            speaker=segment_batch[0].speaker or "S00", attempt=attempt,
            cache_key=(batch_diagnostics or {}).get("cache_key", ""), input_characters=len(source_text))
        diag.update(prompt_version=GROUPING_PROMPT_VERSION, content_scene=scene.to_dict(),
            prompt_characters=sum(len(item["content"]) for item in working_messages))
        if batch_diagnostics:
            diag["scheduler_queue_wait_ms"] = batch_diagnostics.get("scheduler_queue_wait_ms", 0)
        attempt_started = time.perf_counter()
        try:
            _retry_budget.raise_if_rejected('grouped', snapshot.fingerprint)
            content = provider.complete(
                working_messages,
                stage="grouped",
                operation_kind='group',
                batch_index=batch_index,
                max_tokens=GROUPING_OUTPUT_TOKENS,
                temperature=0.0,
                timeout=snapshot.timeout_policy.total,
                _timeout_policy=snapshot.timeout_policy,
                request_diagnostics=diag,
                _task_failure_scope=(_retry_budget, 'grouped', snapshot.fingerprint),
                cancel_check=lambda: bool(abort_event is not None and abort_event.is_set()) or bool(
                    getattr(get_runtime_context().cancellation_token, "is_cancelled", False)),
                enable_thinking=False,
                response_format={"type": "json_object"},
                structured_retry_system_prompt=(
                    '直接输出最终合法 JSON 对象，禁止分析或解释。严格 schema：'
                    '{"boundaries":[8,17,24]}。数组只能包含严格递增整数，'
                    '最后一个整数必须等于 user 数据中的 total_length。'
                ),
                structured_retry_max_tokens=GROUPING_RETRY_OUTPUT_TOKENS,
                json_schema=GROUPING_SCHEMA,
            )
            diag["raw_response_length"] = len(content)
            if not str(content).strip():
                raise AIProviderError("断句正文为空。", category="empty_response")
            try:
                returned = parse_qwen_object(content)
            except (ValueError, TypeError) as exc:
                raise AIProviderError("断句JSON无法解析。", category="parse_failure") from exc
            boundary_offsets = returned.get("boundaries")
            segmented_text = returned.get("segmented_text")
            if isinstance(segmented_text, str) and segmented_text.strip():
                proposed_texts = segmented_text.split("|")
                if not proposed_texts or any(not part for part in proposed_texts):
                    raise ValueError("模型 segmented_text 含有空字幕。")
                if "".join(proposed_texts) == source_text:
                    # 逐字一致时，带竖线的正文最能反映模型的自然语义判断；
                    # 本地只把竖线换算为数字断点，实际正文仍从 source_text 切片。
                    boundary_offsets = []
                    running_offset = 0
                    for text in proposed_texts:
                        running_offset += display_length(text)
                        boundary_offsets.append(running_offset)
                else:
                    raise AIProviderError("模型改动了原文。", category="text_mutation_rejected")
            elif not isinstance(boundary_offsets, list):
                raise ValueError("模型 JSON 中缺少 boundaries 数组。")
            if not isinstance(boundary_offsets, list) or not boundary_offsets:
                raise ValueError("模型 JSON 中缺少非空 boundaries 数组。")
            if any(
                isinstance(offset, bool)
                or not isinstance(offset, (int, float))
                or int(offset) != offset
                for offset in boundary_offsets
            ):
                raise ValueError("模型 boundaries 必须全部是整数。")
            boundary_offsets = [int(offset) for offset in boundary_offsets]
            model_boundaries = list(boundary_offsets)
            if (
                boundary_offsets != sorted(set(boundary_offsets))
                or boundary_offsets[0] <= 0
                or boundary_offsets[-1] != total_length
            ):
                raise ValueError(
                    "模型 boundaries 必须严格递增、均为正数，且最后一项等于 total_length。"
                )
            boundary_offsets = repair_lexical_boundary_offsets(
                segment_batch,
                boundary_offsets,
                firered_tokens,
            )
            boundary_offsets = repair_segmenter_word_boundary_offsets(
                segment_batch,
                boundary_offsets,
                firered_tokens,
            )
            boundary_offsets = repair_incomplete_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            boundary_offsets = repair_latin_predicate_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            boundary_offsets = repair_dependent_particle_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            boundary_offsets = repair_hanging_attribute_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            missing_required = sorted(
                (set(hard_break_offsets) | set(protected_source_offsets))
                - set(boundary_offsets)
            )
            if missing_required:
                # 这些边界来自真实停顿或另一位主播的插话。模型只负责语义断句，
                # 漏报时由本地精确补回即可；不能因此丢掉整批其余自然断句。
                boundary_offsets = sorted(
                    set(boundary_offsets) | set(missing_required)
                )
                print(
                    "   [边界保护] 本地补回模型漏报的 "
                    f"{len(missing_required)} 个说话人/停顿边界。"
                )
            before_validate = list(boundary_offsets)
            if SECOND_PASS_GROUP_VALIDATION:
                boundary_offsets = validate_grouping_boundaries_with_llm(
                    segment_batch,
                    boundary_offsets,
                    firered_tokens=firered_tokens,
                    provider_snapshot=snapshot,
                    batch_diagnostics=diag,
                )
            boundary_offsets = repair_lexical_boundary_offsets(
                segment_batch,
                boundary_offsets,
                firered_tokens,
            )
            boundary_offsets = repair_segmenter_word_boundary_offsets(
                segment_batch,
                boundary_offsets,
                firered_tokens,
            )
            boundary_offsets = repair_dependent_particle_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            boundary_offsets = repair_hanging_attribute_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            boundary_offsets = sorted(
                set(boundary_offsets) | set(hard_break_offsets) | set(protected_source_offsets)
            )
            # hard/protected 并入后可能重新落入词中，再护栏一次。
            boundary_offsets = repair_segmenter_word_boundary_offsets(
                segment_batch,
                boundary_offsets,
                firered_tokens,
            )
            boundary_offsets = sorted(
                set(
                    snap_boundaries_away_from_word_interiors(
                        source_text,
                        boundary_offsets,
                        blocked=set(protected_source_offsets),
                    )
                )
                | set(
                    snap_boundaries_away_from_word_interiors(
                        source_text,
                        hard_break_offsets,
                    )
                )
                | set(protected_source_offsets)
            )
            boundary_offsets = repair_incomplete_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            boundary_offsets = repair_compact_utterance_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            boundary_offsets = repair_dependent_prefix_boundary_offsets(
                segment_batch,
                boundary_offsets,
                protected_offsets=(
                    set(hard_break_offsets) | set(protected_source_offsets)
                ),
                firered_tokens=firered_tokens,
            )
            boundary_offsets = repair_segmenter_word_boundary_offsets(
                segment_batch,
                boundary_offsets,
                firered_tokens,
            )
            if boundary_offsets and boundary_offsets[-1] != total_length:
                boundary_offsets = [offset for offset in boundary_offsets if 0 < offset < total_length] + [
                    total_length
                ]
            if before_validate != boundary_offsets:
                print("   [断句校验] 已应用云端模型竖线校正与本地护栏。")
            proposed_texts = texts_from_boundary_offsets(
                segment_batch,
                boundary_offsets,
                firered_tokens,
            )
            result = cues_from_resegmented_texts(
                segment_batch,
                proposed_texts,
                firered_tokens,
                speech_regions,
            )
            if not _restore_grouped_source(segment_batch, result):
                raise AIProviderError("断句结果未通过逐字符原文校验。", category="text_mutation_rejected")
            diag.update(boundary_count=len(boundary_offsets), validator_result="exact_text_and_boundaries",
                        total_duration_ms=round((time.perf_counter()-attempt_started)*1000, 3), result_origin="ai")
            # 2026-10-10: keep the model's own answer next to what local
            # repair and timing made of it (input -> response -> result).
            record_run_event("grouping_trace", batch_index=batch_index, attempt=attempt,
                source_segment_ids=[segment.segment_id for segment in segment_batch],
                source_text=source_text, hard_break_offsets=hard_break_offsets,
                protected_source_offsets=protected_source_offsets,
                model_boundaries=model_boundaries, model_texts=_texts_at(source_text, model_boundaries),
                final_boundaries=list(boundary_offsets), final_texts=_texts_at(source_text, boundary_offsets),
                cues=[{"text": cue.text, "start": round(cue.start, 3), "end": round(cue.end, 3),
                       "speaker": cue.speaker, "start_basis": _timing_basis(cue.start, firered_tokens, "start"),
                       "end_basis": _timing_basis(cue.end, firered_tokens, "end")} for cue in result])
            if batch_diagnostics is not None:
                batch_diagnostics["fallback_reason"] = None
            record_run_event("asr_provider_request", **diag)
            return GroupedBatchResult(result, validated=True)
        except Exception as exc:
            last_error = exc
            last_category = classify_request_error(exc)
            _retry_budget.reject_snapshot('grouped', snapshot.fingerprint, exc)
            if last_category == "upgrade_required":
                if abort_event is not None:
                    abort_event.set()
                record_run_event("text_ai_terminal_failure", stage="grouped",
                    category=last_category, error=redact_runtime_secrets(exc))
                raise
            if batch_diagnostics is not None:
                batch_diagnostics["fallback_reason"] = last_category
            diag.update(validator_result=last_category if content else "not_run",
                        fallback_reason=last_category, result_origin="failed_attempt",
                        total_duration_ms=round((time.perf_counter()-attempt_started)*1000, 3))
            record_run_event("asr_provider_request", **diag)
            if last_category == "cancelled":
                from .service import CancelledError
                raise CancelledError("断句任务已取消。") from exc
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code in {400, 401, 403, 404}:
                if abort_event is not None:
                    abort_event.set()
                print(
                    f"   [警告] 云端断句配置被服务端拒绝（HTTP {status_code}），"
                    "立即保留本地自然语句边界，不再重复请求。"
                )
                break
            if last_category in {
                "structured_empty_response",
                "structured_output_truncated",
                "structured_output_truncated_before_answer",
            }:
                break
            from .provider_input_budget import retry_delay, wait_retry
            delay=retry_delay(exc,attempt)
            if delay is None:
                break
            if attempt < GROUPING_API_RETRIES:
                if not _retry_budget.take():
                    break
                if content:
                    working_messages = messages + [
                        {
                            "role": "user",
                            "content": (
                                f"上一次结果未通过本地校验：{exc}。"
                                "请只修正这个问题，重新返回完整 JSON。"
                            ),
                        },
                    ]
                record_run_event(
                    "llm_request_retry",
                    stage="grouped",
                    batch_index=batch_index,
                    batch_total=batch_total,
                    attempt=attempt + 1,
                    category=last_category,
                )
                print(
                    f"   [重试] 断句建议暂未成功，{delay} 秒后重试（{attempt}/{GROUPING_API_RETRIES}）"
                )
                if not wait_retry(delay,lambda: bool(getattr(get_runtime_context().cancellation_token,'is_cancelled',False))):
                    from .service import CancelledError
                    raise CancelledError('断句任务已取消。')

    if (
        last_category in {
            "structured_output_truncated",
            "structured_output_truncated_before_answer",
            "request_too_large", "payload_too_large", "transport_length",
        }
        and len(segment_batch) > 1
        and _split_depth < STRUCTURED_SPLIT_MAX_DEPTH
    ):
        midpoint = len(segment_batch) // 2
        record_run_event(
            "llm_structured_batch_split",
            stage="grouped",
            batch_index=batch_index,
            batch_total=batch_total,
            split_depth=_split_depth + 1,
            source_cue_count=len(segment_batch),
            child_cue_counts=[midpoint, len(segment_batch) - midpoint],
            category=last_category,
        )
        child_cues = []
        all_validated=True
        for part,child in enumerate((segment_batch[:midpoint],segment_batch[midpoint:]),1):
            child_result=run_child(child,f'{batch_index}.{part}')
            all_validated=all_validated and bool(getattr(child_result,'validated',False))
            child_cues.extend(child_result)
        return GroupedBatchResult(child_cues,validated=all_validated,origin='ai' if all_validated else 'fallback')

    print(f"   [警告] 断句连续失败，当前批次使用本地均衡分段：{last_error}")
    record_run_event(
        "grouping_api_fallback",
        segment_start=round(float(segment_batch[0].start), 3),
        segment_end=round(float(segment_batch[-1].end), 3),
        batch_index=batch_index,
        batch_total=batch_total,
        category=last_category,
        error=redact_runtime_secrets(last_error),
    )
    add_review_item(
        segment_batch[0].start,
        "断句回退",
        f"断句失败，已使用本地均衡分段：{str(last_error)[:120]}",
        segment_batch[0].text,
        priority=3,
        severity="warning",
        batch_index=batch_index,
        batch_total=batch_total,
    )
    result = fallback_group(segment_batch, firered_tokens, speech_regions)
    if not _restore_grouped_source(segment_batch, result):
        result = [individual_cue(segment) for segment in segment_batch]
        for cue, segment in zip(result, segment_batch):
            cue.text = segment.text
    return GroupedBatchResult(result, origin="fallback")


def group_subtitles(
    segments,
    firered_tokens=(),
    speech_regions=(),
    protect_all_source_boundaries=False,
    cache_context=None,
    use_ai=True,
    provider_snapshot=None,
    max_workers=None,
):
    from .asr_provider_snapshot import task_provider_snapshot, digest, GroupedBatchResult, validate_grouped_text, restore_source_text
    use_ai = bool(use_ai)
    snapshot = (provider_snapshot or task_provider_snapshot("group")) if use_ai else None
    if use_ai:
        print(
            "   云端模型阅读全稿并选择同一说话人内部的语义断点，"
            "不修改任何字幕文字..."
        )
    else:
        from .language_rules import is_japanese
        print(
            "   [本地断句] 已关闭 AI 断句；使用 MOSS 自然语句、日语文节与对齐停顿。" if is_japanese() else
            "   [本地断句] 已关闭 AI 断句；使用 MOSS 自然语句、FireRed 停顿与本地护栏。"
        )
    cues = []
    ordered_segments = sorted(
        segments,
        key=lambda item: (item.start, item.end, item.segment_id),
    )
    global_position = {
        segment.segment_id: index for index, segment in enumerate(ordered_segments)
    }
    speaker_groups = {}
    for segment in ordered_segments:
        speaker = segment.speaker or "S00"
        speaker_groups.setdefault(speaker, []).append(segment)
    interrupted_after = set()
    for speaker, speaker_segments in speaker_groups.items():
        for left, right in zip(speaker_segments, speaker_segments[1:]):
            left_index = global_position[left.segment_id]
            right_index = global_position[right.segment_id]
            if any(
                (middle.speaker or "S00") != speaker
                for middle in ordered_segments[left_index + 1 : right_index]
            ):
                interrupted_after.add(left.segment_id)
    from .grouping_request import grouping_batch_limits, GROUPING_PROMPT_VERSION
    max_rows, max_chars, batch_policy = grouping_batch_limits(ordered_segments,
        max_chars=GROUP_API_BATCH_MAX_CHARS, legacy_max_rows=GROUP_API_BATCH_MAX_CUES)
    batches = []
    turns = []
    for segment in ordered_segments:
        if (not turns or turns[-1][-1].speaker != segment.speaker
                or segment.start - turns[-1][-1].end > 2.0):
            turns.append([])
        turns[-1].append(segment)
    # Protected turns are data constraints, not one CLI process per switch.
    # A complete-ID batch contains labelled segments and mandatory boundaries.
    # Only explicit finished short turns use the deterministic local path.
    remote_rows = []
    for turn in turns:
        if use_ai and _clear_short_utterance(turn, firered_tokens):
            if remote_rows:
                batches.extend(('mixed', part, False) for part in split_items_for_api(remote_rows,
                    max_cues=max_rows,max_chars=max_chars))
                remote_rows = []
            batches.append((turn[0].speaker or 'S00', turn, True))
        else:
            remote_rows.extend(turn)
    if remote_rows:
        batches.extend(('mixed', part, False) for part in split_items_for_api(remote_rows,
            max_cues=max_rows,max_chars=max_chars))
    jobs = []
    grouping_abort_event = threading.Event()
    from .provider_input_budget import RetryBudget
    retry_budget=RetryBudget(GROUPING_API_RETRIES-1)
    for index, (speaker, batch, local_fast) in enumerate(batches, 1):
        # Alignment diagnostics are observations, not semantic cache inputs.
        # The first unaligned run may add one without changing text or timing.
        serialized_batch = _grouping_dependency_segments(batch)
        dependency = {
            "use_ai": use_ai,
            "batch_protocol": GROUPING_PROMPT_VERSION,
            "batch_policy": batch_policy,
            "local_fast": local_fast,
            "speaker": speaker,
            "batch": serialized_batch,
            "protect_all": bool(protect_all_source_boundaries),
            "protected_after": sorted(interrupted_after),
            "firered_tokens": firered_tokens,
            "speech_regions": speech_regions,
            "input_content_hash": digest([item.text for item in batch]),
            "boundaries_hash": digest({"protect_all": bool(protect_all_source_boundaries),
                                       "protected_after": sorted(interrupted_after),
                                       "source_boundaries": sorted(source_segment_character_offsets(batch))}),
        }
        jobs.append((index, speaker, batch, dependency, local_fast))

    def run_job(job):
        index, speaker, batch, dependency, local_fast = job
        print(f"   断句批次 {index}/{len(batches)}，说话人 {speaker}")
        started_at = time.perf_counter()
        batch_diag = {"scheduler_queue_wait_ms": round((started_at-dispatched_at)*1000, 3),
                      'scheduler_submitted_monotonic': dispatched_at,
                      'scheduler_started_monotonic': started_at}

        def run_group_batch():
            if local_fast:
                result = fallback_group(batch, firered_tokens, speech_regions)
                _bind_cue_speakers(result, batch)
                if not _restore_grouped_source(batch, result):
                    raise ValueError('本地断句未保持来源正文。')
                record_run_event('grouping_local_fast_path', source_ids=[x.segment_id for x in batch],
                    reason='finished_short_protected_utterance', input_characters=sum(display_length(x.text) for x in batch))
                return GroupedBatchResult(result, origin='local_fast', validated=True)
            if not use_ai:
                result = fallback_group(batch, firered_tokens, speech_regions)
                if not _restore_grouped_source(batch, result):
                    raise ValueError('本地断句未保持来源正文。')
                return result
            first = global_position[batch[0].segment_id]
            last = global_position[batch[-1].segment_id]
            context = {key:[{'id':x.segment_id,'speaker':x.speaker,'text':x.text,'read_only':True} for x in values]
                for key,values in [('before',ordered_segments[max(0,first-2):first]),
                                   ('after',ordered_segments[last+1:last+3])]}
            return call_grouping_api(
                batch,
                protect_all_source_boundaries=protect_all_source_boundaries,
                protected_after_segment_ids=interrupted_after,
                firered_tokens=firered_tokens,
                speech_regions=speech_regions,
                abort_event=grouping_abort_event,
                batch_index=index,
                batch_total=len(batches),
                provider_snapshot=snapshot,
                batch_diagnostics=batch_diag,
                _retry_budget=retry_budget,
                _cache_context=cache_context,
                _read_only_context=context,
            )
        with capture_review_items() as review_items:
            if cache_context is not None:
                batch_cues = run_cached_api_batch(
                    "grouped" if use_ai and not local_fast else "grouped_local",
                    cache_context,
                    dependency,
                    run_group_batch,
                    encoder=serialize_cues,
                    decoder=(lambda values: GroupedBatchResult(deserialize_cues(values), origin='local_fast', validated=True)) if local_fast else deserialize_cues,
                    fallback_categories=("断句回退",),
                    provider_snapshot=snapshot,
                    validator=lambda values: _validate_grouped_sources(batch, values),
                    diagnostics=batch_diag,
                )
            else:
                batch_cues = run_group_batch()
        if not _validate_grouped_sources(batch, batch_cues):
            raise ValueError('断句批次未保持每个说话人的完整来源正文。')
        elapsed_seconds = time.perf_counter() - started_at
        record_run_event(
            "cloud_batch_completed",
            stage="grouped" if use_ai else "grouped_local",
            job_id=get_runtime_context().job_id,
            batch_index=index,
            batch_total=len(batches),
            cue_count=len(batch),
            elapsed_seconds=round(elapsed_seconds, 3),
            provider_snapshot_fingerprint=snapshot.fingerprint if snapshot else "",
            resolved_provider=snapshot.provider if snapshot else "local", model=snapshot.model if snapshot else "local_rules",
            transport=snapshot.transport if snapshot else "none", protocol=snapshot.protocol if snapshot else "none",
            endpoint_identity=snapshot.endpoint_identity if snapshot else "",
            cache_key=batch_diag.get("cache_key", ""), cache_hit=batch_diag.get("cache_hit", False),
            result_origin=getattr(batch_cues, "origin", "local" if not use_ai else "fallback"),
            fallback_reason=batch_diag.get("fallback_reason"),
            scheduler_queue_wait_ms=batch_diag.get('scheduler_queue_wait_ms'),
            scheduler_submitted_monotonic=dispatched_at,
            scheduler_started_monotonic=started_at,
            scheduler_finished_monotonic=time.perf_counter(),
            validator_result="exact_text_and_boundaries" if getattr(batch_cues, "validated", False) else "not_validated_ai",
        )
        return index, batch_cues, review_items

    results = {}
    workers = (
        min(CLOUD_BATCH_WORKERS, len(jobs))
        if use_ai and PARALLEL_CLOUD_BATCHES
        else 1
    )
    from .provider_service import GLOBAL_PROVIDER_SERVICE
    capacity = GLOBAL_PROVIDER_SERVICE.scheduling_capacity() if use_ai else {"effective_workers": 1}
    configured_workers = workers
    workers = max(1, min(workers, capacity["effective_workers"]))
    if max_workers is not None:
        workers = max(1, min(workers, int(max_workers)))
    record_run_event("grouping_batch_plan", prompt_version=GROUPING_PROMPT_VERSION,
        batch_policy=batch_policy, max_rows=max_rows, max_characters=max_chars,
        batch_count=len(jobs), configured_workers=configured_workers,
        scheduler_workers=workers, provider_capacity=capacity)

    dispatched_at = time.perf_counter()
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"   [并行加速] {len(jobs)} 个断句批次，最多 {workers} 路并发。")
        record_run_event(
            "cloud_batches_parallel",
            stage="grouped",
            batches=len(jobs),
            workers=workers,
        )
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="glm-group") as pool:
            futures = {pool.submit(run_job, job): job[0] for job in jobs}
            for future in as_completed(futures):
                index, batch_cues, review_items = future.result()
                results[index] = batch_cues
                extend_review_items(review_items)
    else:
        for job in jobs:
            index, batch_cues, review_items = run_job(job)
            results[index] = batch_cues
            extend_review_items(review_items)
    for index in sorted(results):
        cues.extend(results[index])
    cues = merge_same_speaker_dangling_cues(cues)
    cues = merge_isolated_two_character_cues(cues)
    cues = repair_mid_word_adjacent_cues(cues, ordered_segments, firered_tokens)
    cues = merge_hanging_attribute_cues(cues)
    for speaker, source_rows in speaker_groups.items():
        output_rows = [cue for cue in cues if (cue.speaker or "S00") == speaker]
        if not restore_source_text(source_rows, output_rows):
            raise ValueError("Stage 9后处理违反原文逐字符守恒；停止返回错误字幕。")
    cues.sort(key=lambda cue: (cue.start, cue.end, cue.speaker))
    for cue_id, cue in enumerate(cues, 1):
        cue.cue_id = cue_id
    origins = {getattr(value, 'origin', 'fallback') for value in results.values()}
    all_validated = bool(use_ai) and all(getattr(value, 'validated', False) for value in results.values())
    origin = 'ai' if all_validated and origins <= {'ai'} else 'local_fast' if all_validated and origins <= {'local_fast'} else 'mixed' if all_validated else 'fallback' if use_ai else 'local'
    record_run_event('cloud_batches_completed', stage='grouped' if use_ai else 'grouped_local',
        job_id=get_runtime_context().job_id, started_monotonic=dispatched_at,
        finished_monotonic=time.perf_counter(), elapsed_seconds=round(time.perf_counter()-dispatched_at,3),
        scheduler_workers=workers, configured_workers=configured_workers,
        provider_capacity=capacity, batch_policy=batch_policy, prompt_version=GROUPING_PROMPT_VERSION,
        batch_count=len(jobs), remote_batch_count=sum(not job[-1] for job in jobs) if use_ai else 0,
        local_fast_batch_count=sum(bool(job[-1]) for job in jobs), protected_turn_count=len(turns),
        result_origin=origin)
    return GroupedBatchResult(cues, origin=origin, validated=all_validated)
