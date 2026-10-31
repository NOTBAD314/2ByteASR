"""Stable display-only wrapping; never rewrite cue text, timing, or font size."""
from dataclasses import dataclass
import unicodedata
import re

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
    from ..subtitle_rules.segmentation_profiles import graphemes as source_graphemes
    return [cluster for a,b,cluster in source_graphemes(text)]


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
        offsets=[0]
        for cluster in chars:offsets.append(offsets[-1]+len(cluster))
        cjk=any(0x3400<=ord(ch)<=0x9fff or 0x3040<=ord(ch)<=0x30ff for ch in paragraph)
        # Spaced scripts keep entire words, apostrophe/hyphen forms and
        # formula no-break spaces. CJK still protects embedded IDs/numbers
        # and complete katakana runs without initializing a tokenizer in paint.
        pattern=r'[A-Za-zÀ-ɏА-яЁё0-9]+(?:[\w\u0300-\u036f’\'._:/%+-]*[\w\u0300-\u036f])?|[ァ-ヿー]+' if cjk else r'[^ \t\r\n]+'
        atoms=[(m.start(),m.end()) for m in re.finditer(pattern,paragraph)]
        legal={i for i,p in enumerate(offsets) if not any(a<p<b for a,b in atoms)}
        while start<len(chars):
            end=start;last_break=None
            while end<len(chars):
                candidate=''.join(chars[start:end+1])
                if end>start and measure(candidate)>limit:break
                end+=1
                # No-break spaces (inside a converted math formula, ADR 0124) never break.
                if end in legal and ((chars[end-1].isspace() and chars[end-1] not in NO_BREAK_SPACES) or chars[end-1][-1] in closing):last_break=end
            if end<len(chars):
                if last_break is not None and last_break>start:end=last_break
                if end-start>1 and chars[end-1][-1] in opening and end-1 in legal:end-=1
                if end-start>1 and chars[end][0] in closing and end-1 in legal:end-=1
            if end not in legal:
                before=[p for p in legal if start<p<=end]
                end=max(before) if before else min(p for p in legal if p>start)
            end=max(start+1,end)
            lines.append(''.join(chars[start:end]));start=end
    widths=tuple(float(measure(line)) if line else 0. for line in lines)
    return CaptionTextLayout('\n'.join(lines),tuple(lines),widths,limit,any(width>limit for width in widths))
