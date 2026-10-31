"""Bounded, file/face-verified glyph runs for the font picker only.

No per-row widgets or images. Glyph runs cannot ask Qt to merge another font
for a missing character; readable UI text is an explicit separate fallback.
"""
from collections import OrderedDict
from dataclasses import dataclass,field
from pathlib import Path
import struct
from functools import lru_cache

from PySide6.QtCore import QPointF,QRectF,Qt
from PySide6.QtGui import QFont,QFontMetricsF,QGlyphRun,QRawFont,QGuiApplication

from .font_metadata import resolve_local_face


@dataclass(frozen=True)
class FontPreviewRequest:
    family:str
    weight:int=0
    style:str=''
    bold:bool=False
    filename:str=''
    face_index:int=0


@dataclass
class GlyphText:
    run:QGlyphRun
    bounds:QRectF
    advance:float


@dataclass
class PreviewFace:
    raw:QRawFont
    metadata:object
    warning:str=''
    layouts:OrderedDict=field(default_factory=OrderedDict)
    glyph_bounds:OrderedDict=field(default_factory=OrderedDict)
    coverage:OrderedDict=field(default_factory=OrderedDict)
    _sample_cache:str|None=None
    collection_bytes:int=0
    source:str='file'

    def covers(self,text):
        if text in self.coverage:return self.coverage[text]
        # supportsCharacter() can reject glyphs present in a font's cmap
        # (e.g. 猫 in Maoken). Actual nonzero glyph IDs are authoritative.
        characters=''.join(ch for ch in text if not ch.isspace())
        value=self.raw.isValid()and all(self.raw.glyphIndexesForString(characters))
        self.coverage[text]=value
        while len(self.coverage)>64:self.coverage.popitem(last=False)
        return value

    def shape(self,text):
        cached=self.layouts.get(text)
        if cached is not None:self.layouts.move_to_end(text);return cached
        glyphs=self.raw.glyphIndexesForString(text)
        advances=self.raw.advancesForGlyphIndexes(glyphs,QRawFont.LayoutFlag.KernedAdvances)
        positions=[];x=0.;bounds=QRectF()
        for glyph,advance in zip(glyphs,advances):
            positions.append(QPointF(x,0))
            ink=self.glyph_bounds.get(glyph)
            if ink is None:
                ink=self.raw.boundingRect(glyph);self.glyph_bounds[glyph]=ink
                while len(self.glyph_bounds)>256:self.glyph_bounds.popitem(last=False)
            ink=ink.translated(x,0)
            if not ink.isEmpty():bounds=ink if bounds.isEmpty()else bounds.united(ink)
            x+=advance.x()
        run=QGlyphRun();run.setRawFont(self.raw);run.setGlyphIndexes(glyphs);run.setPositions(positions)
        value=GlyphText(run,bounds,x);self.layouts[text]=value
        while len(self.layouts)>32:self.layouts.popitem(last=False)
        return value

    def sample(self):
        if self._sample_cache is not None:return self._sample_cache
        if self.covers('ABC123')and not self.shape('ABC123').bounds.isEmpty():
            self._sample_cache='ABC123';return self._sample_cache
        chars=[]
        for ch in 'ABC123abcxyz0123456789字幕汉字':
            if ch not in chars and self.covers(ch) and not self.shape(ch).bounds.isEmpty():chars.append(ch)
            if len(chars)==6:break
        self._sample_cache=''.join(chars);return self._sample_cache


_FACES=OrderedDict()
_FAILURES=OrderedDict()
MAX_PREVIEW_FACES=96
MAX_COLLECTION_BYTES=48*1024*1024


@lru_cache(maxsize=128)
def _identity_tables(filename,index):
    """Small trusted identity tables of a visible face, not the full font."""
    with open(filename,'rb')as stream:
        header=stream.read(12)
        if header[:4]==b'ttcf':
            stream.seek(12+4*index);offset=struct.unpack('>I',stream.read(4))[0]
        else:offset=0
        stream.seek(offset);header=stream.read(12);count=struct.unpack_from('>H',header,4)[0]
        directory=stream.read(16*count);tables={}
        for i in range(count):
            tag,checksum,pos,length=struct.unpack_from('>4sIII',directory,i*16)
            if tag in (b'name',b'head'):
                stream.seek(pos);tables[tag]=stream.read(length)
        return tables.get(b'name'),tables.get(b'head')


def _registered_face(face,pixels):
    if QGuiApplication.platformName()in {'offscreen','minimal'}:return None
    font=QFont(face.full_name);font.setPixelSize(round(pixels));font.setWeight(QFont.Weight(face.weight))
    font.setStyleName(face.style);font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
    raw=QRawFont.fromFont(font)
    if not raw.isValid():return None
    try:name,head=_identity_tables(face.file,face.index)
    except (OSError,ValueError,struct.error):return None
    if (name and head and bytes(raw.fontTable('name'))==name and bytes(raw.fontTable('head'))==head
            and abs(int(raw.weight())-int(face.weight))<=1):return raw
    return None


def preview_face(request,pixels,*,load=True):
    """Return (actual face or None, explanation); never return a silent fallback."""
    face,warning=resolve_local_face(request.family,request.weight,request.style,request.bold,
                                    request.filename,request.face_index)
    known=request.family.casefold()in {s.casefold()for s in face.aliases}
    explicit=bool(request.filename and Path(request.filename)==Path(face.file))
    if not (known or explicit):return None,warning or '无法匹配实际字体'
    key=(face.file,face.index,face.weight,face.style,round(float(pixels),2))
    cached=_FACES.get(key)
    if cached is not None:_FACES.move_to_end(key);return cached,warning
    if key in _FAILURES:return None,_FAILURES[key]
    if not load:return None,'正在加载字形'
    collection_bytes=0;source='registered';raw=_registered_face(face,pixels)
    if raw is not None:pass
    elif face.index==0:
        source='file'
        raw=QRawFont(face.file,float(pixels))
    else:
        source='collection'
        # QRawFont loads a collection's first face. Reorder only its in-memory
        # offset list: all original SFNT tables/checksums/glyphs stay intact,
        # and no installed font is written or registered again.
        data=bytearray(Path(face.file).read_bytes())
        if len(data)<16 or data[:4]!=b'ttcf':return None,'实际字体面暂不可预览'
        count=struct.unpack_from('>I',data,8)[0]
        if not 0<=face.index<count or len(data)<12+count*4:return None,'实际字体面暂不可预览'
        first,selected=12,12+face.index*4
        data[first:first+4],data[selected:selected+4]=data[selected:selected+4],data[first:first+4]
        collection_bytes=len(data);raw=QRawFont(bytes(data),float(pixels))
    if not raw.isValid():
        _FAILURES[key]='实际字体面暂不可预览'
        while len(_FAILURES)>128:_FAILURES.popitem(last=False)
        return None,_FAILURES[key]
    value=PreviewFace(raw,face,warning,collection_bytes=collection_bytes,source=source);_FACES[key]=value
    while len(_FACES)>1 and (len(_FACES)>MAX_PREVIEW_FACES or
            sum(v.collection_bytes for v in _FACES.values())>MAX_COLLECTION_BYTES):_FACES.popitem(last=False)
    return value,warning


def preview_pixels(ui_font):
    px=ui_font.pixelSize()
    if px<=0:px=ui_font.pointSizeF()*96/72
    return max(18.,min(22.,round(px+4)))


def _elided_glyph_text(face,text,width):
    shape=face.shape(text)
    if shape.bounds.width()<=width:return text,shape
    suffix='…' if face.covers('…')else '...' if face.covers('.')else ''
    low,high=0,len(text)
    while low<high:
        middle=(low+high+1)//2
        if face.shape(text[:middle]+suffix).bounds.width()<=width:low=middle
        else:high=middle-1
    chosen=text[:low]+suffix
    return chosen,face.shape(chosen)


def draw_glyph_text(painter,face,text,rect,color):
    if rect.width()<=0 or rect.height()<=0:return
    text,shaped=_elided_glyph_text(face,text,rect.width())
    bounds=shaped.bounds
    if bounds.isEmpty():return
    # Fit unusual ink outsets without altering the row height or cropping.
    scale=min(1.,rect.height()/bounds.height())
    painter.save();painter.setClipRect(rect,Qt.ClipOperation.IntersectClip)
    painter.setPen(color)
    painter.translate(rect.left()-bounds.left()*scale,rect.center().y()-bounds.center().y()*scale)
    painter.scale(scale,scale);painter.drawGlyphRun(QPointF(0,0),shaped.run);painter.restore()


def draw_font_preview(painter,rect,name,request,ui_font,color,*,allow_load=True):
    """Two text columns inside one existing control; return truthful paint state."""
    face,warning=preview_face(request,preview_pixels(ui_font),load=allow_load)
    metrics=QFontMetricsF(ui_font);gap=12.
    glyph_sample=face.sample()if face is not None else ''
    prefix='示例'
    prefix_is_target=bool(glyph_sample and face.covers(prefix))
    sample=prefix+glyph_sample if glyph_sample else ''
    loading=face is None and warning=='正在加载字形'
    example=sample or ('加载中'if loading else '无法预览')
    prefix_width=metrics.horizontalAdvance(prefix)+2
    sample_width=((face.shape(sample).bounds.width()+4 if prefix_is_target else
                   prefix_width+face.shape(glyph_sample).bounds.width()+4)
                  if sample else metrics.horizontalAdvance(example)+4)
    required_sample_width=sample_width
    sample_width=min(max(54.,sample_width),max(54.,rect.width()-60-gap))
    sample_rect=QRectF(rect.right()-sample_width,rect.top(),sample_width,rect.height())
    name_rect=QRectF(rect.left(),rect.top(),max(0.,rect.width()-sample_width-gap),rect.height())
    own_name=bool(face is not None and face.covers(name))
    if own_name:draw_glyph_text(painter,face,name,name_rect,color)
    else:
        painter.save();painter.setFont(ui_font);painter.setPen(color)
        text=metrics.elidedText(name,Qt.TextElideMode.ElideRight,int(name_rect.width()))
        painter.drawText(name_rect,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,text);painter.restore()
    if sample and prefix_is_target:draw_glyph_text(painter,face,sample,sample_rect,color)
    elif sample:
        painter.save();painter.setFont(ui_font);painter.setPen(color)
        prefix_rect=QRectF(sample_rect.left(),sample_rect.top(),prefix_width,sample_rect.height())
        painter.drawText(prefix_rect,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,prefix)
        painter.restore()
        draw_glyph_text(painter,face,glyph_sample,sample_rect.adjusted(prefix_width,0,0,0),color)
    else:
        painter.save();painter.setFont(ui_font);painter.setPen(color)
        painter.drawText(sample_rect,Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignRight,example);painter.restore()
    return dict(requested=name,actual=face.raw.familyName()if face else '',
        actual_style=face.raw.styleName()if face else '',file=face.metadata.file if face else '',
        actual_weight=int(face.raw.weight())if face else None,preview_pixels=preview_pixels(ui_font),
        source=face.source if face else '',
        face_index=face.metadata.index if face else None,name_uses_target=own_name,sample=sample,
        target_sample=sample if prefix_is_target else glyph_sample,
        sample_supported=bool(glyph_sample and face.covers(glyph_sample)),
        sample_complete=bool(sample and sample_width>=required_sample_width),
        sample_uses_ui_prefix=bool(sample and not prefix_is_target),warning=warning,
        loading=loading,
        name_rect=name_rect.getRect(),sample_rect=sample_rect.getRect())
