"""Cloud grouping request/response handling and subtitle grouping orchestration."""

import copy
from functools import wraps
from itertools import accumulate
from .grouping_quality import enabled as _quality_enabled, quality_for_segments, cues_from_quality, SourceIndex, QUALITY_VERSION
from .grouping_quality_request import QualityRetryBudget, retry_quality_windows
import hashlib
import json
import threading
import time

from twobyteasr.providers.ai_providers import provider_for_stage

from subtitle_core import *  # noqa: F401,F403
from .segmentation_profiles import current_profile as _current_language_profile
from twobyteasr.subtitle_rules.segmentation import (
    firered_pause_character_gaps,
    hard_break_character_offsets,
    indexed_content_for_prompt,
    individual_cue,
    locally_repair_resegmented_cue,
    merge_hanging_attribute_cues,
    merge_isolated_two_character_cues,
    merge_same_speaker_dangling_cues,
    missing_hard_break_offsets,
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
    with_mandatory_breaks,
    japanese_break_candidates,
    marked_break_text,
    snap_to_break_candidates,
)


# Resolve cache-backed helpers lazily. This module is imported through
# subtitle_core during cache initialization, so eager wildcard imports can
# otherwise miss functions defined later in that cycle.
_batch_trace = threading.local()
JAPANESE_BATCH_MAX_CHARS = 900

def record_run_event(event, **payload):
    from twobyteasr.recognition.cache import record_run_event as implementation

    payload.setdefault("batch_id", payload.get("batch_index", getattr(_batch_trace, "batch_id", None)))
    return implementation(event, **payload)


def redact_runtime_secrets(value):
    from twobyteasr.recognition.cache import redact_runtime_secrets as implementation

    return implementation(value)


def _source_bound_candidate(function):
    """Work privately, then reject a stale/cancelled source before any return."""
    @wraps(function)
    def bound(segments, *args, **kwargs):
        if kwargs.get("_messages_only"):
            return function(segments, *args, **kwargs)
        from .grouping_contract import capture_grouping_source, validate_grouping_result, runtime_task_binding
        from ..recognition.service import CancelledError
        from .cue_cleanup import prepare_effective_sources
        original = prepare_effective_sources(segments, speech_regions=kwargs.get('speech_regions'))
        owner = get_runtime_context()
        task_binding = runtime_task_binding(owner)
        source = capture_grouping_source(original, job_id=owner.job_id,
                                         batch_id=kwargs.get("batch_index", ""))
        if bool(getattr(owner.cancellation_token, "is_cancelled", False)):
            raise CancelledError("断句任务已取消；不提交候选。")
        # Timing/cohesion helpers historically annotate source arbitration.
        # They now only annotate this private candidate, never live input.
        result = function(copy.deepcopy(original), *args, **kwargs)
        if (get_runtime_context() is not owner or runtime_task_binding(owner) != task_binding
                or bool(getattr(owner.cancellation_token, "is_cancelled", False))):
            raise CancelledError("断句任务已取消或替换；不提交迟到候选。")
        source.require_current(original)
        validate_grouping_result(source, result, minimum_seconds=MIN_SUBTITLE_SECONDS,
            protect_all_source_boundaries=bool(kwargs.get("protect_all_source_boundaries", False)),
            protected_after_source_ids=kwargs.get("protected_after_segment_ids", ()))
        from ..providers.asr_provider_snapshot import GroupedBatchResult
        if not isinstance(result, GroupedBatchResult):
            result = GroupedBatchResult(result, origin="local")
        result.data_validated = True
        result.source_fingerprint = source.fingerprint
        return result
    @wraps(bound)
    def correlated(*args, **kwargs):
        previous = getattr(_batch_trace, "batch_id", None)
        _batch_trace.batch_id = kwargs.get("batch_index", previous)
        try:return bound(*args, **kwargs)
        finally:_batch_trace.batch_id = previous
    return correlated


def _texts_at(text, boundaries):
    """Display-length boundaries of ``text`` as the pieces a reader sees."""
    return SourceIndex.build(text).pieces(boundaries)


def _retain_grouping_range(rows, error, batch_id=None):
    """A data rejection preserves exactly this range at source boundaries."""
    from .grouping_contract import attach_grouping_spans, GroupingContractError
    from ..providers.asr_provider_snapshot import GroupedBatchResult
    message = redact_runtime_secrets(error)
    ids = [row.segment_id for row in rows]
    category = getattr(error, 'category', 'grouping_range_error')
    receipt = dict(batch_id=batch_id, source_segment_ids=ids, category=category,
                   reason=message, requires_review=True)
    cues = [SubtitleCue(index, row.start, row.end, row.text,
                        row.timing_locked, row.speaker or 'S00')
            for index, row in enumerate(rows, 1)]
    split = _locally_split_retained_japanese(rows, cues)
    try:
        if split is None:
            raise GroupingContractError('no local split')
        cues = attach_grouping_spans(rows, split)
    except GroupingContractError as split_error:
        # 2026-11-26: the fallback itself must not fail the task. When the
        # local split does not pass the source contract, the source lines are
        # kept exactly as they are (each one is its own valid cue).
        if split is not None:
            record_run_event('grouping_retained_range_split_dropped', batch_index=batch_id,
                             source_segment_ids=ids, category=getattr(split_error, 'category', ''),
                             reason=str(split_error)[:200])
        attach_grouping_spans(rows, cues)
    for cue in cues:
        cue.grouping_origin = 'source_retained_after_local_rejection'
        cue.grouping_boundary_receipt = dict(receipt)
    record_run_event('grouping_range_pending_retry', batch_index=batch_id, **receipt)
    add_review_item(rows[0].start, '断句待重试', message, rows[0].text,
                    priority=3, severity='warning', batch_id=batch_id,
                    source_segment_ids=ids, failure_category=category)
    return GroupedBatchResult(cues, origin='fallback', data_validated=True, result_status='unresolved')


def _locally_split_retained_japanese(rows, cues):
    """Japanese retained range: over-long source lines are split on legal phrase edges.

    2026-11-25 (Ninja Spy, 785 of 794 lines retained): a retained 30-character
    line failed the whole task at the final length gate. The range stays
    pending retry (same origin and receipt), but its lines are now readable.
    """
    try:
        from .language_rules import active_task_language
        if (active_task_language() or '').split('-')[0] != 'ja':
            return None
        profile = _current_language_profile()
        if not any(display_length(cue.text) > profile.hard_max for cue in cues):
            return None
        from .japanese_grouping import build_candidates, local_only
        from .segmentation_alignment import source_segment_character_offsets
        result = []
        # Speaker turns are independent: split each speaker run on its own.
        run = []
        for row in list(rows) + [None]:
            if run and (row is None or (row.speaker or 'S00') != (run[-1].speaker or 'S00')):
                text = ''.join(item.text for item in run)
                candidates = build_candidates(text, source_segment_character_offsets(run),
                                              segment_offsets=source_segment_character_offsets(run),
                                              hard_max=int(profile.hard_max))
                if candidates is None:
                    return None
                pieces, _receipt = local_only(run, candidates, hard_max=int(profile.hard_max),
                                              preferred=int(profile.preferred), max_seconds=float(profile.max_seconds))
                result.extend(pieces)
                run = []
            if row is not None:
                run.append(row)
        for number, cue in enumerate(result, 1):
            cue.cue_id = number
        record_run_event('grouping_retained_range_local_split', source_segment_ids=[row.segment_id for row in rows],
                         before=len(cues), after=len(result), language='ja')
        return result
    except Exception as error:  # the source lines themselves remain valid output
        record_run_event('grouping_retained_range_local_split_failed', error=str(error)[:300])
        return None


def grouping_origin_summary(cues):
    """Separate counts of how each final line was decided (2026-11-25).

    ai_first_pass: the model's first answer; ai_retry: a targeted correction;
    local_fallback: legal local split the model could not supply; pending: kept
    source lines of a range still waiting for an AI retry. The AI adoption
    rate counts only the first two.
    """
    buckets = dict(ai_first_pass=0, ai_retry=0, local_fallback=0, pending=0, other=0)
    for cue in cues:
        origin = str(getattr(cue, 'grouping_origin', '') or '')
        if origin in ('ai_accepted', 'ai_fast_path') or origin.startswith('ai_accepted'):
            buckets['ai_first_pass'] += 1
        elif origin == 'ai_targeted_correction':
            buckets['ai_retry'] += 1
        elif origin.startswith('local_'):
            buckets['local_fallback'] += 1
        elif origin in ('source_retained_after_local_rejection', 'unresolved'):
            buckets['pending'] += 1
        else:
            buckets['other'] += 1
    total = len(cues)
    decided = buckets['ai_first_pass'] + buckets['ai_retry']
    return dict(buckets, total=total, ai_adoption_rate=round(decided / total, 4) if total else None,
                local_fallback_rate=round(buckets['local_fallback'] / total, 4) if total else None)


def _timing_basis(seconds, tokens, edge):
    """'firered' when a measured word edge is within 20 ms, else 'estimate'."""
    key = "start" if edge == "start" else "end"
    return "firered" if any(abs(float(token.get(key, -9)) - float(seconds)) <= .02 for token in tokens or ()) else "estimate"


def run_cached_api_batch(*args, **kwargs):
    from twobyteasr.recognition.cache import run_cached_api_batch as implementation

    return implementation(*args, **kwargs)


__all__ = [
    "cues_from_resegmented_texts",
    "fallback_group",
    "call_grouping_api",
    "group_subtitles",
]


GROUPING_OUTPUT_TOKENS = 10000
GROUPING_RETRY_OUTPUT_TOKENS = ()
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
    from ..providers.asr_provider_snapshot import restore_source_text
    speakers = {segment.speaker or 'S00' for segment in segments}
    if {cue.speaker or 'S00' for cue in cues} != speakers:
        return False
    # A result that already satisfies the source contract needs no rewriting.
    # Re-slicing such a result can move non-content characters (the '<' of a
    # silence placeholder) onto the neighbouring cue and make that cue claim a
    # far-away source second; the contract then rejects the batch and the whole
    # media fails even though nothing was mutated (2026-11-06).
    if _validate_grouped_sources(segments, cues):
        return True
    candidate = copy.deepcopy(cues)
    for speaker in speakers:
        if not restore_source_text(
                [item for item in segments if (item.speaker or 'S00') == speaker],
                [item for item in candidate if (item.speaker or 'S00') == speaker]):
            return False
    if not _validate_grouped_sources(segments, candidate):
        return False
    for before, after in zip(cues, candidate):
        before.text = after.text
    return True


def _validate_grouped_sources(segments, cues, **kwargs):
    from .grouping_contract import grouped_result_is_valid
    return grouped_result_is_valid(segments, cues, **kwargs)


def _contract_safe_pass(name, step, cues, segments):
    """Run one post-grouping cleanup; keep only the changes the source contract allows.

    2026-10-28 (user's 1-hour stream): the 50 AI batches passed, then one of
    ten lone-character merges joined rows across another speaker's turn, and
    the whole file's AI grouping was replaced by the local fallback. A change
    unit is a run of output cues covering the same input cues (a merge, or
    characters moved between neighbours); each is kept only if the contract
    still holds with it.
    """
    from .text_rules import content_only
    after = step(copy.deepcopy(cues))
    if _restore_grouped_source(segments, copy.deepcopy(after)):
        return after

    def spans(items):
        offsets, result = {}, []
        for cue in items:
            speaker = cue.speaker or 'S00'
            start = offsets.get(speaker, 0)
            offsets[speaker] = start + len(content_only(cue.text))
            result.append((speaker, start, offsets[speaker]))
        return result

    before_spans, after_spans = spans(cues), spans(after)
    same = {(span, cue.text, cue.start, cue.end) for span, cue in zip(before_spans, cues)}
    units = []
    for span, cue in zip(after_spans, after):
        if (span, cue.text, cue.start, cue.end) in same:
            continue
        covered = {index for index, (speaker, a, b) in enumerate(before_spans)
                   if speaker == span[0] and a < span[2] and span[1] < b}
        unit = next((unit for unit in units if unit['inputs'] & covered), None)
        if unit is None:
            units.append({'inputs': covered, 'outputs': [cue]})
        else:
            unit['inputs'] |= covered
            unit['outputs'].append(cue)
    current, kept = list(cues), 0
    for unit in units:
        removed = {id(cues[index]) for index in unit['inputs']}
        positions = [index for index, cue in enumerate(current) if id(cue) in removed]
        if not positions or len(positions) != len(removed):
            continue
        position = positions[0]
        candidate = [cue for cue in current if id(cue) not in removed]
        candidate[position:position] = unit['outputs']
        if _restore_grouped_source(segments, copy.deepcopy(candidate)):
            current, kept = candidate, kept + 1
    record_run_event('grouping_postprocess_partial', step=name, change_units=len(units),
                     kept=kept, dropped=len(units) - kept, reason='source_contract')
    return current


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
        and 0 < item.end-item.start <= _current_language_profile().max_seconds
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
    if _quality_enabled():
        boundaries, cursor = [], 0
        source = "".join(segment.text for segment in segment_batch)
        if "".join(proposed_texts) != source:
            raise ValueError("断句候选改动了来源文字或顺序。")
        for text in proposed_texts:
            cursor += display_length(text)
            boundaries.append(cursor)
        cues, _, _ = cues_from_quality(segment_batch, boundaries, firered_tokens, record=record_run_event)
        return cues
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
            # A turn measures its own pauses; ones the shared request could not show the model
            # are added here rather than failing the whole batch (2026-11-18, batch 120).
            relative, added = with_mandatory_breaks(
                "".join(clean_subtitle_text(item.text) for item in turn), relative,
                hard_break_character_offsets(turn, firered_tokens))
            if added:
                record_run_event('grouping_turn_mandatory_breaks_added',
                                 source_segment_ids=[item.segment_id for item in turn], offsets=added)
            turn_texts = texts_from_boundary_offsets(turn, relative, firered_tokens)
            cues.extend(cues_from_resegmented_texts(turn, turn_texts, firered_tokens,
                         speech_regions, comfort_max_chars=comfort_max_chars))
            cursor += length
        return cues

    from .language_rules import is_english
    if is_english():
        from .english_cue_quality import assemble
        return assemble(segment_batch, proposed_texts, firered_tokens)

    proposed_texts = refine_resegmented_texts(
        segment_batch,
        proposed_texts,
        firered_tokens,
    )

    from .segmentation_alignment import tokens_near_segments
    nearby_tokens = tokens_near_segments(segment_batch, firered_tokens)   # same answer, far fewer tokens
    timeline = []
    for segment in segment_batch:
        timeline.extend(segment_content_timeline(segment, nearby_tokens))
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
        end = units[-1].end
        if end <= start:
            raise ValueError("断句对齐时间无效。")

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
        if length > _current_language_profile().hard_max:
            repair_reasons.append(f"{length} 字")
        # 10 字只是观看舒适目标，不是本地硬切条件。11-16 字若 Qwen 判断语义
        # 尚未说完就保持完整，避免用均匀字时长伪造断点并造成时间轴漂移。
        if end - start > _current_language_profile().max_seconds + 0.05:
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
                f"   [本地优化] batch={getattr(_batch_trace, 'batch_id', None)} 断句结果单条 {'+'.join(repair_reasons)} -> {summary}"
            )
            record_run_event("grouping_local_repair", source_segment_ids=[x.segment_id for x in segment_batch],
                reason="hard_length_or_duration_or_pause", reasons=repair_reasons,
                source_text=text, result=[dict(text=x.text,start=x.start,end=x.end) for x in repaired])
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
    # Semantic restart repair can introduce a short tail *before* the length
    # guard runs (12 characters / 3.5s + 6 / .35s at 然后). Reconsider only an
    # affected neighbouring window, using the same source word edges. Source
    # boundaries and real pauses remain mandatory; never pad acoustic time.
    minimum = _current_language_profile().min_seconds
    source_offsets = source_segment_character_offsets(segment_batch)
    index = offset = 0
    while index + 1 < len(cues):
        pair = cues[index:index + 2]
        sizes = [display_length(c.text) for c in pair]
        end_offset = offset + sum(sizes)
        before_score = sum(max(0., minimum - (c.end-c.start)) ** 2 for c in pair)
        if before_score > 0 and end_offset <= len(timeline):
            forced = {cut-offset for cut in set(hard_offsets) | set(source_offsets)
                      if offset < cut < end_offset}
            try:
                repaired = locally_repair_resegmented_cue(
                    "".join(c.text for c in pair), timeline[offset:end_offset],
                    forced_boundaries=forced)
            except (ValueError, TypeError):
                repaired = pair
            after_score = sum(max(0., minimum - (c.end-c.start)) ** 2 for c in repaired)
            conserved = content_exact("".join(c.text for c in repaired)) == content_exact("".join(c.text for c in pair))
            bounded = all(pair[0].start-1e-6 <= c.start < c.end <= pair[-1].end+1e-6 for c in repaired)
            if conserved and bounded and len(repaired) <= 2 and after_score + 1e-6 < before_score:
                running = offset
                for cue in repaired:
                    cue.timing_locked = span_is_timing_locked(running, running+display_length(cue.text))
                    running += display_length(cue.text)
                record_run_event("grouping_short_span_repair", reason="semantic_cut_created_short_aligned_tail",
                    source_segment_ids=[s.segment_id for s in segment_batch],
                    before=[dict(text=c.text,start=c.start,end=c.end) for c in pair],
                    after=[dict(text=c.text,start=c.start,end=c.end) for c in repaired],
                    protected_boundaries=sorted(forced))
                print(f"   [短尾优化] batch={getattr(_batch_trace,'batch_id',None)} "
                      + "/".join(f"{display_length(c.text)}字 {c.end-c.start:.2f}秒" for c in pair)
                      + " -> " + "/".join(f"{display_length(c.text)}字 {c.end-c.start:.2f}秒" for c in repaired))
                cues[index:index + 2] = repaired
                offset += display_length(repaired[0].text)
                index += 1
                continue
            record_run_event("grouping_short_span_retained", reason="protected_boundary_or_no_safer_source_edge",
                source_segment_ids=[s.segment_id for s in segment_batch],
                spans=[dict(text=c.text,start=c.start,end=c.end) for c in pair],
                protected_boundaries=sorted(forced))
        offset += sizes[0]
        index += 1
    cue_end_offsets = set()
    running = 0
    for cue in cues:
        running += display_length(cue.text)
        cue_end_offsets.add(running)
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


@_source_bound_candidate
def fallback_group(segment_batch, firered_tokens=(), speech_regions=()):
    # A rejected/unavailable cloud model must not make the local result worse.
    # MOSS already emits phrase-level utterances close to the supplied human
    # manuscript; keep them verbatim whenever they satisfy the real hard limits.
    # 舒适目标不是硬限制；保留本语言硬上限内的完整来源语句。
    source_cues = [individual_cue(segment) for segment in segment_batch]
    for cue, segment in zip(source_cues, segment_batch):
        cue.text = segment.text
        cue.start, cue.end = segment.start, segment.end
    if not _quality_enabled() and all(
        display_length(cue.text) <= _current_language_profile().hard_max
        and cue.end - cue.start <= _current_language_profile().max_seconds + 0.05
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
            comfort_max_chars=None,
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
        cue.start, cue.end = segment.start, segment.end
    return source_cues


@_source_bound_candidate
def conservative_ai_fallback(segment_batch, firered_tokens=(), speech_regions=()):
    return _retain_grouping_range(segment_batch, 'AI 断句未完成，保留来源字幕。',
                                  getattr(_batch_trace, 'batch_id', None))


@_source_bound_candidate
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
    _quality_budget=None,
    _source_offsets=None,
):
    from .segmentation_profiles import current_profile,word_spans
    language_profile=current_profile()
    if language_profile.strategy!='cjk':
        if abort_event is not None and abort_event.is_set():
            from ..recognition.service import CancelledError
            raise CancelledError('断句已取消。')
        if language_profile.strategy=='conservative':
            return [] if _messages_only else retain_source_utterances(segment_batch,language_profile)
        from ..providers.asr_provider_snapshot import task_provider_snapshot,GroupedBatchResult
        from .grouping_contract import capture_grouping_source,validate_grouping_result
        batch=[(str(s.segment_id),[w[2] for w in word_spans(s.text)]) for s in segment_batch]
        if language_profile.code=='ko':
            from . import korean_segmentation as owner
            if _messages_only:return owner.build_ai_messages(batch)
            result=owner.group_korean_with_ai(segment_batch,firered_tokens,provider_snapshot or task_provider_snapshot('group'))
        else:
            from . import english_segmentation as owner
            from .european_text import lexicon
            lex=lexicon(language_profile.code) if language_profile.code!='en' else None
            if _messages_only:return owner.build_ai_messages(batch,lex)
            result=owner.group_english_with_ai(segment_batch,firered_tokens,provider_snapshot or task_provider_snapshot('group'),lexicon=lex)
        validate_grouping_result(segment_batch, result)
        from .ai_boundary_policy import provenance
        valid = all(getattr(cue, 'grouping_origin', '') != 'unresolved' for cue in result)
        origin, status = provenance(result, valid)
        return GroupedBatchResult(result, origin=origin, validated=valid, data_validated=True,
            result_status=status, source_fingerprint=capture_grouping_source(segment_batch).fingerprint)
    from ..providers.provider_input_budget import RetryBudget
    _retry_budget=_retry_budget if _retry_budget is not None else RetryBudget(GROUPING_API_RETRIES-1)
    _quality_budget = _quality_budget if _quality_budget is not None else QualityRetryBudget()
    from ..providers.asr_provider_snapshot import (
        task_provider_snapshot, request_record, classify_request_error,
        GroupedBatchResult, validate_grouped_text, restore_source_text,
    )
    from ..providers.ai_providers import AIProviderError
    from ..recognition.service import CancelledError
    snapshot = provider_snapshot or task_provider_snapshot("group")
    rejected = (_retry_budget.snapshot_rejection('grouped', snapshot.fingerprint)
        if not _messages_only else None)
    if rejected:
        if batch_diagnostics is not None:
            batch_diagnostics['fallback_reason'] = rejected[0]
        record_run_event('grouping_api_fallback', batch_index=batch_index,
            category=rejected[0], error=rejected[1], request_dispatched=False)
        result = conservative_ai_fallback(segment_batch, firered_tokens, speech_regions)
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
        return conservative_ai_fallback(segment_batch, firered_tokens, speech_regions)

    hard_break_offsets = sorted(
        hard_break_character_offsets(segment_batch, firered_tokens)
    )
    source_text = "".join(segment.text for segment in segment_batch)
    total_length = display_length(source_text)
    if total_length != len(content_exact(source_text)):
        from .grouping_contract import GroupingContractError
        if _messages_only:
            raise GroupingContractError("来源字形归一化改变了索引长度。", category="index_unit_mismatch")
        record_run_event("grouping_api_fallback", batch_index=batch_index,
            category="index_unit_mismatch", request_dispatched=False)
        add_review_item(segment_batch[0].start, "断句回退",
            "本批字符索引不适合 AI 断句，已保留本地原文和时间。", "",
            priority=3, severity="warning")
        return GroupedBatchResult(conservative_ai_fallback(segment_batch, firered_tokens, speech_regions),
                                  origin="fallback", data_validated=True)
    segment_payload = []
    source_global_starts = {}
    content_cursor = 0
    for segment in segment_batch:
        source_global_starts[segment.segment_id] = content_cursor
        length = display_length(segment.text)
        segment_payload.append(
            {
                "id": segment.segment_id,
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "content_start": content_cursor,
                "content_end": content_cursor + length,
                "global_content_start": segment.caption_arbitration.get('grouping_request_source',{}).get(
                    'global_content_start',(_source_offsets or {}).get(segment.segment_id,content_cursor)),
                "global_content_end": segment.caption_arbitration.get('grouping_request_source',{}).get(
                    'global_content_end',(_source_offsets or {}).get(segment.segment_id,content_cursor)+length),
                "text": segment.text,
                "speaker": segment.speaker or 'S00',
                "source_mapping": {key:value for key,value in segment.caption_arbitration.get(
                    "grouping_request_source", {}).items() if key != "original_text"},
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
    from .grouping_request import grouping_prompt_key, grouping_system_prompt, task_prompt_language
    from ..recognition.content_scene import runtime_content_scene
    scene = runtime_content_scene()
    prompt = grouping_system_prompt(_current_language_profile().hard_max, _current_language_profile().max_seconds)
    from .language_rules import is_english
    if is_english():
        prompt = grouping_system_prompt(84, 6.0) + (
            '\nEnglish cue quality: preserve complete clauses and word groups. '
            'One cue can occupy two visual lines (42 characters per line, 84 including spaces per cue, at most 6 seconds). '
            'Visual wrapping is not a new cue. Do not cut after like before its comparison, articles, prepositions, '
            'auxiliaries, not, or inside phrasal verbs unless a real long pause or speaker interruption requires it. '
            'Keep the exact supplied words (including steam), order and punctuation. '
            'The same JSON boundary-offset schema and all source/time protections remain mandatory.')
    # Built-in prompts keep their version; the user's guidance adds its digest.
    prompt_language = task_prompt_language()
    prompt_key = grouping_prompt_key(prompt_language)
    request_body = {
        "prompt_version": prompt_key,
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
        "source_segment_contract": "provenance_only_optional_boundaries",
        "read_only_context": _read_only_context or segment_batch[0].caption_arbitration.get("grouping_read_only_context", {}),
        "body_range": [0, total_length],
        "index_unit": "content_exact_unicode_codepoints",
        "quality_version": QUALITY_VERSION,
        "time_domain": "source_seconds",
    }
    japanese_candidates = None
    japanese_candidate_set = None
    if prompt_language == "ja":
        # 2026-11-18: the model picks numbered phrase ends instead of copying the text.
        # 2026-11-25: one candidate engine for every entry (japanese_grouping); a
        # mandatory pause measured inside a word (返してくださ｜い) moves to the
        # nearest phrase edge so the request always has a legal answer.
        from .japanese_grouping import build_candidates
        japanese_candidate_set = build_candidates(
            source_text, set(hard_break_offsets) | set(protected_source_offsets),
            segment_offsets=source_boundary_offsets, hard_max=int(_current_language_profile().hard_max))
        if japanese_candidate_set is not None:
            japanese_candidates = japanese_candidate_set.candidates
            moved = {row['given']: row['used'] for row in japanese_candidate_set.moved_mandatory}
            hard_break_offsets = sorted({moved.get(x, x) for x in hard_break_offsets})
            protected_source_offsets = sorted({moved.get(x, x) for x in protected_source_offsets})
            request_body["hard_break_character_offsets"] = hard_break_offsets
            request_body["protected_source_offsets"] = protected_source_offsets
            request_body.pop("indexed_content", None)
            request_body.pop("source_text", None)
            request_body["marked_text"] = marked_break_text(source_text, japanese_candidates)
            request_body["break_candidate_count"] = len(japanese_candidates)
            request_body["candidate_source"] = japanese_candidate_set.source
            if japanese_candidate_set.indivisible:
                request_body["indivisible_length_conflicts"] = [
                    dict(start=a, end=b, units=b - a) for a, b in japanese_candidate_set.indivisible]
            if not _messages_only:
                record_run_event('japanese_grouping_candidates', batch_index=batch_index,
                                 **japanese_candidate_set.receipt())
    if _quality_enabled():
        inherited_allowed = segment_batch[0].caption_arbitration.get('grouping_request_allowed') if len(segment_batch)==1 else None
        if inherited_allowed is not None:
            request_body['allowed_boundaries'] = inherited_allowed
        else:
            request_quality = quality_for_segments(segment_batch, firered_tokens,
                protected=set(hard_break_offsets) | set(protected_source_offsets))
            from .ai_boundary_policy import select_model_boundary_domain
            select_model_boundary_domain(request_quality)
            request_body["allowed_boundaries"] = request_quality.allowed
            request_body["semantic_required_boundaries"] = sorted(request_quality.semantic_required)
            from .segmentation import lexical_boundary_terms
            request_body['protected_terms'] = [term for term in lexical_boundary_terms()
                if content_exact(term) in request_quality.index.content]
        from .grouping_request import uses_marked_breaks
        if uses_marked_breaks(prompt_language):
            # 2026-11-22: the model picks ‹N› marks in the gaps instead of
            # counting characters off indexed_content (英雄了各｜位).
            from .ai_boundary_policy import break_candidates
            marks = (sorted(set(inherited_allowed) | {total_length}) if inherited_allowed is not None
                     else break_candidates(request_quality))
            request_body.pop("indexed_content", None)
            request_body["marked_text"] = marked_break_text(source_text, [x for x in marks if x < total_length])
            request_body["allowed_boundaries"] = marks
        if not _messages_only and inherited_allowed is None:
            offered = set(request_body["allowed_boundaries"])
            candidates = []
            for edge in sorted(request_quality.candidate_edges | offered | set(source_boundary_offsets)):
                if not 0 < edge < total_length:
                    continue
                detail = request_quality.explain_boundary(edge)
                detail['local_evidence_allowed'] = detail['allowed']
                detail['allowed'] = edge in offered
                if detail['allowed'] and not detail['local_evidence_allowed']:
                    detail['override_reason'] = ('measured_pause' if request_quality.pauses.get(edge, 0) >= .55
                                                 else 'advisory_evidence_only')
                candidates.append(detail)
            record_run_event('grouping_boundary_evidence', batch_index=batch_index,
                policy=QUALITY_VERSION, tokens=request_quality.tagged_tokens, candidates=candidates,
                index_unit="content_exact_unicode_codepoints",
                source_text_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                tokenizer=request_quality.tokenizer_identity())
        request_body['length_policy'] = dict(language=prompt_language,
            hard_max=_current_language_profile().hard_max,max_seconds=_current_language_profile().max_seconds,
            unit=_current_language_profile().unit,origin='built_in_language_profile',hard_max_is_target=False)
        if prompt_language == "zh":
            from .segmentation_profiles import profile_for
            request_body['length_policy']['latin_visible_character_max'] = profile_for("en").hard_max
            request_body['length_policy']['mixed'] = 'CJK uses the CJK budget; Latin runs and spaces use the Latin budget proportionally'
        from .ai_boundary_policy import indivisible_spans
        conflicts = indivisible_spans(request_quality) if inherited_allowed is None else []
        if conflicts:
            request_body['indivisible_length_conflicts'] = [
                dict(start=left, end=right, units=right-left) for left, right in conflicts]
            if not _messages_only:
                record_run_event('grouping_constraint_preflight', batch_index=batch_index,
                    conflicts=request_body['indivisible_length_conflicts'])
            prompt += (" indivisible_length_conflicts 是不可拆且超过上限的已知局部冲突。"
                       "保留其完整文字与两端，完成其他范围，不尝试在冲突内部创造断点。")
            if conflicts == [(0, total_length)] and not _messages_only:
                if batch_diagnostics is not None:
                    batch_diagnostics['fallback_reason'] = 'indivisible_unit'
                return _retain_grouping_range(segment_batch, '不可拆单元超过断句上限，需核对识别证据。', batch_index)
        request_body['source_timing'] = [dict(source_id=s.segment_id,
            basis=s.caption_arbitration.get('word_timing',{}).get('basis','source_segment'),
            reliable_internal_timing=s.caption_arbitration.get('word_timing',{}).get('basis')
                in {'provider_words','aligner_words'},
            words=s.caption_arbitration.get('word_timing',{}).get('measured_words',[])) for s in segment_batch]
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(request_body, ensure_ascii=False, separators=(',', ':'))},
    ]
    if _messages_only:
        return messages
    record_run_event('grouping_request_contract', batch_index=batch_index,
        system_prompt=prompt, request_body=request_body)

    def run_child(child, child_id, *, retry_child=False):
        from .grouping_contract import GroupingContractError, runtime_task_binding
        from ..recognition.run_context import context_is_current
        from ..recognition.service import CancelledError
        child_diag = dict(batch_id=child_id, parent_batch_id=batch_index)
        context = get_runtime_context()
        task_binding = runtime_task_binding(context)
        dependency = None
        if _cache_context is not None:
            dependency = {'protocol': 'speaker-labelled-protected-boundaries-v2-packed',
                          'segments': _grouping_dependency_segments(child), 'messages': build_messages(child)}
        checkpoint = None
        if dependency is not None and context.task_journal is not None and not context.shard_id:
            from ..recognition.grouping_checkpoint import range_dependency, range_key
            checkpoint = (range_key(context, child_id), range_dependency(context, dependency, snapshot))

        def validate_child(values):
            return _validate_grouped_sources(child, values,
                protect_all_source_boundaries=protect_all_source_boundaries,
                protected_after_source_ids=protected_after_segment_ids)

        def check_cancelled():
            if not context_is_current(context) or task_binding != runtime_task_binding(context):
                raise CancelledError("断句任务已被替换。")
            if context.cancellation_token is not None:
                context.cancellation_token.raise_if_cancelled()

        check_cancelled()
        if checkpoint and context.resume and not context.force_refresh_group_cache:
            receipt = context.task_journal.load_artifact(*checkpoint)
            if receipt:
                cached = GroupedBatchResult(deserialize_cues(receipt['cues']), origin=receipt['origin'],
                    validated=True, data_validated=True, result_status=receipt['result_status'])
                if validate_child(cached):
                    extend_review_items(receipt['reviews'])
                    record_run_event('grouping_range_reused', batch_index=child_id, source_rows=len(child))
                    return cached

        def execute():
            check_cancelled()
            if retry_child and not _retry_budget.take():
                child_diag['fallback_reason'] = 'retry_budget_exhausted'
                record_run_event('grouping_api_fallback', batch_index=child_id, parent_batch_id=batch_index,
                    category='retry_budget_exhausted', request_dispatched=False)
                return GroupedBatchResult(conservative_ai_fallback(child, firered_tokens, speech_regions),
                    origin='fallback', data_validated=True)
            return call_grouping_api(child,
                protect_all_source_boundaries=protect_all_source_boundaries,
                protected_after_segment_ids=protected_after_segment_ids,
                firered_tokens=firered_tokens,speech_regions=speech_regions,
                abort_event=abort_event,batch_index=child_id,batch_total=batch_total,
                _split_depth=_split_depth+1,provider_snapshot=snapshot,
                batch_diagnostics=child_diag,_retry_budget=_retry_budget,
                _cache_context=_cache_context,
                _read_only_context=child[0].caption_arbitration.get('grouping_read_only_context',_read_only_context),
                _quality_budget=_quality_budget,_source_offsets=_source_offsets)
        with capture_review_items() as reviews:
            try:
                result = execute() if _cache_context is None else run_cached_api_batch('grouped',_cache_context,
                    dependency, execute, encoder=serialize_cues,decoder=deserialize_cues,
                    fallback_categories=('断句回退',),provider_snapshot=snapshot,diagnostics=child_diag,
                    validator=validate_child)
            except GroupingContractError as error:
                if error.category in {'stale_source', 'source_identity'}:
                    raise
                result = _retain_grouping_range(child, error, child_id)
        check_cancelled()
        extend_review_items(reviews)
        if checkpoint and _grouping_range_is_complete(result, True):
            key, binding = checkpoint
            context.task_journal.publish(key, dict(cues=serialize_cues(result),
                origin=result.origin, result_status=result.result_status, reviews=reviews), binding)
        if batch_diagnostics is not None and getattr(result,'origin','') == 'fallback':
            reason = child_diag.get('fallback_reason') or 'child_failed'
            batch_diagnostics.setdefault('child_failures',[]).append(dict(batch_id=child_id,reason=reason))
            batch_diagnostics['fallback_reason'] = reason
        return result

    def build_messages(child):
        if len(child)==len(segment_batch) and all(a is b for a,b in zip(child,segment_batch)):
            return messages
        return call_grouping_api(child,
            protect_all_source_boundaries=protect_all_source_boundaries,
            protected_after_segment_ids=protected_after_segment_ids,
            firered_tokens=firered_tokens,speech_regions=speech_regions,
            provider_snapshot=snapshot,_messages_only=True,_retry_budget=_retry_budget,
            _read_only_context=child[0].caption_arbitration.get('grouping_read_only_context',_read_only_context),
            _source_offsets=_source_offsets)

    if not _packed:
        from ..providers.provider_input_budget import pack_items
        packed,rejected=pack_items(segment_batch,build_messages,
            operation='group',max_tokens=snapshot.max_output_tokens,schema=GROUPING_SCHEMA)
        if rejected or len(packed)>1:
            rejected_ids={item.segment_id for item,_ in rejected}
            by_first={batch[0].segment_id:batch for batch in packed}
            combined=[]
            all_validated=True
            child_count=0
            for item in segment_batch:
                if item.segment_id in rejected_ids:
                    combined.extend(_retain_grouping_range([item],
                        '来源字幕超出模型请求预算，保留原文与时间。', batch_index))
                    all_validated = False
                elif item.segment_id in by_first:
                    child_count+=1
                    child_result=run_child(by_first[item.segment_id],f'{batch_index}.{child_count}')
                    all_validated=all_validated and bool(getattr(child_result,'validated',False))
                    combined.extend(child_result)
            if not _restore_grouped_source(segment_batch,combined):
                raise ValueError('分批断句未保持完整正文与顺序。')
            from .ai_boundary_policy import provenance
            origin,status=provenance(combined,all_validated)
            return GroupedBatchResult(combined,validated=all_validated,origin=origin,result_status=status)
    group_settings = snapshot.endpoint()
    provider = provider_for_stage(snapshot.execution_settings(), "group", sender=post_chat_completion)
    print(
        f"   [断句] batch={batch_index} {snapshot.provider}/{snapshot.model} · {snapshot.transport}（数字 boundaries，原文不可变）"
    )
    last_error = None
    last_category = "request_error"
    working_messages = list(messages)
    for attempt in range(1, GROUPING_API_RETRIES + 1):
        content = ""
        diag = request_record(snapshot, stage="grouped", batch_id=batch_index,
            speaker=segment_batch[0].speaker or "S00", attempt=attempt,
            cache_key=(batch_diagnostics or {}).get("cache_key", ""), input_characters=len(source_text))
        diag.update(prompt_version=prompt_key, content_scene=scene.to_dict(),
            prompt_characters=sum(len(item["content"]) for item in working_messages))
        if batch_diagnostics:
            diag["scheduler_queue_wait_ms"] = batch_diagnostics.get("scheduler_queue_wait_ms", 0)
        attempt_started = time.perf_counter()
        try:
            _retry_budget.raise_if_rejected('grouped', snapshot.fingerprint)
            cancellation = get_runtime_context().cancellation_token
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            content = provider.complete(
                working_messages,
                stage="grouped",
                operation_kind='group',
                batch_index=batch_index,
                max_tokens=snapshot.max_output_tokens,
                temperature=0.0,
                timeout=snapshot.timeout_policy.total,
                _timeout_policy=snapshot.timeout_policy,
                request_diagnostics=diag,
                _task_failure_scope=(_retry_budget, 'grouped', snapshot.fingerprint),
                cancel_check=lambda: bool(abort_event is not None and abort_event.is_set()) or bool(
                    getattr(get_runtime_context().cancellation_token, "is_cancelled", False)),
                enable_thinking=snapshot.enable_thinking,
                thinking_protocol=snapshot.thinking_protocol,
                response_format={"type": "json_object"},
                structured_retry_system_prompt=None,
                structured_retry_max_tokens=(),
                json_schema=GROUPING_SCHEMA,
            )
            diag["raw_response_length"] = len(content)
            diag["raw_response_sha256"] = hashlib.sha256(str(content).encode("utf-8")).hexdigest()
            # The answer is only boundary numbers; a short redacted excerpt makes a
            # rejected batch diagnosable (2026-11-25: only hashes were recorded).
            diag["raw_response_excerpt"] = redact_runtime_secrets(str(content)[:1500])
            if not str(content).strip():
                raise AIProviderError("断句正文为空。", category="empty_response")
            from .grouping_contract import parse_grouping_response, capture_grouping_source
            # 2026-10-18: the Japanese prompt says the bars of segmented_text decide;
            # a missing closing total_length is added for every language.
            boundary_offsets, returned = parse_grouping_response(
                content, source_text, bars_win=prompt_language == "ja",
                closing_added=lambda total: record_run_event(
                    "grouping_closing_boundary_added", batch_index=batch_index,
                    attempt=attempt, total_length=total))
            if japanese_candidate_set is not None:
                # A pick between marks moves to the nearest mark instead of
                # failing the batch (2026-11-25: 3/13 batches of 1.json).
                from .japanese_grouping import snap as _snap_japanese
                boundary_offsets, off_marks = _snap_japanese(boundary_offsets, japanese_candidate_set)
                if off_marks:
                    record_run_event('grouping_marked_boundaries_snapped', batch_index=batch_index,
                                     attempt=attempt, moved=off_marks)
            model_boundaries = list(boundary_offsets)
            source_identity = capture_grouping_source(segment_batch,
                job_id=get_runtime_context().job_id, batch_id=batch_index).identity()
            diag.update(source_identity=source_identity,
                raw_response_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                parsed_response_sha256=hashlib.sha256(json.dumps(returned,
                    sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest())
            quality_issues = []
            boundary_receipts = []
            if _quality_enabled():
                quality = quality_for_segments(segment_batch, firered_tokens,
                    protected=set(hard_break_offsets) | set(protected_source_offsets))
                from .ai_boundary_policy import (inspect, preserve_rejected_windows, annotate,
                                                 select_model_boundary_domain, snap_offset_errors)
                select_model_boundary_domain(quality)
                if inherited_allowed is not None:
                    quality.allowed = list(inherited_allowed)
                diag["model_quality_issues"] = inspect(quality, model_boundaries, advisory=True)
                diag['semantic_advice'] = quality.inspect(model_boundaries)
                source_cuts = sorted(set(source_boundary_offsets) | {total_length})
                model_state = ('unchanged_with_violations' if diag['model_quality_issues'] else 'unchanged_valid') if model_boundaries == source_cuts else 'regrouped'
                diag['model_quality_state'] = model_state
                record_run_event('grouping_model_quality', batch_index=batch_index, state=model_state,
                    protocol_valid=True, content_conserved=True, issues=diag['model_quality_issues'])
                retry_statuses = {}
                # Character-count misses are moved to the adjacent legal edge
                # before any window is judged or sent back (2026-11-22).
                snapped_boundaries = list(model_boundaries)
                from .grouping_request import uses_marked_breaks
                if uses_marked_breaks(prompt_language):
                    from .ai_boundary_policy import break_candidates, place_on_marks, blocked_evidence_edges
                    marks = (sorted(set(quality.allowed) | {total_length}) if inherited_allowed is not None
                             else break_candidates(quality))
                    snapped_boundaries, off_marks = place_on_marks(
                        snapped_boundaries, marks, right=total_length,
                        immutable=quality.hard_lexical_interiors | blocked_evidence_edges(quality))
                    if off_marks:
                        record_run_event('grouping_boundary_snapped', batch_index=batch_index,
                            rule='nearest_offered_mark', moves=[dict(model=a, final=b) for a, b in off_marks])
                snapped_boundaries, _moves = snap_offset_errors(quality, snapped_boundaries,
                    record=record_run_event, batch_index=batch_index)
                # Required cuts (speaker change, protected source edge) are measured
                # locally; a missing one is put back rather than failing the answer.
                missing = sorted(quality.required - set(snapped_boundaries))
                if missing:
                    snapped_boundaries = sorted(set(snapped_boundaries) | set(missing))
                    record_run_event('grouping_required_boundaries_added', batch_index=batch_index,
                                     boundaries=missing)
                boundary_offsets = retry_quality_windows(quality, snapped_boundaries, snapped_boundaries,
                    provider=provider, snapshot=snapshot, schema=GROUPING_SCHEMA,
                    budget=_quality_budget, record=record_run_event, batch_index=batch_index,
                    source_spans=segment_payload,receipts=boundary_receipts,statuses=retry_statuses,
                    cancel_check=lambda: bool(abort_event is not None and abort_event.is_set()) or bool(
                        getattr(get_runtime_context().cancellation_token,"is_cancelled",False)))
                # 2026-11-22 (user: 99.9% without human edits): an AI subtitle
                # editor rereads the finished lines as text and may move breaks,
                # kept only when a blind two-order judge prefers it. Off unless
                # switches.grouping_ai_editor: about +0.5% clean lines for twice
                # the grouping time in the paid reruns.
                try:
                    from .grouping_editor import edit_lines, enabled as editor_enabled
                    if editor_enabled(get_runtime_context()):
                        boundary_offsets = edit_lines(quality, boundary_offsets, provider=provider, snapshot=snapshot,
                        record=record_run_event, batch_index=batch_index,
                        cancel_check=lambda: bool(abort_event is not None and abort_event.is_set()) or bool(
                            getattr(get_runtime_context().cancellation_token,"is_cancelled",False)))
                except CancelledError:
                    raise
                except Exception as editor_error:  # the lines before the editor stand
                    record_run_event('grouping_editor_failed', batch_index=batch_index, error=str(editor_error)[:200])
                # 2026-11-22 (user: AI only, no half-finished local result):
                # the AI's final answer stands; only a split confirmed term or a
                # lost protected cut goes back to the source boundaries.
                from .ai_boundary_policy import must_retain_source, blocking_issues, unsplittable_lengths
                boundary_offsets, unresolved_receipts = preserve_rejected_windows(
                    quality, boundary_offsets, source_cuts, record=record_run_event, statuses=retry_statuses,
                    retain=must_retain_source)
                boundary_receipts.extend(unresolved_receipts)
                result, boundary_offsets, quality_issues = cues_from_quality(segment_batch,
                    boundary_offsets, firered_tokens,
                    protected=set(hard_break_offsets) | set(protected_source_offsets),
                    record=record_run_event, repair=False, quality=quality,
                    review_filter=lambda issues: [x for x in blocking_issues(issues)
                                                  if x not in unsplittable_lengths(quality, issues)])
                annotate(result, model_boundaries, boundary_offsets, boundary_receipts)
                original_by_span = {(start, end): row for start, end, row in
                    zip([0, *source_cuts[:-1]], source_cuts, segment_batch)}
                for cue in result:
                    receipt = cue.grouping_boundary_receipt
                    if cue.grouping_origin == 'unresolved':
                        row = original_by_span[(receipt['content_start'], receipt['content_end'])]
                        cue.start, cue.end = row.start, row.end
                        cue.timing_basis = 'original_source_sentence'
                quality_issues.extend(issue for receipt in unresolved_receipts
                                      for issue in receipt['remaining_issues'] if issue not in quality_issues)
                # Dictionary/POS doubts about the AI's final cut stay review notes;
                # only a cuttable over-long line, a lost protected cut or a split
                # confirmed term leaves the range unfinished.
                quality_issues = blocking_issues(quality_issues)
                # A line with no legal cut inside (a long number) cannot be
                # fixed by anyone; it is a note, not an unfinished range.
                unsplittable = unsplittable_lengths(quality, quality_issues)
                if unsplittable:
                    import subtitle_core as _review_core
                    for issue in unsplittable:
                        position = min(issue['start'], max(0, quality.total-1))
                        _review_core.add_review_item(quality.units[position].start if quality.units else segment_batch[0].start,
                            '断句约束待复核', '这一条没有可以换行的位置（例如一串数字），保留整条。',
                            quality.index.slice(issue['start'], issue['end']), priority=1, severity='info',
                            grouping_quality=issue, grouping_origin='local_review')
                    quality_issues = [x for x in quality_issues if x not in unsplittable]
                record_run_event('pipeline_work_progress',work_id=f'grouped:{batch_index}:local',
                    label='断句：边界校验',phase='grouping_local_validation',state='completed',
                    done=1,total=1,batch_index=batch_index,review_required=bool(quality_issues))
                proposed_texts = quality.index.pieces(boundary_offsets)
                record_run_event('grouping_boundary_commit', batch_index=batch_index, policy=QUALITY_VERSION,
                    index_unit="content_exact_unicode_codepoints",
                    source_text_sha256=hashlib.sha256(quality.index.text.encode("utf-8")).hexdigest(),
                    model_positions=model_boundaries, committed_positions=boundary_offsets,
                    unresolved_issues=quality_issues)
            elif prompt_language == 'ja' and japanese_candidate_set is not None:
                # 2026-11-25: lines are checked one by one. Valid lines stay, only
                # the failing windows go back to the model with the exact error,
                # and what it cannot fix is split locally on legal candidates
                # (labelled local_*). A local line problem never rejects the batch.
                from .japanese_grouping import finalize_batch

                def _japanese_repair(repair_messages):
                    # Bounded by finalize_batch: at most three targeted rounds per
                    # batch, and a repeated answer stops the loop.
                    return provider.complete(
                        repair_messages, stage="grouped", operation_kind='group', batch_index=batch_index,
                        max_tokens=snapshot.max_output_tokens, temperature=0.0,
                        timeout=snapshot.timeout_policy.total, _timeout_policy=snapshot.timeout_policy,
                        cancel_check=lambda: bool(abort_event is not None and abort_event.is_set()) or bool(
                            getattr(get_runtime_context().cancellation_token, "is_cancelled", False)),
                        enable_thinking=snapshot.enable_thinking, thinking_protocol=snapshot.thinking_protocol,
                        response_format={"type": "json_object"})
                profile_now = _current_language_profile()
                result, ja_receipt = finalize_batch(
                    segment_batch, model_boundaries, japanese_candidate_set,
                    firered_tokens=firered_tokens, speech_regions=speech_regions,
                    hard_max=int(profile_now.hard_max), preferred=int(profile_now.preferred),
                    max_seconds=float(profile_now.max_seconds), complete=_japanese_repair,
                    record=record_run_event, batch_index=batch_index)
                boundary_offsets = list(ja_receipt['final_boundaries'])
                proposed_texts = [cue.text for cue in result]
                boundary_receipts.extend(dict(cue.grouping_boundary_receipt) for cue in result
                                         if cue.grouping_origin != 'ai_accepted')
                for cue in result:
                    if cue.grouping_origin == 'local_indivisible_retained':
                        add_review_item(cue.start, '断句约束待复核',
                            '这一条找不到合法的换行位置（完整词或时间证据不足），保留整条并标出局部冲突。',
                            cue.text, priority=1, severity='info', grouping_origin='local_indivisible_retained',
                            batch_index=batch_index)
            else:
                raise AIProviderError("模型断点未通过本语言的边界、长度或时间校验。",
                                      category="semantic_quality")
            if not _restore_grouped_source(segment_batch, result):
                raise AIProviderError("断句结果未通过逐字符原文校验。", category="text_mutation_rejected")
            diag["final_cues_sha256"] = hashlib.sha256(json.dumps(serialize_cues(result),
                sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            ai_corrected = any(r['origin']=='ai_targeted_correction' for r in boundary_receipts)
            diag.update(result_status="unresolved" if quality_issues else "ai_targeted_correction" if ai_corrected else "ai_accepted",
                        parse_status="valid", body_empty=False)
            diag.update(boundary_count=len(boundary_offsets), validator_result="quality_review" if quality_issues else "exact_text_length_semantics_and_boundaries",
                        total_duration_ms=round((time.perf_counter()-attempt_started)*1000, 3), result_origin="fallback" if quality_issues else "ai")
            # 2026-10-10: keep the model's own answer next to what local
            # repair and timing made of it (input -> response -> result).
            record_run_event("grouping_trace", batch_index=batch_index, attempt=attempt,
                source_segment_ids=[segment.segment_id for segment in segment_batch],
                source_text=source_text, source_index_map=list(SourceIndex.build(source_text).raw_edges),
                index_unit="content_exact_unicode_codepoints", hard_break_offsets=hard_break_offsets,
                protected_source_offsets=protected_source_offsets,
                model_boundaries=model_boundaries, model_texts=_texts_at(source_text, model_boundaries),
                final_boundaries=list(boundary_offsets), final_texts=[cue.text for cue in result],
                boundary_receipts=boundary_receipts,result_status=diag['result_status'],
                cues=[{"text": cue.text, "start": round(cue.start, 3), "end": round(cue.end, 3),
                       "speaker": cue.speaker, "start_basis": getattr(cue,"start_timing_basis",_timing_basis(cue.start, firered_tokens, "start")),
                       "end_basis": getattr(cue,"end_timing_basis",_timing_basis(cue.end, firered_tokens, "end"))} for cue in result])
            if batch_diagnostics is not None:
                batch_diagnostics["fallback_reason"] = "semantic_quality" if quality_issues else None
            record_run_event("asr_provider_request", **diag)
            accepted = GroupedBatchResult(result, validated=not quality_issues, origin=diag['result_origin'])
            accepted.result_status = diag["result_status"]
            if prompt_language == 'ja' and japanese_candidate_set is not None and not _quality_enabled():
                # A batch with local splits is reported as mixed, never as pure AI.
                from .ai_boundary_policy import provenance
                accepted.origin, accepted.result_status = provenance(result, True)
            return accepted
        except CancelledError:
            raise
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
            if (last_category in {'text_mutation_rejected','format_mismatch'}
                    and len(segment_batch)>16 and _split_depth==0):
                # A large rejected answer gets one bounded smaller attempt.
                # Never keep resending the same large, invalid text response.
                break
            from ..providers.provider_input_budget import retry_delay, wait_retry
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
                    from ..recognition.service import CancelledError
                    raise CancelledError('断句任务已取消。')

    quality_rebatch=(last_category in {'text_mutation_rejected','format_mismatch'}
                     and len(segment_batch)>16 and _split_depth==0)
    if quality_rebatch or (
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
            child_result=run_child(child,f'{batch_index}.{part}',retry_child=not quality_rebatch)
            all_validated=all_validated and bool(getattr(child_result,'validated',False))
            child_cues.extend(child_result)
        if batch_diagnostics is not None:
            batch_diagnostics['retry_reason'] = last_category
            if all_validated:batch_diagnostics['fallback_reason'] = None
        from .ai_boundary_policy import provenance
        origin,status=provenance(child_cues,all_validated)
        return GroupedBatchResult(child_cues,validated=all_validated,origin=origin,result_status=status)

    print(f"   [警告] 断句连续失败，当前失败范围保守保留原边界：{last_error}")
    record_run_event(
        "grouping_api_fallback",
        source_processing_ids=[int(segment.segment_id) for segment in segment_batch],
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
        "AI 断句结果未通过检查，已保留来源字幕及原时间，等待重试。",
        segment_batch[0].text,
        priority=3,
        severity="warning",
        batch_index=batch_index,
        batch_total=batch_total,
    )
    result = conservative_ai_fallback(segment_batch, firered_tokens, speech_regions)
    if not _restore_grouped_source(segment_batch, result):
        result = [individual_cue(segment) for segment in segment_batch]
        for cue, segment in zip(result, segment_batch):
            cue.text = segment.text
    return GroupedBatchResult(result, origin="fallback")


@_source_bound_candidate
def retain_source_utterances(segments,profile=None):
    from .segmentation_profiles import current_profile,task_language_tag,measure
    profile=profile or current_profile()
    result=[];overflow=0
    for row in sorted(segments,key=lambda r:(r.start,r.end,r.segment_id)):
        cue=SubtitleCue(len(result)+1,float(row.start),float(row.end),row.text,
            bool(getattr(row,'timing_locked',False)),row.speaker or 'S00')
        cue.source_spans=[dict(source_id=row.segment_id,char_start=0,char_end=len(row.text),raw_text=row.text,
            index_unit='python_unicode_codepoint',source_time=[row.start,row.end])]
        cue.timing_basis='original_source_sentence'
        cue.segmentation_language=task_language_tag(profile.code)
        result.append(cue)
        overflow+=measure(row.text,profile.code)>profile.hard_max or row.end-row.start>profile.max_seconds
    record_run_event('conservative_language_grouping',language=profile.code,policy=profile.fingerprint,
        utterances=len(result),over_limit_retained=overflow,reason='no_reliable_lexical_boundaries; source_utterances_retained')
    return result


def accepted_japanese_boundaries(segments,boundaries,required=(),firered_tokens=(),speech_regions=None):
    """Keep source cuts or require measured phrase evidence for new cuts."""
    from .japanese_morphology import document_phrase_spans
    from .language_rules import JAPANESE_CUE_MAX_CHARS,JAPANESE_CUE_MAX_SECONDS
    source_pieces = [content_exact(segment.text) for segment in segments]
    if not set(required) <= set(boundaries):
        return None
    if list(boundaries) == list(accumulate(map(len, source_pieces))):
        # A boundary-only response that selects the existing cuts has no
        # timing edits to commit. Word evidence may cross a display boundary
        # in a reopened Studio project and must not retime its neighbour.
        result = retain_source_utterances(segments)
    else:
        text = ''.join(source_pieces)
        spans = document_phrase_spans(text)
        if spans is None or not set(boundaries) <= {len(text), *(end for _, end, _ in spans)}:
            return None
        pieces = texts_from_boundary_offsets(segments, boundaries, firered_tokens)
        result = cues_from_resegmented_texts(segments, pieces, firered_tokens, speech_regions)
    cursor=0;actual=[]
    for cue in result:
        size=len(content_exact(cue.text));cursor+=size;actual.append(cursor)
        if size>JAPANESE_CUE_MAX_CHARS or cue.end-cue.start>JAPANESE_CUE_MAX_SECONDS+.05:return None
    if actual!=list(boundaries):return None
    from .ai_boundary_policy import annotate
    annotate(result,boundaries,boundaries,[])
    return result


# 2026-11-16: "the model did not answer in the contract" failures (after classify_request_error).
# text_mutation_rejected (the model rewrote text) and auth/quota/HTTP 4xx are never resent.
GROUPING_ESCALATION_CATEGORIES = frozenset({
    'parse_failure', 'format_mismatch', 'empty_response',
    'structured_output_truncated', 'structured_output_truncated_before_answer'})


def _escalate_failed_grouping(jobs, results, fallback_reasons, ordered_segments, global_position, snapshot, *,
                              protect_all_source_boundaries, abort_event, quality_budget, source_offsets,
                              cache_context):
    """Resend batches that fell back on format/truncation once: same model and thinking mode.

    Each batch is resent as two halves with no further retry or split. A half that validates
    replaces that part of the local fallback; a half that fails again keeps the same
    conservative local boundaries as before. Returns rescued batch indexes and new review items.
    """
    import dataclasses
    from ..providers.asr_provider_snapshot import GroupedBatchResult
    from ..providers.provider_input_budget import RetryBudget
    from ..providers.subtitle_request_policy import (retry_thinking, escalation_cue_limit,
                                                     task_escalation_enabled)
    from .ai_boundary_policy import provenance
    candidates = [job for job in jobs if not job[-1] and fallback_reasons.get(job[0]) in GROUPING_ESCALATION_CATEGORIES]
    if not candidates:
        return set(), []
    categories = {}
    for index, *_ in candidates:
        categories[fallback_reasons[index]] = categories.get(fallback_reasons[index], 0) + 1
    count = sum(len(batch) for _, _, batch, *_ in candidates)
    endpoint = snapshot.endpoint()
    level = retry_thinking(snapshot, categories, 'group',
        base_url=endpoint.get('base_url') or endpoint.get('url', ''), endpoint_protocol=snapshot.protocol)
    limit = escalation_cue_limit(len(ordered_segments))
    skipped = ('disabled' if not task_escalation_enabled('group') else
               'configuration_rejected' if abort_event is not None and abort_event.is_set() else
               'no_higher_thinking_level' if level is None else
               'too_many_failures' if count > limit else '')
    event = dict(stage='grouped', candidate_cues=count, candidate_batches=[job[0] for job in candidates],
                 total_cues=len(ordered_segments), cue_limit=limit, categories=categories,
                 current_thinking=snapshot.enable_thinking, thinking_protocol=snapshot.thinking_protocol)
    if skipped:
        record_run_event('ai_escalation_round', skipped_reason=skipped, **event)
        return set(), []
    from ..providers.subtitle_request_policy import escalated_output_tokens
    escalated = dataclasses.replace(snapshot, enable_thinking=level,
                                    max_output_tokens=escalated_output_tokens(snapshot, 'group'))
    work = []
    for job in candidates:
        batch = job[2]
        middle = (len(batch) + 1) // 2  # thinking text also uses the output budget
        work.append((job, [batch] if len(batch) == 1 else [batch[:middle], batch[middle:]]))
    requests = sum(len(halves) for _, halves in work)
    budget = RetryBudget(0, total_seconds=float(snapshot.timeout_policy.total) * requests)
    print(f"   [保留思考设置重试] {len(candidates)} 个断句批次格式或截断仍失败，用同一模型与思考设置，"
          f"输出上限 {escalated.max_output_tokens} 再请求一轮（{requests} 个请求）。")
    record_run_event('ai_escalation_round', state='started', thinking=level, requests=requests, **event)
    owner = get_runtime_context()
    resolved, improved, still_failed, extra_reviews, number = set(), [], [], [], 0
    for (index, speaker, batch, dependency, _local_fast), halves in work:
        cues, all_validated, any_ai, reviews_kept = [], True, False, []
        for half in halves:
            if bool(getattr(owner.cancellation_token, 'is_cancelled', False)):
                from ..recognition.service import CancelledError
                raise CancelledError('断句任务已取消。')
            number += 1
            first, last = global_position[half[0].segment_id], global_position[half[-1].segment_id]
            context = {key: [{'id': x.segment_id, 'speaker': x.speaker, 'text': x.text, 'read_only': True} for x in values]
                for key, values in [('before', ordered_segments[max(0, first-2):first]),
                                    ('after', ordered_segments[last+1:last+3])]}
            protected = set(dependency['protected_after']) & {row.segment_id for row in half}
            diag = {'batch_id': f'E{number}', 'parent_batch_id': index}

            def run(half=half, context=context, protected=protected, diag=diag, number=number):
                return call_grouping_api(half, protect_all_source_boundaries=protect_all_source_boundaries,
                    protected_after_segment_ids=protected, firered_tokens=dependency['firered_tokens'],
                    speech_regions=dependency['speech_regions'], abort_event=abort_event,
                    batch_index=f'E{number}', batch_total=requests, _split_depth=STRUCTURED_SPLIT_MAX_DEPTH,
                    provider_snapshot=escalated, batch_diagnostics=diag, _retry_budget=budget,
                    _quality_budget=quality_budget, _source_offsets=source_offsets,
                    _cache_context=cache_context, _read_only_context=context)
            with capture_review_items() as reviews:
                if cache_context is None:
                    value = run()
                else:
                    value = run_cached_api_batch('grouped', cache_context,
                        dict(dependency, batch=_grouping_dependency_segments(half), thinking_escalation=level,
                             protected_after=sorted(protected)),
                        run, encoder=serialize_cues, decoder=deserialize_cues,
                        fallback_categories=('断句回退',), provider_snapshot=escalated, diagnostics=diag,
                        validator=lambda values, half=half, protected=protected: _validate_grouped_sources(half, values,
                            protect_all_source_boundaries=protect_all_source_boundaries,
                            protected_after_source_ids=protected))
            ok = getattr(value, 'origin', '') != 'fallback'
            any_ai = any_ai or ok
            all_validated = all_validated and ok and bool(getattr(value, 'validated', False))
            # A half that fails again is covered by the batch's 断句回退 warning kept below.
            reviews_kept.extend(item for item in reviews if ok or item.get('category') != '断句回退')
            cues.extend(value)
        if not any_ai or not _validate_grouped_sources(batch, cues):
            still_failed.append(index)
            continue
        origin, status = provenance(cues, all_validated)
        results[index] = GroupedBatchResult(cues, validated=all_validated, origin=origin, result_status=status)
        extra_reviews.extend(reviews_kept)
        improved.append(index)
        if all_validated:
            resolved.add(index)
        else:
            still_failed.append(index)
    record_run_event('ai_escalation_round', state='completed', thinking=level, requests=requests,
        succeeded_batches=len(resolved), partly_improved_batches=sorted(set(improved)-resolved),
        failed_batches=sorted(set(still_failed)), resolved_batches=sorted(resolved),
        succeeded_cues=sum(len(job[2]) for job in candidates if job[0] in resolved),
        failed_cues=sum(len(job[2]) for job in candidates if job[0] not in resolved),
        remaining_fallback_batches=sum(index not in resolved for index in fallback_reasons), **event)
    print(f"   [保留思考设置重试] 救回 {len(resolved)} 个断句批次，仍保留本地断句 {len(set(still_failed))} 个。")
    return resolved, extra_reviews


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
    from ..providers.asr_provider_snapshot import task_provider_snapshot, digest, GroupedBatchResult, validate_grouped_text, restore_source_text
    from .cue_cleanup import prepare_effective_sources
    segments = prepare_effective_sources(segments, speech_regions=speech_regions)
    use_ai = bool(use_ai)
    snapshot = (provider_snapshot or task_provider_snapshot("group")) if use_ai else None
    from .segmentation_profiles import current_profile,task_language_tag
    profile=current_profile()
    if profile.strategy!='cjk':
        if profile.strategy=='eojeol':
            from .korean_segmentation import group_korean_with_ai,group_korean
            result=group_korean_with_ai(segments,firered_tokens,snapshot) if use_ai else group_korean(segments,firered_tokens)
        elif profile.strategy=='space':
            from .english_segmentation import group_english_with_ai,group_english
            from .european_text import lexicon
            lex=lexicon(profile.code) if profile.code!='en' else None
            result=group_english_with_ai(segments,firered_tokens,snapshot,lexicon=lex) if use_ai else group_english(segments,firered_tokens,lexicon=lex)
        else:
            result=retain_source_utterances(segments,profile)
        if use_ai and profile.strategy != 'conservative':
            unresolved = {part['source_id'] for cue in result
                          if cue.grouping_origin == 'unresolved' for part in cue.source_spans}
            pending = [dict(batch_id=f'word:{row.segment_id}', source_segment_ids=[row.segment_id],
                            start=row.start, end=row.end, reason='ai_boundary_unresolved')
                       for row in segments if row.segment_id in unresolved]
            get_runtime_context().grouping_pending.extend(pending)
            answer = GroupedBatchResult(result, origin='fallback' if pending else 'ai',
                validated=not pending, data_validated=True,
                result_status='unresolved' if pending else 'ai_accepted')
            answer.pending_ranges = pending
            return answer
        return GroupedBatchResult(result, origin='local', validated=True, data_validated=True)
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
    global_source_offsets, global_cursor = {}, 0
    for segment in ordered_segments:
        global_source_offsets[segment.segment_id] = global_cursor
        global_cursor += display_length(segment.text)
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
    from .grouping_request import grouping_batch_limits, grouping_prompt_key, task_prompt_language
    from .grouping_contract import GroupingContractError, runtime_task_binding, validate_grouping_result
    from ..recognition.grouping_checkpoint import range_dependency, range_key
    from ..recognition.service import CancelledError
    from ..recognition.run_context import context_is_current
    owner = get_runtime_context()
    task_binding = runtime_task_binding(owner)
    journal = owner.task_journal if not owner.recognition_snapshot and not owner.shard_id else None

    def require_active():
        if not context_is_current(owner) or task_binding != runtime_task_binding(owner):
            raise CancelledError("断句任务已被替换。")
        if owner.cancellation_token is not None:
            owner.cancellation_token.raise_if_cancelled()

    prompt_key = grouping_prompt_key(task_prompt_language())
    # 2026-11-25: Japanese requests carry a mark at every phrase edge and Qwen
    # windows are 20-25 s each; a smaller text budget keeps one request to a
    # couple of minutes of dialogue (1.json batch 1 held 521 characters).
    batch_chars = (min(GROUP_API_BATCH_MAX_CHARS, JAPANESE_BATCH_MAX_CHARS)
                   if task_prompt_language() == 'ja' else GROUP_API_BATCH_MAX_CHARS)
    max_rows, max_chars, batch_policy = grouping_batch_limits(ordered_segments,
        max_chars=batch_chars, legacy_max_rows=GROUP_API_BATCH_MAX_CUES)
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
    from ..recognition.evidence_windows import EvidenceWindows
    token_windows, speech_windows = EvidenceWindows(firered_tokens), EvidenceWindows(speech_regions)
    grouping_abort_event = threading.Event()
    from ..providers.provider_input_budget import RetryBudget
    retry_budget=RetryBudget(GROUPING_API_RETRIES-1)
    quality_budget=QualityRetryBudget()
    for index, (speaker, batch, local_fast) in enumerate(batches, 1):
        # Alignment diagnostics are observations, not semantic cache inputs.
        # The first unaligned run may add one without changing text or timing.
        serialized_batch = _grouping_dependency_segments(batch)
        local_tokens=token_windows.between(min(row.start for row in batch)-2.,max(row.end for row in batch)+2.)
        local_speech=speech_windows.between(min(row.start for row in batch)-2.,max(row.end for row in batch)+2.)
        local_protected=interrupted_after & {row.segment_id for row in batch}
        dependency = {
            "use_ai": use_ai,
            "batch_protocol": prompt_key,
            "batch_policy": batch_policy,
            "local_fast": local_fast,
            "speaker": speaker,
            "batch": serialized_batch,
            "protect_all": bool(protect_all_source_boundaries),
            "protected_after": sorted(local_protected),
            "firered_tokens": local_tokens,
            "speech_regions": local_speech,
            "input_content_hash": digest([item.text for item in batch]),
            "boundaries_hash": digest({"protect_all": bool(protect_all_source_boundaries),
                                       "protected_after": sorted(local_protected),
                                       "source_boundaries": sorted(source_segment_character_offsets(batch))}),
        }
        jobs.append((index, speaker, batch, dependency, local_fast))
    quality_budget.register_batches(index for index, *_ in jobs)
    fallback_reasons = {}

    def execute_job(job):
        index, speaker, batch, dependency, local_fast = job
        require_active()
        _batch_trace.batch_id = index
        batch_tokens=dependency['firered_tokens']
        batch_speech=dependency['speech_regions']
        batch_protected=set(dependency['protected_after'])
        validation_args = dict(protect_all_source_boundaries=protect_all_source_boundaries,
                               protected_after_source_ids=batch_protected)
        checkpoint_key = range_key(owner, index)
        checkpoint_binding = range_dependency(owner, dependency, snapshot)
        if journal is not None and owner.resume and not owner.force_refresh_group_cache:
            receipt = journal.load_artifact(checkpoint_key, checkpoint_binding)
            if receipt:
                cached = GroupedBatchResult(deserialize_cues(receipt['cues']), origin=receipt['origin'],
                    validated=receipt['validated'], data_validated=True, result_status=receipt['result_status'])
                if _validate_grouped_sources(batch, cached, **validation_args):
                    require_active()
                    record_run_event('grouping_range_reused', batch_index=index, source_rows=len(batch))
                    return index, cached, receipt['reviews']
        print(f"   断句批次 {index}/{len(batches)}，说话人 {speaker}")
        record_run_event("cloud_batch_started", stage="grouped" if use_ai else "grouped_local",
                         batch_index=index, batch_total=len(batches), cue_count=len(batch))
        started_at = time.perf_counter()
        batch_diag = {"batch_id": index, "scheduler_queue_wait_ms": round((started_at-dispatched_at)*1000, 3),
                      'scheduler_submitted_monotonic': dispatched_at,
                      'scheduler_started_monotonic': started_at}

        def run_group_batch():
            if local_fast:
                result = retain_source_utterances(batch, profile)
                for cue in result:
                    cue.grouping_origin = 'source_unchanged_short'
                record_run_event('grouping_local_fast_path', source_ids=[x.segment_id for x in batch],
                    reason='finished_short_protected_utterance', input_characters=sum(display_length(x.text) for x in batch))
                return GroupedBatchResult(result, origin='local_fast', validated=True)
            if not use_ai:
                result = fallback_group(batch, batch_tokens, batch_speech)
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
                protected_after_segment_ids=batch_protected,
                firered_tokens=batch_tokens,
                speech_regions=batch_speech,
                abort_event=grouping_abort_event,
                batch_index=index,
                batch_total=len(batches),
                provider_snapshot=snapshot,
                batch_diagnostics=batch_diag,
                _retry_budget=retry_budget,
                _quality_budget=quality_budget,
                _source_offsets=global_source_offsets,
                _cache_context=cache_context,
                _read_only_context=context,
            )
        with capture_review_items() as review_items:
            try:
                batch_cues = run_group_batch() if cache_context is None else run_cached_api_batch(
                    "grouped" if use_ai and not local_fast else "grouped_local",
                    cache_context,
                    dependency,
                    run_group_batch,
                    encoder=serialize_cues,
                    decoder=(lambda values: GroupedBatchResult(deserialize_cues(values), origin='local_fast', validated=True)) if local_fast else deserialize_cues,
                    fallback_categories=("断句回退",),
                    provider_snapshot=snapshot,
                    validator=lambda values: _validate_grouped_sources(batch, values, **validation_args),
                    diagnostics=batch_diag,
                )
                validate_grouping_result(batch, batch_cues, **validation_args)
            except GroupingContractError as error:
                if error.category in {'stale_source', 'source_identity'}:
                    raise
                batch_cues = _retain_grouping_range(batch, error, index)
        require_active()
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
            result_status=getattr(batch_cues, "result_status", "local_fallback" if getattr(batch_cues, "origin", "") == "fallback" else "cloud_direct" if getattr(batch_cues, "origin", "") == "ai" else "local"),
            scheduler_queue_wait_ms=batch_diag.get('scheduler_queue_wait_ms'),
            scheduler_submitted_monotonic=dispatched_at,
            scheduler_started_monotonic=started_at,
            scheduler_finished_monotonic=time.perf_counter(),
            validator_result="exact_text_and_boundaries" if getattr(batch_cues, "validated", False) else "not_validated_ai",
        )
        # 2026-10-15: each batch's subtitle lines show while the step runs.
        record_run_event("cloud_batch_preview", stage="grouped" if use_ai else "grouped_local",
            batch_index=index, batch_total=len(batches), rows=[dict(
                start=round(float(cue.start), 3), end=round(float(cue.end), 3),
                text=str(cue.text or ''), state='grouped' if _grouping_range_is_complete(batch_cues, use_ai)
                else 'grouping_pending') for cue in batch_cues if str(cue.text or '').strip()])
        if getattr(batch_cues, 'origin', '') == 'fallback':
            fallback_reasons[index] = batch_diag.get('fallback_reason')
        if journal is not None and _grouping_range_is_complete(batch_cues, use_ai):
            journal.publish(checkpoint_key, dict(cues=serialize_cues(batch_cues), reviews=review_items,
                origin=getattr(batch_cues, 'origin', 'local'), validated=getattr(batch_cues, 'validated', False),
                result_status=getattr(batch_cues, 'result_status', 'local')), checkpoint_binding)
        return index, batch_cues, review_items

    def run_job(job):
        try:
            return execute_job(job)
        finally:
            quality_budget.finish_batch(job[0])

    results = {}
    batch_reviews = []
    from ..system.task_resources import cloud_request_workers
    workers = (
        min(cloud_request_workers(snapshot,CLOUD_BATCH_WORKERS), len(jobs))
        if use_ai and PARALLEL_CLOUD_BATCHES
        else 1
    )
    from ..providers.provider_service import GLOBAL_PROVIDER_SERVICE
    capacity = GLOBAL_PROVIDER_SERVICE.scheduling_capacity() if use_ai else {"effective_workers": 1}
    configured_workers = workers
    workers = max(1, min(workers, capacity["effective_workers"]))
    if max_workers is not None:
        workers = max(1, min(workers, int(max_workers)))
    record_run_event("grouping_batch_plan", prompt_version=prompt_key,
        batch_policy=batch_policy, max_rows=max_rows, max_characters=max_chars,
        batch_count=len(jobs), configured_workers=configured_workers,
        scheduler_workers=workers, provider_capacity=capacity)

    dispatched_at = time.perf_counter()
    if workers > 1:
        from ..recognition.run_context import ContextExecutor as ThreadPoolExecutor, bounded_results

        print(f"   [并行加速] {len(jobs)} 个断句批次，最多 {workers} 路并发。")
        record_run_event(
            "cloud_batches_parallel",
            stage="grouped",
            batches=len(jobs),
            workers=workers,
        )
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="glm-group") as pool:
            for index, batch_cues, review_items in bounded_results(pool, run_job, jobs,
                    limit=workers, before_submit=require_active):
                results[index] = batch_cues
                batch_reviews.append((index, review_items))
    else:
        for job in jobs:
            index, batch_cues, review_items = run_job(job)
            results[index] = batch_cues
            batch_reviews.append((index, review_items))
    require_active()
    # Review items wait for the thinking-escalation round: a batch it rescued must not keep
    # its 断句回退 warning.
    resolved_batches, escalation_reviews = (_escalate_failed_grouping(
        jobs, results, fallback_reasons, ordered_segments, global_position, snapshot,
        protect_all_source_boundaries=protect_all_source_boundaries, abort_event=grouping_abort_event,
        quality_budget=quality_budget, source_offsets=global_source_offsets, cache_context=cache_context)
        if use_ai and snapshot is not None else (set(), []))
    for index, review_items in batch_reviews:
        extend_review_items([item for item in review_items if index not in resolved_batches
                             or item.get('category') != '断句回退'])
    extend_review_items(escalation_reviews)
    require_active()
    if journal is not None and resolved_batches:
        for index, _, _, dependency, _ in jobs:
            if index in resolved_batches:
                value = results[index]
                journal.publish(range_key(owner, index), dict(cues=serialize_cues(value),
                    reviews=[], origin=value.origin, validated=value.validated,
                    result_status=value.result_status), range_dependency(owner, dependency, snapshot))
    for index in sorted(results):
        cues.extend(results[index])
    final_quality_issues = []
    if _quality_enabled():
        try:
            source_index = SourceIndex.build("".join(s.text for s in ordered_segments))
            if not source_index.content:
                raise ValueError('来源没有可编号正文。')
        except ValueError as error:
            final_quality_issues = [dict(kind='index_unit_mismatch',reason=str(error))]
            for cue in cues:
                cue.timing_basis='quality=grouping-quality-v1;domain=source_segment;review=index_unit_mismatch'
            record_run_event('grouping_quality_review',issues=final_quality_issues,
                source_segment_ids=[s.segment_id for s in ordered_segments])
            add_review_item(ordered_segments[0].start,'断句索引待复核',
                '当前字符索引无法安全细分此正文，保留来源文字与段级时间。',
                "".join(s.text for s in ordered_segments),priority=3,severity='warning')
        else:
            offsets, cursor = [], 0
            for cue in cues:
                cursor += display_length(cue.text)
                offsets.append(cursor)
            # Batch results are already validated and own their boundaries.
            # Reconstructing here used to silently resegment accepted windows.
            if use_ai:
                from .ai_boundary_policy import inspect
                from .ai_boundary_policy import blocking_issues
                final_quality_issues=blocking_issues(
                    inspect(quality_for_segments(ordered_segments,firered_tokens),offsets))
            else:
                cues, _, final_quality_issues = cues_from_quality(ordered_segments, offsets, firered_tokens, record=record_run_event)
    elif not use_ai:
        if _restore_grouped_source(ordered_segments, copy.deepcopy(cues)):
            cues = _contract_safe_pass('merge_same_speaker_dangling_cues', merge_same_speaker_dangling_cues,
                                       cues, ordered_segments)
            cues = _contract_safe_pass('merge_isolated_two_character_cues', merge_isolated_two_character_cues,
                                       cues, ordered_segments)
            cues = _contract_safe_pass('repair_mid_word_adjacent_cues',
                                       lambda items: repair_mid_word_adjacent_cues(items, ordered_segments, firered_tokens),
                                       cues, ordered_segments)
            cues = _contract_safe_pass('merge_hanging_attribute_cues', merge_hanging_attribute_cues,
                                       cues, ordered_segments)
        else:
            cues = merge_same_speaker_dangling_cues(cues)
            cues = merge_isolated_two_character_cues(cues)
            cues = repair_mid_word_adjacent_cues(cues, ordered_segments, firered_tokens)
            cues = merge_hanging_attribute_cues(cues)
    postprocess_fallback = not _restore_grouped_source(ordered_segments, cues)
    if postprocess_fallback:
        record_run_event("grouping_postprocess_rejected", reason="source_contract_failed")
        if use_ai:
            cues = _retain_grouping_range(ordered_segments, '最终来源校验未通过，保留来源字幕。')
        else:
            cues = fallback_group(ordered_segments, firered_tokens, speech_regions)
        add_review_item(ordered_segments[0].start, "断句回退",
            "断句后处理未通过检查，已保留原语音段文字与时间。", "",
            priority=3, severity="warning")
    cues.sort(key=lambda cue: (cue.start, cue.end, cue.speaker))
    if use_ai:
        validate_grouping_result(ordered_segments, cues)
    elif not _validate_grouped_sources(ordered_segments, cues):
        postprocess_fallback = True
        cues = fallback_group(ordered_segments, firered_tokens, speech_regions)
    for cue_id, cue in enumerate(cues, 1):
        cue.cue_id = cue_id
    from .grouping_contract import attach_grouping_spans
    attach_grouping_spans(ordered_segments,cues)
    pending = []
    for index, _, batch, _, _ in jobs:
        value = results[index]
        if not postprocess_fallback and _grouping_range_is_complete(value, use_ai):
            continue
        localized = {}
        if not postprocess_fallback:
            for cue in value:
                if getattr(cue, 'grouping_origin', '') != 'unresolved':
                    continue
                for receipt in getattr(cue, 'grouping_boundary_receipt', {}).get('repairs', ()):
                    if receipt['origin'] != 'unresolved':
                        continue
                    key = (receipt['content_start'], receipt['content_end'])
                    entry = localized.setdefault(key, dict(batch_id=index, content_span=list(key),
                        start=cue.start, end=cue.end, source_segment_ids=set(), reason=receipt['reason'],
                        issues=receipt['remaining_issues']))
                    entry['start'] = min(entry['start'], cue.start)
                    entry['end'] = max(entry['end'], cue.end)
                    entry['source_segment_ids'].update(part['source_id'] for part in cue.source_spans)
        if localized:
            pending.extend(dict(item, source_segment_ids=sorted(item['source_segment_ids']))
                           for item in localized.values())
            continue
        details = [getattr(cue, 'grouping_boundary_receipt', {}) for cue in value
                   if getattr(cue, 'grouping_origin', '') == 'source_retained_after_local_rejection']
        pending.append(dict(batch_id=index, source_segment_ids=[row.segment_id for row in batch],
                            start=min(row.start for row in batch), end=max(row.end for row in batch),
                            reason=next((item['reason'] for item in details if item.get('reason')),
                                        fallback_reasons.get(index) or getattr(value, 'result_status', 'local_fallback'))))
    if pending:
        for item in pending:
            add_review_item(item['start'], '断句待重试', '此范围已保留可审阅字幕，仍需完成断句。', priority=3,
                severity='warning', batch_id=item['batch_id'], reason=item['reason'],
                source_segment_ids=item['source_segment_ids'])
        record_run_event('grouping_partial', pending_ranges=pending,
                         retained_batches=len(results)-len({item['batch_id'] for item in pending}), status='pending_retry')
    owner.grouping_pending.extend(pending)
    origins = {getattr(value, 'origin', 'fallback') for value in results.values()}
    all_validated = bool(use_ai) and not pending and not postprocess_fallback and not final_quality_issues and all(getattr(value, 'validated', False) for value in results.values())
    origin = 'ai' if all_validated and origins <= {'ai'} else 'local_fast' if all_validated and origins <= {'local_fast'} else 'mixed' if all_validated else 'fallback' if use_ai else 'local'
    record_run_event('cloud_batches_completed', stage='grouped' if use_ai else 'grouped_local',
        job_id=get_runtime_context().job_id, started_monotonic=dispatched_at,
        finished_monotonic=time.perf_counter(), elapsed_seconds=round(time.perf_counter()-dispatched_at,3),
        scheduler_workers=workers, configured_workers=configured_workers,
        provider_capacity=capacity, batch_policy=batch_policy, prompt_version=prompt_key,
        batch_count=len(jobs), remote_batch_count=sum(not job[-1] for job in jobs) if use_ai else 0,
        local_fast_batch_count=sum(bool(job[-1]) for job in jobs), protected_turn_count=len(turns),
        quality_retry_outcomes=quality_budget.summary(),result_origin=origin)
    if use_ai:
        record_run_event('grouping_origin_summary', **grouping_origin_summary(cues))
    from .grouping_contract import capture_grouping_source
    grouped = GroupedBatchResult(cues, origin=origin, validated=all_validated,data_validated=True,
        source_fingerprint=capture_grouping_source(ordered_segments).fingerprint,
        result_status='unresolved' if final_quality_issues or any(getattr(v,'result_status','')=='unresolved' for v in results.values())
            else 'ai_targeted_correction' if any(getattr(v,'result_status','')=='ai_targeted_correction' for v in results.values())
            else 'ai_accepted' if all_validated else 'unresolved' if use_ai else 'local')
    grouped.pending_ranges = pending
    return grouped


def _grouping_range_is_complete(value, use_ai):
    return (getattr(value, 'result_status', '') != 'unresolved'
            and (not use_ai or bool(getattr(value, 'validated', False))))
