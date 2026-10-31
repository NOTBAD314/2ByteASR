"""Immutable caption appearance shared by native, LIVE and export consumers.

JSON strings own nested state. Accessors return copies, never mutable aliases.
Font metrics are measured before presentation and cached by font/text/width.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from functools import lru_cache
from collections import OrderedDict
import threading
import hashlib
import json
import os
from pathlib import Path
import re
from .style_resolution import resolve_cue_visual_from_records
from ..projects.studio_project import SubtitleStyle
from .style_recipe import StyleRecipe, recipe_payload_for_style


def one_line_text(text):
    return re.sub(r'[\r\n\u2028\u2029]+', ' ', str(text)).replace(r'\N', ' ')


@lru_cache(maxsize=128)
def font_face(family, bold):
    from .font_metadata import resolve_local_face
    face, reason = resolve_local_face(family, bold=bold)
    return face.full_name, face.file, not reason


# 2026-10-22 (report-eb10): one entry per caption text and style. A bilingual
# project with 2090 cues needs ~4180; with 4096 slots every rebuild of the
# caption preview walked the project in order and missed every time (an LRU
# smaller than a cyclic pass never hits). Room for a 10,000-cue bilingual one.
MEASURE_CACHE_SIZE = 32768
_MEASUREMENT_FONTS = threading.local()


def _measurement_font(filename, size, index=0):
    """Four font faces per measurement thread, shared by texts at one size.

    FreeType objects stay thread-local; the bounded cache holds no bitmaps.
    Identity includes actual file metadata so replacing a font retires its face.
    """
    from PIL import ImageFont
    stat = os.stat(filename)
    key = (filename, int(size), int(index), stat.st_size, stat.st_mtime_ns)
    fonts = getattr(_MEASUREMENT_FONTS, 'faces', None)
    if fonts is None:
        fonts = _MEASUREMENT_FONTS.faces = OrderedDict()
    font = fonts.get(key)
    if font is None:
        font = ImageFont.truetype(filename, size, index=index)
        fonts[key] = font
        while len(fonts) > 4:
            fonts.popitem(last=False)
    else:
        fonts.move_to_end(key)
    return font


@lru_cache(maxsize=MEASURE_CACHE_SIZE)
def fit_single_line(text, family, bold, size, spacing, max_width, scale_x,
                    weight=0, style_name='', filename='', face_index=0):
    from PIL import ImageFont
    from .font_metadata import resolve_local_face
    face, reason = resolve_local_face(family, weight, style_name, bold, filename, face_index)
    font = _measurement_font(face.file, 1000, index=face.index)
    width = (font.getlength(text)/1000 * size + max(0, len(text)-1)*spacing)*scale_x
    # Measuring is read-only. Neither the authored size nor cue text/timing may
    # be rewritten by a presentation operation.
    return face.full_name, not reason, float(size), round(width, 3), width > max_width


@lru_cache(maxsize=MEASURE_CACHE_SIZE)
def layout_caption(text,family,bold,size,spacing,max_width,scale_x,weight=0,style_name='',filename='',face_index=0):
    from PIL import ImageFont
    from .font_metadata import resolve_local_face
    from .caption_text_layout import wrap_caption_text
    face,reason=resolve_local_face(family,weight,style_name,bold,filename,face_index)
    font=_measurement_font(face.file,1000,index=face.index)
    def measure(value):return (font.getlength(value)/1000*size+max(0,len(value)-1)*spacing)*scale_x
    result=wrap_caption_text(text,measure,max_width)
    return face.full_name,not reason,result,(sum(font.getmetrics())/1000*size)


@lru_cache(maxsize=1024)
def _font_ascent(filename, face_index, size):
    from PIL import ImageFont
    return _measurement_font(filename, 1000, index=face_index).getmetrics()[0]/1000*size


@lru_cache(maxsize=MEASURE_CACHE_SIZE)
def _caption_ink_bounds(text, filename, face_index, size, spacing, line_height, ascent, line_widths, anchor_x):
    """Actual fill bounds in design pixels, without stroke/shadow outsets.

    Pillow's getbbox includes the advance of terminal punctuation/spaces; the
    nonzero mask bounds distinguish that blank advance from visible glyphs.
    Limit sampling to 128 px per em and cache only four floats, never bitmaps.
    """
    from PIL import ImageFont
    sample_size = max(16, min(128, round(size)))
    font = _measurement_font(filename, sample_size, index=face_index)
    scale = size/sample_size
    baseline_correction = ascent-font.getmetrics()[0]*scale
    widest = max(line_widths, default=0.)
    boxes = []
    for index, line in enumerate(text.split('\n')):
        if not line.strip():
            continue
        mask, offset = font.getmask2(line, mode='L')
        box = mask.getbbox()
        if box is None:
            continue
        left_spaces = len(line)-len(line.lstrip())
        last_visible = len(line.rstrip())-1
        x = (widest-line_widths[index])*anchor_x
        y = index*line_height+baseline_correction
        boxes.append((x+(offset[0]+box[0])*scale+left_spaces*spacing,
                      y+(offset[1]+box[1])*scale,
                      x+(offset[0]+box[2])*scale+max(0, last_visible)*spacing,
                      y+(offset[1]+box[3])*scale))
    if not boxes:
        return (0., 0., 0., 0.)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


@lru_cache(maxsize=MEASURE_CACHE_SIZE)
def visible_glyph_size(text, family, bold, size, spacing, weight=0,
                       style_name='', filename='', face_index=0):
    """Ink bounds of the actual face, excluding ascent/descent line-box slack.

    Newlines retain the face's baseline advance.  This is the same anchoring
    contract as LIVE's glyph path, before stroke/shadow/background outsets.
    No selection-frame padding or preview-widget scale enters this measure.
    """
    from PIL import ImageFont
    from .font_metadata import resolve_local_face
    face, _ = resolve_local_face(family, weight, style_name, bold, filename, face_index)
    font = _measurement_font(face.file, 1000, index=face.index)
    advance = sum(font.getmetrics())
    boxes = []
    for index, line in enumerate(str(text).split('\n')):
        if not line.strip():
            continue
        left, top, right, bottom = font.getbbox(line)
        boxes.append((left, top + index * advance,
                      right + max(0, len(line)-1) * spacing * 1000 / max(1, size),
                      bottom + index * advance))
    if not boxes:
        return 0., 0.
    return ((max(b[2] for b in boxes)-min(b[0] for b in boxes))*size/1000,
            (max(b[3] for b in boxes)-min(b[1] for b in boxes))*size/1000)


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
    layout_json: str = "{}"

    @property
    def style(self):return SubtitleStyle(**json.loads(self.style_json))
    @property
    def recipe(self):return StyleRecipe.from_dict(json.loads(self.recipe_json))
    @property
    def layout(self):return json.loads(self.layout_json)
    @property
    def style_hash(self):
        return hashlib.sha256((self.style_json+self.recipe_json+str(self.max_width)).encode()).hexdigest()
    def to_dict(self):
        return {**asdict(self),'style_hash':self.style_hash}


def resolve_caption_style(styles,speakers,cue,recipes,play_res_x=1920,play_res_y=None):
    from .visual_snapshot import _materialize_recipe_appearance
    visual=resolve_cue_visual_from_records(styles,speakers,cue)
    style=visual.style
    from .style_resolution import recipe_for_cue
    payload=recipe_for_cue(recipes,cue)
    recipe=StyleRecipe.from_dict(payload) if payload else StyleRecipe(name=style.name,motion={})
    max_width=max(1,float(play_res_x)-max(40,style.margin_l)-max(40,style.margin_r)-2*(max(style.outline_width,style.outline2_width)+style.shadow+4))
    max_width/=max(1.,float(visual.transform.get('_motion_layout_scale',1.)))
    # A derived name-display cue can reserve space around its unchanged
    # anchor. This render-only width also survives immutable worker copies.
    name_width=visual.transform.get('_name_layout_width')
    if isinstance(name_width,(int,float)) and name_width>0:
        max_width=min(max_width,max(1,name_width-2*(max(style.outline_width,style.outline2_width)+style.shadow+4)))
    family,loaded,layout,line_height=layout_caption(cue.text,style.font_family,style.bold,
        style.font_size,style.spacing,max_width,style.scale_x/100,
        style.font_weight,style.font_style_name,style.font_file,style.font_face_index)
    text=layout.text;size=style.font_size;width=round(max(layout.widths,default=0),3)
    # Pathological amounts of text retain the existing explicit split flag;
    # the common long-line case wraps without modifying cue data or size.
    # Older callers supplied only a width; keep their 16:9 default while all
    # preview/export entry points pass the actual design canvas explicitly.
    play_res_y = float(play_res_y if play_res_y is not None else float(play_res_x)*9/16)
    height_limit=max(1.,play_res_y-2*max(32,style.margin_v))
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
    line_count = len(layout.lines)
    line_widths = tuple(value / max(.01, style.scale_x/100) for value in layout.widths)
    ascent = _font_ascent(face.file, face.index, size)
    line_heights = (line_height,) * line_count
    line_ascents = (ascent,) * line_count
    anchor_x = ((style.alignment-1) % 3)/2
    ink_bounds = None
    from .text_marks import layer_marks
    marks = layer_marks(cue)
    if marks and not recipe.web_theme:
        from ..rendering.marked_glyphs import wrap_marked_text
        text,width,line_height,line_count,line_widths,line_heights,line_ascents,ink_bounds = wrap_marked_text(
            cue.text,style,marks,max_width,details=True)
        requires_split = width*style.scale_x/100 > max_width+1 or line_count*line_height*style.scale_y/100 > height_limit
        width = round(width*style.scale_x/100, 3)
    from .caption_text_layout import line_source_ranges
    if ink_bounds is None:
        ink_bounds = _caption_ink_bounds(text, face.file, face.index, size, style.spacing,
                                         line_height, ascent, tuple(line_widths), anchor_x)
    lines = text.split('\n')
    ranges = line_source_ranges(cue.text, lines)
    baseline = 0.
    records = []
    for index, (line, source_range) in enumerate(zip(lines, ranges)):
        records.append(dict(source_range, text=line, widthPx=line_widths[index],
                            baselinePx=baseline+line_ascents[index]))
        baseline += line_height
    layout_data = {
        'version': 1, 'playResX': float(play_res_x), 'playResY': play_res_y,
        'sourceLength': len(cue.text), 'displayLength': len(text),
        'offsetUnit': 'unicode-code-point', 'lineCount': line_count,
        'lineHeightPx': line_height, 'lines': records, 'maxWidthPx': max_width,
        'availableHeightPx': height_limit,
        'boundsPx': [0., 0., width, baseline*style.scale_y/100],
        'anchorKind': 'glyph-ink', 'inkBoundsPx': list(ink_bounds),
        'lineBoxWidthPx': max(line_widths, default=0.), 'lineBoxHeightPx': baseline,
        'overflow': bool(requires_split),
        'font': {**asdict(face), 'sizePx': size, 'letterSpacingPx': style.spacing,
                 'loaded': loaded, 'warning': warning},
    }
    recipe.layout.update(singleLine=line_count==1,maxWidthPx=max_width,fitLocked=True,
        lineCount=line_count,lineHeightPx=line_height)
    encode=lambda value:json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return ResolvedCaptionStyle(encode(asdict(style)),encode(recipe.to_dict()),text,max_width,width,loaded,requires_split,
        line_count=line_count,font_face_json=encode(asdict(face)),font_warning=warning,
        layout_json=encode(layout_data))


def split_overlong_caption_commands(project,cue_ids,stack,changed=None):
    """Split at the data boundary, preserving exact text and total interval.

    No new acoustic claim is made: proportional boundaries are editable. A cue
    too short to split safely stays flagged by requires_split for review.
    """
    from ..timeline.studio_commands import split_cue_command
    pending=list(cue_ids);created=[]
    while pending:
        cue_id=pending.pop(0)
        cue=next((item for item in project.cues if item.id==cue_id),None)
        if cue is None:continue
        caption=resolve_caption_style(project.styles,project.speakers,cue,project.style_recipes,
            int(project.render_settings.get('play_res_x',1920)),int(project.render_settings.get('play_res_y',1080)))
        if not caption.requires_split or len(cue.text)<2:continue
        duration=cue.end_ms-cue.start_ms
        if duration<100:continue
        middle=len(cue.text)//2
        # Prefer a nearby punctuation boundary while retaining punctuation.
        candidates=[i+1 for i,char in enumerate(cue.text) if char in '，。！？、,; ' and middle*.7<=i+1<=middle*1.3]
        boundary=min(candidates,key=lambda index:abs(index-middle)) if candidates else middle
        from ..recognition.cue_word_alignment import cue_words, boundary_words
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
