"""One pixel-coordinate renderer for the editor and full-resolution exports."""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import json
import math
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt, QSaveFile
from PySide6.QtGui import (QColor, QFont, QImage, QImageReader, QImageWriter, QPainter,
                          QPen, QTextBlockFormat, QTextCharFormat, QTextCursor,
                          QTextDocument, QTextOption)

from .cover_document import MAX_PIXELS, MAX_ASSET_BYTES, valid_size


def read_image_bytes(data):
    if len(data) > MAX_ASSET_BYTES:
        raise ValueError('图片文件超过 256 MB。')
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.width()*size.height() > MAX_PIXELS:
        raise ValueError('图片超过 6400 万像素，请先缩小原文件。')
    image = reader.read()
    if image.isNull():
        raise ValueError('无法读取图片：'+reader.errorString())
    image.setDevicePixelRatio(1)
    return image.convertToFormat(QImage.Format_ARGB32_Premultiplied)


def load_image_file(filename):
    path = Path(filename)
    if path.stat().st_size > MAX_ASSET_BYTES:
        raise ValueError('图片文件超过 256 MB。')
    data = path.read_bytes()
    return data, read_image_bytes(data)


def image_filter():
    supported = sorted({bytes(fmt).decode('ascii') for fmt in QImageReader.supportedImageFormats()})
    return '图片 ('+' '.join('*.'+fmt for fmt in supported)+')'


@lru_cache(maxsize=512)
def _load_font_file(filename):
    # Register only the selected face in this application, including fonts
    # discovered in local directories but not registered system-wide.
    from PySide6.QtGui import QFontDatabase
    return QFontDatabase.addApplicationFont(filename)


def text_font(style):
    from .font_metadata import resolve_local_face
    face, warning = resolve_local_face(str(style.get('family', 'Source Han Sans SC')),
                                      int(style.get('weight', 900)), str(style.get('font_style', '')))
    _load_font_file(face.file)
    font = QFont(face.family)
    font.setStyleName(face.style)
    font.setWeight(QFont.Weight(face.weight))
    font.setPixelSize(max(8, min(2048, round(float(style.get('size', 96))))))
    font.setHintingPreference(QFont.PreferNoHinting)
    return font, warning, face


def render_text(layer):
    style = layer.style
    font, warning, _ = text_font(style)
    stroke = max(0, min(100, float(style.get('stroke', 0))))
    blur = max(0, min(100, float(style.get('shadow_blur', 0)))) if style.get('shadow') else 0
    dx = float(style.get('shadow_x', 0)) if style.get('shadow') else 0
    dy = float(style.get('shadow_y', 0)) if style.get('shadow') else 0
    padding = math.ceil(stroke + blur*3 + max(abs(dx), abs(dy)) + 4)
    width = max(padding*2+16, math.ceil(layer.width))
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(font)
    option = QTextOption()
    option.setUseDesignMetrics(True)
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    document.setPlainText(layer.text)
    document.setTextWidth(width-padding*2)
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.Document)
    char_format = QTextCharFormat()
    char_format.setFont(font)
    char_format.setForeground(QColor(style.get('color', '#ffffff')))
    if stroke:
        pen = QPen(QColor(style.get('stroke_color', '#152c28')), stroke*2)
        pen.setJoinStyle(Qt.RoundJoin)
        char_format.setTextOutline(pen)
    cursor.setCharFormat(char_format)
    block_format = QTextBlockFormat()
    block_format.setAlignment({'left': Qt.AlignLeft, 'center': Qt.AlignHCenter, 'right': Qt.AlignRight}.get(style.get('alignment'), Qt.AlignLeft))
    cursor.setBlockFormat(block_format)
    height = math.ceil(document.size().height()) + padding*2
    if width*height > MAX_PIXELS:
        raise ValueError('文字图层过大，请减小字号或缩短内容。')
    ink = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    ink.fill(Qt.transparent)
    painter = QPainter(ink)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    painter.translate(padding, padding)
    document.drawContents(painter)
    if stroke:
        # QTextDocument paints an outline centered over the glyph edge. Restore
        # the full fill above it, so a large outline cannot eat a Heavy face.
        char_format.setTextOutline(QPen(Qt.NoPen))
        cursor.setCharFormat(char_format)
        document.drawContents(painter)
    painter.end()
    if not style.get('shadow'):
        return ink, warning
    # Straight RGBA conversion before blur avoids dark fringes on transparent
    # PNGs. The same raster is painted on the canvas and the export snapshot.
    from PIL import Image, ImageFilter
    rgba = ink.convertToFormat(QImage.Format_RGBA8888)
    alpha = Image.frombytes('RGBA', (width, height), bytes(rgba.constBits())).getchannel('A')
    if blur:
        alpha = alpha.filter(ImageFilter.GaussianBlur(blur))
    color = QColor(style.get('shadow_color', '#b0000000'))
    alpha = alpha.point(lambda value: round(value*color.alphaF()))
    shadow = Image.new('RGBA', (width, height), (color.red(), color.green(), color.blue(), 0))
    shadow.putalpha(alpha)
    shadow_image = QImage(shadow.tobytes(), width, height, width*4, QImage.Format_RGBA8888).copy()
    result = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.drawImage(int(dx), int(dy), shadow_image)
    painter.drawImage(0, 0, ink)
    painter.end()
    return result, warning


class CoverRenderer:
    def __init__(self):
        self.images = {}
        self.texts = OrderedDict()
        self.warnings = {}

    def release_unused(self, document):
        used = {layer.asset for layer in document.layers}
        self.images = {key: value for key, value in self.images.items() if key in used}

    def layer_image(self, document, layer):
        if layer.kind == 'image':
            if layer.asset not in self.images:
                if layer.asset not in document.assets:
                    raise ValueError('素材缺失，请选择该图层并重新定位素材。')
                self.images[layer.asset] = read_image_bytes(document.assets[layer.asset])
            return self.images[layer.asset]
        key = json.dumps([layer.text, layer.width, layer.style], ensure_ascii=False, sort_keys=True)
        if key not in self.texts:
            self.texts[key], self.warnings[layer.id] = render_text(layer)
            while len(self.texts) > 24 or (len(self.texts) > 1 and sum(i.sizeInBytes() for i in self.texts.values()) > 96*1024*1024):
                self.texts.popitem(last=False)
        self.texts.move_to_end(key)
        return self.texts[key]

    def layer_rect(self, document, layer):
        if layer.kind == 'image':
            return QRectF(0, 0, layer.width, layer.height)
        image = self.layer_image(document, layer)
        return QRectF(0, 0, image.width(), image.height())

    def render(self, document, *, jpeg=False):
        width, height = valid_size(document.width, document.height)
        result = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        if result.isNull():
            raise MemoryError('无法分配画布内存，请减小画布尺寸。')
        result.fill(QColor(document.jpeg_background if jpeg else document.background))
        painter = QPainter(result)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        try:
            painter.setClipRect(QRectF(0, 0, width, height))
            for layer in document.layers:
                if not layer.visible:
                    continue
                image = self.layer_image(document, layer)
                target = self.layer_rect(document, layer).translated(layer.x, layer.y)
                painter.setOpacity(layer.opacity)
                painter.drawImage(target, image, QRectF(image.rect()))
        finally:
            painter.end()
        return result


def export_image(document, filename, *, quality=95):
    destination = Path(filename)
    suffix = destination.suffix.lower()
    if suffix not in ('.png', '.jpg', '.jpeg'):
        raise ValueError('请选择 PNG 或 JPEG 文件。')
    image = CoverRenderer().render(document, jpeg=suffix != '.png')
    handle = QSaveFile(str(destination))
    handle.setDirectWriteFallback(False)
    if not handle.open(QIODevice.WriteOnly):
        raise OSError('无法创建输出文件：'+handle.errorString())
    writer = QImageWriter(handle, b'png' if suffix == '.png' else b'jpeg')
    writer.setQuality(max(1, min(100, int(quality))))
    if not writer.write(image):
        handle.cancelWriting()
        raise OSError('图片写入失败：'+writer.errorString())
    if not handle.commit():
        raise OSError('无法完成保存，原文件保持不变：'+handle.errorString())
    return dict(path=str(destination), width=image.width(), height=image.height(), format=suffix[1:])
