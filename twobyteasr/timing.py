"""timing stage implementation extracted from subtitle_core."""

# The core owns runtime configuration; these imports preserve the existing public contract.
from subtitle_core import *  # noqa: F401,F403
from twobyteasr.runtime import get_runtime_context
from twobyteasr.text_similarity import phonetic_text

__all__ = [
    'normalize_cue_times',
    'repair_overlong_cues_from_source',
    'build_local_source_cues',
    'snap_cue_starts_to_vad_onsets',
    'extend_cue_tails_by_speaker',
    'bridge_short_display_gaps',
    'firered_anchor_coverage',
    'collect_review_items',
]


def repair_overlong_cues_from_source(cues, segments, firered_tokens=()):
    """Restore source boundaries when a grouped cue violates final hard limits.

    Grouping is only allowed to change boundaries, never source text.  Therefore an
    invalid long cue can be repaired deterministically by matching its text to the
    original same-speaker segments and restoring those segment boundaries.  This
    also makes old bad grouping caches recoverable without another cloud request.
    """
    if not cues:
        return cues

    ordered_segments = sorted(
        segments,
        key=lambda item: (item.start, item.end, item.segment_id),
    )
    repaired = []
    repaired_count = 0
    tolerance = 0.06
    for cue in sorted(
        cues,
        key=lambda item: (item.start, item.end, item.speaker or "S00", item.cue_id),
    ):
        duration = cue.end - cue.start
        if (
            display_length(cue.text) <= COMPLETE_PHRASE_SOFT_MAX_CHARS
            and duration <= MAX_SUBTITLE_SECONDS + 0.05
            and cue.end > cue.start
        ):
            repaired.append(cue)
            continue

        speaker = cue.speaker or "S00"
        candidates = [
            segment
            for segment in ordered_segments
            if (segment.speaker or "S00") == speaker
            and segment.start >= cue.start - tolerance
            and segment.end <= cue.end + tolerance
            and segment.end > segment.start
        ]
        source_text = content_only("".join(segment.text for segment in candidates))
        cue_text = content_only(cue.text)
        if not candidates or source_text != cue_text:
            repaired.extend(_repair_cue_on_own_timeline(cue))
            repaired_count += 1
            continue

        for segment in candidates:
            segment_duration = segment.end - segment.start
            if (
                display_length(segment.text) <= COMPLETE_PHRASE_SOFT_MAX_CHARS
                and segment_duration <= MAX_SUBTITLE_SECONDS + 0.05
            ):
                pieces = [
                    SubtitleCue(
                        cue_id=0,
                        start=float(segment.start),
                        end=float(segment.end),
                        text=clean_subtitle_text(segment.text),
                    )
                ]
            else:
                units = _segment_content_timeline(segment, firered_tokens)
                pieces = _locally_repair_resegmented_cue(segment.text, units)
            for piece in pieces:
                piece.timing_locked = bool(
                    cue.timing_locked or segment.timing_locked
                )
                piece.speaker = speaker
                repaired.append(piece)
        repaired_count += 1

    repaired.sort(
        key=lambda item: (item.start, item.end, item.speaker or "S00", item.cue_id)
    )
    for cue_id, cue in enumerate(repaired, 1):
        cue.cue_id = cue_id
    if repaired_count:
        print(
            f"   [时间轴自愈] {repaired_count} 条超限字幕已按原始同主播语音段恢复，"
            "无需重新请求云端模型。"
        )
        record_run_event(
            "overlong_cue_source_repair",
            repaired=repaired_count,
            cue_total=len(repaired),
        )
    return repaired


def _repair_cue_on_own_timeline(cue):
    """Last-resort split that conserves a cue's text when source matching fails."""
    chars = content_exact(cue.text)
    count = len(chars)
    if count <= 0 or cue.end <= cue.start:
        return [cue]
    if count == 1:
        return [
            SubtitleCue(
                cue_id=0,
                start=float(cue.start),
                end=min(float(cue.end), float(cue.start) + MAX_SUBTITLE_SECONDS),
                text=clean_subtitle_text(cue.text),
                timing_locked=bool(cue.timing_locked),
                speaker=cue.speaker or "S00",
            )
        ]
    duration = max(MIN_SUBTITLE_SECONDS, float(cue.end) - float(cue.start))
    step = duration / count
    units = [
        WordUnit(
            float(cue.start) + step * index,
            float(cue.start) + step * (index + 1),
            char,
            0.0,
        )
        for index, char in enumerate(chars)
    ]
    try:
        pieces = _locally_repair_resegmented_cue(cue.text, units)
    except ValueError:
        # Extremely sparse ASR output can assign more than five seconds to a
        # single character. Preserve every character and cap only display time.
        pieces = []
        for index, char in enumerate(chars):
            start = float(cue.start) + step * index
            pieces.append(
                SubtitleCue(0, start, min(start + MAX_SUBTITLE_SECONDS, start + step), char)
            )
    for piece in pieces:
        piece.speaker = cue.speaker or "S00"
        piece.timing_locked = bool(cue.timing_locked)
    return pieces


def _segment_content_timeline(*args, **kwargs):
    """延迟导入：见 _firered_token_start 的说明——这两个符号定义在
    segmentation/segmentation_alignment 尾部，经 segmentation 的尾部回写
    才进入 subtitle_core；本模块顶部 star import 的时机早于该回写。"""
    from twobyteasr.segmentation_alignment import segment_content_timeline

    return segment_content_timeline(*args, **kwargs)


def _locally_repair_resegmented_cue(*args, **kwargs):
    from twobyteasr.segmentation import locally_repair_resegmented_cue

    return locally_repair_resegmented_cue(*args, **kwargs)


def build_local_source_cues(segments, firered_tokens=()):
    """Rebuild a conservative cue list from source segments with no cloud output."""
    cues = []
    ordered = sorted(
        segments,
        key=lambda item: (item.start, item.end, item.segment_id),
    )
    for segment in ordered:
        duration = float(segment.end) - float(segment.start)
        if (
            display_length(segment.text) <= COMPLETE_PHRASE_SOFT_MAX_CHARS
            and duration <= MAX_SUBTITLE_SECONDS + 0.05
            and segment.end > segment.start
        ):
            pieces = [
                SubtitleCue(
                    cue_id=0,
                    start=float(segment.start),
                    end=float(segment.end),
                    text=clean_subtitle_text(segment.text),
                )
            ]
        else:
            units = _segment_content_timeline(segment, firered_tokens)
            pieces = _locally_repair_resegmented_cue(segment.text, units)
        for piece in pieces:
            piece.speaker = segment.speaker or "S00"
            piece.timing_locked = bool(segment.timing_locked)
            cues.append(piece)
    for cue_id, cue in enumerate(cues, 1):
        cue.cue_id = cue_id
    return cues

def normalize_cue_times(cues, timeline_fps=TIMELINE_FPS):
    minimum_frames = max(1, int(round(MIN_SUBTITLE_SECONDS * timeline_fps)))
    max_duration_frames = max(1, int(round(MAX_SUBTITLE_SECONDS * timeline_fps)))

    def budgeted_minimum_frames(cue):
        # 碰撞推挤/量化可能把多条字幕压成 0.35s 阶梯串（23~43 字/秒闪现）。
        # 每条至少要拿到“字数/阅读率”的时长，上限仍守 5 秒。
        length = display_length(cue.text)
        if length <= 0:
            return minimum_frames
        reading_frames = int(round(length / NORMALIZE_MAX_CHARS_PER_SECOND * timeline_fps))
        return max(
            minimum_frames,
            min(max_duration_frames, reading_frames),
        )

    for cue in cues:
        start_frame = max(0, int(round(max(0.0, cue.start) * timeline_fps)))
        end_frame = int(round(max(cue.end, cue.start) * timeline_fps))
        end_frame = max(end_frame, start_frame + budgeted_minimum_frames(cue))
        cue.start = start_frame / timeline_fps
        cue.end = end_frame / timeline_fps

    # 只在同一说话人内部消除字幕碰撞。不同主播同时说话是有效重叠，
    # 分轨后必须同时保留，不能用 S02 的起点截断 S01 的尾句。
    minimum_seconds = minimum_frames / timeline_fps
    speaker_rows = {}
    for cue in cues:
        speaker_rows.setdefault(cue.speaker or "S00", []).append(cue)
    for rows in speaker_rows.values():
        # cue_id follows the conserved source-text order.  Overlapping MOSS chunks
        # can give a later phrase an earlier acoustic start; sorting by raw time
        # would silently move that phrase in front of its predecessor.  Repair the
        # timestamps in source order instead, then chronological export remains safe.
        rows.sort(key=lambda cue: (cue.cue_id, cue.start, cue.end))
        for previous, current in zip(rows, rows[1:]):
            if previous.end > current.start:
                if (
                    current.timing_locked
                    and current.start - previous.start >= minimum_seconds
                ):
                    previous.end = current.start
                elif previous.timing_locked:
                    current.start = previous.end
                    current.end = max(
                        current.end,
                        previous.end + budgeted_minimum_frames(current) / timeline_fps,
                    )
                elif current.start - previous.start >= minimum_seconds:
                    previous.end = current.start
                else:
                    current.start = previous.end
                    current.end = max(
                        current.end,
                        previous.end + budgeted_minimum_frames(current) / timeline_fps,
                    )

            gap = current.start - previous.end
            if (
                0.0 < gap <= MAX_CUE_HOLD_GAP_SECONDS
                and current.start - previous.start <= MAX_HELD_SUBTITLE_SECONDS
                and not previous.timing_locked
            ):
                previous.end = current.start
    return cues


def snap_cue_starts_to_vad_onsets(
    cues,
    speech_regions,
    timeline_fps=TIMELINE_FPS,
):
    """句首在明确静音区时向后贴到下一次起音；绝不把字幕向前移动。"""
    if not cues or not speech_regions:
        return cues
    regions = sorted(
        (
            max(0.0, float(item["start"])),
            max(0.0, float(item["end"])),
        )
        for item in speech_regions
        if float(item["end"]) > float(item["start"])
    )
    changed = 0
    shifts = []
    for cue in cues:
        if cue.timing_locked:
            continue
        start = float(cue.start)
        inside_speech = any(
            region_start - VAD_ONSET_CONTAINMENT_PAD_SECONDS
            <= start
            <= region_end + VAD_ONSET_CONTAINMENT_PAD_SECONDS
            for region_start, region_end in regions
        )
        if inside_speech:
            continue
        next_start = next(
            (region_start for region_start, _ in regions if region_start > start),
            None,
        )
        if next_start is None:
            continue
        lead = next_start - start
        if not (
            VAD_ONSET_SNAP_MIN_LEAD_SECONDS
            <= lead
            <= VAD_ONSET_SNAP_MAX_LEAD_SECONDS
        ):
            continue
        snapped_frame = int(round(next_start * timeline_fps))
        snapped_start = snapped_frame / timeline_fps
        if cue.end - snapped_start < MIN_SUBTITLE_SECONDS:
            continue
        cue.start = snapped_start
        changed += 1
        shifts.append(lead)
        add_review_item(
            cue.start,
            "句首VAD校准",
            f"字幕原句首位于静音区，向后校准 {lead * 1000:.0f}ms",
            cue.text,
            priority=1,
        )
    if changed:
        print(
            f"   [句首时间校准] {changed}/{len(cues)} 条从静音区向后贴到实际起音；"
            f"最大校准 {max(shifts) * 1000:.0f}ms，不会把任何字幕提前。"
        )
        record_run_event(
            "vad_onset_snap",
            changed=changed,
            total=len(cues),
            maximum_shift_ms=round(max(shifts) * 1000),
        )
    return cues


def extend_cue_tails_by_speaker(
    cues,
    audio_seconds,
    timeline_fps=TIMELINE_FPS,
):
    """每条分轨字幕尾点增加200ms；同一说话人的下一条出现时立即让位。"""
    if not cues:
        return cues
    tail_frames = max(1, int(round(ISOLATED_CUE_TAIL_SECONDS * timeline_fps)))
    audio_end_frame = max(0, int(round(float(audio_seconds) * timeline_fps)))
    max_duration_frames = max(1, int(round(MAX_SUBTITLE_SECONDS * timeline_fps)))
    speaker_rows = {}
    for cue in cues:
        speaker_rows.setdefault(cue.speaker or "S00", []).append(cue)
    changed = 0
    largest_added_frames = 0
    for rows in speaker_rows.values():
        rows.sort(key=lambda cue: (cue.start, cue.end, cue.cue_id))
        for index, current in enumerate(rows):
            start_frame = int(round(current.start * timeline_fps))
            end_frame = int(round(current.end * timeline_fps))
            next_start_frame = (
                int(round(rows[index + 1].start * timeline_fps))
                if index + 1 < len(rows)
                else audio_end_frame
            )
            target_end_frame = min(
                end_frame + tail_frames,
                next_start_frame,
                audio_end_frame,
                start_frame + max_duration_frames,
            )
            if target_end_frame <= end_frame:
                continue
            added_frames = target_end_frame - end_frame
            if added_frames > tail_frames:
                raise RuntimeError("字幕尾帧延长超过 200ms 护栏，已停止写入。")
            current.end = target_end_frame / timeline_fps
            largest_added_frames = max(largest_added_frames, added_frames)
            changed += 1
    if changed:
        print(
            f"   [完成] 分轨字幕尾帧：{changed}/{len(cues)} 条延长最多 "
            f"{ISOLATED_CUE_TAIL_SECONDS * 1000:.0f}ms；同主播下一条出现时自动让位。"
        )
        record_run_event(
            "cue_tail_extension",
            changed=changed,
            total=len(cues),
            maximum_added_ms=round(largest_added_frames / timeline_fps * 1000),
        )
    return cues


def bridge_short_display_gaps(
    cues,
    audio_seconds,
    timeline_fps=TIMELINE_FPS,
):
    """补齐全轨可见字幕间不足 500ms 的空白，不移动下一条句首。"""
    if len(cues) < 2:
        return cues
    rows = sorted(cues, key=lambda cue: (cue.start, cue.end, cue.speaker, cue.cue_id))
    bridge_frames = max(
        1,
        int(round(SHORT_DISPLAY_GAP_BRIDGE_SECONDS * timeline_fps)),
    )
    audio_end_frame = max(0, int(round(float(audio_seconds) * timeline_fps)))
    max_duration_frames = max(1, int(round(MAX_SUBTITLE_SECONDS * timeline_fps)))

    coverage_owner = rows[0]
    coverage_end_frame = int(round(rows[0].end * timeline_fps))
    changed = 0
    largest_gap_frames = 0
    for cue in rows[1:]:
        start_frame = max(0, int(round(cue.start * timeline_fps)))
        end_frame = max(start_frame, int(round(cue.end * timeline_fps)))
        if start_frame > coverage_end_frame:
            gap_frames = start_frame - coverage_end_frame
            owner_start_frame = max(
                0,
                int(round(coverage_owner.start * timeline_fps)),
            )
            target_end_frame = min(
                start_frame,
                audio_end_frame,
                owner_start_frame + max_duration_frames,
            )
            if gap_frames <= bridge_frames and target_end_frame == start_frame:
                coverage_owner.end = target_end_frame / timeline_fps
                coverage_end_frame = target_end_frame
                changed += 1
                largest_gap_frames = max(largest_gap_frames, gap_frames)
        if end_frame > coverage_end_frame:
            coverage_owner = cue
            coverage_end_frame = end_frame

    if changed:
        maximum_gap_ms = round(largest_gap_frames / timeline_fps * 1000)
        print(
            f"   [短间隙衔接] 补齐 {changed} 处小于等于 "
            f"{SHORT_DISPLAY_GAP_BRIDGE_SECONDS * 1000:.0f}ms 的全轨空白；"
            f"最大 {maximum_gap_ms}ms，不移动下一条句首。"
        )
        record_run_event(
            "short_display_gap_bridge",
            changed=changed,
            maximum_gap_ms=maximum_gap_ms,
            threshold_ms=round(SHORT_DISPLAY_GAP_BRIDGE_SECONDS * 1000),
        )
    return cues


def _firered_token_start(token):
    """延迟导入：firered_token_start 定义在 segmentation_alignment 尾部，
    经 segmentation 的尾部回写才进入 subtitle_core。本模块顶部 ``import *``
    的时机早于该回写（循环导入时序），直接顶部导入或使用泄漏名会在特定
    入口顺序下 NameError；调用时导入则所有模块都已初始化完毕。"""
    from twobyteasr.segmentation_alignment import firered_token_start

    return firered_token_start(token)


def firered_anchor_coverage(segment, firered_tokens=()):
    target = [phonetic_text(char) or char.lower() for char in content_only(segment.text)]
    candidates = []
    for token in firered_tokens or ():
        start = _firered_token_start(token)
        end = max(start + 0.001, float(token["end"]))
        if (
            start > segment.end + FIRERED_EFFECTIVE_TOKEN_OUTSIDE_TOLERANCE_SECONDS
            or end < segment.start - FIRERED_EFFECTIVE_TOKEN_OUTSIDE_TOLERANCE_SECONDS
        ):
            continue
        for char in content_only(token.get("text", "")):
            candidates.append(phonetic_text(char) or char.lower())
    if not target or not candidates:
        return {
            "coverage": 0.0,
            "largest": 0.0,
            "missing_prefix": len(target),
            "missing_suffix": len(target),
        }
    matcher = SequenceMatcher(None, candidates, target, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size]
    matched = sum(block.size for block in blocks)
    largest = max((block.size for block in blocks), default=0)
    first = blocks[0] if blocks else None
    last = blocks[-1] if blocks else None
    return {
        "coverage": matched / len(target),
        "largest": largest / len(target),
        "missing_prefix": first.b if first else len(target),
        "missing_suffix": len(target) - (last.b + last.size) if last else len(target),
    }


def collect_review_items(segments, cues, speech_regions, firered_tokens=()):
    """收集值得人工扫一眼的位置，不修改字幕，也不写第三个文件。"""
    anchor_coverages = []
    for segment in segments:
        text = content_only(segment.text)
        if len(text) >= 3 and segment.confidence < REVIEW_LOW_CONFIDENCE:
            add_review_item(
                segment.start,
                "低置信度",
                f"MOSS 主稿的 FireRed 支持度 {segment.confidence:.2f}",
                segment.text,
                priority=2,
            )
        supports = [
            content_only(value)
            for value in (
                segment.moss_text,
                segment.alternate_text,
                segment.qwen_asr_text,
                segment.firered_llm_text,
            )
            if content_only(value)
        ]
        if text and supports and segment.confidence < 0.60:
            similarity = max(
                SequenceMatcher(None, text, support, autojunk=False).ratio()
                for support in supports
            )
            if similarity < 0.62:
                add_review_item(
                    segment.start,
                    "ASR分歧",
                    f"多套识别一致度仅 {similarity:.0%}",
                    segment.text,
                    priority=2,
                )

        anchor = firered_anchor_coverage(segment, firered_tokens)
        anchor_coverages.append(anchor["coverage"])
        if len(text) >= 4 and (
            anchor["coverage"] < 0.55 or anchor["largest"] < 0.30
        ):
            add_review_item(
                segment.start,
                "时间锚覆盖低",
                (
                    f"FireRed 字锚覆盖 {anchor['coverage']:.0%}，"
                    f"最长连续 {anchor['largest']:.0%}，"
                    f"缺段首/段尾 {anchor['missing_prefix']}/{anchor['missing_suffix']} 字；"
                    "该段使用 MOSS 外边界回退"
                ),
                segment.text,
                priority=2,
                severity="info",
            )

    if anchor_coverages:
        usable = sum(value >= 0.55 for value in anchor_coverages)
        print(
            f"   [时间锚覆盖] {usable}/{len(anchor_coverages)} 段达到 55%，"
            f"中位覆盖 {median(anchor_coverages):.0%}；低覆盖段已加入复核清单。"
        )

    for left, right in zip(cues, cues[1:]):
        left_text = content_only(left.text)
        right_text = content_only(right.text)
        if not left_text or not right_text:
            continue
        near_contiguous = (
            left.speaker == right.speaker
            and right.start - left.end <= 0.10
        )
        # 口语里“别电弧了好吗 / 别电弧了”这类包含关系经常是有意重复；
        # 这里只提示逐字相同的相邻字幕，避免长视频出现大量误报。
        duplicate = len(left_text) >= 3 and left_text == right_text
        if near_contiguous and duplicate:
            add_review_item(
                right.start,
                "疑似重复",
                "相邻字幕相同或高度包含",
                f"{left.text} / {right.text}",
                priority=3,
            )

    recent_repetitions = {}
    for cue in cues:
        text = content_only(cue.text)
        if len(text) < 5:
            continue
        previous_occurrences = [
            item
            for item in recent_repetitions.get(text, [])
            if cue.start - item.end <= 8.0
        ]
        if len(previous_occurrences) >= 2:
            add_review_item(
                cue.start,
                "疑似重复",
                "8秒内第3次出现完全相同长句；仅提示，不自动删除",
                cue.text,
                priority=2,
            )
        previous_occurrences.append(cue)
        recent_repetitions[text] = previous_occurrences

    for cue in cues:
        duration = max(0.001, cue.end - cue.start)
        length = display_length(cue.text)
        if duration < 0.45:
            add_review_item(
                cue.start,
                "显示过短",
                f"只显示 {duration:.2f} 秒",
                cue.text,
                priority=2,
            )
        if length >= 8 and length / duration > REVIEW_FAST_CHARS_PER_SECOND:
            add_review_item(
                cue.start,
                "阅读较快",
                f"约 {length / duration:.1f} 字/秒",
                cue.text,
                priority=1,
            )

    transitions = []
    for left, right in zip(speech_regions, speech_regions[1:]):
        gap = right["start"] - left["end"]
        if gap < BOUNDARY_VAD_MIN_GAP_SECONDS:
            continue
        candidate = max(
            left["end"],
            right["start"] - BOUNDARY_VAD_SHORT_GAP_ONSET_LEAD_SECONDS,
        )
        transitions.append((left["end"], right["start"], candidate))
    for cue in cues:
        candidates = []
        for speech_end, next_start, candidate in transitions:
            if not (
                speech_end - BOUNDARY_VAD_LOOKBACK_SECONDS
                <= cue.start
                <= next_start + 0.30
            ):
                continue
            difference = abs(cue.start - candidate)
            if difference >= REVIEW_TIMING_DIFFERENCE_SECONDS:
                candidates.append((difference, candidate))
        if candidates:
            difference, candidate = min(candidates)
            add_review_item(
                cue.start,
                "边界待看",
                f"字幕句首与人声起音候选相差 {difference * 1000:.0f}ms",
                cue.text,
                priority=1,
            )
    return get_runtime_context().review_items


import subtitle_core as _core
for _name in __all__:
    setattr(_core, _name, globals()[_name])
del _core, _name
