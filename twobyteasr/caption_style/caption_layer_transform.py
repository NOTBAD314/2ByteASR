"""Persistent per-language cue geometry; render copies consume it once.

Position is in project pixels, scale in percent, anchor in [0,1] of ink bounds,
rotation clockwise in degrees. Defaults retain the existing bilingual layout.
Only presentation lives here: no text, timing or translation records are edited.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping

from ..timeline.studio_commands import SetCuesPresentationCommand

GEOMETRY = frozenset({'position_x', 'position_y', 'scale_x', 'scale_y',
                      'rotation', 'anchor_x', 'anchor_y', 'font_size'})
LAYER_KEY = 'language_layers'
MOTION_KEY = 'language_motion'


def target_ids(project, cue_ids):
    """Exact persisted IDs win over the legacy projected-id fallback."""
    from ..timeline.studio_edit_sequence import source_cue_id_of
    known={cue.id for cue in project.cues}
    return {str(key) if str(key) in known else source_cue_id_of(str(key)) for key in cue_ids}


def layer_values(cue, language):
    layers = (cue.transform or {}).get(LAYER_KEY, {})
    value = layers.get(language, {}) if isinstance(layers, Mapping) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def materialize_layer(cue, language):
    if (cue.transform or {}).get('_language_materialized'):
        return cue
    values = layer_values(cue, language)
    motion = (cue.transform or {}).get(MOTION_KEY, {})
    if not values and language == 'original' and not motion:
        return cue
    result = copy.deepcopy(cue)
    result.transform = dict(result.transform or {})
    result.transform.pop(LAYER_KEY, None)
    result.transform.pop(MOTION_KEY, None)
    result.transform.update({k:v for k,v in values.items() if k in GEOMETRY})
    if values.get('style_id'):
        result.style_id=str(values['style_id'])
    result.transform['_language_materialized'] = language
    if any(key in GEOMETRY for key in values):
        result.transform['_geometry_base']={k:v for k,v in (cue.transform or {}).items() if k in GEOMETRY}
        result.transform['_canvas_transform'] = True
    if language == 'translation':
        result.effect_id = str(motion.get('translation_effect_id', result.effect_id))
        result.evidence_refs = []
        result.raw_ass_override = ''
    return result


def displayed_layer(project, cue, language):
    from .bilingual_layout import display_cues, translations_of, settings_from_state, companion_id
    settings = settings_from_state(project.studio_state)
    # Inspect the real bilingual layout even if the other language is hidden.
    from dataclasses import replace
    settings = replace(settings, mode='bilingual')
    rows = display_cues([cue], translations=translations_of(project.generation_metadata), settings=settings,
        styles=project.styles, speakers=project.speakers, style_recipes=project.style_recipes,
        play_res_x=int(project.render_settings.get('play_res_x',1920)),
        play_res_y=int(project.render_settings.get('play_res_y',1080)))
    target = companion_id(cue.id) if language == 'translation' else cue.id
    return next((row for row in rows if row.id == target), None)


def resolved_values(project, cue, language, *, geometry_only=False):
    from .resolved_caption_style import resolve_caption_style
    from .visual_snapshot import _anchor
    shown = displayed_layer(project, cue, language)
    if shown is None:
        return None
    width, height = (int(project.render_settings.get(k,d)) for k,d in (('play_res_x',1920),('play_res_y',1080)))
    if geometry_only:
        from .style_resolution import resolve_cue_visual
        style=resolve_cue_visual(project,shown).style
    else:style = resolve_caption_style(project.styles,project.speakers,shown,project.style_recipes,width).style
    x,y,ax,ay = _anchor(style,width,height)
    explicit=layer_values(cue,language)
    return dict(position_x=x,position_y=y,scale_x=style.scale_x,scale_y=style.scale_y,
        rotation=float(shown.transform.get('rotation',0)),
        anchor_x=float(shown.transform.get('anchor_x',ax)),anchor_y=float(shown.transform.get('anchor_y',ay)),
        font_size=style.font_size,scale_link=bool(layer_values(cue,language).get('scale_link',True)))


class GeometryBatch:
    """Operation-local geometry reuse; glyph measurement stays with visible ink."""
    def __init__(self,project):
        from .bilingual_layout import translations_of
        self.project=project;self.cache={};self.translations=translations_of(project.generation_metadata)

    def values(self,cue,language):
        import json
        from .bilingual_layout import translation_for_cue
        translation=translation_for_cue(self.translations,cue.id)
        key=(language,cue.style_id,cue.base_preset_id,cue.speaker_id,
             json.dumps((cue.transform,cue.appearance_override),sort_keys=True,ensure_ascii=False),
             (cue.text,translation) if translation else None)
        if key not in self.cache:self.cache[key]=resolved_values(self.project,cue,language,geometry_only=True)
        value=self.cache[key]
        return dict(value) if value is not None else None


class LayerEditCommand(SetCuesPresentationCommand):
    COMMAND_ID = 0x221B

    def mergeWith(self, other):
        if not isinstance(other, LayerEditCommand) or not getattr(self,'merge_token',None):
            return False
        if self.merge_token != getattr(other,'merge_token',None):
            return False
        return super().mergeWith(other)


def presentation_command(project, targets, transforms, *, effects=None, effect_ids=None,
                         changed=None, text='调整字幕变换', merge_token=None):
    if not targets:
        return None
    if all(transforms.get(c.id,c.transform)==c.transform and (effect_ids or {}).get(c.id,c.effect_id)==c.effect_id for c in targets):
        return None
    command = LayerEditCommand(project,[c.id for c in targets],style_id=targets[0].style_id,
        style_ids={c.id:c.style_id for c in targets},effect_id=targets[0].effect_id,
        effect_ids=effect_ids or {c.id:c.effect_id for c in targets},transform_overrides=transforms,
        effects=effects,changed=changed,text=text,merge_enabled=merge_token is not None)
    command.merge_token = merge_token
    return command


def transform_command(project, cue_ids, language, changes, *, reset=False, changed=None, merge_token=None):
    if language not in {'original','translation','linked'}:
        raise ValueError('unknown subtitle language layer')
    changes=dict(changes)
    for key,value in changes.items():
        if key == 'scale_link':
            if not isinstance(value,bool):raise ValueError('scale_link must be boolean')
        elif key not in GEOMETRY or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f'invalid transform field: {key}')
        elif key.startswith('anchor_') and not 0 <= value <= 1:
            raise ValueError('anchor outside [0,1]')
        elif key in {'scale_x','scale_y','font_size'} and value <= 0:
            raise ValueError('scale and font size must be positive')
    ids=target_ids(project,cue_ids)
    targets=[c for c in project.cues if c.id in ids]
    transforms={}
    for cue in targets:
        transform=copy.deepcopy(cue.transform or {})
        layers=transform.setdefault(LAYER_KEY,{})
        for layer in (('original','translation') if language=='linked' else (language,)):
            if reset:
                values=layers.get(layer,{})
                for key in GEOMETRY | {'scale_link'}:values.pop(key,None)
                if not values:layers.pop(layer,None)
                continue
            before=resolved_values(project,cue,layer)
            if before is None:
                continue
            values=layers.setdefault(layer,{})
            delta=dict(changes)
            scale_keys={'scale_x','scale_y'} & delta.keys()
            if before['scale_link'] and len(scale_keys)==1:
                axis=next(iter(scale_keys));other='scale_y' if axis=='scale_x' else 'scale_x'
                delta[other]=before[other]*delta[axis]/max(.01,before[axis])
            from .caption_group_transform import inverse_changes
            values.update(inverse_changes(project,cue,delta))
        if not layers:transform.pop(LAYER_KEY,None)
        transforms[cue.id]=transform
    return presentation_command(project,targets,transforms,changed=changed,merge_token=merge_token)
