"""Round gain faders and level meters for the volume windows (2026-11-14).

User (2026-11-14): the volume windows should be 「好用、顺手、圆润」. Draft C of
the track window (a row of vertical faders, one per track) and draft A of the
project window (a horizontal fader under 「自己微调」) share this fader:

* 0 dB near the middle (``gain_scale`` anchors), a fill that grows from 0 dB —
  cool colour for quieter, accent for louder, danger past +6 dB;
* drag anywhere (a click away from the cap jumps there), Shift fine, Ctrl
  coarse, near 0 dB it settles on 0; wheel, arrow keys, double-click → 0 dB;
  Esc during a drag puts the value back.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import gain_scale as scale

CAP_LONG, CAP_SHORT = 40, 22     # vertical cap: a rounded pill
THUMB = 24                       # horizontal thumb: a circle
RAIL = 10


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _alpha(color: str, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(alpha)
    return value


def fill_color(theme, db: float) -> QColor:
    return QColor(theme.focus if db < 0 else theme.danger if db > 6 else theme.accent)


class GainFader(QWidget):
    """A bipolar dB fader. ``valueChanged`` while moving, ``editFinished`` once a gesture ends."""

    valueChanged = Signal(float)
    editFinished = Signal()

    def __init__(self, parent=None, *, vertical: bool = True, ticks: bool = False):
        super().__init__(parent)
        self.vertical = bool(vertical)
        self.ticks = bool(ticks) and not self.vertical
        self._value = 0.
        self._drag = None
        self._hover = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SizeVerCursor if self.vertical else Qt.CursorShape.SizeHorCursor)
        if self.vertical:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # ---- value ----
    def value(self) -> float:
        return self._value

    def setValue(self, value: float, *, emit: bool = True) -> None:
        value = scale.snap(value, fine=True)
        if value == self._value:
            return
        self._value = value
        self.update()
        if emit:
            self.valueChanged.emit(value)

    # ---- geometry ----
    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(CAP_LONG + 2, 220) if self.vertical else QSize(320, 54 if self.ticks else 34)

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        return QSize(CAP_LONG + 2, 120) if self.vertical else QSize(160, 54 if self.ticks else 34)

    def _span(self) -> tuple[float, float]:
        """Pixel positions of −60 dB and +24 dB along the travel axis."""
        if self.vertical:
            return self.height() - CAP_SHORT / 2 - 1, CAP_SHORT / 2 + 1
        return THUMB / 2 + 2, self.width() - THUMB / 2 - 2

    def rail_span(self) -> tuple[float, float]:
        return self._span()

    def _axis(self) -> float:
        return self.width() / 2 if self.vertical else (17 if self.ticks else self.height() / 2)

    def pixel_of(self, db: float) -> float:
        low, high = self._span()
        return low + (high - low) * scale.position_of(db)

    def _position_at(self, point: QPointF) -> float:
        low, high = self._span()
        along = point.y() if self.vertical else point.x()
        return (along - low) / (high - low)

    # ---- painting ----
    def paintEvent(self, _event):  # noqa: N802 - Qt override
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        low, high = self._span()
        axis = self._axis()
        enabled = self.isEnabled()

        def rect_between(a: float, b: float, thickness: float) -> QRectF:
            a, b = min(a, b), max(a, b)
            if self.vertical:
                return QRectF(axis - thickness / 2, a, thickness, b - a)
            return QRectF(a, axis - thickness / 2, b - a, thickness)

        rail = rect_between(low, high, RAIL)
        painter.setPen(QPen(QColor(theme.border), 1.2))
        painter.setBrush(QColor(theme.input_surface))
        painter.drawRoundedRect(rail, RAIL / 2, RAIL / 2)
        zero, here = self.pixel_of(0.), self.pixel_of(self._value)
        if abs(here - zero) > .5:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill_color(theme, self._value) if enabled else QColor(theme.disabled))
            painter.drawRoundedRect(rect_between(zero, here, RAIL), RAIL / 2, RAIL / 2)
        painter.setPen(QPen(_alpha(theme.text_secondary, 150), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        if self.vertical:
            painter.drawLine(QPointF(axis - 13, zero), QPointF(axis + 13, zero))
        else:
            painter.drawLine(QPointF(zero, axis - 11), QPointF(zero, axis + 11))
        if self.ticks:
            font = QFont(self.font())
            font.setPixelSize(11)
            painter.setFont(font)
            for db in scale.ANCHORS:
                x = self.pixel_of(db)
                painter.setPen(QColor(theme.text if db == 0 else theme.text_muted))
                painter.drawText(QRectF(x - 20, axis + 14, 40, 16), Qt.AlignmentFlag.AlignCenter, scale.tick_label(db))
        accent = QColor(theme.accent if enabled else theme.disabled)
        lifted = 1.1 if self._drag is not None else 1.06 if self._hover else 1.
        painter.save()
        if self.vertical:
            painter.translate(axis, here)
        else:
            painter.translate(here, axis)
        painter.scale(lifted, lifted)
        cap = (QRectF(-CAP_LONG / 2, -CAP_SHORT / 2, CAP_LONG, CAP_SHORT) if self.vertical
               else QRectF(-THUMB / 2, -THUMB / 2, THUMB, THUMB))
        radius = CAP_SHORT / 2 if self.vertical else THUMB / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 34))
        painter.drawRoundedRect(cap.translated(0, 2.5), radius, radius)
        painter.setBrush(QColor(theme.surface_elevated))
        painter.setPen(QPen(accent, 2.6))
        painter.drawRoundedRect(cap, radius, radius)
        if self.vertical:
            painter.setPen(QPen(accent, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(QPointF(-CAP_LONG / 2 + 9, 0), QPointF(CAP_LONG / 2 - 9, 0))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent_soft))
            painter.drawEllipse(cap.adjusted(6, 6, -6, -6))
        if self.hasFocus():
            painter.setPen(QPen(_alpha(theme.focus, 150), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(cap.adjusted(-4, -4, 4, 4), radius + 4, radius + 4)
        painter.restore()
        painter.end()

    # ---- interaction ----
    def _multiplier(self, modifiers) -> float:
        return .25 if modifiers & Qt.KeyboardModifier.ShiftModifier else 3. if modifiers & Qt.KeyboardModifier.ControlModifier else 1.

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if event.button() != Qt.MouseButton.LeftButton or not self.isEnabled():
            return super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        point = event.position()
        along = point.y() if self.vertical else point.x()
        start = self._value
        if abs(along - self.pixel_of(self._value)) > (CAP_SHORT if self.vertical else THUMB) * .7:
            fine = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.setValue(scale.snap(scale.db_at(self._position_at(point)), fine=fine))
        self._drag = (along, scale.position_of(self._value), start)
        self.update()
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt override
        if self._drag is None:
            self._hover = self._near_cap(event.position())
            self.update()
            return super().mouseMoveEvent(event)
        origin, position, _start = self._drag
        low, high = self._span()
        along = event.position().y() if self.vertical else event.position().x()
        moved = position + (along - origin) / (high - low) * self._multiplier(event.modifiers())
        fine = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self.setValue(scale.snap(scale.db_at(moved), fine=fine))
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self._drag is not None:
            self._drag = None
            self.update()
            self.editFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._drag = None
            self.setValue(0.)
            self.editFinished.emit()
            event.accept()

    def wheelEvent(self, event):  # noqa: N802 - Qt override
        if not self.isEnabled():
            return super().wheelEvent(event)
        steps = event.angleDelta().y() / 120 or event.angleDelta().x() / 120
        if not steps:
            return
        mods = event.modifiers()
        step = .1 if mods & Qt.KeyboardModifier.ShiftModifier else 3. if mods & Qt.KeyboardModifier.ControlModifier else .5
        self.setValue(scale.snap(self._value + steps * step, fine=True))
        self.editFinished.emit()
        event.accept()

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        key = event.key()
        if key == Qt.Key.Key_Escape and self._drag is not None:
            start = self._drag[2]
            self._drag = None
            self.setValue(start)
            event.accept()
            return
        fine = .1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else .5
        delta = {Qt.Key.Key_Up: fine, Qt.Key.Key_Right: fine, Qt.Key.Key_Down: -fine, Qt.Key.Key_Left: -fine,
                 Qt.Key.Key_PageUp: 6., Qt.Key.Key_PageDown: -6.}.get(key)
        if delta is not None:
            self.setValue(scale.snap(self._value + delta, fine=True))
            self.editFinished.emit()
            event.accept()
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_0):
            self.setValue(0.)
            self.editFinished.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):  # noqa: N802 - Qt override
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):  # noqa: N802 - Qt override
        self.update()
        super().focusOutEvent(event)

    def _near_cap(self, point: QPointF) -> bool:
        along = point.y() if self.vertical else point.x()
        return abs(along - self.pixel_of(self._value)) < (CAP_SHORT if self.vertical else THUMB)


class GainScaleLabels(QWidget):
    """The dB numbers beside a row of vertical faders, aligned to their travel."""

    def __init__(self, fader: GainFader, parent=None):
        super().__init__(parent)
        self._fader = fader
        self.setFixedWidth(34)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        theme = _theme()
        painter = QPainter(self)
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        offset = self._fader.mapTo(self.window(), QPointF(0, 0)).y() - self.mapTo(self.window(), QPointF(0, 0)).y()
        for db in scale.ANCHORS:
            y = offset + self._fader.pixel_of(db)
            painter.setPen(QColor(theme.text if db == 0 else theme.text_muted))
            weight = QFont(font)
            weight.setBold(db == 0)
            painter.setFont(weight)
            painter.drawText(QRectF(0, y - 8, self.width() - 4, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, scale.tick_label(db))
        painter.end()


class LevelMeter(QWidget):
    """A thin vertical meter: −48…0 dBFS, green → amber → red, with a falling peak mark."""

    FLOOR = -48.

    def __init__(self, parent=None):
        super().__init__(parent)
        self._level = 0.
        self._peak = 0.
        self.setFixedWidth(10)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setToolTip('')

    def set_level(self, dbfs: float | None) -> None:
        level = 0. if dbfs is None else max(0., min(1., (float(dbfs) - self.FLOOR) / -self.FLOOR))
        # Fast attack, slow release; the peak mark falls slowly too.
        self._level = level if level > self._level else max(level, self._level - .045)
        self._peak = self._level if self._level > self._peak else max(self._level, self._peak - .008)
        self.update()

    def level(self) -> float:
        return self._level

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top, bottom = CAP_SHORT / 2 + 1, self.height() - CAP_SHORT / 2 - 1
        rail = QRectF(1, top, self.width() - 2, bottom - top)
        path = QPainterPath()
        path.addRoundedRect(rail, rail.width() / 2, rail.width() / 2)
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.setBrush(QColor(theme.input_surface))
        painter.drawPath(path)
        if self._level > 0:
            painter.setClipPath(path)
            height = rail.height()
            for start, end, color in ((0., .62, theme.success), (.62, .875, theme.warning), (.875, 1., theme.danger)):
                if self._level <= start:
                    break
                upto = min(self._level, end)
                painter.fillRect(QRectF(rail.left(), bottom - height * upto, rail.width(), height * (upto - start)),
                                 QColor(color))
            painter.setClipping(False)
        if self._peak > .02:
            y = bottom - rail.height() * self._peak
            painter.setPen(QPen(QColor(theme.text_secondary), 2))
            painter.drawLine(QPointF(rail.left() + 1, y), QPointF(rail.right() - 1, y))
        painter.end()
