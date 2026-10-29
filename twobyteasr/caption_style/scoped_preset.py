"""Preset application preserves unedited language layers and authored geometry."""
import copy
from dataclasses import fields as data_fields
from .scoped_style import style_patch_command,GEOMETRY
from .caption_layer_transform import GeometryBatch,LAYER_KEY,GEOMETRY as LAYER_GEOMETRY
from .scoped_transform import edit_values
from .style_resolution import APPEARANCE_FIELDS
from ..projects.studio_project import SubtitleStyle
from ..timeline.studio_commands import SetCuesPresentationCommand


def preset_command(project,cue_ids,patch,*,layer='original',apply_geometry=False,changed=None):
    if layer=='linked':layer='group'
    if layer not in {'original','translation','group'}:raise ValueError('Unknown preset language')
    wanted=frozenset(cue_ids);targets=[c for c in project.cues if c.id in wanted]
    if not targets:return None
    authored={f.name for f in data_fields(SubtitleStyle)}
    template=SubtitleStyle(**{k:copy.deepcopy(v) for k,v in patch.items() if k in authored})
    template.validate()
    style_fields={k:copy.deepcopy(v) for k,v in patch.items() if k in APPEARANCE_FIELDS-GEOMETRY}
    recipe=copy.deepcopy(patch.get('recipe') or {})
    full=authored-{'id','name'} <= patch.keys()
    if full:
        from .style_recipe import StyleRecipe
        from .visual_snapshot import _materialize_recipe_appearance
        recipe=_materialize_recipe_appearance(StyleRecipe.from_dict({'name':template.name,**recipe}),template,{}).to_dict()
        recipe.setdefault('webTheme',None);recipe.setdefault('visualGraph',None)
    base=style_patch_command(project,cue_ids,style_fields,recipe_patch=recipe,layer=layer)
    after=base.after if base is not None else {}
    styles=base.after_styles if base is not None and base.after_styles is not None else project.styles
    recipes=base.after_style_recipes if base is not None and base.after_style_recipes is not None else project.style_recipes
    from .visual_snapshot import _anchor
    from .caption_group_transform import inverse_changes
    x,y,ax,ay=_anchor(template,int(project.render_settings.get('play_res_x',1920)),int(project.render_settings.get('play_res_y',1080)))
    pose={}
    if apply_geometry:
        if {'position_x','alignment','margin_l','margin_r'} & patch.keys():pose['position_x']=x
        if {'position_y','alignment','margin_v'} & patch.keys():pose['position_y']=y
        for key in ('scale_x','scale_y','rotation'):
            if key in patch:pose[key]=patch[key]
        if 'alignment' in patch:pose.update(anchor_x=ax,anchor_y=ay)
    cache=GeometryBatch(project);overrides={};transforms={};style_ids={};effect_ids={}
    preserve=LAYER_GEOMETRY-{'font_size'}|{'scale_link'}
    for cue in targets:
        record=after.get(cue.id)
        appearance=copy.deepcopy(record[3] if record is not None else cue.appearance_override)
        transform=copy.deepcopy((record[4] if record is not None else cue.transform) or {});layers=transform.setdefault(LAYER_KEY,{})
        style_ids[cue.id]=record[0] if record is not None else cue.style_id
        effect_ids[cue.id]=record[1] if record is not None else cue.effect_id
        before_original=cache.values(cue,'original')
        for language in ('original','translation'):
            before=cache.values(cue,language)
            if before is None:continue
            edited=layer=='group' or layer==language
            value=layers.setdefault(language,{})
            # Appearance can alter the default bilingual layout. Freeze the
            # other layer's effective geometry, and both when geometry is off.
            if not edited or not apply_geometry:
                value.update(inverse_changes(project,cue,{k:before[k] for k in preserve}))
            elif pose:
                result=edit_values(before,pose,reference=before_original,owner=before_original,linked=layer=='group')
                value.update(inverse_changes(project,cue,{k:result[k] for k in preserve if k in result}))
            if edited:
                if full:value.pop('style_id',None)
                if 'font_size' in style_fields:value['font_size']=style_fields['font_size']
                if language=='original':appearance.setdefault('original',{})['preset_id']=str(patch['id'])
                else:appearance.setdefault('translation',{})['preset_id']=str(patch['id'])
        overrides[cue.id]=appearance;transforms[cue.id]=transform
    return SetCuesPresentationCommand(project,[c.id for c in targets],style_id=targets[0].style_id,
        effect_id=targets[0].effect_id,style_ids=style_ids,effect_ids=effect_ids,
        appearance_overrides=overrides,transform_overrides=transforms,styles=styles,style_recipes=recipes,
        changed=changed,merge_enabled=False,text='应用所选语言层预设')
