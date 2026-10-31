"""Project transcript evidence onto a cue's real word interval.

This is text alignment, not a newly measured acoustic timestamp. Original
segment evidence stays intact; neighboring partial segments cannot vote.
"""
import re
from functools import lru_cache

from .caption_arbitration import align, content, usable_transcript

# Words separated by spaces and no CJK/kana: English, the European languages,
# Korean (2026-10-27). Their slices keep the transcript's own spacing.
_CJK_OR_KANA = re.compile(r'[぀-ヿ㐀-鿿豈-﫿]')
_SPACED = re.compile(r'\S\s+\S')


def _spaced_words(value: str) -> bool:
    return bool(_SPACED.search(value)) and not _CJK_OR_KANA.search(value)


def join_pieces(parts) -> str:
    """One model's pieces of a cue in order; pieces without CJK/kana get a space between them."""
    text = ''
    for part in parts:
        part = str(part or '')
        if (text and part and not text[-1].isspace() and not part[0].isspace()
                and not _CJK_OR_KANA.search(text) and not _CJK_OR_KANA.search(part)):
            text += ' '
        text += part
    return text


@lru_cache(maxsize=64)
def _text_alignment(base: str, reference: str):
    """Reuse the immutable text map across slices; word times stay uncached.

    Both inputs are already bounded to 512 characters by slice_evidence.
    A cache entry owns no project, cue, word dictionary or dynamic timing.
    """
    if base == reference:
        return tuple((i, i + 1, char, char) for i, char in enumerate(base))
    return tuple(align(base, reference))


def _snap_to_caption(value, start, end, caption):
    """Move a spaced slice's edges onto the caption's own words.

    English cue times come from the caption's forced alignment, the segment's
    word times from the recognizer, so a word midpoint can put one edge word
    into the neighbouring cue ("talk to" | "you today"), and one long API word
    ("sgamut3.cine/slog3", 3.5 s) can push the rest past the cue end. When
    the caption's words occur in the transcript exactly once, overlapping the
    slice and with each edge within the caption's length (at least 2 words),
    that range is the slice. Text matching only, no new timing; a caption
    with other words keeps the time slice and its real difference.
    """
    wanted = [word for word in (content(item).casefold() for item in str(caption or '').split()) if word]
    tokens = [(match.start(), match.end(), content(match.group()).casefold())
              for match in re.finditer(r'\S+', value)]
    tokens = [token for token in tokens if token[2]]
    first = next((index for index, token in enumerate(tokens) if token[1] > start), None)
    last = next((index for index in range(len(tokens) - 1, -1, -1) if tokens[index][0] < end), None)
    if not wanted or first is None or last is None:
        return start, end
    size = len(wanted)
    max_shift = max(2, size)
    matches = [at for at in range(max(0, first - max_shift), min(len(tokens) - size, first + max_shift) + 1)
               if abs(at + size - 1 - last) <= max_shift and at <= last and at + size - 1 >= first
               and [token[2] for token in tokens[at:at + size]] == wanted]
    if len(matches) != 1:
        return start, end
    return tokens[matches[0]][0], tokens[matches[0] + size - 1][1]


def _slice_spaced(value, base, low, high, entity_char, caption=None):
    """The cue's part of a spaced transcript, keeping the transcript's spacing.

    ``base`` joins the word texts without spaces, so a whole English segment
    looked like one player ID to the per-letter extension and the slice lost
    every space. Positions map back to ``value``; an identifier is kept whole
    only inside one space-separated token.
    """
    positions = [index for index, char in enumerate(value) if content(char)]
    reference = ''.join(value[index] for index in positions)
    if base.casefold() == reference.casefold():
        # Same letters as the word timeline: one to one, at any length
        # (a whole-file API segment is thousands of letters).
        chosen = range(low, min(high, len(positions)))
    elif max(len(base), len(reference)) > 512:
        return ''
    else:
        cursor, chosen = 0, []
        for left, right, old, new in _text_alignment(base.casefold(), reference.casefold()):
            if new and ((old and left < high and right > low) or (not old and low < left < high)):
                chosen.append(cursor)
            cursor += len(new)
    if not chosen:
        return ''
    start, end = positions[chosen[0]], positions[chosen[-1]] + 1
    while start > 0 and entity_char(value[start-1]) and entity_char(value[start]):
        start -= 1
    while end < len(value) and entity_char(value[end-1]) and entity_char(value[end]):
        end += 1
    if caption:
        start, end = _snap_to_caption(value, start, end, caption)
    return value[start:end]


def slice_evidence(row, cue, field, *, caption=None, text_range=None):
    """``caption``: the cue's current text; spaced transcripts snap their edge words to it."""
    value = str(row.get(field) or '')
    if not usable_transcript(value):
        return ''
    start, end = cue.start_ms, cue.end_ms
    a, b = int(row.get('start_ms', 0)), int(row.get('end_ms', 0))
    overlap = max(0, min(end, b)-max(start, a))
    if overlap < .3 * max(1, end-start):
        return ''
    words = row.get('words') or []
    if not words:
        return value if start <= a and b <= end else ''
    base, selected = '', []
    for word in words:
        text = content(word.get('text', ''))
        left = len(base); base += text
        midpoint = (float(word.get('start_ms', a))+float(word.get('end_ms', b)))/2
        if start <= midpoint < end:
            selected.append((left, len(base)))
    if text_range is not None and base:
        # A proven, untrimmed caption receipt owns an exact source character
        # range. Do not slice it again using another model's word midpoints.
        low, high = text_range
        if not (0 <= low < high <= len(base)):
            return ''
    elif selected and base:
        low, high = selected[0][0], selected[-1][1]
    else:
        return ''
    entity_char = lambda c: c.isascii() and (c.isalnum() or c == '_')
    if _spaced_words(value):
        return _slice_spaced(value, base, low, high, entity_char, caption)
    if max(len(base), len(content(value))) > 512:
        return ''
    # A player ID is one token even when the stored word timeline is per-letter.
    while low > 0 and low < len(base) and entity_char(base[low-1]) and entity_char(base[low]):
        low -= 1
    while high < len(base) and high > 0 and entity_char(base[high-1]) and entity_char(base[high]):
        high += 1
    reference = content(value)
    # Case-fold only for alignment. Emit the original reference's characters.
    operations = _text_alignment(base.casefold(), reference.casefold())
    cursor, pieces = 0, []
    for left, right, old, new in operations:
        text = reference[cursor:cursor+len(new)]
        cursor += len(new)
        if new and ((old and left < high and right > low) or (not old and low < left < high)):
            pieces.append(text)
    return ''.join(pieces)


def cue_evidence(project, cue, field):
    from .asr_source_evidence import cue_source_hypotheses
    wanted = {'moss_text': 'primary', 'firered_text': 'firered',
              'qwen_asr_text': 'qwen', 'qwen_text': 'qwen'}.get(field)
    if wanted:
        return join_pieces(row['text'] for row in cue_source_hypotheses(project, cue)
                           if row['source'] == wanted)
    # Derived context is retained for callers that explicitly ask for it, but
    # it never becomes an independent acoustic source.
    return join_pieces(dict.fromkeys(slice_evidence(project.asr_evidence.get(ref, {}), cue, field)
                                     for ref in cue.evidence_refs))
