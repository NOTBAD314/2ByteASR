"""Dependency-light text distance helpers shared across pipeline stages."""

from __future__ import annotations

from functools import lru_cache
import re


def levenshtein(left, right):
    previous = list(range(len(right) + 1))
    for left_index, left_value in enumerate(left, 1):
        current = [left_index]
        for right_index, right_value in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_value != right_value),
                )
            )
        previous = current
    return previous[-1]


# 拼音转换是纯函数且全句音串在仲裁/共识/相似度多处反复重算（2026-09-03
# run eca757 实测：242 段的本地共识曾因此单核跑 8 分钟）。LRU 上限取足够
# 覆盖一次全音频的所有去重文本，避免无界增长。
@lru_cache(maxsize=131072)
def _phonetic_text_cached(text: str) -> str:
    # Lazy import keeps this low-level module out of subtitle_core's import cycle.
    from pypinyin import Style, lazy_pinyin
    # Keep the distance layer dependency-light: importing text_rules here
    # before subtitle_core boots creates a partially initialized correction
    # module. This is the same content alphabet as content_only.
    from twobyteasr.language_rules import CONTENT_CHAR_CLASS
    normalized = ''.join(re.findall(f'[{CONTENT_CHAR_CLASS}]+', str(text))).lower()
    return "".join(
        lazy_pinyin(
            normalized,
            style=Style.NORMAL,
            errors=lambda value: list(value),
        )
    ).lower()


def phonetic_text(text):
    return _phonetic_text_cached(text if isinstance(text, str) else str(text))


__all__ = ["levenshtein", "phonetic_text"]
