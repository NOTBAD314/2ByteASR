"""Remember manual Studio corrections in the project's glossary (2026-10-15).

User request: when a project uses a glossary, a caption the user fixed by
hand should be saved to that glossary automatically, so later recognition
remembers it. Until now every manual fix waited in "learned words" for an
explicit confirmation on the term library page.

A saved row becomes a confirmed alias that later recognition replaces
everywhere, so only fixes with a clear name span are written; everything else
keeps the old review flow (the learned list):

1. Glossary-backed: the fixed text covers a term of an applied glossary
   (芙宁娜) → the misheard form there (福宁娜) becomes its alias, in the
   library that owns the term.
2. New name: the span must be clean — on word boundaries, no particle /
   pronoun / preposition at either edge, at least three Chinese characters
   (two-character aliases hide inside ordinary words: 来特 in 来特别), or the
   user's own find-and-replace pair.

Never: a 他 / 她 / 它 flip; a wrong form that is ordinary language (老是 →
老师 would rewrite every later 老是; 所以他, 我们在); a fixed form containing
an ordinary non-noun word (的是安排).

Which glossary: the one owning the term; else the only applied library; with
several and no owner the pair stays in the learned list and the user is told.
A result remembers exactly which rows it added, so undoing the edit removes
them again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
import re

AUTO_ORIGIN = "Studio 手动修改（自动记入）"
SAVED, EXISTS, AMBIGUOUS, CONFLICT, FAILED = "saved", "exists", "ambiguous", "conflict", "failed"
MAX_TERM_LENGTH = 12
NAME_TAGS = {"nr", "nrt", "nrfg", "ns", "nt", "nz", "eng", "j", "x"}
_HAN = re.compile(r"[㐀-鿿]")


@dataclass
class AutoSaveResult:
    source: str
    target: str
    status: str
    library_id: str = ""
    library_name: str = ""
    added: list = field(default_factory=list)   # [(from, to)] rows this save created
    reason: str = ""


# text analysis -------------------------------------------------------------
@lru_cache(maxsize=256)
def _posseg(text: str) -> tuple:
    """(word, tag, start, end) with jieba's new-word detection (finds 芙宁娜)."""
    import jieba.posseg as posseg
    from ..subtitle_rules.stutter_cleanup import _lexicon
    _lexicon()
    rows, cursor = [], 0
    for pair in posseg.cut(text, HMM=True):
        word = pair.word
        start = text.find(word, cursor)
        if start < 0:
            continue
        rows.append((word, pair.flag, start, start + len(word)))
        cursor = start + len(word)
    return tuple(rows)


def _function_word(word: str, tag: str) -> bool:
    from ..subtitle_rules.stutter_cleanup import CLOSED, COMMON_VERBS_FUNCTION, FUNCTION_TAGS
    return (tag in FUNCTION_TAGS or word in COMMON_VERBS_FUNCTION
            or (len(word) == 1 and word in CLOSED))


def _ordinary_language(text: str, start: int, end: int) -> bool:
    """``text[start:end]`` is ordinary words: one common word, only common
    two-plus-character words, or only function words / pronouns."""
    from ..subtitle_rules.stutter_cleanup import (ORDINARY_WORD_FREQ, _tokens, function_words_only,
                                                  word_frequency)
    span = text[start:end]
    if not span:
        return True
    if function_words_only(text, start, end):
        return True
    words = [word for word, a, b in _tokens(text) if start <= a and b <= end and word.strip()]
    if not words or "".join(words) != span.replace(" ", ""):
        return word_frequency(span) >= ORDINARY_WORD_FREQ
    return all(len(word) >= 2 and word_frequency(word) >= ORDINARY_WORD_FREQ for word in words)


def _contains_ordinary_word(text: str, start: int, end: int) -> bool:
    """A common multi-character non-noun word sits inside ``text[start:end]``
    (的是安排: the fix was an ordinary word, the rest is context)."""
    from ..subtitle_rules.stutter_cleanup import NOUN_TAGS, ORDINARY_WORD_FREQ, _tokens, word_frequency, word_tag
    return any(start <= a and b <= end and len(word) >= 2 and word_frequency(word) >= ORDINARY_WORD_FREQ
               and word_tag(word) not in NOUN_TAGS for word, a, b in _tokens(text))


def _region(before: str, after: str):
    """The one changed region ``(a, b, c, d)``: before[a:b] became after[c:d]."""
    blocks = [(a, b, c, d) for tag, a, b, c, d in SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
              if tag != "equal"]
    if not blocks:
        return None
    a, c = blocks[0][0], blocks[0][2]
    b, d = blocks[-1][1], blocks[-1][3]
    if max(b - a, d - c) > MAX_TERM_LENGTH:
        return None
    return a, b, c, d


def _clean_pair(before: str, after: str, source: str, target: str, *, explicit: bool) -> bool:
    """Shared gates for any pair (see the module docstring)."""
    from ..subtitle_rules.pronouns import is_pronoun_swap
    if (not source or not target or source == target or is_pronoun_swap(source, target)
            or max(len(source), len(target)) > MAX_TERM_LENGTH or source.strip() != source
            or target.strip() != target):
        return False
    left, right = before.find(source), after.find(target)
    if left < 0 or right < 0:
        return False
    return (not _ordinary_language(before, left, left + len(source))
            and not _contains_ordinary_word(after, right, right + len(target)))


def _span_tokens(text: str, part: str):
    start = text.find(part)
    end = start + len(part)
    return start, end, [row for row in _posseg(text) if row[2] < end and start < row[3]]


def _clean_new_name(before: str, after: str, source: str, target: str, *, explicit: bool,
                    name_edges: bool = False) -> bool:
    """A pair not anchored by an existing glossary term."""
    if not _clean_pair(before, after, source, target, explicit=explicit):
        return False
    han = len(_HAN.findall(target))
    if han and han < (2 if explicit else 3):
        return False
    if not han and len(target) < 2:
        return False
    # The misheard form holds no particle / pronoun / preposition / 是: 老是 is
    # an ordinary adverb even where the dictionary does not list it.
    _start, _end, inside = _span_tokens(before, source)
    if any(_function_word(word, tag) for word, tag, _a, _b in inside):
        return False
    if explicit:
        return True
    start, end, tokens = _span_tokens(after, target)
    if not tokens or tokens[0][2] != start or tokens[-1][3] != end:
        return False  # not on word boundaries (把用芙宁)
    if _function_word(tokens[0][0], tokens[0][1]) or _function_word(tokens[-1][0], tokens[-1][1]):
        return False
    return not name_edges or (tokens[0][1] in NAME_TAGS and tokens[-1][1] in NAME_TAGS)


# pair extraction ----------------------------------------------------------
def glossary_pairs(before: str, after: str, canonical_terms) -> list[tuple[str, str]]:
    """(misheard, canonical) when the fixed text covers an applied glossary term."""
    region = _region(before, after)
    if region is None:
        return []
    a, b, c, d = region
    delta = (d - c) - (b - a)
    best = None
    for term in sorted({str(term) for term in canonical_terms if str(term).strip()}, key=len, reverse=True):
        for match in re.finditer(re.escape(term), after):
            s, e = match.span()
            if s <= c and d <= e and (c < d or s < c < e or (s <= c <= e and b > a)):
                source = before[s:e - delta]
                if source and source != term:
                    best = (source, term)
                    break
        if best:
            break
    if best is None or not _clean_pair(before, after, *best, explicit=True):
        return []
    return [best]


def _name_token_pair(before: str, after: str):
    """The name (jieba name-tagged words) the fixed characters belong to."""
    region = _region(before, after)
    if region is None:
        return None
    a, b, c, d = region
    delta = (d - c) - (b - a)
    tokens = list(_posseg(after))
    covering = [index for index, row in enumerate(tokens) if row[2] < max(d, c + 1) and c < row[3]]
    if not covering:
        return None
    first, last = covering[0], covering[-1]
    while first > 0 and tokens[first - 1][1] in NAME_TAGS:
        first -= 1
    while last + 1 < len(tokens) and tokens[last + 1][1] in NAME_TAGS:
        last += 1
    if not all(tokens[index][1] in NAME_TAGS for index in range(first, last + 1)):
        return None
    s, e = tokens[first][2], tokens[last][3]
    if not (s <= c and d <= e):
        return None
    return before[s:e - delta], after[s:e]


def new_name_pairs(before: str, after: str, learned_pairs=(), *, explicit: bool = False) -> list[tuple[str, str]]:
    """A clean new-name pair: the name the fixed characters belong to (jieba
    name tags: 芙宁娜, 迪卢克), else the learned pair when it starts and ends
    on name words; the user's own find-and-replace pair is taken as typed."""
    try:
        if explicit:
            return [(source, target) for source, target in learned_pairs[:1]
                    if _clean_new_name(before, after, source, target, explicit=True)]
        pair = _name_token_pair(before, after)
        if pair is not None and _clean_new_name(before, after, *pair, explicit=False):
            return [pair]
        return [(source, target) for source, target in learned_pairs[:1]
                if _clean_new_name(before, after, source, target, explicit=False, name_edges=True)]
    except Exception:  # no lexicon: never guess
        return []


def autosave_pairs(before: str, after: str, *, canonical_terms=(), learned_pairs=None,
                   explicit: bool = False) -> list[tuple[str, str]]:
    """Name pairs of one manual edit that may be written without asking."""
    from .glossary_learning import extract_term_replacements
    from ..subtitle_rules.pronouns import is_pronoun_swap
    before, after = str(before or ""), str(after or "")
    region = _region(before, after)
    if region is None or is_pronoun_swap(before[region[0]:region[1]], after[region[2]:region[3]]):
        return []
    try:
        pairs = glossary_pairs(before, after, canonical_terms)
    except Exception:
        pairs = []
    if pairs:
        return pairs
    if learned_pairs is None:
        learned_pairs = extract_term_replacements(before, after)
    return new_name_pairs(before, after, learned_pairs, explicit=explicit)


# writing ------------------------------------------------------------------
def applied_terms(glossary_ids, *, legacy=None):
    """(snapshot of the applied libraries, their canonical terms)."""
    ids = [str(item) for item in dict.fromkeys(glossary_ids or ()) if str(item).strip()]
    if not ids:
        return None, ()
    if legacy is None:
        import subtitle_core as legacy
    from .terminology import snapshot_glossaries
    snapshot = snapshot_glossaries(legacy, ids)
    terms = tuple(dict.fromkeys(term.canonical for library in snapshot.libraries if library.found
                                for term in library.terms if term.canonical))
    return snapshot, terms


def choose_library(snapshot, target: str):
    """(library_id, library_name, category) for ``target``, or (None, reason, "")."""
    if snapshot is None:
        return None, "no_glossary", ""
    found = [library for library in snapshot.libraries if library.found]
    owners = []
    for library in found:
        term = next((term for term in library.terms if term.canonical.casefold() == target.casefold()), None)
        if term is not None:
            owners.append((library, term.category))
    if len(owners) == 1:
        library, category = owners[0]
        return library.id, library.name, category or "其他"
    if len(found) == 1:
        return found[0].id, found[0].name, "其他"
    return None, AMBIGUOUS, ""


def _mapping_keys(legacy, library_id):
    payload = legacy.load_learned_term_payload()
    games = payload.get("games", {}) if isinstance(payload, dict) else {}
    key = legacy._glossary_entry_key(library_id, games) if hasattr(legacy, "_glossary_entry_key") else library_id
    entry = games.get(key) or {}
    return {(str(row.get("from", "")), str(row.get("to", ""))) for row in entry.get("mappings", ())
            if isinstance(row, dict)}


def remember(snapshot, source: str, target: str, *, legacy=None) -> AutoSaveResult:
    """Write ``source → target`` (and the canonical itself) into the chosen library."""
    if legacy is None:
        import subtitle_core as legacy
    library_id, name, category = choose_library(snapshot, target)
    if library_id is None:
        return AutoSaveResult(source, target, name if name == AMBIGUOUS else FAILED, reason=name)
    result = AutoSaveResult(source, target, EXISTS, library_id, name)
    try:
        before = _mapping_keys(legacy, library_id)
        for row in ((target, target), (source, target)):
            if legacy.add_learned_mapping(library_id, row[0], row[1], category=category, origin=AUTO_ORIGIN):
                result.status = SAVED
        after = _mapping_keys(legacy, library_id)
        result.added = sorted(after - before)
    except ValueError as exc:  # 别名冲突: the user's own mapping wins
        result.status, result.reason = CONFLICT, str(exc)
    except (OSError, TypeError) as exc:
        result.status, result.reason = FAILED, str(exc)
    return result


def forget(result: AutoSaveResult, *, legacy=None) -> int:
    """Undo one save: remove the rows it added (the canonical row only while no
    other alias still points to it)."""
    if not result.added or not result.library_id:
        return 0
    if legacy is None:
        import subtitle_core as legacy
    rows = [tuple(row) for row in result.added if tuple(row)[0] != tuple(row)[1]]
    removed = legacy.delete_learned_mappings(result.library_id, rows) if rows else 0
    canonical = [tuple(row) for row in result.added if tuple(row)[0] == tuple(row)[1]]
    if canonical:
        remaining = _mapping_keys(legacy, result.library_id)
        orphan = [row for row in canonical
                  if not any(to == row[1] and source != to for source, to in remaining)]
        if orphan:
            removed += legacy.delete_learned_mappings(result.library_id, orphan)
    result.added = []
    return removed


__all__ = ["AMBIGUOUS", "AUTO_ORIGIN", "AutoSaveResult", "CONFLICT", "EXISTS", "FAILED", "SAVED",
           "applied_terms", "autosave_pairs", "choose_library", "forget", "glossary_pairs", "new_name_pairs",
           "remember"]
