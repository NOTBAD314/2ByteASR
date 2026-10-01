"""Immutable caption appearance shared by native, LIVE and export consumers.

JSON strings own nested state. Accessors return copies, never mutable aliases.
Font metrics are measured before presentation and cached by font/text/width.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from .style_resolution import resolve_cue_visual_from_records
from .studio_project import SubtitleStyle
from .style_recipe import StyleRecipe, recipe_payload_for_style


def one_line_text(text):
    return re.sub(r'[\r\n\u2028\u2029]+', ' ', str(text)).replace(r'\N', ' ')


@lru_cache(maxsize=128)
def font_face(family, bold):
    from .font_metadata import resolve_local_face
    face, reason = resolve_local_face(family, bold=bold)
    return face.full_name, face.file, not reason


@lru_cache(maxsize=4096)
def fit_single_line(text, family, bold, size, spacing, max_width, scale_x,
                    weight=0, style_name='', filename='', face_index=0):
    from PIL import ImageFont
    from .font_metadata import resolve_local_face
    face, reason = resolve_local_face(family, weight, style_name, bold, filename, face_index)
    font = ImageFont.truetype(face.file, 1000, index=face.index)
    width = (font.getlength(text)/1000 * size + max(0, len(text)-1)*spacing)*scale_x
    # Measuring is read-only. Neither the authored size nor cue text/timing may
    # be rewritten by a presentation operation.
    return face.full_name, not reason, float(size), round(width, 3), width > max_width


@lru_cache(maxsize=4096)
def layout_caption(text,family,bold,size,spacing,max_width,scale_x,weight=0,style_name='',filename='',face_index=0):
    from PIL import ImageFont
    from .font_metadata import resolve_local_face
    from .caption_text_layout import wrap_caption_text
    face,reason=resolve_local_face(family,weight,style_name,bold,filename,face_index)
    font=ImageFont.truetype(face.file,1000,index=face.index)
    def measure(value):return (font.getlength(value)/1000*size+max(0,len(value)-1)*spacing)*scale_x
    result=wrap_caption_text(text,measure,max_width)
    return face.full_name,not reason,result,(sum(font.getmetrics())/1000*size)


@dataclass(frozen=True,slots=True)
class ResolvedCaptionStyle:
    style_json: str
    recipe_json: str
    text: str
    max_width: float
    measured_width: float
    font_loaded: bool
    requires_split: bool
    line_count: int = 1
    font_face_json: str = "{}"
    font_warning: str = ""

    @property
    def style(self):return SubtitleStyle(**json.loads(self.style_json))
    @property
    def recipe(self):return StyleRecipe.from_dict(json.loads(self.recipe_json))
    @property
    def style_hash(self):
        return hashlib.sha256((self.style_json+self.recipe_json+str(self.max_width)).encode()).hexdigest()
    def to_dict(self):
        return {**asdict(self),'style_hash':self.style_hash}


def resolve_caption_style(styles,speakers,cue,recipes,play_res_x=1920):
    from .visual_snapshot import _materialize_recipe_appearance
    visual=resolve_cue_visual_from_records(styles,speakers,cue)
    style=visual.style
    payload=recipe_payload_for_style(recipes,cue.style_id)
    recipe=StyleRecipe.from_dict(payload) if payload else StyleRecipe(name=style.name,motion={})
    max_width=max(1,float(play_res_x)-max(40,style.margin_l)-max(40,style.margin_r)-2*(max(style.outline_width,style.outline2_width)+style.shadow+4))
    family,loaded,layout,line_height=layout_caption(cue.text,style.font_family,style.bold,
        style.font_size,style.spacing,max_width,style.scale_x/100,
        style.font_weight,style.font_style_name,style.font_file,style.font_face_index)
    text=layout.text;size=style.font_size;width=round(max(layout.widths,default=0),3)
    # Pathological amounts of text retain the existing explicit split flag;
    # the common long-line case wraps without modifying cue data or size.
    height_limit=max(1.,float(play_res_x)*9/16-2*max(32,style.margin_v))
    requires_split=layout.overflow or len(layout.lines)*line_height*style.scale_y/100>height_limit
    from .font_metadata import resolve_local_face
    face, warning = resolve_local_face(style.font_family, style.font_weight, style.font_style_name,
        style.bold, style.font_file, style.font_face_index)
    style.font_family,style.font_size=family,size
    style.font_style_name,style.font_weight=face.style,face.weight
    if any(item.id in {getattr(cue,'base_preset_id',''),cue.style_id} for item in styles):
        recipe=_materialize_recipe_appearance(recipe,style,visual.appearance_override)
    else:
        recipe.typography.update(fontFamily=family,fontSize=size)
    recipe.layout.update(singleLine=len(layout.lines)==1,maxWidthPx=max_width,fitLocked=True,
        lineCount=len(layout.lines),lineHeightPx=line_height)
    encode=lambda value:json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return ResolvedCaptionStyle(encode(asdict(style)),encode(recipe.to_dict()),text,max_width,width,loaded,requires_split,
        line_count=len(layout.lines),font_face_json=encode(asdict(face)),font_warning=warning)


def split_overlong_caption_commands(project,cue_ids,stack,changed=None):
    """Split at the data boundary, preserving exact text and total interval.

    No new acoustic claim is made: proportional boundaries are editable. A cue
    too short to split safely stays flagged by requires_split for review.
    """
    from .studio_commands import split_cue_command
    pending=list(cue_ids);created=[]
    while pending:
        cue_id=pending.pop(0)
        cue=next((item for item in project.cues if item.id==cue_id),None)
        if cue is None:continue
        caption=resolve_caption_style(project.styles,project.speakers,cue,project.style_recipes,
            int(project.render_settings.get('play_res_x',1920)))
        if not caption.requires_split or len(cue.text)<2:continue
        duration=cue.end_ms-cue.start_ms
        if duration<100:continue
        middle=len(cue.text)//2
        # Prefer a nearby punctuation boundary while retaining punctuation.
        candidates=[i+1 for i,char in enumerate(cue.text) if char in '，。！？、,; ' and middle*.7<=i+1<=middle*1.3]
        boundary=min(candidates,key=lambda index:abs(index-middle)) if candidates else middle
        from .cue_word_alignment import cue_words, boundary_words
        words, _reason = cue_words(project, cue)
        aligned = boundary_words(words, boundary)
        if aligned is None:
            continue  # wrapping/formatting must not invent new acoustic times
        split_ms = aligned[1].start_ms
        if not cue.start_ms + 50 <= split_ms <= cue.end_ms - 50:
            continue
        old_ids={item.id for item in project.cues}
        stack.push(split_cue_command(project,cue.id,split_ms,cue.text[:boundary],cue.text[boundary:],changed))
        replacements=[item.id for item in project.cues if item.id not in old_ids or item.id==cue.id]
        created.extend(replacements);pending.extend(replacements)
    return created
