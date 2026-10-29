"""Field-only presentation transactions; every cue keeps its own unedited values."""
from __future__ import annotations

import copy
from dataclasses import asdict
import hashlib
import json

from .style_recipe import StyleRecipe, normalize_glow_contract, normalize_shadow_contract
from .style_resolution import APPEARANCE_FIELDS, TRANSFORM_FIELDS, resolve_cue_visual
from ..timeline.studio_commands import SetCuesPresentationCommand


def style_fields_command(project, cue_ids, patch, *, shadow_patch=None, glow_patch=None, changed=None):
    """Build one undo step, preserving bases, effects, recipes and each original value."""
    from .visual_snapshot import _materialize_recipe_appearance
    wanted = set(cue_ids)
    cues = [cue for cue in project.cues if cue.id in wanted]
    if not cues:
        return None
    shadow_patch, glow_patch = dict(shadow_patch or {}), dict(glow_patch or {})
    styles = {style.id: style for style in project.styles}
    recipes = dict(project.style_recipes)
    mapped, appearances, bases, transforms = {}, {}, {}, {}
    old_ids = set()
    # Materialization depends on presentation, not cue text or time. Share the
    # computation inside this transaction only; no persistent invalidation or
    # unbounded cache, and every cue still owns its editable dictionaries.
    materialized = {}
    for cue in cues:
        old_ids.add(cue.style_id)
        transform = cue.transform or {}
        visual_transform = {k:v for k,v in transform.items() if k in TRANSFORM_FIELDS}
        initial = transform.get('initial_layout', {})
        if isinstance(initial, dict) and initial.get('version') == 1:
            visual_transform['initial_layout'] = {k:initial[k] for k in ('version','position_x','position_y') if k in initial}
        cache_key = (cue.style_id, cue.base_preset_id, cue.speaker_id,
               json.dumps(cue.appearance_override or {}, sort_keys=True, ensure_ascii=False),
               json.dumps(visual_transform, sort_keys=True, ensure_ascii=False))
        cached = materialized.get(cache_key)
        if cached is not None:
            style_id, base_id = cached
            appearance, transform = copy.deepcopy(cue.appearance_override or {}), copy.deepcopy(cue.transform or {})
            for name, value in patch.items():
                if name in APPEARANCE_FIELDS:
                    appearance[name] = copy.deepcopy(value)
                if name in TRANSFORM_FIELDS and (name in transform or name.startswith('position_')):
                    transform[name] = copy.deepcopy(value)
            if shadow_patch:
                appearance.pop('shadow', None)
            mapped[cue.id], appearances[cue.id], bases[cue.id] = style_id, appearance, base_id
            transforms[cue.id] = transform
            continue
        style = resolve_cue_visual(project, cue).style
        base_id = cue.base_preset_id or style.id
        appearance = copy.deepcopy(cue.appearance_override or {})
        transform = copy.deepcopy(cue.transform or {})
        for key, value in patch.items():
            setattr(style, key, copy.deepcopy(value))
            if key in APPEARANCE_FIELDS:
                appearance[key] = copy.deepcopy(value)
            if key in TRANSFORM_FIELDS and (key in transform or key.startswith('position_')):
                transform[key] = copy.deepcopy(value)
        payload = copy.deepcopy(project.style_recipes.get(cue.style_id))
        if shadow_patch or glow_patch:
            recipe = StyleRecipe.from_dict(payload) if payload else StyleRecipe(
                name=style.name, engine='native',
                colors={'fill': style.primary_color},
                outline={'color': style.outline_color, 'width': style.outline_width},
            )
            if shadow_patch:
                shadow = normalize_shadow_contract(recipe.outline.get('shadow', style.shadow))
                shadow.update(shadow_patch)
                shadow['strength'] = max(abs(shadow['offset_x']), abs(shadow['offset_y']),
                                         shadow['blur_radius'] / 1.5, shadow['spread'])
                shadow['enabled'] = shadow['opacity'] > 0 and shadow['strength'] > 0
                recipe.outline['shadow'] = normalize_shadow_contract(shadow)
                style.shadow = shadow['strength']
                # A scalar appearance override would flatten the richer contract.
                appearance.pop('shadow', None)
            if glow_patch:
                glow = normalize_glow_contract(recipe.effects.get('glow', {}))
                glow.update(glow_patch)
                if 'radius' in glow_patch:
                    glow['strength'] = glow['blur'] = glow['radius']
                if glow_patch.get('enabled') and glow['opacity'] <= 0:
                    glow.pop('opacity')
                recipe.effects['glow'] = normalize_glow_contract(glow)
            recipe = _materialize_recipe_appearance(recipe, style, appearance)
            shadow = recipe.outline.get('shadow', {})
            if (shadow_patch and shadow.get('enabled') and not recipe.visual_graph
                    and not recipe.web_theme):
                from ..caption_design.visual_design_graph import graph_from_style_recipe
                recipe.engine = 'remotion'
                recipe.visual_graph = graph_from_style_recipe(recipe).to_dict()
            payload = recipe.to_dict()
        elif payload and 'primary_color' in patch:
            payload.setdefault('colors', {})['fill'] = patch['primary_color']
        style.validate()
        # Keep the persisted recipe's glyph fields in sync with the canonical
        # appearance too. Native styles get a native recipe; creating one must
        # not pull rounded shadow/gradient values from the active inspector.
        recipe = StyleRecipe.from_dict(payload) if payload else StyleRecipe(
            name=style.name, engine='native', colors={'fill': style.primary_color},
            outline={'shadow': style.shadow},
        )
        recipe = _materialize_recipe_appearance(recipe, style, appearance)
        recipe.typography.update(underline=style.underline, fontFile=style.font_file,
                                 fontFaceIndex=style.font_face_index)
        payload = recipe.to_dict()
        signature = asdict(style)
        signature.pop('id')
        signature['recipe'] = payload
        digest = hashlib.sha1(json.dumps(signature, sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()[:12]
        style.id = f'{base_id}-scope-{digest}'
        styles[style.id] = style
        if payload:
            recipes[style.id] = payload
        mapped[cue.id], appearances[cue.id], bases[cue.id] = style.id, appearance, base_id
        transforms[cue.id] = transform
        materialized[cache_key] = (style.id, base_id)
    # Replace only now-unused variants involved in this edit. User presets,
    # speaker bases and unrelated project records are never garbage-collected.
    referenced = {mapped.get(cue.id, cue.style_id) for cue in project.cues}
    referenced.update(bases.get(cue.id, cue.base_preset_id) for cue in project.cues)
    referenced.update(speaker.style_id for speaker in project.speakers)
    for style_id in old_ids - referenced:
        if '-scope-' in style_id:
            styles.pop(style_id, None)
            recipes.pop(style_id, None)
    return SetCuesPresentationCommand(
        project, mapped, style_id=mapped[cues[0].id], style_ids=mapped,
        base_preset_ids=bases, appearance_overrides=appearances,
        effect_id=cues[0].effect_id, effect_ids={cue.id: cue.effect_id for cue in cues},
        styles=list(styles.values()), effects=project.effects, style_recipes=recipes,
        transform_overrides=transforms, text='修改选中字幕样式', changed=changed, merge_enabled=False,
    )
