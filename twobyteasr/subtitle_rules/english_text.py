"""English subtitle text rules (2026-10-14).

The Chinese/Japanese rules count characters, strip spaces and treat every
letter as a unit. English is written in words: a space separates them, an
apostrophe belongs inside a word (don't, it's, players'), and a line may only
break between words. These helpers are the one place that knows that; the
English line breaker (english_segmentation.py) and the English branches of
cleanup, merging and quality checks use them.

Lengths are characters including spaces, the way English subtitle guidelines
count them (a comfortable line is up to about 42). Since 2026-10-21 one
subtitle holds up to two such lines (players wrap them), so a whole sentence of
up to 84 characters and 7 seconds stays one subtitle instead of being chopped
into one-line scraps.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SPACE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?…%)\]}”’])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[{“‘])\s+")
_CURLY_APOSTROPHE = re.compile(r"(?<=[A-Za-z])[’‘](?=[A-Za-z])|(?<=s)’(?=\s|$)")
_LONE_I = re.compile(r"(?<![A-Za-z'’])i(?=('(m|d|ll|ve|s)\b)|\b(?!['’.]))")
_LETTERS = re.compile(r"[A-Za-z]")
_WORD_CORE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*")


from .segmentation_profiles import profile_for as _profile_for
_PROFILE=_profile_for('en')

@dataclass(frozen=True)
class EnglishLineRules:
    """Limits for one English subtitle (characters include spaces).

    ``max_chars``/``preferred_chars`` are one line; ``cue_*`` are one subtitle
    of up to ``max_lines`` lines, which is what the line breaker fills.
    """
    preferred_chars: int = int(_PROFILE.line_preferred)
    max_chars: int = int(_PROFILE.line_max)
    min_chars: int = int(_PROFILE.minimum_units)
    max_lines: int = _PROFILE.lines
    cue_preferred_chars: int = _PROFILE.preferred
    cue_max_chars: int = _PROFILE.hard_max
    max_seconds: float = _PROFILE.max_seconds
    min_seconds: float = _PROFILE.min_seconds
    comfortable_cps: float = _PROFILE.comfortable_cps
    warning_cps: float = _PROFILE.warning_cps
    critical_cps: float = _PROFILE.critical_cps


RULES = EnglishLineRules()


def normalize_spaces(text: str) -> str:
    """One space between words, none before closing punctuation or after an opening one."""
    text = _SPACE.sub(" ", str(text or "")).strip()
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _SPACE_AFTER_OPEN.sub(r"\1", text)


def join(parts) -> str:
    """Join pieces of English text with exactly one space between words."""
    return normalize_spaces(" ".join(str(part or "").strip() for part in parts if str(part or "").strip()))


def words(text: str) -> list[str]:
    """Whitespace-separated words, punctuation attached (\"well,\" \"don't\" \"U.S.\")."""
    return normalize_spaces(text).split(" ") if normalize_spaces(text) else []


def word_core(word: str) -> str:
    """The comparable part of a word: letters/digits/inner apostrophes, lower case."""
    found = _WORD_CORE.search(str(word or "").replace("’", "'"))
    return found.group(0).lower() if found else ""


def display_length(text: str) -> int:
    from .segmentation_profiles import measure
    return int(measure(text,'en'))


def letters(text: str) -> int:
    return len(_LETTERS.findall(str(text or "")))


def clean(text: str) -> str:
    """Output cleanup for English: spacing, straight apostrophes, the pronoun I.

    Never removes apostrophes, hyphens or casing (the Chinese cleanup drops ’ and
    would turn don’t into dont).
    """
    text = normalize_spaces(text)
    text = _CURLY_APOSTROPHE.sub("'", text)
    return _LONE_I.sub("I", text)


def is_latin_text(text: str, *, threshold: float = 0.6) -> bool:
    """True when letters in the text are mostly Latin (an English line)."""
    value = str(text or "")
    latin = letters(value)
    other = sum(1 for char in value if char.isalpha() and not ("A" <= char <= "z"))
    return latin > 0 and latin / (latin + other) >= threshold


def reading_speed(text: str, seconds: float) -> float:
    """Characters per second (spaces included), as English guidelines measure it."""
    return display_length(text) / max(0.001, float(seconds or 0.0))
