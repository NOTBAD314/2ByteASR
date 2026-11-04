"""Chinese third-person pronouns 他 / 她 / 它 (2026-10-15).

The three are one syllable (tā), so a recognizer can only guess the gender
from its language model; streamers fix 他 → 她 by hand all the time. Context
decides, never the audio. These helpers are shared by the AI correction safety
gate (a pure pronoun swap is a context decision, not an unsupported homophone
edit), Studio review (click or press P to flip) and manual-edit learning
(a pronoun flip is never a glossary term).

He-as-a-word-part (其他, 吉他, 他人 …) is not a pronoun and is never offered.
"""
from __future__ import annotations

import re

THIRD_PERSON = "他她它"
# One click: the usual fix first (他 ↔ 她); 它 goes to 他.
_TOGGLE = {"他": "她", "她": "他", "它": "他"}
# Words where the character is not a personal pronoun.
NON_PRONOUN_WORDS = (
    "其他", "其它", "吉他", "他人", "他乡", "他国", "他方", "他日", "他处", "他物", "他者", "他律",
    "他杀", "他用", "他山", "利他", "排他", "无他", "他妈", "他娘", "他喵",
)
_NON_PRONOUN = re.compile("|".join(map(re.escape, NON_PRONOUN_WORDS)))


def pronoun_positions(text: str) -> list[int]:
    """Indexes of 他 / 她 / 它 used as personal pronouns in ``text``."""
    text = str(text or "")
    excluded = set()
    for match in _NON_PRONOUN.finditer(text):
        excluded.update(index for index in range(match.start(), match.end()) if text[index] in THIRD_PERSON)
    return [index for index, char in enumerate(text) if char in THIRD_PERSON and index not in excluded]


def toggle_pronoun(char: str) -> str:
    return _TOGGLE.get(str(char), str(char))


def pronoun_options(char: str) -> tuple[str, ...]:
    """The click choice first, then the remaining one (他 → 她, 它)."""
    first = toggle_pronoun(char)
    return (first,) + tuple(value for value in THIRD_PERSON if value not in (char, first))


def flip_pronouns(text: str) -> str:
    """One caption's third person flipped as a whole (review key P).

    Captions usually refer to one person, so every pronoun of the leading
    gender changes together: 他 → 她 if the caption has 他, else 她 → 他,
    else 它 → 他. Text without a pronoun is returned unchanged.
    """
    text = str(text or "")
    positions = pronoun_positions(text)
    present = {text[index] for index in positions}
    source = next((char for char in "他她它" if char in present), "")
    if not source:
        return text
    target = toggle_pronoun(source)
    chars = list(text)
    for index in positions:
        if chars[index] == source:
            chars[index] = target
    return "".join(chars)


def is_pronoun_swap(source: str, target: str) -> bool:
    """``target`` differs from ``source`` only by 他 / 她 / 它 at the same places."""
    source, target = "".join(str(source or "").split()), "".join(str(target or "").split())
    if not source or len(source) != len(target) or source == target:
        return False
    return all(a == b or (a in THIRD_PERSON and b in THIRD_PERSON) for a, b in zip(source, target))


def pronoun_swap_in_context(text: str, start: int, end: int, target: str) -> bool:
    """Replacing ``text[start:end]`` with ``target`` only changes real pronouns."""
    text = str(text or "")
    source = text[start:end]
    if not is_pronoun_swap(source, target) or len(source) != len(target):
        return False
    positions = set(pronoun_positions(text))
    return all(start + offset in positions for offset, (a, b) in enumerate(zip(source, target)) if a != b)


__all__ = [
    "NON_PRONOUN_WORDS", "THIRD_PERSON", "flip_pronouns", "is_pronoun_swap", "pronoun_options",
    "pronoun_positions", "pronoun_swap_in_context", "toggle_pronoun",
]
