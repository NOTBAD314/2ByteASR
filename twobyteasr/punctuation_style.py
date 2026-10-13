"""Punctuation style for preview, burn-in and every subtitle export (2026-10-13).

The manuscript (``cue.text``) is never rewritten by this module. A project
stores one choice in ``studio_state['punctuation']``:

* ``original`` — 保留原文: the text exactly as recognized and edited (also
  what an older project without the key gets, so nothing changes on upgrade);
* ``add``      — 添加标点: pause spaces between Chinese/Japanese characters
  become ，/、 and each subtitle ends with 。 (or ``.`` for Latin-only text).
  This is a free local inference from the pauses already in the text, not a
  language model; existing marks are kept;
* ``none``     — 不加标点: general sentence marks (，。、；：！？… and their
  ASCII forms) are removed. Removed marks between words become one space so
  the pause stays visible and English words never run together.

Symbols with meaning are protected in every mode: decimals and thousands
(3.14, 1,000), times (12:30), versions (v1.2.3), negative numbers, URLs,
e-mail addresses, abbreviations (U.S., e.g.), apostrophes and hyphens inside
words, symbols inside names (Node.js, AT&T, C++), and glossary terms passed in
``protected_terms``. Digits, numerals (一个 stays 一个), letter case and line
breaks are never changed. Applying a style twice gives the same text.

``StyledText.index_map`` maps every manuscript character index to its index in
the styled text (``None`` when removed), so word timings that point into the
manuscript can be shown against the styled text.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

MODE_ORIGINAL = 'original'
MODE_ADD = 'add'
MODE_NONE = 'none'
MODES = (MODE_ORIGINAL, MODE_ADD, MODE_NONE)
STATE_KEY = 'punctuation'
MODE_LABELS = {MODE_ORIGINAL: '保留原文', MODE_ADD: '添加标点', MODE_NONE: '不加标点'}
MODE_HINTS = {
    MODE_ORIGINAL: '照原文输出',
    MODE_ADD: '停顿处加逗号，句末加句号',
    MODE_NONE: '去掉语句标点，用空格分开',
}

# General sentence marks (句读). Quotes, brackets, 《》, ·, ～ and dashes are
# not removed: they carry names, titles or tone.
SENTENCE_MARKS = frozenset('，。、；：！？,.;:!?｡､…')
TERMINAL_MARKS = frozenset('。！？.!?…｡')
CLOSERS = frozenset('”’」』）)】]》〉"\'')
SPACES = frozenset(' 　')

_PROTECTED = (
    re.compile(r'(?:https?://|www\.)[^\s，。！？；：、“”「」（）()<>]+', re.IGNORECASE),
    re.compile(r'[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+'),
    re.compile(r'(?<![\w.])[vV]?\d+(?:[.,:：]\d+)+%?'),           # 3.14 1,000 12:30 v1.2.3
    re.compile(r'(?<![\w\d])[-−]\d+(?:\.\d+)?%?'),                 # -5  −3.5
    re.compile(r'\b(?:[A-Za-z]\.){2,}'),                          # U.S.A.  e.g.
    re.compile(r'\b(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|vs|etc|No|Vol|Ep|Lv|ver)\.(?=\s|$|[A-Za-z0-9])', re.IGNORECASE),
    re.compile(r"[A-Za-z0-9]+(?:['’&+#/_.\-][A-Za-z0-9]+)+[+#]*"),  # don't  Node.js  AT&T  R&D
    re.compile(r'\b[A-Za-z][+#]{1,2}(?![A-Za-z0-9])'),             # C++  C#  F#
)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (0x3040 <= code <= 0x30FF or 0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF
            or 0xF900 <= code <= 0xFAFF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F
            or 0x20000 <= code <= 0x2FA1F)


def _is_kana(char: str) -> bool:
    code = ord(char)
    return 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F


def text_language(text: str, hint: str = '') -> str:
    """'ja', 'zh' or 'en' for one subtitle; kana decides Japanese."""
    if any(_is_kana(ch) for ch in text):
        return 'ja'
    if any(_is_cjk(ch) for ch in text):
        return 'ja' if hint == 'ja' else 'zh'
    return 'en'


@dataclass
class StyledText:
    text: str
    index_map: list = field(default_factory=list)   # manuscript index -> styled index or None
    changed: bool = False


def _protected_mask(text: str, terms=()) -> list[bool]:
    mask = [False] * len(text)
    for pattern in _PROTECTED:
        for match in pattern.finditer(text):
            for index in range(match.start(), match.end()):
                mask[index] = True
    for term in terms or ():
        term = str(term or '')
        if not term or not any(ch in SENTENCE_MARKS or not ch.isalnum() for ch in term):
            continue  # a term without symbols needs no protection
        start = text.find(term)
        while start >= 0:
            for index in range(start, start + len(term)):
                mask[index] = True
            start = text.find(term, start + len(term))
    return mask


def _identity(text: str) -> StyledText:
    return StyledText(text, list(range(len(text))), False)


def strip_sentence_punctuation(text: str, *, protected_terms=()) -> StyledText:
    """不加标点: remove sentence marks outside protected spans."""
    text = str(text or '')
    mask = _protected_mask(text, protected_terms)
    out: list[str] = []
    mapping: list = [None] * len(text)
    index = 0
    while index < len(text):
        char = text[index]
        if char in SENTENCE_MARKS and not mask[index]:
            end = index
            while end < len(text) and text[end] in SENTENCE_MARKS and not mask[end]:
                end += 1
            # Never let removal glue two words together: keep (at most) one space.
            before = out[-1] if out else ''
            after = text[end] if end < len(text) else ''
            if before and after and before not in SPACES and after not in SPACES and before != '\n' and after != '\n':
                out.append(' ')
            index = end
            continue
        if char in SPACES and out and out[-1] in SPACES:
            index += 1  # one space is enough
            continue
        mapping[index] = len(out)
        out.append(char)
        index += 1
    styled = ''.join(out)
    # Spaces at line edges carry no pause.
    lines = styled.split('\n')
    trimmed = '\n'.join(line.strip(' 　') for line in lines)
    if trimmed != styled:
        mapping = _remap_after_trim(styled, trimmed, mapping)
        styled = trimmed
    return StyledText(styled, mapping, styled != text)


def _remap_after_trim(before: str, after: str, mapping: list) -> list:
    """Map indices of ``before`` to ``after`` where only edge spaces were removed."""
    position = {}
    j = 0
    for i, char in enumerate(before):
        if j < len(after) and after[j] == char:
            position[i] = j
            j += 1
    return [position.get(value) if value is not None else None for value in mapping]


def add_pause_punctuation(text: str, *, language: str = '', protected_terms=()) -> StyledText:
    """添加标点: pause spaces between CJK characters become ，/、; a final 。 or ."""
    text = str(text or '')
    if not text.strip():
        return _identity(text)
    lang = text_language(text, language)
    comma = '、' if lang == 'ja' else '，'
    mask = _protected_mask(text, protected_terms)
    out: list[str] = []
    mapping: list = [None] * len(text)
    for index, char in enumerate(text):
        if char in SPACES and not mask[index]:
            before = next((text[k] for k in range(index - 1, -1, -1) if text[k] not in SPACES), '')
            after = next((text[k] for k in range(index + 1, len(text)) if text[k] not in SPACES), '')
            if before and after and before != '\n' and after != '\n':
                if _is_cjk(before) and _is_cjk(after):
                    if not out or out[-1] != comma:
                        out.append(comma)
                    continue
                if before in SENTENCE_MARKS and _is_cjk(after):
                    continue  # "好！ 我们" -> "好！我们"
        mapping[index] = len(out)
        out.append(char)
    styled = ''.join(out)
    tail = styled.rstrip(' 　\n')
    last_source = len(text.rstrip(' 　\n')) - 1
    if tail and last_source >= 0:
        last = tail[-1]
        # A Latin line ending in a URL, version or e-mail gets no '.' (it would
        # read as part of it); a full-width 。 is never ambiguous.
        ambiguous = lang == 'en' and mask[last_source]
        if last not in SENTENCE_MARKS and last not in CLOSERS and (last.isalnum() or _is_cjk(last)) and not ambiguous:
            end_mark = '。' if lang in {'zh', 'ja'} else '.'
            styled = tail + end_mark + styled[len(tail):]
    return StyledText(styled, mapping, styled != text)


def style_text(text: str, mode: str, *, language: str = '', protected_terms=()) -> StyledText:
    mode = mode if mode in MODES else MODE_ORIGINAL
    if mode == MODE_NONE:
        return strip_sentence_punctuation(text, protected_terms=protected_terms)
    if mode == MODE_ADD:
        return add_pause_punctuation(text, language=language, protected_terms=protected_terms)
    return _identity(str(text or ''))


# ----------------------------------------------------------------- project

def mode_from_state(state) -> str:
    value = (state or {}).get(STATE_KEY) if isinstance(state, dict) else None
    mode = value.get('mode') if isinstance(value, dict) else value
    return mode if mode in MODES else MODE_ORIGINAL


def project_mode(project) -> str:
    return mode_from_state(getattr(project, 'studio_state', None) or {})


def state_value(mode: str) -> dict:
    return {'mode': mode if mode in MODES else MODE_ORIGINAL, 'version': 1}


def protected_terms_of(project) -> tuple[str, ...]:
    """Glossary spellings recorded in the project (kept exactly as written)."""
    metadata = getattr(project, 'generation_metadata', None) or {}
    terms = []
    for key in ('canonical_terms', 'glossary_terms'):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, (list, tuple)):
            terms.extend(str(item) for item in value if isinstance(item, str))
    return tuple(dict.fromkeys(terms))


def _language_hint(project) -> str:
    try:
        from .language_rules import project_language
        return project_language(project) or ''
    except Exception:
        return ''


def _with_text(cue, text: str):
    """A copy of ``cue`` carrying ``text`` (frozen render DTOs included)."""
    import dataclasses
    params = getattr(type(cue), '__dataclass_params__', None)
    if params is not None and params.frozen:
        return dataclasses.replace(cue, text=text)
    copied = copy.copy(cue)
    copied.text = text
    return copied


def style_cues(project, cues, *, mode: str | None = None) -> list:
    """Copies of ``cues`` with the project's (or the given) style applied."""
    mode = project_mode(project) if mode is None else mode
    cues = list(cues)
    if mode == MODE_ORIGINAL:
        return cues
    hint = _language_hint(project)
    terms = protected_terms_of(project)
    out = []
    for cue in cues:
        styled = style_text(cue.text, mode, language=hint, protected_terms=terms)
        if styled.changed:
            cue = _with_text(cue, styled.text)
        out.append(cue)
    return out


def style_cues_for_state(state, cues, *, language: str = '', metadata=None) -> list:
    """Same as :func:`style_cues` for worker DTOs that carry a state mapping only."""
    mode = mode_from_state(state)
    cues = list(cues)
    if mode == MODE_ORIGINAL:
        return cues
    holder = type('_Holder', (), {})()
    holder.studio_state = state
    holder.generation_metadata = metadata or {}
    terms = protected_terms_of(holder)
    out = []
    for cue in cues:
        styled = style_text(cue.text, mode, language=language, protected_terms=terms)
        if styled.changed:
            cue = _with_text(cue, styled.text)
        out.append(cue)
    return out


def style_translation(text: str, mode: str) -> str:
    """Translations already come punctuated; only 不加标点 changes them."""
    if mode != MODE_NONE:
        return str(text or '')
    return strip_sentence_punctuation(text).text


def style_translations(state, translations):
    mode = mode_from_state(state)
    if mode != MODE_NONE or not translations:
        return translations
    return {key: style_translation(value, mode) for key, value in dict(translations).items()}


def preview_rows(project=None, mode: str = MODE_ADD, limit: int = 3) -> list[tuple[str, str]]:
    """(manuscript, styled) pairs for the choice preview: real cues when there
    are any, otherwise built-in examples that show the protected symbols."""
    rows = []
    if project is not None:
        hint = _language_hint(project)
        terms = protected_terms_of(project)
        for cue in list(getattr(project, 'cues', []) or [])[:200]:
            if not str(cue.text or '').strip():
                continue
            styled = style_text(cue.text, mode, language=hint, protected_terms=terms)
            rows.append((cue.text, styled.text))
            if len(rows) >= limit:
                break
    if not rows:
        samples = ('大家好 今天来玩 v1.2.3 版本 胜率提升到 98.5% 了', '真的吗？我们上 bilibili.com 看看，好不好。',
                   "It's 12:30 now, see you at the U.S. server!")
        rows = [(sample, style_text(sample, mode).text) for sample in samples[:limit]]
    return rows


def default_mode_for_new_tasks(settings: dict) -> str:
    value = ((settings or {}).get('switches') or {}).get('subtitle_punctuation')
    return value if value in MODES else MODE_ORIGINAL
