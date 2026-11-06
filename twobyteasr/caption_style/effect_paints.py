"""Optional effect paint specs, with legacy flat colors retained as fallbacks.

The authored source is recipe.colors.effectPaints. Materialized strokes,
shadows, glow and panels carry the same paint into both renderers.
"""
from __future__ import annotations
import copy
from collections.abc import Mapping

TARGETS = ('outline', 'outline2', 'background', 'shadow', 'glow')
FIELDS = {'outline': 'outline_color', 'outline2': 'outline2_color', 'background': 'back_color'}


def normalize_effect_paints(value):
    from .style_recipe import FillSpec, StyleRecipeValidationError
    if value is None:
        return {}
    if not isinstance(value, Mapping) or set(value) - set(TARGETS):
        raise StyleRecipeValidationError('colors.effectPaints contains an unknown target')
    return {key: FillSpec.from_value(paint).to_dict() for key, paint in value.items()}


def apply_effect_paints(recipe):
    paints = normalize_effect_paints(recipe.colors.get('effectPaints'))
    if not paints:
        return recipe
    recipe.colors['effectPaints'] = copy.deepcopy(paints)
    layers = recipe.outline.get('layers')
    if not isinstance(layers, list):
        layers = [{'color': recipe.outline.get('color', '#FF000000'), 'width': recipe.outline.get('width', 0)}]
        recipe.outline['layers'] = layers
    for index, target in enumerate(('outline', 'outline2')):
        if target in paints and index < len(layers):
            layers[index]['paint'] = copy.deepcopy(paints[target])
    for target, section in (('shadow', recipe.outline), ('glow', recipe.effects)):
        if target in paints:
            effect = section.setdefault(target, {})
            effect['paint'] = copy.deepcopy(paints[target])
            # The authored paint owns color alpha; the legacy color is only
            # an opaque fallback, independent of the effect's opacity field.
            color = str(effect.get('color') or '#FFFFFFFF')
            effect['color'] = '#FF' + color[-6:]
    if 'background' in paints:
        recipe.background['paint'] = copy.deepcopy(paints['background'])
        recipe.background.setdefault('padding', 8)
    graph = recipe.visual_graph
    if isinstance(graph, dict) and graph:
        text = graph.setdefault('textLayer', {})
        text['strokes'] = copy.deepcopy(layers)
        for target, section in (('shadow', recipe.outline), ('glow', recipe.effects)):
            if target in paints:
                text[target] = copy.deepcopy(section[target])
        if 'background' in paints:
            graph.setdefault('panelLayer', {}).setdefault('params', {})['paint'] = copy.deepcopy(paints['background'])
    return recipe


def paint_value(recipe, target, fallback):
    paints = recipe.get('colors', {}).get('effectPaints', {}) if isinstance(recipe, Mapping) else {}
    return copy.deepcopy(paints.get(target, fallback))


def scope_has_effect_paint(project, cue_ids, target, layer):
    from .style_resolution import recipe_for_cue
    from types import SimpleNamespace
    wanted = frozenset(cue_ids)
    for cue in project.cues:
        if cue.id not in wanted: continue
        for language in (('original','translation') if layer == 'group' else (layer,)):
            appearance = cue.appearance_override or {}
            if language == 'translation':
                child = appearance.get('translation', {})
                appearance = {key: appearance[key] for key in ('_recipe_patch','_recipe_base') if key in appearance}
                if child.get('recipe'): appearance['_recipe_patch'] = child['recipe']
                if 'recipe_base' in child: appearance['_recipe_base'] = child['recipe_base']
            payload = recipe_for_cue(project.style_recipes, SimpleNamespace(style_id=cue.style_id, appearance_override=appearance)) or {}
            if target in payload.get('colors', {}).get('effectPaints', {}): return True
    return False


def effect_paint_patch(target, value):
    from PySide6.QtGui import QColor
    from .style_recipe import FillSpec
    if target not in TARGETS:
        raise ValueError('Unknown effect paint target')
    spec = FillSpec.from_value(value)
    fallback = spec.color if spec.kind == 'solid' else str(spec.stops[0]['color'])
    fields = {FIELDS[target]: fallback} if target in FIELDS else {}
    if target == 'background': fields['border_style'] = 3
    patch = {'colors': {'effectPaints': {target: spec.to_dict()}}}
    if target == 'shadow':
        color = QColor(fallback)
        shadow = {'color': color.name(QColor.HexRgb)}
        if spec.kind == 'solid':
            shadow['opacity'] = color.alphaF()
            # Shadow opacity is stored separately; never multiply the same alpha twice.
            patch['colors']['effectPaints'][target] = FillSpec.solid(color.name(QColor.HexRgb)).to_dict()
        patch['outline'] = {'shadow': shadow}
    elif target == 'glow':
        patch['effects'] = {'glow': {'color': QColor(fallback).name(QColor.HexRgb)}}
    return {'fields': fields, 'recipe': patch}


def apply_paint_command(project, cue_ids, target, value, *, layer='original', changed=None):
    from .scoped_style import style_patch_command
    patch = effect_paint_patch(target, value)
    return style_patch_command(project, cue_ids, patch['fields'], recipe_patch=patch['recipe'],
                               layer=layer, changed=changed, allow_paint=False)


def picker_snapshot(snapshot, target, value, width=350, height=156):
    """Fit the actual subtitle face/effects into the common picker preview."""
    from dataclasses import replace
    from .style_recipe import StyleRecipe, FillSpec
    from PySide6.QtGui import QFont, QFontMetricsF
    if snapshot is None:
        return None
    recipe = StyleRecipe.from_dict(snapshot.style_recipe)
    if target == 'fill':
        recipe.colors['fill'] = FillSpec.from_value(value).to_recipe_value()
        if recipe.visual_graph:
            recipe.visual_graph['textLayer']['fill'] = FillSpec.from_value(value).to_dict()
    else:
        recipe.colors.setdefault('effectPaints', {})[target] = FillSpec.from_value(value).to_dict()
    apply_effect_paints(recipe)
    font_size = min(34., snapshot.font_size)
    text = snapshot.text or '字幕样式 Aa 123'
    font = QFont(snapshot.font_family)
    font.setPixelSize(round(font_size))
    measured = QFontMetricsF(font).horizontalAdvance(max(text.splitlines(), key=len))
    font_size *= min(1., (width - 44) / max(1., measured))
    factor = font_size / max(1., snapshot.font_size)
    strokes = copy.deepcopy(recipe.outline.get('layers') or list(snapshot.strokes))
    for stroke in strokes:
        stroke['width'] = float(stroke.get('width', 0)) * factor
    shadow = copy.deepcopy(recipe.outline.get('shadow') or snapshot.shadow)
    glow = copy.deepcopy(recipe.effects.get('glow') or snapshot.glow)
    for section, names in ((shadow, ('offset_x','offset_y','blur','blur_radius','spread','strength')),
                           (glow, ('radius','blur','spread','strength'))):
        for key in names:
            if key in section: section[key] = float(section[key]) * factor
    recipe.outline['layers'], recipe.outline['shadow'], recipe.effects['glow'] = strokes, shadow, glow
    recipe.layout['lineHeightPx'] = font_size * 1.25
    recipe.background = copy.deepcopy(recipe.background)
    recipe.background['padding'] = 6
    recipe.motion = {'mode': 'none', 'origin': 'none'}
    # The sample compares paint on the current face; timeline choreography is not played here.
    recipe.visual_graph = {}
    return replace(snapshot, text=text, font_size=font_size, playres_x=width, playres_y=height,
        position_x=width/2, position_y=height/2-6, anchor_x=.5, anchor_y=.5, alignment=5,
        scale_x=1., scale_y=1., rotation=0., fill=FillSpec.from_value(recipe.colors.get('fill')).to_dict(),
        strokes=tuple(strokes), shadow=shadow, glow=glow, style_recipe=recipe.to_dict(),
        word_animation=None, text_marks=None, resolution=(width,height))


def needs_effect_paint_pixels(snapshot):
    """Old solid/linear pixels keep their cache identity across this upgrade."""
    recipe = getattr(snapshot, 'style_recipe', {}) or {}
    if recipe.get('colors', {}).get('effectPaints'):
        return True
    parts = list(getattr(snapshot, 'strokes', ())) + [
        getattr(snapshot, 'shadow', {}), getattr(snapshot, 'glow', {}), recipe.get('background', {})]
    if any(isinstance(part, Mapping) and part.get('paint') for part in parts):
        return True
    fill = getattr(snapshot, 'fill', {})
    return isinstance(fill, Mapping) and float(fill.get('radius', 1) or 1) != 1
