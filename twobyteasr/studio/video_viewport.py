"""Keep the native picture at video aspect while Qt owns the letterbox bars.

Windows can scale the last GPU buffer before mpv presents its next frame.
A picture-shaped child keeps that intermediate frame in proportion too.
"""
import math

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import QWidget


def fitted_video_rect(size: QSize, aspect: float) -> QRect:
    width, height = max(1, size.width()), max(1, size.height())
    if not math.isfinite(aspect) or aspect <= 0:
        aspect = 16 / 9
    fitted_width = min(width, max(1, round(height * aspect)))
    fitted_height = min(height, max(1, round(fitted_width / aspect)))
    return QRect((width - fitted_width) // 2, (height - fitted_height) // 2,
                 fitted_width, fitted_height)


class VideoViewportHost(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioVideoOverlayHost")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#studioVideoOverlayHost { background: #000; }")
        self._video_canvas = None
        self._video_aspect = 16 / 9

    def set_canvas(self, canvas: QWidget) -> None:
        self._video_canvas = canvas
        canvas.setParent(self)
        canvas.setMinimumSize(1, 1)
        self._fit_video()
        canvas.show()

    def set_video_size(self, width: int, height: int) -> None:
        if width > 0 and height > 0:
            self._video_aspect = width / height
            self._fit_video()

    def _fit_video(self) -> None:
        if self._video_canvas is None:
            return
        target = fitted_video_rect(self.size(), self._video_aspect)
        if self._video_canvas.geometry() != target:
            self._video_canvas.setGeometry(target)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_video()
