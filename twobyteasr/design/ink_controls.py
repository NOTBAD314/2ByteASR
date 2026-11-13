"""Controls of the style tab's shadow editor (2026-11-13, user).

``ShadowStage`` shows a line of caption text with the shadow being edited;
dragging on it moves the shadow, which sets direction and distance in one
gesture.  ``PillSlider`` is a rounded bar that carries its caption, its value
and its level together and drives an existing spin box, so the page keeps one
value holder per property.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractSpinBox, QSizePolicy, QWidget

from ..i18n import tr
from .theme_manager import theme_key
from .typography import weighted_font
from .ui_theme import blend_hex, theme_definition


class PillSlider(QWidget):
    """Rounded slider bound to ``spin``: drag anywhere on it, or use the
    arrow keys.  The spin box stays the value holder and may be hidden."""

    scrubStarted = Signal()
    scrubFinished = Signal()

    HEIGHT = 30

    def __init__(self, spin: QAbstractSpinBox, label: str, unit: str = "px", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spin = spin
        self._label = str(label)
        self._unit = str(unit)
        self._dragging = False
        self.setObjectName("pillSlider")
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(self._label)
        spin.valueChanged.connect(lambda *_args: self.update())
        spin.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.spin and event.type() == QEvent.Type.EnabledChange:
            self.update()  # the page switches the spin box off for web themes
        return super().eventFilter(watched, event)

    def _active(self) -> bool:
        return self.isEnabled() and self.spin.isEnabled()

    def fraction(self) -> float:
        low, high = float(self.spin.minimum()), float(self.spin.maximum())
        return 0.0 if high <= low else min(1.0, max(0.0, (float(self.spin.value()) - low) / (high - low)))

    def _set_from_x(self, x: float) -> None:
        inset = self.HEIGHT / 2.0
        span = max(1.0, self.width() - 2.0 * inset)
        share = min(1.0, max(0.0, (x - inset) / span))
        low, high = float(self.spin.minimum()), float(self.spin.maximum())
        self.spin.setValue(round(low + share * (high - low)))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._active():
            self._dragging = True
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.scrubStarted.emit()
            self._set_from_x(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._set_from_x(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._set_from_x(event.position().x())
            self.scrubFinished.emit()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Down: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: 1}.get(event.key())
        if step is None or not self._active():
            super().keyPressEvent(event)
            return
        self.spin.setValue(self.spin.value() + step * self.spin.singleStep())
        event.accept()

    def wheelEvent(self, event) -> None:
        event.ignore()  # the panel scrolls; a pass over the slider changes nothing

    def paintEvent(self, _event) -> None:
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._active():
            painter.setOpacity(0.5)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = rect.height() / 2.0
        track = QPainterPath()
        track.addRoundedRect(rect, radius, radius)
        painter.fillPath(track, QColor(blend_hex(theme.surface, theme.text, 0.07)))
        # The level: a pill inside the pill, never shorter than a circle.
        level = QRectF(rect.left(), rect.top(), max(rect.height(), rect.width() * self.fraction()), rect.height())
        fill = QLinearGradient(level.topLeft(), level.bottomLeft())
        fill.setColorAt(0.0, QColor(blend_hex(theme.surface_elevated, theme.accent, 0.20)))
        fill.setColorAt(1.0, QColor(blend_hex(theme.surface_elevated, theme.accent, 0.34)))
        painter.setPen(QPen(QColor(blend_hex(theme.surface_elevated, theme.accent, 0.5)), 1.0))
        painter.setBrush(fill)
        painter.drawRoundedRect(level, radius, radius)
        if self.hasFocus() or self._dragging:
            painter.setPen(QPen(QColor(theme.accent), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, radius, radius)
        font = QFont(self.font())
        font.setPixelSize(12)
        weighted_font(font, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(theme.text_secondary))
        text_rect = rect.adjusted(12.0, 0.0, -12.0, 0.0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(tr(self._label)))
        value = f"{float(self.spin.value()):g}"
        metrics = QFontMetrics(font)
        unit_width = metrics.horizontalAdvance(" " + self._unit)
        painter.setPen(QColor(theme.text_muted))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, " " + self._unit)
        painter.setPen(QColor(theme.text))
        painter.drawText(text_rect.adjusted(0.0, 0.0, -unit_width, 0.0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, value)
        painter.end()


class ShadowStage(QWidget):
    """A strip of caption text casting the edited shadow.  Dragging moves
    the shadow.  Takes the place of the angle disc: ``angle`` / ``setAngle`` /
    ``angleChanged`` keep its contract, and ``distanceChanged`` carries the
    other half of the gesture."""

    angleChanged = Signal(float)
    distanceChanged = Signal(float)
    scrubStarted = Signal()
    scrubFinished = Signal()

    PIXELS_PER_UNIT = 1.7
    DRAG_LIMIT = 40.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 135.0
        self._distance = 6.0
        self._color = QColor("#000000")
        self._opacity = 0.45
        self._blur = 3.0
        self._spread = 0.0
        self._dragging = False
        self.setObjectName("shadowStage")
        self.setFixedHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("阴影方向")

    def angle(self) -> float:
        return self._angle

    def setAngle(self, value: float) -> None:  # noqa: N802 - the disc's API
        wrapped = float(value) % 360.0
        if abs(wrapped - self._angle) < 0.05:
            return
        self._angle = wrapped
        self.update()
        self.angleChanged.emit(self._angle)

    def distance(self) -> float:
        return self._distance

    def setDistance(self, value: float) -> None:  # noqa: N802 - Qt naming
        """Show ``value``; only a drag emits ``distanceChanged``."""
        if abs(float(value) - self._distance) < 0.01:
            return
        self._distance = max(0.0, float(value))
        self.update()

    def set_look(self, color: QColor, opacity: float, blur: float, spread: float = 0.0) -> None:
        look = (QColor(color).rgb(), round(float(opacity), 3), float(blur), float(spread))
        if look == (self._color.rgb(), round(self._opacity, 3), self._blur, self._spread):
            return
        self._color = QColor(color)
        self._opacity, self._blur, self._spread = float(opacity), float(blur), float(spread)
        self.update()

    def _set_from_pos(self, pos) -> None:
        dx = (pos.x() - self.width() / 2.0) / self.PIXELS_PER_UNIT
        dy = (pos.y() - self.height() / 2.0) / self.PIXELS_PER_UNIT
        distance = float(round(min(self.DRAG_LIMIT, math.hypot(dx, dy))))
        if distance >= 1.0:
            angle = math.degrees(math.atan2(dy, dx))
            self.setAngle(round(angle + 360.0) % 360.0)
        if distance != self._distance:
            self._distance = distance
            self.update()
            self.distanceChanged.emit(distance)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.scrubStarted.emit()
            self._set_from_pos(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._set_from_pos(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._set_from_pos(event.position())
            self.scrubFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        frame = QPainterPath()
        frame.addRoundedRect(rect, 14.0, 14.0)
        # A mid tone: light and dark shadows both show on it.
        back = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        back.setColorAt(0.0, QColor(blend_hex(theme.media, "#ffffff", 0.50)))
        back.setColorAt(1.0, QColor(blend_hex(theme.media, "#ffffff", 0.38)))
        painter.fillPath(frame, back)
        painter.setClipPath(frame)
        font = QFont(self.font())
        font.setPixelSize(27)
        weighted_font(font, QFont.Weight.ExtraBold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        text = str(tr("字幕样式"))
        metrics = QFontMetrics(font)
        glyphs = QPainterPath()
        glyphs.addText(rect.center().x() - metrics.horizontalAdvance(text) / 2.0,
                       rect.center().y() + (metrics.ascent() - metrics.descent()) / 2.0, font, text)
        radians = math.radians(self._angle)
        offset = QPointF(math.cos(radians) * self._distance, math.sin(radians) * self._distance)
        if self._opacity > 0.0:
            # Soft edge: a few faint copies around the offset stand in for the blur.
            soft = min(6.0, self._blur * 0.35 + self._spread * 0.3)
            copies = [(0.0, 0.0)] if soft < 0.4 else [(0.0, 0.0)] + [
                (math.cos(i * math.pi / 4.0) * soft, math.sin(i * math.pi / 4.0) * soft) for i in range(8)]
            shade = QColor(self._color)
            shade.setAlphaF(min(1.0, self._opacity) / (1.0 if len(copies) == 1 else 3.2))
            for jx, jy in copies:
                painter.fillPath(glyphs.translated(offset.x() * 0.8 + jx, offset.y() * 0.8 + jy), shade)
        painter.strokePath(glyphs, QPen(QColor("#1d1712"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                        Qt.PenJoinStyle.RoundJoin))
        painter.fillPath(glyphs, QColor("#ffffff"))
        # The handle sits where the shadow has gone.
        handle = rect.center() + offset * self.PIXELS_PER_UNIT
        painter.setPen(QPen(QColor("#ffffff"), 2.5))
        accent = QColor(theme.accent)
        accent.setAlphaF(0.78)
        painter.setBrush(accent)
        painter.drawEllipse(handle, 6.5, 6.5)
        small = QFont(self.font())
        small.setPixelSize(11)
        weighted_font(small, QFont.Weight.DemiBold)
        painter.setFont(small)
        small_metrics = QFontMetrics(small)
        readout = f"{self._angle:.0f}° · {self._distance:g} px"
        chip = QRectF(0.0, 0.0, small_metrics.horizontalAdvance(readout) + 16.0, 18.0)
        chip.moveTopRight(QPointF(rect.right() - 8.0, rect.top() + 7.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 66))
        painter.drawRoundedRect(chip, 9.0, 9.0)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, readout)
        painter.setPen(QColor(255, 255, 255, 178))
        painter.drawText(rect.adjusted(10.0, 0.0, 0.0, -6.0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, str(tr("拖一拖影子")))
        painter.end()
