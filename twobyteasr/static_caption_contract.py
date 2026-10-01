"""Static glyphs share one raster contract in Studio and production export."""
from .style_recipe import motion_mode


def shared_static_recipe(recipe):
    if recipe.get('webTheme') or recipe.get('wordHighlight'):
        return False
    graph = recipe.get('visualGraph') or {}
    if (recipe.get('typography', {}).get('underline') or recipe.get('ass', {}).get('tags')
            or graph.get('textLayer', {}).get('emphasis')):
        return False
    if graph.get('decorationLayers') or graph.get('effectLayers') or graph.get('motionGraph', {}).get('tracks'):
        return False
    if motion_mode(recipe.get('motion', {})) != 'none':
        return False
    panel = graph.get('panelLayer', {}).get('primitive', 'NONE')
    if panel not in ('NONE', 'ROUNDED_PANEL'):
        return False
    return True


def shared_static_cue(project,cue):
    """A generated effect ID can still describe an entirely static cue."""
    from .advanced_renderer import recipe_payload_for_cue
    if not shared_static_recipe(recipe_payload_for_cue(project,cue)):return False
    if cue.effect_id in ('','none'):return True
    effect=project.effects.get(cue.effect_id)
    if not isinstance(effect,dict) or set(effect)-{'entry','exit'}:return False
    return all((effect.get(part) or {}).get('type','none')=='none' for part in ('entry','exit'))
