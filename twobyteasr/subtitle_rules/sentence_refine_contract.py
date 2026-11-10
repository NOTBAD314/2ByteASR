"""Lossless Studio refinement wire rules and conservative boundary candidates."""

from __future__ import annotations

import json
import re
import unicodedata

PROTOCOL_VERSION = "studio-refine-v5-zh-complete-expression"


class RefineError(ValueError):
    def __init__(self, message, category="format_error"):
        super().__init__(message)
        self.category = category


def _unique_object(pairs):
    result = {}
    duplicates = []
    for key, value in pairs:
        if key in result:
            duplicates.append(key)
        result[key] = value
    if duplicates:
        # A damaged row can be refused without discarding independent rows.
        # Conflicting top-level objects still have no trusted interpretation.
        if 'cue_id' not in result:
            raise RefineError(f"返回 JSON 有重复字段 {duplicates[0]}", "duplicate_field")
        ids = list(dict.fromkeys(value for key, value in pairs if key == 'cue_id' and isinstance(value, str)))
        return {'cue_id': ids[0] if len(ids) == 1 else '', '_duplicate_fields': duplicates,
                '_candidate_cue_ids': ids}
    return result


def _without_trailing_commas(text):
    result = []
    quoted = escaped = False
    for index, char in enumerate(text):
        if not quoted and char == ",":
            following = index + 1
            while following < len(text) and text[following].isspace():
                following += 1
            if following < len(text) and text[following] in '}]':
                continue
        result.append(char)
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
    return "".join(result)


def parse_response(content):
    """Extract exactly one balanced JSON value, then apply unambiguous repair.

    A stack respects strings and escapes. No bracket completion, quote rewriting
    or selection between competing objects is permitted.
    """
    if not isinstance(content, str) or not content.strip():
        raise RefineError("模型没有返回正文", "empty_response")
    if len(content) > 1_000_000:
        raise RefineError("返回内容超过安全解析大小", "response_too_large")
    text = content.lstrip("\ufeff").strip()
    stack = []
    candidates = []
    quoted = escaped = False
    start = None
    for index, char in enumerate(text):
        if not stack:
            if char in "{[":
                stack.append(char)
                start = index
            continue
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted:
            if char in "{[":
                stack.append(char)
            elif char in "}]":
                if stack[-1] != {"}": "{", "]": "["}[char]:
                    raise RefineError("JSON 括号不匹配")
                stack.pop()
                if not stack:
                    candidates.append(text[start:index + 1])
    if stack:
        raise RefineError("模型返回未收齐，JSON 尚未结束", "incomplete_response")
    if len(candidates) != 1:
        raise RefineError("返回中有多个候选 JSON，无法确定应采用哪一个" if candidates else "返回中没有完整 JSON",
                          "ambiguous_response" if candidates else "format_error")
    raw = candidates[0]
    repaired = _without_trailing_commas(raw)
    try:
        payload = json.loads(repaired, object_pairs_hook=_unique_object,
                             parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except RefineError:
        raise
    except ValueError as exc:
        raise RefineError(f"JSON 格式错误，位置 {getattr(exc, 'pos', '?')}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RefineError("顶层必须包含 results 数组", "structure_error")
    if any(not isinstance(row, dict) for row in payload["results"]):
        raise RefineError("results 中存在非对象结果", "structure_error")
    repairs = []
    if raw != text:
        repairs.append("已提取唯一完整 JSON")
    if raw != repaired:
        repairs.append("已移除字符串以外的尾逗号")
    return payload["results"], repairs


def boundary_candidates(text, language="", terms=()):
    """Raw Python code-point offsets. Text is never normalized for reconstruction."""
    from .language_rules import japanese_phrase_spans
    from .segmentation import chinese_word_spans, lexical_boundary_terms

    blocked = set()
    if language == "ja":
        spans = japanese_phrase_spans(text)
    elif language in ("", "zh", "zh-CN", "zh-TW"):
        spans = chinese_word_spans(text)
    else:
        spans = []
    if language in {'en', 'ko', 'es', 'de', 'fr', 'pt', 'it', 'ru'}:
        for match in re.finditer(r'\S+', text):
            blocked.update(range(match.start()+1, match.end()))
    for start, end, _ in spans:
        blocked.update(range(start + 1, end))
    # Words, decimals, abbreviations and number-unit groups stay intact in all languages.
    for pattern in (r"[A-Za-zÀ-ɏ]+(?:['’.-][A-Za-zÀ-ɏ]+)*", r"\d+(?:[.,]\d+)*(?:\s*(?:%|％|ms|kg|km|GB|MB|Hz|fps|seconds?|minutes?|秒|分钟|公斤|公里|元|万|亿))?"):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            blocked.update(range(match.start() + 1, match.end()))
    for term in set(terms) | set(lexical_boundary_terms()):
        if len(term) < 2:
            continue
        start = text.find(term)
        while start >= 0:
            blocked.update(range(start + 1, start + len(term)))
            start = text.find(term, start + 1)
    for offset in range(1, len(text)):
        left, right = text[offset - 1], text[offset]
        if (unicodedata.combining(right) or right in "\ufe0e\ufe0f\u200d" or left == "\u200d"
                or 0x1F3FB <= ord(right) <= 0x1F3FF
                or 0x1F1E6 <= ord(left) <= 0x1F1FF and 0x1F1E6 <= ord(right) <= 0x1F1FF):
            blocked.add(offset)
    # Reuse the language's phrase scoring, including phrasal verbs and hanging determiners.
    if language == "en" or language in {"es", "de", "fr", "pt", "it", "ru"}:
        from .english_segmentation import break_scores
        tokens = list(re.finditer(r"\S+", text))
        lexicon = None
        if language != "en":
            from .european_text import lexicon as get_lexicon
            lexicon = get_lexicon(language)
        scores = break_scores([match.group() for match in tokens], lexicon=lexicon)
        for index, (match, score) in enumerate(zip(tokens, scores)):
            if score < -20:
                blocked.update(range(match.end(), tokens[index + 1].start() + 1))
    from .segmentation_profiles import legal_raw_boundaries
    legal = legal_raw_boundaries(text, language or 'zh')
    first_content = len(text) - len(text.lstrip())
    last_content = len(text.rstrip())
    return {f"b{offset:05d}": offset - 1 for offset in range(1, len(text))
            if offset in legal and offset not in blocked and first_content < offset < last_content
            and (language not in {'en', 'ko', 'es', 'de', 'fr', 'pt', 'it', 'ru'}
                 or not text[offset-1].isspace() and text[offset].isspace())}


def decode_boundary_ids(row, candidates):
    """Legacy offsets remain valid only if they pass the same candidate rules."""
    result = dict(row)
    if "break_after" in row:
        ids = row["break_after"]
        if not isinstance(ids, list) or any(not isinstance(item, str) or item not in candidates for item in ids):
            raise RefineError("返回了本次输入没有提供的断点编号", "boundary_id_error")
        offsets = [candidates[item] for item in ids]
        if offsets != sorted(set(offsets)):
            raise RefineError("断点编号重复或顺序错误", "boundary_id_error")
        if "split_after_chars" in row and row["split_after_chars"] != offsets:
            raise RefineError("断点编号与字符索引相互矛盾", "structure_error")
        result["split_after_chars"] = offsets
    return result
