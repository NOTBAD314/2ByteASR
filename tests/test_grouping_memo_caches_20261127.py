"""Memo caches in the Chinese grouping rules (2026-11-27).

A fast-anything scan of scripts/replay_grouping_boundaries.py found the gates
re-tagging the same texts with jieba and rebuilding the same boundary terms
through content_exact (about 730,000 calls for 190 segments). Both now go
through caches; these tests pin that the cached answers equal the uncached
ones and that the caches cannot outlive what they depend on.
"""
import re
from pathlib import Path

import pytest
import subtitle_core  # noqa: F401  (loads text_rules in the order the app does)

from twobyteasr.subtitle_rules import text_rules, word_tags
from twobyteasr.subtitle_rules.language_rules import CONTENT_CHAR_CLASS

ROOT = Path(__file__).resolve().parents[1]
TEXTS = [
    "对面上卡瓦重给我们那个虫群过境的机会了",
    "两发暴风雪就能清掉这一波",
    "芙宁娜的元素战技可以挂水",
    "我们先去第三层看看",
    "ok那就这样",
    "",
]


def _uncached_content(text):
    return "".join(re.findall(f"[{CONTENT_CHAR_CLASS}]+", str(text)))


@pytest.mark.parametrize("hmm", [True, False])
def test_pos_tags_match_jieba(hmm):
    import jieba.posseg as posseg

    for text in TEXTS:
        expected = [(p.word, p.flag) for p in posseg.cut(text, HMM=hmm)]
        assert [(p.word, p.flag) for p in word_tags.pos_tags(text, HMM=hmm)] == expected
        # The second call is the cached one and must give the same pairs.
        assert [(p.word, p.flag) for p in word_tags.pos_tags(text, HMM=hmm)] == expected


def test_pos_tags_reuse_one_result_per_text():
    word_tags.clear_pos_tags()
    first = word_tags.pos_tags(TEXTS[0])
    assert word_tags.pos_tags(TEXTS[0]) is first
    word_tags.clear_pos_tags()
    assert word_tags.pos_tags(TEXTS[0]) is not first


def test_patched_jieba_gets_its_own_entries(monkeypatch):
    import jieba.posseg as posseg

    text = TEXTS[1]
    real = [(p.word, p.flag) for p in word_tags.pos_tags(text)]
    fake = [type("Pair", (), dict(word=text, flag="x"))()]
    with monkeypatch.context() as patch:
        patch.setattr(posseg, "cut", lambda *args, **kwargs: list(fake))
        assert [(p.word, p.flag) for p in word_tags.pos_tags(text)] == [(text, "x")]
    # Once the patch is gone the real tags come back, not the patched ones.
    assert [(p.word, p.flag) for p in word_tags.pos_tags(text)] == real


def test_app_never_changes_the_jieba_dictionary():
    """The tag cache is keyed by text only: a runtime dictionary change would
    make it stale. Whoever adds one must call word_tags.clear_pos_tags()."""
    mutators = re.compile(r"\b(?:add_word|load_userdict|suggest_freq|del_word|set_dictionary)\s*\(")
    offenders = []
    for path in sorted((ROOT / "twobyteasr").rglob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        if "jieba" in source and mutators.search(source) and "clear_pos_tags" not in source:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


@pytest.mark.parametrize("text", [
    *TEXTS,
    "Hello, World! 你好，世界。",
    "ーー々・ひらがなカタカナ",
    "😀表情👍符号",
    "长" * 300,  # longer than the cached length: computed every time
    "a, b" * 100,
])
def test_content_exact_matches_uncached(text):
    assert text_rules.content_exact(text) == _uncached_content(text)
    assert text_rules.content_exact(text) == _uncached_content(text)


def test_content_exact_keeps_non_string_behavior():
    class Marked(str):
        def __str__(self):
            return "改过的"

    assert text_rules.content_exact(None) == "None"
    assert text_rules.content_exact(12.5) == "125"
    assert text_rules.content_exact(Marked("原文")) == "改过的"
    assert text_rules.content_exact(["对", "的"]) == _uncached_content(["对", "的"])
