"""Korean subtitle text rules (2026-10-19).

Korean is written in words (어절) separated by spaces, like English: a line may
only break at a space and the spaces must survive every cleanup. Lengths are
counted the way Korean subtitle guidelines count them (Netflix Korean Timed
Text Style Guide): a Hangul syllable or Han character is one character; a
space, a Latin letter, a digit or a punctuation mark is half. One line holds
up to 16; a comfortable reading speed is about 12 characters per second.

These helpers are the one place that knows that; the Korean line breaker
(korean_segmentation.py) and the Korean branches of cleanup, merging and the
quality checks use them.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .english_text import join, normalize_spaces, words  # noqa: F401  (same spacing rules)

_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_WORD_CORE = re.compile(r"[0-9A-Za-z가-힣ᄀ-ᇿ㄰-㆏㐀-鿿]+")


from .segmentation_profiles import profile_for as _profile_for
_PROFILE=_profile_for('ko')

@dataclass(frozen=True)
class KoreanLineRules:
    """Limits for one Korean subtitle (lengths in Netflix units, see display_length).

    ``max_chars``/``preferred_chars`` are one line; since 2026-10-21 a subtitle
    holds up to ``max_lines`` lines (``cue_*``), so a whole sentence stays one.
    """
    preferred_chars: float = _PROFILE.line_preferred
    max_chars: float = _PROFILE.line_max
    min_chars: float = _PROFILE.minimum_units
    max_lines: int = _PROFILE.lines
    cue_preferred_chars: float = _PROFILE.preferred
    cue_max_chars: float = _PROFILE.hard_max
    max_seconds: float = _PROFILE.max_seconds
    min_seconds: float = _PROFILE.min_seconds
    comfortable_cps: float = _PROFILE.comfortable_cps
    warning_cps: float = _PROFILE.warning_cps
    critical_cps: float = _PROFILE.critical_cps


RULES = KoreanLineRules()


def char_weight(char: str) -> float:
    """1 for Hangul (incl. ㅋ jamo) or an ideograph, 0.5 for a space, Latin letter, digit or mark."""
    if char.isascii() or unicodedata.category(char).startswith(("P", "S", "Z")):
        return 0.5
    return 1.0 if unicodedata.east_asian_width(char) in ("F", "W") else 0.5


def display_length(text: str) -> float:
    from .segmentation_profiles import measure
    return measure(text,'ko')


def hangul(text: str) -> int:
    return len(_HANGUL.findall(str(text or "")))


def word_core(word: str) -> str:
    """The comparable part of a word: Hangul, ideographs, letters and digits, lower case."""
    return "".join(_WORD_CORE.findall(unicodedata.normalize("NFC", str(word or "")))).lower()


def clean(text: str) -> str:
    """Output cleanup for Korean: one space between words, none before closing marks.

    Never removes spaces between words (the Chinese cleanup drops them and would
    run 오늘 방송 together) and never changes letters or punctuation.
    """
    return normalize_spaces(unicodedata.normalize("NFC", str(text or "")))
