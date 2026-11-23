"""Per-cue text marks inside an AI web theme.

A caption's own marks (Markdown bold, highlight, strike, heading, colour; see
``caption_style.text_marks``) ride with the cue's text to the theme runtime as
one suffix after ``SEPARATOR``. Text is the identity every web-theme cache,
strip and cue pool already keys on, so a mark change invalidates them without
a second key, and an unmarked caption is byte-for-byte what it was before.

The three places that expand ``{{text}}``/``{{words}}`` (Python, the LIVE page
and the Remotion component) only peel the suffix off and put it on the caption
node as ``data-cue-marks``. ``renderer/src/webThemeClock.js`` groups the real
characters; nothing here or there can add, drop or change a character.
"""
import json
import re

SEPARATOR = '\x01'
_FLAGS = (('bold', 'wt-b'), ('italic', 'wt-i'), ('highlight', 'wt-hl'), ('strike', 'wt-s'))
_COLOR = re.compile(r'#[0-9a-fA-F]{6}')
_FONT = re.compile(r'[\w \-぀-ヿ一-鿿]{1,60}')


def theme_marks(text, marks):
    """Resolved runs as ``[start, end, classes, colour, font]`` in code points."""
    if not marks:
        return []
    from ..caption_style.text_marks import heading_level, runs
    rows = []
    for start, end, attrs in runs(str(text or ''), marks):
        classes = [name for key, name in _FLAGS if attrs.get(key) is True]
        level = heading_level(attrs)
        if level:
            classes.append(f'wt-h{level}')
        color = attrs.get('color') if isinstance(attrs.get('color'), str) and _COLOR.fullmatch(attrs['color']) else ''
        font = attrs.get('font') if isinstance(attrs.get('font'), str) and _FONT.fullmatch(attrs['font']) else ''
        if not (classes or color or font):
            continue
        row = [start, end, ' '.join(classes), color, font]
        # Neighbouring runs that look the same are one group for the theme.
        if rows and rows[-1][1] == start and rows[-1][2:] == row[2:]:
            rows[-1][1] = end
        else:
            rows.append(row)
    return rows


def marked_text(text, rows):
    """The text handed to the theme runtime; unchanged when there is nothing to mark."""
    text = str(text or '')
    if not rows or SEPARATOR in text:
        return text
    return text + SEPARATOR + json.dumps(rows, ensure_ascii=False, separators=(',', ':'))


def split_marked(text):
    """``(plain text, marks json or '')``; malformed suffixes are dropped, never shown."""
    plain, found, raw = str(text or '').partition(SEPARATOR)
    if not found:
        return plain, ''
    try:
        rows = json.loads(raw)
    except ValueError:
        return plain, ''
    return plain, raw if isinstance(rows, list) and rows else ''


def marks_attribute(raw):
    if not raw:
        return ''
    return ' data-cue-marks="' + raw.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;') + '"'
