"""Tidy downloaded captions before import and the derived files (2026-10-26).

User report: YouTube captions carry ``[Music]``-style labels that mean nothing
in a subtitle, and automatic captions break where YouTube's display rows wrap
("…faces in MMA has been" / "America's new favorite pastime and" / "wearing").

1. Sound labels go: ``[Music]``, ``[Applause]`` and anything else in square
   brackets (also across several words), ``♪``/``♫``, and the ``>>`` speaker
   mark (kept as a forced break). A row left empty is dropped.
2. Automatic captions whose rows give every word's start are re-broken by
   words with the same rules as recognized English (and the European languages
   that share its breaker): sentence end first, then a clause mark, a
   conjunction or a pause; never after "the", "a", "to"…; two lines of 42
   characters and 7 seconds at most. A pause of 2 s or more, a row without
   word times and a speaker mark always end a subtitle.

The original file stays untouched (``link_manifest`` keeps it by content
hash); this only shapes the parsed captions.
"""
from __future__ import annotations

from dataclasses import replace
import re

from .link_subtitles import Caption, ParsedSubtitles

TIDY_VERSION = "1"
_BRACKETED = re.compile(r"\[[^\[\]]*\]")
_NOTES = re.compile(r"[♪♫♬]+")
_SPEAKER = re.compile(r"(^|\s)>>+(?=\s|$)")
_SPACES = re.compile(r"\s+")
HARD_PAUSE_MS = 2000
REGROUP_LANGUAGES = {"en", "es", "de", "fr", "pt", "it", "ru"}


def strip_labels(text: str) -> tuple[str, bool, int]:
    """(text without sound labels, had a speaker mark, labels removed)."""
    count = len(_BRACKETED.findall(text)) + len(_NOTES.findall(text))
    speaker = bool(_SPEAKER.search(text))
    cleaned = _SPEAKER.sub(" ", _NOTES.sub(" ", _BRACKETED.sub(" ", text)))
    return _SPACES.sub(" ", cleaned).strip(), speaker, count + (1 if speaker else 0)


def _words(caption: Caption) -> list[dict] | None:
    """Every word of ``caption`` with its onset, or None when one has none."""
    if not caption.anchors:
        stripped = caption.text.strip()
        if stripped and " " not in stripped:   # a one-word row starts with its row
            return [dict(text=stripped, start_ms=caption.start_ms, ref=(caption.events or [""])[0])]
        return None
    covered = [False] * len(caption.text)
    rows = []
    for anchor in sorted(caption.anchors, key=lambda a: (a["char_start"], a["start_ms"])):
        lo, hi = int(anchor["char_start"]), int(anchor["char_end"])
        for index in range(max(0, lo), min(len(caption.text), hi)):
            covered[index] = True
        for piece in caption.text[lo:hi].split():
            rows.append(dict(text=piece, start_ms=int(anchor["start_ms"]), ref=anchor.get("event_ref", "")))
    if any(not done and not char.isspace() for done, char in zip(covered, caption.text)):
        return None
    for left, right in zip(rows, rows[1:]):
        if right["start_ms"] < left["start_ms"]:
            return None
    return rows


def strip_word_labels(words: list[dict]) -> tuple[list[dict], int, bool]:
    """Drop bracketed labels spanning words, music notes and ``>>``; the first
    word after a speaker mark carries ``break_before``."""
    kept, removed, depth, speaker, pending_break = [], 0, 0, False, False
    for word in words:
        text = word["text"]
        if depth or text.startswith("["):
            opens, closes = text.count("["), text.count("]")
            depth = max(0, depth + opens - closes)
            if not depth:
                removed += 1
                tail = text[text.rfind("]") + 1:].strip()
                if tail:
                    kept.append(dict(word, text=tail, break_before=pending_break))
                    pending_break = False
            continue
        if _NOTES.fullmatch(text) or text in (">>", ">>>"):
            removed += 1
            if text.startswith(">>"):
                speaker = pending_break = True
            continue
        cleaned = _NOTES.sub("", text)
        if not cleaned:
            continue
        kept.append(dict(word, text=cleaned, break_before=pending_break))
        pending_break = False
    return kept, removed, speaker


def lexicon_for(language: str):
    from ..subtitle_rules import european_text
    from ..subtitle_rules.language_rules import normalize_language
    code = normalize_language(language)
    if code == "en":
        from ..subtitle_rules.english_segmentation import ENGLISH
        return ENGLISH
    return european_text.lexicon(code) if code in REGROUP_LANGUAGES else None


def _caption(words: list[dict], end_ms: int, lexicon, events: list[str]) -> Caption:
    from ..subtitle_rules.english_segmentation import _tools
    join = _tools(lexicon)[3]
    text = join([w["text"] for w in words])
    anchors, cursor = [], 0
    for word in words:
        lo = text.find(word["text"], cursor)
        if lo < 0:      # the join changed spacing around punctuation; fall back to sentence timing
            anchors = []
            break
        hi = lo + len(word["text"])
        anchors.append(dict(text=word["text"], char_start=lo, char_end=hi, start_ms=word["start_ms"],
                            event_ref=word.get("ref", ""), precision="segment_start"))
        cursor = hi
    start = words[0]["start_ms"]
    return Caption(start, max(end_ms, start + 1), text, events, anchors,
                   "segment_start" if anchors else "sentence", "regrouped_by_words")


def _regroup(run: list[dict], run_end_ms: int, lexicon) -> list[Caption]:
    """Re-break one run of timed words (see the module note)."""
    from ..subtitle_rules.english_segmentation import split_tokens
    tokens = [w["text"] for w in run]
    onsets = [w["start_ms"] for w in run]
    durations, gaps = [], []
    for index, onset in enumerate(onsets):
        nxt = onsets[index + 1] if index + 1 < len(onsets) else run_end_ms
        durations.append(max(0.05, (nxt - onset) / 1000))
    for index in range(len(onsets) - 1):
        spoken = 0.15 + 0.06 * len(tokens[index])
        gaps.append(max(0.0, (onsets[index + 1] - onsets[index]) / 1000 - spoken))
    pieces = split_tokens(tokens, gaps, durations=durations, lexicon=lexicon)
    captions = []
    for lo, hi in pieces:
        end = onsets[hi] if hi < len(onsets) else run_end_ms
        events = list(dict.fromkeys(w["ref"] for w in run[lo:hi] if w.get("ref")))
        captions.append(_caption(run[lo:hi], end, lexicon, events))
    return captions


def tidy_captions(parsed: ParsedSubtitles, *, language: str = "", source: str = "",
                  regroup: bool = True) -> ParsedSubtitles:
    """``parsed`` without sound labels; automatic captions re-broken by words."""
    lexicon = lexicon_for(language) if regroup and source == "automatic" else None
    output: list[Caption] = []
    run: list[dict] = []
    run_end = 0
    removed_total = 0

    def flush():
        nonlocal run, run_end
        if run:
            output.extend(_regroup(run, run_end, lexicon))
        run, run_end = [], 0

    for caption in parsed.captions:
        words = _words(caption) if lexicon is not None else None
        if words is not None:
            kept, removed, _speaker = strip_word_labels(words)
            removed_total += removed
            for word in kept:
                if run and (word.get("break_before") or word["start_ms"] - run[-1]["start_ms"] >= HARD_PAUSE_MS):
                    flush()
                run.append(word)
            if kept:
                run_end = caption.end_ms
            continue
        flush()
        text, _speaker, removed = strip_labels(caption.text)
        removed_total += removed
        if not text:
            continue
        if removed:
            # The text moved: its character anchors no longer point at the same words.
            caption = replace(caption, text=text, anchors=[], precision="sentence")
        output.append(caption)
    flush()
    return replace(parsed, captions=output, warnings=list(parsed.warnings),
                   tidy=dict(version=TIDY_VERSION, labels_removed=removed_total, rows_before=len(parsed.captions),
                             rows_after=len(output), regrouped=lexicon is not None))
