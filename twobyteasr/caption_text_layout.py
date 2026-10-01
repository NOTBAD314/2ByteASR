"""Stable display-only wrapping; never rewrite cue text, timing, or font size."""
from dataclasses import dataclass
import unicodedata


def normalized_caption_text(text):
    return str(text).replace('\r\n','\n').replace('\r','\n').replace('\u2028','\n').replace('\u2029','\n')


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
                if chars[end-1].isspace() or chars[end-1][-1] in closing:last_break=end
            if end<len(chars):
                if last_break is not None and last_break>start:end=last_break
                if end-start>1 and chars[end-1][-1] in opening:end-=1
                if end-start>1 and chars[end][0] in closing:end-=1
            end=max(start+1,end)
            lines.append(''.join(chars[start:end]));start=end
    widths=tuple(float(measure(line)) if line else 0. for line in lines)
    return CaptionTextLayout('\n'.join(lines),tuple(lines),widths,limit,any(width>limit for width in widths))
