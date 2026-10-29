"""The Chinese subtitle cleanup: ordinary punctuation removed, meaningful marks kept.

Moved out of ``text_rules.clean_subtitle_text`` on 2026-10-25 so glossary code
can ask how a spelling looks after cleanup without importing ``subtitle_core``.
``clean`` keeps question and exclamation marks, number separators and ellipses.

``keep`` (2026-10-25): a compiled pattern of spellings to keep exactly as
written, e.g. confirmed glossary terms with symbols (漂泊者·男, Re:Zero) that
the cleanup would otherwise turn into 漂泊者男 / ReZero.
"""
from __future__ import annotations

import re

DROPPED = """《》〈〉【】[]（）(){}“”‘’\"`·・•、，。；：:;,—~～"""
_DROP_TABLE = str.maketrans("", "", DROPPED)
# Each kept span becomes one character from Supplementary Private Use Area-A
# while the rules run; no rule removes or joins on such a character.
_KEPT_BASE = 0xF0000
_KEPT_RANGE = re.compile("[\U000F0000-\U000FFFFD]")


def clean(text, keep: re.Pattern | None = None) -> str:
    text = str(text).replace("\r", " ").replace("\n", " ")
    kept: list[str] = []
    if keep is not None and not _KEPT_RANGE.search(text):
        def hold(match):
            kept.append(match.group(0))
            return chr(_KEPT_BASE + len(kept) - 1)

        text = keep.sub(hold, text)
    # Deleting a comma between spoken numbers concatenated independent events
    # before the Chinese parser (二十，二十 -> 二十二十 -> 40).
    text = re.sub(r'(?<=[零〇一二两三四五六七八九十百千万亿0-9])[，,、](?=[零〇一二两三四五六七八九十百千万亿0-9])', '\ue000', text)
    # A ratio separator belongs to the numerical expression. Removing it
    # before number formatting turns 二:三 into the ambiguous event 二三.
    text = re.sub(r'(?<=[零〇一二两三四五六七八九十百千万亿0-9])[:：](?=[零〇一二两三四五六七八九十百千万亿0-9])', '\ue001', text)
    text = text.translate(_DROP_TABLE)
    text = text.replace('\ue000', '，')
    text = text.replace('\ue001', ':')
    text = text.replace("……", "...").replace("…", "...")
    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"(?<![A-Za-z0-9.])\.(?!\.)", "", text)
    text = re.sub(r"(?<!\.)\.(?![A-Za-z0-9.])", "", text)
    text = re.sub(r"(?<![A-Za-z0-9])['-]|['-](?![A-Za-z0-9])", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if kept:
        text = _KEPT_RANGE.sub(lambda match: kept[ord(match.group(0)) - _KEPT_BASE], text)
    return text
