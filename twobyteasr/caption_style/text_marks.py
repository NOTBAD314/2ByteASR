"""Plain caption text is authoritative. Markdown is an explicit input codec.

Ranges use Python Unicode offsets on grapheme boundaries, never Markdown or
UTF-16 offsets. ==highlight== is a 2ByteASR extension. No acoustic times live here.
"""
from copy import deepcopy
from difflib import SequenceMatcher
from functools import lru_cache

MARK_FIELDS = frozenset(('bold', 'italic', 'highlight', 'color'))


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
    """A bounded inline grammar. Unmatched delimiters stay editable/literal."""
    source = str(source)
    chars, marks, source_positions = [], [], []

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

    def scan(start, end, depth=0):
        pos = start
        while pos < end:
            if source[pos] == '\\' and pos+1 < end and source[pos+1] in '*=\\`':
                chars.append(source[pos+1]); source_positions.append(pos+1); pos += 2
                continue
            token = next((v for v in ('***', '**', '==', '*', '`') if source.startswith(v, pos)), '')
            stop = closing(token, pos+len(token), end) if token and depth < 32 else -1
            if stop > pos+len(token):
                a = len(chars)
                if token == '`':
                    chars.extend(source[pos+1:stop]); source_positions.extend(range(pos+1, stop))
                else:
                    scan(pos+len(token), stop, depth+1)
                    marks.append({'start': a, 'end': len(chars),
                                  {'***':'bold', '**':'bold', '*':'italic', '==':'highlight'}[token]: True})
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


def markdown_text(text, marks):
    parts = []
    for a, b, attrs in runs(text, marks):
        value = ''.join('\\'+c if c in '*=\\`' else c for c in text[a:b])
        for key, token in (('italic','*'), ('bold','**'), ('highlight','==')):
            if attrs.get(key):
                value = token+value+token
        parts.append(value)
    return ''.join(parts)


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
