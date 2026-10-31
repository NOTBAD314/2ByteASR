"""Property patches against an explicit cue set; shared presets are never edited."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

from .style_resolution import APPEARANCE_FIELDS, TRANSFORM_FIELDS, resolve_cue_visual
from ..timeline.studio_commands import SetCuesPresentationCommand

GEOMETRY = frozenset(('position_x', 'position_y', 'scale_x', 'scale_y', 'alignment',
                      'margin_l', 'margin_r', 'margin_v', 'rotation'))


def merge_patch(value, patch):
    result = deepcopy(value) if isinstance(value, dict) else {}
    for key, item in patch.items():
        result[key] = merge_patch(result.get(key), item) if isinstance(item, dict) else deepcopy(item)
    return result


def property_patch(before, after):
    """Only authored changes, including false/zero, never a full inspector copy."""
    patch = {}
    for key, value in after.items():
        if before.get(key) == value:
            continue
        patch[key] = property_patch(before.get(key, {}), value) if isinstance(value, dict) else deepcopy(value)
    return patch


def effective_layer_style(project, cue, layer='original'):
    if layer=='group':layer='original'
    from .bilingual_layout import settings_from_state, _translation_font
    settings = settings_from_state(project.studio_state)
    from .caption_layer_transform import layer_values,materialize_layer
    base=materialize_layer(cue,layer) if layer_values(cue,layer).get('style_id') else cue
    style = resolve_cue_visual(project, base).style
    if layer == 'translation':
        style.font_size = round(style.font_size*settings.translation_scale, 2)
        text = str(project.generation_metadata.get('translations', {}).get(cue.id, ''))
        font = _translation_font(settings, text, style)
        if font and font != style.font_family:
            style.font_family = font
            style.font_weight, style.font_style_name, style.font_file, style.font_face_index = 0, '', '', 0
        for key, value in cue.appearance_override.get('translation', {}).get('style', {}).items():
            if key in APPEARANCE_FIELDS | GEOMETRY:
                setattr(style, key, deepcopy(value))
    elif layer == 'original' and settings.mode == 'bilingual':
        style.font_size = cue.appearance_override.get('original', {}).get('font_size', style.font_size*settings.original_scale)
    from .caption_layer_transform import layer_values
    explicit=layer_values(cue,layer)
    if 'font_size' in explicit:style.font_size=float(explicit['font_size'])
    return style


def effective_layer_recipe(project,cue,layer='original',*,style=None):
    """Inspector and renderer share the same resolved recipe appearance."""
    from .caption_layer_transform import materialize_layer
    from .bilingual_layout import _translation_appearance
    from .style_resolution import recipe_for_cue
    from .style_recipe import StyleRecipe
    from .visual_snapshot import _materialize_recipe_appearance
    language='original' if layer=='group' else layer
    shown=deepcopy(cue)
    if language=='translation':shown=_translation_appearance(cue,shown)
    shown=materialize_layer(shown,language)
    payload=recipe_for_cue(project.style_recipes,shown)
    face=style or effective_layer_style(project,cue,language)
    recipe=StyleRecipe.from_dict(payload) if payload else StyleRecipe(name=face.name,motion={})
    return _materialize_recipe_appearance(recipe,face,shown.appearance_override)


def style_patch_command(project, cue_ids, fields, *, recipe_patch=None, layer='original', changed=None, allow_paint=True,
                        replace_recipe=False,cancel_check=None):
    """Copy nested recipe data on write and retain every other cue property."""
    chosen = frozenset(cue_ids)
    cues = [cue for cue in project.cues if cue.id in chosen]
    if not cues or not (fields or recipe_patch):
        return None
    if layer not in ('original', 'translation', 'group'):
        raise ValueError('Unknown subtitle layer')
    from .paint_patch import paint_only,paint_command,redundant_solid_fill
    if allow_paint and (paint_only(fields,recipe_patch) or redundant_solid_fill(project,cues,fields,recipe_patch,layer)):
        return paint_command(project,cue_ids,fields,layer=layer,changed=changed)
    if layer != 'group' and GEOMETRY.intersection(fields) and any(project.generation_metadata.get('translations', {}).get(c.id) for c in cues):
        from ..i18n import tr
        raise ValueError(tr('双语字幕的位置与缩放请选择整组后调整'))
    styles = {s.id: deepcopy(s) for s in project.styles}
    recipes = dict(project.style_recipes)
    from .style_recipe import recipe_payload_for_style
    # 2026-10-24 daily port: the shadow lives in the recipe (outline.shadow, offsets / blur /
    # spread). ``SubtitleStyle.shadow`` is only its ASS scalar; as an appearance override it
    # outranks the recipe and the next blur or angle edit never shows (as in _apply_style).
    shadow_in_recipe = isinstance(((recipe_patch or {}).get('outline') or {}).get('shadow'), dict)
    if shadow_in_recipe:
        fields = {key: value for key, value in fields.items() if key != 'shadow'}
    overrides, transforms, style_ids, effect_ids = {}, {}, {}, {}
    materialized = {}  # Transaction-local; complete cue presentation is the key.
    for cue in cues:
        if cancel_check is not None and cancel_check():return None
        cache_key=json.dumps((cue.style_id,cue.base_preset_id,cue.speaker_id,
            cue.appearance_override,cue.transform,
            project.generation_metadata.get('translations',{}).get(cue.id,'')),
            ensure_ascii=False,sort_keys=True)
        hit=materialized.get(cache_key)
        if hit is not None:
            overrides[cue.id],transforms[cue.id]=deepcopy(hit[0]),deepcopy(hit[1])
            style_ids[cue.id],effect_ids[cue.id]=hit[2],cue.effect_id
            continue
        appearance = deepcopy(cue.appearance_override)
        transform = deepcopy(cue.transform)
        style_ids[cue.id], effect_ids[cue.id] = cue.style_id, cue.effect_id
        if layer == 'original' and project.generation_metadata.get('translations', {}).get(cue.id):
            # Editing the source must not change an inherited translation face.
            previous_translation = effective_layer_style(project, cue, 'translation')
            language = appearance.setdefault('translation', {})
            language_style = language.setdefault('style', {})
            for key in fields:
                if key in APPEARANCE_FIELDS and key not in language_style:
                    language_style[key] = deepcopy(getattr(previous_translation, key))
            if recipe_patch and 'recipe_base' not in language:
                language['recipe_base'] = deepcopy(recipe_payload_for_style(recipes, cue.style_id) or {})
        if layer in ('original', 'group') and 'font_size' in fields:
            appearance.setdefault('original', {})['font_size'] = fields['font_size']
        if 'font_size' in fields:
            from .caption_layer_transform import LAYER_KEY
            for language in (('original','translation') if layer=='group' else (layer,)):
                existing=transform.get(LAYER_KEY,{}).get(language,{})
                if 'font_size' in existing:existing['font_size']=fields['font_size']
        if layer in ('original', 'group'):
            if {'position_x','position_y'}.intersection(fields):
                from .visual_snapshot import _anchor
                current=resolve_cue_visual(project,cue).style
                x,y,_,_=_anchor(current,int(project.render_settings.get('play_res_x',1920)),int(project.render_settings.get('play_res_y',1080)))
                transform.update(position_x=fields.get('position_x', current.position_x if current.position_x is not None else x),
                                 position_y=fields.get('position_y', current.position_y if current.position_y is not None else y))
            for key, value in fields.items():
                if key in GEOMETRY:
                    transform[key] = deepcopy(value)
                elif key in APPEARANCE_FIELDS:
                    appearance[key] = deepcopy(value)
                if key in TRANSFORM_FIELDS and key in transform:
                    transform[key] = deepcopy(value)
            if shadow_in_recipe:
                appearance.pop('shadow', None)
            effective_patch = deepcopy(recipe_patch or {})
            # Derived ids (-fill-/-scope-/-cue-) read their base recipe; a lookup by the
            # exact id dropped e.g. a visual design graph from the local copy.
            base_recipe = recipe_payload_for_style(recipes, cue.style_id) or {}
            if base_recipe:
                names = {'font_family':'fontFamily', 'font_size':'fontSize', 'font_weight':'fontWeight',
                    'font_style_name':'fontStyleName', 'font_file':'fontFile', 'font_face_index':'fontFaceIndex',
                    'bold':'bold', 'italic':'italic', 'spacing':'spacing'}
                typed = {names[k]:v for k,v in fields.items() if k in names}
                if typed: effective_patch['typography'] = merge_patch(effective_patch.get('typography', {}), typed)
            if shadow_in_recipe and not (base_recipe.get('outline') or {}).get('shadow'):
                # A partial shadow edit (one angle or blur) on a cue whose shadow is still the
                # style's scalar starts from that cue's current shadow, not from nothing (2026-10-24 port).
                from .style_recipe import normalize_shadow_contract
                current = normalize_shadow_contract(resolve_cue_visual(project, cue).style.shadow)
                effective_patch['outline'] = dict(effective_patch['outline'],
                                                  shadow=merge_patch(current, effective_patch['outline']['shadow']))
            if effective_patch:
                if not base_recipe:
                    # A new fill/shadow recipe must start from this cue's
                    # native face; default recipe typography would flatten
                    # mixed fonts and sizes across the selection.
                    from .style_recipe import StyleRecipe
                    from .visual_snapshot import _materialize_recipe_appearance
                    current_style = resolve_cue_visual(project, cue).style
                    native = StyleRecipe(name=current_style.name, engine='native',
                        colors={'fill': current_style.primary_color},
                        outline={'color': current_style.outline_color, 'width': current_style.outline_width,
                                 'shadow': current_style.shadow})
                    base_recipe = _materialize_recipe_appearance(native, current_style, appearance).to_dict()
                payload = deepcopy(effective_patch) if replace_recipe else merge_patch(base_recipe, effective_patch)
                payload.setdefault('name', '局部样式')
                mirror = deepcopy(styles.get(cue.style_id, project.styles[0]))
                signature = {'recipe': payload, 'native': {k:v for k,v in asdict(mirror).items() if k != 'id'}}
                key = 'local-' + hashlib.sha256(json.dumps(signature, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
                mirror.id = key
                styles[key], recipes[key], style_ids[cue.id] = mirror, payload, key
        if layer in ('translation', 'group'):
            translation = appearance.setdefault('translation', {})
            translation['style'] = merge_patch(translation.get('style', {}),
                {k: v for k, v in fields.items() if k in APPEARANCE_FIELDS or (layer == 'translation' and k in GEOMETRY)})
            if recipe_patch:
                translation['recipe'] = (deepcopy(recipe_patch) if replace_recipe else
                                         merge_patch(translation.get('recipe', {}), recipe_patch))
                if replace_recipe:translation['recipe_base']={}
            if shadow_in_recipe:translation.get('style',{}).pop('shadow',None)
        overrides[cue.id], transforms[cue.id] = appearance, transform
        materialized[cache_key]=(appearance,transform,style_ids[cue.id])
    if cancel_check is not None and cancel_check():return None
    return SetCuesPresentationCommand(project, [c.id for c in cues], style_id=cues[0].style_id,
        effect_id=cues[0].effect_id, style_ids=style_ids, effect_ids=effect_ids,
        appearance_overrides=overrides, transform_overrides=transforms,
        styles=list(styles.values()), style_recipes=recipes, changed=changed,
        merge_enabled=False, text='修改所选字幕属性')
