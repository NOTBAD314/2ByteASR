"""Split a caption at a position in its text (2026-10-22, MFA plan step 4).

The user asked: when a text position is chosen, find the reliable acoustic
cut for it; a position that maps to the sound on its own may be cut there,
one that does not stays whole or asks for a new alignment. The grades come
from ``recognition.boundary_grades`` (a second aligner or a pause confirmed
the boundary); the cut time comes from the caption's current word timing in
Studio (project clock), so no evidence clock is converted here.

``plan_text_split`` is UI-independent: Studio commits ``plan.split_ms`` for
an ``independent`` position and otherwise offers ``plan.choices``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# A gap of at least this much between two measured words is a pause: cut in its middle.
PAUSE_MIN_MS = 20


@dataclass(frozen=True)
class SplitChoice:
    kind: str           # cut | realign | estimate
    position: int = 0
    split_ms: int = 0
    left_text: str = ""
    right_text: str = ""


@dataclass(frozen=True)
class TextSplitPlan:
    cue_id: str
    position: int       # the cut goes before this character (a content character)
    grade: str          # independent | whole | unreliable | blocked
    reason: str
    split_ms: int | None = None
    left_text: str = ""
    right_text: str = ""
    choices: tuple = field(default_factory=tuple)


def _content_starts(text: str) -> list[int]:
    from ..forced_alignment import content_char_map
    return [start for _char, start, _end in content_char_map(text)]


def _cut_position(text: str, position: int):
    """The content character a cut at ``position`` goes before, or None at the text's edges."""
    starts = _content_starts(text)
    after = [start for start in starts if start >= position]
    if not after or after[0] == starts[0]:
        return None
    return after[0]


def graded_positions(project, cue) -> tuple[dict, str]:
    """``({position: grade row}, source)`` for ``cue``'s current text.

    Sources, in order: a Studio re-alignment's receipt (``realign``), the
    caption's own alignment row (``evidence``; a caption split from it reads
    its own slice of the row, ``evidence_slice``).
    """
    from ..recognition.boundary_grades import caption_boundaries
    from .studio_caption_timeline import KEY
    receipt = ((getattr(project, "studio_state", None) or {}).get(KEY) or {}).get("instances", {}).get(cue.id) or {}
    if receipt.get("boundaries") and receipt.get("text") == cue.text:
        return {int(row["pos"]): dict(row) for row in receipt["boundaries"]}, "realign"
    rows, reason = caption_boundaries(project, cue, refs=[*cue.evidence_refs, *(receipt.get("evidence_refs") or ())])
    return {int(row["pos"]): row for row in rows}, reason


def _cut_time(words, position: int):
    from ..recognition.cue_word_alignment import boundary_words
    pair = boundary_words(words, position)
    if pair is None:
        return None
    left, right = pair
    if right.start_ms - left.end_ms >= PAUSE_MIN_MS:
        return (left.end_ms + right.start_ms) // 2
    return int(right.start_ms)


def _estimate_time(cue, words, position: int) -> int:
    time = _cut_time(words, position) if words else None
    if time is not None:
        return time
    starts = _content_starts(cue.text)
    share = starts.index(position) / max(1, len(starts)) if position in starts else 0.5
    return round(cue.start_ms + (cue.end_ms - cue.start_ms) * share)


def _inside(cue, time, min_ms) -> bool:
    return time is not None and cue.start_ms + min_ms <= time <= cue.end_ms - min_ms


def plan_text_split(project, cue, position: int, *, min_duration_ms: int | None = None) -> TextSplitPlan:
    """What a cut of ``cue`` at text ``position`` does (see the module docstring)."""
    from ..recognition.cue_word_alignment import cue_words
    from .studio_timing import SPLIT_MIN_CUE_DURATION_MS, split_texts_at
    min_ms = SPLIT_MIN_CUE_DURATION_MS if min_duration_ms is None else int(min_duration_ms)
    text = str(cue.text)
    at = _cut_position(text, int(position))
    if at is None:
        return TextSplitPlan(cue.id, int(position), "blocked", "text_edge")
    left_text, right_text = split_texts_at(text, at)
    words, word_reason = cue_words(project, cue) if project is not None else ((), "missing_project_evidence")
    grades, source = graded_positions(project, cue) if project is not None else ({}, "missing_project_evidence")

    def cut(q):
        time = _cut_time(words, q)
        if not _inside(cue, time, min_ms):
            return None
        left, right = split_texts_at(text, q)
        return SplitChoice("cut", q, int(time), left, right)

    def nearest():
        """The closest independent positions left and right of ``at``."""
        found = []
        inner = sorted(q for q, row in grades.items() if 0 < q < len(text) and row.get("grade") == "independent")
        for side in ([q for q in inner if q < at][-1:], [q for q in inner if q > at][:1]):
            choice = cut(side[0]) if side else None
            if choice is not None:
                found.append(choice)
        return found

    row = grades.get(at)
    if row is None and grades:
        # Graded text without a row here: the position sits inside one aligned unit.
        row = {"grade": "whole", "reason": "inside_unit"}
    if row is None:
        # Never graded (older project, FireRed timeline, edited text): words decide what is possible.
        from ..recognition.cue_word_alignment import boundary_words
        if words and boundary_words(words, at) is None:
            row = {"grade": "whole", "reason": "inside_word"}
        else:
            row = {"grade": "unreliable", "reason": f"not_graded:{source if source != 'not_graded' else word_reason}"}
    grade, reason = row["grade"], str(row.get("reason") or "")
    if grade == "independent":
        choice = cut(at)
        if choice is not None:
            return TextSplitPlan(cue.id, at, grade, reason, choice.split_ms, left_text, right_text, (choice,))
        grade, reason = "unreliable", "words_mismatch_or_too_short"
    choices = list(nearest())
    if grade == "unreliable":
        estimate = _estimate_time(cue, words, at)
        choices.insert(0, SplitChoice("realign"))
        if _inside(cue, estimate, min_ms):
            choices.append(SplitChoice("estimate", at, int(estimate), left_text, right_text))
    elif not choices:
        choices.append(SplitChoice("realign"))
    return TextSplitPlan(cue.id, at, grade, reason, None, left_text, right_text, tuple(choices))
