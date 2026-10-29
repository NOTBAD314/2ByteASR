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


@dataclass(frozen=True)
class KoreanLineRules:
    """Limits for one Korean subtitle (lengths in Netflix units, see display_length).

    ``max_chars``/``preferred_chars`` are one line; since 2026-10-21 a subtitle
    holds up to ``max_lines`` lines (``cue_*``), so a whole sentence stays one.
    """
    preferred_chars: float = 12.0
    max_chars: float = 16.0
    min_chars: float = 4.0
    max_lines: int = 2
    cue_preferred_chars: float = 24.0
    cue_max_chars: float = 32.0
    max_seconds: float = 7.0
    min_seconds: float = 0.8
    comfortable_cps: float = 12.0     # adult programmes
    warning_cps: float = 14.0
    critical_cps: float = 18.0


RULES = KoreanLineRules()


def char_weight(char: str) -> float:
    """1 for Hangul (incl. ㅋ jamo) or an ideograph, 0.5 for a space, Latin letter, digit or mark."""
    if char.isascii() or unicodedata.category(char).startswith(("P", "S", "Z")):
        return 0.5
    return 1.0 if unicodedata.east_asian_width(char) in ("F", "W") else 0.5


def display_length(text: str) -> float:
    return sum(char_weight(char) for char in normalize_spaces(text))


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
