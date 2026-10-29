"""Inline math in captions shown as readable Unicode text (2026-10-16, ADR 0124).

A caption may contain ``$…$`` formulas written in LaTeX (``$\\int_0^1 x^2\\,dx$``).
The manuscript (``cue.text``) keeps that source. When a project turns the switch
``studio_state['math_formulas']`` on, preview, burn-in and every subtitle export
show the formula as Unicode text instead (``∫₀¹ x² dx``); the punctuation style
module applies it together with the punctuation choice, so every drawn or
exported path agrees. A formula that cannot be converted (an unknown or
misspelled command, a matrix) is shown exactly as written, ``$`` included.

Delimiters follow the usual Markdown rule so prices are not taken for math:
an opening ``$`` is followed by a non-space, a closing ``$`` is preceded by a
non-space and not followed by a digit; ``\\$`` is a dollar sign; ``$$`` and an
unclosed ``$`` stay as written. Spaces inside a converted formula become
no-break spaces so line wrapping keeps the formula on one line.

Structure (scripts, fractions, roots, binomials, operators with limits) is
converted here; symbols come from pylatexenc's tables (MIT, imported lazily).
"""
from __future__ import annotations

import re
from functools import lru_cache

STATE_KEY = 'math_formulas'
NBSP = ' '

SUP = dict(zip('0123456789+-=()niT', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵀ'))
SUB = dict(zip('0123456789+-=()aeoxijklmnprstuv', '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓᵢⱼₖₗₘₙₚᵣₛₜᵤᵥ'))
SUP['−'], SUB['−'] = '⁻', '₋'
DOUBLE_STRUCK = {'R': 'ℝ', 'N': 'ℕ', 'Z': 'ℤ', 'Q': 'ℚ', 'C': 'ℂ', 'P': 'ℙ'}
FUNCTIONS = frozenset({'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'log', 'ln', 'lg', 'exp', 'max', 'min', 'det',
                       'gcd', 'arg', 'deg', 'dim', 'sinh', 'cosh', 'tanh', 'arcsin', 'arccos', 'arctan'})
LIMIT_OPERATORS = {'sum': '∑', 'prod': '∏', 'bigcup': '⋃', 'bigcap': '⋂'}
INTEGRALS = {'int': '∫', 'iint': '∬', 'iiint': '∭', 'oint': '∮'}
SPACING = {',': ' ', ';': ' ', ':': ' ', '>': ' ', 'quad': ' ', 'qquad': ' ', ' ': ' ', '!': ''}
IGNORED = frozenset({'displaystyle', 'textstyle', 'scriptstyle', 'limits', 'nolimits', 'left', 'right',
                     'big', 'Big', 'bigg', 'Bigg', 'bigl', 'bigr', 'Bigl', 'Bigr'})
TEXTLIKE = frozenset({'text', 'mathrm', 'mathit', 'mathbf', 'mathsf', 'textbf', 'textit', 'operatorname',
                      'boldsymbol'})
GEOMETRY = {'triangle': '△', 'square': '□', 'parallel': '∥', 'perp': '⊥'}
ESCAPED = frozenset('{}%$&#_')
RELATIONS = '=≠≤≥≈≡<>→⇒⇔∈∉⊂⊆∼≅∝'
BINARY = '×·∪∩÷∧∨⊕⊗'


class _Unsupported(Exception):
    pass


# ----------------------------------------------------------------- switch

def enabled_from_state(state) -> bool:
    value = state.get(STATE_KEY) if isinstance(state, dict) else None
    return bool(value.get('enabled')) if isinstance(value, dict) else value is True


def project_enabled(project) -> bool:
    return enabled_from_state(getattr(project, 'studio_state', None) or {})


def state_value(enabled: bool) -> dict:
    return {'enabled': bool(enabled), 'version': 1}


# ----------------------------------------------------------------- spans

def math_spans(text: str) -> list[tuple[int, int, str | None]]:
    """``(start, end, body)`` for every ``$…$`` formula and ``(start, end, None)``
    for every ``\\$`` escape, in order; ``end`` is exclusive."""
    text = str(text or '')
    spans: list[tuple[int, int, str | None]] = []
    index, size = 0, len(text)
    while index < size:
        char = text[index]
        if char == '\\' and text.startswith('\\$', index):
            spans.append((index, index + 2, None))
            index += 2
            continue
        if char != '$' or text.startswith('$$', index):
            index += 2 if text.startswith('$$', index) else 1
            continue
        if index + 1 >= size or text[index + 1].isspace():
            index += 1
            continue
        close = index + 1
        found = None
        while close < size:
            if text[close] == '\n':
                break
            if text[close] == '\\':
                close += 2
                continue
            if (text[close] == '$' and not text[close - 1].isspace()
                    and not (close + 1 < size and text[close + 1].isdigit())):
                found = close
                break
            close += 1
        if found is None:
            index += 1
            continue
        spans.append((index, found + 1, text[index + 1:found]))
        index = found + 1
    return spans


def protected_mask(text: str) -> list[bool]:
    """True for every character inside a formula or ``\\$`` escape."""
    mask = [False] * len(str(text or ''))
    for start, end, _body in math_spans(text):
        for position in range(start, end):
            mask[position] = True
    return mask


# ----------------------------------------------------------------- formula

@lru_cache(maxsize=1)
def _parser():
    from pylatexenc import latexwalker
    from pylatexenc.latex2text import LatexNodes2Text, get_default_latex_context_db
    from pylatexenc.macrospec import MacroSpec

    context = latexwalker.get_default_latex_context_db()
    context.add_context_category('2byteasr-math', prepend=True, macros=[
        MacroSpec('binom', '{{'), MacroSpec('dbinom', '{{'), MacroSpec('dfrac', '{{'), MacroSpec('tfrac', '{{'),
        MacroSpec('operatorname', '{'), MacroSpec('pmod', '{'), MacroSpec('boldsymbol', '{'),
        MacroSpec('mathbb', '{'),
    ])
    return latexwalker, context, LatexNodes2Text(), get_default_latex_context_db()


def _tokens(nodes):
    latexwalker = _parser()[0]
    for node in nodes or []:
        if node is None or node.isNodeType(latexwalker.LatexCommentNode):
            continue
        if node.isNodeType(latexwalker.LatexCharsNode):
            yield from (('char', char) for char in node.chars)
        elif node.isNodeType(latexwalker.LatexGroupNode):
            yield ('group', node.nodelist)
        elif node.isNodeType(latexwalker.LatexMacroNode):
            yield ('macro', node)
        elif node.isNodeType(latexwalker.LatexSpecialsNode):
            yield from (('char', char) for char in node.specials_chars)
        else:  # environments (matrices), nested math: shown as written
            raise _Unsupported(type(node).__name__)


def _arguments(node):
    return [argument for argument in (node.nodeargd.argnlist if node.nodeargd else []) if argument is not None]


def _inner(argument):
    latexwalker = _parser()[0]
    return argument.nodelist if argument.isNodeType(latexwalker.LatexGroupNode) else [argument]


def _script(text: str, table: dict, mark: str) -> str:
    if text and all(char in table for char in text):
        return ''.join(table[char] for char in text)
    if text == '∘':
        return '°' if mark == '^' else '_∘'
    return f'{mark}{text}' if len(text) == 1 else f'{mark}({text})'


def _operand(text: str) -> str:
    """A fraction or root operand, in parentheses when it is not one term."""
    plain = text.strip()
    if ' ' not in plain and not re.search(r'[+\-−=/×·]', plain):
        return plain
    return f'({plain})'


def _render(nodes) -> str:
    tokens = list(_tokens(nodes))
    out: list[str] = []
    index = 0

    def atom(position):
        if position >= len(tokens):
            raise _Unsupported('script without operand')
        kind, value = tokens[position]
        if kind == 'char':
            return value, position + 1
        if kind == 'group':
            return _render(value).strip(), position + 1
        return _macro(value, tokens, position).strip(), position + 1

    while index < len(tokens):
        kind, value = tokens[index]
        if kind == 'char' and value in '^_':
            text, index = atom(index + 1)
            out.append(_script(text, SUP if value == '^' else SUB, value))
            continue
        name = value.macroname if kind == 'macro' else ''
        if name in LIMIT_OPERATORS or name in INTEGRALS or name == 'lim':
            index += 1
            lower = upper = None
            while index < len(tokens) and tokens[index][0] == 'char' and tokens[index][1] in '^_':
                mark = tokens[index][1]
                text, index = atom(index + 1)
                if mark == '_':
                    lower = text
                else:
                    upper = text
            if name == 'lim':
                out.append(f'lim({lower}) ' if lower else 'lim ')
            elif name in INTEGRALS and all(char in SUB for char in lower or '') \
                    and all(char in SUP for char in upper or ''):
                out.append(INTEGRALS[name] + _script(lower or '', SUB, '_') * bool(lower)
                           + _script(upper or '', SUP, '^') * bool(upper) + ' ')
            else:
                symbol = LIMIT_OPERATORS.get(name) or INTEGRALS[name]
                if lower or upper:
                    out.append(f"{symbol}({lower or ''}…{upper}) " if upper else f'{symbol}({lower}) ')
                else:
                    out.append(symbol + ' ')
            continue
        if kind == 'char':
            out.append(value)
        elif kind == 'group':
            out.append(_render(value))
        else:
            out.append(_macro(value, tokens, index))
        index += 1
    return ''.join(out)


def _macro(node, tokens, index) -> str:
    name = node.macroname
    arguments = _arguments(node)
    follower = tokens[index + 1] if index + 1 < len(tokens) else None
    if name in ('frac', 'dfrac', 'tfrac'):
        numerator, denominator = (_render(_inner(argument)).strip() for argument in arguments[:2])
        text = f'{_operand(numerator)}/{_operand(denominator)}'
        # (√3/4)a²: a fraction directly followed by a term reads as one factor.
        if follower and not (follower[0] == 'char' and (follower[1].isspace() or follower[1] in '+-=,)]')):
            text = f'({text})'
        return text
    if name == 'sqrt':
        latexwalker = _parser()[0]
        degree = [a for a in arguments if a.isNodeType(latexwalker.LatexGroupNode) and a.delimiters[0] == '[']
        body = [a for a in arguments if a not in degree]
        radicand = _operand(_render(_inner(body[-1])))
        if not degree:
            return '√' + radicand
        order = _render(degree[0].nodelist).strip()
        sign = {'3': '∛', '4': '∜'}.get(order) or _script(order, SUP, '^') + '√'
        return sign + radicand
    if name in ('binom', 'dbinom'):
        top, bottom = (_render(_inner(argument)).strip() for argument in arguments[:2])
        return f'C({top},{bottom})'
    if name == 'bmod':
        return ' mod '
    if name == 'pmod':
        return f' (mod {_render(_inner(arguments[0])).strip()})'
    if name == 'mathbb':
        return ''.join(DOUBLE_STRUCK.get(char, char) for char in _render(_inner(arguments[0])).strip())
    if name in TEXTLIKE:
        return _render(_inner(arguments[0])) if arguments else ''
    if name in IGNORED:
        return ''
    if name in FUNCTIONS:
        return name if follower and follower[0] == 'char' and follower[1] in '^_' else name + ' '
    if name in GEOMETRY:
        return GEOMETRY[name]
    if name in ('circ', 'degree'):
        return '∘' if name == 'circ' else '°'
    if name in ('ldots', 'dots'):
        return '…'
    if name == 'cdots':
        return '⋯'
    if name in SPACING:
        return SPACING[name]
    if name in ESCAPED:
        return name
    _latexwalker, _context, symbols, known = _parser()
    if known.get_macro_spec(name) is None:
        raise _Unsupported('\\' + name)
    text = symbols.node_to_text(node)
    if not text and not arguments:
        raise _Unsupported(f'\\{name} has no text form')
    return text


def _tidy(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(rf'\s*([{RELATIONS}{BINARY}])\s*', r' \1 ', text)
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    return re.sub(r'\s+', ' ', text).strip()


@lru_cache(maxsize=4096)
def formula_to_unicode(body: str) -> str | None:
    """Readable Unicode for one formula body, or ``None`` when it stays as written."""
    latexwalker, context, _symbols, _known = _parser()
    try:
        walker = latexwalker.LatexWalker(str(body), latex_context=context, tolerant_parsing=False)
        nodes, _position, _length = walker.get_latex_nodes(
            parsing_state=walker.make_parsing_state(in_math_mode=True))
        text = _tidy(_render(nodes))
    except (_Unsupported, latexwalker.LatexWalkerError, IndexError, AttributeError, ValueError):
        return None
    return text.replace(' ', NBSP) if text else None


def convert(text: str) -> tuple[str, list, bool]:
    """``(converted, index_map, changed)``: ``index_map[i]`` is where character
    ``i`` of ``text`` ended up, ``None`` inside a converted formula."""
    text = str(text or '')
    out: list[str] = []
    length = 0  # characters written so far (a converted formula is one multi-character piece)
    mapping: list = [None] * len(text)
    cursor = 0
    changed = False

    def keep(start, end):
        nonlocal length
        for position in range(start, end):
            mapping[position] = length
            out.append(text[position])
            length += 1

    for start, end, body in math_spans(text):
        keep(cursor, start)
        if body is None:  # \$ -> $
            keep(start + 1, end)
            changed = True
        else:
            converted = formula_to_unicode(body)
            if converted is None:
                keep(start, end)
            else:
                out.append(converted)
                length += len(converted)
                changed = True
        cursor = end
    keep(cursor, len(text))
    return ''.join(out), mapping, changed


def caption_text(text: str) -> str:
    return convert(text)[0]


# ----------------------------------------------------------------- AI requests
#
# 2026-10-16 (ADR 0124, stage 1B): text AI never sees a formula. Each ``$…$``
# becomes ⟦F1⟧, ⟦F2⟧ … before a request and is put back afterwards; an answer
# that drops, repeats or alters a placeholder is not used for that subtitle.
# ⟦ ⟧ survive clean_subtitle_text, which deletes ordinary brackets and braces.

PLACEHOLDER = re.compile(r'⟦F(\d+)⟧')
FORMULA_RULE = ('文本中的 ⟦F1⟧、⟦F2⟧ 等记号代表数学公式，必须逐字原样保留：'
                '不要删除、改写、翻译、移动、合并或拆开它们，修改内容不得包含这些记号。')


def mask_formulas(text: str) -> tuple[str, tuple[str, ...]]:
    """``(masked text, formulas)``; formula ``n`` (1-based) became ⟦Fn⟧. ``\\$`` stays as written."""
    text = str(text or '')
    out: list[str] = []
    formulas: list[str] = []
    cursor = 0
    for start, end, body in math_spans(text):
        if body is None:
            continue
        out.append(text[cursor:start])
        formulas.append(text[start:end])
        out.append(f'⟦F{len(formulas)}⟧')
        cursor = end
    out.append(text[cursor:])
    return ''.join(out), tuple(formulas)


def unmask_formulas(text: str, formulas) -> str | None:
    """Put the formulas back; ``None`` when a placeholder is missing, repeated or unknown."""
    text = str(text or '')
    formulas = tuple(formulas or ())
    found = [int(match.group(1)) for match in PLACEHOLDER.finditer(text)]
    if sorted(found) != list(range(1, len(formulas) + 1)):
        return None
    return PLACEHOLDER.sub(lambda match: formulas[int(match.group(1)) - 1], text)


def has_placeholders(text: str) -> bool:
    return bool(PLACEHOLDER.search(str(text or '')))


__all__ = ['FORMULA_RULE', 'NBSP', 'PLACEHOLDER', 'STATE_KEY', 'caption_text', 'convert', 'enabled_from_state',
           'formula_to_unicode', 'has_placeholders', 'mask_formulas', 'math_spans', 'project_enabled',
           'protected_mask', 'state_value', 'unmask_formulas']
