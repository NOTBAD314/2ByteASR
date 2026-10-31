"""Compose later field/geometry intent on detached presentation data."""
import copy


def augment(project,command,ops,*,fields=None,recipe=None,layer='original',cancel_check=None):
    from ..timeline.studio_commands import SetCuesPresentationCommand
    from .paint_patch import _write
    from .caption_group_transform import KEY,GroupTransformCommand,shared_after,reset_group_command
    from .scoped_transform import transform_plan
    if command is None:return None
    if hasattr(command,'entries'):
        faces={}
        for cue in project.cues:
            if cue.id not in command.entries:continue
            face=cue.appearance_override
            for row in command.entries[cue.id]:face=_write(face,row[0],row[2])
            faces[cue.id]=face
        first=next(c for c in project.cues if c.id in faces)
        command=SetCuesPresentationCommand(project,faces,style_id=first.style_id,effect_id=first.effect_id,
            style_ids={c.id:c.style_id for c in project.cues if c.id in faces},
            effect_ids={c.id:c.effect_id for c in project.cues if c.id in faces},appearance_overrides=faces,
            text='组合字幕修改',merge_enabled=False)
    view=copy.copy(project);view.studio_state=copy.deepcopy(project.studio_state)
    view.styles=command.after_styles;view.effects=command.after_effects;view.style_recipes=command.after_style_recipes
    view.cues=[]
    for cue in project.cues:
        shown=copy.copy(cue)
        if cue.id in command.after:
            row=command.after[cue.id]
            shown.style_id,shown.effect_id,shown.base_preset_id=row[:3]
            shown.appearance_override=copy.deepcopy(row[3]);shown.transform=copy.deepcopy(row[4])
        view.cues.append(shown)
    if fields or recipe:
        from .scoped_style import style_patch_command
        delta=style_patch_command(view,command.after,fields or {},recipe_patch=recipe,layer=layer,allow_paint=False)
        if delta is not None:
            command.after=delta.after;command.after_styles=delta.after_styles;command.after_style_recipes=delta.after_style_recipes
            return augment(project,command,ops,layer=layer,cancel_check=cancel_check)
    by_id={cue.id:cue for cue in view.cues}
    for op in ops:
        if cancel_check is not None and cancel_check():return None
        reference=by_id.get(op['reference_id'])
        if reference is None:return None
        if op['global_mode']:
            group=(reset_group_command(view) if op['reset'] else
                   GroupTransformCommand(view,shared_after(view,reference,op['language'],op['changes'])))
            if group.after is None:view.studio_state.pop(KEY,None)
            else:view.studio_state[KEY]=copy.deepcopy(group.after)
            transforms=group.after_cues
            command.group_before=copy.deepcopy(project.studio_state.get(KEY))
            command.group_after=copy.deepcopy(view.studio_state.get(KEY))
            command.group_changed=command.group_before!=command.group_after
        else:
            transforms=transform_plan(view,op['ids'],op['language'],op['changes'],mode=op['mode'],
                reference_id=op['reference_id'],reset=op['reset']) or {}
        for cue_id,transform in transforms.items():
            by_id[cue_id].transform=transform
            old=command.after[cue_id]
            command.after[cue_id]=(*old[:4],transform)
    return command
