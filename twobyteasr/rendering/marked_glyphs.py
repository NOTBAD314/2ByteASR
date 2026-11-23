"""Shape marked text once with Qt's Unicode layout, retaining glyph ownership."""
from collections import OrderedDict
import json
import threading
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QTextLayout, QTextCharFormat, QTextFormat
from ..caption_style.text_marks import runs, utf16_offset, python_offset, heading_level, heading_scale


_SHAPES = OrderedDict()
STRIKE_COLOR = '#FF4D6D'   # ~~struck~~ bar in the live / burned-in caption (2026-11-20)
_SHAPE_LOCK = threading.RLock()


def shape_marked_text(text, font, marks, anchor_x, line_height=None):
    key = (text, font.toString(), font.pixelSize(), json.dumps(marks, sort_keys=True), anchor_x, line_height)
    with _SHAPE_LOCK:
        cached = _SHAPES.get(key)
        if cached is not None:
            _SHAPES.move_to_end(key)
            return QPainterPath(cached[0]), [(QPainterPath(p), i, c) for p,i,c in cached[1]]
    result = _shape_marked_text(text, font, marks, anchor_x, line_height)
    with _SHAPE_LOCK:
        _SHAPES[key] = result
        while len(_SHAPES) > 256: _SHAPES.popitem(last=False)
    return QPainterPath(result[0]), [(QPainterPath(p), i, c) for p,i,c in result[1]]


def _char_format(font, attrs):
    fmt = QTextCharFormat()
    level = heading_level(attrs)
    if 'bold' in attrs or 'italic' in attrs or attrs.get('font') or level: fmt.setFontStyleName('')
    if attrs.get('font'): fmt.setFontFamilies([str(attrs['font'])])
    if 'bold' in attrs: fmt.setFontWeight(max(int(font.weight()),700) if attrs['bold'] else 400)
    elif level: fmt.setFontWeight(max(int(font.weight()),700))
    if 'italic' in attrs: fmt.setFontItalic(bool(attrs['italic']))
    if level and font.pixelSize() > 0:
        fmt.setProperty(QTextFormat.Property.FontPixelSize, max(1, round(font.pixelSize()*heading_scale(attrs))))
    return fmt


def _strike_rect(size, point, advance):
    """Glyph paths carry no decoration: strike-through is a bar across the advance.

    As thick and as high as 问问兔白's bubble line (tour_mascot.MarkedLabel): a thin
    bar vanishes into heavy CJK strokes (了 + a thin bar reads as 子). ``size`` is the
    layout's own pixel size: a fallback run's raw font can report 0."""
    size = max(1.0, float(size))
    thickness = max(1.5, size/8.0)
    path = QPainterPath()
    path.addRect(QRectF(point.x(), point.y()-size*0.36-thickness/2, max(0.0, advance), thickness))
    return path


def _shape_marked_text(text, font, marks, anchor_x, line_height=None):
    shaped = []
    widths = []
    y = 0.0
    start = 0
    for line_text in text.split('\n'):
        layout = QTextLayout(line_text, font)
        segments = [(max(0,a-start), min(len(line_text),b-start), attrs)
                    for a,b,attrs in runs(text, marks) if a < start+len(line_text) and b > start]
        formats = []
        for a,b,attrs in segments:
            item = QTextLayout.FormatRange()
            item.start, item.length, item.format = utf16_offset(line_text,a), utf16_offset(line_text,b)-utf16_offset(line_text,a), _char_format(font, attrs)
            formats.append(item)
        layout.setFormats(formats)
        layout.beginLayout(); line = layout.createLine()
        line.setLineWidth(1e7); line.setPosition(QPointF(0, y)); layout.endLayout()
        width = line.naturalTextWidth(); widths.append(width)
        flags = QTextLayout.GlyphRunRetrievalFlag.RetrieveAll
        glyphs = []
        for run in layout.glyphRuns(0, -1, flags):
            raw_font = run.rawFont()
            indexes = run.glyphIndexes()
            advances = raw_font.advancesForGlyphIndexes(indexes) if any(v.get('strike') for _a,_b,v in segments) else ()
            for number, (index, point, string_index) in enumerate(zip(indexes, run.positions(), run.stringIndexes())):
                cp = python_offset(line_text, int(string_index))
                attrs = next((v for a,b,v in segments if a <= cp < b), {})
                path = raw_font.pathForGlyph(index)
                path.setFillRule(Qt.WindingFill)
                path.translate(point)
                bar = None
                if attrs.get('strike') and number < len(advances):
                    # united, not addPath: a rect against the glyph's winding could punch a hole.
                    size = font.pixelSize()*heading_scale(attrs) if font.pixelSize() > 0 else raw_font.pixelSize()
                    bar = _strike_rect(size, point, advances[number].x())
                    path = path.united(bar)
                    path.setFillRule(Qt.WindingFill)
                glyphs.append((path, start+cp, attrs.get('color') or ('#FFD166' if attrs.get('highlight') else '')))
                if bar is not None:
                    # The bar is painted again on top in its own colour: in the text's
                    # colour it merges into the strokes (了 + bar reads as 子).
                    glyphs.append((bar, start+cp, STRIKE_COLOR))
        shaped.append((width, glyphs))
        y += line_height if line_height is not None else line.height()
        start += len(line_text)+1
    widest = max(widths, default=0)
    path = QPainterPath(); path.setFillRule(Qt.WindingFill); pieces = []
    for width, glyphs in shaped:
        for glyph, index, color in glyphs:
            glyph.translate((widest-width)*anchor_x, 0)
            path.addPath(glyph); pieces.append((glyph, index, color))
    return path, pieces


def wrap_marked_text(text, style, marks, max_width, *, details=False):
    """Fit actual bold/italic glyph advances instead of the unmarked base face."""
    from PySide6.QtGui import QFont, QTextOption, QFontMetricsF
    from ..caption_style.caption_text_layout import normalized_caption_text
    from ..caption_style.text_marks import remap_marks
    normalized = normalized_caption_text(text)
    if normalized != text:
        marks = remap_marks(text, normalized, marks)
        text = normalized
    font = QFont(style.font_family)
    font.setPixelSize(max(1, round(style.font_size)))
    font.setWeight(QFont.Weight(style.font_weight or (700 if style.bold else 400)))
    font.setItalic(style.italic)
    font.setLetterSpacing(QFont.AbsoluteSpacing, style.spacing)
    output, widths, heights, ascents, offset = [], [], [], [], 0
    for paragraph in text.split('\n'):
        layout = QTextLayout(paragraph, font)
        option = QTextOption(); option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        formats = []
        for a,b,attrs in runs(text, marks):
            lo,hi = max(0,a-offset),min(len(paragraph),b-offset)
            if lo >= hi: continue
            item=QTextLayout.FormatRange()
            item.start,item.length,item.format=utf16_offset(paragraph,lo),utf16_offset(paragraph,hi)-utf16_offset(paragraph,lo),_char_format(font,attrs)
            formats.append(item)
        layout.setFormats(formats);layout.beginLayout()
        if not paragraph:
            metrics = QFontMetricsF(font)
            output.append(''); widths.append(0.); heights.append(metrics.height()); ascents.append(metrics.ascent())
        while paragraph:
            line=layout.createLine()
            if not line.isValid(): break
            line.setLineWidth(max(1,max_width/max(.01,style.scale_x/100)))
            a,b=python_offset(paragraph,line.textStart()),python_offset(paragraph,line.textStart()+line.textLength())
            output.append(paragraph[a:b]);widths.append(line.naturalTextWidth());heights.append(line.height());ascents.append(line.ascent())
        layout.endLayout();offset+=len(paragraph)+1
    result = ('\n'.join(output),max(widths,default=0),max(heights,default=style.font_size*1.2),len(output))
    if details:
        from types import SimpleNamespace
        from ..caption_style.caption_text_layout import line_source_ranges
        from ..caption_style.text_marks import remap_caption_marks
        displayed = SimpleNamespace(text=result[0], layout={'lines': line_source_ranges(text, output)})
        mapped = remap_caption_marks(text, displayed, marks)
        path, _pieces = shape_marked_text(result[0], font, mapped, ((style.alignment-1) % 3)/2, result[2])
        ink = path.boundingRect()
        return (*result, tuple(widths), tuple(heights), tuple(ascents),
                (ink.left(), ink.top(), ink.right(), ink.bottom()))
    return result


def _ass_font_name(family):
    return ''.join(c for c in str(family) if c not in '\\{}\r\n').strip()


def _ass_size(value):
    return f"{float(value):.2f}".rstrip('0').rstrip('.')


def marked_ass_text(text, marks, style, extra_tags="", *, sized=None, struck=None):
    """``sized`` / ``struck`` force the \\fs / \\s reset on every run: a word-timed
    caption is compiled piece by piece, and a heading or strike must not leak."""
    from .ass_compiler import escape_ass_text
    from ..caption_style.effect_dsl import _ass_color
    output = []
    pieces = runs(text, marks)
    fonted = any(attrs.get('font') for _a, _b, attrs in pieces)
    sized = any(heading_level(attrs) for _a, _b, attrs in pieces) if sized is None else sized
    struck = any(attrs.get('strike') for _a, _b, attrs in pieces) if struck is None else struck
    for a,b,attrs in pieces:
        level = heading_level(attrs)
        bold =max(int(style.font_weight or 400),700) if attrs.get('bold', style.bold or bool(level)) else 400
        italic = int(attrs.get('italic', style.italic))
        color = attrs.get('color') or ('#FFD166' if attrs.get('highlight') else style.primary_color)
        # ASS style colours include alpha; the inline 1c tag takes only BGR.
        value = _ass_color(color)
        # After a run with its own face, an empty \fn returns to the style's face,
        # so a styled speaker name never leaks into the body.
        face = ('\\fn'+_ass_font_name(attrs.get('font') or '')) if fonted else ''
        size = ('\\fs'+_ass_size(float(style.font_size)*heading_scale(attrs))) if sized else ''
        strike = ('\\s'+str(int(bool(attrs.get('strike'))))) if struck else ''
        output.append('{'+face+'\\b'+str(bold)+'\\i'+str(italic)+size+strike+'\\1c'+value+extra_tags+'}'+escape_ass_text(text[a:b]))
    return ''.join(output)
