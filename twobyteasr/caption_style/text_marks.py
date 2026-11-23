"""Plain caption text is authoritative. Markdown is an explicit input codec.

Ranges use Python Unicode offsets on grapheme boundaries, never Markdown or
UTF-16 offsets. ==highlight== is a 2ByteASR extension. No acoustic times live here.

2026-11-20 (user): ~~strike~~ (also --strike--) and line headings ``# `` to
``###### `` join the grammar. A heading is a mark ``heading: 1..6`` over its
line's text; renderers scale the line by ``heading_scale`` and draw it bold.
"""
from copy import deepcopy
from difflib import SequenceMatcher
from functools import lru_cache

# ``font`` (a family name) is display-only: speaker-name prefixes use it, and
# no Markdown token or editor command writes it.
MARK_FIELDS = frozenset(('bold', 'italic', 'highlight', 'strike', 'heading', 'color', 'font'))

# Markdown heading level -> type size against the caption's own size. Levels 5
# and 6 are smaller than body text, as in Markdown; every heading is bold.
HEADING_SCALES = {1: 1.6, 2: 1.4, 3: 1.25, 4: 1.12, 5: 0.9, 6: 0.78}
_ESCAPABLE = '*=\\`~-#'


def heading_level(attrs):
    try:
        level = int(attrs.get('heading') or 0)
    except (TypeError, ValueError):
        return 0
    return level if level in HEADING_SCALES else 0


def heading_scale(attrs):
    return HEADING_SCALES.get(heading_level(attrs), 1.0)


def translation_text_override(cue, previous_text, next_text):
    """Preserve local presentation while committing a new translation body."""
    override = deepcopy(cue.appearance_override)
    previous_text = str((override.get('translation_group') or {}).get('text') or previous_text or '')
    if previous_text != str(next_text or ''):
        marks = layer_marks(cue, 'translation')
        if marks:
            override = with_marks(cue, remap_marks(previous_text, str(next_text or ''), marks), 'translation')
        override.pop('translation_group', None)
    return override


def unencoded_marks(marks):
    """Retain color and explicit suppression: neither has a Markdown token."""
    result=[]
    for mark in marks:
        attrs={k:v for k,v in mark.items() if k=='color' or k in MARK_FIELDS and v is False}
        if attrs:result.append(dict(start=mark['start'],end=mark['end'],**attrs))
    return result


def utf16_offset(text, index):
    return len(text[:index].encode('utf-16-le')) // 2


def python_offset(text, index):
    return len(text.encode('utf-16-le')[:max(0, index)*2].decode('utf-16-le', errors='ignore'))


@lru_cache(maxsize=4096)
def boundaries(text):
    from PySide6.QtCore import QTextBoundaryFinder
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    result = [0]
    while True:
        index = finder.toNextBoundary()
        if index < 0:
            break
        result.append(python_offset(text, index))
    return tuple(dict.fromkeys(result + [len(text)]))


def normalize_marks(text, marks):
    edges = boundaries(text)
    result = []
    for mark in marks or ():
        if not isinstance(mark, dict):
            continue
        try:
            a, b = int(mark.get('start', 0)), int(mark.get('end', 0))
        except (ValueError, TypeError, OverflowError):
            continue
        # Expand explicit selection to whole graphemes; never cut a ZWJ/combining cluster.
        a = max((x for x in edges if x <= a), default=0)
        b = min((x for x in edges if x >= b), default=len(text))
        attrs = {k: deepcopy(v) for k, v in mark.items() if k in MARK_FIELDS}
        if a < b and attrs:
            result.append(dict(start=a, end=b, **attrs))
    return result


def remap_marks(before, after, marks):
    """Keep only unchanged text identities. Insertions/replacements inherit nothing."""
    if not marks:
        return []
    if before == after:
        return normalize_marks(after, marks)
    if len(before) == len(after):
        from ..subtitle_rules.chinese_script import fold
        if all(a.casefold() == b.casefold() or fold(a) == fold(b) for a,b in zip(before,after)):
            return normalize_marks(after,marks)
    blocks = SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks()
    result = []
    for mark in normalize_marks(before, marks):
        token = before[mark['start']:mark['end']]
        if max(before.count(token),after.count(token)) > 1 and before.count(token) != after.count(token):
            continue  # No editor delta: do not attach a repeated word's mark to the wrong occurrence.
        for a, b, size in blocks:
            lo, hi = max(a, mark['start']), min(a+size, mark['end'])
            if lo < hi:
                result.append(dict(mark, start=b+lo-a, end=b+hi-a))
    return normalize_marks(after, result)


def remapped_override(cue, text):
    value = deepcopy(cue.appearance_override)
    old = layer_marks(cue)
    if old:
        marks = remap_marks(cue.text,text,old)
        value['text_marks'] = marks
        if sum(m['end']-m['start'] for m in marks) < sum(m['end']-m['start'] for m in old):
            value['text_marks_review'] = '文字修改后已移除无法可靠对应的局部标记'
    return value


def remap_caption_marks(source, caption, marks):
    """Map decoration ranges through known layout insertions without guessing.

    Generic edit matching must reject ambiguous repeated phrases. Layout has
    exact source ranges, so wrapping an emphasized repeated phrase is not an
    edit and must not silently remove its marks.
    """
    layout = getattr(caption, 'layout', {})
    lines = layout.get('lines', []) if isinstance(layout, dict) else []
    if not lines:
        return remap_marks(source, caption.text, marks)
    result = []
    for mark in normalize_marks(source, marks):
        for line in lines:
            start = max(mark['start'], line['sourceStart'])
            end = min(mark['end'], line['sourceEnd'])
            if start < end:
                result.append(dict(mark, start=line['displayStart']+start-line['sourceStart'],
                                   end=line['displayStart']+end-line['sourceStart']))
    return result


def edit_marks(before, after, marks, start, end, replacement_end):
    """Rebase an editor's exact edit, including repeated identical words."""
    if before[:start]+after[start:replacement_end]+before[end:] != after:
        return remap_marks(before, after, marks)
    delta = replacement_end-end
    result = []
    for mark in normalize_marks(before, marks):
        if mark['start'] < start:
            result.append(dict(mark, end=min(mark['end'],start)))
        if mark['end'] > end:
            result.append(dict(mark, start=max(mark['start'],end)+delta, end=mark['end']+delta))
    return normalize_marks(after,result)


def parse_markdown(source):
    """A bounded inline grammar. Unmatched delimiters stay editable/literal.

    A line starting with 1-6 ``#`` and a space is a heading; the inline marks
    inside it still apply. ``--x--`` is the same strike as ``~~x~~``.
    """
    source = str(source)
    chars, marks, source_positions = [], [], []
    names = {'***': 'bold', '**': 'bold', '*': 'italic', '==': 'highlight', '~~': 'strike', '--': 'strike'}

    def closing(token, start, end):
        pos = start
        while pos < end:
            if source[pos] == '\\':
                pos += 2
                continue
            if source.startswith(token, pos):
                return pos
            pos += 1
        return -1

    def heading_at(pos, end):
        if pos and source[pos-1] != '\n':
            return 0, pos
        level = 0
        while pos+level < end and source[pos+level] == '#' and level < 7:
            level += 1
        if 1 <= level <= 6 and pos+level < end and source[pos+level] in ' \u3000':
            return level, pos+level+1
        return 0, pos

    def scan(start, end, depth=0):
        pos = start
        while pos < end:
            if depth == 0:
                level, body = heading_at(pos, end)
                if level:
                    stop = source.find('\n', body, end)
                    stop = end if stop < 0 else stop
                    a = len(chars)
                    scan(body, stop, 1)
                    if len(chars) > a:
                        marks.append({'start': a, 'end': len(chars), 'heading': level})
                    pos = stop
                    continue
            if source[pos] == '\\' and pos+1 < end and source[pos+1] in _ESCAPABLE:
                chars.append(source[pos+1]); source_positions.append(pos+1); pos += 2
                continue
            token = next((v for v in ('***', '**', '==', '~~', '--', '*', '`') if source.startswith(v, pos)), '')
            stop = closing(token, pos+len(token), end) if token and depth < 32 else -1
            if stop > pos+len(token):
                a = len(chars)
                if token == '`':
                    chars.extend(source[pos+1:stop]); source_positions.extend(range(pos+1, stop))
                else:
                    scan(pos+len(token), stop, depth+1)
                    marks.append({'start': a, 'end': len(chars), names[token]: True})
                if token == '***': marks[-1]['italic'] = True
                pos = stop+len(token)
            else:
                chars.append(source[pos]); source_positions.append(pos); pos += 1
    scan(0, len(source))
    text = ''.join(chars)
    return text, normalize_marks(text, marks), source_positions


def runs(text, marks):
    marks = normalize_marks(text, marks)
    edges = sorted({0, len(text), *(m[k] for m in marks for k in ('start','end'))})
    result = []
    for a, b in zip(edges, edges[1:]):
        attrs = {}
        for mark in marks:
            if mark['start'] <= a and b <= mark['end']:
                attrs.update({k:v for k,v in mark.items() if k in MARK_FIELDS})
        result.append((a, b, attrs))
    return result


def _escape_markdown(value, line_start):
    out = []
    for index, char in enumerate(value):
        doubled = char in '~-' and ((index+1 < len(value) and value[index+1] == char)
                                    or (index and value[index-1] == char))
        leading = char == '#' and (value[index-1] == '\n' if index else line_start)
        out.append('\\'+char if char in '*=\\`' or doubled or leading else char)
    return ''.join(out)


def _inline_markdown(text, a, b, attrs):
    value = _escape_markdown(text[a:b], a == 0 or text[a-1] == '\n')
    for key, token in (('italic','*'), ('bold','**'), ('highlight','=='), ('strike', '~~')):
        if attrs.get(key):
            value = token+value+token
    return value


def markdown_text(text, marks):
    marks = normalize_marks(text, marks)
    headings = [m for m in marks if heading_level(m)]
    if not headings:
        return ''.join(_inline_markdown(text, a, b, attrs) for a, b, attrs in runs(text, marks))
    # Headings are whole lines, so inline tokens close at each line end and a
    # covered line starts with its ``#`` prefix.
    inline = [m for m in marks if not heading_level(m) or set(m) - {'start', 'end', 'heading'}]
    inline = [{k: v for k, v in m.items() if k != 'heading'} for m in inline]
    shown, offset = [], 0
    for line in text.split('\n'):
        end = offset+len(line)
        pieces = [(max(a, offset), min(b, end), attrs) for a, b, attrs in runs(text, inline)
                  if a < end and b > offset]
        value = ''.join(_inline_markdown(text, a, b, attrs) for a, b, attrs in pieces)
        level = next((heading_level(m) for m in headings
                      if line and m['start'] <= offset and end <= m['end']), 0)
        shown.append('#'*level+' '+value if level else value)
        offset = end+1
    return '\n'.join(shown)


def layer_marks(cue, layer='original'):
    from collections.abc import Mapping
    data = cue.appearance_override
    if not isinstance(data, Mapping):
        from ..projects.studio_revisions import thaw_json
        data = thaw_json(data) or {}
    if layer == 'translation':
        data = data.get('translation', {})
    return data.get('text_marks', [])


def with_marks(cue, marks, layer='original'):
    value = deepcopy(cue.appearance_override)
    target = value.setdefault('translation', {}) if layer == 'translation' else value
    target['text_marks'] = deepcopy(marks)
    return value
