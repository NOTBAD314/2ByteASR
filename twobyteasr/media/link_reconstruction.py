"""Reflow timed web captions without changing their normalized text."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .link_subtitles import Caption, ParsedSubtitles

MODES = ("smart", "original", "ai")
RECONSTRUCTION_VERSION = "1"
PAUSE_MS = 1100
# Number punctuation, contractions and Latin tokens are left intact.
CJK = r"[\u3041-\u30ff\u3400-\u9fff\uf900-\ufaff]"
TOKEN = re.compile(r"\[[^\]\n]{1,80}\]|【[^】\n]{1,80}】|>>+|[♪♫♬]+|" + CJK +
                   r"|[^\s\u3041-\u30ff\u3400-\u9fff\uf900-\ufaff\[\]【】<>♪♫♬]+|[^\s]")
SOUND = re.compile(
    r"(?i)(?:[\[【](?:music|applause|laughter|laughs?|cheering|sighs?|"
    r"音乐|音樂|掌声|掌聲|笑声|笑聲|音楽|拍手|笑い)(?:[ :：][^\]】]*)?[\]】]|[♪♫♬]+)"
)
ABBREVIATION = re.compile(
    r"(?i)(?:\b(?:mr|mrs|ms|dr|prof|sr|jr|st|vs|e\.g|i\.e|etc|no)\.|(?:\b[a-z]\.){2,}|^[A-Z]\.)$"
)
SENTENCE_END = re.compile(r"""[.!?。！？]+["'”’」』）)]*$""")
CLAUSE_END = re.compile(r"""[,;:，、；：]+["'”’」』）)]*$""")
SPEAKER = re.compile(r"^>>+|^[-–—]\s|^[^\W\d_][\w .'-]{0,24}[:：]\s", re.UNICODE)


@dataclass(frozen=True)
class Word:
    text: str
    space_before: bool
    start: int
    end: int | None
    ref: str
    precision: str


def _tokenize(cue: Caption) -> list[Word]:
    anchors = sorted(cue.anchors, key=lambda a: a["char_start"])
    matches = list(TOKEN.finditer(cue.text))
    result = []
    previous_end = anchor_index = 0
    for match in matches:
        lo, hi = match.span()
        while anchor_index < len(anchors) and anchors[anchor_index]["char_end"] <= lo:
            anchor_index += 1
        anchor = anchors[anchor_index] if anchor_index < len(anchors) else None
        if anchor and anchor["char_start"] <= lo < anchor["char_end"]:
            exact = not cue.text[anchor["char_start"]:lo].strip()
            start = anchor["start_ms"]
            precision = anchor.get("precision", "segment_start") if exact else "shared_segment"
            ref = anchor.get("event_ref", "")
            end = anchor.get("end_ms") if not cue.text[hi:anchor["char_end"]].strip() else None
        else:
            start = result[-1].start if result else cue.start_ms
            precision = "estimated" if result else "row_start"
            ref = cue.events[0] if cue.events else ""
            end = None
        result.append(Word(match[0], bool(lo - previous_end), start, end, ref, precision))
        previous_end = hi

    # Interpolate unanchored tokens between reliable onsets. A timed multi-word
    # segment supplies one onset, so its remaining tokens stay estimated.
    previous = None
    pending = []
    for i, word in enumerate(result):
        if word.precision in {"estimated", "shared_segment"}:
            pending.append(i)
            continue
        if pending and previous is not None and word.start > previous.start:
            for n, index in enumerate(pending, 1):
                offset = (word.start - previous.start) * n // (len(pending) + 1)
                result[index] = replace(result[index], start=previous.start + offset, precision="estimated")
        pending.clear()
        previous = word
    if pending and previous is not None:
        tail = max(0, min(cue.end_ms - previous.start - 1, 200 * len(pending)))
        for n, index in enumerate(pending, 1):
            result[index] = replace(result[index], start=previous.start + tail * n // len(pending),
                                    precision="estimated")
    return result


def _is_sentence_end(word: str) -> bool:
    return bool(SENTENCE_END.search(word) and not ABBREVIATION.search(word.rstrip("\"'”’")))


def _word_end(word: Word, next_start: int | None, display_limit: int) -> int:
    if word.end is not None and word.end > word.start:
        return word.end
    estimate = word.start + min(650, max(140, 90 + 48 * len(word.text)))
    limits = [estimate]
    if next_start is not None and next_start > word.start:
        limits.append(next_start)
    if display_limit > word.start:
        limits.append(display_limit)
    return min(limits)


def _caption(words: list[Word], end: int, events: list[str], window) -> Caption:
    parts, anchors = [], []
    position = 0
    for word in words:
        if parts and word.space_before:
            parts.append(" ")
            position += 1
        next_position = position + len(word.text)
        anchors.append(dict(text=word.text, start_ms=word.start, char_start=position,
                            char_end=next_position, event_ref=word.ref, precision=word.precision))
        if word.end is not None and word.start < word.end <= end:
            anchors[-1]["end_ms"] = word.end
        parts.append(word.text)
        position = next_position
    timed = any(w.precision.startswith("segment") for w in words)
    return Caption(words[0].start, max(end, words[-1].start + 1), "".join(parts),
                   events=list(dict.fromkeys(events + [w.ref for w in words if w.ref])),
                   anchors=anchors, precision="segment_start" if timed else "estimated",
                   end_basis="explicit_segment_end" if words[-1].end == end else "estimated_word_end",
                   window=window)


def _protected_offsets(words, language):
    if language not in {"ja", "zh"}:
        return set()
    text = "".join((" " if i and w.space_before else "") + w.text for i, w in enumerate(words))
    if language == "ja":
        from ..subtitle_rules.language_rules import japanese_phrase_spans
        spans = japanese_phrase_spans(text)
    else:
        import jieba
        spans = jieba.tokenize(text)
        spans = [(start, end, word) for word, start, end in spans]
    return {i for start, end, word in spans if any(character.isalnum() for character in word)
            for i in range(start + 1, end)}


def _display_ranges(words: list[Word], max_chars: int, *, language: str):
    """Fit a semantic sentence on screen, choosing a clause or a natural pause."""
    protected = _protected_offsets(words, language)
    offsets = [0]
    for index, word in enumerate(words):
        offsets.append(offsets[-1] + len(word.text) + (index > 0 and word.space_before))
    lo = 0
    while lo < len(words):
        hi, length, best, best_score = lo, 0, lo, -1
        while hi < len(words):
            word = words[hi]
            length += len(word.text) + (hi > lo and word.space_before)
            if hi > lo and (length > max_chars or word.start - words[lo].start > 6900):
                break
            hi += 1
            if hi == len(words):
                break
            following = words[hi]
            if not following.space_before and re.fullmatch(r"[\W_]+", following.text) and not re.fullmatch(CJK, following.text):
                continue
            if word.text.casefold() in {"a", "an", "the", "of", "to", "in", "for", "my", "your", "and", "or"}:
                continue
            if offsets[hi] in protected or (language == "ja" and following.text in "はがをにでともへやの"):
                continue
            gap = following.start - word.start
            score = (250 if CLAUSE_END.search(word.text) else 0) + min(gap, 600) + length * 4
            if length >= max_chars // 3 and score > best_score:
                best, best_score = hi, score
        cut = best if hi < len(words) and best > lo else hi
        while cut < len(words) and offsets[cut] in protected:
            cut += 1
        # Keep attached punctuation with its word when a hard limit lands there.
        while cut < len(words) and not words[cut].space_before and SENTENCE_END.fullmatch(words[cut].text):
            cut += 1
        yield lo, cut
        lo = cut


def reconstruct(parsed: ParsedSubtitles, *, language: str, source: str, mode: str = "smart",
                keep_sound: bool = True, line_chars: int | None = None) -> ParsedSubtitles:
    if mode not in MODES:
        raise ValueError("无效的在线字幕处理模式。")
    if mode == "original":
        captions = [replace(c, end_ms=c.display_end_ms, end_basis="source_display_end")
                    if c.display_end_ms else c for c in parsed.captions]
        return replace(parsed, captions=captions, tidy=dict(mode=mode, version=RECONSTRUCTION_VERSION,
                       rows_before=len(captions), rows_after=len(captions)))
    if keep_sound and (source == "manual" or (
            parsed.format in {"srt", "ttml"} and not any(c.anchors for c in parsed.captions))):
        return replace(parsed, tidy=dict(mode=mode, version=RECONSTRUCTION_VERSION,
                                         rows_before=len(parsed.captions), rows_after=len(parsed.captions)))

    code = language.lower().split("-", 1)[0]
    cjk = code in {"zh", "ja"}
    max_chars = max(12, min(200, (line_chars or (22 if cjk else 42)) * 2))
    result, sentence, refs = [], [], []
    sentence_count = removed = 0
    display_limit = 0
    previous_window = None
    previous_display_end = 0
    semantic_sentences = []
    refs_by_word = {}

    def flush(next_start=None):
        nonlocal sentence_count
        if not sentence:
            return
        sentence_count += 1
        first_index = len(result)
        for lo, hi in _display_ranges(sentence, max_chars, language=code):
            following = sentence[hi].start if hi < len(sentence) else next_start
            mapping = [ref for word in sentence[lo:hi] for ref in refs_by_word.get(word.ref, ())]
            result.append(_caption(sentence[lo:hi], _word_end(sentence[hi - 1], following, display_limit),
                                   mapping, previous_window))
        semantic_sentences.append({"caption_start": first_index, "caption_end": len(result)})
        sentence.clear()
        refs_by_word.clear()

    for cue in parsed.captions:
        words = _tokenize(cue)
        if not words:
            continue
        if sentence and (cue.window != previous_window or SPEAKER.search(cue.text) or
                         words[0].start - _word_end(sentence[-1], None, display_limit) >= PAUSE_MS or
                         words[0].start < sentence[-1].start):
            flush(words[0].start if cue.window == previous_window else None)
        previous_window = cue.window
        previous_display_end, display_limit = display_limit, cue.end_ms

        for index, word in enumerate(words):
            if not keep_sound and SOUND.fullmatch(word.text):
                removed += 1
                continue
            sound = SOUND.fullmatch(word.text) is not None
            if sentence and (word.text.startswith(">>") or sound or
                             word.start - _word_end(sentence[-1], None, previous_display_end if index == 0 else display_limit) >= PAUSE_MS):
                flush(word.start)
            if index == 0 and sentence:
                word = replace(word, space_before=not cjk or not (
                    re.search(CJK + r"$", sentence[-1].text) and re.match(CJK, word.text)))
            sentence.append(word)
            if word.ref:
                # Includes source row controls and duplicate-display references.
                refs_by_word.setdefault(word.ref, cue.events)
            next_start = words[index + 1].start if index + 1 < len(words) else None
            if sound or _is_sentence_end(word.text):
                flush(next_start)
    flush()
    if not result:
        raise ValueError("此字幕在当前选项下没有可导入文字。")
    tidy = dict(mode=mode, version=RECONSTRUCTION_VERSION, rows_before=len(parsed.captions),
                rows_after=len(result), semantic_sentences=sentence_count, labels_removed=removed,
                word_onsets=sum(a["precision"].startswith("segment") for c in result for a in c.anchors),
                estimated_onsets=sum(a["precision"] in {"estimated", "row_start"} for c in result for a in c.anchors))
    return replace(parsed, captions=result, tidy=tidy, sentence_ranges=semantic_sentences)
