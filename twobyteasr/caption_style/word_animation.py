"""Read-only speech timing for caption animation; never invent word timings."""
from __future__ import annotations

import re
from collections.abc import Mapping

from ..recognition.cue_word_alignment import align_text_to_tokens, cue_words

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
    prefix = plan.get('static_prefix', '') if plan else ''
    if prefix:
        match = re.match(r'\s*'.join(re.escape(c) for c in prefix if not c.isspace()), text)
        if match:
            offset = match.end()
            body_plan = {k:v for k,v in plan.items() if k not in ('static_prefix', 'units')}
            mapped = remap_word_animation(body_plan, text[offset:])
            for key in ('spans', 'units'):
                mapped[key] = [{**row, 'char_start':row['char_start']+offset,
                               'char_end':row['char_end']+offset} for row in mapped.get(key, ())]
            if mapped.get('units'):
                # This is a static display unit, not an acoustic word/span.
                from .motion_catalog import REST
                rest = {**REST, 'opacity':1, 'scale':1, 'sy':1, 'ink':1, 'reveal':1}
                frame = [0, *(rest.get(channel, 0) for channel in mapped.get('channels', ()))]
                mapped['units'].insert(0, {'char_start':0, 'char_end':offset,
                    'static_display': True, 'frames':[frame]})
            return {**mapped, 'text':text, 'static_prefix':prefix, 'static_prefix_length':offset}
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
    # Preview is a read path: an edited receipt needs explicit alignment.
    # Re-running SequenceMatcher here used to stall every draft refresh.
    prefix = getattr(cue, '_speaker_name_prefix', '')
    source_cue = cue
    if prefix:
        import copy
        source_cue = copy.copy(cue)
        source_cue.text = cue._speaker_name_body
    from .bilingual_layout import is_companion
    if is_companion(cue.id) or (cue.transform or {}).get('_language_materialized')=='translation':
        # A companion ID resembles a projected source ID, but is another
        # language. Never resolve its word indices through the source cue.
        words, reason = [], 'translation_no_alignment'
    else:
        words, reason = cue_words(project, source_cue, allow_realign=False)
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
    if prefix:
        plan['static_prefix'] = prefix
    return remap_word_animation(plan, cue.text if text is None else text)


def word_state(plan, milliseconds):
    """Discrete visual state is cacheable between actual speech boundaries."""
    mode = plan.get('mode')
    if plan.get('units'):
        return (round(milliseconds, 2),)
    return tuple(0 if milliseconds < r['start_ms'] else
                 (2 if mode != 'word_current' or milliseconds < r['end_ms'] else 1)
                 for r in plan.get('spans', ()))


def compile_word_ass(plan, text, base_color, *, offset_ms=0, marks=None, style=None):
    from ..rendering.ass_compiler import escape_ass_text
    from .effect_dsl import _ass_color
    from .text_marks import runs
    from ..rendering.marked_glyphs import marked_ass_text
    from copy import copy
    plan = remap_word_animation(plan, text)
    if not plan.get('spans'):
        return marked_ass_text(text, marks, style) if marks and style else escape_ass_text(text)
    result = [escape_ass_text(text[:plan.get('static_prefix_length', 0)])]
    for span in plan['spans']:
        start, end = span['start_ms']-offset_ms, span['end_ms']-offset_ms
        segments = [(max(a,span['char_start']),min(b,span['char_end']),attrs)
                    for a,b,attrs in runs(text,marks) if a<span['char_end'] and b>span['char_start']] if marks and style else [(span['char_start'],span['char_end'],{})]
        for a,b,attrs in segments:
            local=copy(style) if marks and style else None
            normal_color=attrs.get('color') or ('#FFD166' if attrs.get('highlight') else base_color)
            if local is not None:
                local.primary_color=normal_color
                if 'bold' in attrs:local.bold=attrs['bold']
                if 'italic' in attrs:local.italic=attrs['italic']
            if plan['mode'] == 'word_reveal':
                tags = r'\alpha&H00&' if start <= 0 else rf'\alpha&HFF&\t({start},{start+1},\alpha&H00&)'
            else:
                color,normal = _ass_color(plan['color']),_ass_color(normal_color)
                tags = r'\1c'+(color if start <= 0 else normal)
                if start > 0: tags += rf'\t({start},{start+1},\1c{color})'
                if plan['mode'] == 'word_current':
                    tags = r'\1c'+normal if end <= 0 else tags+rf'\t({max(0,end)},{max(0,end)+1},\1c{normal})'
            result.append(marked_ass_text(text[a:b],[],local,extra_tags=tags) if local is not None
                          else '{'+tags+'}'+escape_ass_text(text[a:b]))
    return ''.join(result)
