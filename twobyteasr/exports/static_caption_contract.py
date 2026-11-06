"""Static glyphs share one raster contract in Studio and production export."""
from ..caption_style.style_recipe import motion_mode


def shared_static_recipe(recipe):
    recipe = recipe or {}
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
    params=graph.get('panelLayer',{}).get('params') or {}
    if params.get('coordinateSpace',params.get('coordinate_space'))=='video-canvas':
        return False  # The glyph-local Qt still does not paint canvas panels.
    return True


def shared_static_cue(project,cue):
    """A generated effect ID can still describe an entirely static cue."""
    from ..rendering.advanced_renderer import recipe_payload_for_cue
    if not shared_static_recipe(recipe_payload_for_cue(project,cue)):return False
    if cue.effect_id in ('','none'):return True
    effect=project.effects.get(cue.effect_id)
    if not isinstance(effect,dict) or set(effect)-{'entry','exit'}:return False
    return all((effect.get(part) or {}).get('type','none')=='none' for part in ('entry','exit'))


def intentional_empty_reason(snapshot):
    """Conservative proof of invisible static content, never a frame sample.

    Unknown decorations/effects and off-canvas text must still fail loudly.
    Animated graphs never enter this contract.
    """
    from PySide6.QtCore import QRectF
    from ..rendering.advanced_live_renderer import _color,_number
    from ..studio.studio_helpers import resolve_fill_brush
    recipe=snapshot.style_recipe or {}
    graph=recipe.get('visualGraph') or {}
    if graph.get('decorationLayers') or graph.get('effectLayers'):
        return None
    def visible_brush(value):
        brush=resolve_fill_brush(value,QRectF(0,0,100,100));gradient=brush.gradient()
        return any(color.alpha() for _,color in gradient.stops()) if gradient is not None else brush.color().alpha()>0
    panel=graph.get('panelLayer') or {}
    if panel.get('primitive','NONE')!='NONE':
        if panel.get('primitive')!='ROUNDED_PANEL':return None
        params=panel.get('params') or {}
        if visible_brush(params.get('paint') or params.get('gradient') or params.get('fill') or params.get('color','#CC111111')):return None
        if _number(params,'outlineWidth','borderWidth',default=0)>0 and _color(params.get('outlineColor',params.get('borderColor',params.get('color'))),'#FF111111').alpha():return None
    background=recipe.get('background') or {}
    if not graph and background.get('enabled') and _number(background,'opacity',default=1)>0 and visible_brush(background.get('paint') or background.get('color')):
        return None
    if not snapshot.text.strip():
        return 'empty_display_text'
    if snapshot.text_marks or (getattr(snapshot,'word_animation',None) or {}).get('spans'):
        return None
    if visible_brush(snapshot.fill):
        return None
    for stroke in snapshot.strokes:
        if float(stroke.get('width',0) or 0)>0 and float(stroke.get('opacity',1))>0 and visible_brush(stroke.get('paint') or stroke.get('color')):
            return None
    for effect in (snapshot.shadow,snapshot.glow):
        if effect and effect.get('enabled',float(effect.get('strength',0) or 0)>0):
            if float(effect.get('opacity',1))>0 and visible_brush(effect.get('paint') or effect.get('color')):return None
    return 'explicitly_transparent_paint'
