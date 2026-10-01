"""Custom color picker widgets (SV square, hue/alpha sliders, hex/RGB input).

Used by the subtitle Fill editor so color selection works identically under
every theme instead of relying on the native QColorDialog surface.

Layout follows a professional picker: large 2D plane, vertical channel bar,
current/previous plates, HSB/RGB/HSL/YUV radios, HEX and eyedropper.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import bind_text


def _theme_color(widget: QWidget, role: QPalette.ColorRole, fallback: str) -> QColor:
    color = widget.palette().color(role)
    if not color.isValid():
        return QColor(fallback)
    return color


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def rgb_to_yuv(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Rec.601 full-range YUV in 0..255."""
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = 128.0 - 0.168736 * r - 0.331264 * g + 0.5 * b
    v = 128.0 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return (
        int(round(_clamp(y, 0, 255))),
        int(round(_clamp(u, 0, 255))),
        int(round(_clamp(v, 0, 255))),
    )


def yuv_to_rgb(y: int, u: int, v: int) -> tuple[int, int, int]:
    u = u - 128.0
    v = v - 128.0
    r = y + 1.402 * v
    g = y - 0.344136 * u - 0.714136 * v
    b = y + 1.772 * u
    return (
        int(round(_clamp(r, 0, 255))),
        int(round(_clamp(g, 0, 255))),
        int(round(_clamp(b, 0, 255))),
    )


def _safe_hue(color: QColor) -> int:
    hue = color.hue()
    return 0 if hue < 0 else hue


def _safe_hsl_hue(color: QColor) -> int:
    hue = color.hslHue()
    return 0 if hue < 0 else hue


def alpha_to_percent(alpha: int) -> int:
    """Map QColor's 0..255 alpha to the displayed 0..100 percent value."""

    return round(max(0, min(255, int(alpha))) * 100 / 255)


def percent_to_alpha(percent: int) -> int:
    """Map the displayed opacity percentage back to QColor's 0..255 alpha."""

    return round(max(0, min(100, int(percent))) * 255 / 100)


class SaturationValueSquare(QWidget):
    """Two-dimensional color plane. Default mapping is S×V with a fixed hue.

    Other channel radios switch the axes (Photoshop/GIMP behaviour).
    """

    valueChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "hsv_h"
        self._color = QColor(255, 255, 255)
        self._hue = 0
        self._saturation = 0.0
        self._value = 1.0
        self._cache: QImage | None = None
        self._cache_key: tuple | None = None
        self.setMinimumSize(300, 300)
        self.setMaximumSize(480, 480)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(300, min(480, int(width)))

    def sizeHint(self) -> QSize:
        return QSize(360, 360)

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        self._cache = None
        self.update()

    def set_hue(self, hue: int) -> None:
        self._hue = max(0, min(359, int(hue)))
        if self._mode == "hsv_h":
            self._color = QColor.fromHsv(
                self._hue,
                round(self._saturation * 255),
                round(self._value * 255),
            )
        self._cache = None
        self.update()

    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor) -> None:
        hsv = color.toHsv()
        if hsv.hue() >= 0:
            self._hue = hsv.hue()
        self._saturation = hsv.saturation() / 255.0
        self._value = hsv.value() / 255.0
        self._color = QColor(color.red(), color.green(), color.blue())
        self._cache = None
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_position(event.position())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_position(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:
        self._cache = None
        super().resizeEvent(event)

    def _apply_position(self, position: QPointF) -> None:
        width = max(1.0, float(self.width()))
        height = max(1.0, float(self.height()))
        xr = _clamp(position.x() / width, 0.0, 1.0)
        yr = _clamp(position.y() / height, 0.0, 1.0)
        self._color = self._xy_to_color(xr, yr)
        hsv = self._color.toHsv()
        if hsv.hue() >= 0:
            self._hue = hsv.hue()
        self._saturation = hsv.saturation() / 255.0
        self._value = hsv.value() / 255.0
        self.update()
        self.valueChanged.emit()

    def _xy_to_color(self, xr: float, yr: float) -> QColor:
        mode = self._mode
        base = self._color
        if mode == "hsv_h":
            return QColor.fromHsv(self._hue, round(xr * 255), round((1.0 - yr) * 255))
        if mode == "hsv_s":
            hsv = base.toHsv()
            return QColor.fromHsv(round(xr * 359), hsv.saturation(), round((1.0 - yr) * 255))
        if mode == "hsv_v":
            hsv = base.toHsv()
            return QColor.fromHsv(round(xr * 359), round((1.0 - yr) * 255), hsv.value())
        if mode == "rgb_r":
            return QColor(base.red(), round(xr * 255), round((1.0 - yr) * 255))
        if mode == "rgb_g":
            return QColor(round(xr * 255), base.green(), round((1.0 - yr) * 255))
        if mode == "rgb_b":
            return QColor(round(xr * 255), round((1.0 - yr) * 255), base.blue())
        if mode == "hsl_h":
            return QColor.fromHsl(_safe_hsl_hue(base), round(xr * 255), round((1.0 - yr) * 255))
        if mode == "hsl_s":
            hsl = base.toHsl()
            return QColor.fromHsl(round(xr * 359), hsl.hslSaturation(), round((1.0 - yr) * 255))
        if mode == "hsl_l":
            hsl = base.toHsl()
            return QColor.fromHsl(round(xr * 359), round((1.0 - yr) * 255), hsl.lightness())
        y, u, v = rgb_to_yuv(base.red(), base.green(), base.blue())
        if mode == "yuv_y":
            return QColor(*yuv_to_rgb(y, round(xr * 255), round((1.0 - yr) * 255)))
        if mode == "yuv_u":
            return QColor(*yuv_to_rgb(round(xr * 255), u, round((1.0 - yr) * 255)))
        return QColor(*yuv_to_rgb(round(xr * 255), round((1.0 - yr) * 255), v))

    def _color_to_xy(self) -> tuple[float, float]:
        color = self._color
        mode = self._mode
        if mode == "hsv_h":
            hsv = color.toHsv()
            return hsv.saturation() / 255.0, 1.0 - hsv.value() / 255.0
        if mode == "hsv_s":
            hsv = color.toHsv()
            return _safe_hue(hsv) / 359.0, 1.0 - hsv.value() / 255.0
        if mode == "hsv_v":
            hsv = color.toHsv()
            return _safe_hue(hsv) / 359.0, 1.0 - hsv.saturation() / 255.0
        if mode == "rgb_r":
            return color.green() / 255.0, 1.0 - color.blue() / 255.0
        if mode == "rgb_g":
            return color.red() / 255.0, 1.0 - color.blue() / 255.0
        if mode == "rgb_b":
            return color.red() / 255.0, 1.0 - color.green() / 255.0
        if mode == "hsl_h":
            hsl = color.toHsl()
            return hsl.hslSaturation() / 255.0, 1.0 - hsl.lightness() / 255.0
        if mode == "hsl_s":
            hsl = color.toHsl()
            return _safe_hsl_hue(hsl) / 359.0, 1.0 - hsl.lightness() / 255.0
        if mode == "hsl_l":
            hsl = color.toHsl()
            return _safe_hsl_hue(hsl) / 359.0, 1.0 - hsl.hslSaturation() / 255.0
        y, u, v = rgb_to_yuv(color.red(), color.green(), color.blue())
        if mode == "yuv_y":
            return u / 255.0, 1.0 - v / 255.0
        if mode == "yuv_u":
            return y / 255.0, 1.0 - v / 255.0
        return y / 255.0, 1.0 - u / 255.0

    def _key(self) -> tuple:
        c = self._color
        return (self._mode, self._hue, c.red(), c.green(), c.blue(), self.width(), self.height())

    def _render(self) -> QImage:
        width = max(1, self.width())
        height = max(1, self.height())
        image = QImage(width, height, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        mode = self._mode
        if mode == "hsv_h":
            hue_gradient = QLinearGradient(0, 0, width, 0)
            hue_gradient.setColorAt(0.0, QColor.fromHsv(self._hue, 0, 255))
            hue_gradient.setColorAt(1.0, QColor.fromHsv(self._hue, 255, 255))
            painter.fillRect(0, 0, width, height, QBrush(hue_gradient))
            shade = QLinearGradient(0, 0, 0, height)
            shade.setColorAt(0.0, QColor(0, 0, 0, 0))
            shade.setColorAt(1.0, QColor(0, 0, 0, 255))
            painter.fillRect(0, 0, width, height, QBrush(shade))
        else:
            self._render_scanlines(painter, width, height)
        painter.end()
        return image

    def _render_scanlines(self, painter: QPainter, width: int, height: int) -> None:
        mode = self._mode
        base = self._color
        steps = (
            (0.0, QColor.fromHsv(0, 255, 255)),
            (1 / 6, QColor.fromHsv(60, 255, 255)),
            (2 / 6, QColor.fromHsv(120, 255, 255)),
            (3 / 6, QColor.fromHsv(180, 255, 255)),
            (4 / 6, QColor.fromHsv(240, 255, 255)),
            (5 / 6, QColor.fromHsv(300, 255, 255)),
            (1.0, QColor.fromHsv(359, 255, 255)),
        )
        for y in range(height):
            t = 0.0 if height == 1 else y / (height - 1)
            top = 1.0 - t
            gradient = QLinearGradient(0, y, width, y)
            if mode == "hsv_s":
                sat = base.toHsv().saturation()
                val = round(top * 255)
                for pos, _color in steps:
                    hue = round(pos * 359)
                    gradient.setColorAt(pos, QColor.fromHsv(hue, sat, val))
            elif mode == "hsv_v":
                val = base.toHsv().value()
                sat = round(top * 255)
                for pos, _color in steps:
                    hue = round(pos * 359)
                    gradient.setColorAt(pos, QColor.fromHsv(hue, sat, val))
            elif mode == "rgb_r":
                blue = round(top * 255)
                gradient.setColorAt(0.0, QColor(base.red(), 0, blue))
                gradient.setColorAt(1.0, QColor(base.red(), 255, blue))
            elif mode == "rgb_g":
                blue = round(top * 255)
                gradient.setColorAt(0.0, QColor(0, base.green(), blue))
                gradient.setColorAt(1.0, QColor(255, base.green(), blue))
            elif mode == "rgb_b":
                green = round(top * 255)
                gradient.setColorAt(0.0, QColor(0, green, base.blue()))
                gradient.setColorAt(1.0, QColor(255, green, base.blue()))
            elif mode == "hsl_h":
                hue = _safe_hsl_hue(base)
                light = round(top * 255)
                gradient.setColorAt(0.0, QColor.fromHsl(hue, 0, light))
                gradient.setColorAt(1.0, QColor.fromHsl(hue, 255, light))
            elif mode == "hsl_s":
                sat = base.toHsl().hslSaturation()
                light = round(top * 255)
                for pos, _color in steps:
                    gradient.setColorAt(pos, QColor.fromHsl(round(pos * 359), sat, light))
            elif mode == "hsl_l":
                light = base.toHsl().lightness()
                sat = round(top * 255)
                for pos, _color in steps:
                    gradient.setColorAt(pos, QColor.fromHsl(round(pos * 359), sat, light))
            else:
                yv, uv, vv = rgb_to_yuv(base.red(), base.green(), base.blue())
                if mode == "yuv_y":
                    vch = round(top * 255)
                    gradient.setColorAt(0.0, QColor(*yuv_to_rgb(yv, 0, vch)))
                    gradient.setColorAt(1.0, QColor(*yuv_to_rgb(yv, 255, vch)))
                elif mode == "yuv_u":
                    vch = round(top * 255)
                    gradient.setColorAt(0.0, QColor(*yuv_to_rgb(0, uv, vch)))
                    gradient.setColorAt(1.0, QColor(*yuv_to_rgb(255, uv, vch)))
                else:
                    uch = round(top * 255)
                    gradient.setColorAt(0.0, QColor(*yuv_to_rgb(0, uch, vv)))
                    gradient.setColorAt(1.0, QColor(*yuv_to_rgb(255, uch, vv)))
            painter.fillRect(0, y, width, 1, QBrush(gradient))

    def paintEvent(self, _event) -> None:
        key = self._key()
        if self._cache is None or self._cache_key != key:
            self._cache = self._render()
            self._cache_key = key
        painter = QPainter(self)
        painter.drawImage(0, 0, self._cache)
        xr, yr = self._color_to_xy()
        cursor = QPointF(xr * self.width(), yr * self.height())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(cursor, 7, 7)
        painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
        painter.drawEllipse(cursor, 8.5, 8.5)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()


class HueSlider(QWidget):
    """Channel bar. Default is a 0-359 hue strip; can show any 1D spectrum.

    Vertical by default to sit beside the SV plane. Horizontal remains
    available for older call sites.
    """

    hueChanged = Signal(int)
    channelChanged = Signal(int)

    def __init__(self, parent=None, *, vertical: bool = True):
        super().__init__(parent)
        self._hue = 0
        self._value = 0
        self._maximum = 359
        self._vertical = vertical
        self._colors: list[QColor] | None = None
        self._invert = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if vertical:
            self.setMinimumWidth(26)
            self.setMaximumWidth(30)
            self.setMinimumHeight(160)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setMinimumHeight(22)
            self.setMaximumHeight(26)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def hue(self) -> int:
        return self._hue

    def set_hue(self, hue: int, notify: bool = False) -> None:
        self._maximum = 359
        self._colors = None
        self._invert = False
        self._hue = max(0, min(359, int(hue)))
        self._value = self._hue
        self.update()
        if notify:
            self.hueChanged.emit(self._hue)
            self.channelChanged.emit(self._value)

    def set_channel(self, value: int, *, maximum: int = 255, colors: list[QColor] | None = None, invert: bool = True, notify: bool = False) -> None:
        self._maximum = max(1, int(maximum))
        self._colors = list(colors) if colors else None
        self._invert = invert
        self._value = max(0, min(self._maximum, int(value)))
        if self._maximum == 359:
            self._hue = self._value
        self.update()
        if notify:
            if self._maximum == 359:
                self.hueChanged.emit(self._hue)
            self.channelChanged.emit(self._value)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply(event.position())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def _track_rect(self) -> QRectF:
        if self._vertical:
            return QRectF(self.rect()).adjusted(1.5, 8.0, -11.5, -8.0)
        return QRectF(self.rect()).adjusted(8.0, 4.5, -8.0, -4.5)

    def _apply(self, position: QPointF) -> None:
        rect = self._track_rect()
        if self._vertical:
            ratio = _clamp((position.y() - rect.top()) / max(1.0, rect.height()), 0.0, 1.0)
        else:
            ratio = _clamp((position.x() - rect.left()) / max(1.0, rect.width()), 0.0, 1.0)
        if self._invert:
            ratio = 1.0 - ratio
        value = round(ratio * self._maximum)
        if self._maximum == 359 and self._colors is None:
            self.set_hue(value, notify=True)
        else:
            self.set_channel(value, maximum=self._maximum, colors=self._colors, invert=self._invert, notify=True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self._track_rect()
        if self._vertical:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        if self._colors is None:
            for step in range(0, 361, 15):
                pos = step / 360.0
                if self._invert:
                    pos = 1.0 - pos
                gradient.setColorAt(_clamp(pos, 0.0, 1.0), QColor.fromHsv(min(359, step), 255, 255))
        else:
            last = max(1, len(self._colors) - 1)
            for index, color in enumerate(self._colors):
                pos = index / last
                if self._invert:
                    pos = 1.0 - pos
                gradient.setColorAt(_clamp(pos, 0.0, 1.0), color)
        painter.fillRect(rect, QBrush(gradient))
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ratio = self._value / max(1, self._maximum)
        if self._invert:
            ratio = 1.0 - ratio
        if self._vertical:
            center = QPointF(rect.center().x(), rect.top() + ratio * rect.height())
            path = QPainterPath()
            path.moveTo(rect.right() + 1, center.y())
            path.lineTo(rect.right() + 8, center.y() - 5)
            path.lineTo(rect.right() + 8, center.y() + 5)
            path.closeSubpath()
        else:
            center = QPointF(rect.left() + ratio * rect.width(), rect.center().y())
            path = QPainterPath()
            path.moveTo(center.x(), center.y() - 2)
            path.lineTo(center.x() - 6, center.y() - 10)
            path.lineTo(center.x() + 6, center.y() - 10)
            path.closeSubpath()
        painter.setPen(QPen(QColor(0, 0, 0, 150), 1))
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 220), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, 5.5, 5.5)
        painter.end()


class AlphaSlider(QWidget):
    """Checkerboard strip from opaque (left) to transparent (right).

    Numeric alpha is standard: 255 = opaque, 0 = transparent. The paint
    gradient is opaque→transparent left to right, so the handle and mouse
    mapping must invert (left click = 255, right click = 0).
    """

    alphaChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._alpha = 255
        self._color = QColor("#FFFFFF")
        self.setMinimumHeight(22)
        self.setMaximumHeight(26)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def alpha(self) -> int:
        return self._alpha

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color.rgb())
        self.update()

    def set_alpha(self, alpha: int, notify: bool = False) -> None:
        self._alpha = max(0, min(255, int(alpha)))
        self.update()
        if notify:
            self.alphaChanged.emit(self._alpha)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply(event.position())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def _apply(self, position: QPointF) -> None:
        ratio = max(0.0, min(1.0, position.x() / max(1.0, self.width())))
        self.set_alpha(round((1.0 - ratio) * 255), notify=True)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 4.5, -0.5, -4.5)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        cell = 7
        painter.setPen(Qt.PenStyle.NoPen)
        for y in range(int(rect.top()), int(rect.bottom()), cell):
            for x in range(int(rect.left()), int(rect.right()), cell):
                light = ((x // cell) + (y // cell)) % 2 == 0
                painter.setBrush(QColor(235, 235, 235) if light else QColor(205, 205, 205))
                painter.drawRect(x, y, cell, cell)
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        gradient.setColorAt(0.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 255))
        gradient.setColorAt(1.0, QColor(self._color.red(), self._color.green(), self._color.blue(), 0))
        painter.fillRect(rect, QBrush(gradient))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QPointF(rect.left() + (1.0 - self._alpha / 255.0) * rect.width(), rect.center().y())
        painter.setPen(QPen(QColor(255, 255, 255, 220), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, 7, 7)
        painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
        painter.drawEllipse(center, 8.5, 8.5)
        painter.end()


class CurrentPreviousPlate(QWidget):
    """Split current / previous color plate. Click the previous half to restore."""

    previousClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = QColor("#FFFFFF")
        self._previous = QColor("#FFFFFF")
        self.setMinimumHeight(34)
        self.setMaximumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, '左侧当前色，右侧上次颜色（点击恢复）', property='toolTip')

    def set_current(self, color: QColor) -> None:
        self._current = QColor(color)
        self.update()

    def set_previous(self, color: QColor) -> None:
        self._previous = QColor(color)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().x() >= self.width() / 2:
            self.previousClicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.setClipPath(path)
        cell = 7
        painter.setPen(Qt.PenStyle.NoPen)
        for y in range(int(rect.top()), int(rect.bottom()) + cell, cell):
            for x in range(int(rect.left()), int(rect.right()) + cell, cell):
                light = ((x // cell) + (y // cell)) % 2 == 0
                painter.setBrush(QColor(235, 235, 235) if light else QColor(205, 205, 205))
                painter.drawRect(x, y, cell, cell)
        mid = rect.center().x()
        painter.fillRect(QRectF(rect.left(), rect.top(), mid - rect.left(), rect.height()), self._current)
        painter.fillRect(QRectF(mid, rect.top(), rect.right() - mid, rect.height()), self._previous)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QPen(QColor(0, 0, 0, 50), 1))
        painter.drawLine(QPointF(mid, rect.top() + 1), QPointF(mid, rect.bottom() - 1))
        painter.end()


class _EyedropOverlay(QWidget):
    """Fullscreen click-to-sample overlay. Hidden just before grabWindow."""

    picked = Signal(QColor)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        virtual = QRectF()
        for screen in QGuiApplication.screens():
            virtual = virtual.united(QRectF(screen.geometry())) if virtual.isValid() else QRectF(screen.geometry())
        self.setGeometry(virtual.toRect())

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            self.cancelled.emit()
            self.close()
            return
        pos = event.globalPosition().toPoint()
        self.hide()
        QApplication.processEvents()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        local = pos - screen.geometry().topLeft()
        image = screen.grabWindow(0, int(local.x()), int(local.y()), 1, 1).toImage()
        self.picked.emit(image.pixelColor(0, 0))
        self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        super().keyPressEvent(event)


class ColorPickerWidget(QWidget):
    """Professional picker: plane + vertical channel + HSB/RGB/HSL/YUV + HEX."""

    colorChanged = Signal(QColor)

    def __init__(self, parent=None, *, show_alpha: bool = True, embed_fields: bool = True):
        super().__init__(parent)
        self._updating = False
        self._previous = QColor("#FFFFFF")
        self._color = QColor("#FFFFFF")
        self._mode = "hsv_h"
        self._dropper: _EyedropOverlay | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._preview_slot = QVBoxLayout()
        self._preview_slot.setContentsMargins(0, 0, 0, 0)
        self._preview_slot.setSpacing(0)
        layout.addLayout(self._preview_slot)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        self.sv_square = SaturationValueSquare()
        body.addWidget(self.sv_square, 1)

        self.hue_slider = HueSlider(vertical=True)
        body.addWidget(self.hue_slider, 0)
        self._body_layout = body

        self._fields_host = QWidget()
        self._fields_host.setObjectName("fillNumericFields")
        self._fields_host.setFixedWidth(168)
        self._fields_host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        fields = QVBoxLayout(self._fields_host)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setSpacing(6)

        self.plate = CurrentPreviousPlate()
        self.plate.setFixedSize(72, 30)
        self.plate.previousClicked.connect(self._restore_previous)
        plate_caption = QHBoxLayout()
        plate_caption.setContentsMargins(0, 0, 0, 0)
        plate_caption.setSpacing(6)
        plate_caption.addWidget(self.plate)
        current_caption = QLabel("当前")
        current_caption.setObjectName("fillFieldLabel")
        previous_caption = QLabel("之前")
        previous_caption.setObjectName("fillFieldLabel")
        plate_caption.addWidget(current_caption)
        plate_caption.addWidget(previous_caption)
        plate_caption.addStretch(1)
        fields.addLayout(plate_caption)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        self._channel_group = QButtonGroup(self)
        self._channel_group.setExclusive(True)
        self._channel_radios: dict[str, QRadioButton] = {}
        self._hsv_spins: list[QSpinBox] = []
        self.rgb_spins: list[QSpinBox] = []
        self._hsl_spins: list[QSpinBox] = []
        self._yuv_spins: list[QSpinBox] = []

        left = (("hsv_h", "H", 0, 359), ("hsv_s", "S", 0, 100), ("hsv_v", "B", 0, 100),
                ("hsl_h", "H", 0, 359), ("hsl_s", "S", 0, 100), ("hsl_l", "L", 0, 100))
        right = (("rgb_r", "R", 0, 255), ("rgb_g", "G", 0, 255), ("rgb_b", "B", 0, 255),
                 ("yuv_y", "Y", 0, 255), ("yuv_u", "U", 0, 255), ("yuv_v", "V", 0, 255))
        buckets = {
            "hsv_h": self._hsv_spins, "hsv_s": self._hsv_spins, "hsv_v": self._hsv_spins,
            "rgb_r": self.rgb_spins, "rgb_g": self.rgb_spins, "rgb_b": self.rgb_spins,
            "hsl_h": self._hsl_spins, "hsl_s": self._hsl_spins, "hsl_l": self._hsl_spins,
            "yuv_y": self._yuv_spins, "yuv_u": self._yuv_spins, "yuv_v": self._yuv_spins,
        }
        for column, spec in ((0, left), (2, right)):
            for row, (mode, label, lo, hi) in enumerate(spec):
                radio = QRadioButton(label)
                radio.setObjectName("fillChannelRadio")
                radio.setCursor(Qt.CursorShape.PointingHandCursor)
                radio.setFixedWidth(24)
                self._channel_group.addButton(radio)
                self._channel_radios[mode] = radio
                spin = QSpinBox()
                spin.setRange(lo, hi)
                spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                spin.setFixedWidth(42)
                spin.setMinimumHeight(22)
                spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                buckets[mode].append(spin)
                radio.toggled.connect(lambda checked, key=mode: checked and self._set_mode(key))
                spin.valueChanged.connect(lambda _value, key=mode: self._spin_changed(key))
                grid.addWidget(radio, row, column)
                grid.addWidget(spin, row, column + 1)
        self._channel_radios["hsv_h"].setChecked(True)

        hex_row = QHBoxLayout()
        hex_row.setSpacing(6)
        hex_label = QLabel("HEX")
        hex_label.setObjectName("fillFieldLabel")
        self.hex_edit = QLineEdit()
        self.hex_edit.setPlaceholderText("#RRGGBB")
        self.hex_edit.setMinimumHeight(28)
        self.hex_edit.editingFinished.connect(self._hex_committed)
        # 编辑/提交分离：键入期间只做即时预览（仅当已是完整合法 HEX），
        # 绝不因中间态（#、#F、#FF7…）改写颜色或回写文本（2026-09-20）。
        self.hex_edit.textChanged.connect(self._hex_edited)
        hex_row.addWidget(hex_label)
        hex_row.addWidget(self.hex_edit, 1)
        self.eyedropper = QToolButton()
        self.eyedropper.setObjectName("fillEyedropper")
        self.eyedropper.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.eyedropper, '从屏幕取色', property='toolTip')
        self.eyedropper.setFixedSize(28, 28)
        try:
            import qtawesome as qta
            self.eyedropper.setIcon(qta.icon("fa5s.eye-dropper", color="#3d433d"))
        except Exception:
            bind_text(self.eyedropper, '拾')
        self.eyedropper.clicked.connect(self._start_eyedrop)
        hex_row.addWidget(self.eyedropper)
        fields.addLayout(hex_row)

        self.alpha_slider = AlphaSlider()
        self.alpha_slider.setVisible(False)
        self.alpha_spin = QSpinBox()
        self.alpha_spin.setObjectName("fillOpacityPercent")
        self.alpha_spin.setRange(0, 100)
        self.alpha_spin.setSuffix("%")
        self.alpha_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.alpha_spin.setMinimumHeight(24)
        self.alpha_spin.setFixedWidth(54)
        self.alpha_spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._opacity_row = QWidget()
        opacity_layout = QHBoxLayout(self._opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(6)
        opacity_label = QLabel("透明度")
        opacity_label.setObjectName("fillFieldLabel")
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setObjectName("fillControlSlider")
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        opacity_layout.addWidget(opacity_label)
        opacity_layout.addWidget(self._opacity_slider, 1)
        opacity_layout.addWidget(self.alpha_spin)
        self._opacity_row.setVisible(show_alpha)
        if not show_alpha:
            self.alpha_spin.hide()
        fields.addWidget(self._opacity_row)
        self._advanced_toggle = QToolButton()
        self._advanced_toggle.setObjectName("styleSectionHeader")
        bind_text(self._advanced_toggle, '高级')
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setChecked(False)
        self._advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._advanced_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._channel_grid_host = QWidget()
        advanced_layout = QVBoxLayout(self._channel_grid_host)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.addLayout(grid)
        self._channel_grid_host.hide()
        self._advanced_toggle.toggled.connect(self._channel_grid_host.setVisible)
        self._advanced_toggle.toggled.connect(
            lambda visible: self._advanced_toggle.setArrowType(
                Qt.ArrowType.DownArrow if visible else Qt.ArrowType.RightArrow
            )
        )
        fields.addWidget(self._advanced_toggle)
        fields.addWidget(self._channel_grid_host)
        fields.addStretch(1)

        if embed_fields:
            body.addWidget(self._fields_host, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(body, 1)

        self.sv_square.valueChanged.connect(self._sv_changed)
        self.hue_slider.hueChanged.connect(self._hue_changed)
        self.hue_slider.channelChanged.connect(self._bar_changed)
        self.alpha_slider.alphaChanged.connect(self._alpha_slider_changed)
        self.alpha_spin.valueChanged.connect(self._alpha_spin_changed)
        self._opacity_slider.valueChanged.connect(self._alpha_spin_changed)
        self.set_color(QColor("#FFFFFF"))

    def fields_host(self) -> QWidget:
        return self._fields_host

    def detach_fields(self) -> QWidget:
        """Take the numeric fields out of this layout for external placement."""
        if self._fields_host.parentWidget() is self:
            self._body_layout.removeWidget(self._fields_host)
            self._fields_host.setParent(None)
        return self._fields_host

    def attach_preview(self, widget: QWidget) -> None:
        """Place a composite preview above the SV/hue/fields row."""
        while self._preview_slot.count():
            item = self._preview_slot.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        self._preview_slot.addWidget(widget)

    def color(self) -> QColor:
        return QColor(self._color)

    def set_previous(self, color: QColor) -> None:
        self._previous = QColor(color)
        self.plate.set_previous(color)

    def set_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self._updating = True
        self._color = QColor(color)
        self.sv_square.set_color(color)
        self._sync_bar()
        self.alpha_slider.set_color(color)
        self.alpha_slider.set_alpha(color.alpha())
        self._sync_fields()
        self.plate.set_current(self._color)
        self._updating = False
        self.colorChanged.emit(QColor(self._color))

    def _set_mode(self, mode: str) -> None:
        if self._mode == mode:
            return
        self._mode = mode
        self.sv_square.set_mode(mode)
        self._sync_bar()
        self.update()

    def _sync_bar(self) -> None:
        color = self._color
        mode = self._mode
        if mode == "hsv_h":
            self.hue_slider.set_hue(_safe_hue(color.toHsv()))
            return
        hsv = color.toHsv()
        hsl = color.toHsl()
        y, u, v = rgb_to_yuv(color.red(), color.green(), color.blue())
        if mode == "hsv_s":
            self.hue_slider.set_channel(
                hsv.saturation(),
                maximum=255,
                colors=[QColor.fromHsv(_safe_hue(hsv), 0, hsv.value()), QColor.fromHsv(_safe_hue(hsv), 255, hsv.value())],
            )
        elif mode == "hsv_v":
            self.hue_slider.set_channel(
                hsv.value(),
                maximum=255,
                colors=[QColor(0, 0, 0), QColor.fromHsv(_safe_hue(hsv), hsv.saturation(), 255)],
            )
        elif mode == "rgb_r":
            self.hue_slider.set_channel(color.red(), colors=[QColor(0, color.green(), color.blue()), QColor(255, color.green(), color.blue())])
        elif mode == "rgb_g":
            self.hue_slider.set_channel(color.green(), colors=[QColor(color.red(), 0, color.blue()), QColor(color.red(), 255, color.blue())])
        elif mode == "rgb_b":
            self.hue_slider.set_channel(color.blue(), colors=[QColor(color.red(), color.green(), 0), QColor(color.red(), color.green(), 255)])
        elif mode == "hsl_h":
            self.hue_slider.set_hue(_safe_hsl_hue(hsl))
        elif mode == "hsl_s":
            self.hue_slider.set_channel(
                hsl.hslSaturation(),
                maximum=255,
                colors=[QColor.fromHsl(_safe_hsl_hue(hsl), 0, hsl.lightness()), QColor.fromHsl(_safe_hsl_hue(hsl), 255, hsl.lightness())],
            )
        elif mode == "hsl_l":
            self.hue_slider.set_channel(
                hsl.lightness(),
                maximum=255,
                colors=[QColor(0, 0, 0), QColor.fromHsl(_safe_hsl_hue(hsl), hsl.hslSaturation(), 128), QColor(255, 255, 255)],
            )
        elif mode == "yuv_y":
            self.hue_slider.set_channel(y, colors=[QColor(*yuv_to_rgb(0, u, v)), QColor(*yuv_to_rgb(255, u, v))])
        elif mode == "yuv_u":
            self.hue_slider.set_channel(u, colors=[QColor(*yuv_to_rgb(y, 0, v)), QColor(*yuv_to_rgb(y, 255, v))])
        else:
            self.hue_slider.set_channel(v, colors=[QColor(*yuv_to_rgb(y, u, 0)), QColor(*yuv_to_rgb(y, u, 255))])

    def _sync_fields(self) -> None:
        color = self._color
        hsv = color.toHsv()
        hsl = color.toHsl()
        y, u, v = rgb_to_yuv(color.red(), color.green(), color.blue())
        values = {
            self._hsv_spins[0]: _safe_hue(hsv),
            self._hsv_spins[1]: round(hsv.saturation() * 100 / 255),
            self._hsv_spins[2]: round(hsv.value() * 100 / 255),
            self.rgb_spins[0]: color.red(),
            self.rgb_spins[1]: color.green(),
            self.rgb_spins[2]: color.blue(),
            self._hsl_spins[0]: _safe_hsl_hue(hsl),
            self._hsl_spins[1]: round(hsl.hslSaturation() * 100 / 255),
            self._hsl_spins[2]: round(hsl.lightness() * 100 / 255),
            self._yuv_spins[0]: y,
            self._yuv_spins[1]: u,
            self._yuv_spins[2]: v,
        }
        for spin, value in values.items():
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        formatted = color.name(QColor.NameFormat.HexRgb).upper()
        # 用户正在编辑等价文本（大小写/有无 # 之差）时不重写：避免 setText
        # 造成光标跳动与 textChanged 递归（十一：防信号递归）。
        if self._hex_editing_compatible(self.hex_edit.text(), formatted):
            self._clear_hex_validation()
        else:
            self.hex_edit.blockSignals(True)
            self.hex_edit.setText(formatted)
            self.hex_edit.blockSignals(False)
            self._clear_hex_validation()
        self.alpha_spin.blockSignals(True)
        percent = alpha_to_percent(color.alpha())
        self.alpha_spin.setValue(percent)
        self.alpha_spin.blockSignals(False)
        self._opacity_slider.blockSignals(True)
        self._opacity_slider.setValue(percent)
        self._opacity_slider.blockSignals(False)

    def _publish(self, color: QColor, *, from_plane: bool = False, from_bar: bool = False) -> None:
        if self._updating:
            return
        self._color = QColor(color)
        if not from_plane:
            self.sv_square.set_color(color)
        if not from_bar:
            self._sync_bar()
        self.alpha_slider.set_color(color)
        self.alpha_slider.set_alpha(color.alpha())
        self._sync_fields()
        self.plate.set_current(self._color)
        self.colorChanged.emit(QColor(color))

    def _sv_changed(self) -> None:
        color = self.sv_square.color()
        color.setAlpha(self._color.alpha())
        self._publish(color, from_plane=True)

    def _hue_changed(self, hue: int) -> None:
        if self._mode not in {"hsv_h", "hsl_h"}:
            return
        if self._mode == "hsv_h":
            self.sv_square.set_hue(hue)
            color = self.sv_square.color()
        else:
            hsl = self._color.toHsl()
            color = QColor.fromHsl(hue, hsl.hslSaturation(), hsl.lightness())
            self.sv_square.set_color(color)
        color.setAlpha(self._color.alpha())
        self._publish(color, from_plane=True, from_bar=True)

    def _bar_changed(self, value: int) -> None:
        if self._updating or self._mode in {"hsv_h", "hsl_h"}:
            return
        color = QColor(self._color)
        mode = self._mode
        hsv = color.toHsv()
        hsl = color.toHsl()
        y, u, v = rgb_to_yuv(color.red(), color.green(), color.blue())
        if mode == "hsv_s":
            color = QColor.fromHsv(_safe_hue(hsv), value, hsv.value())
        elif mode == "hsv_v":
            color = QColor.fromHsv(_safe_hue(hsv), hsv.saturation(), value)
        elif mode == "rgb_r":
            color.setRed(value)
        elif mode == "rgb_g":
            color.setGreen(value)
        elif mode == "rgb_b":
            color.setBlue(value)
        elif mode == "hsl_s":
            color = QColor.fromHsl(_safe_hsl_hue(hsl), value, hsl.lightness())
        elif mode == "hsl_l":
            color = QColor.fromHsl(_safe_hsl_hue(hsl), hsl.hslSaturation(), value)
        elif mode == "yuv_y":
            color = QColor(*yuv_to_rgb(value, u, v))
        elif mode == "yuv_u":
            color = QColor(*yuv_to_rgb(y, value, v))
        elif mode == "yuv_v":
            color = QColor(*yuv_to_rgb(y, u, value))
        color.setAlpha(self._color.alpha())
        self._publish(color, from_bar=True)

    def _spin_changed(self, mode: str) -> None:
        if self._updating:
            return
        alpha = self._color.alpha()
        if mode.startswith("hsv"):
            color = QColor.fromHsv(
                self._hsv_spins[0].value(),
                round(self._hsv_spins[1].value() * 255 / 100),
                round(self._hsv_spins[2].value() * 255 / 100),
            )
        elif mode.startswith("rgb"):
            color = QColor(self.rgb_spins[0].value(), self.rgb_spins[1].value(), self.rgb_spins[2].value())
        elif mode.startswith("hsl"):
            color = QColor.fromHsl(
                self._hsl_spins[0].value(),
                round(self._hsl_spins[1].value() * 255 / 100),
                round(self._hsl_spins[2].value() * 255 / 100),
            )
        else:
            color = QColor(*yuv_to_rgb(self._yuv_spins[0].value(), self._yuv_spins[1].value(), self._yuv_spins[2].value()))
        color.setAlpha(alpha)
        self._publish(color)

    def _alpha_slider_changed(self, alpha: int) -> None:
        color = QColor(self._color)
        color.setAlpha(alpha)
        self._publish(color)

    def _alpha_spin_changed(self, value: int) -> None:
        color = QColor(self._color)
        color.setAlpha(percent_to_alpha(value))
        self._publish(color)

    @staticmethod
    def _hex_editing_compatible(current: str, formatted: str) -> bool:
        """用户正在输入的文本是否与程序化 HEX 等价（大小写/# 前缀之差）。"""
        return current.strip().lstrip("#").lower() == formatted.lstrip("#").lower()

    def _show_hex_validation(self) -> None:
        self.hex_edit.setStyleSheet("QLineEdit { border: 1px solid #d9534f; }")
        bind_text(self.hex_edit, '请输入 6 位 HEX 颜色，例如 #FF7100', property='toolTip')

    def _clear_hex_validation(self) -> None:
        self.hex_edit.setStyleSheet("")
        self.hex_edit.setToolTip("")

    def _hex_edited(self, text: str) -> None:
        """键入即时预览：只在完整合法的 #RRGGBB/RRGGBB 时更新颜色。"""
        if self._updating:
            return
        compact = str(text or "").strip().lstrip("#")
        if len(compact) != 6 or any(
            character not in "0123456789abcdefABCDEF" for character in compact
        ):
            self._clear_hex_validation()
            return
        color = QColor(f"#{compact}")
        if not color.isValid():
            self._clear_hex_validation()
            return
        color.setAlpha(self._color.alpha())
        self._clear_hex_validation()
        self._publish(color)

    def _hex_committed(self) -> None:
        text = self.hex_edit.text().strip()
        color = QColor(text)
        if not color.isValid():
            compact = text.lstrip("#")
            if len(compact) == 6:
                color = QColor(f"#{compact}")
            elif len(compact) == 8:
                color = QColor(f"#{compact}")
        if color.isValid():
            if len(text.lstrip("#")) == 6:
                color.setAlpha(self._color.alpha())
            self._clear_hex_validation()
            self.set_color(color)
        else:
            # 非法提交：恢复上一个合法颜色（黑色是真实颜色，绝不能当解析
            # 失败的替身），并给出轻量红框提示；下一次输入自动清除。
            self._sync_fields()
            self._show_hex_validation()

    def _restore_previous(self) -> None:
        self.set_color(self._previous)

    def _start_eyedrop(self) -> None:
        window = self.window()
        was_visible = window.isVisible() if window is not None else False
        if window is not None:
            window.hide()
        QApplication.processEvents()
        overlay = _EyedropOverlay()
        self._dropper = overlay

        def finish(color: QColor | None, *, visible=was_visible) -> None:
            if window is not None and visible:
                window.show()
                window.raise_()
                window.activateWindow()
            if color is not None and color.isValid():
                color.setAlpha(self._color.alpha())
                self.set_color(color)
            self._dropper = None

        overlay.picked.connect(lambda color: finish(color))
        overlay.cancelled.connect(lambda: finish(None))
        overlay.show()
        overlay.grabMouse()
        overlay.setFocus(Qt.FocusReason.PopupFocusReason)


class _SwatchPreview(QWidget):
    """Current/previous color plate with a checkerboard for alpha."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors: list[QColor] = [QColor("#FFFFFF")]
        self._alpha = 1.0
        self.setMinimumHeight(34)

    def set_colors(self, colors: list[QColor], alpha: float | None = None) -> None:
        self._colors = list(colors) or [QColor("#FFFFFF")]
        if alpha is not None:
            self._alpha = max(0.0, min(1.0, alpha))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        cell = 7
        for y in range(int(rect.top()), int(rect.bottom()) + cell, cell):
            for x in range(int(rect.left()), int(rect.right()) + cell, cell):
                light = ((x // cell) + (y // cell)) % 2 == 0
                painter.setBrush(QColor(235, 235, 235) if light else QColor(205, 205, 205))
                painter.drawRect(x, y, cell, cell)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.setClipPath(path)
        if len(self._colors) == 1:
            painter.fillRect(rect, self._colors[0])
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            for index, color in enumerate(self._colors):
                gradient.setColorAt(index / max(1, len(self._colors) - 1), color)
            painter.fillRect(rect, QBrush(gradient))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 6, 6)
        painter.end()


class SimpleColorDialog(QDialog):
    """Themed single-color picker used by stroke/shadow/glow/background edits.

    Replaces the old QColorDialog ("基本颜色/屏幕取色") so every color entry in
    the style inspector shares one modern picker surface.
    """

    def __init__(self, initial: QColor, parent=None, *, title: str = "选择颜色", common_colors: tuple[str, ...] = ()):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("toolDialog")
        self.setMinimumSize(520, 520)
        self.resize(540, 560)
        from .studio_theme import apply_secondary_surface_theme

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)
        self.picker = ColorPickerWidget(show_alpha=True)
        layout.addWidget(self.picker, 1)
        if common_colors:
            common = QHBoxLayout()
            common.setSpacing(6)
            common.addWidget(QLabel("常用"))
            for value in common_colors:
                swatch = QPushButton()
                swatch.setFixedSize(30, 24)
                swatch.setStyleSheet(f"background:{value};border:1px solid #837f75;border-radius:4px")
                swatch.clicked.connect(lambda _checked=False, color=value: self.picker.set_color(QColor(color)))
                common.addWidget(swatch)
            common.addStretch(1)
            layout.addLayout(common)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        color = QColor(initial) if initial is not None and initial.isValid() else QColor("#FFFFFF")
        self.picker.set_color(color)
        self.picker.set_previous(color)
        apply_secondary_surface_theme(self)

    def selected_color(self) -> QColor:
        return QColor(self.picker.color())

    # QColorDialog-compatible alias so existing call sites keep working.
    def selectedColor(self) -> QColor:
        return self.selected_color()
