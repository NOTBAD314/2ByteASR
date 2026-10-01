"""Character/timeline alignment helpers for subtitle segmentation."""

import math
import re
from difflib import SequenceMatcher

from subtitle_core import *  # noqa: F401,F403
from twobyteasr.text_similarity import phonetic_text
from twobyteasr.segmentation import (
    lexical_forbidden_boundary_offsets,
    segmenter_forbidden_boundary_offsets,
    semantically_awkward_boundary,
)

__all__ = [
    "individual_cue",
    "segment_content_timeline",
    "firered_pause_character_boundaries",
    "firered_pause_character_gaps",
    "_vad_silence_ratio",
    "snap_internal_cue_boundaries",
    "hard_break_character_offsets",
    "source_segment_character_offsets",
    "protected_source_boundary_offsets",
    "text_boundary_hints",
    "firered_token_start",
    "ALIGNMENT_CHINESE_DIGITS",
    "arabic_number_for_alignment",
    "boundary_alignment_content",
    "boundary_alignment_units",
]

def individual_cue(segment):
    return SubtitleCue(
        cue_id=0,
        start=segment.start,
        end=max(segment.end, segment.start + MIN_SUBTITLE_SECONDS),
        text=clean_subtitle_text(segment.text),
        timing_locked=segment.timing_locked,
        speaker=segment.speaker,
    )


def segment_content_timeline(segment, firered_tokens=()):
    """用 FireRed 的可信字级锚点重切段内边界；始终保留 MOSS 外边界与正文。"""
    from .number_fidelity import mapped_content_timeline
    mapped = mapped_content_timeline(segment)
    if mapped is not None:
        return mapped
    target = list(content_only(segment.text))
    if not target:
        return []

    raw_timeline = []
    using_firered = False
    if firered_tokens:
        candidate_timeline = []
        for token in firered_tokens:
            if (
                float(token["end"])
                < segment.start - FIRERED_TEXT_ALIGNMENT_PAD_SECONDS
                or float(token["start"])
                > segment.end + FIRERED_TEXT_ALIGNMENT_PAD_SECONDS
            ):
                continue
            chars = list(content_only(token.get("text", "")))
            if not chars:
                continue
            start = firered_token_start(token)
            end = max(start + 0.001, float(token["end"]))
            if (
                start
                > segment.end + FIRERED_EFFECTIVE_TOKEN_OUTSIDE_TOLERANCE_SECONDS
                or end
                < segment.start - FIRERED_EFFECTIVE_TOKEN_OUTSIDE_TOLERANCE_SECONDS
            ):
                continue
            for index, char in enumerate(chars):
                char_start = start + (end - start) * index / len(chars)
                char_end = start + (end - start) * (index + 1) / len(chars)
                candidate_timeline.append(
                    WordUnit(
                        char_start,
                        max(char_start + 0.001, char_end),
                        char,
                        float(token.get("confidence", segment.confidence)),
                    )
                )
        target_keys = [phonetic_text(char) or char.lower() for char in target]
        candidate_keys = [
            phonetic_text(unit.text) or unit.text.lower()
            for unit in candidate_timeline
        ]
        if candidate_keys:
            evidence = SequenceMatcher(
                None,
                candidate_keys,
                target_keys,
                autojunk=False,
            )
            matched_blocks = [
                block for block in evidence.get_matching_blocks() if block.size
            ]
            matched = sum(block.size for block in matched_blocks)
            largest_match = max((block.size for block in matched_blocks), default=0)
            enough_evidence = matched >= max(2, math.ceil(len(target) * 0.55))
            # 重叠锁定段不允许 FireRed 改字或改变说话人，只使用其连续性很强的
            # 内部时间锚点。这样能利用“然后……不好意思”的准确字时刻，同时
            # 避免把另一位主播零散碰巧同音的字当作本段时间证据。
            if segment.timing_locked:
                enough_evidence = enough_evidence and largest_match >= max(
                    2,
                    math.ceil(len(target) * 0.45),
                )
            if enough_evidence and matched_blocks:
                # 丢掉窗口中属于另一位主播/相邻句的未匹配前后缀。FireRed 若漏掉
                # 本段开头（例如“好继续吧”），下方会把它安全铺在 MOSS 起点到
                # 第一个 FireRed 匹配字之间，而不会把后文整体提前均分。
                first_match = matched_blocks[0]
                last_match = matched_blocks[-1]
                raw_timeline = candidate_timeline[
                    first_match.a : last_match.a + last_match.size
                ]
                using_firered = True

    if not raw_timeline:
        for word in segment.words:
            chars = list(content_only(word.text))
            if not chars:
                continue
            duration = max(0.001, word.end - word.start)
            for index, char in enumerate(chars):
                start = word.start + duration * index / len(chars)
                end = word.start + duration * (index + 1) / len(chars)
                raw_timeline.append(
                    WordUnit(start, max(start + 0.001, end), char, word.probability)
                )

    if not raw_timeline:
        # These are display estimates only. Preserve the absence of acoustic
        # evidence in the existing arbitration metadata and diagnostic stream.
        if not segment.caption_arbitration.get('timing_degradation'):
            segment.caption_arbitration['timing_degradation'] = {
                'reason': 'no-word-alignment', 'precision': 'segment-only',
                'display_estimates': True, 'start': segment.start, 'end': segment.end}
            record_run_event('alignment_degraded', segment_id=segment.segment_id,
                             start=segment.start,end=segment.end,reason='no-word-alignment')
        duration = max(0.001, segment.end - segment.start)
        return [
            WordUnit(
                segment.start + duration * index / len(target),
                segment.start + duration * (index + 1) / len(target),
                char,
                segment.confidence,
            )
            for index, char in enumerate(target)
        ]

    raw_keys = [phonetic_text(unit.text) or unit.text.lower() for unit in raw_timeline]
    target_keys = [phonetic_text(char) or char.lower() for char in target]
    # 同字数且逐字同音时直接保留原位置，不因校对后的字形不同而改变时间。
    if (
        len(raw_timeline) == len(target)
        and raw_keys == target_keys
        and not using_firered
        and not segment.timing_locked
    ):
        return [
            WordUnit(unit.start, unit.end, char, unit.probability)
            for unit, char in zip(raw_timeline, target)
        ]

    result = [None] * len(target)
    matcher = SequenceMatcher(None, raw_keys, target_keys, autojunk=False)
    for tag, raw_start, raw_end, target_start, target_end in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(target_end - target_start):
                unit = raw_timeline[raw_start + offset]
                result[target_start + offset] = WordUnit(
                    unit.start,
                    unit.end,
                    target[target_start + offset],
                    unit.probability,
                )
            continue
        if target_start == target_end:
            continue

        if raw_start < raw_end:
            span_start = raw_timeline[raw_start].start
            span_end = raw_timeline[raw_end - 1].end
        else:
            if using_firered and raw_start == 0 and target_start == 0:
                # FireRed 漏掉了段首文字：MOSS 起点可靠，首个匹配字的起点可靠。
                first_match_start = raw_timeline[0].start
                if segment.timing_locked or first_match_start >= segment.start:
                    span_start = segment.start
                else:
                    # 非锁定段的第一个 FireRed 匹配字偶尔略早于 MOSS 起点；
                    # 漏掉的前缀必须放在该锚点之前，不能反过来制造倒序字时刻。
                    missing_count = max(1, target_end - target_start)
                    prefix_duration = max(
                        0.04,
                        min(0.24, 0.08 * missing_count),
                    )
                    span_start = max(
                        0.0,
                        segment.start - FIRERED_TIMELINE_MAX_START_SHIFT_SECONDS,
                        first_match_start - prefix_duration,
                    )
            else:
                span_start = (
                    raw_timeline[raw_start - 1].end
                    if raw_start > 0
                    else (
                        max(segment.start, raw_timeline[0].start)
                        if using_firered
                        else segment.start
                    )
                )
            span_end = (
                raw_timeline[raw_start].start
                if raw_start < len(raw_timeline)
                else (
                    segment.end
                    if using_firered
                    else segment.end
                )
            )
            if (
                using_firered
                and 0 < raw_start < len(raw_timeline)
                and target_start > 0
                and result[target_start - 1] is not None
            ):
                # FireRed 常把“看一下”整体记在“看”的长 token 上，文本对齐会表现为
                # 在“看”和“他”之间插入“一下”，但两 token 之间没有空隙。此时把
                # 前一个长 token 的时间在“看/一/下”之间重分，不能制造倒序时间。
                previous_unit = result[target_start - 1]
                following_start = raw_timeline[raw_start].start
                inserted_count = target_end - target_start
                if following_start - previous_unit.end < inserted_count * 0.001:
                    combined_duration = following_start - previous_unit.start
                    if combined_duration >= (inserted_count + 1) * 0.001:
                        piece_duration = combined_duration / (inserted_count + 1)
                        previous_unit.end = previous_unit.start + piece_duration
                        span_start = previous_unit.end
                        span_end = following_start
        span_end = max(span_start + 0.001, span_end)
        count = target_end - target_start
        for offset in range(count):
            start = span_start + (span_end - span_start) * offset / count
            end = span_start + (span_end - span_start) * (offset + 1) / count
            result[target_start + offset] = WordUnit(
                start,
                max(start + 0.001, end),
                target[target_start + offset],
                segment.confidence,
            )

    # 理论上 SequenceMatcher 会覆盖全部 target；仍保留线性兜底。
    duration = max(0.001, segment.end - segment.start)
    for index, unit in enumerate(result):
        if unit is None:
            start = segment.start + duration * index / len(target)
            end = segment.start + duration * (index + 1) / len(target)
            result[index] = WordUnit(
                start,
                max(start + 0.001, end),
                target[index],
                segment.confidence,
            )
    if using_firered or segment.timing_locked:
        if segment.timing_locked:
            # 锁定只限制外边界、正文与说话人归属；段内仍可使用高置信 FireRed 锚点。
            minimum = max(0.0, segment.start)
            maximum = segment.end
        else:
            # FireRed 只负责 MOSS 段内字符锚点。外边界一旦外扩，病态长 token
            # 就会把字幕提前或拖后；成片尾部统一在最终阶段另加 200ms。
            minimum = max(0.0, segment.start)
            maximum = segment.end
        for unit in result:
            unit.start = max(minimum, min(maximum - 0.001, unit.start))
            unit.end = max(unit.start + 0.001, min(maximum, unit.end))
    return result


def firered_pause_character_boundaries(
    segment_batch,
    firered_tokens=(),
    minimum_gap=REAL_PAUSE_HINT_SECONDS,
):
    """把 FireRed 的真实字间停顿映射为字符偏移及精确左右时间。"""
    if not segment_batch or not firered_tokens:
        return {}

    result = {}
    batch_offset = 0
    for segment in segment_batch:
        source_units = boundary_alignment_units(segment.text)
        source_spoken = "".join(char for char, _ in source_units)
        source_length = display_length(segment.text)
        if len(source_spoken) < 2 or source_length < 2:
            batch_offset += source_length
            continue

        nearby = [
            token
            for token in firered_tokens
            if float(token["end"]) >= segment.start - FIRERED_TEXT_ALIGNMENT_PAD_SECONDS
            and float(token["start"]) <= segment.end + FIRERED_TEXT_ALIGNMENT_PAD_SECONDS
            and boundary_alignment_content(token.get("text", ""))
        ]
        candidate_units = []
        for token in nearby:
            chars = list(boundary_alignment_content(token.get("text", "")))
            if not chars:
                continue
            start = firered_token_start(token)
            # FireRed 偶尔把一个字的时间戳拉得很长；此时真实字头更接近尾部，
            # 但字尾仍应使用原 token.end，不能把同一个 token 裁成负时长并制造假停顿。
            end = max(start + 0.001, float(token["end"]))
            for index, char in enumerate(chars):
                char_start = start + (end - start) * index / len(chars)
                char_end = start + (end - start) * (index + 1) / len(chars)
                candidate_units.append((char, char_start, max(char_start + 0.001, char_end)))
        candidate_text = "".join(item[0] for item in candidate_units)
        if len(candidate_text) < 2:
            batch_offset += source_length
            continue

        source_to_candidate = {}
        # 校对后的“飞飞钥/地武队”和 FireRed 原始近音字可能不同；停顿映射按
        # 单字读音对齐，避免文字修正后反而丢失真实气口。
        source_alignment = [phonetic_text(char) or char for char in source_spoken]
        candidate_alignment = [
            phonetic_text(item[0]) or item[0] for item in candidate_units
        ]
        matcher = SequenceMatcher(
            None,
            source_alignment,
            candidate_alignment,
            autojunk=False,
        )
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                source_to_candidate[block.a + offset] = block.b + offset

        forbidden = lexical_forbidden_boundary_offsets(segment.text)
        for source_index in range(1, len(source_units)):
            source_offset = source_units[source_index - 1][1]
            if (
                source_offset <= 0
                or source_offset >= source_length
                or source_offset == source_units[source_index][1]
                or source_offset in forbidden
            ):
                continue
            left_index = source_to_candidate.get(source_index - 1)
            right_index = source_to_candidate.get(source_index)
            if left_index is None or right_index != left_index + 1:
                continue
            gap = candidate_units[right_index][1] - candidate_units[left_index][2]
            if gap + 1e-6 < minimum_gap:
                continue
            absolute_offset = batch_offset + source_offset
            detail = {
                "gap": gap,
                "left_end": candidate_units[left_index][2],
                "right_start": candidate_units[right_index][1],
                "segment_id": segment.segment_id,
            }
            previous = result.get(absolute_offset)
            if previous is None or gap > previous["gap"]:
                result[absolute_offset] = detail
        batch_offset += source_length
    return result


def firered_pause_character_gaps(
    segment_batch,
    firered_tokens=(),
    minimum_gap=REAL_PAUSE_HINT_SECONDS,
):
    return {
        offset: detail["gap"]
        for offset, detail in firered_pause_character_boundaries(
            segment_batch,
            firered_tokens,
            minimum_gap,
        ).items()
    }


def _vad_silence_ratio(start, end, speech_regions):
    duration = max(0.001, end - start)
    speech = sum(
        max(0.0, min(end, float(item["end"])) - max(start, float(item["start"])))
        for item in speech_regions or ()
    )
    return max(0.0, min(1.0, 1.0 - speech / duration))


def snap_internal_cue_boundaries(
    cues,
    segment_batch,
    firered_tokens=(),
    speech_regions=(),
):
    """冻结 MOSS 外边界，只把同一原段内部的字幕交界贴到真实停顿。"""
    if len(cues) < 2 or not firered_tokens:
        return cues
    details = firered_pause_character_boundaries(
        segment_batch,
        firered_tokens,
        REAL_PAUSE_HINT_SECONDS,
    )
    if not details:
        return cues
    source_boundaries = source_segment_character_offsets(segment_batch)
    cursor = 0
    changed = 0
    for left, right in zip(cues, cues[1:]):
        cursor += display_length(left.text)
        if cursor in source_boundaries or left.timing_locked or right.timing_locked:
            continue
        detail = details.get(cursor)
        if detail is None:
            continue
        proposed_left = float(detail["left_end"])
        proposed_right = float(detail["right_start"])
        if proposed_right <= proposed_left:
            continue
        if (
            abs(proposed_left - left.end) > INTERNAL_BOUNDARY_MAX_SHIFT_SECONDS
            or abs(proposed_right - right.start) > INTERNAL_BOUNDARY_MAX_SHIFT_SECONDS
            or proposed_left - left.start < MIN_SUBTITLE_SECONDS
            or right.end - proposed_right < MIN_SUBTITLE_SECONDS
        ):
            continue
        if speech_regions and _vad_silence_ratio(
            proposed_left,
            proposed_right,
            speech_regions,
        ) < INTERNAL_BOUNDARY_MIN_VAD_SILENCE_RATIO:
            continue
        left.end = proposed_left
        right.start = proposed_right
        changed += 1
    if changed:
        print(f"   [内部时间校准] {changed} 个字幕交界贴到 FireRed/VAD 真实停顿。")
    return cues


def hard_break_character_offsets(segment_batch, firered_tokens=()):
    source = content_exact(
        "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    )
    # 词中禁切：通用分词 + 既有词表。真实超长静音仍会保留，但后续会贴到词边。
    forbidden = lexical_forbidden_boundary_offsets(source) | segmenter_forbidden_boundary_offsets(
        source
    )

    def keep_required(offset, gap, repeated=False):
        if repeated or gap >= INTERNAL_HARD_GAP_SECONDS:
            return True
        if offset in forbidden or semantically_awkward_boundary(source, offset):
            return False
        return gap >= HARD_GAP_SECONDS

    offsets = set()
    offset = 0
    for index, segment in enumerate(segment_batch):
        offset += display_length(segment.text)
        if index + 1 < len(segment_batch):
            next_segment = segment_batch[index + 1]
            repeated_response = (
                bool(content_only(segment.text))
                and content_only(segment.text) == content_only(next_segment.text)
            )
            gap = next_segment.start - segment.end
            if keep_required(offset, gap, repeated_response):
                offsets.add(offset)
    # 普通停顿只作为优先气口交给 Qwen；若刚好落在未完成成分或语法助词前，
    # 即使超过 1.2 秒也允许语言模型越过它重组。只有 3 秒以上才无条件断开。
    offsets.update(
        offset
        for offset, gap in firered_pause_character_gaps(
            segment_batch,
            firered_tokens,
        ).items()
        if keep_required(offset, gap)
    )
    return offsets


def source_segment_character_offsets(segment_batch):
    offsets = set()
    offset = 0
    for segment in segment_batch[:-1]:
        offset += display_length(segment.text)
        offsets.add(offset)
    return offsets


def protected_source_boundary_offsets(segment_batch):
    """只保护真实停顿和重复回应；普通 200ms 口语停连不再锁死。"""
    source = content_exact(
        "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    )
    forbidden = lexical_forbidden_boundary_offsets(source)
    offsets = set()
    offset = 0
    for index, segment in enumerate(segment_batch[:-1]):
        offset += display_length(segment.text)
        next_segment = segment_batch[index + 1]
        gap = next_segment.start - segment.end
        repeated_response = (
            bool(content_only(segment.text))
            and content_only(segment.text) == content_only(next_segment.text)
        )
        keep_required = (
            repeated_response
            or gap >= INTERNAL_HARD_GAP_SECONDS
            or (
                gap >= PROTECTED_SOURCE_GAP_SECONDS
                and offset not in forbidden
                and not semantically_awkward_boundary(source, offset)
            )
        )
        if keep_required:
            offsets.add(offset)
    return offsets


def text_boundary_hints(text):
    """返回空格或标点所在的内容字边界，供本地修复时优先选择。"""
    positions = [
        index
        for index, char in enumerate(text)
        if re.match(r"[\u3400-\u9fffA-Za-z0-9]", char)
    ]
    hints = set()
    for offset in range(1, len(positions)):
        between = text[positions[offset - 1] + 1 : positions[offset]]
        if re.search(r"\s|[?!！？.]", between):
            hints.add(offset)
    return hints



def firered_token_start(token):
    start = float(token["start"])
    end = float(token["end"])
    if end - start > FIRERED_NORMAL_TOKEN_SECONDS:
        return end - FIRERED_LONG_TOKEN_TAIL_SECONDS
    return start


ALIGNMENT_CHINESE_DIGITS = "零一二三四五六七八九"


def arabic_number_for_alignment(value):
    """仅供边界匹配：把 20/70 等字幕数字还原成 ASR 常见中文读法。"""
    number = int(value)
    if number < 10:
        return ALIGNMENT_CHINESE_DIGITS[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        prefix = "" if tens == 1 else ALIGNMENT_CHINESE_DIGITS[tens]
        suffix = "" if ones == 0 else ALIGNMENT_CHINESE_DIGITS[ones]
        return f"{prefix}十{suffix}"
    if number < 10000:
        digits = [int(char) for char in f"{number:04d}"]
        units = ("千", "百", "十", "")
        pieces = []
        pending_zero = False
        for index, digit in enumerate(digits):
            if digit == 0:
                if pieces and any(value != 0 for value in digits[index + 1 :]):
                    pending_zero = True
                continue
            if pending_zero:
                pieces.append("零")
                pending_zero = False
            pieces.append(ALIGNMENT_CHINESE_DIGITS[digit] + units[index])
        return "".join(pieces)
    return "".join(ALIGNMENT_CHINESE_DIGITS[int(char)] for char in value)


def boundary_alignment_content(text):
    restored = re.sub(
        r"\d+",
        lambda match: arabic_number_for_alignment(match.group(0)),
        simplify_chinese(str(text or "")),
    )
    return content_only(restored)


def boundary_alignment_units(text):
    """返回边界匹配读音字及其对应的原字幕字符结束位置。"""
    source = list(content_only(simplify_chinese(str(text or ""))))
    units = []
    index = 0
    while index < len(source):
        if not source[index].isdigit():
            units.append((source[index], index + 1))
            index += 1
            continue
        end = index + 1
        while end < len(source) and source[end].isdigit():
            end += 1
        spoken = arabic_number_for_alignment("".join(source[index:end]))
        units.extend((char, end) for char in spoken)
        index = end
    return units

