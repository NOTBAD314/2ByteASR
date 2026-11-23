"""Display-only speaker prefixes. Manuscript, translation input and word evidence stay clean."""
from __future__ import annotations
import copy
import re

KEY = 'show_speaker_names'


def enabled(state):
    return bool((state or {}).get(KEY, False))


def prefix(speaker_id, speakers):
    speaker = next((item for item in speakers if item.id == speaker_id), None)
    name = str(getattr(speaker, 'name', '') or speaker_id)
    name = re.sub(r'[\r\n\t\u2028\u2029]+', ' ', name).strip() or str(speaker_id)
    return name + '：'


def name_mark(speaker_id, speakers):
    """Display attributes of a speaker's name prefix: colour, face, weight.

    Empty fields follow the caption, so unstyled names render as before.
    """
    speaker = next((item for item in speakers if item.id == speaker_id), None)
    mark = {}
    color = str(getattr(speaker, 'name_color', '') or '').strip()
    font = str(getattr(speaker, 'name_font', '') or '').strip()
    if color:
        mark['color'] = color
    if font:
        mark['font'] = font
    if getattr(speaker, 'name_bold', False):
        mark['bold'] = True
    return mark


def prefixed_marks(marks, name, mark):
    """Body marks moved behind the name, plus the name's own mark."""
    shifted = [dict(m, start=int(m['start'])+len(name), end=int(m['end'])+len(name))
               for m in marks or () if isinstance(m, dict) and 'start' in m and 'end' in m]
    return ([dict(mark, start=0, end=len(name))] if mark else []) + shifted


def apply_name_marks(cue):
    """Re-anchor a decorated display copy's marks after its body marks changed."""
    name = getattr(cue, '_speaker_name_prefix', '')
    if not name or not str(cue.text).startswith(name):
        return cue
    from collections.abc import Mapping
    override = cue.appearance_override or {}
    if not isinstance(override, Mapping):
        from ..projects.studio_revisions import thaw_json
        override = thaw_json(override) or {}
    override = copy.deepcopy(dict(override))
    marks =prefixed_marks(override.get('text_marks', []), name, getattr(cue, '_speaker_name_mark', {}))
    if marks or 'text_marks' in override:
        override['text_marks'] = marks
        cue.appearance_override = override
    return cue


def decorate(cue, speakers):
    if not str(cue.text).strip() or getattr(cue, '_speaker_name_prefix', ''):
        return cue
    result = copy.copy(cue)
    result._speaker_name_body = cue.text
    result._speaker_name_prefix = prefix(cue.speaker_id, speakers)
    result._speaker_name_mark = name_mark(cue.speaker_id, speakers)
    result.text = result._speaker_name_prefix + cue.text
    # Marks are stored on the copy, so frozen/exported display cues keep them.
    return apply_name_marks(result)


def display_text_cues(project, cues):
    return [decorate(cue, project.speakers) for cue in cues] if enabled(project.studio_state) else list(cues)


def constrain_layout(cues, styles, speakers, width=1920, height=1080):
    """Keep display text inside its anchor's space, including nearby speakers.

    Only derived cue copies receive a layout width. Original transforms, font size,
    text and acoustic evidence are unchanged. Existing renderers then wrap
    the name and body together using their shared measured text layout.
    """
    from .style_resolution import resolve_cue_visual_from_records
    rows=[]
    for cue in cues:
        style=resolve_cue_visual_from_records(styles,speakers,cue).style
        column=(style.alignment-1)%3;row=(style.alignment-1)//3
        x=float(style.position_x if style.position_x is not None else
            (style.margin_l,width/2,width-style.margin_r)[column])
        y=float(style.position_y if style.position_y is not None else
            (height-style.margin_v,height/2,style.margin_v)[row])
        rows.append(dict(cue=cue,style=style,x=x,y=y,column=column,
                         left=max(40,style.margin_l),right=width-max(40,style.margin_r)))
    active=[]
    for item in sorted(rows,key=lambda item:item['cue'].start_ms):
        active=[old for old in active if old['cue'].end_ms>item['cue'].start_ms]
        for old in active:
            if old['cue'].speaker_id==item['cue'].speaker_id:
                continue
            em=max(old['style'].font_size,item['style'].font_size)
            if abs(old['x']-item['x'])<em or abs(old['y']-item['y'])>max(160,3*em):
                continue
            left,right=sorted((old,item),key=lambda row:row['x'])
            midpoint=(left['x']+right['x'])/2
            left['right']=min(left['right'],midpoint-8)
            right['left']=max(right['left'],midpoint+8)
        active.append(item)
    result=[]
    for item in rows:
        cue,style,x=item['cue'],item['style'],item['x']
        available=(item['right']-x,2*min(x-item['left'],item['right']-x),x-item['left'])[item['column']]
        available=max(float(style.font_size)*2,available)
        original_width=width-max(40,style.margin_l)-max(40,style.margin_r)
        if available<original_width:
            cue=copy.copy(cue)
            cue.transform=dict(cue.transform or {},_name_layout_width=available)
        result.append(cue)
    return result
