"""匹配文稿 (2026-10-14): time the user's own, already line-broken script with
word/character timestamps only. No recognition model, no AI, no network.

The input besides the script is a stream of timed tokens in one clock: in
Studio the words every caption already has, on the Home route the character
timestamps of the timeline model. The user's lines are never rewritten,
merged or re-split.

1. Every content character of the script is aligned to the tokens' content
   characters in one monotonic pass. Chinese characters compare by folded
   pinyin, so a heard homophone (至东 for 至冬) still anchors its line; other
   characters compare case-folded.
2. A line runs from its first to its last heard character. Unheard
   characters at either edge extend it by the line's own reading pace, at
   most ``EDGE_EXTEND_MAX_MS``, never into a neighbour.
3. A line without any heard character is placed between its neighbours by
   character share and marked as estimated, so the user can review it.
4. The line's words are re-derived with the matcher Studio uses for edited
   captions (``cue_word_alignment.align_text_to_tokens``), so word timing,
   razor cuts and karaoke keep their usual measured/unmeasured rules.

Tokens marked ``estimated`` (captions without measured words, spread by the
caption's own interval) may place a line but never become words.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import difflib
import re

from .cue_word_alignment import AlignedWord, align_text_to_tokens, content_positions, normalized_content

EDGE_EXTEND_MAX_MS = 1500
MIN_LINE_MS = 300
# Tokens considered around a line when its words are derived.
WORD_WINDOW_MS = 3000


@dataclass(frozen=True)
class Token:
    start_ms: int
    end_ms: int
    text: str
    ref: str = ''
    speaker: str = ''
    estimated: bool = False


@dataclass
class MatchedLine:
    index: int
    text: str
    start_ms: int
    end_ms: int
    content_chars: int
    matched_chars: int
    measured_chars: int
    speaker: str = ''
    refs: tuple[str, ...] = ()
    placed_by: str = 'heard'          # heard | estimated_between_neighbours
    edges_estimated: bool = False
    words: tuple[AlignedWord, ...] = ()
    word_reason: str = 'missing_word_timestamps'

    @property
    def coverage(self) -> float:
        return self.matched_chars / self.content_chars if self.content_chars else 0.0

    @property
    def needs_review(self) -> bool:
        return self.placed_by != 'heard' or self.coverage < 0.5 or not self.words


@dataclass
class ScriptMatch:
    lines: list[MatchedLine] = field(default_factory=list)
    total_chars: int = 0
    matched_chars: int = 0
    token_chars: int = 0
    unmatched_token_chars: int = 0

    @property
    def coverage(self) -> float:
        return self.matched_chars / self.total_chars if self.total_chars else 0.0

    @property
    def review_count(self) -> int:
        return sum(1 for line in self.lines if line.needs_review)


class ScriptMatchError(ValueError):
    pass


def parse_script(text: str) -> list[str]:
    """One subtitle per non-empty line, exactly as typed (edges trimmed)."""
    return [line.strip() for line in str(text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
            if line.strip()]


_CJK = re.compile(r'[㐀-鿿豈-﫿]')


def _fold(text: str) -> str:
    """Width and kana folding (2026-10-15, scripts in other languages): ＡＢ
    = AB, ｶﾞ = ガ, and katakana compares as hiragana (カ = か), so a script
    and a recognizer that chose a different kana or width still meet. Whole
    strings: a half-width voiced mark is its own character until composed."""
    import unicodedata
    text = unicodedata.normalize('NFKC', str(text))
    return ''.join(chr(ord(char) - 0x60) if 0x30A1 <= ord(char) <= 0x30F6 else char for char in text)


def _key(char: str, language: str = '') -> str:
    if _CJK.match(char) and language != 'ja':
        # Chinese: a heard homophone (至东 for 至冬) still anchors the line.
        # Japanese kanji keep their own identity: Chinese readings would make
        # unrelated kanji equal.
        try:
            from ..subtitle_rules.text_similarity import phonetic_text
            key = phonetic_text(char) or char
        except Exception:  # pinyin unavailable: exact characters still match
            return char
        key = re.sub(r'^(zh|ch|sh)', lambda match: match.group(1)[0], key)
        return 'py:' + re.sub(r'(?<=[aeiouv])ng$', 'n', key)
    return char.casefold()


def match_script(lines: list[str], tokens: list[Token], *, speech_regions_ms=None, language: str = '') -> ScriptMatch:
    """Place every script line on the token clock; see the module docstring.

    ``speech_regions_ms`` (``[(start, end), ...]`` from an energy VAD) trims
    heard lines whose first or last token absorbed a pause: FireRed's
    character boundaries are contiguous, so the silence before a line belongs
    to its first character (2026-10-14 check: 今 lasted 748 ms).
    ``language`` is the spoken language ('zh', 'ja', 'en'; '' = Chinese rules).
    """
    if not lines:
        raise ScriptMatchError('文稿是空的')
    stream = sorted((t for t in tokens if t.end_ms > t.start_ms and normalized_content(t.text)),
                    key=lambda t: (t.start_ms, t.end_ms))
    if not stream:
        raise ScriptMatchError('没有可用的字级时间戳')
    language = str(language or '')
    heard_keys, heard_owner = [], []
    for index, token in enumerate(stream):
        for char in _fold(normalized_content(token.text)):
            heard_keys.append(_key(char, language))
            heard_owner.append(index)
    script_keys, script_line = [], []
    content = [_fold(normalized_content(line)) for line in lines]
    for index, text in enumerate(content):
        for char in text:
            script_keys.append(_key(char, language))
            script_line.append(index)
    linked: list[int | None] = [None] * len(script_keys)   # script char -> heard char
    matcher = difflib.SequenceMatcher(None, heard_keys, script_keys, autojunk=False)
    for i, j, size in matcher.get_matching_blocks():
        for k in range(size):
            linked[j + k] = i + k

    result = ScriptMatch(total_chars=len(script_keys), token_chars=len(heard_keys))
    result.matched_chars = sum(1 for value in linked if value is not None)
    result.unmatched_token_chars = len(heard_keys) - result.matched_chars
    per_line: list[list[tuple[int, int]]] = [[] for _ in lines]   # (char offset in line, heard char)
    offset_in_line = Counter()
    for j, line_index in enumerate(script_line):
        offset = offset_in_line[line_index]
        offset_in_line[line_index] += 1
        if linked[j] is not None:
            per_line[line_index].append((offset, linked[j]))

    placed: list[MatchedLine] = []
    for index, text in enumerate(lines):
        hits = per_line[index]
        count = len(content[index])
        line = MatchedLine(index=index, text=text, start_ms=0, end_ms=0, content_chars=count,
                           matched_chars=len(hits), measured_chars=0)
        if hits:
            owners = [heard_owner[h] for _, h in hits]
            line.start_ms = stream[owners[0]].start_ms
            line.end_ms = max(stream[o].end_ms for o in owners)
            line.measured_chars = sum(1 for o in owners if not stream[o].estimated)
            speakers = Counter(stream[o].speaker for o in owners)
            line.speaker = speakers.most_common(1)[0][0]
            line.refs = tuple(dict.fromkeys(stream[o].ref for o in owners if stream[o].ref))
            lead, trail = hits[0][0], count - 1 - hits[-1][0]
            if (lead or trail) and line.end_ms > line.start_ms:
                pace = (line.end_ms - line.start_ms) / max(1, hits[-1][0] - hits[0][0] + 1)
                line.start_ms -= min(EDGE_EXTEND_MAX_MS, round(lead * pace))
                line.end_ms += min(EDGE_EXTEND_MAX_MS, round(trail * pace))
                line.edges_estimated = True
            if line.measured_chars == 0:
                line.placed_by = 'estimated_tokens'
        else:
            line.placed_by = 'estimated_between_neighbours'
        placed.append(line)

    _resolve_overlaps(placed)
    if speech_regions_ms:
        _snap_to_speech(placed, per_line, heard_owner, stream, speech_regions_ms)
    _place_unheard(placed, stream)
    for line in placed:
        if line.end_ms - line.start_ms < MIN_LINE_MS:
            following = next((other.start_ms for other in placed[line.index + 1:] if other.start_ms > line.start_ms),
                             None)
            limit = following if following is not None else line.start_ms + MIN_LINE_MS
            line.end_ms = max(line.end_ms, min(line.start_ms + MIN_LINE_MS, limit))
            if line.end_ms <= line.start_ms:
                line.end_ms = line.start_ms + 1
        line.start_ms, line.end_ms = max(0, int(line.start_ms)), max(1, int(line.end_ms))
    _derive_words(placed, stream)
    result.lines = placed
    return result


def _resolve_overlaps(lines: list[MatchedLine]) -> None:
    """Heard lines keep script order; a shared or extended edge is split at the midpoint."""
    heard = [line for line in lines if line.placed_by != 'estimated_between_neighbours']
    for left, right in zip(heard, heard[1:]):
        if right.start_ms < left.end_ms:
            boundary = (max(left.start_ms, right.start_ms) + min(left.end_ms, right.end_ms)) // 2
            boundary = min(max(boundary, left.start_ms + 1), max(right.end_ms - 1, left.start_ms + 1))
            left.end_ms, right.start_ms = boundary, boundary
            left.edges_estimated = right.edges_estimated = True


MIN_TOKEN_KEEP_MS = 80


def _snap_to_speech(lines, per_line, heard_owner, stream, regions) -> None:
    """Start at the next speech onset / end at the last speech offset when the
    edge sits in silence, never past the line's own first or last token."""
    regions = sorted((int(a), int(b)) for a, b in regions if b > a)

    def region_at(at):
        return next(((a, b) for a, b in regions if a <= at <= b), None)

    for line, hits in zip(lines, per_line):
        if line.placed_by == 'estimated_between_neighbours' or not hits:
            continue
        first = stream[heard_owner[hits[0][1]]]
        last = stream[heard_owner[hits[-1][1]]]
        # The speech the first character ends in starts this line; the speech
        # the last character starts in ends it. Edges reaching into the pause
        # (or the neighbour's speech) are pulled back to those bounds.
        opening = region_at(first.end_ms - MIN_TOKEN_KEEP_MS // 2)
        if opening and line.start_ms < opening[0] <= first.end_ms - MIN_TOKEN_KEEP_MS:
            line.start_ms = opening[0]
        closing = region_at(last.start_ms + MIN_TOKEN_KEEP_MS // 2)
        if closing and line.end_ms > closing[1] >= last.start_ms + MIN_TOKEN_KEEP_MS and closing[1] > line.start_ms:
            line.end_ms = closing[1]


def _place_unheard(lines: list[MatchedLine], stream: list[Token]) -> None:
    """Runs of lines with no heard character share the gap between heard neighbours."""
    index = 0
    while index < len(lines):
        if lines[index].placed_by != 'estimated_between_neighbours':
            index += 1
            continue
        end = index
        while end < len(lines) and lines[end].placed_by == 'estimated_between_neighbours':
            end += 1
        before = lines[index - 1].end_ms if index > 0 else stream[0].start_ms
        after = lines[end].start_ms if end < len(lines) else stream[-1].end_ms
        if after - before < MIN_LINE_MS * (end - index):
            # No room: hang them after the previous line, one minimum each.
            after = before + MIN_LINE_MS * (end - index)
        weights = [max(1, lines[k].content_chars) for k in range(index, end)]
        total = sum(weights)
        cursor = before
        for k, weight in zip(range(index, end), weights):
            span = (after - before) * weight / total
            lines[k].start_ms, lines[k].end_ms = round(cursor), round(cursor + span)
            lines[k].speaker = lines[index - 1].speaker if index > 0 else (lines[end].speaker if end < len(lines) else '')
            cursor += span
        index = end


def _derive_words(lines: list[MatchedLine], stream: list[Token]) -> None:
    measured = [t for t in stream if not t.estimated]
    starts = [t.start_ms for t in measured]
    import bisect
    for line in lines:
        if line.placed_by == 'estimated_between_neighbours' or not content_positions(line.text):
            line.word_reason = 'missing_word_timestamps'
            continue
        lo = bisect.bisect_left(starts, line.start_ms - WORD_WINDOW_MS)
        hi = bisect.bisect_right(starts, line.end_ms + WORD_WINDOW_MS)
        records = [(t.start_ms, t.end_ms, normalized_content(t.text), t.ref or 'script-match') for t in measured[lo:hi]]
        words, reason = align_text_to_tokens(line.text, records, (line.start_ms, line.end_ms))
        line.words, line.word_reason = tuple(words), reason


def tokens_from_project(project) -> list[Token]:
    """Every caption's current words on the project clock (Studio route).

    Captions whose words are not measured contribute their characters spread
    over the caption, marked estimated: they can place a line, never time a word.
    """
    from .cue_word_alignment import cue_words
    tokens: list[Token] = []
    for cue in sorted(project.cues, key=lambda c: (c.start_ms, c.end_ms)):
        words, _reason = cue_words(project, cue)
        if words:
            tokens.extend(Token(w.start_ms, w.end_ms, cue.text[w.char_start:w.char_end], w.evidence_ref,
                                cue.speaker_id) for w in words)
            continue
        chars = [char for _, char in content_positions(cue.text)]
        if not chars or cue.end_ms <= cue.start_ms:
            continue
        step = (cue.end_ms - cue.start_ms) / len(chars)
        tokens.extend(Token(round(cue.start_ms + k * step), round(cue.start_ms + (k + 1) * step), char,
                            'cue-estimate:' + cue.id, cue.speaker_id, True)
                      for k, char in enumerate(chars))
    return tokens


__all__ = ['MatchedLine', 'ScriptMatch', 'ScriptMatchError', 'Token', 'match_script', 'parse_script',
           'tokens_from_project']
