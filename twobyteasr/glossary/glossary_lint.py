"""Shared checks for glossary rows that leave this computer (2026-10-17).

The online glossary hub (glossary_hub.py) uses these rules in three places:
the "submit" dialog, the hub repository's CI (scripts/glossary_hub.py check)
and the install preview.  They come from the 2026-10-17 cleanup of the user's
own libraries, where the following rows did real damage:

* a confirmed alias (from != to) replaces that text everywhere, as a substring
  without word boundaries: 落地→跺地 turns 落地窗 into 跺地窗;
* one alias pointing at two targets disables both (TermResolver conflict);
* an alias that is another row's canonical is a chain the resolver rejects;
* a non-ASCII term longer than 15 characters makes Bailian Filetrans refuse the
  whole request;
* "broader word → longer name" rewrites (作战记录→高级作战记录) and
  "full phrase → part of it" rewrites (强攻特性→强攻) change what was said.

``block`` findings stop a submission or a publication.  ``warn`` findings are
allowed, but the install preview leaves such rules unticked by default.
Messages are Simplified Chinese UI source strings (translated through tr()).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

BLOCK, WARN = "block", "warn"
FILETRANS_TERM_LIMIT = 15           # Bailian Filetrans rejects longer non-ASCII terms
MAX_TERM_LENGTH = 40
COMMON_WORD_FREQ = 5                # jieba dictionary frequency; 夜宵=44, 封印=18, 奥特曼=6
SHORT_ASCII_ALIAS = 3               # op / ak / kj / s3 hit unrelated text

_CJK = re.compile(r"[㐀-鿿]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

MESSAGES = {
    "empty": "词或改字结果是空的",
    "control": "含有控制字符",
    "too_long": "超过 40 个字",
    "filetrans": "超过 15 个字，百炼 Filetrans 会整个失败",
    "conflict": "同一个词被改成两个不同结果",
    "chain": "改字来源是另一条的正式写法",
    "short_cjk": "两字以内的改字规则，会改到词中间",
    "short_ascii": "很短的英文改字规则，容易改到无关文字",
    "common_word": "改字来源是普通词，所有出现都会被改",
    "expands": "会把原词扩写成更长的名字",
    "truncates": "会删掉原话的一部分",
}


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    source: str
    target: str

    @property
    def message(self) -> str:
        return MESSAGES[self.code]

    @property
    def key(self) -> tuple[str, str]:
        return self.source, self.target


def _text(value) -> str:
    return " ".join(str(value or "").split())


def is_cjk(text: str) -> bool:
    return bool(_CJK.search(text))


def is_common_word(text: str) -> bool:
    """A word of the jieba dictionary that people use in ordinary speech."""
    text = _text(text)
    if len(text) < 2 or not is_cjk(text):
        return False
    try:
        from ..subtitle_rules.stutter_cleanup import word_frequency
    except ImportError:  # a standalone copy (the hub repository's CI)
        try:
            import logging
            import jieba
            jieba.setLogLevel(logging.ERROR)
            jieba.dt.check_initialized()
            return int(jieba.dt.FREQ.get(text) or 0) >= COMMON_WORD_FREQ
        except Exception:  # noqa: BLE001 - jieba is optional there
            return False
    try:
        return word_frequency(text) >= COMMON_WORD_FREQ
    except Exception:  # noqa: BLE001 - the dictionary failed to load
        return False


def row_findings(row: Mapping) -> list[Finding]:
    """Findings that depend on one row only."""
    source, target = _text(row.get("from")), _text(row.get("to"))
    found = []

    def add(level, code):
        found.append(Finding(level, code, source, target))

    if not source or not target:
        add(BLOCK, "empty")
        return found
    if _CONTROL.search(source + target):
        add(BLOCK, "control")
    if max(len(source), len(target)) > MAX_TERM_LENGTH:
        add(BLOCK, "too_long")
    if any(not term.isascii() and len(term) > FILETRANS_TERM_LIMIT for term in (source, target)):
        add(BLOCK, "filetrans")
    if source == target:
        return found
    if is_cjk(source) and len(source) <= 2:
        add(WARN, "short_cjk")
    elif source.isascii() and len(source) <= SHORT_ASCII_ALIAS:
        add(WARN, "short_ascii")
    if is_common_word(source):
        add(WARN, "common_word")
    if source in target:
        add(WARN, "expands")
    elif target in source:
        add(WARN, "truncates")
    return found


def lint_rows(rows: Iterable[Mapping], *, existing: Iterable[Mapping] = ()) -> list[Finding]:
    """Every finding for ``rows``; ``existing`` rows (the user's library) count
    for conflicts and chains but are not reported themselves."""
    rows = [row for row in rows if isinstance(row, Mapping)]
    everything = rows + [row for row in existing if isinstance(row, Mapping)]
    found = [finding for row in rows for finding in row_findings(row)]
    targets = defaultdict(set)
    for row in everything:
        source, target = _text(row.get("from")), _text(row.get("to"))
        if source and target:
            targets[source].add(target)
    canonicals = {_text(row.get("to")) for row in everything}
    for row in rows:
        source, target = _text(row.get("from")), _text(row.get("to"))
        if not source or not target:
            continue
        if len(targets[source]) > 1:
            found.append(Finding(BLOCK, "conflict", source, target))
        elif source != target and source in canonicals:
            found.append(Finding(BLOCK, "chain", source, target))
    return found


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.level == BLOCK]


def findings_by_row(findings: Iterable[Finding]) -> dict[tuple[str, str], list[Finding]]:
    grouped: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for finding in findings:
        grouped[finding.key].append(finding)
    return dict(grouped)
