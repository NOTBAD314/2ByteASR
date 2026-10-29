"""Conservative proposal guards shared by local recall, AI and consistency.

Particles and quantities stay in the caption. Literal aliases remain
evidence except where they destroy a valid term or a quantity in context.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

_NUMBER = r"[零〇一二两三四五六七八九十百千万亿\d]+(?:[点\.][零〇一二两三四五六七八九\d]+)?"
_QUANTITY = re.compile(r"(?:增加|减少|降低|提高|提升|减|加|升|降|第|负|正|[+＋－-])\s*" + _NUMBER
                       + r"|" + _NUMBER + r"\s*(?:级|次|层|点|个|秒|分钟|小时|倍|枚|颗|只|件|%|％)")
_PARTICLES = frozenset("啊呀呢吧嘛哦哟喔呗啦呐哇唉哎诶欸" + " ，。！？、；：…,.!?;:　")


def numeric_expression_at(text, start, end):
    return any(a < end and start < b for a, b in (m.span() for m in _QUANTITY.finditer(str(text))))


@lru_cache(maxsize=24)
def _pattern(names):
    names = sorted({n for n in names if n}, key=lambda n: (-len(n), n))
    return re.compile("|".join(re.escape(n) for n in names), re.I) if names else None


def snapshot_names(snapshot):
    if hasattr(snapshot, "review_names"):
        return snapshot.review_names
    return tuple(dict.fromkeys(name for library in getattr(snapshot, "libraries", ())
                               for name in (*[t.canonical for t in library.terms if t.confirmed],
                                            *library.reference_terms) if name))


@lru_cache(maxsize=24)
def _folded_names(names):
    from ..subtitle_rules.chinese_script import to_simplified
    return tuple(to_simplified(n) for n in names)


@lru_cache(maxsize=24)
def _identities(names):
    from ..subtitle_rules.chinese_script import fold
    return frozenset(fold(n).casefold() for n in names)


def contains_name(snapshot, name):
    from ..subtitle_rules.chinese_script import fold
    return fold(name).casefold() in _identities(snapshot_names(snapshot))


def review_change_reason(text, span, replacement, *, snapshot=None, names=(), inferred=True, protect_exact=True):
    """Return a rejection reason; an empty result does not assert correctness."""
    from ..subtitle_rules.chinese_script import to_simplified
    from ..subtitle_rules.stutter_cleanup import common_word_in_context
    if not isinstance(span, (tuple, list)) or len(span) != 2:
        return "invalid_span"
    start, end = span
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text):
        return "invalid_span"
    source = text[start:end]
    if source == replacement:
        return "no_change"
    if numeric_expression_at(text, start, end):
        return "quantity_in_context"
    if source.isascii() and source.casefold() == replacement.casefold():
        return ""  # preserve explicitly configured ID casing, e.g. BerLIN
    view, target = to_simplified(text), to_simplified(replacement)
    source = view[start:end]
    known = _folded_names(snapshot_names(snapshot) if snapshot is not None else tuple(names))
    pattern = _pattern(known)
    if pattern is not None:
        matches = list(pattern.finditer(view))
        edits = [(start+a, start+b) for op, a, b, _c, _d in SequenceMatcher(None, source, target, autojunk=False).get_opcodes()
                 if op != "equal"]
        if protect_exact and any(m.start() < b and a < m.end() if a < b else m.start() < a < m.end()
               for m in matches for a, b in edits):
            return "already_correct_term"
        if source and all(char in _PARTICLES for char in source) and any(
                m.end() == start or m.start() == end for m in matches):
            return "normal_outer_particle"
    if target and source != target and (source.startswith(target) and all(c in _PARTICLES for c in source[len(target):])
            or source.endswith(target) and all(c in _PARTICLES for c in source[:-len(target)])):
        return "normal_outer_particle"
    if inferred and common_word_in_context(view, start, end):
        return "ordinary_word_without_context_evidence"
    return ""
