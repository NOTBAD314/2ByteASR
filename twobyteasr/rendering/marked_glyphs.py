"""Shape marked text once with Qt's Unicode layout, retaining glyph ownership."""
from collections import OrderedDict
import json
import threading
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath, QTextLayout, QTextCharFormat
from ..caption_style.text_marks import runs, utf16_offset, python_offset


_SHAPES = OrderedDict()
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
            fmt = QTextCharFormat()
            if 'bold' in attrs or 'italic' in attrs: fmt.setFontStyleName('')
            if 'bold' in attrs: fmt.setFontWeight(max(int(font.weight()),700) if attrs['bold'] else 400)
            if 'italic' in attrs: fmt.setFontItalic(bool(attrs['italic']))
            item = QTextLayout.FormatRange()
            item.start, item.length, item.format = utf16_offset(line_text,a), utf16_offset(line_text,b)-utf16_offset(line_text,a), fmt
            formats.append(item)
        layout.setFormats(formats)
        layout.beginLayout(); line = layout.createLine()
        line.setLineWidth(1e7); line.setPosition(QPointF(0, y)); layout.endLayout()
        width = line.naturalTextWidth(); widths.append(width)
        flags = QTextLayout.GlyphRunRetrievalFlag.RetrieveAll
        glyphs = []
        for run in layout.glyphRuns(0, -1, flags):
            for index, point, string_index in zip(run.glyphIndexes(), run.positions(), run.stringIndexes()):
                cp = python_offset(line_text, int(string_index))
                attrs = next((v for a,b,v in segments if a <= cp < b), {})
                path = run.rawFont().pathForGlyph(index)
                path.setFillRule(Qt.WindingFill)
                path.translate(point)
                glyphs.append((path, start+cp, attrs.get('color') or ('#FFD166' if attrs.get('highlight') else '')))
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
            fmt = QTextCharFormat()
            if 'bold' in attrs or 'italic' in attrs: fmt.setFontStyleName('')
            if 'bold' in attrs: fmt.setFontWeight(max(int(font.weight()),700) if attrs['bold'] else 400)
            if 'italic' in attrs: fmt.setFontItalic(bool(attrs['italic']))
            item=QTextLayout.FormatRange()
            item.start,item.length,item.format=utf16_offset(paragraph,lo),utf16_offset(paragraph,hi)-utf16_offset(paragraph,lo),fmt
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


def marked_ass_text(text, marks, style, extra_tags=""):
    from .ass_compiler import escape_ass_text
    from ..caption_style.effect_dsl import _ass_color
    output = []
    for a,b,attrs in runs(text, marks):
        bold = max(int(style.font_weight or 400),700) if attrs.get('bold', style.bold) else 400
        italic = int(attrs.get('italic', style.italic))
        color = attrs.get('color') or ('#FFD166' if attrs.get('highlight') else style.primary_color)
        # ASS style colours include alpha; the inline 1c tag takes only BGR.
        value = _ass_color(color)
        output.append('{\\b'+str(bold)+'\\i'+str(italic)+'\\1c'+value+extra_tags+'}'+escape_ass_text(text[a:b]))
    return ''.join(output)
