"""Fill/gradient editors and the studio font picker dialog."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .font_system import resolve_font_weight, system_font_inventory
from ..design.studio_theme import StudioComboBox
from ..studio.studio_widgets import ScrubDoubleSpinBox, ScrubSpinBox

from ..i18n import apply_ui_language, bind_text, current_language, translate

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
        self._removing = False
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
            return self.bar.rect().adjusted(16, 9, -16, -9)
        return self.bar.rect().adjusted(2, 2, -2, -2)

    def _paint_rounded_bar(self) -> None:
        """Compact rail (2026-11-03): pill strip with round white-ring stops."""
        from ..design.fill_picker import checker_brush, paint_knob
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition

        theme = theme_definition(theme_key())
        p = QPainter(self.bar)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self._strip_rect())
        strip = r.adjusted(-8, 0, 8, 0)
        path = QPainterPath()
        path.addRoundedRect(strip, strip.height() / 2, strip.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(checker_brush(5))
        p.drawPath(path)
        ordered = sorted(self._stops, key=lambda x: x.pos)
        grad = QLinearGradient(r.left(), 0, r.right(), 0)
        for s in ordered:
            grad.setColorAt(max(0.0, min(1.0, s.pos)), QColor(s.color))
        p.setBrush(QBrush(grad))
        p.drawPath(path)
        p.setPen(QPen(QColor(0, 0, 0, 45), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        for s in ordered:
            if s is self._selected:
                continue
            p.setOpacity(1.0)
            paint_knob(p, QPointF(r.left() + s.pos * r.width(), r.center().y()), 11.5, QColor(s.color))
        if self._selected in self._stops:
            center = QPointF(r.left() + self._selected.pos * r.width(), r.center().y())
            p.setOpacity(0.35 if self._removing else 1.0)
            p.setPen(QPen(QColor(theme.accent), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(center, 17, 17)
            paint_knob(p, center, 14, QColor(self._selected.color))
        p.end()

    def _paint_bar(self, ev):
        if self._compact:
            self._paint_rounded_bar()
            return
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
        self._removing = False
        hit_threshold = max(0.01, (14.0 if self._compact else 10.0) / max(1, r.width()))
        nearest = min(self._stops, key=lambda s: abs(s.pos - pos), default=None)
        if nearest is not None and abs(nearest.pos - pos) <= hit_threshold:
            self._selected = nearest
            self._dragging_stop = True
            self._sync_stop_controls()
            self.update()
            self.selectionChanged.emit(self._stops.index(nearest))

    # Compact rail: dragging a stop this far above/below the strip removes it.
    REMOVE_DISTANCE = 34

    def _bar_drag(self, ev):
        if not (ev.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self._dragging_stop or self._selected is None or self._selected not in self._stops:
            return
        r = self._strip_rect()
        pos = max(0.0, min(1.0, (ev.position().x() - r.left()) / max(1, r.width())))
        selected = self._selected
        selected.pos = pos
        self._removing = (
            self._compact and len(self._stops) > 2
            and abs(ev.position().y() - r.center().y()) > self.REMOVE_DISTANCE
        )
        self._sync_stop_controls()
        self._stops.sort(key=lambda x: x.pos)
        self._selected = selected
        self.update()
        self._emit()

    def _bar_release(self, _ev):
        if self._dragging_stop and self._removing:
            self._removing = False
            self._delete_selected()
            if self._selected in self._stops:
                self.selectionChanged.emit(self._stops.index(self._selected))
        self._dragging_stop = False
        self._removing = False

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


class _FillPreview(QWidget):
    """Large sample-subtitle card painted with the current fill (2026-11-03).

    Three backdrops (checker / game-like scene / light) sit behind outlined
    sample text; the top-right tag names the fill, the bottom-left dots switch
    the backdrop.
    """

    BACKDROPS = ("checker", "scene", "light")
    SAMPLE = "字幕样式 Aa 123"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fill: str | dict = "#FFFFFFFF"
        self._desc = ""
        self._snapshot = None
        self._raster = None
        self.backdrop = "scene"
        self.setFixedHeight(156)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_fill(self, fill: str | dict, desc: str = "") -> None:
        self._fill = fill
        self._desc = desc
        self.update()

    def set_snapshot(self, snapshot, desc=''):
        self._snapshot = snapshot
        self._raster = None
        self._desc = desc
        self.update()

    def set_backdrop(self, name: str) -> None:
        if name in self.BACKDROPS:
            self.backdrop = name
            self.update()

    def _dot_rects(self) -> list[QRectF]:
        return [QRectF(16 + index * 26, self.height() - 34, 20, 20) for index in range(len(self.BACKDROPS))]

    def mousePressEvent(self, event) -> None:
        for name, rect in zip(self.BACKDROPS, self._dot_rects()):
            if rect.adjusted(-3, -3, 3, 3).contains(event.position()):
                self.set_backdrop(name)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        over = any(rect.adjusted(-3, -3, 3, 3).contains(event.position()) for rect in self._dot_rects())
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def _paint_backdrop(self, painter: QPainter, rect: QRectF) -> None:
        from ..design.fill_picker import checker_brush

        if self.backdrop == "checker":
            painter.fillRect(rect, checker_brush(8, dark=True))
        elif self.backdrop == "light":
            painter.fillRect(rect, QColor("#f4f1ee"))
        else:
            sky = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            sky.setColorAt(0.0, QColor("#1b1f3d"))
            sky.setColorAt(0.62, QColor("#55386a"))
            sky.setColorAt(1.0, QColor("#a65f7c"))
            painter.fillRect(rect, sky)
            for center, radius, color in (
                (QPointF(rect.width() * 0.84, rect.bottom() + 8), rect.width() * 0.42, QColor(246, 161, 116, 150)),
                (QPointF(rect.width() * 0.06, rect.top() - 12), rect.width() * 0.4, QColor(79, 69, 160, 150)),
            ):
                glow = QRadialGradient(center, radius)
                glow.setColorAt(0.0, color)
                glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
                painter.fillRect(rect, glow)
            hill = QPainterPath()
            hill.addEllipse(QRectF(rect.left() - rect.width() * 0.08, rect.bottom() - rect.height() * 0.3, rect.width() * 1.16, rect.height() * 0.7))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(26, 20, 38, 215))
            painter.drawPath(hill)

    def paintEvent(self, _event) -> None:
        from ..design.typography import TITLE_FONT_FAMILIES
        from ..design.fill_picker import checker_brush, mono_font
        from ..studio.studio_helpers import resolve_fill_brush

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        card = QPainterPath()
        card.addRoundedRect(rect, 18, 18)
        painter.setClipPath(card)
        self._paint_backdrop(painter, rect)

        if self._snapshot is not None:
            from ..rendering.advanced_live_renderer import render_live_snapshot
            key = (self.width(), self.height(), self.devicePixelRatioF())
            if self._raster is None or self._raster[0] != key:
                self._raster = (key, render_live_snapshot(self._snapshot, width=self.width(),
                    height=self.height(), device_pixel_ratio=self.devicePixelRatioF()))
            painter.drawImage(QPointF(0, 0), self._raster[1])
        else:
            font = QFont()
            font.setFamilies(list(TITLE_FONT_FAMILIES))
            font.setPixelSize(34)
            font.setWeight(QFont.Weight.Black)
            text = QPainterPath()
            text.addText(0, 0, font, self.SAMPLE)
            bounds = text.boundingRect()
            text.translate(rect.center().x() - bounds.center().x(), rect.center().y() - 6 - bounds.center().y())
            painter.setPen(QPen(QColor("#1a1320"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(text)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(resolve_fill_brush(self._fill, text.boundingRect()))
            painter.drawPath(text)

        if self._desc:
            tag_font = mono_font(12, QFont.Weight.Bold)
            painter.setFont(tag_font)
            width = painter.fontMetrics().horizontalAdvance(self._desc) + 22
            tag = QRectF(rect.right() - width - 10, 10, width, 24)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawRoundedRect(tag, 12, 12)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(tag, Qt.AlignmentFlag.AlignCenter, self._desc)

        dots = self._dot_rects()
        holder = QRectF(dots[0].left() - 5, dots[0].top() - 5, dots[-1].right() - dots[0].left() + 10, 30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 90))
        painter.drawRoundedRect(holder, 15, 15)
        for name, dot in zip(self.BACKDROPS, dots):
            if name == "checker":
                painter.setBrush(checker_brush(4, dark=True))
            elif name == "light":
                painter.setBrush(QColor("#f4f1ee"))
            else:
                swatch = QLinearGradient(dot.topLeft(), dot.bottomLeft())
                swatch.setColorAt(0.0, QColor("#2a2c5a"))
                swatch.setColorAt(1.0, QColor("#a65f7c"))
                painter.setBrush(QBrush(swatch))
            painter.setPen(QPen(QColor("#ffffff") if name == self.backdrop else QColor(255, 255, 255, 70), 2 if name == self.backdrop else 1))
            painter.drawEllipse(dot)
        painter.end()


class _Avatar(QWidget):
    """Brand bunny in a soft accent circle for the dialog header."""

    _pixmap: QPixmap | None = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(38, 38)
        if _Avatar._pixmap is None:
            from ..runtime_paths import detect_install_root

            _Avatar._pixmap = QPixmap(str(detect_install_root() / "assets" / "2byteasr-icon-transparent.png"))

    def paintEvent(self, _event) -> None:
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme_definition(theme_key()).accent_soft))
        painter.drawEllipse(rect)
        pixmap = _Avatar._pixmap
        if pixmap is not None and not pixmap.isNull():
            clip = QPainterPath()
            clip.addEllipse(rect)
            painter.setClipPath(clip)
            painter.drawPixmap(rect.adjusted(2, 2, -2, -2).toRect(), pixmap)
        painter.end()


class FillEditorDialog(QDialog):
    """Solid / linear / radial subtitle fill editor ("调色工作台", 2026-11-03).

    Frameless rounded card: left column previews the fill and holds the
    gradient rail and swatch box (常用 / 最近 / 渐变); right column is the
    color picker (hue ring + square, opacity, current/previous, numbers).
    Still a Qt-modal QDialog: ``exec()`` / ``value()`` are unchanged.
    """

    from ..design.widget_teardown import delete_tree_before_collection as __del__

    recent_colors: list[str] = []
    COMMON_COLORS = ("#FFFFFF", "#000000", "#FFE45E", "#FF4FA3", "#20D9FF", "#7C5CFF", "#FF6B6B", "#7CF29A")
    GRADIENT_PRESETS = (
        ("莓果汽水", ("#FF7EB6", "#7C5CFF")),
        ("薄荷", ("#20D9FF", "#7CF29A")),
        ("晚霞", ("#FFE45E", "#FF4FA3")),
        ("兔耳", ("#FFFFFF", "#F4DCE8")),
        ("霓虹", ("#00F0FF", "#FF00E5", "#FFE45E")),
        ("金币", ("#FFF3A3", "#FFB800")),
        ("夜空", ("#7C5CFF", "#20D9FF")),
        ("奶糖", ("#FFF4E8", "#FFB3C7")),
    )
    MODES = ("solid", "linear-gradient", "radial-gradient")
    SHADOW = 18

    def __init__(self, fill: str | Mapping[str, object] | None = None, parent=None, *,
                 title='填充', allow_gradients=True, preview_update=None, preview_snapshot=None, edit_target='fill'):
        # A complete appearance surface owns its style sheet. Keeping it in
        # Studio's QObject style tree repolished the entire large workspace
        # when the modal appeared and closed. Native transient ownership still
        # keeps it above, and modal to, the editing window.
        super().__init__(None)
        import weakref
        self._owner_widget = weakref.ref(parent) if parent is not None else lambda: None
        self._owns_theme_sheet = True
        self._startup_gc_timer = None
        self._native_transitions_disabled = False
        from ..design.fill_picker import AngleDial, FillColorPicker, PillField, PillSegment, round_button

        self.allow_gradients = bool(allow_gradients)
        self._preview_update = preview_update
        self._preview_snapshot = preview_snapshot
        self.edit_target = edit_target
        bind_text(self, title, property='windowTitle')
        self.setObjectName("fillEditorDialog")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.SHADOW, self.SHADOW - 6, self.SHADOW, self.SHADOW + 6)
        self.card = QFrame()
        self.card.setObjectName("fillCard")
        outer.addWidget(self.card)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(16)

        self.header = QWidget()
        self.header.installEventFilter(self)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(_Avatar())
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title_label = QLabel(title)
        self._title_label = title_label
        title_label.setObjectName("fillTitle")
        self.subtitle = QLabel('字幕正文' if edit_target == 'fill' else '字幕' + title)
        self.subtitle.setObjectName("fillSubtitle")
        titles.addWidget(title_label)
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        modes = [("纯色", "solid"), ("线性渐变", "linear"), ("径向渐变", "radial")]
        self.mode_segment = PillSegment(modes if allow_gradients else modes[:1], height=42, icons=True)
        self.mode_segment.setFixedWidth(340 if allow_gradients else 120)
        self.mode_group = self.mode_segment.group
        # QComboBox-style alias kept for acceptance scripts.
        self.mode_combo = self.mode_segment
        header.addWidget(self.mode_segment)
        self.close_button = round_button("fa5s.times", "关闭")
        self.close_button.setProperty("ghost", True)
        self.close_button.clicked.connect(self.reject)
        header.addWidget(self.close_button)
        layout.addWidget(self.header)

        body = QHBoxLayout()
        body.setSpacing(20)
        left_host = QWidget()
        left_host.setFixedWidth(350)
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(12)
        self.preview = _FillPreview()
        left.addWidget(self.preview)

        self.gradient = GradientEditor(self, compact=True)
        self._default_gradient_value = self.gradient.value()
        self.gradient.colorRequested.connect(self._pick_gradient_stop)
        self.gradient.selectionChanged.connect(self._select_gradient_stop)
        self.gradient.gradientChanged.connect(self._gradient_changed)
        self.gradient.opacity_spin.valueChanged.connect(self._stop_opacity_to_picker)
        self.gradient.bar.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(self.gradient.bar, '双击加色点，拖动移动，拖出色条删除', property='toolTip')

        self._gradient_card = QFrame()
        self._gradient_card.setObjectName("fillSubCard")
        gradient_layout = QVBoxLayout(self._gradient_card)
        gradient_layout.setContentsMargins(14, 12, 14, 12)
        gradient_layout.setSpacing(8)
        gradient_title = QHBoxLayout()
        label = QLabel("渐变色条")
        label.setObjectName("fillCardTitle")
        hint = QLabel("双击色条加色点 · 拖出去删除")
        hint.setObjectName("fillHint")
        gradient_title.addWidget(label)
        gradient_title.addStretch(1)
        gradient_title.addWidget(hint)
        gradient_layout.addLayout(gradient_title)
        gradient_layout.addWidget(self.gradient)
        tools = QHBoxLayout()
        tools.setSpacing(4)
        self._angle_host = QWidget()
        angle_row = QHBoxLayout(self._angle_host)
        angle_row.setContentsMargins(0, 0, 0, 0)
        angle_row.setSpacing(4)
        self.angle_dial = AngleDial()
        self.angle_dial.angleChanged.connect(lambda angle: self.gradient._set_angle(angle))
        angle_row.addWidget(self.angle_dial)
        angle_field = PillField(self.gradient.angle_spin, suffix="°")
        angle_field.setFixedWidth(78)
        angle_row.addWidget(angle_field)
        self._angle_chips: list[QPushButton] = []
        for angle in (0, 45, 90):
            chip = QPushButton(f"{angle}°")
            chip.setObjectName("fillChip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setProperty("angle", angle)
            chip.setFixedWidth(36)
            chip.clicked.connect(lambda _c=False, a=angle: self.gradient._set_angle(a))
            angle_row.addWidget(chip)
            self._angle_chips.append(chip)
        tools.addWidget(self._angle_host)
        self._radius_host = QWidget()
        radius_row = QHBoxLayout(self._radius_host)
        radius_row.setContentsMargins(0, 0, 0, 0)
        radius_row.addWidget(QLabel('范围'))
        self.radius_spin = ScrubDoubleSpinBox()
        self.radius_spin.setRange(5, 400)
        self.radius_spin.setDecimals(0)
        self.radius_spin.setSingleStep(5)
        self.radius_spin.setValue(100)
        radius_row.addWidget(PillField(self.radius_spin, suffix='%'))
        self.radius_spin.valueChanged.connect(lambda _v: self._refresh_preview())
        tools.addWidget(self._radius_host)
        tools.addStretch(1)
        self.reverse_button = round_button("fa5s.exchange-alt", "反转渐变方向")
        self.reverse_button.clicked.connect(self.gradient._reverse)
        tools.addWidget(self.reverse_button)
        delete = self.gradient.delete_stop_button
        delete.setText("")
        delete.setObjectName("fillRoundButton")
        delete.setFixedSize(34, 34)
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        from ..design.fill_picker import _theme
        import qtawesome as qta
        delete.setIcon(qta.icon("fa5s.trash-alt", color=_theme().text_secondary, color_disabled=_theme().disabled))
        tools.addWidget(delete)
        gradient_layout.addLayout(tools)
        self.gradient.angle_spin.valueChanged.connect(self._sync_angle_controls)
        left.addWidget(self._gradient_card)

        palette_card = QFrame()
        palette_card.setObjectName("fillSubCard")
        palette_layout = QVBoxLayout(palette_card)
        palette_layout.setContentsMargins(14, 12, 14, 12)
        palette_layout.setSpacing(8)
        palette_title = QHBoxLayout()
        palette_title.setSpacing(2)
        label = QLabel("颜料盒")
        label.setObjectName("fillCardTitle")
        palette_title.addWidget(label)
        palette_title.addStretch(1)
        self.palette_group = QButtonGroup(self)
        self.palette_group.setExclusive(True)
        self._palette_tabs: dict[str, QPushButton] = {}
        for key, text in (("common", "常用"), ("recent", "最近"), ("gradient", "渐变")):
            tab = QPushButton(text)
            tab.setObjectName("fillTab")
            tab.setCheckable(True)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.clicked.connect(lambda _c=False, k=key: self._set_palette(k))
            self.palette_group.addButton(tab)
            self._palette_tabs[key] = tab
            palette_title.addWidget(tab)
        palette_layout.addLayout(palette_title)
        self._palette_host = QWidget()
        self._palette_grid = QGridLayout(self._palette_host)
        self._palette_grid.setContentsMargins(0, 0, 0, 0)
        self._palette_grid.setHorizontalSpacing(0)
        self._palette_grid.setVerticalSpacing(2)
        palette_layout.addWidget(self._palette_host)
        self._palette = "common"
        self._swatches: list = []
        left.addWidget(palette_card)
        left.addStretch(1)
        body.addWidget(left_host)

        self.picker = FillColorPicker()
        body.addWidget(self.picker, 1, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.save_button = QPushButton("+ 存进颜料盒")
        self.save_button.setObjectName("fillTextButton")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self._save_current)
        footer.addWidget(self.save_button)
        footer.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        for kind, name in ((QDialogButtonBox.StandardButton.Ok, "fillPrimary"), (QDialogButtonBox.StandardButton.Cancel, "fillGhost")):
            button = buttons.button(kind)
            button.setObjectName(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        footer.addWidget(buttons)
        layout.addLayout(footer)

        kind = "solid"
        initial = "#FFFFFF"
        if isinstance(fill, Mapping):
            kind = str(fill.get("type") or "solid")
            self.gradient.set_value(dict(fill))
            self.radius_spin.setValue(float(fill.get('radius', 1))*100)
            stops = fill.get("stops") or []
            if stops and isinstance(stops[0], Mapping):
                initial = str(stops[0].get("color", "#FFFFFF"))
            elif kind == "solid":
                initial = str(fill.get("color") or "#FFFFFF")
        else:
            initial = str(fill or "#FFFFFF")
        self._solid = QColor(initial)
        self.picker.set_color(QColor(initial))
        self.picker.set_previous(QColor(initial))
        self.picker.colorChanged.connect(self._picker_changed)
        mode_id = {"solid": 0, "linear-gradient": 1, "radial-gradient": 2}.get(kind, 0) if allow_gradients else 0
        self.mode_group.button(mode_id).setChecked(True)
        self.mode_group.idToggled.connect(self._group_toggled)
        self._apply_theme()
        self._set_palette("gradient" if mode_id else "common")
        self._sync_mode()
        self._sync_angle_controls()
        if parent is not None:
            owner = parent.window()
            handle = owner.windowHandle()
            if handle is not None:
                self.winId()
                self.windowHandle().setTransientParent(handle)
            owner.destroyed.connect(self._owner_destroyed)
        if QApplication.instance() is not None and QApplication.instance().platformName() == 'windows':
            import ctypes
            from ctypes import wintypes
            try:
                disable = wintypes.BOOL(True)
                function = ctypes.windll.dwmapi.DwmSetWindowAttribute
                function.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
                function.restype = wintypes.LONG
                DWMWA_TRANSITIONS_FORCEDISABLED = 3
                self._native_transitions_disabled = function(int(self.winId()), DWMWA_TRANSITIONS_FORCEDISABLED,
                    ctypes.byref(disable), ctypes.sizeof(disable)) == 0
            except (OSError, AttributeError):
                pass

    def exec(self):
        # Publish the already prepared surface before unrelated queued work.
        # A short, bounded GC lease protects this first interactive frame only.
        from ..playback.playback_gc_budget import hold_full_collections, release_full_collections
        key = ('appearance-show', id(self))
        held = hold_full_collections(key)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: release_full_collections(key))
        if held:
            self._startup_gc_timer = timer
            timer.start(2000)
        try:
            import time
            self.setResult(QDialog.DialogCode.Rejected)
            began = time.perf_counter()
            self.show()
            shown = time.perf_counter()
            self.repaint()
            self._open_timing = {'show_ms': (shown-began)*1000, 'repaint_ms': (time.perf_counter()-shown)*1000}
            if not self.isVisible():return self.result()
            return super().exec()
        finally:
            self._startup_gc_timer = None
            from shiboken6 import isValid
            if isValid(timer):
                timer.stop()
                timer.deleteLater()
            if held:release_full_collections(key)

    def _owner_destroyed(self, *_args):
        self._retain_for_style = False
        self.reject()
        QDialog.deleteLater(self)

    def reset_draft(self, fill, *, title='填充', preview_snapshot=None, edit_target='fill'):
        from .style_recipe import FillSpec
        spec = FillSpec.from_value(fill)
        self._preview_snapshot = preview_snapshot
        self._preview_update = None
        self.edit_target = edit_target
        self._owner_positioned = False
        bind_text(self, title, property='windowTitle')
        bind_text(self._title_label, title)
        bind_text(self.subtitle, '字幕正文' if edit_target == 'fill' else '字幕' + title)
        value = spec.to_dict()
        self.gradient.set_value(value if spec.kind != 'solid' else self._default_gradient_value)
        self.radius_spin.setValue(float(value.get('radius', 1))*100)
        initial = spec.color if spec.kind == 'solid' else str(spec.stops[0]['color'])
        self._solid = QColor(initial)
        self._set_picker_color(QColor(initial))
        self.picker.set_previous(QColor(initial))
        self.mode_group.button(self.MODES.index(spec.kind)).setChecked(True)
        self._set_palette('common' if spec.kind == 'solid' else 'gradient')
        self._sync_mode()
        self._sync_angle_controls()
        self.layout().activate()
        self.adjustSize()

    def prepare_language(self):
        language = current_language()
        if getattr(self, '_prepared_language', None) != language:
            apply_ui_language(self, language)
            self._prepared_language = language

    def refresh_theme_palette(self):
        from ..design.theme_manager import theme_key
        if getattr(self, '_theme_key', None) != theme_key():
            self._apply_theme()

    # --- shell ----------------------------------------------------------
    def _apply_theme(self) -> None:
        from ..design.fill_picker import fill_editor_qss
        from ..design.studio_theme import build_secondary_surface_qss
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition

        theme = theme_definition(theme_key())
        self._theme_key = theme.key
        from ..app.ui_zoom import set_sheet
        set_sheet(self, build_secondary_surface_qss(theme) + fill_editor_qss(theme))
        self.mode_segment.refresh_icons()

    def showEvent(self, event) -> None:
        from ..design.theme_manager import theme_key

        if getattr(self, "_theme_key", None) != theme_key():
            self._apply_theme()
        self.prepare_language()
        # Appearance editors are frequent actions: their first frame is fully
        # visible and interactive. Sampling alone temporarily clears opacity.
        self.setWindowOpacity(1.0)
        owner = self._owner_widget()
        if owner is not None and not getattr(self, '_owner_positioned', False):
            frame = self.frameGeometry()
            frame.moveCenter(owner.window().frameGeometry().center())
            screen = self.screen()
            if screen is not None:
                bounds = screen.availableGeometry()
                frame.moveLeft(max(bounds.left(), min(frame.left(), bounds.right()-frame.width()+1)))
                frame.moveTop(max(bounds.top(), min(frame.top(), bounds.bottom()-frame.height()+1)))
            self.move(frame.topLeft())
            self._owner_positioned = True
        super().showEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.header and event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return True
        return super().eventFilter(obj, event)

    def paintEvent(self, _event) -> None:
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition

        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = QRectF(self.card.geometry())
        radius = 26.0
        painter.setPen(Qt.PenStyle.NoPen)
        layers = 10
        strength = 9 if theme.is_light else 22
        for step in range(layers, 0, -1):
            spread = step * 1.6
            painter.setBrush(QColor(0, 0, 0, max(1, round(strength * (1 - step / (layers + 1)) ** 2))))
            painter.drawRoundedRect(card.adjusted(-spread, -spread + 4, spread, spread + 4), radius + spread, radius + spread)
        painter.setBrush(QColor(theme.surface))
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.end()
        timer = self._startup_gc_timer
        if timer is not None and self.isVisible():
            self._startup_gc_timer = None
            timer.start(250)

    # --- palette --------------------------------------------------------
    def _set_palette(self, key: str) -> None:
        from ..design.fill_picker import SwatchButton

        if key == "gradient" and self.mode_group.checkedId() == 0:
            key = "common"
        signature = (key, repr(self.GRADIENT_PRESETS) if key == 'gradient' else
                     tuple(self.COMMON_COLORS if key == 'common' else self.recent_colors[:7]))
        if getattr(self, '_palette_signature', None) == signature:
            self._palette_tabs[key].setChecked(True)
            self._sync_swatches()
            return
        self._palette_signature = signature
        self._palette = key
        self._palette_tabs[key].setChecked(True)
        while self._palette_grid.count():
            item = self._palette_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        swatches = []
        if key == "gradient":
            for name, stops in self.GRADIENT_PRESETS:
                button = SwatchButton(stops=stops)
                bind_text(button, name, property='toolTip')
                button.clicked.connect(lambda _c=False, s=stops: self._apply_preset(s))
                swatches.append(button)
        else:
            colors = self.COMMON_COLORS if key == "common" else tuple(self.recent_colors[:7])
            for value in colors:
                button = SwatchButton(value)
                button.setToolTip(QColor(value).name(QColor.NameFormat.HexRgb).upper())
                button.clicked.connect(lambda _c=False, v=value: self.picker.set_color(QColor(v)))
                swatches.append(button)
            if key == "recent":
                add = SwatchButton(add=True)
                bind_text(add, '把当前颜色存进最近', property='toolTip')
                add.clicked.connect(self._save_current)
                swatches.append(add)
        for index, button in enumerate(swatches):
            self._palette_grid.addWidget(button, index // 8, index % 8, Qt.AlignmentFlag.AlignCenter)
        for column in range(8):
            self._palette_grid.setColumnStretch(column, 1)
        self._swatches = swatches
        self._sync_swatches()

    def _sync_swatches(self) -> None:
        color = self.picker.color()
        current = color.name(QColor.NameFormat.HexArgb).upper()
        for button in self._swatches:
            if button.color.isValid() and not button.stops:
                button.set_selected(button.color.name(QColor.NameFormat.HexArgb).upper() == current)

    def _save_current(self) -> None:
        value = self.picker.color().name(QColor.NameFormat.HexArgb).upper()
        self.recent_colors[:] = [value] + [item for item in self.recent_colors if item.upper() != value][:7]
        self._set_palette("recent")

    def _apply_preset(self, stops: tuple[str, ...]) -> None:
        count = max(1, len(stops) - 1)
        self.gradient.set_value({
            "stops": [{"color": value, "position": index / count} for index, value in enumerate(stops)],
            "angle": self.gradient._angle,
        })
        self.gradient._emit()
        self._select_gradient_stop(0)

    # --- mode / sync ----------------------------------------------------
    def _group_toggled(self, ident: int, checked: bool) -> None:
        if checked:
            self._sync_mode()

    def _sync_mode(self) -> None:
        mode = self.mode_group.checkedId()
        gradient_mode = mode != 0
        self._gradient_card.setVisible(gradient_mode)
        self._angle_host.setVisible(mode == 1)
        self._radius_host.setVisible(mode == 2)
        self._palette_tabs["gradient"].setVisible(gradient_mode)
        if gradient_mode != (self._palette == "gradient"):
            self._set_palette("gradient" if gradient_mode else "common")
        if gradient_mode and self.gradient._selected in self.gradient._stops:
            self._set_picker_color(QColor(self.gradient._selected.color))
            self.picker.set_previous(QColor(self.gradient._selected.color))
        elif not gradient_mode:
            self._set_picker_color(self._solid)
        self._sync_target_label()
        self._refresh_preview()

    def _sync_target_label(self) -> None:
        if self.mode_group.checkedId() == 0 or self.gradient._selected not in self.gradient._stops:
            self.picker.set_target_suffix("")
        else:
            ordered = sorted(self.gradient._stops, key=lambda item: item.pos)
            self.picker.set_target_suffix(translate(" · 色点 {index}").format(index=ordered.index(self.gradient._selected) + 1))

    def _sync_angle_controls(self, *_args) -> None:
        angle = float(self.gradient.angle_spin.value())
        self.angle_dial.set_angle(angle)
        for chip in self._angle_chips:
            chip.setChecked(abs(float(chip.property("angle")) - angle) < 0.5)
        self._refresh_preview()

    def _set_picker_color(self, color: QColor) -> None:
        if not color.isValid():
            return
        self.picker.blockSignals(True)
        self.picker.set_color(color)
        self.picker.blockSignals(False)
        self._sync_swatches()

    def _select_gradient_stop(self, index: int) -> None:
        if 0 <= index < len(self.gradient._stops):
            self.gradient._selected = self.gradient._stops[index]
            self.gradient._sync_stop_controls()
            color = QColor(self.gradient._stops[index].color)
            self._set_picker_color(color)
            self.picker.set_previous(color)
        self.gradient.update()
        self._sync_target_label()
        self._refresh_preview()

    def _stop_opacity_to_picker(self, _value: int) -> None:
        selected = self.gradient._selected
        if selected in self.gradient._stops:
            self._set_picker_color(QColor(selected.color))

    def _pick_gradient_stop(self, index: int) -> None:
        if not (0 <= index < len(self.gradient._stops)):
            return
        self.gradient._selected = self.gradient._stops[index]
        self.gradient._sync_stop_controls()
        self._set_picker_color(QColor(self.gradient._selected.color))

    def _picker_changed(self, color: QColor) -> None:
        self._sync_swatches()
        if self.mode_group.checkedId() == 0 or not color.isValid():
            self._solid = QColor(color)
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
        self._sync_target_label()
        self._refresh_preview()

    def _current_value(self):
        if self.mode_group.checkedId() <= 0:
            return self.picker.color().name(QColor.NameFormat.HexArgb)
        value = self.gradient.value()
        value['type'] = self.MODES[self.mode_group.checkedId()]
        if self.mode_group.checkedId() == 2:
            value['radius'] = self.radius_spin.value()/100
        return value

    def _refresh_preview(self) -> None:
        value = self._current_value()
        if self._preview_update is not None:
            self._preview_update(self.preview, self.picker.color())
        mode = self.mode_group.checkedId()
        if mode <= 0:
            color = self.picker.color()
            desc = f'{color.name(QColor.HexRgb).upper()} · {round(color.alphaF()*100)}%'
        else:
            desc = ('线性渐变' if mode == 1 else '径向渐变') + f" · {len(value['stops'])} 色"
            desc += f" · {round(value.get('angle', 0))}°" if mode == 1 else f" · {round(self.radius_spin.value())}%"
        if self._preview_snapshot is not None:
            from .effect_paints import picker_snapshot
            snapshot = picker_snapshot(self._preview_snapshot, self.edit_target, value)
            self.preview.set_snapshot(snapshot, desc)
        else:
            self.preview.set_fill(value, desc)

    def value(self) -> str | dict:
        value = self._current_value()
        if isinstance(value, str):
            self.recent_colors[:] = [value] + [item for item in self.recent_colors if item != value][:7]
        return value

    def selectedColor(self) -> QColor:
        value = self._current_value()
        return QColor(value if isinstance(value, str) else value['stops'][0]['color'])


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
