"""A real Gaussian blur of a picture, for soft backdrops (2026-11-27).

User (2026-11-27): opening a project showed its cover behind the loading card "very blurry and
obviously low resolution" - the cover was shrunk to 32x18 and stretched over the whole window,
so the big soft blocks of a tiny picture showed. They asked for a true Gaussian blur instead.

``gaussian_backdrop`` blurs a moderately sized copy with Qt's own blur effect (a proper Gaussian,
not a stretched thumbnail), on a canvas a little larger than the result so the edges do not fade
to transparent, then scales the already smooth picture up to the target size.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

WORK_WIDTH = 360          # the blur runs on a copy about this wide
RADIUS_PART = 1 / 22      # blur radius as a part of that width


def blurred_image(source: QImage | QPixmap, size: QSize, *, radius: float) -> QImage:
    """``source`` cropped to fill ``size`` (KeepAspectRatioByExpanding) and blurred by ``radius`` px
    at that size. Edges keep their colour (the blur runs on a margin that is then cut away)."""
    width, height = max(1, size.width()), max(1, size.height())
    margin = max(2, int(radius * 2.5))
    pixmap = source if isinstance(source, QPixmap) else QPixmap.fromImage(source)
    fill = pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                         Qt.TransformationMode.SmoothTransformation)
    fill = fill.copy((fill.width() - width) // 2, (fill.height() - height) // 2, width, height)
    # The margin repeats the picture's own edges (a stretched copy under the exact one), so the
    # blur near the edges mixes in its colours instead of transparency.
    padded = QPixmap(width + 2 * margin, height + 2 * margin)
    padded.fill(QColor(0, 0, 0, 0))
    canvas = QPainter(padded)
    canvas.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    canvas.drawPixmap(padded.rect(), fill)
    canvas.drawPixmap(margin, margin, fill)
    canvas.end()
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(padded)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(float(radius))
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    # The padded picture is centred on the result; its margin is cut away.
    left = (padded.width() - width) / 2
    top = (padded.height() - height) / 2
    result = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(QColor(0, 0, 0, 0))
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(0, 0, fill)        # an opaque floor: the blur's last edge pixels never show through
    scene.render(painter, QRectF(0, 0, width, height), QRectF(QPointF(left, top), QSize(width, height).toSizeF()))
    painter.end()
    scene.clear()
    return result


def gaussian_backdrop(source: QImage | QPixmap, size: QSize) -> QPixmap:
    """A softly blurred ``source`` filling ``size``; an empty pixmap for an empty source."""
    if source is None or source.isNull() or size.width() <= 0 or size.height() <= 0:
        return QPixmap()
    work_w = min(WORK_WIDTH, size.width())
    work_h = max(1, round(size.height() * work_w / size.width()))
    small = blurred_image(source, QSize(work_w, work_h), radius=max(3.0, work_w * RADIUS_PART))
    return QPixmap.fromImage(small.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))


__all__ = ['blurred_image', 'gaussian_backdrop']
