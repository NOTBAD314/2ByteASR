"""Draw one video layer under a sampled transition effect.

Shared by the paused preview, the playback raster thread and the export
raster pass, so a look renders the same everywhere. ``fx`` comes from
``timeline.studio_transitions.transition_effect``; layers whose fx only
changes opacity never reach this module (their old drawing is unchanged).

Blur is drawn on a reduced-resolution buffer: motion blur shrinks only along
its axis, zoom blur shrinks both axes. The taps then sit about one buffer
pixel apart, so a long streak stays smooth instead of showing stepped copies,
and the cost stays near one extra full-frame draw.
"""
from __future__ import annotations

import math
import random

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

_MAX_TAPS = 24
_MAX_ZOOM_TAPS = 32
_MIN_BLUR = 2.     # canvas pixels; shorter streaks are invisible and not worth a buffer pass
_TAP_SPACING = 3.  # canvas pixels per buffer pixel along a motion blur: at most 4 copies
_ZOOM_SPACING = 3.  # canvas pixels of zoom reach per buffer pixel
_MAX_ZOOM_REDUCE = 4.


def effect_transform(local: QRectF, matrix: QTransform, fx: dict, width: float, height: float) -> QTransform:
    """Offset (fractions of the canvas) and scale about the layer centre."""
    centre = matrix.map(local.center())
    result = QTransform()
    result.translate(centre.x()+fx['dx']*width, centre.y()+fx['dy']*height)
    result.scale(fx['sx'], fx['sy'])
    result.translate(-centre.x(), -centre.y())
    return result


def pixel_effects(image: QImage, fx: dict) -> QImage:
    """Colour-channel split and horizontal slice offsets, in source pixels."""
    source = image if image.format() == QImage.Format.Format_ARGB32 else image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = source.width(), source.height()
    if width < 2 or height < 2:
        return image
    rows = np.frombuffer(source.constBits(), np.uint8, count=source.sizeInBytes()).reshape(height, source.bytesPerLine())
    pixels = rows[:, :width*4].reshape(height, width, 4)
    result = pixels.copy()
    shift = min(width-1, int(round(fx['rgb_split']*width)))
    if shift > 0:
        # Memory order is B, G, R, A: red moves right, blue moves left.
        result[:, shift:, 2] = pixels[:, :-shift, 2]
        result[:, :shift, 2] = pixels[:, :1, 2]
        result[:, :-shift, 0] = pixels[:, shift:, 0]
        result[:, -shift:, 0] = pixels[:, -1:, 0]
    strength = min(1.5, fx['glitch'])
    if strength > 0:
        rng = random.Random(fx['seed'])
        for _ in range(3+int(5*min(1., strength))):
            top = int(rng.random()*height)
            band = max(1, int(height*(.015+.05*rng.random())))
            offset = int((rng.random()*2-1)*.06*strength*width)
            result[top:top+band] = np.roll(result[top:top+band], offset, axis=1)
    return QImage(result.data, width, height, width*4, QImage.Format.Format_ARGB32).copy()


def _blank(width: int, height: int) -> QImage:
    image = QImage(max(1, width), max(1, height), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    return image


def _average(image: QImage, transforms: list[QTransform]) -> QImage:
    """Mean of transformed copies; partial coverage keeps partial alpha.

    The layer is scaled to 1/n once in a 16-bit buffer and the copies are
    then summed (Plus) at full opacity. Painter opacity is quantised to 8
    bits (1/24 becomes 9/255) and Qt's Plus clamps before applying it, so the
    scale is a 16-bit DestinationIn fill instead. A running SourceOver mean is
    order-dependent where only some copies cover a pixel (one hard edge).
    Up to four copies 8 bits are exact enough (255/n rounds to a full sum)
    and avoid two format conversions.
    """
    deep = (QImage.Format.Format_RGBA64_Premultiplied if len(transforms) > 4
            else QImage.Format.Format_ARGB32_Premultiplied)
    share = image.convertToFormat(deep)
    painter = QPainter(share)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.fillRect(share.rect(), QColor.fromRgba64(0, 0, 0, round(65535/len(transforms))))
    painter.end()
    result = QImage(image.width(), image.height(), deep)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    for transform in transforms:
        painter.setTransform(transform)
        painter.drawImage(QPointF(0, 0), share)
    painter.end()
    return result if deep == QImage.Format.Format_ARGB32_Premultiplied else \
        result.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def _motion_blur(image: QImage, length_x: float, length_y: float) -> QImage:
    length = max(length_x, length_y)
    taps = max(2, min(_MAX_TAPS, int(math.ceil(length))+1))
    ux, uy = (length_x, length_y)
    return _average(image, [QTransform.fromTranslate(ux*(i/(taps-1)-.5), uy*(i/(taps-1)-.5)) for i in range(taps)])


def _zoom_blur(image: QImage, centre: QPointF, amount: float) -> QImage:
    reach = amount*math.hypot(image.width(), image.height())/2
    taps = max(3, min(_MAX_ZOOM_TAPS, int(math.ceil(reach))+1))
    transforms = []
    for i in range(taps):
        scale = 1+amount*i/(taps-1)
        transform = QTransform()
        transform.translate(centre.x(), centre.y())
        transform.scale(scale, scale)
        transform.translate(-centre.x(), -centre.y())
        transforms.append(transform)
    return _average(image, transforms)


def sample_frames(width: int, height: int) -> tuple[QImage, QImage]:
    """Two contrasting stand-in pictures for look cards (no bundled assets)."""
    from PySide6.QtGui import QLinearGradient
    frames = []
    for first, second, accent in (('#F2994A', '#7B4397', '#FFF3D6'), ('#11998E', '#2F80ED', '#D9F7FF')):
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        gradient = QLinearGradient(0, 0, width, height)
        gradient.setColorAt(0, QColor(first))
        gradient.setColorAt(1, QColor(second))
        painter.fillRect(image.rect(), gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent))
        if not frames:
            painter.drawEllipse(QPointF(width*.32, height*.48), height*.24, height*.24)
            painter.setBrush(QColor(40, 20, 50, 150))
            painter.drawRect(QRectF(0, height*.78, width, height*.22))
        else:
            for index in range(4):
                painter.drawRect(QRectF(width*(.14+.2*index), height*(.3+.1*(index % 2)), width*.07, height*.5))
        painter.end()
        frames.append(image)
    return frames[0], frames[1]


def compose_pair(look: dict | None, progress: float, outgoing: QImage, incoming: QImage,
                 size: tuple[int, int], transition_id: str = 'preview') -> QImage:
    """One frame of a seam between two full-frame pictures (cards, tests)."""
    from .studio_transitions import transition_effect, transition_fx_active
    from .video_compositor import layer_geometry
    width, height = size
    canvas = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.black)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    for role, image in (('out', outgoing), ('in', incoming)):
        if look is None:
            envelopes = [] if role == 'out' else [dict(start_ms=0, end_ms=1000, role='in', curve='linear')]
        else:
            envelopes = [dict(start_ms=0, end_ms=1000, role=role, curve='look', look=look, transition_id=transition_id)]
        fx = transition_effect(envelopes, progress*1000)
        local, matrix = layer_geometry(width, height, dict(transform={}), image.width(), image.height())
        if transition_fx_active(fx):
            paint_with_effects(painter, size, image, local, matrix, fx, opacity=fx['opacity'])
        elif fx['opacity'] > 0:
            painter.save()
            painter.setOpacity(fx['opacity'])
            painter.setTransform(matrix)
            painter.drawImage(local, image)
            painter.restore()
    painter.end()
    return canvas


def paint_with_effects(painter: QPainter, size: tuple[int, int], image: QImage, local: QRectF,
                       matrix: QTransform, fx: dict, *, opacity: float,
                       mode: QPainter.CompositionMode = QPainter.CompositionMode.CompositionMode_SourceOver) -> None:
    """Paint ``image`` (layer geometry ``local``/``matrix`` in canvas pixels)."""
    opacity = max(0., min(1., float(opacity)))
    if opacity <= 0 or image.isNull():
        return
    width, height = size
    if fx['rgb_split'] > 0 or fx['glitch'] > 0:
        image = pixel_effects(image, fx)
    full = matrix*effect_transform(local, matrix, fx, width, height)
    blur_x, blur_y = fx['blur_x']*width, fx['blur_y']*height
    blur_x, blur_y = (blur_x if blur_x >= _MIN_BLUR else 0.), (blur_y if blur_y >= _MIN_BLUR else 0.)
    zoom = fx['zoom_blur']
    reach = zoom*math.hypot(width, height)/2
    if reach < _MIN_BLUR:
        zoom = 0.
    if not blur_x and not blur_y and not zoom and fx['tint_alpha'] <= 0:
        painter.save()
        painter.setOpacity(opacity)
        painter.setCompositionMode(mode)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setTransform(full, False)
        painter.drawImage(local, image)
        painter.restore()
        return
    reduce_x = max(1., blur_x/_TAP_SPACING)
    reduce_y = max(1., blur_y/_TAP_SPACING)
    if zoom:
        overall = max(1., min(_MAX_ZOOM_REDUCE, reach/_ZOOM_SPACING))
        reduce_x, reduce_y = max(reduce_x, overall), max(reduce_y, overall)
    buffer = _blank(width, height)
    layer = QPainter(buffer)
    layer.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    layer.setTransform(full)
    layer.drawImage(local, image)
    layer.end()
    if reduce_x > 1 or reduce_y > 1:
        # Area-average down (a box filter), not bilinear sampling in the draw:
        # sampling one pixel in `reduce` would shimmer while the picture moves.
        buffer = buffer.scaled(int(math.ceil(width/reduce_x)), int(math.ceil(height/reduce_y)),
                               Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    shrink = QTransform.fromScale(1/reduce_x, 1/reduce_y)
    if blur_x or blur_y:
        buffer = _motion_blur(buffer, blur_x/reduce_x, blur_y/reduce_y)
    if zoom:
        buffer = _zoom_blur(buffer, (full*shrink).map(local.center()), zoom)
    if fx['tint_alpha'] > 0:
        tint = QPainter(buffer)
        tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        colour = QColor(fx['tint'] or '#ffffff')
        colour.setAlphaF(max(0., min(1., fx['tint_alpha'])))
        tint.fillRect(buffer.rect(), colour)
        tint.end()
    painter.save()
    painter.resetTransform()
    painter.setOpacity(opacity)
    painter.setCompositionMode(mode)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawImage(QRectF(0, 0, buffer.width()*reduce_x, buffer.height()*reduce_y), buffer)
    painter.restore()
