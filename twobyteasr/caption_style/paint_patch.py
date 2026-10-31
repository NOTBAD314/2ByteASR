"""Sparse paint edits keep geometry and shared preset records untouched."""
from enum import Enum
from PySide6.QtGui import QColor,QUndoCommand
from ..projects.studio_revisions import freeze_json,thaw_json
from ..projects.studio_runtime_state import DirtyDomain

PAINT_FIELDS=frozenset({'primary_color','outline_color','outline2_color','back_color'})


class Missing(Enum):
    VALUE=0


def paint_only(fields,recipe=None):
    return bool(fields) and fields.keys()<=PAINT_FIELDS and not recipe


def redundant_solid_fill(project,cues,fields,patch,layer):
    """A solid recipe already follows primary_color; gradients need the full edit."""
    if not fields or not fields.keys()<=PAINT_FIELDS or 'primary_color' not in fields:return False
    if not isinstance(patch,dict) or set(patch)!={'colors'} or set(patch['colors'])!={'fill'}:return False
    from .style_recipe import FillSpec
    fill=FillSpec.from_value(patch['colors']['fill'])
    if fill.kind!='solid' or QColor(fill.color)!=QColor(fields['primary_color']):return False
    from types import SimpleNamespace
    from .style_resolution import recipe_for_cue
    checked={}
    for cue in cues:
        for language in (('original','translation') if layer=='group' else (layer,)):
            face=cue.appearance_override
            override={key:face[key] for key in ('_recipe_patch','_recipe_base') if key in face}
            if language=='translation':
                child=face.get('translation',{})
                if child.get('recipe'):override['_recipe_patch']=child['recipe']
                if 'recipe_base' in child:override['_recipe_base']=child['recipe_base']
            key=(cue.style_id,freeze_json(override))
            if key not in checked:
                payload=recipe_for_cue(project.style_recipes,SimpleNamespace(style_id=cue.style_id,appearance_override=override)) or {}
                checked[key]=(not payload.get('webTheme') and FillSpec.from_value(payload.get('colors',{}).get('fill')).kind=='solid')
            if not checked[key]:return False
    return True


def _diff(before,after,path=()):
    if before is after:return
    if isinstance(before,dict) and isinstance(after,dict):
        for key in before.keys()|after.keys():
            yield from _diff(before.get(key,Missing.VALUE),after.get(key,Missing.VALUE),(*path,key))
    elif before!=after:
        yield path,(Missing.VALUE if before is Missing.VALUE else freeze_json(before)),(Missing.VALUE if after is Missing.VALUE else freeze_json(after))


def _write(root,path,value):
    result=dict(root);node=result
    for key in path[:-1]:
        child=dict(node.get(key) or {})
        node[key]=child;node=child
    if value is Missing.VALUE:node.pop(path[-1],None)
    else:node[path[-1]]=thaw_json(value)
    return result


class PaintPatchCommand(QUndoCommand):
    def __init__(self,project,entries,changed=None):
        super().__init__('修改字幕颜色')
        self.project=project;self.entries=entries;self.changed=changed
        self.changed_ids=tuple(entries)

    def _apply(self,index):
        from ..timeline.studio_commands import _commit_mutation
        def mutate():
            for cue in self.project.cues:
                patches=self.entries.get(cue.id)
                if not patches:continue
                value=cue.appearance_override
                for row in patches:value=_write(value,row[0],row[index])
                cue.appearance_override=value
                cue.appearance_generation+=1
        _commit_mutation(self.project,action_id=self.text(),dirty=(DirtyDomain.CUE_STYLE
            |DirtyDomain.TIMELINE_PIXELS|DirtyDomain.NATIVE_SUBTITLE|DirtyDomain.ADVANCED_PREVIEW|DirtyDomain.AUTOSAVE),
            cue_ids=self.changed_ids,mutate=mutate,changed=self.changed)

    def redo(self):self._apply(2)
    def undo(self):self._apply(1)


def paint_command(project,cue_ids,fields,*,layer='original',changed=None):
    """Each live cue owns its mutable maps; command leaves are immutable."""
    from .scoped_style import effective_layer_style
    from .caption_layer_transform import layer_values
    if not paint_only(fields):return None
    if any(not isinstance(value,str) or not QColor(value).isValid() for value in fields.values()):
        raise ValueError('无效的字幕颜色')
    wanted=frozenset(cue_ids);entries={};inherited={}
    translations=project.generation_metadata.get('translations',{})
    for cue in project.cues:
        if cue.id not in wanted:continue
        before=cue.appearance_override;after=dict(before)
        if layer=='original' and translations.get(cue.id):
            language=dict(after.get('translation') or {});face=dict(language.get('style') or {})
            for field in fields:
                if field not in face:
                    key=(cue.style_id,cue.base_preset_id,cue.speaker_id,
                         layer_values(cue,'translation').get('style_id'),field,before.get(field))
                    if key not in inherited:inherited[key]=getattr(effective_layer_style(project,cue,'translation'),field)
                    face[field]=inherited[key]
            language['style']=face;after['translation']=language
        if layer in ('original','group'):after.update(fields)
        if layer in ('translation','group'):
            language=dict(after.get('translation') or {});face=dict(language.get('style') or {})
            face.update(fields);language['style']=face;after['translation']=language
        patches=tuple(_diff(before,after))
        if patches:entries[cue.id]=patches
    return PaintPatchCommand(project,entries,changed) if entries else None
