"""Rounded widgets for the subtitle Fill editor (2026-11-03 redesign, plan B).

Pill segments, a hue ring around a rounded saturation/value square, a pill
opacity strip, a current/previous plate, round swatches, an angle dial and
``FillColorPicker`` (the right-hand column of the dialog). Every colour is
read from the active ThemeDefinition at paint time.

All Studio appearance entries use this picker. General color dialogs outside
the appearance editor may still use ``color_picker``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QConicalGradient, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import bind_text
from .color_picker import _start_screen_eyedrop, alpha_to_percent, percent_to_alpha, rgb_to_yuv, yuv_to_rgb
from .theme_manager import theme_key
from .typography import MONO_FONT_FAMILIES
from .ui_motion import motion_duration
from .ui_theme import ThemeDefinition, theme_definition
from .typography import emphasized, weighted_font


def _theme() -> ThemeDefinition:
    return theme_definition(theme_key())


_CHECKERS: dict[tuple[int, bool], QBrush] = {}


def checker_brush(cell: int = 5, dark: bool = False) -> QBrush:
    """Cached two-tone checkerboard brush so translucent colors stay readable."""
    key = (cell, dark)
    brush = _CHECKERS.get(key)
    if brush is None:
        light, shade = (QColor("#2b2531"), QColor("#211c26")) if dark else (QColor("#efebf1"), QColor("#d2ccd6"))
        pixmap = QPixmap(cell * 2, cell * 2)
        pixmap.fill(light)
        painter = QPainter(pixmap)
        painter.fillRect(cell, 0, cell, cell, shade)
        painter.fillRect(0, cell, cell, cell, shade)
        painter.end()
        brush = _CHECKERS[key] = QBrush(pixmap)
    return brush


def paint_knob(painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
    """White-ring knob with a soft drop shadow; translucent colors sit on a checker."""
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 60))
    painter.drawEllipse(center + QPointF(0, 1.6), radius + 1.2, radius + 1.2)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(center, radius, radius)
    inner = max(1.0, radius - 3.0)
    if color.alpha() < 255:
        painter.setBrush(checker_brush(4))
        painter.drawEllipse(center, inner, inner)
    painter.setBrush(color)
    painter.drawEllipse(center, inner, inner)
    painter.restore()


def animate_value(owner: QWidget, attr: str, end: float, duration: int = 240, *, spring: bool = True) -> None:
    """Tween ``owner.<attr>`` toward ``end`` and repaint; honours reduced motion."""
    duration = motion_duration(duration)
    animation = getattr(owner, f"_{attr}_animation", None)
    if animation is not None:
        animation.stop()
    if not duration:
        setattr(owner, attr, float(end))
        owner.update()
        return
    if animation is None:
        animation = QVariantAnimation(owner)
        animation.valueChanged.connect(lambda value: (setattr(owner, attr, float(value)), owner.update()))
        setattr(owner, f"_{attr}_animation", animation)
    animation.setEasingCurve(QEasingCurve.Type.OutBack if spring else QEasingCurve.Type.OutCubic)
    animation.setDuration(duration)
    animation.setStartValue(float(getattr(owner, attr)))
    animation.setEndValue(float(end))
    animation.start()


def mode_icon(kind: str, color: QColor, size: int = 16) -> QPixmap:
    """Solid / linear / radial glyphs for the fill mode segment."""
    ratio = 2.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    c = QPointF(size / 2, size / 2)
    def tinted(alpha: float) -> QColor:
        value = QColor(color)
        value.setAlphaF(alpha)
        return value
    if kind == "solid":
        painter.setBrush(color)
        painter.drawEllipse(c, size * 0.37, size * 0.37)
    elif kind == "linear":
        width = size * 0.25
        for index, alpha in enumerate((1.0, 0.6, 0.3)):
            painter.setBrush(tinted(alpha))
            painter.drawRoundedRect(QRectF(size * 0.1 + index * width * 1.12, size * 0.16, width, size * 0.68), width / 2, width / 2)
    else:
        for radius, alpha in ((0.42, 0.28), (0.28, 0.6), (0.13, 1.0)):
            painter.setBrush(tinted(alpha))
            painter.drawEllipse(c, size * radius, size * radius)
    painter.end()
    return pixmap


def mono_font(size: int = 13, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    font = QFont()
    font.setFamilies(list(MONO_FONT_FAMILIES))
    font.setPixelSize(size)
    weighted_font(font, weight)
    return font


class PillSegment(QWidget):
    """Segmented control with its accent pill bound to the selected option.

    ``group`` is an exclusive QButtonGroup of the option buttons;
    ``currentIndex`` / ``setCurrentIndex`` keep QComboBox-style callers working.
    """

    currentIndexChanged = Signal(int)

    def __init__(self, items, parent=None, *, height: int = 40, icons: bool = False):
        super().__init__(parent)
        self.setObjectName("fillSegment")
        self._icons = icons
        self._pill = QRectF()
        self.setFixedHeight(height)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for index, (text, kind) in enumerate(items):
            button = QPushButton(text)
            button.setObjectName("fillSegButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("fillKind", kind)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.group.addButton(button, index)
            layout.addWidget(button)
        self.group.idToggled.connect(self._toggled)
        self._pill_animation = QVariantAnimation(self)
        self._pill_animation.setEasingCurve(QEasingCurve.Type.OutBack)
        self._pill_animation.valueChanged.connect(self._set_pill)
        self.refresh_icons()

    def button(self, index: int) -> QPushButton | None:
        return self.group.button(index)

    def count(self) -> int:
        return len(self.group.buttons())

    def currentIndex(self) -> int:
        return self.group.checkedId()

    def setCurrentIndex(self, index: int) -> None:
        button = self.group.button(int(index))
        if button is not None:
            button.setChecked(True)

    def refresh_icons(self) -> None:
        if not self._icons:
            return
        theme = _theme()
        for button in self.group.buttons():
            kind = str(button.property("fillKind") or "")
            icon = QIcon()
            icon.addPixmap(mode_icon(kind, QColor(theme.text_muted)), QIcon.Mode.Normal, QIcon.State.Off)
            icon.addPixmap(mode_icon(kind, QColor(theme.text_on_accent)), QIcon.Mode.Normal, QIcon.State.On)
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))

    def _target(self) -> QRectF:
        button = self.group.checkedButton()
        return QRectF(button.geometry()) if button is not None else QRectF()

    def _set_pill(self, rect) -> None:
        self._pill = QRectF(rect)
        self.update()

    def _snap(self) -> None:
        self._pill_animation.stop()
        self._set_pill(self._target())

    def _toggled(self, index: int, checked: bool) -> None:
        if not checked:
            return
        # Selection and its text change together. A spring could overshoot
        # the track and leave the accent pill under a neighbouring label.
        self._snap()
        self.currentIndexChanged.emit(index)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._snap)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._snap)

    def paintEvent(self, _event) -> None:
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(QColor(theme.input_surface))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        if not self._pill.isNull():
            pill = QRectF(self._pill)
            glow = QColor(theme.accent)
            glow.setAlpha(60)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(pill.translated(0, 2), pill.height() / 2, pill.height() / 2)
            painter.setBrush(QColor(theme.accent))
            painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        painter.end()


class RoundSVPlane(QWidget):
    """Rounded saturation (x) × value (y) square for one hue."""

    changed = Signal(float, float)
    MARGIN = 13

    def __init__(self, parent=None, *, side: int = 128):
        super().__init__(parent)
        self._side = side
        self._hue = 0.0
        self._sat = 0.0
        self._val = 1.0
        self.grow = 0.0
        self._cache: QImage | None = None
        self._cache_key: tuple | None = None
        self.setFixedSize(side + self.MARGIN * 2, side + self.MARGIN * 2)
        self.setCursor(Qt.CursorShape.CrossCursor)
        bind_text(self, '拖动选择饱和度和亮度', property='toolTip')

    def plane_rect(self) -> QRectF:
        scale = min(self.width(), self.height()) / (self._side + self.MARGIN*2)
        side = self._side * scale
        return QRectF((self.width()-side)/2, (self.height()-side)/2, side, side)

    def set_hsv(self, hue: float, saturation: float, value: float) -> None:
        self._hue, self._sat, self._val = float(hue) % 360.0, float(saturation), float(value)
        self.update()

    def color(self) -> QColor:
        return QColor.fromHsvF(self._hue / 360.0, self._sat, self._val)

    def _apply(self, position: QPointF) -> None:
        rect = self.plane_rect()
        self._sat = min(1.0, max(0.0, (position.x() - rect.left()) / rect.width()))
        self._val = min(1.0, max(0.0, 1.0 - (position.y() - rect.top()) / rect.height()))
        self.update()
        self.changed.emit(self._sat, self._val)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            animate_value(self, "grow", 1.0)
            self._apply(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        animate_value(self, "grow", 0.0)
        super().mouseReleaseEvent(event)

    def _image(self) -> QImage:
        ratio = self.devicePixelRatioF()
        size = max(1, round(self.plane_rect().width() * ratio))
        key = (round(self._hue, 1), size)
        if self._cache is None or self._cache_key != key:
            image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor.fromHsvF(self._hue / 360.0, 1.0, 1.0))
            painter = QPainter(image)
            white = QLinearGradient(0, 0, size, 0)
            white.setColorAt(0.0, QColor(255, 255, 255, 255))
            white.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(0, 0, size, size, white)
            black = QLinearGradient(0, 0, 0, size)
            black.setColorAt(0.0, QColor(0, 0, 0, 0))
            black.setColorAt(1.0, QColor(0, 0, 0, 255))
            painter.fillRect(0, 0, size, size, black)
            painter.end()
            image.setDevicePixelRatio(ratio)
            self._cache, self._cache_key = image, key
        return self._cache

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = self.plane_rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        painter.save()
        painter.setClipPath(path)
        painter.drawImage(rect, self._image())
        painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 22), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        center = QPointF(rect.left() + self._sat * rect.width(), rect.top() + (1.0 - self._val) * rect.height())
        paint_knob(painter, center, 10.5 + 3.5 * self.grow, self.color())
        painter.end()


class ColorWheel(QWidget):
    """Hue ring (0° at the top, clockwise) around a ``RoundSVPlane``."""

    hueChanged = Signal(float)
    SIZE = 252
    BAND = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0.0
        self.grow = 0.0
        self._dragging = False
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sv = RoundSVPlane(self, side=128)
        offset = (self.SIZE - self.sv.width()) // 2
        self.sv.move(offset, offset)
        self.sv.installEventFilter(self)
        bind_text(self, '拖动圆环选择色相', property='toolTip')

    def _outer(self) -> float:
        return min(self.width(), self.height()) * (0.5 - 8/self.SIZE)

    def _band(self) -> float:
        return self.BAND * min(self.width(),self.height()) / self.SIZE

    def _center_plane(self):
        if hasattr(self, 'sv'):
            self.sv.move(round((self.width()-self.sv.width())/2), round((self.height()-self.sv.height())/2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._center_plane()

    def eventFilter(self, watched, event):
        if watched is self.sv and event.type() == QEvent.Type.Resize:
            self._center_plane()
        return super().eventFilter(watched,event)

    def hue(self) -> float:
        return self._hue

    def set_hue(self, hue: float) -> None:
        self._hue = float(hue) % 360.0
        self.update()

    def _hit_band(self, position: QPointF) -> bool:
        center = QPointF(self.width() / 2, self.height() / 2)
        distance = math.hypot(position.x() - center.x(), position.y() - center.y())
        return self._outer() - self._band() - 8 <= distance <= self._outer() + 8

    def _apply(self, position: QPointF) -> None:
        dx = position.x() - self.width() / 2
        dy = position.y() - self.height() / 2
        self._hue = (math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0
        self.update()
        self.hueChanged.emit(self._hue)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._hit_band(event.position()):
            self._dragging = True
            animate_value(self, "grow", 1.0)
            self._apply(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._apply(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            animate_value(self, "grow", 0.0)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(self.width() / 2, self.height() / 2)
        outer = self._outer()
        inner = outer - self._band()
        gradient = QConicalGradient(center, 90)
        for step in range(13):
            t = step / 12
            gradient.setColorAt(t, QColor.fromHsvF(((1.0 - t) % 1.0), 1.0, 1.0))
        ring = QPainterPath()
        ring.addEllipse(center, outer, outer)
        ring.addEllipse(center, inner, inner)
        ring.setFillRule(Qt.FillRule.OddEvenFill)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(ring)
        painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, inner, inner)
        mid = outer - self._band() / 2
        radians = math.radians(self._hue)
        knob = QPointF(center.x() + mid * math.sin(radians), center.y() - mid * math.cos(radians))
        paint_knob(painter, knob, 11.5 + 3.5 * self.grow, QColor.fromHsvF(self._hue / 360.0, 1.0, 1.0))
        painter.end()


class PillAlphaSlider(QWidget):
    """Opacity strip: transparent on the left, opaque on the right."""

    alphaChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alpha = 255
        self._color = QColor("#FFFFFF")
        self.grow = 0.0
        self.setFixedHeight(30)
        self.setMinimumWidth(120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, '透明度', property='toolTip')

    def alpha(self) -> int:
        return self._alpha

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color.red(), color.green(), color.blue())
        self.update()

    def set_alpha(self, alpha: int) -> None:
        self._alpha = max(0, min(255, int(alpha)))
        self.update()

    def _track(self) -> QRectF:
        return QRectF(12, (self.height() - 16) / 2, max(1, self.width() - 24), 16)

    def _apply(self, position: QPointF) -> None:
        track = self._track()
        ratio = min(1.0, max(0.0, (position.x() - track.left()) / track.width()))
        self._alpha = round(ratio * 255)
        self.update()
        self.alphaChanged.emit(self._alpha)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            animate_value(self, "grow", 1.0)
            self._apply(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        animate_value(self, "grow", 0.0)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = self._track()
        bar = track.adjusted(-8, 0, 8, 0)
        path = QPainterPath()
        path.addRoundedRect(bar, bar.height() / 2, bar.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(checker_brush(5))
        painter.drawPath(path)
        gradient = QLinearGradient(bar.topLeft(), bar.topRight())
        clear = QColor(self._color)
        clear.setAlpha(0)
        gradient.setColorAt(0.0, clear)
        gradient.setColorAt(1.0, self._color)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(0, 0, 0, 45), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        color = QColor(self._color)
        color.setAlpha(self._alpha)
        center = QPointF(track.left() + self._alpha / 255.0 * track.width(), track.center().y())
        paint_knob(painter, center, 11 + 3 * self.grow, color)
        painter.end()


class SplitPlate(QWidget):
    """Pill split in two: current color on the left, previous on the right (click to restore)."""

    previousClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = QColor("#FFFFFF")
        self._previous = QColor("#FFFFFF")
        self._hover_previous = False
        self.setFixedSize(84, 40)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, '左侧当前色，右侧上次颜色（点击恢复）', property='toolTip')

    def set_current(self, color: QColor) -> None:
        self._current = QColor(color)
        self.update()

    def set_previous(self, color: QColor) -> None:
        self._previous = QColor(color)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        hover = event.position().x() >= self.width() / 2
        if hover != self._hover_previous:
            self._hover_previous = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_previous = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().x() >= self.width() / 2:
            self.previousClicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, checker_brush(5))
        mid = rect.center().x()
        painter.fillRect(QRectF(rect.left(), rect.top(), mid - rect.left(), rect.height()), self._current)
        painter.fillRect(QRectF(mid, rect.top(), rect.right() - mid, rect.height()), self._previous)
        if self._hover_previous:
            painter.fillRect(QRectF(mid, rect.top(), rect.right() - mid, rect.height()), QColor(255, 255, 255, 46))
        painter.restore()
        painter.setPen(QPen(QColor(theme.border_strong), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


class SwatchButton(QAbstractButton):
    """Round color / gradient swatch that pops on hover; ``add`` draws a dashed +."""

    def __init__(self, color: str = "", parent=None, *, stops: tuple[str, ...] = (), add: bool = False, diameter: int = 28):
        super().__init__(parent)
        self.color = QColor(color) if color else QColor()
        self.stops = tuple(stops)
        self.add = add
        self.selected = False
        self.hover = 0.0
        self._diameter = diameter
        self.setFixedSize(diameter + 12, diameter + 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, selected: bool) -> None:
        if bool(selected) != self.selected:
            self.selected = bool(selected)
            self.update()

    def enterEvent(self, event) -> None:
        animate_value(self, "hover", 1.0, 260)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        animate_value(self, "hover", 0.0, 200)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = min(self.width(), self.height()) / max(1., self._diameter + 12)
        painter.translate(self.width()/2, self.height()/2)
        painter.scale(scale, scale)
        center = QPointF(0, 0 if self.selected else -1.5 * self.hover)
        radius = self._diameter / 2 * (1.0 + (0.03 if self.selected else 0.14) * self.hover)
        if self.add:
            painter.setPen(QPen(QColor(theme.accent if self.hover > 0.5 else theme.border_strong), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius - 1, radius - 1)
            painter.setPen(QPen(QColor(theme.accent_text if self.hover > 0.5 else theme.text_muted), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(center.x() - 5, center.y()), QPointF(center.x() + 5, center.y()))
            painter.drawLine(QPointF(center.x(), center.y() - 5), QPointF(center.x(), center.y() + 5))
            painter.end()
            return
        if self.selected:
            painter.setPen(QPen(QColor(theme.accent), 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius + 3.5, radius + 3.5)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.stops:
            gradient = QLinearGradient(center + QPointF(-radius, -radius), center + QPointF(radius, radius))
            for index, value in enumerate(self.stops):
                gradient.setColorAt(index / max(1, len(self.stops) - 1), QColor(value))
            painter.setBrush(QBrush(gradient))
        else:
            if self.color.alpha() < 255:
                painter.setBrush(checker_brush(4))
                painter.drawEllipse(center, radius, radius)
            painter.setBrush(self.color)
        painter.drawEllipse(center, radius, radius)
        painter.setPen(QPen(QColor(255, 255, 255, 46) if not theme.is_light else QColor(0, 0, 0, 40), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius - 0.5, radius - 0.5)
        painter.end()


class AngleDial(QWidget):
    """Small round gradient-direction dial. 0° points right, 90° points up."""

    angleChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self.setFixedSize(38, 38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, '拖动旋转渐变角度', property='toolTip')

    def angle(self) -> float:
        return self._angle

    def set_angle(self, angle: float) -> None:
        self._angle = float(angle)
        self.update()

    def _apply(self, position: QPointF) -> None:
        dx = position.x() - self.width() / 2
        dy = position.y() - self.height() / 2
        if abs(dx) + abs(dy) < 2:
            return
        angle = round(math.degrees(math.atan2(-dy, dx)) / 5) * 5
        self._angle = 180.0 if angle == -180 else float(angle)
        self.update()
        self.angleChanged.emit(self._angle)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def paintEvent(self, _event) -> None:
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(theme.border), 1.5))
        painter.setBrush(QColor(theme.input_surface))
        painter.drawEllipse(rect)
        center = rect.center()
        radians = math.radians(self._angle)
        tip = QPointF(center.x() + 12 * math.cos(radians), center.y() - 12 * math.sin(radians))
        painter.setPen(QPen(QColor(theme.accent), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(center, tip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.text_secondary))
        painter.drawEllipse(center, 4, 4)
        painter.end()


class PillField(QFrame):
    """Rounded field shell: muted prefix, borderless editor, muted suffix; focus rings the shell."""

    def __init__(self, editor: QWidget, prefix: str = "", suffix: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("fillPillField")
        self.setProperty("focused", False)
        self.editor = editor
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(5)
        def affix(text: str) -> None:
            if text:
                label = QLabel(text)
                label.setObjectName("fillFieldAffix")
                layout.addWidget(label)
        affix(prefix)
        layout.addWidget(editor, 1)
        affix(suffix)
        editor.setProperty("fieldWidth", "fill")
        editor.setFont(mono_font())
        editor.setMinimumWidth(0)
        if isinstance(editor, QAbstractSpinBox):
            editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            editor.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        editor.installEventFilter(self)
        self.setFixedHeight(34)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.editor and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            self.style().unpolish(self)
            self.style().polish(self)
        return super().eventFilter(obj, event)


def round_button(icon_name: str, tooltip: str, parent=None, *, size: int = 34) -> QToolButton:
    import qtawesome as qta

    button = QToolButton(parent)
    button.setObjectName("fillRoundButton")
    button.setFixedSize(size, size)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    theme = _theme()
    button.setIcon(qta.icon(icon_name, color=theme.text_secondary, color_disabled=theme.disabled))
    button.setIconSize(QSize(15, 15))
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    return button


class FillColorPicker(QWidget):
    """Right-hand column of the Fill editor: wheel, opacity, plate, eyedropper, numbers.

    Keeps the ``ColorPickerWidget`` surface the dialog relies on: ``color``,
    ``set_color``, ``set_previous``, ``colorChanged``, ``sv_square``,
    ``alpha_spin``, ``rgb_spins``, ``hex_edit``, ``plate``.
    """

    colorChanged = Signal(QColor)
    FORMATS = ("HEX", "RGB", "HSB", "HSL", "YUV")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fillColorPicker")
        self._color = QColor("#FFFFFF")
        self._previous = QColor("#FFFFFF")
        self._hue = 0.0
        self._updating = False
        self._dropper: _EyedropOverlay | None = None
        self._target_suffix = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.wheel = ColorWheel()
        self.sv_square = self.wheel.sv
        layout.addWidget(self.wheel, 0, Qt.AlignmentFlag.AlignHCenter)

        alpha_row = QHBoxLayout()
        alpha_row.setSpacing(8)
        alpha_label = QLabel("透明度")
        alpha_label.setObjectName("fillFieldLabel")
        self.alpha_slider = PillAlphaSlider()
        alpha_row.addWidget(alpha_label)
        alpha_row.addWidget(self.alpha_slider, 1)
        layout.addLayout(alpha_row)

        plate_row = QHBoxLayout()
        plate_row.setSpacing(10)
        self.plate = SplitPlate()
        self.plate.previousClicked.connect(self._restore_previous)
        plate_row.addWidget(self.plate)
        caption = QVBoxLayout()
        caption.setSpacing(1)
        self.hex_caption = QLabel("#FFFFFF")
        self.hex_caption.setObjectName("fillHexCaption")
        self.hex_caption.setFont(mono_font(14, QFont.Weight.Bold))
        hint = QLabel("右半边是之前的颜色，点它恢复")
        hint.setObjectName("fillHint")
        caption.addWidget(self.hex_caption)
        caption.addWidget(hint)
        plate_row.addLayout(caption, 1)
        self.eyedropper = round_button("fa5s.eye-dropper", "从屏幕取色")
        self.eyedropper.clicked.connect(self._start_eyedrop)
        plate_row.addWidget(self.eyedropper)
        layout.addLayout(plate_row)

        self.format_segment = PillSegment([(name, name.lower()) for name in self.FORMATS], height=32)
        self.format_segment.setFixedWidth(300)
        layout.addWidget(self.format_segment, 0, Qt.AlignmentFlag.AlignLeft)
        self.format_stack = QStackedWidget()
        self.format_stack.setFixedHeight(34)
        layout.addWidget(self.format_stack)

        self.hex_edit = QLineEdit()
        self.hex_edit.setPlaceholderText("#RRGGBB")
        self.hex_edit.setMaxLength(9)
        self.hex_edit.textChanged.connect(self._hex_edited)
        self.hex_edit.editingFinished.connect(self._hex_committed)
        self.alpha_spin = QSpinBox()
        self.alpha_spin.setObjectName("fillOpacityPercent")
        self.alpha_spin.setRange(0, 100)
        self.alpha_spin.valueChanged.connect(self._alpha_spin_changed)
        hex_page = QWidget()
        hex_layout = QHBoxLayout(hex_page)
        hex_layout.setContentsMargins(0, 0, 0, 0)
        hex_layout.setSpacing(8)
        hex_layout.addWidget(PillField(self.hex_edit), 1)
        alpha_field = PillField(self.alpha_spin, suffix="%")
        alpha_field.setFixedWidth(96)
        hex_layout.addWidget(alpha_field)
        self.format_stack.addWidget(hex_page)

        self.rgb_spins = self._spin_page("RGB", (255, 255, 255), "rgb")
        self.hsb_spins = self._spin_page("HSB", (359, 100, 100), "hsb")
        self.hsl_spins = self._spin_page("HSL", (359, 100, 100), "hsl")
        self.yuv_spins = self._spin_page("YUV", (255, 255, 255), "yuv")
        self.format_segment.currentIndexChanged.connect(self.format_stack.setCurrentIndex)
        self.format_segment.setCurrentIndex(0)

        self.wheel.hueChanged.connect(self._hue_changed)
        self.sv_square.changed.connect(self._sv_changed)
        self.alpha_slider.alphaChanged.connect(self._alpha_changed)
        self.set_color(QColor("#FFFFFF"))

    def _spin_page(self, letters: str, maxima: tuple[int, int, int], model: str) -> list[QSpinBox]:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        spins = []
        for letter, maximum in zip(letters, maxima):
            spin = QSpinBox()
            spin.setRange(0, maximum)
            spin.valueChanged.connect(lambda _value, key=model: self._spins_changed(key))
            row.addWidget(PillField(spin, prefix=letter), 1)
            spins.append(spin)
        self.format_stack.addWidget(page)
        return spins

    # --- public surface -------------------------------------------------
    def color(self) -> QColor:
        return QColor(self._color)

    def previous(self) -> QColor:
        return QColor(self._previous)

    def set_previous(self, color: QColor) -> None:
        self._previous = QColor(color)
        self.plate.set_previous(color)

    def set_target_suffix(self, suffix: str) -> None:
        self._target_suffix = str(suffix or "")
        self._sync_caption()

    def set_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self._publish(QColor(color))

    # --- internals ------------------------------------------------------
    def _publish(self, color: QColor, *, hue: float | None = None) -> None:
        self._color = QColor(color)
        if hue is not None:
            self._hue = float(hue) % 360.0
        else:
            derived = color.hsvHueF()
            if derived >= 0 and color.hsvSaturationF() > 0 and color.valueF() > 0:
                self._hue = derived * 360.0
        self._updating = True
        try:
            self.wheel.set_hue(self._hue)
            self.sv_square.set_hsv(self._hue, color.hsvSaturationF(), color.valueF())
            self.alpha_slider.set_color(color)
            self.alpha_slider.set_alpha(color.alpha())
            self.plate.set_current(color)
            self._sync_fields()
        finally:
            self._updating = False
        self._sync_caption()
        self.colorChanged.emit(QColor(self._color))

    def _sync_caption(self) -> None:
        self.hex_caption.setText(self._color.name(QColor.NameFormat.HexRgb).upper() + self._target_suffix)

    def _sync_fields(self) -> None:
        color = self._color
        hsv_sat = round(color.hsvSaturationF() * 100)
        hsl = color.toHsl()
        y, u, v = rgb_to_yuv(color.red(), color.green(), color.blue())
        values = (
            (self.rgb_spins, (color.red(), color.green(), color.blue())),
            (self.hsb_spins, (round(self._hue) % 360, hsv_sat, round(color.valueF() * 100))),
            (self.hsl_spins, (round(self._hue) % 360, round(hsl.hslSaturationF() * 100), round(hsl.lightnessF() * 100))),
            (self.yuv_spins, (y, u, v)),
            ((self.alpha_spin,), (alpha_to_percent(color.alpha()),)),
        )
        for spins, numbers in values:
            for spin, number in zip(spins, numbers):
                if spin.value() != int(number):
                    spin.blockSignals(True)
                    spin.setValue(int(number))
                    spin.blockSignals(False)
        formatted = color.name(QColor.NameFormat.HexRgb).upper()
        if self.hex_edit.text().strip().lstrip("#").lower() != formatted.lstrip("#").lower():
            self.hex_edit.blockSignals(True)
            self.hex_edit.setText(formatted)
            self.hex_edit.blockSignals(False)
        self.hex_edit.setProperty("invalid", False)

    def _hue_changed(self, hue: float) -> None:
        color = QColor.fromHsvF(hue / 360.0, self._color.hsvSaturationF(), self._color.valueF(), self._color.alphaF())
        self._publish(color, hue=hue)

    def _sv_changed(self, saturation: float, value: float) -> None:
        color = QColor.fromHsvF(self._hue / 360.0, saturation, value, self._color.alphaF())
        self._publish(color, hue=self._hue)

    def _alpha_changed(self, alpha: int) -> None:
        color = QColor(self._color)
        color.setAlpha(alpha)
        self._publish(color, hue=self._hue)

    def _alpha_spin_changed(self, value: int) -> None:
        if self._updating:
            return
        self._alpha_changed(percent_to_alpha(value))

    def _spins_changed(self, model: str) -> None:
        if self._updating:
            return
        alpha = self._color.alpha()
        hue = None
        if model == "rgb":
            color = QColor(*(spin.value() for spin in self.rgb_spins))
        elif model == "hsb":
            hue = self.hsb_spins[0].value()
            color = QColor.fromHsvF(hue / 360.0, self.hsb_spins[1].value() / 100, self.hsb_spins[2].value() / 100)
        elif model == "hsl":
            hue = self.hsl_spins[0].value()
            color = QColor.fromHslF(hue / 360.0, self.hsl_spins[1].value() / 100, self.hsl_spins[2].value() / 100)
        else:
            color = QColor(*yuv_to_rgb(*(spin.value() for spin in self.yuv_spins)))
        color.setAlpha(alpha)
        self._publish(color, hue=hue)

    def _hex_edited(self, text: str) -> None:
        """Live preview only for a complete #RRGGBB; partial input never rewrites the color."""
        if self._updating:
            return
        compact = str(text or "").strip().lstrip("#")
        if len(compact) == 6 and all(c in "0123456789abcdefABCDEF" for c in compact):
            color = QColor(f"#{compact}")
            color.setAlpha(self._color.alpha())
            self._publish(color)

    def _hex_committed(self) -> None:
        compact = self.hex_edit.text().strip().lstrip("#")
        color = QColor(f"#{compact}") if len(compact) in (6, 8) else QColor()
        if color.isValid():
            if len(compact) == 6:
                color.setAlpha(self._color.alpha())
            self._publish(color)
        else:
            self._sync_fields()

    def _restore_previous(self) -> None:
        self.set_color(self._previous)

    def _start_eyedrop(self) -> None:
        _start_screen_eyedrop(self)


@emphasized
def fill_editor_qss(theme: ThemeDefinition) -> str:
    """Dialog-local sheet appended after the secondary-surface sheet."""
    t = theme
    # Light themes: surface_elevated is white on a near-white card, so raised
    # controls use the input tone instead.
    raised = t.input_surface if t.is_light else t.surface_elevated
    mono = ", ".join(f'"{name}"' for name in MONO_FONT_FAMILIES)
    return f"""
QDialog#fillEditorDialog {{ background: transparent; }}
QFrame#fillCard {{ background: transparent; border: 0; }}
QFrame#fillCard QStackedWidget, QFrame#fillCard QStackedWidget > QWidget {{ background: transparent; border: 0; }}
QFrame#fillCard QLabel {{ color: {t.text}; background: transparent; }}
QLabel#fillTitle {{ font-size: 16px; font-weight: 800; }}
QFrame#fillCard QLabel#fillSubtitle, QFrame#fillCard QLabel#fillHint {{ color: {t.text_muted}; font-size: 12px; }}
QFrame#fillCard QLabel#fillFieldLabel, QFrame#fillCard QLabel#fillFieldAffix {{ color: {t.text_muted}; font-size: 12px; font-weight: 700; }}
QLabel#fillCardTitle {{ font-size: 13px; font-weight: 800; }}
QFrame#fillSubCard {{ background: {t.input_surface}; border: 0; border-radius: 18px; }}
QPushButton#fillSegButton {{
    background: transparent; color: {t.text_muted}; border: 0; border-radius: 15px;
    padding: 0 10px; min-height: 0; font-size: 13px; font-weight: 700;
}}
QPushButton#fillSegButton:hover {{ color: {t.text}; }}
QPushButton#fillSegButton:checked {{ color: {t.text_on_accent}; }}
QFrame#fillPillField {{ background: {t.input_surface}; border: 1px solid {t.border_strong}; border-radius: 17px; }}
QFrame#fillPillField[focused="true"] {{ border: 2px solid {t.accent}; }}
QFrame#fillSubCard QFrame#fillPillField {{ background: {t.surface}; }}
QFrame#fillPillField QLineEdit, QFrame#fillPillField QSpinBox, QFrame#fillPillField QDoubleSpinBox {{
    background: transparent; color: {t.text}; border: 0; padding: 0; margin: 0;
    min-height: 0; max-height: 30px; font-family: {mono}; font-size: 13px; font-weight: 600;
    selection-background-color: {t.accent}; selection-color: {t.text_on_accent};
}}
QToolButton#fillRoundButton, QPushButton#fillRoundButton {{
    background: {raised}; border: 0; border-radius: 17px; padding: 0;
    min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
}}
QToolButton#fillRoundButton:hover, QPushButton#fillRoundButton:hover {{ background: {t.selected}; }}
QToolButton#fillRoundButton:pressed, QPushButton#fillRoundButton:pressed {{ background: {t.accent_soft}; }}
QToolButton#fillRoundButton:disabled, QPushButton#fillRoundButton:disabled {{ background: {raised}; }}
QToolButton#fillRoundButton[ghost="true"] {{ background: transparent; }}
QToolButton#fillRoundButton[ghost="true"]:hover {{ background: {raised}; }}
QPushButton#fillChip {{
    background: {raised}; color: {t.text_secondary}; border: 0; border-radius: 14px;
    min-height: 28px; max-height: 28px; padding: 0 4px; font-size: 12px; font-weight: 700;
}}
QPushButton#fillChip:hover {{ background: {t.selected}; }}
QPushButton#fillChip:checked {{ background: {t.accent_soft}; color: {t.accent_text}; border: 2px solid {t.accent}; padding: 0 2px; }}
QPushButton#fillTab {{
    background: transparent; color: {t.text_muted}; border: 0; border-radius: 11px;
    min-height: 22px; max-height: 22px; padding: 0 10px; font-size: 12px; font-weight: 700;
}}
QPushButton#fillTab:hover {{ color: {t.text}; }}
QPushButton#fillTab:checked {{ background: {raised}; color: {t.text}; }}
QPushButton#fillPrimary {{
    background: {t.accent}; color: {t.text_on_accent}; border: 0; border-bottom: 4px solid {t.accent_pressed};
    border-radius: 20px; min-height: 36px; max-height: 36px; min-width: 64px; padding: 0 24px; font-size: 14px; font-weight: 700;
}}
QPushButton#fillPrimary:hover {{ background: {t.accent_hover}; }}
QPushButton#fillPrimary:pressed {{ background: {t.accent_pressed}; border-bottom: 1px solid {t.accent_pressed}; }}
QPushButton#fillGhost {{
    background: {raised}; color: {t.text_secondary}; border: 0; border-radius: 20px;
    min-height: 40px; max-height: 40px; min-width: 64px; padding: 0 22px; font-size: 14px; font-weight: 700;
}}
QPushButton#fillGhost:hover {{ background: {t.selected}; color: {t.text}; }}
QPushButton#fillTextButton {{
    background: transparent; color: {t.text_muted}; border: 0; border-radius: 16px;
    min-height: 32px; padding: 0 12px; font-size: 13px; font-weight: 700;
}}
QPushButton#fillTextButton:hover {{ background: {t.accent_soft}; color: {t.accent_text}; }}
"""
