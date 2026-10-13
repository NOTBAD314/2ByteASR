"""Local ASR-consensus checks and correction edit safety decisions."""

import re
import time
from collections import Counter
from difflib import SequenceMatcher

from subtitle_core import *  # noqa: F401,F403
from twobyteasr.term_constants import (
    ASR_CONSENSUS_PROTECTED_PHRASES,
    GLOBAL_DOMAIN_TERM_SUFFIXES,
)
from twobyteasr.text_similarity import levenshtein, phonetic_text

__all__ = [
    "asr_consensus_similarity",
    "reference_consensus_edits",
    "apply_reference_consensus_corrections",
    "reference_differences_are_compatible",
    "consensus_candidate_is_safe",
    "build_asr_difference_hints",
    "build_gacha_quantity_hints",
    "build_gacha_term_hints",
    "build_strong_reference_consensus_hint",
    "hinted_quantity_change_is_supported",
    "hinted_domain_term_change_is_supported",
    "nearby_glossary_candidates",
    "normalize_asr_supports",
    "count_independent_asr_supports",
    "correction_is_safe",
    "decompose_broad_edit",
    "find_unique_patch_span",
    "broad_consensus_support_count",
    "apply_correction_edits",
]


_CONSENSUS_PARTICLES = frozenset("啊呀呢吧嘛吗啦哦呃嗯了的地得他她它")
_CONSENSUS_NUMBER_CHARS = frozenset("0123456789零〇一二两三四五六七八九十百千万亿")


def _reference_replacement_spans(primary, reference):
    """Return position-stable replacement spans; insertions/deletions stay manual."""
    primary_content = content_exact(primary)
    reference_content = content_exact(reference)
    if not primary_content or not reference_content:
        return set()
    spans = set()
    matcher = SequenceMatcher(
        None,
        primary_content,
        reference_content,
        autojunk=False,
    )
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag != "replace":
            continue
        source = primary_content[left_start:left_end]
        target = reference_content[right_start:right_end]
        if source and target:
            spans.add((left_start, left_end, source, target))
    return spans


def reference_consensus_edits(primary, independent_references):
    """Find identical local substitutions supported by two independent ASR models.

    Whole-sentence similarity is intentionally not used as the acceptance gate: a
    single wrong homophone makes two long sentences look almost identical and was
    previously the reason correct FireRed/Qwen evidence lost to MOSS.
    """
    from .caption_arbitration import usable_transcript
    if not usable_transcript(primary):
        return []
    primary_content = content_exact(primary)
    references = []
    for value in independent_references or ():
        if not usable_transcript(value):
            continue
        candidate = content_exact(value)
        # Equal text from FireRed and Qwen is precisely the strongest case here;
        # keep the two model slots separate instead of deduplicating by value.
        if candidate and candidate != primary_content:
            references.append(candidate)
    if len(references) < 2:
        return []

    support = Counter()
    # 跨度集合与全句音串按“值”只算一次：此前每个候选跨度都对每个参考重算
    # _reference_replacement_spans + 全句拼音 + 全句相似度，是 2026-09-03
    # run eca757 中 242 段共识单核跑 8 分钟的主要来源。投票仍按参考“槽位”
    # 计数——FireRed 与 Qwen3 文本完全一致时两票都必须计入，不能按值去重。
    spans_by_reference = {}
    for reference in references:
        spans = spans_by_reference.get(reference)
        if spans is None:
            spans = spans_by_reference[reference] = (
                _reference_replacement_spans(primary_content, reference)
            )
        for span in spans:
            support[span] += 1

    primary_sound = None
    full_sound_by_reference = {}

    def _full_sound(reference):
        nonlocal primary_sound
        cached = full_sound_by_reference.get(reference)
        if cached is None:
            if primary_sound is None:
                primary_sound = phonetic_text(primary_content)
            cached = SequenceMatcher(
                None,
                primary_sound,
                phonetic_text(reference),
                autojunk=False,
            ).ratio()
            full_sound_by_reference[reference] = cached
        return cached

    accepted = []
    occupied = set()
    for (start, end, source, target), count in sorted(
        support.items(),
        key=lambda item: (item[0][0], item[0][1]),
    ):
        if count < 2 or len(source) != len(target) or not (1 <= len(source) <= 4):
            continue
        if source.lower() == target.lower():
            continue
        if re.search(r'[A-Za-z0-9]', source + target):
            continue
        if any(char in _CONSENSUS_NUMBER_CHARS for char in source + target):
            continue
        if len(source) == 1 and (
            source in _CONSENSUS_PARTICLES or target in _CONSENSUS_PARTICLES
        ):
            continue
        if any(index in occupied for index in range(start, end)):
            continue

        local_sound = SequenceMatcher(
            None,
            phonetic_text(source),
            phonetic_text(target),
            autojunk=False,
        ).ratio()
        full_sound = max(
            _full_sound(reference)
            for reference in references
            if (start, end, source, target) in spans_by_reference[reference]
        )
        # Most corrections are homophones.  A less similar one-character patch is
        # accepted only when both complete independent transcripts remain nearly
        # identical, which covers conversational "看看→看个" without opening the
        # door to broad semantic rewrites.
        if local_sound < 0.68 and not (len(source) == 1 and full_sound >= 0.88):
            continue
        accepted.append(
            {
                "start": start,
                "end": end,
                "from": source,
                "to": target,
                "support": count,
            }
        )
        occupied.update(range(start, end))
    return accepted


def apply_reference_consensus_corrections(segments):
    """Apply only the local spans jointly supported by FireRed and Qwen3-ASR."""
    changes = []
    total = len(segments)
    started_at = time.perf_counter()
    if total >= 40:
        print(f"   [三路仲裁] 本地双模型共识核对 {total} 段（每 40 段报告一次进度）…")
    for index, segment in enumerate(segments, 1):
        if total >= 80 and index % 40 == 0 and index < total:
            print(f"   [三路仲裁] 进度 {index}/{total} 段。")
        primary = content_exact(segment.text)
        previous = dict(segment.caption_arbitration or {})
        evidence = previous.get('independent_input_evidence') or {
            'primary': segment.moss_text or segment.text,
            'firered': segment.firered_text,
            'qwen': segment.qwen_asr_text,
        }
        edits = reference_consensus_edits(
            primary,
            (evidence['firered'], evidence['qwen']),
        )
        from .caption_arbitration import arbitrate
        decision = arbitrate(evidence['primary'], evidence['firered'],evidence['qwen'],
            manual_text=getattr(segment,'manual_text',None),
            start_ms=round(segment.start*1000),end_ms=round(segment.end*1000),
            primary_model='MOSS' if segment.moss_text else str(segment.primary_source or 'primary'))
        decision['independent_input_evidence'] = dict(evidence)
        for name in ('terminology_polish', 'terminology_normalization', 'source_coverage',
                     'speaker_evidence','native_model_probability','confidence_kind','timing_precision',
                     'streaming_chunk_index','native_timestamp_source',
                     # 2026-10-13: provenance markers of display-estimate words
                     # must survive, or estimates are later read as measured.
                     'word_timing','timing_degradation'):
            if name in previous:
                decision[name] = previous[name]
        if 'forced_alignment_window' in previous and not str(getattr(segment, 'primary_source', '') or '').startswith('moss'):
            # Cloud/other primaries timed by the local aligner on their own text.
            # (MOSS rows keep their tuned route: Japanese re-aligns final cues.)
            decision['forced_alignment_window'] = previous['forced_alignment_window']
        segment.caption_arbitration = decision
        if decision['reason'] == '用户手动确认':
            segment.text = decision['selected_text']
            continue
        if decision['accepted_spans']:
            if primary == content_exact(evidence['primary']):
                new_edits = decision['accepted_spans']
                occupied = {i for row in new_edits for i in range(row['start'],max(row['end'],row['start']+1))}
                edits = sorted(new_edits + [row for row in edits if not any(i in occupied for i in range(row['start'],row['end']))], key=lambda row:row['start'])
        if not edits:
            continue
        corrected = primary
        for edit in reversed(edits):
            corrected = (
                corrected[: edit["start"]]
                + edit["to"]
                + corrected[edit["end"] :]
            )
        if corrected == primary:
            continue
        before = segment.text
        segment.text = clean_subtitle_text(corrected)
        decision.update(selected_text=segment.text,reason='FireRed+Qwen片段共识',accepted_spans=edits)
        segment.primary_source = f"{segment.primary_source}+local-consensus"
        changes.extend(
            (segment.segment_id, edit["from"], edit["to"], before, segment.text)
            for edit in edits
        )
    if changes:
        sample = "、".join(
            f"{source}→{target}" for _, source, target, _, _ in changes[:12]
        )
        print(f"   [本地双模型纠错] FireRed+Qwen3 共识修正 {len(changes)} 处：{sample}。")
        record_run_event(
            "local_reference_consensus_applied",
            count=len(changes),
            segments_scanned=total,
            elapsed_seconds=round(time.perf_counter() - started_at, 3),
            edits=[
                {"cue_id": cue_id, "from": source, "to": target}
                for cue_id, source, target, _, _ in changes
            ],
        )
    else:
        record_run_event(
            "local_reference_consensus_skipped",
            count=0,
            segments_scanned=total,
            elapsed_seconds=round(time.perf_counter() - started_at, 3),
        )
    return segments

def asr_consensus_similarity(left, right):
    left_content = content_only(simplify_chinese(left))
    right_content = content_only(simplify_chinese(right))
    if not left_content or not right_content:
        return 0.0
    text_similarity = SequenceMatcher(
        None,
        left_content,
        right_content,
        autojunk=False,
    ).ratio()
    phonetic_similarity = SequenceMatcher(
        None,
        phonetic_text(left_content),
        phonetic_text(right_content),
        autojunk=False,
    ).ratio()
    return text_similarity * 0.60 + phonetic_similarity * 0.40


def reference_differences_are_compatible(left, right):
    """防止两份长句只因公共上下文相同，就掩盖关键位置互相冲突。"""
    left_content = content_only(left)
    right_content = content_only(right)
    if not left_content or not right_content:
        return False
    matcher = SequenceMatcher(
        None,
        left_content,
        right_content,
        autojunk=False,
    )
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        left_part = left_content[left_start:left_end]
        right_part = right_content[right_start:right_end]
        if not left_part or not right_part:
            return False
        left_sound = phonetic_text(left_part)
        right_sound = phonetic_text(right_part)
        distance = levenshtein(left_sound, right_sound) / max(
            1,
            len(left_sound),
            len(right_sound),
        )
        if distance > 0.45:
            return False
    return True


def consensus_candidate_is_safe(primary, candidate, confidence):
    primary_content = content_only(primary)
    candidate_content = content_only(candidate)
    if not primary_content or not candidate_content:
        return False
    if len(primary_content) != len(candidate_content):
        return False

    changed_edges = int(primary_content[0] != candidate_content[0]) + int(
        primary_content[-1] != candidate_content[-1]
    )
    if changed_edges and not (confidence <= 0.60 and changed_edges <= 1):
        return False
    if any(
        phrase in primary_content and phrase not in candidate_content
        for phrase in ASR_CONSENSUS_PROTECTED_PHRASES
    ):
        return False
    quantities = re.findall(
        r"(?:\d+|[零〇一二两三四五六七八九十百千万亿]+)(?:抽|命|个|层)",
        primary_content,
    )
    if any(quantity not in candidate_content for quantity in quantities):
        return False
    for index in range(len(candidate_content) - 1):
        char = candidate_content[index]
        if (
            char == candidate_content[index + 1]
            and char not in LEGITIMATE_REPEATED_VOCALS
            and char * 2 not in primary_content
        ):
            return False
    return True


def build_asr_difference_hints(primary, alternate):
    """把两套 ASR 的每处差异显式列给 Qwen，避免只修正第一个错词。"""
    primary_content = content_only(primary)
    alternate_content = content_only(alternate)
    if not primary_content or not alternate_content or primary_content == alternate_content:
        return []
    hints = []
    matcher = SequenceMatcher(
        None, primary_content, alternate_content, autojunk=False
    )
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        hints.append(
            {
                "primary": primary_content[left_start:left_end],
                "alternate": alternate_content[right_start:right_end],
            }
        )
    return hints[:8]


def build_gacha_quantity_hints(text, context=""):
    """只向大模型提示抽卡语境里的量词近音，不在本地直接替换。"""
    source = clean_subtitle_text(simplify_chinese(text))
    combined = content_only(f"{context}{source}")
    if not any(
        marker in combined
        for marker in ("抽卡", "卡池", "保底", "抽", "歪", "连金", "双黄", "648")
    ):
        return []

    hints = []
    number = r"\d+|[零〇一二两三四五六七八九十百千万亿]+"
    for match in re.finditer(rf"(?P<number>{number})(?P<unit>冲|处|出)", source):
        hints.append(
            {
                "heard": match.group(0),
                "candidate": f"{match.group('number')}抽",
                "reason": "抽卡上下文中的数量量词近音，必须结合整句判断",
            }
        )

    for match in re.finditer(
        r"(?P<digit>[一二两三四五六七八九])(?:叔|数)出(?P<tail>了?)",
        source,
    ):
        value = CHINESE_NUMBER_DIGITS[match.group("digit")] * 10
        hints.append(
            {
                "heard": match.group(0),
                "candidate": f"{value}抽出{match.group('tail')}",
                "reason": "可能是几十抽出了，只作为语境候选，不得强制采用",
            }
        )
    return hints[:2]


def build_gacha_term_hints(text, context=""):
    """把少量强语境二游近音交给大模型判断，本地不直接改写。"""
    source = clean_subtitle_text(simplify_chinese(text))
    combined = content_only(f"{context}{source}")
    if not any(
        marker in combined
        for marker in ("抽卡", "卡池", "保底", "抽", "歪", "连金", "双黄", "648")
    ):
        return []

    hints = []
    candidates = (
        ("双方", "双黄", "抽卡语境中表示一次出现两个高稀有结果"),
        ("双簧", "双黄", "抽卡语境中表示一次出现两个高稀有结果"),
        ("连襟", "连金", "抽卡语境中表示连续出金"),
        ("连筋", "连金", "抽卡语境中表示连续出金"),
        ("没电", "没垫", "抽卡语境中表示没有预先垫抽数"),
        ("飞球", "非酋", "抽卡语境中表示运气差的玩家身份，不是球类"),
    )
    for heard, candidate, reason in candidates:
        if heard in source:
            hints.append(
                {"heard": heard, "candidate": candidate, "reason": reason}
            )

    # 这一提示必须同时满足完整句式和抽卡上下文；“出版/实况”在普通语境不提示。
    match = re.search(r"今天的(?P<heard>出版|实况|春晚)会(?:异常|非常)", source)
    if match:
        hints.append(
            {
                "heard": match.group("heard"),
                "candidate": "抽卡",
                "reason": "前后在谈卡池、欧非且句式为“今天的抽卡会很欧”",
            }
        )
    return hints[:4]


def build_strong_reference_consensus_hint(segment):
    """两份独立参考逐字一致时显式告知校对模型，仍由模型结合语义决定。"""
    first_reference = clean_subtitle_text(
        simplify_chinese(
            (segment.firered_text or segment.alternate_text)
            if segment.primary_source.startswith("moss-host")
            else (segment.moss_text or segment.alternate_text)
        )
    )
    qwen = clean_subtitle_text(simplify_chinese(segment.qwen_asr_text))
    primary = content_only(segment.text)
    if (
        not first_reference
        or not qwen
        or content_only(first_reference) != content_only(qwen)
        or content_only(first_reference) == primary
    ):
        return None
    return {
        "candidate": normalize_output_text(first_reference),
        "reason": "FireRed 与 Qwen3-ASR 两份独立参考逐字一致，但仍需结合上下文判断",
    }


def hinted_quantity_change_is_supported(source, target, hints, alternates):
    """Qwen 采纳抽卡数量提示时，只放行提示中的数量且要求两套 ASR 支持原近音。"""
    source_content = content_only(source)
    target_quantities = quantity_expression_keys(target, set("抽"))
    if not source_content or not target_quantities:
        return False
    for hint in hints or []:
        heard = clean_subtitle_text(hint.get("heard", ""))
        candidate = clean_subtitle_text(hint.get("candidate", ""))
        if (
            heard
            and content_only(heard) in source_content
            and target_quantities & quantity_expression_keys(candidate, set("抽"))
            and asr_candidate_support_count(source, alternates, threshold=0.72) >= 2
        ):
            return True
    return False


def hinted_domain_term_change_is_supported(source, target, hints):
    """只验证 Qwen 的局部补丁是否严格命中已发送给它的强语境候选。"""
    source_content = content_only(source)
    target_content = content_only(target)
    return any(
        content_only(item.get("heard", "")) == source_content
        and content_only(item.get("candidate", "")) == target_content
        for item in (hints or [])
    )


def nearby_glossary_candidates(text, glossary):
    """只向 Qwen提示读音高度接近的专名；是否采用仍完全由 Qwen 判断。"""
    text_content = content_only(text)
    if not text_content:
        return []
    candidates = []
    for term in glossary:
        term_content = content_only(term)
        if not term_content:
            continue
        term_sound = phonetic_text(term_content)
        best = 0.0
        for window_length in range(
            max(1, len(term_content) - 1),
            min(len(text_content), len(term_content) + 1) + 1,
        ):
            for start in range(0, len(text_content) - window_length + 1):
                window = text_content[start : start + window_length]
                score = SequenceMatcher(
                    None, phonetic_text(window), term_sound, autojunk=False
                ).ratio()
                best = max(best, score)
        if best >= 0.78:
            candidates.append(term)
    return candidates


def count_independent_asr_supports(target, sources, threshold=None):
    """统计支持 target 的独立 ASR 证据家族数（P1-2 单一计数入口）。

    ``sources`` 为 ``(family, text)`` 二元组列表；同一 family 最多贡献
    1 票，不同 family 即使文本完全相同也各计 1 票（FireRed-AED 与
    复核 ASR 都转出"洛克王国" = 2 票）。

    family 语义（由调用方标注，派生证据不要传入）：
    - ``firered``：FireRed-AED（独立）
    - ``review``：Qwen3-ASR / Whisper / FunASR 等互斥复核后端（独立）
    - 其它：非 MOSS 主稿路径的 primary 参考等现状来源

    ``threshold=None`` 时用精确包含（``target in text``）判定；
    否则用文字/读音相似度判定，每家族取最高相似度
    （与 ``asr_candidate_support_count`` 的阈值语义一致）。
    """
    target_content = content_only(target)
    if not target_content:
        return 0
    grouped = {}
    for family, text in sources or []:
        candidate = content_only(text)
        if not candidate:
            continue
        grouped.setdefault(str(family or ""), []).append(candidate)
    votes = 0
    for texts in grouped.values():
        if threshold is None:
            if any(target_content in value for value in texts):
                votes += 1
            continue
        best = 0.0
        for value in texts:
            text_score = SequenceMatcher(
                None, target_content, value, autojunk=False
            ).ratio()
            sound_score = SequenceMatcher(
                None,
                phonetic_text(target_content),
                phonetic_text(value),
                autojunk=False,
            ).ratio()
            best = max(best, max(text_score, sound_score))
        if best >= threshold:
            votes += 1
    return votes


def normalize_asr_supports(alternates):
    if isinstance(alternates, str):
        alternates = [alternates]
    normalized = []
    seen = set()
    for value in alternates or []:
        candidate = content_only(value)
        if not candidate or candidate in seen:
            continue
        normalized.append(candidate)
        seen.add(candidate)
    return normalized


def correction_is_safe(original, corrected, alternates=()):
    original_content = content_only(original)
    corrected_content = content_only(corrected)
    alternate_contents = normalize_asr_supports(alternates)
    if not corrected_content:
        return False, "结果为空"
    if original_content == corrected_content:
        return True, "只改标点/空格"
    for index in range(len(corrected_content) - 1):
        char = corrected_content[index]
        repeated = char * 2
        if (
            char == corrected_content[index + 1]
            and char not in LEGITIMATE_REPEATED_VOCALS
            and repeated not in original_content
            and len(corrected_content) > len(original_content)
            and sum(repeated in value for value in alternate_contents) < 2
        ):
            return False, f"不得凭单套结果新增重复字“{repeated}”"
    if (
        len(corrected_content) < max(1, int(len(original_content) * 0.60))
        or len(corrected_content) > len(original_content) * 1.55 + 3
    ):
        return False, "长度变化过大"

    content_distance = levenshtein(original_content, corrected_content) / max(
        1, len(original_content), len(corrected_content)
    )
    original_sound = phonetic_text(original_content)
    corrected_sound = phonetic_text(corrected_content)
    primary_sound_similarity = SequenceMatcher(
        None, original_sound, corrected_sound, autojunk=False
    ).ratio()
    alternate_support = 0.0
    for alternate_content in alternate_contents:
        alternate_support = max(
            alternate_support,
            SequenceMatcher(
                None, alternate_content, corrected_content, autojunk=False
            ).ratio(),
            SequenceMatcher(
                None,
                phonetic_text(alternate_content),
                corrected_sound,
                autojunk=False,
            ).ratio(),
        )
    if content_distance > 0.58 and alternate_support < 0.78:
        return False, f"改字比例过大（{content_distance:.2f}）"

    changes = []
    matcher = SequenceMatcher(None, original_content, corrected_content)
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        left_chunk = original_content[left_start:left_end]
        right_chunk = corrected_content[right_start:right_end]
        left_sound = phonetic_text(left_chunk)
        right_sound = phonetic_text(right_chunk)
        distance = levenshtein(left_sound, right_sound) / max(
            1, len(left_sound), len(right_sound)
        )
        changes.append(distance)

    if not changes:
        return False, "没有可验证的改动"
    if max(changes) > PHONETIC_MAX_DISTANCE and alternate_support < 0.78:
        return False, f"改写读音差距过大（{max(changes, default=1.0):.2f}）"
    if len(corrected_content) < len(original_content) and (
        primary_sound_similarity < 0.62 and alternate_support < 0.82
    ):
        return False, "删字缺少多 ASR 或读音支持"
    return True, (
        f"读音差距={max(changes):.2f}，其他ASR支持={alternate_support:.2f}"
    )


def decompose_broad_edit(source, target, basis):
    """把模型偶尔提交的整句替换拆成近音的小补丁；插入和删除一律丢弃。"""
    result = []
    matcher = SequenceMatcher(None, source, target, autojunk=False)
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag != "replace":
            continue
        left = source[left_start:left_end].strip()
        right = target[right_start:right_end].strip()
        if not left or not right or display_length(left) > 6:
            continue
        left_sound = phonetic_text(left)
        right_sound = phonetic_text(right)
        distance = levenshtein(left_sound, right_sound) / max(
            1, len(left_sound), len(right_sound)
        )
        if distance < 0.65:
            result.append(
                {
                    "from": left,
                    "to": right,
                    "basis": f"{basis}+局部拆分",
                }
            )
    if result:
        return result

    # SequenceMatcher 在两句字形差异很大时可能只对齐最后一个“了”。
    # 再搜索最长的严格近音短片段，例如“骑完了→起晚了”。
    candidates = []
    source_content = content_only(source)
    target_content = content_only(target)
    for source_length in range(1, min(6, len(source_content)) + 1):
        for left_start in range(0, len(source_content) - source_length + 1):
            left = source_content[left_start : left_start + source_length]
            for target_length in range(
                max(1, source_length - 1),
                min(6, len(target_content), source_length + 1) + 1,
            ):
                for right_start in range(0, len(target_content) - target_length + 1):
                    right = target_content[
                        right_start : right_start + target_length
                    ]
                    if left == right:
                        continue
                    left_sound = phonetic_text(left)
                    right_sound = phonetic_text(right)
                    distance = levenshtein(left_sound, right_sound) / max(
                        1, len(left_sound), len(right_sound)
                    )
                    if distance <= 0.35:
                        candidates.append(
                            (
                                -distance,
                                min(source_length, target_length),
                                left_start,
                                right_start,
                                left,
                                right,
                            )
                        )
    if candidates:
        _, _, _, _, left, right = max(candidates)
        return [
            {
                "from": left,
                "to": right,
                "basis": f"{basis}+近音拆分",
            }
        ]
    return result


def find_unique_patch_span(text, source):
    """优先精确匹配；否则允许 Qwen 的 from 忽略字幕中的空格。"""
    if text.count(source) == 1:
        start = text.index(source)
        return start, start + len(source)
    source_content = content_only(source)
    if not source_content:
        return None
    pattern = r"\s*".join(re.escape(char) for char in source_content)
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
    if len(matches) != 1:
        return None
    match = matches[0]
    if content_only(match.group(0)) != source_content:
        return None
    return match.start(), match.end()


def broad_consensus_support_count(target, alternates):
    target_content = content_only(target)
    if not target_content:
        return 0
    target_sound = phonetic_text(target_content)
    supported = 0
    for alternate in alternates or []:
        alternate_content = content_only(alternate)
        if not alternate_content:
            continue
        text_similarity = SequenceMatcher(
            None,
            target_content,
            alternate_content,
            autojunk=False,
        ).ratio()
        sound_similarity = SequenceMatcher(
            None,
            target_sound,
            phonetic_text(alternate_content),
            autojunk=False,
        ).ratio()
        if max(text_similarity, sound_similarity) >= 0.88:
            supported += 1
    return supported


def apply_correction_edits(
    original,
    alternates,
    edits,
    *,
    allow_broad_consensus=False,
    consensus_alternates=(),
    gacha_quantity_hints=(),
    gacha_term_hints=(),
    protect_primary_speaker=False,
    protected_domain_terms=(),
    approved_global_mappings=(),
    verified_terms=(),
    independent_sources,
    contextual_term_candidates=(),
    cue_id=None,
    moss_text='',
    decisions=None,
):
    """只执行 Qwen 明确指出的唯一局部替换；每个补丁单独过安全门。

    ``alternates`` 保留全部证据文本（含派生副本），供相似度佐证判断使用。
    ``independent_sources`` 为**必填** keyword-only 参数：带家族标注的
    ``(family, text)`` 列表，只含可投票的独立 ASR 证据（P1-2）。
    漏传会直接 TypeError——安全门函数不允许静默回退到旧的
    "文本份数计票"语义（同源副本会凑满多票）。
    """
    if not isinstance(edits, list):
        return clean_subtitle_text(original), []

    text = clean_subtitle_text(original)
    original_text = text
    applied = []
    pending = list(edits[:6])
    processed = 0
    grouped = {}
    for family, evidence in independent_sources:
        candidate = content_only(evidence)
        if candidate:
            grouped.setdefault(str(family or ""), []).append(candidate)
    vote_sources = independent_sources
    def reject(rule_id, **evidence):
        if decisions is not None:
            decisions.append({**edit, 'rule_id': rule_id, 'accepted': False,
                'input_text': text, 'evidence': evidence})
    # 每家族取第一份非空文本，供相似度型计数（hinted / 数字 / 数量）使用。
    independent_alternates = [texts[0] for texts in grouped.values()]
    while pending and processed < 12:
        edit = pending.pop(0)
        processed += 1
        if not isinstance(edit, dict):
            continue
        source = clean_subtitle_text(edit.get("from", ""))
        target = clean_subtitle_text(edit.get("to", ""))
        candidate_id = str(edit.get('candidate_id') or '')
        if candidate_id and not any(row.get('candidate_id') == candidate_id
                and row.get('canonical', '').casefold() == target.casefold()
                for row in contextual_term_candidates):
            reject('unknown_or_mismatched_candidate_id', candidate_id=candidate_id)
            continue
        canonical_spellings = {row['canonical'] for row in contextual_term_candidates
            if row.get('status') == 'confirmed' and not row.get('ambiguous')
            and row.get('canonical', '').casefold() == target.casefold()}
        if len(canonical_spellings) == 1:
            target = next(iter(canonical_spellings))
        if not source or not target or content_only(source) == content_only(target):
            from .number_fidelity import numeric_events
            rule = ('ordered_numeric_events_changed' if
                tuple(x.value for x in numeric_events(source)) != tuple(x.value for x in numeric_events(target))
                else 'invalid_or_no_effect')
            reject(rule)
            continue
        if protect_primary_speaker:
            print(
                "   [拦截补丁] 重叠说话人片段只保留当前主播文字："
                f"{source} -> {target}"
            )
            reject('overlapping_speaker_protection')
            continue
        if 'start' in edit or 'end' in edit:
            a, b = edit.get('start'), edit.get('end')
            if (type(a) is not int or type(b) is not int or not 0 <= a < b <= len(original_text)
                    or original_text[a:b] != source
                    or any(a < row['end'] and row['start'] < b for row in applied
                           if 'start' in row)):
                reject('invalid_original_span')
                continue
            shift = sum(len(row['to'])-(row['end']-row['start']) for row in applied
                if 'start' in row and row['end'] <= a)
            span = (a+shift, b+shift)
            if text[span[0]:span[1]] != source:
                reject('stale_original_span')
                continue
        else:
            span = find_unique_patch_span(text, source)
        if span is None:
            print(f"   [跳过补丁] 原片段不唯一或不存在：{source} -> {target}")
            reject('source_not_unique_or_missing')
            continue
        start, end = span
        candidate_preview = clean_subtitle_text(text[:start] + target + text[end:])
        from .content_scene import alias_context_conflict
        alias_entry = next((row for row in contextual_term_candidates
            if row.get('canonical') == target and source in row.get('aliases', ())), None)
        if alias_entry:
            from .content_scene import runtime_content_scene
            scene = runtime_content_scene()
            domains = {row.get('domain_id') for row in alias_entry.get('sources', ()) if row.get('domain_id')}
            labels = {row.get('domain_name') for row in alias_entry.get('sources', ()) if row.get('domain_name')}
            if (scene.source == 'user_selected' and domains
                    and not domains.intersection(scene.domain_ids) and scene.domain not in labels):
                reject('alias_domain_conflict')
                continue
        if alias_entry and alias_context_conflict(text, source, target,
                category=' '.join(str(row.get('category', '')) for row in alias_entry.get('sources', ())), span=span):
            reject('alias_context_topic_conflict')
            continue
        source_content = content_only(source)
        target_content = content_only(target)
        from .terminology_retrieval import (contextual_patch_supported, latin_identifier_patch_supported,
                                           short_latin_identifier_patch_supported)
        short_latin_supported = short_latin_identifier_patch_supported(source, target,
            str(edit.get('basis') or ''), contextual_term_candidates, cue_id, text, moss_text)
        context_supported = contextual_patch_supported(source, target,
            str(edit.get('basis') or ''), contextual_term_candidates, independent_sources, cue_id, text) or short_latin_supported
        latin_term_supported = latin_identifier_patch_supported(source, target,
            str(edit.get('basis') or ''), contextual_term_candidates, cue_id, text) or short_latin_supported
        from .terminology_support import confirmed_patch_evidence, contextual_spelling_patch
        normalization_evidence = confirmed_patch_evidence(source, target, edit.get('basis'),
            contextual_term_candidates, cue_id, text, span=span)
        spelling_supported = contextual_spelling_patch(source, target, edit.get('basis'), text, start)
        context_supported = bool(context_supported or normalization_evidence or spelling_supported)
        latin_term_supported = bool(latin_term_supported or (normalization_evidence
            and re.fullmatch(r'[A-Za-z0-9_]+', target)))
        verified_contents = {
            content_only(term) for term in verified_terms if content_only(term)
        }
        target_is_verified = any(
            target_content in term or term in target_content
            for term in verified_contents
        )
        exact_target_support = count_independent_asr_supports(
            target_content, vote_sources
        )
        actual_support = [{'family': family, 'text': value,
            'exact_target_present': target_content in content_only(value)}
            for family, value in vote_sources if content_only(value)]
        approved_pair = (source_content, target_content) in {
            (content_only(item.get("from", "")), content_only(item.get("to", "")))
            for item in approved_global_mappings
        }
        if (any(row.get('canonical') == target for row in contextual_term_candidates)
                and not context_supported and exact_target_support < 2 and not approved_pair):
            # An unsupported catalog suggestion cannot fall through a looser
            # legacy multi-character phonetic gate. The recall row itself
            # never proves that this ordinary phrase is a proper name.
            print(f"   [拦截补丁] 已召回词条缺少唯一语境与独立支持：{source} -> {target}")
            reject('catalog_without_local_support', canonical=target, independent_exact_support=exact_target_support)
            continue
        if (
            len(source_content) == 1
            and len(target_content) == 1
            and not approved_pair
            and not spelling_supported
        ):
            print(f"   [拦截补丁] 单字歧义交给全文术语表决：{source} -> {target}")
            reject('ambiguous_single_character')
            continue
        changed_chunk_sizes = []
        for tag, left_start, left_end, right_start, right_end in SequenceMatcher(
            None,
            source_content,
            target_content,
            autojunk=False,
        ).get_opcodes():
            if tag != "equal":
                changed_chunk_sizes.append(
                    max(left_end - left_start, right_end - right_start)
                )
        if (
            changed_chunk_sizes
            and max(changed_chunk_sizes) <= 1
            and not target_is_verified
            and exact_target_support < 2
            and not approved_pair
            and not context_supported
        ):
            print(
                "   [拦截补丁] 普通单字差异缺少两套精确支持："
                f"{source} -> {target}"
            )
            reject('local_difference_without_two_sources', independent_exact_support=exact_target_support)
            continue
        if (
            len(source_content) != len(target_content)
            and not target_is_verified
            and exact_target_support < 2
            and not approved_pair
            and not context_supported
        ):
            print(
                "   [拦截补丁] 增删字缺少两套精确支持："
                f"{source} -> {target}"
            )
            reject('length_change_without_support', independent_exact_support=exact_target_support,
                actual_asr_support=actual_support, model_evidence_is_not_support=True)
            continue
        protected_hit = next(
            (
                term
                for term in protected_domain_terms
                if term and term in content_only(text) and term in source_content
            ),
            "",
        )
        source_looks_like_domain_term = (
            len(source_content) >= 2
            and source_content[-1:] in GLOBAL_DOMAIN_TERM_SUFFIXES
        )
        if (protected_hit or source_looks_like_domain_term) and not approved_pair and not (
                context_supported and protected_hit not in verified_terms):
            protected_label = protected_hit or source
            print(
                f"   [拦截补丁] 专名“{protected_label}”只能由联网全文表决修改："
                f"{source} -> {target}"
            )
            reject('protected_domain_term')
            continue
        cue_length = display_length(text)
        from .number_fidelity import numeric_events
        # Digits inside a validated complete canonical ID are spelling, not
        # a newly spoken quantity. Every numeric event outside this token
        # still has to retain its value and order.
        numeric_protection = (source, target) if latin_term_supported else ()
        if (tuple(x.value for x in numeric_events(text, protected_terms=numeric_protection)) !=
                tuple(x.value for x in numeric_events(candidate_preview, protected_terms=numeric_protection))):
            record_run_event('numeric_edit_rejected', source=text, proposed=candidate_preview,
                             reason='ordered_numeric_events_changed')
            reject('ordered_numeric_events_changed')
            continue
        unwanted_formats = unwanted_arabic_format_values(text, candidate_preview)
        if unwanted_formats:
            values = ",".join(sorted(unwanted_formats))
            print(
                f"   [拦截补丁] 普通中文数词不得数字化（{values}）："
                f"{source} -> {target}"
            )
            reject('unwanted_numeric_format', values=sorted(unwanted_formats))
            continue
        quantity_hint_supported = hinted_quantity_change_is_supported(
            source,
            target,
            gacha_quantity_hints,
            independent_alternates,
        )
        domain_hint_supported = hinted_domain_term_change_is_supported(
            source,
            target,
            gacha_term_hints,
        )
        lost_protected_phrases = [
            phrase
            for phrase in ASR_CONSENSUS_PROTECTED_PHRASES
            if phrase in content_only(text)
            and phrase not in content_only(candidate_preview)
        ]
        if lost_protected_phrases:
            exact_target_support = count_independent_asr_supports(
                target_content, vote_sources
            )
            if exact_target_support < 2:
                print(
                    "   [拦截补丁] 受保护词缺少两套 ASR 的新写法支持："
                    f"{','.join(lost_protected_phrases)}；{source} -> {target}"
                )
                reject('protected_phrase_removed')
                continue
        broad_consensus = (
            allow_broad_consensus
            and broad_consensus_support_count(target, consensus_alternates) >= 2
            and len(target_content) >= max(1, int(len(source_content) * 0.72))
        )
        if (
            cue_length > 6
            and len(source_content) > max(6, int(cue_length * 0.60))
            and not broad_consensus
        ):
            basis = clean_subtitle_text(edit.get("basis", "")) or "未说明"
            smaller_edits = decompose_broad_edit(source, target, basis)
            if smaller_edits:
                print(
                    f"   [拆分补丁] 修改范围过大，改为 {len(smaller_edits)} 个近音小补丁："
                    f"{source} -> {target}"
                )
                pending = smaller_edits + pending
            else:
                print(f"   [拦截补丁] 修改范围过大：{source} -> {target}")
                reject('broad_semantic_rewrite')
            continue
        unsupported_numerals = introduces_unverified_numeral(
            source,
            target,
            independent_alternates,
        )
        if latin_term_supported:
            unsupported_numerals = set()
        if unsupported_numerals and contextual_quantity_change_is_supported(
            text,
            candidate_preview,
            independent_alternates,
        ):
            unsupported_numerals = set()
        if unsupported_numerals and quantity_hint_supported:
            unsupported_numerals = set()
        if unsupported_numerals:
            values = ",".join(sorted(unsupported_numerals))
            print(
                f"   [拦截补丁] 新数字缺少两套 ASR 支持（{values}）："
                f"{source} -> {target}"
            )
            reject('unverified_new_numeral', values=sorted(unsupported_numerals))
            continue
        lost_quantities = quantity_expression_keys(
            text,
            CORRECTION_PROTECTED_QUANTITY_UNITS,
        ) - quantity_expression_keys(
            candidate_preview,
            CORRECTION_PROTECTED_QUANTITY_UNITS,
        )
        if lost_quantities and not contextual_quantity_change_is_supported(
            text,
            candidate_preview,
            independent_alternates,
        ):
            values = ",".join(
                f"{number}{unit}" for number, unit in sorted(lost_quantities)
            )
            print(
                f"   [拦截补丁] 不得破坏已有数量单位（{values}）："
                f"{source} -> {target}"
            )
            reject('quantity_unit_removed')
            continue
        source_digits = re.findall(r"\d+", source)
        if source_digits and any(value not in target for value in source_digits) and not latin_term_supported:
            print(f"   [拦截补丁] 不得改写已有数字：{source} -> {target}")
            reject('existing_digits_changed')
            continue
        source_latin = re.findall(r"[A-Za-z]+", source)
        if source_latin and not latin_term_supported and any(
            value.lower() not in target.lower() for value in source_latin
        ):
            print(f"   [拦截补丁] 不得改写已有英文/缩写：{source} -> {target}")
            reject('existing_latin_changed')
            continue
        if len(target_content) < len(source_content) and not broad_consensus and not normalization_evidence:
            print(f"   [拦截补丁] 不得跟随第二套 ASR 删字：{source} -> {target}")
            reject('unsupported_deletion')
            continue
        left_sound = phonetic_text(source_content)
        right_sound = phonetic_text(target_content)
        local_sound_distance = levenshtein(left_sound, right_sound) / max(
            1, len(left_sound), len(right_sound)
        )
        alternate_exact_short = (
            target_content in normalize_asr_supports(alternates)
            and len(source_content) <= 6
            and len(source_content) == len(target_content)
        )
        if (
            local_sound_distance > 0.62
            and not alternate_exact_short
            and not broad_consensus
            and not quantity_hint_supported
            and not domain_hint_supported
            and not latin_term_supported
            and not normalization_evidence
        ):
            print(
                f"   [拦截补丁] 局部读音差距过大（{local_sound_distance:.2f}）："
                f"{source} -> {target}"
            )
            reject('phonetic_distance', distance=local_sound_distance)
            continue
        following = content_only(text[end:])[:1]
        if (
            following
            and target_content.endswith(following)
            and not source_content.endswith(following)
        ):
            print(f"   [拦截补丁] 替换后会产生边界重复：{source} -> {target}")
            reject('boundary_duplicate')
            continue
        candidate = candidate_preview
        safe, reason = correction_is_safe(text, candidate, alternates)
        if not safe and quantity_hint_supported:
            safe = True
            reason = "Qwen采纳抽卡数量近音提示，且两套ASR支持原近音"
        elif not safe and domain_hint_supported:
            safe = True
            reason = "Qwen采纳强抽卡语境候选"
        elif not safe and latin_term_supported:
            safe = True
            reason = "模型采纳本批已确认规范词，完整 Latin ID 的有限近形补丁；未核验原音"
        elif not safe and normalization_evidence:
            safe, reason = True, "已确认词条的有据局部规范化；未核验原音"
        elif not safe and spelling_supported:
            safe, reason = True, "持续动作语境中的局部同音字纠错"
        if not safe:
            print(f"   [拦截补丁] {source} -> {target}：{reason}")
            reject('whole_sentence_safety', reason=reason)
            continue
        text = candidate
        applied.append(
            {
                "from": source,
                "to": target,
                **({'start': edit['start'], 'end': edit['end']} if 'start' in edit and 'end' in edit else {}),
                **({'candidate_id': candidate_id} if candidate_id else {}),
                'type': ('alias_normalization' if normalization_evidence and
                    normalization_evidence['rule_id'] == 'confirmed_exact_alias' else
                    'id_spelling' if latin_term_supported else 'asr_correction'),
                'evidence': str(edit.get('evidence') or edit.get('basis') or ''),
                'actual_independent_exact_support': exact_target_support,
                **({'model_to': clean_subtitle_text(edit.get('to', ''))}
                   if target != clean_subtitle_text(edit.get('to', '')) else {}),
                "basis": clean_subtitle_text(edit.get("basis", "")) or "未说明",
                "reason": reason,
                "rule_id": (normalization_evidence['rule_id'] if normalization_evidence
                    else 'ongoing_aspect_spelling' if spelling_supported else 'existing_local_safety'),
                **({'normalization_evidence': normalization_evidence} if normalization_evidence else {}),
                **({'terminology_evidence': {'status': next(x['status'] for x in contextual_term_candidates
                    if x.get('canonical') == target), 'basis': (
                        'model_glossary_context_and_same_cue_moss_repeated_ids' if short_latin_supported
                        else 'model_glossary_context_and_bounded_latin_token' if latin_term_supported
                        else 'model_glossary_context_and_independent_phonetic_asr'),
                    'acoustic_verified': False}}
                   if context_supported and any(x.get('canonical') == target for x in contextual_term_candidates) else {}),
            }
        )
    return text, applied
