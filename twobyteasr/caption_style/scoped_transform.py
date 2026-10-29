"""Absolute fields and relative canvas gestures share one layer transaction."""
import copy
import math
from .caption_layer_transform import GeometryBatch,GEOMETRY,LAYER_KEY,presentation_command,target_ids


def edit_values(before,changes,*,reference=None,owner=None,mode='absolute',linked=False):
    result=dict(before);delta=dict(changes);reference=reference or before;owner=owner or before
    if mode=='delta':
        for key in ('position_x','position_y'):
            if key in delta:delta[key]=before[key]+delta[key]-reference[key]
    if mode=='ratio':
        for key in ('scale_x','scale_y'):
            if key in delta:delta[key]=before[key]*delta[key]/reference[key]
    if linked:
        pivot_x=owner['position_x'];pivot_y=owner['position_y']
        dest_x=(owner['position_x']+changes.get('position_x',reference['position_x'])-reference['position_x']
                if mode=='delta' else changes.get('position_x',pivot_x))
        dest_y=(owner['position_y']+changes.get('position_y',reference['position_y'])-reference['position_y']
                if mode=='delta' else changes.get('position_y',pivot_y))
        sx=changes.get('scale_x',reference['scale_x'] if mode=='ratio' else owner['scale_x'])/(reference['scale_x'] if mode=='ratio' else owner['scale_x'])
        sy=changes.get('scale_y',reference['scale_y'] if mode=='ratio' else owner['scale_y'])/(reference['scale_y'] if mode=='ratio' else owner['scale_y'])
        if owner['scale_link'] and len({'scale_x','scale_y'} & changes.keys())==1:
            if 'scale_x' in changes:sy=sx
            else:sx=sy
        rotation=changes.get('rotation',owner['rotation'])-owner['rotation']
        angle=math.radians(rotation);x=(before['position_x']-pivot_x)*sx;y=(before['position_y']-pivot_y)*sy
        if {'position_x','position_y','scale_x','scale_y','rotation'} & changes.keys():
            delta.update(position_x=dest_x+x*math.cos(angle)-y*math.sin(angle),position_y=dest_y+x*math.sin(angle)+y*math.cos(angle))
        for key,factor in (('scale_x',sx),('scale_y',sy)):
            if key in changes or (owner['scale_link'] and {'scale_x','scale_y'} & changes.keys()):delta[key]=before[key]*factor
        if 'rotation' in changes:delta['rotation']=before['rotation']+rotation
    scale_keys={'scale_x','scale_y'} & delta.keys()
    if before['scale_link'] and len(scale_keys)==1:
        key=next(iter(scale_keys));other='scale_y' if key=='scale_x' else 'scale_x'
        delta[other]=before[other]*delta[key]/before[key]
    result.update(delta)
    return result


def transform_command(project,cue_ids,language,changes,*,mode='absolute',reference_id=None,reset=False,changed=None):
    if language=='group':language='linked'
    if language not in {'original','translation','linked'}:raise ValueError('unknown language layer')
    if mode not in {'absolute','delta','ratio'}:raise ValueError('unknown transform semantics')
    for key,value in changes.items():
        if key=='scale_link':
            if not isinstance(value,bool):raise ValueError('scale_link must be boolean')
        elif key not in GEOMETRY or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('invalid transform field')
        elif key.startswith('anchor_') and not 0<=value<=1:raise ValueError('anchor outside [0,1]')
        elif key in {'scale_x','scale_y','font_size'} and value<=0:raise ValueError('scale must be positive')
    wanted=target_ids(project,cue_ids);targets=[c for c in project.cues if c.id in wanted]
    if not targets:return None
    cache=GeometryBatch(project);ref=next((c for c in targets if c.id==reference_id),targets[0])
    primary='original' if language=='linked' else language;reference=cache.values(ref,primary)
    if reference is None:return None
    transforms={}
    from .caption_group_transform import inverse_changes
    for cue in targets:
        transform=copy.deepcopy(cue.transform or {});layers=transform.setdefault(LAYER_KEY,{})
        owner=cache.values(cue,primary)
        for layer in (('original','translation') if language=='linked' else (language,)):
            if reset:
                value=layers.get(layer,{})
                for key in GEOMETRY|{'scale_link'}:value.pop(key,None)
                if not value:layers.pop(layer,None)
                continue
            before=cache.values(cue,layer)
            if before is None:continue
            after=edit_values(before,changes,reference=reference,owner=owner,mode=mode,linked=language=='linked')
            delta={key:value for key,value in after.items() if key in GEOMETRY|{'scale_link'} and (value!=before[key] or key in changes)}
            if delta:layers.setdefault(layer,{}).update(inverse_changes(project,cue,delta))
        if not layers:transform.pop(LAYER_KEY,None)
        transforms[cue.id]=transform
    return presentation_command(project,targets,transforms,changed=changed)
