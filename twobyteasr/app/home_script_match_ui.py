# SPDX-License-Identifier: GPL-3.0-only
"""Painted parts of the 首页「匹配文稿」 wizard (2026-11-12, design C).

Step badges (todo / current / done), the line between them and the drop
zone of the first step. Colours come from the active theme at paint time.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget
from ..design.typography import weighted_font


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _px(value: float) -> int:
    from .ui_zoom import px
    return px(value)


class StepBadge(QWidget):
    """A numbered circle; ``current`` wears a soft ring, ``done`` a check mark."""

    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self.number = number
        self.state = 'todo'
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_state(self, state: str):
        if state != self.state:
            self.state = state
            self.update()

    def sizeHint(self):
        return QSize(_px(36), _px(36))

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = _px(26)
        circle = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.state == 'current':
            painter.setBrush(QColor(t.accent_soft))
            painter.drawEllipse(circle.adjusted(-_px(5), -_px(5), _px(5), _px(5)))
            fill, ink = t.accent, '#ffffff'
        elif self.state == 'done':
            fill, ink = t.success, '#ffffff'
        else:
            fill, ink = t.border, t.text_muted
        painter.setBrush(QColor(fill))
        painter.drawEllipse(circle)
        if self.state == 'done':
            pen = QPen(QColor(ink), max(2.0, _px(2.6)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            c = circle.center()
            u = side / 26
            path = QPainterPath(QPointF(c.x() - 5.5 * u, c.y() + 0.5 * u))
            path.lineTo(QPointF(c.x() - 1.5 * u, c.y() + 4.5 * u))
            path.lineTo(QPointF(c.x() + 6 * u, c.y() - 4 * u))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        else:
            font = self.font()
            font.setPixelSize(_px(13))
            weighted_font(font, 700)
            painter.setFont(font)
            painter.setPen(QColor(ink))
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(self.number))
        painter.end()


class StepLine(QWidget):
    """The rounded bar between two steps; green once the step before is done."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.done = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(_px(24))

    def set_done(self, done: bool):
        if bool(done) != self.done:
            self.done = bool(done)
            self.update()

    def sizeHint(self):
        return QSize(_px(60), _px(36))

    def paintEvent(self, event):
        t = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.success if self.done else t.border))
        h = max(2, _px(3))
        painter.drawRoundedRect(QRectF(0, (self.height() - h) / 2, self.width(), h), h / 2, h / 2)
        painter.end()


class DropZone(QFrame):
    """Accepts one dropped audio or video file and hands its path to ``on_media``."""

    def __init__(self, on_media, parent=None):
        super().__init__(parent)
        self.on_media = on_media
        self.setObjectName('scriptDropZone')
        self.setAcceptDrops(True)

    @staticmethod
    def _media_path(event):
        from .main_ui_helpers import SUPPORTED_MEDIA_SUFFIXES
        mime = event.mimeData()
        if not mime.hasUrls():
            return ''
        for url in mime.urls():
            path = Path(url.toLocalFile())
            if url.isLocalFile() and path.suffix.lower() in SUPPORTED_MEDIA_SUFFIXES:
                return str(path)
        return ''

    def _mark(self, dragging: bool):
        self.setProperty('dragging', 'true' if dragging else 'false')
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if self.isEnabled() and self._media_path(event):
            self._mark(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._mark(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._mark(False)
        path = self._media_path(event)
        if path:
            event.acceptProposedAction()
            self.on_media(path)


__all__ = ['DropZone', 'StepBadge', 'StepLine']
