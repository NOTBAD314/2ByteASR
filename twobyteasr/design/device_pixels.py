"""Pictures copied 1:1 in device pixels, also at fractional screen scales (2026-11-19).

User (2026-11-19, daily 171e958e): "UI motion still stutters ... it all looks below 15 fps"; their
main screen is 3840x2160 at 175 %. At a fractional device pixel ratio (125/150/175 %) a widget
painter's transform is a scale, and Qt's raster engine then sends every ``drawPixmap`` through
its scaling path, even when the picture has the screen's ratio and lands 1:1. Measured offscreen
on a 2194x1234 (logical) page, one old+new page frame: 17 ms at 175 % and 9 ms at 125 % that way,
4 ms and 1.5 ms drawn in device pixels (same pixels; 1.0 and 2.0 were already fast).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainter, QPixmap, QTransform

_PLAIN_TRANSFORMS = (QTransform.TransformationType.TxNone, QTransform.TransformationType.TxTranslate)


def draw_picture(painter: QPainter, at, pixmap: QPixmap, source: QRectF | None = None) -> None:
    """``painter.drawPixmap`` of ``pixmap`` (or its ``source`` rect, in the pixmap's own pixels) with
    its top left at ``at`` (logical), 1:1 in device pixels: Qt's plain copy, at any screen scale.

    For the draw the painter's scale is undone, so the combined transform is a plain translation
    again. A position between two device pixels is rounded to one (at most half a device pixel).
    A painter that scales or rotates itself (a page stepping back, a growing dialog) and a picture
    of another ratio than the device are drawn by Qt as before."""
    ratio = pixmap.devicePixelRatio() or 1.0
    device = painter.device()
    world = painter.worldTransform()
    if (ratio == 1.0 or device is None or abs(device.devicePixelRatio() - ratio) > 1e-3
            or world.type() not in _PLAIN_TRANSFORMS):
        if source is None:
            painter.drawPixmap(QPointF(at), pixmap)
        else:
            painter.drawPixmap(QRectF(at.x(), at.y(), source.width() / ratio, source.height() / ratio), pixmap, source)
        return
    src = QRectF(pixmap.rect()) if source is None else QRectF(round(source.x()), round(source.y()),
                                                              round(source.width()), round(source.height()))
    painter.save()
    painter.setWorldTransform(QTransform.fromScale(1 / ratio, 1 / ratio))
    painter.drawPixmap(QRectF(round((at.x() + world.dx()) * ratio), round((at.y() + world.dy()) * ratio),
                              src.width(), src.height()), pixmap, src)
    painter.restore()
