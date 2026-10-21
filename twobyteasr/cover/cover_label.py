"""Aspect-preserving cover preview for the Project Library.

Fills the available label area with the source pixmap while keeping the
source aspect ratio: the image is scaled up until both dimensions are
covered, centered, and the overflow is cropped vertically (and horizontally
only when unavoidable). This avoids both horizontal stretching and the
letterbox strips a plain scaled-contents QLabel would show.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel


class CoverPreviewLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cover = QPixmap()
        self._radius = 0
        self._fit = "cover"
        self.setMinimumSize(1, 1)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())

    def set_corner_radius(self, radius: int) -> None:
        self._radius = max(0, int(radius))
        self.update()

    def set_fit_mode(self, mode: str) -> None:
        """cover = fill and crop; contain = full image, no stretch."""
        self._fit = "contain" if str(mode) == "contain" else "cover"
        self.update()

    def set_cover(self, pixmap: QPixmap) -> None:
        self._cover = QPixmap(pixmap)
        self.update()

    def clear_cover(self) -> None:
        self._cover = QPixmap()
        self.clear()
        self.update()

    def pixmap(self) -> QPixmap:
        return self._cover

    def sizeHint(self) -> QSize:
        return QSize(320, 180)

    def minimumSizeHint(self) -> QSize:
        return QSize(16, 16)

    def paintEvent(self, event) -> None:
        if self._cover.isNull():
            super().paintEvent(event)
            return
        target = self.rect()
        mode = (
            Qt.AspectRatioMode.KeepAspectRatio
            if self._fit == "contain"
            else Qt.AspectRatioMode.KeepAspectRatioByExpanding
        )
        scaled = self._cover.scaled(
            target.size() if not target.isEmpty() else QSize(16, 16),
            mode,
            Qt.TransformationMode.SmoothTransformation,
        )
        offset = QPoint(
            target.center().x() - scaled.width() // 2,
            target.center().y() - scaled.height() // 2,
        )
        painter = QPainter(self)
        if self._radius > 0:
            path = QPainterPath()
            path.addRoundedRect(QRect(target), self._radius, self._radius)
            painter.setClipPath(path)
        painter.drawPixmap(offset, scaled)
        painter.end()
