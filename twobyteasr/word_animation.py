"""Read-only speech timing for caption animation; never invent word timings."""
from __future__ import annotations

import re
from collections.abc import Mapping

from .cue_word_alignment import align_text_to_tokens, cue_words

from .letter_motion import BEAT_MODES, PRESETS, choreograph
from .motion_catalog import RICH_ENTRY, RICH_EXIT

WORD_MODES = frozenset({'word_reveal', 'karaoke_highlight', 'word_current', 'karaoke_wipe'}) | PRESETS.keys() | BEAT_MODES


def word_part(effect):
    if not isinstance(effect, Mapping):
        return {}
    part = effect.get('word_highlight', effect.get('entry', {}))
    return dict(part) if isinstance(part, Mapping) and part.get('type') in WORD_MODES else {}


def needs_word_plan(effect):
    """Word modes, loops and curated entry/exit all ride on per-unit keyframes."""
    if not isinstance(effect, Mapping):
        return False
    return bool(word_part(effect) or effect.get('loop', {}).get('type', 'none') != 'none'
                or effect.get('entry', {}).get('type') in RICH_ENTRY or effect.get('exit', {}).get('type') in RICH_EXIT)


def remap_word_animation(plan, text):
    """Map punctuation/line wrapping changes without moving acoustic intervals."""
    if not plan or not plan.get('spans'):
        return choreograph({**plan, 'text': text}) if plan else {}
    records = [(r['start_ms'], r['end_ms'], r['spoken'], '') for r in plan['spans']]
    offset = plan.get('clock_offset_ms', 0)
    bounds = (-offset, plan.get('original_duration_ms',plan['duration_ms'])-offset)
    words, reason = align_text_to_tokens(text, records, bounds)
    if not words:
        return choreograph({**plan, 'text': text, 'spans': [], 'status': reason})
    # Latin letters measured one at a time still form whole reading words.
    latin = list(re.finditer(r"[A-Za-z0-9]+(?:['’_-][A-Za-z0-9]+)*", text))
    groups = []
    for w in words:
        token = next((m.span() for m in latin if m.start() <= w.char_start and w.char_end <= m.end()), None)
        if groups and token is not None and groups[-1][0] == token:
            groups[-1][1].append(w)
        else:
            groups.append((token, [w]))
    spans = []
    for index, (_, group) in enumerate(groups):
        start = 0 if index == 0 else group[0].char_start
        end = groups[index+1][1][0].char_start if index+1 < len(groups) else len(text)
        spans.append({'char_start': start, 'char_end': end,
                      'start_ms': max(bounds[0], min(bounds[1], group[0].start_ms)),
                      'end_ms': max(bounds[0], min(bounds[1], max(w.end_ms for w in group))),
                      'spoken': ''.join(w.text for w in group)})
    return choreograph({**plan, 'text': text, 'spans': spans, 'status': 'measured'})


def build_word_animation(project, cue, text=None, *, effect=None):
    effect = effect if effect is not None else project.effects.get(cue.effect_id, {})
    part = word_part(effect)
    loop = effect.get('loop', {}).get('type', 'none') != 'none'
    entry, leave = effect.get('entry', {}), effect.get('exit', {})
    rich_entry = dict(entry) if entry.get('type') in RICH_ENTRY else None
    rich_exit = dict(leave) if leave.get('type') in RICH_EXIT else None
    if not part and not loop and not rich_entry and not rich_exit:
        return {}
    words, reason = cue_words(project, cue)
    plan = {'mode': part.get('type', 'line_motion'), 'color': part.get('color', '#4D9FFF' if part.get('type') == 'karaoke_wipe' else '#FFD166') if part else '#FFFFFF',
            'composed_loop': loop,
            'loop_effect': effect.get('loop', {}),
            **({'rich_entry': rich_entry} if rich_entry else {}),
            **({'rich_exit': rich_exit} if rich_exit else {}),
            'entry_ms': (effect.get('entry', {}).get('duration', 180)+effect.get('entry', {}).get('delay', 0)
                         if effect.get('entry', {}).get('type', 'none') not in WORD_MODES | {'none'} else 0),
            'exit_ms': (effect.get('exit', {}).get('duration', 140)+effect.get('exit', {}).get('delay', 0)
                        if effect.get('exit', {}).get('type', 'none') != 'none' else 0),
            'duration_ms': max(1, cue.end_ms-cue.start_ms), 'text': cue.text,
            'status': reason, 'spans': [
                {'char_start': w.char_start, 'char_end': w.char_end, 'spoken': w.text,
                 'start_ms': w.start_ms-cue.start_ms, 'end_ms': w.end_ms-cue.start_ms}
                for w in words]}
    return remap_word_animation(plan, cue.text if text is None else text)


def word_state(plan, milliseconds):
    """Discrete visual state is cacheable between actual speech boundaries."""
    mode = plan.get('mode')
    if plan.get('units'):
        return (round(milliseconds, 2),)
    return tuple(0 if milliseconds < r['start_ms'] else
                 (2 if mode != 'word_current' or milliseconds < r['end_ms'] else 1)
                 for r in plan.get('spans', ()))


def compile_word_ass(plan, text, base_color, *, offset_ms=0):
    from .ass_compiler import escape_ass_text
    from .effect_dsl import _ass_color
    plan = remap_word_animation(plan, text)
    if not plan.get('spans'):
        return escape_ass_text(text)
    result = []
    for span in plan['spans']:
        start, end = span['start_ms']-offset_ms, span['end_ms']-offset_ms
        content = escape_ass_text(text[span['char_start']:span['char_end']])
        if plan['mode'] == 'word_reveal':
            tags = r'\alpha&H00&' if start <= 0 else rf'\alpha&HFF&\t({start},{start+1},\alpha&H00&)'
        else:
            color = _ass_color(plan['color'])
            normal = _ass_color(base_color)
            tags = r'\1c'+(color if start <= 0 else normal)
            if start > 0:
                tags += rf'\t({start},{start+1},\1c{color})'
            if plan['mode'] == 'word_current':
                tags = r'\1c'+normal if end <= 0 else tags+rf'\t({max(0,end)},{max(0,end)+1},\1c{normal})'
        result.append('{'+tags+'}'+content)
    return ''.join(result)
