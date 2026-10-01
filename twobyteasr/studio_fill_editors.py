"""Fill/gradient editors and the studio font picker dialog."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .font_system import resolve_font_weight, system_font_inventory
from .studio_theme import StudioComboBox, apply_secondary_surface_theme
from .studio_widgets import ScrubDoubleSpinBox, ScrubSpinBox

from .i18n import bind_text

class GradientStop:
    """Simple value holder for a gradient stop (used by GradientEditor)."""
    def __init__(self, color: str = "#FFFFFF", pos: float = 0.0):
        self.color = color
        self.pos = max(0.0, min(1.0, float(pos)))


class GradientEditor(QWidget):
    """Compact gradient editor with real-time preview.

    - Click on bar to add stop
    - Drag stops to reorder
    - Double click stop to pick color
    - Angle spin
    - Presets
    Emits gradientChanged(dict) with keys: type, stops(list[{color,pos}]), angle

    ``compact=True`` shows only the stop-rail (Photoshop-style triangles on a
    gradient strip). Host dialogs place opacity / location / angle elsewhere.
    """

    gradientChanged = Signal(dict)
    colorRequested = Signal(int)
    selectionChanged = Signal(int)

    def __init__(self, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self._compact = compact
        self._stops: list[GradientStop] = [
            GradientStop("#FFE45E", 0.0),
            GradientStop("#20D9FF", 1.0),
        ]
        self._angle = 0.0
        self._selected: GradientStop | None = self._stops[0]
        self._dragging_stop = False
        self.setMinimumHeight(48 if compact else 92)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.angle_spin = ScrubDoubleSpinBox()
        self.angle_spin.setRange(-360, 360)
        self.angle_spin.setDecimals(0)
        self.angle_spin.setValue(self._angle)
        self.angle_spin.valueChanged.connect(self._on_angle)

        self.position_spin = ScrubDoubleSpinBox()
        self.position_spin.setRange(0.0, 1.0)
        self.position_spin.setDecimals(3)
        self.position_spin.setSingleStep(0.01)
        self.position_spin.valueChanged.connect(self._on_stop_position)

        self.stop_color_button = QPushButton("#FFE45E")
        self.stop_color_button.setObjectName("gradientStopColor")
        self.stop_color_button.clicked.connect(self._request_selected_color)

        self.opacity_spin = ScrubSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.valueChanged.connect(self._on_stop_opacity)

        self.add_stop_button = QPushButton("+ 添加颜色")
        self.add_stop_button.clicked.connect(self._add_stop)
        self.delete_stop_button = QPushButton("删除")
        bind_text(self.delete_stop_button, '删除选中的渐变色标（Delete / Backspace 也可），至少保留 2 个', property='toolTip')
        self.delete_stop_button.clicked.connect(self._delete_selected)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        if not compact:
            top = QHBoxLayout()
            top.setContentsMargins(0, 0, 0, 0)
            top.addWidget(QLabel("角度"))
            top.addWidget(self.angle_spin)
            top.addStretch(1)
            for label, angle in (("水平", 0), ("↗", 45), ("垂直", 90), ("↖", -45)):
                button = QPushButton(label)
                button.setFixedWidth(36)
                button.clicked.connect(lambda _c=False, a=angle: self._set_angle(a))
                top.addWidget(button)
            v.addLayout(top)

        self.bar = QWidget()
        self.bar.setFixedHeight(40 if compact else 28)
        self.bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.bar.paintEvent = self._paint_bar
        self.bar.mousePressEvent = self._bar_click
        self.bar.mouseMoveEvent = self._bar_drag
        self.bar.mouseReleaseEvent = self._bar_release
        self.bar.mouseDoubleClickEvent = self._bar_double
        v.addWidget(self.bar)

        if not compact:
            stop_row = QHBoxLayout()
            stop_row.setContentsMargins(0, 0, 0, 0)
            stop_row.setSpacing(4)
            stop_row.addWidget(QLabel("位置"))
            stop_row.addWidget(self.position_spin)
            stop_row.addWidget(QLabel("颜色"))
            stop_row.addWidget(self.stop_color_button)
            stop_row.addWidget(QLabel("透明度"))
            stop_row.addWidget(self.opacity_spin)
            stop_row.addStretch(1)
            v.addLayout(stop_row)
            row = QHBoxLayout()
            rev = QPushButton("反转")
            rev.clicked.connect(self._reverse)
            row.addWidget(self.add_stop_button)
            row.addWidget(self.delete_stop_button)
            row.addWidget(rev)
            row.addStretch(1)
            v.addLayout(row)
        self._sync_stop_controls()

    def value(self) -> dict:
        return {
            "type": "linear-gradient",
            "stops": [{"color": QColor(s.color).name(QColor.NameFormat.HexArgb), "position": round(s.pos, 4)} for s in sorted(self._stops, key=lambda x: x.pos)],
            "angle": float(self._angle),
        }

    def set_value(self, g: dict | None):
        if not g or not isinstance(g, dict):
            return
        stops = g.get("stops") or []
        if len(stops) >= 2:
            self._stops = []
            for s in stops:
                col = str(s.get("color", "#FFFFFF"))
                pos = float(s.get("pos", s.get("position", 0)))
                self._stops.append(GradientStop(col, pos))
            self._stops.sort(key=lambda x: x.pos)
            self._selected = self._stops[0]
        self._angle = float(g.get("angle", 0))
        self.angle_spin.blockSignals(True)
        self.angle_spin.setValue(self._angle)
        self.angle_spin.blockSignals(False)
        self._sync_stop_controls()
        self.update()

    def _emit(self):
        self.gradientChanged.emit(self.value())

    def _strip_rect(self) -> QRect:
        if self._compact:
            return self.bar.rect().adjusted(10, 16, -10, -6)
        return self.bar.rect().adjusted(2, 2, -2, -2)

    def _paint_bar(self, ev):
        p = QPainter(self.bar)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._strip_rect()
        # Checkerboard so translucent stops stay readable.
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(r), 3, 3)
        p.setClipPath(clip)
        cell = 6
        p.setPen(Qt.PenStyle.NoPen)
        for y in range(r.top(), r.bottom() + cell, cell):
            for x in range(r.left(), r.right() + cell, cell):
                light = ((x // cell) + (y // cell)) % 2 == 0
                p.setBrush(QColor(235, 235, 235) if light else QColor(205, 205, 205))
                p.drawRect(x, y, cell, cell)
        grad = QLinearGradient(r.left(), r.top(), r.right(), r.top())
        for s in sorted(self._stops, key=lambda x: x.pos):
            grad.setColorAt(max(0.0, min(1.0, s.pos)), QColor(s.color))
        p.fillRect(r, grad)
        p.setClipping(False)
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(r), 3, 3)
        for s in sorted(self._stops, key=lambda x: x.pos):
            x = r.left() + int(s.pos * r.width())
            col = QColor(s.color)
            selected = s is self._selected
            if self._compact:
                path = QPainterPath()
                top = r.top() - 13
                path.moveTo(x, r.top() + 1)
                path.lineTo(x + 6, top + 8)
                path.lineTo(x + 6, top)
                path.lineTo(x - 6, top)
                path.lineTo(x - 6, top + 8)
                path.closeSubpath()
                p.setBrush(col)
                p.setPen(QPen(QColor("#111111") if selected else QColor("#3a3a3a"), 1.4 if selected else 1))
                p.drawPath(path)
                if selected:
                    p.setPen(QPen(QColor("#4a8a5e"), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(path)
            else:
                p.setBrush(col)
                p.setPen(QPen(QColor("#111"), 1))
                p.drawEllipse(QPoint(x, r.center().y()), 7, 7)
                if selected:
                    p.setPen(QPen(QColor("#4a8a5e"), 2))
                    p.drawEllipse(QPoint(x, r.center().y()), 9, 9)
        p.end()

    # Keeps the bar scannable: more stops than this become unreadable.
    MAX_STOPS = 8

    def _bar_click(self, ev):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        r = self._strip_rect()
        pos = max(0.0, min(1.0, (ev.position().x() - r.left()) / max(1, r.width())))
        self._dragging_stop = False
        hit_threshold = max(0.01, 10.0 / max(1, r.width()))
        for i, s in enumerate(self._stops):
            if abs(s.pos - pos) <= hit_threshold:
                self._selected = s
                self._dragging_stop = True
                self._sync_stop_controls()
                self.update()
                self.selectionChanged.emit(i)
                return

    def _bar_drag(self, ev):
        if not (ev.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self._dragging_stop or self._selected is None or self._selected not in self._stops:
            return
        r = self._strip_rect()
        pos = max(0.0, min(1.0, (ev.position().x() - r.left()) / max(1, r.width())))
        selected = self._selected
        selected.pos = pos
        self._sync_stop_controls()
        self._stops.sort(key=lambda x: x.pos)
        self._selected = selected
        self.update()
        self._emit()

    def _bar_release(self, _ev):
        self._dragging_stop = False

    def _bar_double(self, ev):
        if len(self._stops) >= self.MAX_STOPS:
            return
        r = self._strip_rect()
        pos = max(0.0, min(1.0, (ev.position().x() - r.left()) / max(1, r.width())))
        color = self._interpolated_color(pos)
        stop = GradientStop(color.name(QColor.NameFormat.HexArgb), pos)
        self._stops.append(stop)
        self._stops.sort(key=lambda item: item.pos)
        self._selected = stop
        self._sync_stop_controls()
        self.update()
        self.selectionChanged.emit(self._stops.index(stop))
        self._emit()

    def _interpolated_color(self, position: float) -> QColor:
        ordered = sorted(self._stops, key=lambda item: item.pos)
        if not ordered:
            return QColor("#FFFFFF")
        if position <= ordered[0].pos:
            return QColor(ordered[0].color)
        if position >= ordered[-1].pos:
            return QColor(ordered[-1].color)
        for left, right in zip(ordered, ordered[1:]):
            if left.pos <= position <= right.pos:
                ratio = (position - left.pos) / max(1e-6, right.pos - left.pos)
                a, b = QColor(left.color), QColor(right.color)
                return QColor(
                    round(a.red() + (b.red() - a.red()) * ratio),
                    round(a.green() + (b.green() - a.green()) * ratio),
                    round(a.blue() + (b.blue() - a.blue()) * ratio),
                    round(a.alpha() + (b.alpha() - a.alpha()) * ratio),
                )
        return QColor(ordered[-1].color)

    def _add_stop(self):
        if len(self._stops) >= self.MAX_STOPS:
            return
        # Add into the largest gap so the simple two-stop editor grows
        # naturally into three/four stops without exposing a pro editor.
        ordered = sorted(self._stops, key=lambda item: item.pos)
        left, right = max(zip(ordered, ordered[1:]), key=lambda pair: pair[1].pos-pair[0].pos)
        position = (left.pos + right.pos) / 2
        self._stops.append(GradientStop("#FFFFFF", position))
        self._stops.sort(key=lambda x: x.pos)
        self._selected = next(x for x in self._stops if x.pos == position)
        self._sync_stop_controls()
        self.update()
        self.selectionChanged.emit(self._stops.index(self._selected))
        self._emit()

    def _reverse(self):
        for s in self._stops:
            s.pos = 1.0 - s.pos
        self._stops.sort(key=lambda x: x.pos)
        self._selected = self._selected if self._selected in self._stops else self._stops[0]
        self._sync_stop_controls()
        self.update()
        self._emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace} and len(self._stops) > 2 and self._selected in self._stops:
            self._delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    def _delete_selected(self) -> None:
        """Remove the selected stop; a gradient always keeps at least two."""
        if self._selected not in self._stops or len(self._stops) <= 2:
            return
        removed = self._selected
        self._stops.remove(removed)
        ordered = sorted(self._stops, key=lambda item: item.pos)
        self._selected = min(
            ordered,
            key=lambda item: abs(item.pos - removed.pos),
        )
        self._sync_stop_controls()
        self.update()
        self._emit()

    def _on_angle(self, v):
        self._angle = float(v)
        self._emit()

    def _sync_stop_controls(self) -> None:
        selected = self._selected if self._selected in self._stops else None
        if selected is None or not hasattr(self, "position_spin"):
            return
        self.position_spin.blockSignals(True)
        self.opacity_spin.blockSignals(True)
        self.position_spin.setValue(float(selected.pos))
        color = QColor(selected.color)
        self.opacity_spin.setValue(round(color.alpha() * 100 / 255))
        self.stop_color_button.setText(color.name(QColor.NameFormat.HexArgb).upper())
        if hasattr(self, "add_stop_button"):
            self.add_stop_button.setEnabled(len(self._stops) < self.MAX_STOPS)
        if hasattr(self, "delete_stop_button"):
            self.delete_stop_button.setEnabled(len(self._stops) > 2)
        self.position_spin.blockSignals(False)
        self.opacity_spin.blockSignals(False)

    def _on_stop_position(self, value: float) -> None:
        if self._selected not in self._stops:
            return
        self._selected.pos = max(0.0, min(1.0, float(value)))
        self._stops.sort(key=lambda x: x.pos)
        self.update()
        self._emit()

    def _on_stop_opacity(self, value: int) -> None:
        if self._selected not in self._stops:
            return
        color = QColor(self._selected.color)
        color.setAlpha(round(max(0, min(100, int(value))) * 255 / 100))
        self._selected.color = color.name(QColor.NameFormat.HexArgb)
        self.update()
        self._emit()

    def _request_selected_color(self) -> None:
        if self._selected in self._stops:
            self.colorRequested.emit(self._stops.index(self._selected))

    def _set_angle(self, a):
        self._angle = float(a)
        self.angle_spin.setValue(self._angle)


class _FillPreview(QLabel):
    """Sample subtitle text painted with the current solid/gradient fill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._solid = QColor("#FFFFFF")
        self._stops: list[tuple[float, QColor]] = []
        self._gradient_mode = False
        self.setMinimumHeight(56)
        self.setMaximumHeight(72)

    def set_solid(self, color: QColor) -> None:
        self._solid = QColor(color)
        self._gradient_mode = False
        self.update()

    def set_gradient(self, stops: list[tuple[float, QColor]]) -> None:
        self._stops = list(stops)
        self._gradient_mode = True
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        cell = 8
        for y in range(0, self.height(), cell):
            for x in range(0, self.width(), cell):
                light = ((x // cell) + (y // cell)) % 2 == 0
                painter.setBrush(QColor(30, 30, 34) if light else QColor(46, 46, 52))
                painter.drawRect(x, y, cell, cell)
        font = QFont(self.font())
        font.setPointSize(max(15, min(24, self.height() // 3)))
        font.setBold(True)
        painter.setFont(font)
        text_rect = QRectF(rect).adjusted(10, 2, -10, -2)
        painter.setPen(QPen(QColor(0, 0, 0, 180), 3))
        painter.drawText(text_rect.translated(1, 1), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter, "字幕样式 Aa 123")
        if self._gradient_mode and self._stops:
            gradient = QLinearGradient(text_rect.left(), 0, text_rect.right(), 0)
            for position, color in self._stops:
                gradient.setColorAt(max(0.0, min(1.0, position)), QColor(color))
            painter.setPen(QPen(QBrush(gradient), 0))
        else:
            painter.setPen(QPen(QBrush(self._solid), 0))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter, "字幕样式 Aa 123")
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 6, 6)
        painter.end()


class FillEditorDialog(QDialog):
    """One surface for solid, linear and radial subtitle fills.

    Professional picker stack: mode, gradient rail, opacity/location/angle,
    SV plane + vertical hue, HSB/RGB/HSL/YUV, HEX, current/previous plates.
    """

    recent_colors: list[str] = []

    def __init__(self, fill: str | Mapping[str, object] | None = None, parent=None):
        super().__init__(parent)
        bind_text(self, '填充', property='windowTitle')
        self.setObjectName("toolDialog")
        self.setMinimumSize(620, 620)
        self.resize(680, 700)
        from .color_picker import ColorPickerWidget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("fillModeCombo")
        self.mode_combo.addItems(["纯色", "线性渐变", "径向渐变"])
        self.mode_combo.setMinimumHeight(30)
        layout.addWidget(self.mode_combo)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for index, (label, value) in enumerate((("纯色", "solid"), ("线性渐变", "linear-gradient"), ("径向渐变", "radial-gradient"))):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("fillModeButton")
            button.setProperty("fillMode", value)
            button.hide()
            self.mode_group.addButton(button, index)
        self.mode_combo.currentIndexChanged.connect(self._combo_to_group)
        self.mode_group.idToggled.connect(self._group_toggled)

        self.gradient = GradientEditor(self, compact=True)
        self.gradient.colorRequested.connect(self._pick_gradient_stop)
        self.gradient.selectionChanged.connect(self._select_gradient_stop)
        self.gradient.gradientChanged.connect(self._gradient_changed)
        self.gradient.opacity_spin.valueChanged.connect(self._stop_opacity_to_picker)

        self._stop_host = QWidget()
        stop_grid = QGridLayout(self._stop_host)
        stop_grid.setContentsMargins(0, 0, 0, 0)
        stop_grid.setHorizontalSpacing(8)
        stop_grid.setVerticalSpacing(6)
        opacity_label = QLabel("透明度")
        opacity_label.setObjectName("fillFieldLabel")
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setObjectName("fillControlSlider")
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.valueChanged.connect(self._opacity_slider_changed)
        self.gradient.opacity_spin.setMinimumHeight(28)
        self.gradient.opacity_spin.setMaximumWidth(72)
        stop_grid.addWidget(opacity_label, 0, 0)
        stop_grid.addWidget(self._opacity_slider, 0, 1)
        stop_grid.addWidget(self.gradient.opacity_spin, 0, 2)

        self._location_host = QWidget()
        location_grid = QGridLayout(self._location_host)
        location_grid.setContentsMargins(0, 0, 0, 0)
        location_grid.setHorizontalSpacing(8)
        self._location_label = QLabel("位置")
        self._location_label.setObjectName("fillFieldLabel")
        self._location_slider = QSlider(Qt.Orientation.Horizontal)
        self._location_slider.setObjectName("fillControlSlider")
        self._location_slider.setRange(0, 1000)
        self._location_slider.valueChanged.connect(self._location_slider_changed)
        self.gradient.position_spin.setMinimumHeight(28)
        self.gradient.position_spin.setMaximumWidth(84)
        self.gradient.position_spin.setSuffix("")
        self.gradient.delete_stop_button.setObjectName("fillDeleteStop")
        self.gradient.delete_stop_button.setMinimumHeight(28)
        # Stop position is manipulated directly on the rail. Keep the legacy
        # widgets alive for payload/test compatibility, but do not expose the
        # redundant position row in the product UI.
        self._location_host.hide()
        stop_grid.addWidget(self.gradient.delete_stop_button, 0, 3)
        stop_grid.setColumnStretch(1, 1)

        self._angle_host = QWidget()
        angle_row = QHBoxLayout(self._angle_host)
        angle_row.setContentsMargins(0, 0, 0, 0)
        angle_row.setSpacing(8)
        angle_label = QLabel("角度")
        angle_label.setObjectName("fillFieldLabel")
        self._angle_slider = QSlider(Qt.Orientation.Horizontal)
        self._angle_slider.setObjectName("fillControlSlider")
        self._angle_slider.setRange(-180, 180)
        self._angle_slider.valueChanged.connect(self._angle_slider_changed)
        self.gradient.angle_spin.setMinimumHeight(28)
        self.gradient.angle_spin.setMaximumWidth(72)
        angle_row.addWidget(angle_label)
        angle_row.addWidget(self._angle_slider, 1)
        angle_row.addWidget(self.gradient.angle_spin)
        for label, angle, tip in (("0°", 0, "水平"), ("45°", 45, "斜向"), ("90°", 90, "垂直"), ("-45°", -45, "反斜向")):
            button = QPushButton(label)
            button.setFixedWidth(52)
            button.setMinimumHeight(28)
            button.setToolTip(tip)
            button.clicked.connect(lambda _c=False, a=angle: self.gradient._set_angle(a))
            angle_row.addWidget(button)
        self.gradient.angle_spin.valueChanged.connect(self._sync_angle_slider)

        picker_surface = QFrame()
        picker_surface.setObjectName("fillPickerSurface")
        picker_layout = QVBoxLayout(picker_surface)
        picker_layout.setContentsMargins(8, 8, 8, 8)
        picker_layout.setSpacing(8)
        picker_layout.addWidget(self._stop_host)
        picker_layout.addWidget(self._angle_host)
        picker_layout.addWidget(self.gradient)
        self.picker = ColorPickerWidget(show_alpha=False, embed_fields=True)
        picker_layout.addWidget(self.picker, 1)
        layout.addWidget(picker_surface, 1)
        self.preview = _FillPreview()
        self.preview.hide()

        common_row = QHBoxLayout()
        common_row.setSpacing(6)
        common_label = QLabel("常用")
        common_label.setObjectName("fillFieldLabel")
        common_row.addWidget(common_label)
        for color in tuple(dict.fromkeys(self.recent_colors + ["#FFFFFF", "#000000", "#FFE45E", "#FF4FA3", "#20D9FF", "#7C5CFF"]))[:8]:
            swatch = QPushButton()
            swatch.setFixedSize(22, 22)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setStyleSheet(
                f"background:{color};border:1px solid #9a9488;border-radius:4px;padding:0;min-height:22px"
            )
            swatch.clicked.connect(lambda _checked=False, value=color: self.picker.set_color(QColor(value)))
            common_row.addWidget(swatch)
        common_row.addStretch(1)
        layout.addLayout(common_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        kind = "solid"
        initial = "#FFFFFF"
        if isinstance(fill, Mapping):
            kind = str(fill.get("type") or "solid")
            self.gradient.set_value(dict(fill))
            stops = fill.get("stops") or []
            if stops and isinstance(stops[0], Mapping):
                initial = str(stops[0].get("color", "#FFFFFF"))
            elif kind == "solid":
                initial = str(fill.get("color") or "#FFFFFF")
        else:
            initial = str(fill or "#FFFFFF")
        self.picker.set_color(QColor(initial))
        self.picker.set_previous(QColor(initial))
        self.picker.colorChanged.connect(self._picker_changed)
        self.gradient.position_spin.valueChanged.connect(self._sync_location_slider)
        self.gradient.opacity_spin.valueChanged.connect(self._sync_opacity_slider)
        mode_id = {"solid": 0, "linear-gradient": 1, "radial-gradient": 2}.get(kind, 0)
        self.mode_group.button(mode_id).setChecked(True)
        apply_secondary_surface_theme(self)
        self._sync_mode()
        self._sync_opacity_slider()
        self._sync_location_slider()
        self._sync_angle_slider()

    def _combo_to_group(self, index: int) -> None:
        button = self.mode_group.button(index)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def _group_toggled(self, ident: int, checked: bool) -> None:
        if not checked:
            return
        if self.mode_combo.currentIndex() != ident:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(ident)
            self.mode_combo.blockSignals(False)
        self._sync_mode()

    def _sync_mode(self) -> None:
        gradient_mode = self.mode_group.checkedId() != 0
        self.gradient.setVisible(gradient_mode)
        self._location_host.hide()
        self.gradient.delete_stop_button.setVisible(gradient_mode)
        self._angle_host.setVisible(self.mode_group.checkedId() == 1)
        if gradient_mode and self.gradient._selected in self.gradient._stops:
            self._set_picker_color(QColor(self.gradient._selected.color))
        self._refresh_preview()

    def _set_picker_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self.picker.blockSignals(True)
        self.picker.set_color(color)
        self.picker.blockSignals(False)
        self._sync_opacity_slider()

    def _select_gradient_stop(self, index: int) -> None:
        if 0 <= index < len(self.gradient._stops):
            self.gradient._selected = self.gradient._stops[index]
            self.gradient._sync_stop_controls()
            self._set_picker_color(QColor(self.gradient._stops[index].color))
        self._refresh_preview()

    def _stop_opacity_to_picker(self, _value: int) -> None:
        selected = self.gradient._selected
        if selected not in self.gradient._stops:
            return
        self._set_picker_color(QColor(selected.color))

    def _opacity_slider_changed(self, value: int) -> None:
        color = self.picker.color()
        color.setAlpha(round(max(0, min(100, int(value))) * 255 / 100))
        self.picker.set_color(color)

    def _location_slider_changed(self, value: int) -> None:
        position = value / 1000.0
        if abs(self.gradient.position_spin.value() - position) > 0.0005:
            self.gradient.position_spin.setValue(position)

    def _angle_slider_changed(self, value: int) -> None:
        if int(self.gradient.angle_spin.value()) != int(value):
            self.gradient.angle_spin.setValue(value)

    def _sync_opacity_slider(self, *_args) -> None:
        if self.mode_group.checkedId() == 0:
            value = round(self.picker.color().alpha() * 100 / 255)
        else:
            value = self.gradient.opacity_spin.value()
        if self._opacity_slider.value() != value:
            self._opacity_slider.blockSignals(True)
            self._opacity_slider.setValue(value)
            self._opacity_slider.blockSignals(False)

    def _sync_location_slider(self, *_args) -> None:
        value = round(self.gradient.position_spin.value() * 1000)
        if self._location_slider.value() != value:
            self._location_slider.blockSignals(True)
            self._location_slider.setValue(value)
            self._location_slider.blockSignals(False)

    def _sync_angle_slider(self, *_args) -> None:
        value = int(self.gradient.angle_spin.value())
        if self._angle_slider.value() != value:
            self._angle_slider.blockSignals(True)
            self._angle_slider.setValue(value)
            self._angle_slider.blockSignals(False)

    def _pick_gradient_stop(self, index: int) -> None:
        if not (0 <= index < len(self.gradient._stops)):
            return
        self.gradient._selected = self.gradient._stops[index]
        self.gradient._sync_stop_controls()
        self._set_picker_color(QColor(self.gradient._selected.color))

    def _picker_changed(self, color: QColor) -> None:
        self._sync_opacity_slider()
        if self.mode_group.checkedId() == 0 or not color.isValid():
            self._refresh_preview()
            return
        selected = self.gradient._selected
        if selected not in self.gradient._stops:
            return
        selected.color = color.name(QColor.NameFormat.HexArgb)
        self.gradient._sync_stop_controls()
        self.gradient.update()
        self.gradient._emit()
        self._refresh_preview()

    def _gradient_changed(self, _value: dict) -> None:
        self._sync_location_slider()
        self._sync_angle_slider()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        if self.mode_group.checkedId() == 0:
            self.preview.set_solid(self.picker.color())
        else:
            stops = [
                (float(stop.get("position", 0)), QColor(str(stop.get("color", "#FFFFFF"))))
                for stop in self.gradient.value().get("stops", [])
            ]
            self.preview.set_gradient(stops)

    def value(self) -> str | dict:
        if self.mode_group.checkedId() == 0:
            color = self.picker.color().name(QColor.NameFormat.HexArgb)
            self.recent_colors[:] = [color] + [item for item in self.recent_colors if item != color][:7]
            return color
        value = self.gradient.value()
        value["type"] = "radial-gradient" if self.mode_group.checkedId() == 2 else "linear-gradient"
        return value


class FontPickerDialog(QDialog):
    recent_fonts: list[str] = []

    def __init__(self, current_family: str, preferred_weight: str | int = 400, parent=None):
        super().__init__(parent)
        bind_text(self, '字体', property='windowTitle')
        self.setObjectName("toolDialog")
        self.setMinimumSize(560, 560)
        self.resize(580, 600)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        bind_text(self.search, '搜索字体…', property='placeholderText')
        layout.addWidget(self.search)
        self.recent_label = QLabel("最近使用")
        self.recent_label.setStyleSheet("font-weight:700;color:#5f6861")
        layout.addWidget(self.recent_label)
        self.recent_table = QTableWidget(0, 1)
        self.recent_table.horizontalHeader().hide()
        self.recent_table.verticalHeader().hide()
        self.recent_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.recent_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.recent_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recent_table.setMaximumHeight(132)
        layout.addWidget(self.recent_table)
        self.all_label = QLabel("所有字体")
        self.all_label.setStyleSheet("font-weight:700;color:#5f6861")
        layout.addWidget(self.all_label)
        self.table = QTableWidget(0, 1)
        self.table.horizontalHeader().hide()
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.weight = StudioComboBox()
        for label, value in (("Regular", 400), ("Medium", 500), ("SemiBold", 600), ("Bold", 700), ("Heavy", 800), ("Black", 900)):
            self.weight.addItem(label, value)
        self.weight.setCurrentIndex(max(0, self.weight.findData(int(preferred_weight) if not isinstance(preferred_weight, str) else 400)))
        layout.addWidget(self.weight)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._inventory = system_font_inventory()
        self.search.textChanged.connect(self._populate)
        self.table.itemDoubleClicked.connect(lambda _item: self.accept())
        self.recent_table.itemDoubleClicked.connect(lambda _item: self.accept())
        self.table.currentItemChanged.connect(lambda current, _old: self.recent_table.clearSelection() if current else None)
        self.recent_table.currentItemChanged.connect(lambda current, _old: self.table.clearSelection() if current else None)
        if current_family:
            self.recent_fonts[:] = [current_family] + [value for value in self.recent_fonts if value != current_family][:7]
        self._populate()
        matches = self.recent_table.findItems(current_family, Qt.MatchFlag.MatchExactly)
        if matches:
            self.recent_table.setCurrentItem(matches[0])
        else:
            matches = self.table.findItems(current_family, Qt.MatchFlag.MatchExactly)
        if matches:
            if matches[0].tableWidget() is self.table:
                self.table.setCurrentItem(matches[0])

    def _populate(self) -> None:
        needle = self.search.text().strip().casefold()
        entries = [entry for entry in self._inventory if not needle or needle in entry.family.casefold()]
        recent = [entry for family in self.recent_fonts for entry in entries if entry.family == family]
        all_entries = [entry for entry in entries if entry.family not in self.recent_fonts]
        self.recent_label.setVisible(bool(recent))
        self.recent_table.setVisible(bool(recent))
        self.recent_table.setRowCount(len(recent))
        for row, entry in enumerate(recent):
            item = QTableWidgetItem(entry.family)
            item.setFont(QFont(entry.family, 13))
            item.setToolTip(" / ".join(entry.styles) or entry.family)
            self.recent_table.setItem(row, 0, item)
            self.recent_table.setRowHeight(row, 38)
        self.table.setRowCount(len(all_entries))
        for row, entry in enumerate(all_entries):
            item = QTableWidgetItem(entry.family)
            item.setFont(QFont(entry.family, 13))
            item.setToolTip(" / ".join(entry.styles) or entry.family)
            self.table.setItem(row, 0, item)
            self.table.setRowHeight(row, 38)

    def selection(self) -> tuple[str, str, int]:
        item = self.recent_table.currentItem() if self.recent_table.hasFocus() else self.table.currentItem()
        if item is None:
            item = self.recent_table.currentItem()
        family = item.text() if item else "Microsoft YaHei UI"
        style, weight = resolve_font_weight(family, int(self.weight.currentData() or 400))
        self.recent_fonts[:] = [family] + [value for value in self.recent_fonts if value != family][:7]
        return family, style, weight
