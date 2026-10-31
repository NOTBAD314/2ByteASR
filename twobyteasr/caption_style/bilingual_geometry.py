"""Measure bilingual anchors without materializing raster/recipe/export data."""
import copy
from .style_resolution import APPEARANCE_FIELDS,TRANSFORM_FIELDS,resolve_cue_visual


def _thin(cue):
    shown=copy.copy(cue)
    shown.appearance_override={k:v for k,v in cue.appearance_override.items() if k in APPEARANCE_FIELDS}
    keep=TRANSFORM_FIELDS|{'initial_layout','_canvas_transform','_name_layout_width','anchor_x','anchor_y','_motion_layout_scale','language_motion'}
    shown.transform={k:v for k,v in cue.transform.items() if k in keep}
    return shown


def _layout_style(project,cue):
    from .resolved_caption_style import layout_caption
    from .font_metadata import resolve_local_face
    style=resolve_cue_visual(project,cue).style
    width=float(project.render_settings.get('play_res_x',1920))
    maximum=max(1,width-max(40,style.margin_l)-max(40,style.margin_r)
                -2*(max(style.outline_width,style.outline2_width)+style.shadow+4))
    maximum/=max(1.,float(cue.transform.get('_motion_layout_scale',1.)))
    named=cue.transform.get('_name_layout_width')
    if isinstance(named,(int,float)) and named>0:
        maximum=min(maximum,max(1,named-2*(max(style.outline_width,style.outline2_width)+style.shadow+4)))
    family,_,layout,_=layout_caption(cue.text,style.font_family,style.bold,style.font_size,
        style.spacing,maximum,style.scale_x/100,style.font_weight,style.font_style_name,style.font_file,style.font_face_index)
    face,_=resolve_local_face(style.font_family,style.font_weight,style.font_style_name,
                             style.bold,style.font_file,style.font_face_index)
    style.font_family=family;style.font_style_name=face.style;style.font_weight=face.weight
    return style,layout.text


def _block(style,text):
    from .resolved_caption_style import visible_glyph_size
    width,height=visible_glyph_size(text,style.font_family,style.bold,float(style.font_size),float(style.spacing),
        style.font_weight,style.font_style_name,style.font_file,style.font_face_index)
    return (height*style.scale_y/100,width*style.scale_x/100,
            style.outline_width+style.outline2_width,max(0.,style.shadow))


def geometry_pair(project,cue,text,settings):
    """Exact ink_v1 geometry; unsupported authored/legacy paths return None."""
    from .bilingual_layout import theme_owns_translation,_translation_font,group_positions
    from .caption_layer_transform import GEOMETRY,layer_values
    from .visual_snapshot import _anchor
    layers=cue.appearance_override
    if (not text or settings.legacy or settings.layout!='ink_v1' or settings.group_transform
            or theme_owns_translation(project.style_recipes,cue) or layers.get('translation_group')
            or layers.get('text_marks') or layers.get('translation',{}).get('text_marks')
            or cue.transform.get('_language_materialized')):
        return None
    base=resolve_cue_visual(project,_thin(cue)).style
    # resolve_caption_style normalizes the face before choosing the companion.
    from .font_metadata import resolve_local_face
    face,_=resolve_local_face(base.font_family,base.font_weight,base.font_style_name,base.bold,base.font_file,base.font_face_index)
    base.font_family=face.full_name;base.font_weight=face.weight;base.font_style_name=face.style
    original=_thin(cue)
    original.transform['font_size']=layers.get('original',{}).get('font_size',round(base.font_size*settings.original_scale,2))
    companion=_thin(cue);companion.text=str(text).strip()
    companion.transform['font_size']=round(base.font_size*settings.translation_scale,2)
    font=_translation_font(settings,companion.text,base)
    if font:companion.appearance_override['font_family']=font
    translated=layers.get('translation',{}).get('style',{})
    companion.appearance_override.update({k:v for k,v in translated.items() if k in APPEARANCE_FIELDS})
    for key in ('font_size','position_x','position_y','scale_x','scale_y'):
        if key in translated:companion.transform[key]=translated[key]
    # Measurement consumes the same layer geometry as display_cues; applying
    # font size only after measuring used the previous line height/wrapping.
    original.transform.update({k:v for k,v in layer_values(cue,'original').items()
                               if k in {'font_size','scale_x','scale_y','rotation'}})
    companion.transform.update({k:v for k,v in layer_values(cue,'translation').items()
                                if k in {'font_size','scale_x','scale_y','rotation'}})
    if layer_values(cue,'original').get('style_id'):original.style_id=layer_values(cue,'original')['style_id']
    if layer_values(cue,'translation').get('style_id'):companion.style_id=layer_values(cue,'translation')['style_id']
    from .bilingual_layout import motion_layout_layer
    original=motion_layout_layer(original,'original',project.effects)
    companion=motion_layout_layer(companion,'translation',project.effects)
    os_,ot=_layout_style(project,original);ts,tt=_layout_style(project,companion)
    width=int(project.render_settings.get('play_res_x',1920));height=int(project.render_settings.get('play_res_y',1080))
    x,y,_,_=_anchor(os_,width,height)
    ob,tb=_block(os_,ot),_block(ts,tt)
    from .bilingual_layout import reserve_motion_block
    ob=reserve_motion_block(ob,cue,'original',project.effects)
    tb=reserve_motion_block(tb,cue,'translation',project.effects)
    first=settings.order=='translation_first';top,bottom=(tb,ob) if first else (ob,tb)
    from .bilingual_layout import automatic_group_layout
    top_y,bottom_y=group_positions(y,(base.alignment-1)//3,top,bottom,settings.gap_ratio*max(os_.font_size,ts.font_size),
        height if automatic_group_layout(cue) else None)
    oy,ty=(bottom_y,top_y) if first else (top_y,bottom_y)
    result={}
    for language,shown,position in (('original',original,oy),('translation',companion,ty)):
        shown.transform.update(position_x=round(x),position_y=round(max(4.,min(height-4.,position))))
        explicit=layer_values(cue,language)
        shown.transform.update({k:v for k,v in explicit.items() if k in GEOMETRY})
        if explicit.get('style_id'):shown.style_id=str(explicit['style_id'])
        if GEOMETRY & explicit.keys():shown.transform['_canvas_transform']=True
        style=resolve_cue_visual(project,shown).style
        px,py,ax,ay=_anchor(style,width,height)
        result[language]=dict(position_x=px,position_y=py,scale_x=style.scale_x,scale_y=style.scale_y,
            rotation=float(shown.transform.get('rotation',0)),anchor_x=float(shown.transform.get('anchor_x',ax)),
            anchor_y=float(shown.transform.get('anchor_y',ay)),font_size=style.font_size,scale_link=bool(explicit.get('scale_link',True)))
    return result
