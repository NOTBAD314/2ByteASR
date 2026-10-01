"""Small, reusable Subtitle Studio widgets."""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtWidgets import QLabel

from .themed_icons import themed_icon
from .ui_theme import MUTED

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox

from .i18n import bind_text


class StudioStatusLabel(QLabel):
    """A single-line status with full localized text available on hover."""
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self._full_text = ''
        self.setText(text)

    def text(self):
        return self._full_text

    def setText(self, text):
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(20,self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class _ScrubMixin:
    """Wheel-safe numeric field with horizontal scrub preview."""

    def _init_scrub(self):
        self._scrubbing = False
        self._scrub_pending = False
        self._scrub_origin = QPoint()
        self._scrub_value = 0
        self.setMouseTracking(True)
        self.lineEdit().setMouseTracking(True)
        self.lineEdit().installEventFilter(self)
        self.lineEdit().setCursor(Qt.CursorShape.SizeHorCursor)
        bind_text(self, '左右拖动调整数值；双击可直接输入', property='toolTip')

    def eventFilter(self, watched, event) -> bool:
        if watched is self.lineEdit():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._begin_scrub_pointer(event.globalPosition().toPoint())
                return False
            if event.type() == QEvent.Type.MouseMove:
                return self._move_scrub_pointer(event.globalPosition().toPoint(), event.modifiers())
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                return self._end_scrub_pointer()
        return super().eventFilter(watched, event)

    def _begin_scrub_pointer(self, point: QPoint) -> None:
        self._scrub_pending = True
        self._scrub_origin = QPoint(point)
        self._scrub_value = self.value()

    def _move_scrub_pointer(self, point: QPoint, modifiers) -> bool:
        if self._scrub_pending and not self._scrubbing:
            if abs(point.x() - self._scrub_origin.x()) >= 4:
                self._scrubbing = True
                self.lineEdit().grabMouse()
                self.scrubStarted.emit()
        if not self._scrubbing:
            return False
        delta = point.x() - self._scrub_origin.x()
        step = float(self.singleStep())
        multiplier = 0.25 if modifiers & Qt.KeyboardModifier.ShiftModifier else 1.0
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            multiplier = 5.0
        value = self._scrub_value + delta * step * multiplier / 4.0
        if isinstance(self, QSpinBox):
            value = round(value)
        self.setValue(value)
        return True

    def _end_scrub_pointer(self) -> bool:
        was_scrubbing = self._scrubbing
        self._scrub_pending = False
        if was_scrubbing:
            self._scrubbing = False
            self.lineEdit().releaseMouse()
            self.lineEdit().unsetCursor()
            self.unsetCursor()
            self.scrubFinished.emit()
        return was_scrubbing

    def _cancel_scrub(self) -> None:
        self._scrub_pending = False
        if self._scrubbing:
            self._scrubbing = False
            self.lineEdit().releaseMouse()
            self.scrubFinished.emit()
        self.lineEdit().unsetCursor()
        self.unsetCursor()

    def focusOutEvent(self, event) -> None:
        self._cancel_scrub()
        super().focusOutEvent(event)

    def event(self, event) -> bool:
        if event.type() in {QEvent.Type.WindowDeactivate, QEvent.Type.Hide}:
            self._cancel_scrub()
        return super().event(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin_scrub_pointer(self.mapToGlobal(event.position().toPoint()))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._move_scrub_pointer(self.mapToGlobal(event.position().toPoint()), event.modifiers()):
            event.accept()
            return
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._end_scrub_pointer():
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ScrubSpinBox(_ScrubMixin, QSpinBox):
    scrubStarted = Signal()
    scrubFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_scrub()


class ScrubDoubleSpinBox(_ScrubMixin, QDoubleSpinBox):
    scrubStarted = Signal()
    scrubFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_scrub()


def _icon(name: str, color: str | None = None):
    # No explicit color means "follow the active theme's primary icon color".
    if color is None:
        return themed_icon(name, "primary")
    return qta.icon(name, color=color)


def _time_spinbox() -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 24 * 60 * 60 * 1000)
    spin.setSuffix(" ms")
    spin.setSingleStep(50)
    spin.setMinimumWidth(112)
    return spin


def _icon_label(name: str) -> QLabel:
    label = QLabel()
    label.setPixmap(_icon(name, MUTED).pixmap(16, 16))
    return label
