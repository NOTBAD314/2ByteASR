"""Stable display-only wrapping; never rewrite cue text, timing, or font size."""
from dataclasses import dataclass
import unicodedata

NO_BREAK_SPACES=frozenset('   ')


def normalized_caption_text(text):
    return str(text).replace('\r\n','\n').replace('\r','\n').replace('\u2028','\n').replace('\u2029','\n')


def line_source_ranges(source, lines):
    """Map display-only line breaks back to unchanged source code points.

    Offsets use Python/Unicode code points, as the word-animation contract
    does. CRLF and Unicode paragraph separators remain identifiable in the
    original source; an inserted soft break consumes no source character.
    """
    source = str(source)
    normalized, starts, ends = [], [], []
    index = 0
    while index < len(source):
        start = index
        char = source[index]
        index += 1
        if char == '\r' and index < len(source) and source[index] == '\n':
            index += 1
        normalized.append('\n' if char in '\r\n\u2028\u2029' else char)
        starts.append(start)
        ends.append(index)
    text = ''.join(normalized)
    result, cursor, display_start = [], 0, 0
    for number, line in enumerate(lines):
        stop = cursor + len(line)
        if text[cursor:stop] != line:
            raise ValueError('Caption layout must preserve every source character')
        manual = stop < len(text) and text[stop] == '\n'
        result.append({
            'sourceStart': starts[cursor] if cursor < len(starts) else len(source),
            'sourceEnd': ends[stop - 1] if stop > cursor else (starts[cursor] if cursor < len(starts) else len(source)),
            'displayStart': display_start,
            'displayEnd': display_start + len(line),
            'breakAfter': 'manual' if manual else ('automatic' if number + 1 < len(lines) else 'none'),
        })
        cursor = stop + int(manual)
        display_start += len(line) + 1
    if cursor != len(text):
        raise ValueError('Caption layout omitted source characters')
    return result


def graphemes(text):
    clusters=[]
    for char in text:
        continuation=unicodedata.combining(char) or char in ('\ufe0e','\ufe0f','\u200d') or (clusters and clusters[-1].endswith('\u200d'))
        if continuation and clusters:clusters[-1]+=char
        else:clusters.append(char)
    return clusters


@dataclass(frozen=True)
class CaptionTextLayout:
    text: str
    lines: tuple[str,...]
    widths: tuple[float,...]
    max_width: float
    overflow: bool


def wrap_caption_text(text,measure,max_width):
    """Greedy measured lines with word/punctuation breaks and explicit newlines.

    Breaks are inserted between graphemes. Every original character remains;
    a single overwide grapheme is reported rather than cropped or shrunk.
    """
    text=normalized_caption_text(text);limit=max(1.,float(max_width));lines=[]
    closing=set('，。！？；：、）】》」』,.!?;:)]}')
    opening=set('（【《「『([{')
    for paragraph in text.split('\n'):
        if not paragraph or measure(paragraph)<=limit:
            lines.append(paragraph);continue
        chars=graphemes(paragraph);start=0
        while start<len(chars):
            end=start;last_break=None
            while end<len(chars):
                candidate=''.join(chars[start:end+1])
                if end>start and measure(candidate)>limit:break
                end+=1
                # No-break spaces (inside a converted math formula, ADR 0124) never break.
                if (chars[end-1].isspace() and chars[end-1] not in NO_BREAK_SPACES) or chars[end-1][-1] in closing:last_break=end
            if end<len(chars):
                if last_break is not None and last_break>start:end=last_break
                if end-start>1 and chars[end-1][-1] in opening:end-=1
                if end-start>1 and chars[end][0] in closing:end-=1
            end=max(start+1,end)
            lines.append(''.join(chars[start:end]));start=end
    widths=tuple(float(measure(line)) if line else 0. for line in lines)
    return CaptionTextLayout('\n'.join(lines),tuple(lines),widths,limit,any(width>limit for width in widths))
