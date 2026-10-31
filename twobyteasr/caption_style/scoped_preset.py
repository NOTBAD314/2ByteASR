"""Preset application preserves unedited language layers and authored geometry."""
import copy
from dataclasses import asdict, fields as data_fields
from .scoped_style import style_patch_command,GEOMETRY
from .caption_layer_transform import GeometryBatch,LAYER_KEY,GEOMETRY as LAYER_GEOMETRY
from .scoped_transform import edit_values
from .style_resolution import APPEARANCE_FIELDS
from ..projects.studio_project import SubtitleStyle
from ..timeline.studio_commands import SetCuesPresentationCommand


def preset_command(project,cue_ids,patch,*,layer='original',apply_geometry=False,changed=None,cancel_check=None,appearance=True):
    if cancel_check is not None and cancel_check():return None
    if layer=='linked':layer='group'
    if layer not in {'original','translation','group'}:raise ValueError('Unknown preset language')
    wanted=frozenset(cue_ids);targets=[c for c in project.cues if c.id in wanted]
    if not targets:return None
    authored={f.name for f in data_fields(SubtitleStyle)}
    template=SubtitleStyle(**{k:copy.deepcopy(v) for k,v in patch.items() if k in authored})
    template.validate()
    # Older complete presets predate the four explicit font-face fields.
    # Their absent fields mean defaults, whereas genuinely sparse patches
    # continue to inherit unspecified properties.
    full=(APPEARANCE_FIELDS-{'font_weight','font_style_name','font_file','font_face_index'}) <= patch.keys()
    source=asdict(template) if full else patch
    style_fields={k:copy.deepcopy(v) for k,v in source.items() if k in APPEARANCE_FIELDS-GEOMETRY}
    recipe=copy.deepcopy(patch.get('recipe') or {})
    if full and appearance:
        from .style_recipe import StyleRecipe
        from .visual_snapshot import _materialize_recipe_appearance
        recipe=_materialize_recipe_appearance(StyleRecipe.from_dict({'name':template.name,**recipe}),template,{}).to_dict()
        recipe.setdefault('webTheme',None);recipe.setdefault('visualGraph',None)
    base=(style_patch_command(project,cue_ids,style_fields,recipe_patch=recipe,layer=layer,allow_paint=False,
                             replace_recipe=full,cancel_check=cancel_check)
          if appearance else None)
    if cancel_check is not None and cancel_check():return None
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
        if cancel_check is not None and cancel_check():return None
        record=after.get(cue.id)
        face=copy.deepcopy(record[3] if record is not None else cue.appearance_override)
        transform=copy.deepcopy((record[4] if record is not None else cue.transform) or {});layers=transform.setdefault(LAYER_KEY,{})
        style_ids[cue.id]=record[0] if record is not None else cue.style_id
        effect_ids[cue.id]=record[1] if record is not None else cue.effect_id
        # An automatic pair owns one group anchor. Applying appearance must
        # not convert its derived line positions into independent absolute
        # positions. Explicit layer positions remain manual and keep the
        # established affine editing path below (including old projects).
        manual=any({'position_x','position_y'} & set((cue.transform or {}).get(LAYER_KEY,{}).get(name,{}))
                   for name in ('original','translation'))
        if not manual:
            if pose:
                group_pose={k:v for k,v in pose.items() if k in {'position_x','position_y'}}
                transform.update(inverse_changes(project,cue,group_pose))
                if 'alignment' in patch:transform['alignment']=template.alignment
            for language in ('original','translation'):
                if layer!='group' and layer!=language:continue
                value=layers.setdefault(language,{})
                if pose:
                    value.update(inverse_changes(project,cue,{k:v for k,v in pose.items()
                        if k in {'scale_x','scale_y','rotation','anchor_x','anchor_y'}}))
                if appearance:
                    if full:value.pop('style_id',None)
                    if 'font_size' in style_fields:value['font_size']=style_fields['font_size']
                    face.setdefault(language,{})['preset_id']=str(patch['id'])
            overrides[cue.id]=face;transforms[cue.id]=transform
            continue
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
                # A missing authored axis is preserved, even when interactive
                # scaling is linked. Presets are absolute saved parameters.
                saved_pose = dict(pose)
                for axis in ('scale_x', 'scale_y'):
                    if axis not in saved_pose and {'scale_x', 'scale_y'} & pose.keys():
                        saved_pose[axis] = before_original[axis] if layer == 'group' else before[axis]
                result=edit_values(before,saved_pose,reference=before_original,owner=before_original,linked=layer=='group')
                value.update(inverse_changes(project,cue,{k:result[k] for k in preserve if k in result}))
            if edited and appearance:
                if full:value.pop('style_id',None)
                if 'font_size' in style_fields:value['font_size']=style_fields['font_size']
                if language=='original':face.setdefault('original',{})['preset_id']=str(patch['id'])
                else:face.setdefault('translation',{})['preset_id']=str(patch['id'])
        overrides[cue.id]=face;transforms[cue.id]=transform
    return SetCuesPresentationCommand(project,[c.id for c in targets],style_id=targets[0].style_id,
        effect_id=targets[0].effect_id,style_ids=style_ids,effect_ids=effect_ids,
        appearance_overrides=overrides,transform_overrides=transforms,styles=styles,style_recipes=recipes,
        changed=changed,merge_enabled=False,text='应用所选语言层预设')
