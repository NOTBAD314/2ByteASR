"""Pieces of the 视频 tool panel in the user's design C (2026-10-23).

:class:`VideoPositionPad` is a small picture of the canvas: dragging its dot
moves the selected clip through the existing 位置 X / Y boxes (preview while
dragging, one undo step on release). :class:`SliderValueRow` puts a value's
name and box on one line and a slider under it (design B), driving the same
spin box the rest of Studio reads.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QSizePolicy, QVBoxLayout, QWidget

from ..design.soft_qss import preview_stage, soft_tokens
from ..design.soft_widgets import UnitField
from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition
from ..i18n import bind_text


class VideoPositionPad(QWidget):
    """Drag the dot to move the clip; the framed stage is the canvas.

    The caption card (2026-10-24) drives its own X / Y boxes with it;
    ``on_press`` opens one undo step that ``on_commit`` closes.
    """

    def __init__(self, x_spin, y_spin, on_commit, *, aspect=None, on_press=None,
                 tooltip='拖动圆点改变片段位置', name='片段位置', parent=None):
        super().__init__(parent)
        self.x_spin, self.y_spin, self.on_commit = x_spin, y_spin, on_commit
        self.on_press = on_press
        self.aspect = aspect or (lambda: 16 / 9)
        self._dragging = False
        self.setObjectName("videoPositionPad")
        self.setFixedHeight(100)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self, tooltip, property='toolTip')
        bind_text(self, name, property='accessibleName')
        for spin in (x_spin, y_spin):
            spin.valueChanged.connect(self.update)
        x_spin.installEventFilter(self)
        self.setEnabled(x_spin.isEnabled())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.setEnabled(watched.isEnabled())
            self.update()
        return False

    def refresh_theme_palette(self):
        self.update()

    def _frame(self) -> QRectF:
        height = self.height() - 28
        width = min(self.width() - 40, height * max(0.3, float(self.aspect() or 16 / 9)))
        height = width / max(0.3, float(self.aspect() or 16 / 9))
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def _has_value(self) -> bool:
        return self.isEnabled() and not self.x_spin.specialValueText()

    def _point(self) -> QPointF:
        frame = self._frame()
        x = frame.left() + self.x_spin.value() / 100 * frame.width()
        y = frame.top() + self.y_spin.value() / 100 * frame.height()
        return QPointF(min(max(x, 9), self.width() - 9), min(max(y, 9), self.height() - 9))

    def paintEvent(self, _event):
        theme = theme_definition(theme_key())
        tokens = soft_tokens(theme)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens.card_fill))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)
        frame = self._frame()
        gradient = QLinearGradient(frame.topLeft(), frame.bottomLeft())
        top, bottom = preview_stage(theme)
        gradient.setColorAt(0, QColor(top))
        gradient.setColorAt(1, QColor(bottom))
        painter.setBrush(gradient)
        painter.drawRoundedRect(frame, 6, 6)
        guide = QColor(theme.text)
        guide.setAlphaF(0.14)
        painter.setPen(QPen(guide, 1))
        painter.drawLine(QPointF(frame.center().x(), 0), QPointF(frame.center().x(), self.height()))
        painter.drawLine(QPointF(0, frame.center().y()), QPointF(self.width(), frame.center().y()))
        if self._has_value():
            painter.setPen(QPen(QColor("#ffffff"), 3))
            painter.setBrush(QColor(theme.accent))
            painter.drawEllipse(self._point(), 7, 7)
        painter.end()

    def _move_to(self, position) -> None:
        frame = self._frame()
        x = (position.x() - frame.left()) / max(1.0, frame.width()) * 100
        y = (position.y() - frame.top()) / max(1.0, frame.height()) * 100
        for spin, value in ((self.x_spin, x), (self.y_spin, y)):
            spin.setValue(round(min(spin.maximum(), max(spin.minimum(), value)), 2))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._has_value():
            self._dragging = True
            if self.on_press is not None:
                self.on_press()
            self._move_to(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._move_to(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.on_commit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _WheelSafeSlider(QSlider):
    """The panel scrolls under the wheel; the slider only takes it once focused."""

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class SliderValueRow(QWidget):
    """「名称 …… 数值」 over a slider (design B), both bound to one spin box.

    The slider follows the spin box (whole units); moving it previews through
    the spin box's own signals and ``on_commit`` runs when it is let go.
    """

    def __init__(self, title: str, spin, on_commit, parent=None):
        super().__init__(parent)
        self.spin, self.on_commit = spin, on_commit
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("softLabel")
        bind_text(self.title, title)
        head.addWidget(self.title, 1)
        self.field = UnitField(spin)
        self.field.setFixedWidth(96)
        head.addWidget(self.field)
        column.addLayout(head)
        self.slider = _WheelSafeSlider(Qt.Orientation.Horizontal)
        self.slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.slider.setRange(int(spin.minimum()), int(spin.maximum()))
        self.slider.setAccessibleName(title)
        column.addWidget(self.slider)
        self.slider.setValue(int(round(spin.value())))
        spin.valueChanged.connect(self._from_spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.slider.sliderReleased.connect(self.on_commit)
        spin.installEventFilter(self)
        self.slider.setEnabled(spin.isEnabled())

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.slider.setEnabled(watched.isEnabled())
        return False

    def sync(self):
        """Follow a value the panel set with the spin box's signals blocked."""
        self._from_spin(self.spin.value())

    def _from_spin(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(value)))
        self.slider.blockSignals(False)

    def _from_slider(self, value):
        if int(round(self.spin.value())) != value:
            self.spin.setValue(float(value))
        if not self.slider.isSliderDown():
            self.on_commit()  # a click on the groove or a key press
