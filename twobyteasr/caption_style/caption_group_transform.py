"""Project-wide affine geometry after bilingual layout, before rendering.

The shared transform moves original/translation as a group and preserves saved
speaker avoidance. Per-cue edits are stored in inverse coordinates so disabling
linking changes only the selection. No text, word evidence or timing is touched.
"""
import copy
from dataclasses import replace
from PySide6.QtGui import QUndoCommand

KEY='caption_group_transform'
LINK_KEY='caption_global_link'
DEFAULT=dict(dx=0.,dy=0.,sx=1.,sy=1.)


def values(project):
    return dict(DEFAULT, **(project.studio_state.get(KEY) or {}))


def anchor(project,cue):
    from .style_resolution import resolve_cue_visual
    from .visual_snapshot import _anchor
    width=int(project.render_settings.get('play_res_x',1920))
    height=int(project.render_settings.get('play_res_y',1080))
    style=resolve_cue_visual(project,cue).style
    return _anchor(style,width,height)[:2]


def inverse_changes(project,cue,changes):
    shared=values(project)
    needs_pivot=any(key in changes and shared['s'+axis]!=1 for key,axis in (('position_x','x'),('position_y','y')))
    x,y=anchor(project,cue) if needs_pivot else (0.,0.)
    delta=dict(changes)
    for key,axis,pivot in (('position_x','x',x),('position_y','y',y)):
        if key in delta:delta[key]=pivot+(delta[key]-shared['d'+axis]-pivot)/shared['s'+axis]
    for key,axis in (('scale_x','x'),('scale_y','y')):
        if key in delta:delta[key]/=shared['s'+axis]
    return delta


def apply_display(rows,source,shared,styles,speakers,recipes,width,height):
    if not shared:return rows
    from types import SimpleNamespace
    from .bilingual_layout import companion_id
    from .resolved_caption_style import resolve_caption_style
    from .visual_snapshot import _anchor
    project=SimpleNamespace(styles=styles,speakers=speakers,style_recipes=recipes,
        render_settings={'play_res_x':width,'play_res_y':height})
    owners={c.id:c for c in source}
    owners.update({companion_id(c.id):c for c in source})
    shared=dict(DEFAULT,**shared)
    pivots={}
    out=[]
    for row in rows:
        if (row.transform or {}).get('_group_materialized'):
            out.append(row);continue
        owner=owners[row.id]
        if owner.id not in pivots:pivots[owner.id]=anchor(project,owner)
        px,py=pivots[owner.id]
        style=resolve_caption_style(styles,speakers,row,recipes,width).style
        x,y,*_=_anchor(style,width,height)
        shown=copy.deepcopy(row)
        from .caption_layer_transform import GEOMETRY
        shown.transform.setdefault('_geometry_base',{k:v for k,v in row.transform.items() if k in GEOMETRY})
        shown.transform=dict(shown.transform or {},position_x=px+(x-px)*shared['sx']+shared['dx'],
            position_y=py+(y-py)*shared['sy']+shared['dy'],
            scale_x=style.scale_x*shared['sx'],scale_y=style.scale_y*shared['sy'],
            _canvas_transform=True,_group_materialized=True)
        out.append(shown)
    return out


class GroupTransformCommand(QUndoCommand):
    def __init__(self,project,after,changed=None,*,label='全局联动字幕位置与缩放',transforms=None):
        super().__init__(label)
        self.project=project;self.changed=changed
        self.before=copy.deepcopy(project.studio_state.get(KEY))
        self.after=copy.deepcopy(after)
        self.after_cues=copy.deepcopy(transforms or {})
        self.before_cues={c.id:copy.deepcopy(c.transform) for c in project.cues if c.id in self.after_cues}

    def apply(self,shared,transforms):
        from ..timeline.studio_commands import _commit_mutation
        from ..projects.studio_runtime_state import DirtyDomain
        def mutate():
            if shared is None:self.project.studio_state.pop(KEY,None)
            else:self.project.studio_state[KEY]=copy.deepcopy(shared)
            for cue in self.project.cues:
                if cue.id in transforms:cue.transform=copy.deepcopy(transforms[cue.id])
        _commit_mutation(self.project,action_id=self.text(),
            dirty=(DirtyDomain.NATIVE_SUBTITLE|DirtyDomain.ADVANCED_PREVIEW|DirtyDomain.TRANSFORM|
                   DirtyDomain.TIMELINE_PIXELS|DirtyDomain.AUTOSAVE|DirtyDomain.PROJECT_METADATA),
            cue_ids=tuple(transforms),mutate=mutate,changed=self.changed)

    def redo(self):self.apply(self.after,self.after_cues)
    def undo(self):self.apply(self.before,self.before_cues)


def shared_after(project,cue,language,changes,*,reset=False,current=None,pivot=None):
    if reset:return dict(DEFAULT)
    from .caption_layer_transform import resolved_values
    current=current or resolved_values(project,cue,language)
    before=values(project);after=dict(before)
    changes=dict(changes)
    scale_keys={'scale_x','scale_y'} & changes.keys()
    if current['scale_link'] and len(scale_keys)==1:
        key=next(iter(scale_keys));other='scale_y' if key=='scale_x' else 'scale_x'
        changes[other]=current[other]*changes[key]/current[key]
    px,py=pivot or anchor(project,cue)
    for axis,pivot in (('x',px),('y',py)):
        pos='position_'+axis;scale='scale_'+axis
        if scale in changes:
            factor=changes[scale]/current[scale]
            after['s'+axis]*=factor
            # Keep the edited row's anchor fixed while scaling the whole group.
            after['d'+axis]=current[pos]-pivot-(current[pos]-before['d'+axis]-pivot)*factor
        if pos in changes:after['d'+axis]+=changes[pos]-current[pos]
    return after


def reset_group_command(project,changed=None):
    transforms={}
    fields={'position_x','position_y','scale_x','scale_y'}
    for cue in project.cues:
        transform=copy.deepcopy(cue.transform or {})
        for key in fields:transform.pop(key,None)
        for layer in transform.get('language_layers',{}).values():
            for key in fields:layer.pop(key,None)
        transforms[cue.id]=transform
    return GroupTransformCommand(project,None,changed,label='重设全部字幕位置与缩放',transforms=transforms)


def apply_all_command(project,reference,changed=None):
    from .caption_layer_transform import resolved_values,LAYER_KEY
    # Copy geometry only; use the selected bilingual pair, retaining its gap.
    geometry={language:resolved_values(project,reference,language) for language in ('original','translation')}
    transforms={}
    for cue in project.cues:
        transform=copy.deepcopy(cue.transform or {})
        layers=transform.setdefault(LAYER_KEY,{})
        initial=transform.get('initial_layout') or {}
        reference_initial=(reference.transform or {}).get('initial_layout') or {}
        # Saved speaker-row offsets remain separate from the manual group base.
        offsets={axis:float(initial.get('position_'+axis,0))-float(reference_initial.get('position_'+axis,0))
                 if initial.get('version')==reference_initial.get('version')==1 else 0. for axis in ('x','y')}
        for language,value in geometry.items():
            if value is None:continue
            fields={k:value[k] for k in ('position_x','position_y','scale_x','scale_y')}
            for axis in ('x','y'):fields['position_'+axis]+=offsets[axis]
            layers.setdefault(language,{}).update(fields)
        transforms[cue.id]=transform
    # New cues inherit the same group base: an affine delta relative to the
    # reference's unmodified default. Existing cues retain exact copied values.
    defaults={language:{k:value[k] for k in ('position_x','position_y','scale_x','scale_y')}
              for language,value in geometry.items() if value is not None}
    return GroupTransformCommand(project,dict(DEFAULT,defaults=defaults),changed,
        label='将当前位置与缩放套用至全部字幕',transforms=transforms)
