"""Intra-phrase spacing for conversational subtitles (2026-09-20 rework).

Separates independent interjections, repeated acknowledgements and whole-phrase
repeats with plain U+0020 spaces, driven by word-level timestamps where
available (audio evidence, not blind text heuristics).

User contract:
- Idempotent: applying twice yields the same string.
- Conservative: never splits legitimate words ("好像还不错", "这个判断是对的").
- Trailing interjections stay attached ("蹲一下不亏啊").
- U+0020 only; never full-width, zero-width, or runs of spaces.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

INTERJECTIONS = set("嗯啊哎哦噢呃欸诶咦嚯哇呀哈嘿喏咯喽咦欸")
ACKNOWLEDGEMENTS = {"对", "好", "是", "行", "中", "嗯", "啊"}
TAIL_PARTICLES = set("的了吧呢吗啊呀嘛啦")
# Multi-char interjection compounds must never be split by the single-char
# rules (they keep their own spacing contract from segmentation.py).
COMPOUND_INTERJECTIONS = (
    "哎呦", "哎哟", "诶呦", "诶哟", "哎呀", "诶呀", "哦豁", "哇哦",
    "哎哎", "嗯嗯", "啊啊", "哦哦", "欸欸", "哟呵", "呦呵", "嗨呀",
)


def _clean(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", "", str(text or ""))


def _word_field(word, name, default=None):
    if isinstance(word, Mapping):
        return word.get(name, default)
    return getattr(word, name, default)


def _word_gaps(words: Sequence[Mapping[str, object]] | None) -> list[float] | None:
    if not words:
        return None
    anchors = [w for w in words if str(_word_field(w, "text", "") or "").strip()]
    gaps = []
    for index in range(len(anchors) - 1):
        try:
            gaps.append(float(_word_field(anchors[index + 1], "start_ms", 0)) - float(_word_field(anchors[index], "end_ms", 0)))
        except (TypeError, ValueError):
            gaps.append(0.0)
    return gaps


def apply_intra_phrase_spacing(
    text: str,
    words: Sequence[Mapping[str, object]] | None = None,
    *,
    pause_ms: int = 140,
) -> str:
    """Insert phrase-separating spaces; idempotent; preserves character order.

    ``words`` is word-level evidence (``[{"text", "start_ms", "end_ms"}, ...]``).
    With it, a leading interjection separates only on a real pause; without it
    only unambiguous shapes (leading interjection + clear phrase, repeated
    acknowledgements, whole-phrase repetition) are separated.
    """
    original = str(text or "").strip()
    cleaned = _clean(original)
    if not cleaned:
        return original
    # Compound interjections (哎呀魔偶…) keep their segmentation-era layout.
    for compound in COMPOUND_INTERJECTIONS:
        if cleaned.startswith(compound) and len(cleaned) > len(compound):
            head, tail = original[: len(compound) + _leading_space_len(original, len(compound))], \
                original[len(compound) + _leading_space_len(original, len(compound)):]
            if _clean(tail)[:1] not in TAIL_PARTICLES and len(_clean(tail)) >= 2:
                return f"{compound} {tail.strip()}".strip()
            return original
    gaps = _word_gaps(words)
    pieces = _layout(cleaned, gaps, pause_ms)
    result = " ".join(piece for piece in pieces if piece)
    return result or original


def _leading_space_len(text: str, index: int) -> int:
    extra = 0
    while index + extra < len(text) and text[index + extra] == " ":
        extra += 1
    return extra


def _layout(cleaned: str, gaps: list[float] | None, pause_ms: int) -> list[str]:
    pieces: list[str] = []
    rest = cleaned
    has_word_evidence = gaps is not None

    # 1) Leading interjection / acknowledgement.
    #    ACK 字（对/好/是/行）可作实词词头（"好像还不错"），无词级停顿证据
    #    时不得拆；纯语气词（嗯/啊/哎…）无证据也可拆。
    if len(rest) >= 3:
        head, tail = rest[0], rest[1:]
        repeated_pair = head in ACKNOWLEDGEMENTS and tail[:1] == head
        if (head in INTERJECTIONS or head in ACKNOWLEDGEMENTS) and not repeated_pair:
            rest_is_phrase = len(tail) >= 2 and tail[0] not in TAIL_PARTICLES
            if rest_is_phrase:
                if has_word_evidence and gaps:
                    allowed = gaps[0] >= pause_ms
                else:
                    allowed = head in INTERJECTIONS
                if allowed:
                    pieces.append(head)
                    rest = tail

    # 2) Repeated acknowledgements: 对对/好好/是是 -> 对 对 (each its own piece).
    for index in range(len(rest) - 1):
        a, b = rest[index], rest[index + 1]
        if a == b and a in ACKNOWLEDGEMENTS:
            pieces.append(rest[:index])
            pieces.append(a)
            pieces.append(b)
            rest = rest[index + 2:]
            break

    if rest:
        # 3) Phrase repetition: 有点担心啊有点担心 -> 有点担心啊 有点担心.
        #    Both the exact half repeat and the trailing-particle variant.
        split = _phrase_repeat_split(rest)
        if split:
            pieces.extend(split)
            return pieces
        pieces.append(rest)
    return [piece for piece in pieces if piece]


def _phrase_repeat_split(text: str) -> list[str] | None:
    if len(text) < 6 or " " in text:
        return None
    half = len(text) // 2
    if len(text) % 2 == 0 and text[:half] == text[half:]:
        if not _is_single_word_like(text[:half]):
            return [text[:half], text[half:]]
    # 有点担心啊 + 有点担心: head ends with a particle, stripped head repeats.
    for cut in range(3, len(text) - 2):
        head, tail = text[:cut], text[cut:]
        stripped = head.rstrip("".join(TAIL_PARTICLES))
        if stripped and stripped == tail and not _is_single_word_like(stripped):
            return [head, tail]
    return None


def _is_single_word_like(token: str) -> bool:
    """Avoid splitting reduplicative words (试试/看看/等等) as phrase repeats."""
    if len(token) == 2 and token[0] == token[1]:
        return True
    return len(token) <= 2
