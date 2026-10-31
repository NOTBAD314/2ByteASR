"""A user's explicit style action, bound to one project, cue and text layer."""
from copy import deepcopy
from dataclasses import dataclass, field
from .scoped_style import merge_patch, style_patch_command
from .scoped_preset import preset_command


def context_key(page):
    return (id(page.project), str(page.selected_cue_id or ''), page.style_layer.currentData())


@dataclass
class StyleApplication:
    key: tuple
    preset: dict | None = None
    fields: dict = field(default_factory=dict)
    recipe: dict = field(default_factory=dict)
    applied: tuple | None = None
    replay: bool = True
    geometry_only: bool = False
    geometry_ops: list = field(default_factory=list)

    def extend(self, patch):
        self.fields.update(deepcopy(patch.get('fields', {})))
        self.recipe = merge_patch(self.recipe, patch.get('recipe', {}))
        self.applied = None

    def command(self, project, scope, *, geometry, changed, cancel_check=None):
        if self.preset is None:
            command=style_patch_command(project, scope.cue_ids, self.fields,
                recipe_patch=self.recipe, layer=scope.layer, changed=changed,cancel_check=cancel_check)
            if self.geometry_ops:
                from .style_plan_ops import augment
                command=augment(project,command,self.geometry_ops,layer=scope.layer,cancel_check=cancel_check)
            return command
        patch = deepcopy(self.preset)
        if not self.geometry_only:
            patch.update(deepcopy(self.fields))
            patch['recipe'] = merge_patch(patch.get('recipe', {}), self.recipe)
        command=preset_command(project, scope.cue_ids, patch, layer=scope.layer,
            apply_geometry=geometry, changed=changed,cancel_check=cancel_check,appearance=not self.geometry_only)
        if self.geometry_ops or self.geometry_only and (self.fields or self.recipe):
            from .style_plan_ops import augment
            command=augment(project,command,self.geometry_ops,
                fields=self.fields if self.geometry_only else None,recipe=self.recipe if self.geometry_only else None,
                layer=scope.layer,cancel_check=cancel_check)
        return command


def changed_count(command):
    if command is not None and hasattr(command,'changed_ids'):return len(command.changed_ids)
    if command is None:return 0
    count=sum(command.before[key] != value for key, value in command.after.items())
    return max(count,len(command.after) if getattr(command,'group_changed',False) else 0)
