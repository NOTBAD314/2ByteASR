"""Memoized jieba part-of-speech tags for the Chinese grouping rules.

2026-11-27 (fast-anything scan of scripts/replay_grouping_boundaries.py): the
grouping gates tagged the same short texts again and again, 10,772
jieba.posseg.cut calls for 190 source segments, the largest single cost of
regrouping. Tags depend only on the text and on jieba's dictionary, which the
app never changes after loading it (no add_word, load_userdict, suggest_freq
or del_word), so one cache per process returns the very same pairs.

The cache key also holds the current jieba.posseg.cut, so a test that patches
it gets its own entries and never leaks them into later calls. Code that ever
changes jieba's dictionary at runtime must call clear_pos_tags() afterwards.
"""
from __future__ import annotations

from functools import lru_cache

_posseg = None


@lru_cache(maxsize=8192)
def _tags(text, hmm, cut):
    return tuple(cut(text, HMM=hmm))


def pos_tags(text, HMM=True):
    """jieba.posseg.cut(text, HMM=HMM) as a tuple of its (word, flag) pairs.

    Callers read the pairs and must not change them: they are shared.
    """
    global _posseg
    if _posseg is None:
        # Lazy: importing this module must not load jieba at startup.
        import jieba.posseg as posseg
        _posseg = posseg
    if type(text) is not str:
        return tuple(_posseg.cut(text, HMM=HMM))
    return _tags(text, bool(HMM), _posseg.cut)


def clear_pos_tags():
    _tags.cache_clear()


__all__ = ["clear_pos_tags", "pos_tags"]
