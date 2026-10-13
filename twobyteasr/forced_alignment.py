"""Alignment units with reversible positions for Qwen3-ForcedAligner.

The official aligner (qwen-asr 0.0.6, ``qwen3_forced_aligner.py``) puts two
``<timestamp>`` slots after every unit and predicts each slot as a class times
``timestamp_segment_time`` (80 ms). For Japanese it segments with
``nagisa.tagging`` and keeps only letters/digits of each word (Unicode L*/N*
and the apostrophe), on nagisa's NFKC-like normalised text. Those words do not
map back to the displayed text by themselves (``ＡＢＣ`` becomes ``ABC``,
``ｽﾄﾘｰﾄ`` becomes ``ストリート`` and digits are split one by one).

This module builds the same kind of unit list but remembers, for every unit,
the ``[char_start, char_end)`` span of the original text, so display text is
never rewritten. Units are passed to the model through its own slot format
(the "arbitrary units" of the model card); nothing here invents times.

``timed_units`` keeps the raw model value of every slot next to the value
after the official monotonic repair (``fix_timestamp``) and says which slots
were repaired and how. ``reliable_segments`` exposes a boundary only where the
model measured it; words are never divided by duration or character count.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import unicodedata

ALIGNER_STEP_MS = 80
ALIGNER_MAX_SECONDS = 300.0
ALIGNER_REPO = "Qwen/Qwen3-ForcedAligner-0.6B"
ALIGNER_REVISION = "c7cbfc2048c462b0d63a45797104fc9db3ad62b7"
ALIGNER_CODE = "qwen-asr==0.0.6 (qwen_asr/inference/qwen3_forced_aligner.py, QwenLM/Qwen3-ASR 9567667)"
UNIT_POLICY_VERSION = "ja-units-v1"

# Kana voicing marks combine with the preceding base in NFKC (ｶﾞ -> ガ).
_COMBINING_EXTRA = frozenset("゙゚ﾞﾟ")
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese", "en": "English", "ko": "Korean"}


def kept_char(char: str) -> bool:
    """The official processor's ``is_kept_char``: letters, digits, apostrophe."""
    if char == "'":
        return True
    category = unicodedata.category(char)
    return category.startswith("L") or category.startswith("N")


def content_char_map(text: str) -> list[tuple[str, int, int]]:
    """``(normalized kept char, original start, original end)`` in text order.

    Each original grapheme base plus its combining marks is NFKC-normalised as
    one cluster; every kept character of the result maps to that cluster.
    """
    text = str(text or "")
    out: list[tuple[str, int, int]] = []
    index = 0
    while index < len(text):
        end = index + 1
        while end < len(text) and (unicodedata.combining(text[end]) or text[end] in _COMBINING_EXTRA):
            end += 1
        for char in unicodedata.normalize("NFKC", text[index:end]):
            if kept_char(char):
                out.append((char, index, end))
        index = end
    return out


@dataclass(frozen=True)
class AlignUnit:
    text: str          # model-facing text (NFKC letters/digits)
    char_start: int    # span in the ORIGINAL text, end exclusive
    char_end: int
    kind: str          # word | number | latin | char
    word_index: int    # index of the enclosing word unit


class UnitMappingError(ValueError):
    pass


def _script(char: str) -> str:
    if char.isdigit():
        return "digit"
    if char.isascii() and char.isalpha():
        return "latin"
    return "other"


def word_units(text: str, words) -> list[AlignUnit]:
    """Map tokenizer ``words`` (e.g. nagisa) back onto ``text``.

    Digit runs that the tokenizer split per digit are merged into one unit:
    a number's reading has no per-digit acoustic boundary.
    """
    content = content_char_map(text)
    position = 0
    raw: list[AlignUnit] = []
    for word in words:
        cleaned = "".join(c for c in unicodedata.normalize("NFKC", str(word)) if kept_char(c))
        if not cleaned:
            continue
        piece = content[position:position + len(cleaned)]
        if len(piece) != len(cleaned) or "".join(c for c, _a, _b in piece) != cleaned:
            raise UnitMappingError(f"tokenizer word {word!r} does not match text at content index {position}")
        kind = ("number" if all(_script(c) == "digit" for c in cleaned)
                else "latin" if all(_script(c) == "latin" for c in cleaned) else "word")
        raw.append(AlignUnit(cleaned, piece[0][1], piece[-1][2], kind, len(raw)))
        position += len(cleaned)
    if position != len(content):
        raise UnitMappingError(f"tokenizer covered {position} of {len(content)} content characters")
    merged: list[AlignUnit] = []
    for unit in raw:
        previous = merged[-1] if merged else None
        if (previous is not None and unit.kind == previous.kind == "number"
                and text[previous.char_end:unit.char_start].strip() == ""):
            merged[-1] = AlignUnit(previous.text + unit.text, previous.char_start, unit.char_end, "number",
                                   previous.word_index)
        else:
            merged.append(unit)
    return [AlignUnit(u.text, u.char_start, u.char_end, u.kind, i) for i, u in enumerate(merged)]


def char_units(text: str, words: list[AlignUnit]) -> list[AlignUnit]:
    """One unit per original character inside each word (numbers/latin stay whole)."""
    content = content_char_map(text)
    out: list[AlignUnit] = []
    for word in words:
        if word.kind in {"number", "latin"} or word.char_end - word.char_start <= 1:
            out.append(AlignUnit(word.text, word.char_start, word.char_end, word.kind, word.word_index))
            continue
        clusters: dict[tuple[int, int], str] = {}
        for char, start, end in content:
            if word.char_start <= start and end <= word.char_end:
                clusters[(start, end)] = clusters.get((start, end), "") + char
        for (start, end), chars in clusters.items():
            out.append(AlignUnit(chars, start, end, "char", word.word_index))
    return out


def slot_text(units) -> str:
    """The aligner's input text for ``units`` (same format as the official processor)."""
    words = [u.text for u in units]
    return "<|audio_start|><|audio_pad|><|audio_end|>" + "<timestamp><timestamp>".join(words) + "<timestamp><timestamp>"


def monotonic_repair_kinds(raw) -> list[str]:
    """Which slots the official ``fix_timestamp`` keeps and how it repairs the rest.

    Mirrors its selection exactly: the longest non-decreasing subsequence is
    kept ("model"); runs of at most two other slots take the nearest kept
    neighbour ("nearest"); longer runs are linearly interpolated
    ("interpolated"); a run without any kept neighbour is "unanchored".
    """
    data = [float(x) for x in raw]
    n = len(data)
    if n == 0:
        return []
    dp, parent = [1] * n, [-1] * n
    for i in range(1, n):
        for j in range(i):
            if data[j] <= data[i] and dp[j] + 1 > dp[i]:
                dp[i], parent[i] = dp[j] + 1, j
    index = dp.index(max(dp))
    normal = [False] * n
    while index != -1:
        normal[index] = True
        index = parent[index]
    kinds = ["model" if ok else "" for ok in normal]
    i = 0
    while i < n:
        if normal[i]:
            i += 1
            continue
        j = i
        while j < n and not normal[j]:
            j += 1
        has_left, has_right = any(normal[:i]), any(normal[j:])
        kind = ("unanchored" if not (has_left or has_right)
                else "nearest" if j - i <= 2 or not (has_left and has_right) else "interpolated")
        for k in range(i, j):
            kinds[k] = kind
        i = j
    return kinds


@dataclass(frozen=True)
class TimedUnit:
    text: str
    char_start: int
    char_end: int
    kind: str
    word_index: int
    raw_start_ms: int        # model output, relative to the window
    raw_end_ms: int
    start_ms: int            # after the official repair, absolute (window offset added)
    end_ms: int
    start_basis: str         # model | nearest | interpolated | unanchored
    end_basis: str
    # Slot posterior within the window: peak class probability, mass within
    # one class of the peak, standard deviation of the time distribution.
    start_p: float = 0.0
    end_p: float = 0.0
    start_local: float = 0.0
    end_local: float = 0.0
    start_spread_ms: float = 0.0
    end_spread_ms: float = 0.0


def timed_units(units, raw_ms, fixed_ms, offset_ms: int, posterior=None, window_ms=None) -> list[TimedUnit]:
    """Units with raw/repaired times; ``window_ms`` marks slots clamped to the window edge.

    A slot on the first class or the last class of the window is where the
    model puts speech that begins before / ends after the audio it was given
    (or a neighbour's words inside the padding): never a measured boundary.
    """
    if len(raw_ms) != 2 * len(units) or len(fixed_ms) != 2 * len(units):
        raise ValueError(f"aligner returned {len(raw_ms)} slots for {len(units)} units")
    kinds = monotonic_repair_kinds(raw_ms)
    if window_ms:
        for slot, value in enumerate(raw_ms):
            if kinds[slot] == "model" and (float(value) <= 0.0 or float(value) >= float(window_ms) - ALIGNER_STEP_MS):
                kinds[slot] = "window_edge"
    posterior = posterior or {}
    p_max = list(posterior.get("p_max") or [0.0] * len(raw_ms))
    local = list(posterior.get("p_local") or [0.0] * len(raw_ms))
    spread = list(posterior.get("spread_ms") or [0.0] * len(raw_ms))
    out = []
    for index, unit in enumerate(units):
        a, b = 2 * index, 2 * index + 1
        out.append(TimedUnit(unit.text, unit.char_start, unit.char_end, unit.kind, unit.word_index,
                             int(round(float(raw_ms[a]))), int(round(float(raw_ms[b]))),
                             int(round(float(fixed_ms[a]))) + int(offset_ms),
                             int(round(float(fixed_ms[b]))) + int(offset_ms), kinds[a], kinds[b],
                             float(p_max[a]), float(p_max[b]), float(local[a]), float(local[b]),
                             float(spread[a]), float(spread[b])))
    return out


@dataclass(frozen=True)
class AlignedSegment:
    """A piece of the original text whose start and end the model measured."""
    char_start: int
    char_end: int
    start_ms: int
    end_ms: int
    granularity: str             # word | char_slot | merged
    start_basis: str
    end_basis: str
    word_indices: tuple = field(default_factory=tuple)


def _measured(basis: str) -> bool:
    return basis == "model"


_SMALL_KANA = frozenset("ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ")
# Plausibility only (never used to place a time): faster than this is not speech.
MAX_MORAE_PER_SECOND = 16.0
# A character-slot cut inside a word needs this posterior mass on both slots.
MIN_CHAR_CUT_LOCAL_MASS = 0.6


def estimated_morae(text: str) -> float:
    """Rough upper estimate of spoken morae, for a speech-rate sanity check."""
    count = 0.0
    for char in text:
        code = ord(char)
        if 0x3040 <= code <= 0x30FF or 0xFF66 <= code <= 0xFF9F:
            count += 0.0 if char in _SMALL_KANA else 1.0
        elif char.isdigit():
            count += 1.5
        elif char.isascii() and char.isalpha():
            count += 0.5
        elif unicodedata.category(char).startswith("L"):
            count += 2.0          # kanji: readings are usually one or two morae
    return count


def _implausibly_fast(text: str, start_ms: int, end_ms: int) -> bool:
    morae = estimated_morae(text)
    return morae >= 1 and (end_ms <= start_ms or morae / ((end_ms - start_ms) / 1000.0) > MAX_MORAE_PER_SECOND * 1.75)


def reliable_segments(words: list[TimedUnit], chars: list[TimedUnit] | None = None,
                      *, envelope_tolerance_ms: int = 2 * ALIGNER_STEP_MS) -> tuple[list[AlignedSegment], dict]:
    """Segments whose every exposed boundary is a direct, plausible model prediction.

    Word units are the base. A word boundary is not offered (its two
    neighbours are merged) when a slot was repaired by the monotonic fix, or
    when a neighbour has no duration or an impossible speaking rate. When the
    whole text is squeezed into an impossible duration no inner boundary is
    offered at all. Inside a word a character boundary from the
    character-slot pass is used only when both slots are direct predictions
    with posterior mass >= ``MIN_CHAR_CUT_LOCAL_MASS``, it lies strictly
    inside the word-pass span, the character pass agrees with the word pass
    on the word's outer edges within ``envelope_tolerance_ms``, and both
    characters have a positive duration.
    """
    stats = {"words": len(words), "word_boundaries": max(0, len(words) - 1), "word_boundaries_repaired": 0,
             "word_boundaries_degenerate": 0, "compressed": False,
             "char_boundaries_considered": 0, "char_boundaries_measured": 0, "char_boundaries_rejected": {},
             "edge_slots_repaired": 0}
    if not words:
        return [], stats
    whole = "".join(w.text for w in words)
    if len(words) > 1 and _implausibly_fast(whole, words[0].start_ms, max(w.end_ms for w in words)):
        stats["compressed"] = True
        first, last = words[0], words[-1]
        return [AlignedSegment(first.char_start, last.char_end, first.start_ms, max(w.end_ms for w in words),
                               "merged", first.start_basis, last.end_basis,
                               tuple(w.word_index for w in words))], stats

    def reject(reason):
        stats["char_boundaries_rejected"][reason] = stats["char_boundaries_rejected"].get(reason, 0) + 1

    by_word: dict[int, list[TimedUnit]] = {}
    for unit in chars or ():
        by_word.setdefault(unit.word_index, []).append(unit)
    pieces: list[AlignedSegment] = []
    for word in words:
        cuts = []  # (char index, time)
        inside = by_word.get(word.word_index, [])
        if len(inside) > 1:
            stats["char_boundaries_considered"] += len(inside) - 1
            agree = (abs(inside[0].start_ms - word.start_ms) <= envelope_tolerance_ms
                     and abs(inside[-1].end_ms - word.end_ms) <= envelope_tolerance_ms)
            for left, right in zip(inside, inside[1:]):
                if not agree:
                    reject("char_pass_disagrees_with_word_span")
                elif not (_measured(left.end_basis) and _measured(right.start_basis)):
                    reject("repaired_slot")
                elif min(left.end_local, right.start_local) < MIN_CHAR_CUT_LOCAL_MASS:
                    reject("low_posterior")
                elif not (left.end_ms - left.start_ms > 0 and right.end_ms - right.start_ms > 0):
                    reject("zero_duration_side")
                else:
                    cut = right.start_ms
                    if not (word.start_ms < cut < word.end_ms) or (cuts and cut <= cuts[-1][1]):
                        reject("outside_word_or_not_increasing")
                    else:
                        cuts.append((right.char_start, cut))
                        stats["char_boundaries_measured"] += 1
        bounds = [(word.char_start, word.start_ms, word.start_basis)]
        bounds += [(index, time, "model") for index, time in cuts]
        bounds.append((word.char_end, word.end_ms, word.end_basis))
        for (char_a, time_a, basis_a), (char_b, time_b, basis_b) in zip(bounds, bounds[1:]):
            pieces.append(AlignedSegment(char_a, char_b, time_a, time_b,
                                         "word" if len(bounds) == 2 else "char_slot",
                                         basis_a, basis_b, (word.word_index,)))
    # A boundary that is not a direct prediction on both sides, or that borders
    # a piece with no plausible duration, is not offered.
    def degenerate(piece):
        return piece.end_ms <= piece.start_ms or _implausibly_fast(
            "".join(w.text for w in words if w.word_index in piece.word_indices)
            if piece.granularity == "word" else "x", piece.start_ms, piece.end_ms)

    merged: list[AlignedSegment] = []
    for piece in pieces:
        repaired = merged and not (_measured(merged[-1].end_basis) and _measured(piece.start_basis))
        weak = merged and (degenerate(merged[-1]) or degenerate(piece))
        if repaired or weak:
            last = merged[-1]
            if last.word_indices != piece.word_indices:
                stats["word_boundaries_repaired" if repaired else "word_boundaries_degenerate"] += 1
            merged[-1] = AlignedSegment(last.char_start, piece.char_end, last.start_ms, max(last.end_ms, piece.end_ms),
                                        "merged", last.start_basis, piece.end_basis,
                                        tuple(sorted(set(last.word_indices) | set(piece.word_indices))))
        else:
            merged.append(piece)
    stats["edge_slots_repaired"] = int(not _measured(merged[0].start_basis)) + int(not _measured(merged[-1].end_basis))
    return merged, stats


def cover_display_span(text: str, segments: list[AlignedSegment]) -> list[AlignedSegment]:
    """Extend segments over displayed symbols they bracket (～, ♪) so the
    pieces tile every non-space, non-punctuation character of ``text``."""
    if not segments:
        return []
    out = [AlignedSegment(**asdict(s)) for s in segments]

    def visible(char):
        return not char.isspace() and not unicodedata.category(char).startswith(("P", "Z"))

    result = []
    for index, seg in enumerate(out):
        start, end = seg.char_start, seg.char_end
        if index == 0:
            while start > 0 and visible(text[start - 1]):
                start -= 1
        limit = out[index + 1].char_start if index + 1 < len(out) else len(text)
        while end < limit and visible(text[end]):
            end += 1
        result.append(AlignedSegment(start, end, seg.start_ms, seg.end_ms, seg.granularity,
                                     seg.start_basis, seg.end_basis, seg.word_indices))
    return result


def unit_rows(units) -> list[dict]:
    return [asdict(u) for u in units]


def segment_alignment_key(speaker, start_s, end_s) -> str:
    """Identity of one primary speaker segment for its alignment job."""
    return f"{str(speaker or 'S00')}@{int(round(float(start_s) * 1000))}-{int(round(float(end_s) * 1000))}"
