"""correction stage implementation extracted from subtitle_core."""

import json
import re

# The core owns runtime configuration; these imports preserve the existing public contract.
from subtitle_core import *  # noqa: F401,F403
from twobyteasr.text_similarity import levenshtein, phonetic_text

__all__ = [
    'ASR_CONSENSUS_MIN_SIMILARITY',
    'ASR_CONSENSUS_PROTECTED_PHRASES',
    'MOSS_TERM_STABILITY_MIN_SEGMENTS',
    'MOSS_TERM_STABILITY_MIN_CHARS',
    'MOSS_TERM_STABILITY_MAX_CHARS',
    'MOSS_DOMAIN_TERM_SUFFIXES',
    'MOSS_TERM_STABILITY_STOPWORDS',
    'GLOBAL_DOMAIN_TERM_SUFFIXES',
    'split_boundary_cohesion_term',
    'split_items_for_api',
    'extract_json_object_text',
    'parse_qwen_object',
    'parse_qwen_json',
    'levenshtein',
    'phonetic_text',
    'select_relevant_game_lexicon_terms',
    'apply_title_profile_aliases',
    'repair_with_user_glossary_terms',
    'collect_stable_moss_term_candidates',
    'collect_global_term_disputes',
    '_public_https_url',
    'verify_term_source_urls',
    'discover_global_domain_term_mappings',
    'apply_global_domain_term_mappings',
    'asr_consensus_similarity',
    'reference_consensus_edits',
    'apply_reference_consensus_corrections',
    'reference_differences_are_compatible',
    'consensus_candidate_is_safe',
    'build_asr_difference_hints',
    'build_gacha_quantity_hints',
    'build_gacha_term_hints',
    'build_strong_reference_consensus_hint',
    'hinted_quantity_change_is_supported',
    'hinted_domain_term_change_is_supported',
    'nearby_glossary_candidates',
    'normalize_asr_supports',
    'correction_is_safe',
    'decompose_broad_edit',
    'find_unique_patch_span',
    'broad_consensus_support_count',
    'apply_correction_edits',
    'call_correction_api',
    'boundary_overlap_length',
    'trim_content_suffix',
    'trim_content_prefix',
    'repair_introduced_boundary_duplicates',
    'apply_final_segment_boundary_dedup',
    'filter_untrusted_polished_text',
    'polish_subtitles',
]

def split_boundary_cohesion_term(left_text, right_text):
    """返回被两段从中间切开的确定词语；只影响分批，不修改文字。"""
    left = content_exact(left_text)
    right = content_exact(right_text)
    for term in sorted(BOUNDARY_COHESION_TERMS, key=len, reverse=True):
        term = content_exact(term)
        for offset in range(1, len(term)):
            if left.endswith(term[:offset]) and right.startswith(term[offset:]):
                return term
    return ""


def split_items_for_api(items, max_cues=API_BATCH_MAX_CUES, max_chars=API_BATCH_MAX_CHARS):
    batches = []
    current = []
    current_chars = 0

    for item in items:
        cost = len(item.text) + 32
        if current and (
            len(current) >= max_cues
            or current_chars + cost > max_chars
        ):
            carry = None
            if (
                len(current) > 1
                and split_boundary_cohesion_term(current[-1].text, item.text)
            ):
                carry = current.pop()
                current_chars -= len(carry.text) + 32
            batches.append(current)
            current = [carry] if carry is not None else []
            current_chars = len(carry.text) + 32 if carry is not None else 0
        current.append(item)
        current_chars += cost

    if current:
        batches.append(current)
    return batches


def _decode_json_value(content):
    """Decode the first complete JSON value, tolerating fences and short prose.

    ``find('{')/rfind('}')`` loses nested objects and rejects valid top-level
    arrays.  ``raw_decode`` lets the JSON decoder determine the real boundary
    while still accepting providers that prepend a short explanation.
    """
    text_value = str(content or "").lstrip("\ufeff").strip()
    if not text_value:
        raise ValueError("模型没有返回 JSON。")
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text_value, re.S | re.I)
    candidates = [fence.group(1).strip()] if fence else [text_value]
    if not fence:
        candidates.append(text_value.replace("\ufeff", "", 1).strip())
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for index, char in enumerate(candidate):
            if char not in "[{\"":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            # Some gateways double-encode JSON as a JSON string.
            if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
                try:
                    value = json.loads(value)
                except (TypeError, ValueError):
                    pass
            if isinstance(value, (dict, list)):
                return value
    if "{" in text_value or "[" in text_value:
        raise ValueError("模型 JSON 解析失败：响应不完整或格式损坏。")
    raise ValueError("模型没有返回 JSON。")


def extract_json_object_text(content):
    """从模型输出中提取完整 JSON 值的文本（兼容旧调用名）。"""
    value = _decode_json_value(content)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_qwen_object(content):
    data = _decode_json_value(content)
    if isinstance(data, dict):
        return data
    # A few OpenAI-compatible gateways ignore the requested object mode and
    # return the obvious schema array.  Coerce only unambiguous shapes; all
    # downstream schema validation remains in charge of the actual fields.
    if isinstance(data, list):
        if all(isinstance(item, dict) and "id" in item for item in data):
            return {"cues": data}
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in data):
            return {"boundaries": data}
        if all(isinstance(item, dict) and {"from", "to"}.issubset(item) for item in data):
            return {"mappings": data}
    raise ValueError("模型 JSON 顶层类型不符合对象契约。")


def parse_qwen_json(content):
    data = parse_qwen_object(content)
    items = data.get("cues")
    if not isinstance(items, list):
        raise ValueError("模型 JSON 中缺少 cues 数组。")
    return items


from twobyteasr.domain_terms import (
    ASR_CONSENSUS_MIN_SIMILARITY,
    ASR_CONSENSUS_PROTECTED_PHRASES,
    GLOBAL_DOMAIN_TERM_SUFFIXES,
    MOSS_DOMAIN_TERM_SUFFIXES,
    MOSS_TERM_STABILITY_MAX_CHARS,
    MOSS_TERM_STABILITY_MIN_CHARS,
    MOSS_TERM_STABILITY_MIN_SEGMENTS,
    MOSS_TERM_STABILITY_STOPWORDS,
    _public_https_url,
    apply_title_profile_aliases,
    apply_global_domain_term_mappings,
    collect_global_term_disputes,
    collect_stable_moss_term_candidates,
    discover_global_domain_term_mappings,
    select_relevant_game_lexicon_terms,
    repair_with_user_glossary_terms,
    verify_term_source_urls,
)


from twobyteasr.correction_safety import (
    apply_reference_consensus_corrections,
    apply_correction_edits,
    asr_consensus_similarity,
    broad_consensus_support_count,
    build_asr_difference_hints,
    build_gacha_quantity_hints,
    build_gacha_term_hints,
    build_strong_reference_consensus_hint,
    consensus_candidate_is_safe,
    correction_is_safe,
    decompose_broad_edit,
    find_unique_patch_span,
    hinted_domain_term_change_is_supported,
    hinted_quantity_change_is_supported,
    nearby_glossary_candidates,
    normalize_asr_supports,
    reference_differences_are_compatible,
    reference_consensus_edits,
)


from twobyteasr.polishing import (
    apply_final_segment_boundary_dedup,
    boundary_overlap_length,
    call_correction_api,
    filter_untrusted_polished_text,
    polish_subtitles,
    repair_introduced_boundary_duplicates,
    trim_content_prefix,
    trim_content_suffix,
)


import subtitle_core as _core
for _name in __all__:
    setattr(_core, _name, globals()[_name])
del _core, _name
