"""User placement in normalized video coordinates, separate from theme motion."""
from collections.abc import Mapping
from copy import deepcopy
import math


def normalize_placement(value=None):
    value=value if isinstance(value,Mapping) else {}
    def number(key,default):
        try:n=float(value.get(key,default))
        except (TypeError,ValueError):return default
        return n if math.isfinite(n) else default
    return dict(version=1,x=number('x',.5),y=number('y',.5),
        originX=number('originX',.5),originY=number('originY',.5),
        scaleX=max(.01,min(20,number('scaleX',1))),scaleY=max(.01,min(20,number('scaleY',1))),
        rotation=number('rotation',0))


def cue_placement(project,cue):
    """Resolve old pixel Transform too, without changing saved legacy themes."""
    from .style_resolution import resolve_cue_visual
    from .visual_snapshot import _anchor
    w=max(1,int(project.render_settings.get('play_res_x',1920)))
    h=max(1,int(project.render_settings.get('play_res_y',1080)))
    baseline=deepcopy(cue)
    baseline.transform={}
    original=resolve_cue_visual(project,baseline).style
    ox,oy,_,_=_anchor(original,w,h)
    current=resolve_cue_visual(project,cue).style
    x,y,_,_=_anchor(current,w,h)
    stored=cue.transform.get('web_placement')
    if isinstance(stored,Mapping):return normalize_placement(stored)
    return normalize_placement(dict(x=x/w,y=y/h,originX=ox/w,originY=oy/h,
        scaleX=current.scale_x/max(.01,original.scale_x),scaleY=current.scale_y/max(.01,original.scale_y),
        rotation=cue.transform.get('rotation',0)))


def moved_placement(project,cue,position):
    value=cue_placement(project,cue)
    from .style_resolution import resolve_cue_visual
    from .visual_snapshot import _anchor
    w=max(1,int(project.render_settings.get('play_res_x',1920)))
    h=max(1,int(project.render_settings.get('play_res_y',1080)))
    x,y,_,_=_anchor(resolve_cue_visual(project,cue).style,w,h)
    value.update(x=value['x']+(float(position[0])-x)/w,
                 y=value['y']+(float(position[1])-y)/h)
    return normalize_placement(value)


def scaled_placement(project, cue, ratio, anchor=None):
    """Scale the complete artwork about a stable visual anchor, not its text."""
    value = cue_placement(project, cue)
    ratio = max(.01, min(20, float(ratio)))
    ax, ay = anchor or (value['x'], value['y'])
    value.update(x=ax+(value['x']-ax)*ratio, y=ay+(value['y']-ay)*ratio,
                 scaleX=value['scaleX']*ratio, scaleY=value['scaleY']*ratio)
    return normalize_placement(value)
