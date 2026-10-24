"""Scoped motion edits preserve every cue's appearance and word timing."""
from __future__ import annotations

import copy
import hashlib
import json

from .effect_dsl import validate_effect, STRENGTH_PRESETS
from .word_animation import WORD_MODES, word_part
from ..timeline.studio_commands import SetCuesPresentationCommand

MOTION_PREFIX = 'cue-motion-'


def motion_command(project, cue_ids, *, motion=None, words=None, changed=None, language=None, merge_token=None):
    from .caption_layer_transform import MOTION_KEY, presentation_command,target_ids
    if language not in {None,'linked','original','translation'}:
        raise ValueError('unknown motion language layer')
    selected = target_ids(project,cue_ids)
    targets = [c for c in project.cues if c.id in selected]
    if not targets:
        return None
    effects = dict(project.effects)
    ids = {}
    transforms = {}
    def store_effect(effect):
        effect=validate_effect(effect)
        digest=hashlib.sha256(json.dumps(effect,sort_keys=True).encode()).hexdigest()[:16]
        key=MOTION_PREFIX+digest
        effects[key]=effect
        return key
    for cue in targets:
        transform=copy.deepcopy(cue.transform or {})
        prior=dict(transform.get(MOTION_KEY) or {})
        source_id=prior.get('translation_effect_id','none') if language=='translation' else cue.effect_id
        effect = validate_effect(effects.get(source_id, {}))
        if motion is not None:
            previous_words = word_part(effect)
            effect = validate_effect(motion)
            effect['motion_override'] = True
            if previous_words and not word_part(effect):
                effect['word_highlight'] = previous_words
        if words is not None:
            if effect['entry']['type'] in WORD_MODES:
                effect['entry'] = {'type': 'none'}
            if words.get('type','none')=='none':effect.pop('word_highlight',None)
            else:effect['word_highlight'] = words
        effect = validate_effect(effect)
        key = store_effect(effect)
        ids[cue.id] = cue.effect_id if language=='translation' else key
        if language is not None:
            companion=copy.deepcopy(effect)
            # Translation text has no original acoustic word indices. A word
            # request becomes one whole-line fade; keep entry/exit/loop intent.
            companion.pop('word_highlight',None)
            for stage in ('entry','exit'):
                if companion[stage]['type'] in WORD_MODES:
                    companion[stage]={'type':'fade','duration':250}
            if word_part(effect) and companion['entry']['type']=='none':
                companion['entry']={'type':'fade','duration':250}
            translated = store_effect(companion) if language in {'linked','translation'} else prior.get('translation_effect_id','none')
            transform[MOTION_KEY]={'linked':language=='linked','translation_effect_id':translated,
                                  'word_fallback':'whole_sentence' if word_part(effect) else 'none'}
            transforms[cue.id]=transform
    return presentation_command(project,targets,transforms,effects=effects,effect_ids=ids,
        text='应用字幕动效',changed=changed,merge_token=merge_token)


def native_motion_graph(effect, duration_ms):
    """One cue-relative graph for native effects on raster/advanced renderers."""
    effect = validate_effect(effect)
    duration = max(1, min(30000, int(duration_ms)))
    entry, leave = effect['entry'], effect['exit']
    active = entry['type'] not in WORD_MODES | {'none', 'emphasis'}
    delay = min(duration, entry.get('delay', 0)) if active else 0
    enter = min(entry.get('duration', 180), duration-delay) if active else 0
    out_end = max(0, duration-leave.get('delay', 0))
    out_start = max(0, out_end-leave.get('duration', 140))
    tracks = []
    def track(prop, points):
        values = {int(t): float(v) for t, v in points}
        tracks.append({'target': 'group', 'property': prop,
                       'keyframes': [{'timeMs': t, 'value': v, 'easing': 'linear'} for t, v in sorted(values.items())]})
    def curve(start, end, a, b, accel):
        # Match the ASS power curve with bounded piecewise-linear keyframes.
        return [(round(start+(end-start)*i/12), a+(b-a)*(i/12)**accel) for i in range(13)]
    fade_in = entry['type'] in {'fade','soft_fade','float_up','drop_in','slide_soft','blur_reveal'}
    fade_out = leave['type'] in {'fade','soft_fade'}
    if fade_in or fade_out:
        points = [(0, 0 if fade_in else 1)]
        if fade_in:
            points += curve(delay, delay+enter, 0, 1, entry.get('accel',1))
        if fade_out:
            points += curve(max(delay+enter, out_start), out_end, 1, 0, leave.get('accel',1))
        track('opacity', points)
    strength = STRENGTH_PRESETS[entry.get('strength', 'medium')]
    scale_points = []
    if active and entry['type'] in {'soft_pop', 'pop', 'punch', 'bounce_lite', 'scale'}:
        start = round(100+(entry.get('scale_from',90)-100)*strength)/100
        peak = round(100+(entry.get('overshoot',100)-100)*strength)/100
        target = entry.get('scale_to',100)/100
        first = delay+round(enter*(.42 if entry['type']=='bounce_lite' else .56))
        scale_points = [(0,start)]
        if entry['type'] in {'pop','scale'}:
            scale_points += curve(0, min(duration,entry['duration']),entry['scale_from']/100,target,1)
        else:
            scale_points += curve(delay,first,start,peak,entry['accel'])
            if entry['type']=='bounce_lite':
                second = delay+round(enter*.74)
                settle = round(100-2*strength)/100
                scale_points += curve(first,second,peak,settle,1.45)+curve(second,delay+enter,settle,target,.68)
            else:
                scale_points += curve(first,delay+enter,peak,target,1.55)
    if leave['type'] in {'scale','pop','soft_pop','punch','bounce_lite'}:
        target = round(100+(leave['scale_from']-100)*STRENGTH_PRESETS[leave['strength']])/100
        scale_points += curve(out_start,out_end,1,target,leave['accel'])
    if scale_points:
        track('scale', scale_points)
    if active and entry['type'] in {'slide', 'slide_soft', 'float_up', 'drop_in'}:
        for prop in ('x', 'y'):
            offset = entry.get('offset_'+prop, 0)*strength
            if offset:
                track(prop, [(0, offset)]+curve(delay, delay+enter, offset, 0, entry.get('accel',1)))
    if entry['type']=='blur_reveal':
        track('blur',curve(delay,delay+enter,entry['blur']*strength,0,entry['accel']))
    return {'durationMs': duration, 'tracks': tracks}
