"""Shared media silhouette in real project-time coordinates; hit testing is separate."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainterPath


def media_clip_shape(left, right, top, height, view_left, view_right):
    width = max(0., right - left)
    radius = min(14., max(0., height) * .44, width / 2.)
    # Bound raster coordinates while keeping artificial ends fully outside
    # the viewport, even when the radius is larger than the old 8px overscan.
    x1, x2 = max(left, view_left - radius - 2), min(right, view_right + radius + 2)
    rect = QRectF(x1, top, max(0., x2 - x1), max(0., height))
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return rect, path
