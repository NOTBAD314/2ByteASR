"""Shared P9A form and toolbar controls.

Existing page.style_* spinboxes stay as ScrubDoubleSpinBox instances.
CompactNumericField wraps them for label + unit chrome without replacing
the live attribute.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme_manager import theme_key
from ..ui_theme import theme_definition


def polar_to_offset(angle_deg: float, distance: float) -> tuple[float, float]:
    """0° = east, 90° = screen-down (Qt y-down)."""
    radians = math.radians(float(angle_deg))
    return math.cos(radians) * float(distance), math.sin(radians) * float(distance)


def offset_to_polar(offset_x: float, offset_y: float) -> tuple[float, float]:
    distance = math.hypot(float(offset_x), float(offset_y))
    angle = math.degrees(math.atan2(float(offset_y), float(offset_x)))
    if angle < 0:
        angle += 360.0
    return angle, distance


class CompactNumericField(QWidget):
    """Label + compact numeric control + unit. Wraps an existing spinbox."""

    def __init__(
        self,
        spin: QAbstractSpinBox,
        *,
        label: str = "",
        unit: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.spin = spin
        self.setObjectName("compactNumericField")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if label:
            caption = QLabel(label)
            caption.setObjectName("styleFieldLabel")
            layout.addWidget(caption)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        spin.setMinimumHeight(28)
        spin.setMaximumHeight(32)
        spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row.addWidget(spin, 1)
        if unit:
            unit_label = QLabel(unit)
            unit_label.setObjectName("styleFieldLabel")
            row.addWidget(unit_label)
        layout.addLayout(row)


class AngleDisc(QWidget):
    """Compact 0–360° direction control. Does not own shadow offset fields."""

    angleChanged = Signal(float)
    scrubStarted = Signal()
    scrubFinished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 135.0
        self.setObjectName("angleDisc")
        self.setFixedSize(72, 72)
        self.setToolTip("阴影方向")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def angle(self) -> float:
        return self._angle

    def setAngle(self, value: float) -> None:
        wrapped = float(value) % 360.0
        if wrapped < 0:
            wrapped += 360.0
        if abs(wrapped - self._angle) < 0.05:
            return
        self._angle = wrapped
        self.update()
        self.angleChanged.emit(self._angle)

    def _set_from_pos(self, pos) -> None:
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        delta = QPointF(pos.x(), pos.y()) - center
        if delta.manhattanLength() < 1:
            return
        angle = math.degrees(math.atan2(delta.y(), delta.x()))
        if angle < 0:
            angle += 360.0
        self.setAngle(angle)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.scrubStarted.emit()
            self._set_from_pos(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from_pos(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_from_pos(event.position())
            self.scrubFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(QColor(theme.border_strong), 1.5))
        painter.setBrush(QColor(theme.surface_elevated))
        painter.drawEllipse(rect)
        cx, cy = rect.center().x(), rect.center().y()
        radius = rect.width() / 2.0
        painter.setPen(QPen(QColor(theme.border), 1))
        for degree in range(0, 360, 45):
            radians = math.radians(degree)
            inner = radius - 7
            outer = radius - 2
            painter.drawLine(
                QPointF(cx + math.cos(radians) * inner, cy + math.sin(radians) * inner),
                QPointF(cx + math.cos(radians) * outer, cy + math.sin(radians) * outer),
            )
        radians = math.radians(self._angle)
        knob = QPointF(cx + math.cos(radians) * (radius - 12), cy + math.sin(radians) * (radius - 12))
        painter.setPen(QPen(QColor(theme.accent), 2))
        painter.drawLine(QPointF(cx, cy), knob)
        painter.setBrush(QColor(theme.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(knob, 5, 5)
        painter.setPen(QColor(theme.text))
        font = QFont(painter.font())
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._angle:.0f}°")
        painter.end()


class StyledCheckBox(QAbstractButton):
    """Painted checkbox so Fusion/native indicators cannot double-draw."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(max(28 + metrics.horizontalAdvance(self.text()) + 12, 72), 28)

    def paintEvent(self, _event) -> None:
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(4, (self.height() - 16) / 2, 16, 16)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent))
            painter.drawRoundedRect(box, 3, 3)
            path = QPainterPath()
            path.moveTo(box.left() + 3.5, box.center().y())
            path.lineTo(box.left() + 6.5, box.bottom() - 4)
            path.lineTo(box.right() - 3.5, box.top() + 3.5)
            painter.setPen(QPen(QColor(theme.text_on_accent), 1.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        else:
            painter.setPen(QPen(QColor(theme.border_strong if self.underMouse() else theme.border), 1))
            painter.setBrush(QColor(theme.surface_elevated))
            painter.drawRoundedRect(box, 3, 3)
        painter.setPen(QColor(theme.text if self.isEnabled() else theme.disabled))
        text_rect = QRectF(24, 0, self.width() - 28, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()


class StyledRadio(QAbstractButton):
    """Painted radio so native Windows indicators cannot nest inside QSS."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(max(28 + metrics.horizontalAdvance(self.text()) + 12, 72), 28)

    def paintEvent(self, _event) -> None:
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(4, (self.height() - 16) / 2, 16, 16)
        painter.setPen(QPen(QColor(theme.accent if self.isChecked() else theme.border_strong), 1.5))
        painter.setBrush(QColor(theme.surface_elevated))
        painter.drawEllipse(box)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent))
            painter.drawEllipse(box.adjusted(4, 4, -4, -4))
        painter.setPen(QColor(theme.text if self.isEnabled() else theme.disabled))
        text_rect = QRectF(24, 0, self.width() - 28, self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        painter.end()


class ToolbarButton(QToolButton):
    """32–36 hit target, 24px icon, tooltip required."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioTool")
        self.setIconSize(QSize(24, 24))
        self.setMinimumSize(32, 32)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class IconButton(ToolbarButton):
    """Alias for unlabeled icon actions that must carry a tooltip."""
