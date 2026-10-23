"""A caption's measured speech span, kept apart from its display time (2026-10-22, MFA plan step 5).

The user asked that acoustic time and display time be separate, so reading
comfort (lead-in, reading tails, frame grid, closed short gaps) never
pretends to be the sound. A caption's start/end stay its display time; its
acoustic span is read from the immutable alignment evidence: the first and
last measured word in Studio's current word timing (project clock), with the
grade of each edge (``boundary_grades``: ``independent`` when a second
aligner or a pause confirmed it). Nothing here is stored in the project.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AcousticSpan:
    start_ms: int
    end_ms: int
    start_grade: str    # independent | unreliable | unmeasured | ungraded
    end_grade: str

    @property
    def confirmed(self) -> bool:
        return self.start_grade == self.end_grade == "independent"


def _edge(row) -> str:
    if not row:
        return "ungraded"
    if str(row.get("reason") or "").startswith("unmeasured"):
        return "unmeasured"
    return str(row.get("grade") or "ungraded")


def acoustic_span(project, cue) -> AcousticSpan | None:
    """The measured span of ``cue``'s current text, or None without measured words."""
    from ..recognition.cue_word_alignment import MEASURED_ALIGNMENTS, cue_words
    from .text_split import graded_positions
    words, reason = cue_words(project, cue, allow_realign=False)
    if not words or reason not in MEASURED_ALIGNMENTS:
        return None
    grades, _source = graded_positions(project, cue)
    return AcousticSpan(int(words[0].start_ms), int(max(word.end_ms for word in words)),
                        _edge(grades.get(0)), _edge(grades.get(len(cue.text))))


def cache_key(project, cue) -> tuple:
    """What an acoustic span depends on: the caption, and its receipt after a re-alignment."""
    from .studio_caption_timeline import KEY
    receipt = ((getattr(project, "studio_state", None) or {}).get(KEY) or {}).get("instances", {}).get(cue.id) or {}
    words = receipt.get("words") or ()
    return (cue.id, cue.text, int(cue.start_ms), int(cue.end_ms), receipt.get("text"), len(words),
            words[0].get("start_ms") if words else None, len(receipt.get("boundaries") or ()))
