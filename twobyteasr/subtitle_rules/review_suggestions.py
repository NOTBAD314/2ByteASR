"""Click-to-fix marks on the current caption in Studio review (2026-10-15).

User request: like the AI glossary proofreading page, review mode should let
one click change a suggested wrong word, marked only on card 1 (the current
caption) so three recognizer results do not triple the noise.

A mark is one span of the current text with one or more replacements:

* ``model``    another recognizer wrote this part differently (local diff
               against each candidate; a span where several candidates differ
               is one mark with their options, most-supported first);
* ``glossary`` a confirmed glossary alias found in the text (alias → canonical);
* ``pronoun``  a third-person 他 / 她 / 它 (see ``pronouns``).

Pure functions: no Qt, no project mutation. Studio applies the chosen option
as an ordinary, undoable user edit.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import unicodedata
from typing import Iterable, Sequence

from .pronouns import pronoun_options, pronoun_positions

MODEL, GLOSSARY, PRONOUN = "model", "glossary", "pronoun"
# A candidate this different is a rewrite: adopt it whole (card 2–4), do not
# scatter its pieces over the current caption.
MIN_CANDIDATE_RATIO = 0.5
MAX_SPAN_CHARS = 16
MAX_MARKS = 8


@dataclass(frozen=True)
class SuggestionOption:
    text: str
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewSuggestion:
    start: int
    end: int
    original: str
    options: tuple[SuggestionOption, ...]
    kind: str

    def apply(self, text: str, option: int = 0) -> str:
        """``text`` with this span replaced; unchanged if the span no longer matches."""
        text = str(text)
        if text[self.start:self.end] != self.original or not 0 <= option < len(self.options):
            return text
        return text[:self.start] + self.options[option].text + text[self.end:]


def _has_content(value: str) -> bool:
    return any(unicodedata.category(char)[0] in "LN" for char in value)


def _content(value: str) -> str:
    return "".join(char.casefold() for char in value if unicodedata.category(char)[0] in "LN")


def _map(opcodes, position: int) -> int:
    """``position`` in the current text mapped onto the candidate.

    Only used at mark boundaries, which never fall strictly inside another
    candidate's changed block (the marks are unions of whole blocks)."""
    for tag, a, b, c, d in opcodes:
        if tag == "equal":
            if a <= position <= b:
                return c + position - a
        elif position == a:
            return c
        elif position == b:
            return d
    return opcodes[-1][4] if opcodes else 0


def model_suggestions(current: str, candidates: Iterable[tuple[str, Sequence[str]]]) -> list[ReviewSuggestion]:
    """Local differences between the current caption and each candidate."""
    current = str(current or "")
    rows = []
    for text, sources in candidates:
        text = str(text or "").strip()
        if not text or text == current:
            continue
        matcher = SequenceMatcher(None, current, text, autojunk=False)
        if matcher.ratio() < MIN_CANDIDATE_RATIO:
            continue
        opcodes = matcher.get_opcodes()
        blocks = [(a, b) for tag, a, b, c, d in opcodes if tag != "equal"
                  and (_has_content(current[a:b]) or _has_content(text[c:d]))
                  and _content(current[a:b]) != _content(text[c:d])]
        if blocks:
            rows.append((text, tuple(str(source) for source in sources), opcodes, blocks))
    spans = sorted(block for _text, _sources, _opcodes, blocks in rows for block in blocks)
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    result = []
    for start, end in merged:
        original = current[start:end]
        options: dict[str, list] = {}
        for order, (text, sources, opcodes, _blocks) in enumerate(rows):
            replacement = text[_map(opcodes, start):_map(opcodes, end)]
            if replacement == original or _content(replacement) == _content(original):
                continue
            entry = options.setdefault(replacement, [order, []])
            entry[1].extend(source for source in sources if source not in entry[1])
        if not options or len(original) > MAX_SPAN_CHARS or any(len(value) > MAX_SPAN_CHARS for value in options):
            continue
        ranked = sorted(options.items(), key=lambda item: (-len(item[1][1]), item[1][0]))
        result.append(ReviewSuggestion(start, end, original,
                                       tuple(SuggestionOption(value, tuple(meta[1])) for value, meta in ranked), MODEL))
    return result


def glossary_suggestions(current: str, resolver, *, scene=None) -> list[ReviewSuggestion]:
    """Confirmed glossary aliases in the current caption (alias → canonical)."""
    if resolver is None:
        return []
    try:
        resolution = resolver.resolve(str(current or ""), scene=scene)
    except Exception:  # a broken library never blocks review
        return []
    return [ReviewSuggestion(hit.start, hit.end, hit.source, (SuggestionOption(hit.canonical),), GLOSSARY)
            for hit in resolution.hits if hit.source != hit.canonical and hit.end > hit.start]


def pronoun_suggestions(current: str) -> list[ReviewSuggestion]:
    current = str(current or "")
    return [ReviewSuggestion(index, index + 1, current[index],
                             tuple(SuggestionOption(value) for value in pronoun_options(current[index])), PRONOUN)
            for index in pronoun_positions(current)]


def _overlaps(row: ReviewSuggestion, taken: list[ReviewSuggestion]) -> bool:
    return any(row.start < other.end and other.start < row.end
               or (row.start == row.end and other.start <= row.start <= other.end)
               or (other.start == other.end and row.start <= other.start <= row.end)
               for other in taken)


def review_suggestions(current: str, candidates: Iterable[tuple[str, Sequence[str]]] = (), *,
                       resolver=None, scene=None, pronouns: bool = True) -> list[ReviewSuggestion]:
    """All marks for card 1, in text order; recognizer differences win overlaps,
    then glossary aliases, then pronoun toggles."""
    taken: list[ReviewSuggestion] = []
    for group in (model_suggestions(current, candidates), glossary_suggestions(current, resolver, scene=scene),
                  pronoun_suggestions(current) if pronouns else []):
        for row in group:
            if not _overlaps(row, taken):
                taken.append(row)
    taken.sort(key=lambda row: (row.start, row.end))
    if len([row for row in taken if row.kind != PRONOUN]) > MAX_MARKS:
        # A caption with this many separate differences is a rewrite; keep the
        # first marks readable and leave the rest to the whole-candidate cards.
        kept, count = [], 0
        for row in taken:
            if row.kind != PRONOUN:
                count += 1
                if count > MAX_MARKS:
                    continue
            kept.append(row)
        taken = kept
    return taken


__all__ = [
    "GLOSSARY", "MODEL", "PRONOUN", "ReviewSuggestion", "SuggestionOption", "glossary_suggestions",
    "model_suggestions", "pronoun_suggestions", "review_suggestions",
]
