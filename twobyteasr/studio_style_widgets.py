"""Style inspector building blocks: property rows, scope selector, color
button, and the style preview swatch."""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping

from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QKeySequence,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from .effect_dsl import POSITION_EFFECT_TYPES, STRENGTH_PRESETS, validate_effect
from .style_recipe import FillSpec
from .studio_helpers import _preview_color, render_style_sample
from .studio_theme import STYLE_FIELD_HEIGHT
from .theme_manager import theme_key
from .ui_theme import theme_definition

from .i18n import bind_text, tr

def motion_preview_pacing(effect: Mapping) -> int:
    """Hold time between library preview loops, by motion category.

    The animation itself plays at its authored speed; the hold keeps each
    loop readable (user-spec 2.5-4s cycle) instead of strobing past.
    """
    entry = effect.get("entry", {}) if isinstance(effect, Mapping) else {}
    exit_part = effect.get("exit", {}) if isinstance(effect, Mapping) else {}
    kind = str(entry.get("type") or "none").casefold()
    animation_ms = int(entry.get("delay", 0)) + int(entry.get("duration", 180)) + int(exit_part.get("duration", 140))
    if any(word in kind for word in ("typewriter", "type", "scan", "reveal")):
        hold = 2400
    elif any(word in kind for word in ("glitch", "split", "chromatic")):
        hold = 2800
    elif any(word in kind for word in ("float", "fade", "soft")):
        hold = 3200
    elif any(word in kind for word in ("bounce", "punch", "pop", "impact", "shake")):
        hold = 2400
    else:
        hold = 2600
    # Guarantee the 2.5-4s loop contract regardless of authored animation
    # speed, while keeping very long animations from stacking extra seconds.
    return max(2100 - animation_ms, min(hold, 3600 - animation_ms))


class _PropertyChip(QWidget):
    """Square color swatch; multiple colors render the actual gradient."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors: list[str] = []
        self.setFixedSize(36, 36)

    def set_colors(self, colors: list[str] | None) -> None:
        self._colors = [str(color) for color in (colors or [])][:8]
        self.setVisible(bool(self._colors))
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._colors:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 7, 7)
        painter.setClipPath(path)
        if len(self._colors) == 1:
            painter.fillRect(rect, QColor(self._colors[0]))
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            for index, color in enumerate(self._colors):
                gradient.setColorAt(index / max(1, len(self._colors) - 1), QColor(color))
            painter.fillRect(rect, QBrush(gradient))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(0, 0, 0, 110), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 7, 7)
        painter.end()


class StylePropertyRow(QFrame):
    """Collapsible visual-property row: title + summary, click to expand.

    High-frequency state lives on the row itself; the full parameter editor
    inside stays hidden until the row is clicked, so the Appearance section
    scans as five clear rows instead of a parameter matrix.
    """

    def __init__(self, title: str, parent=None, *, on_activate=None):
        super().__init__(parent)
        self._on_activate = on_activate
        self._exclusive_group: list[StylePropertyRow] | None = None
        self._tint_colors: list[str] = []
        self.setObjectName("stylePropertyRow")
        self.setProperty("expanded", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)
        header = QFrame()
        header.setObjectName("stylePropertyRowHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("stylePropertyRowTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        self.chip = _PropertyChip()
        header_layout.addWidget(self.chip)
        self.chevron = QLabel("▸")
        self.chevron.setObjectName("stylePropertyRowChevron")
        header_layout.addWidget(self.chevron)
        if on_activate is not None:
            self.chevron.setText("✎")
        outer.addWidget(header)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("stylePropertyRowSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setMinimumWidth(0)
        outer.addWidget(self.summary_label)
        self.content = QWidget()
        self.content.setObjectName("stylePropertyRowContent")
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setSpacing(8)
        self.content.hide()
        outer.addWidget(self.content)

    def set_exclusive_group(self, rows: list[StylePropertyRow] | None) -> None:
        self._exclusive_group = rows

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(tr(str(text)))

    def set_chip_colors(self, colors: list[str] | None) -> None:
        self._tint_colors = [str(color) for color in (colors or []) if QColor(str(color)).isValid()][:8]
        self.chip.set_colors(self._tint_colors)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # The chip owns the actual style color. Keep the surrounding control
        # on the shared surface, even for white or multicolor subtitle fills.

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded:
            for other in self._exclusive_group or ():
                if other is not self and other.content.isVisible():
                    other.set_expanded(False)
        self.content.setVisible(expanded)
        self.chevron.setText("▾" if expanded else "▸")
        if self.property("expanded") != expanded:
            self.setProperty("expanded", expanded)
            self.style().unpolish(self)
            self.style().polish(self)

    def toggle(self) -> None:
        self.set_expanded(not self.content.isVisible())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if callable(self._on_activate):
                self._on_activate()
                event.accept()
                return
            if not self.content.isVisible():
                self.toggle()
                event.accept()
                return
            content_top = self.content.mapTo(self, QPoint(0, 0)).y()
            if event.position().y() < content_top:
                self.toggle()
                event.accept()
                return
        super().mousePressEvent(event)


class StyleScopeSelector(QWidget):
    """Compact radio selector with the QComboBox API used by style persistence."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, str]] = []
        self._buttons: list[QRadioButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(8)
        self._layout.setVerticalSpacing(2)
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def addItem(self, label: str, data: str) -> None:
        index = len(self._items)
        self._items.append((label, data))
        button = bind_text(QRadioButton(), label)
        button.setObjectName("scopeOption")
        button.setFixedHeight(STYLE_FIELD_HEIGHT - 2)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bind_text(button, '应用到{label}', property='toolTip', label=label if hasattr(label, "source") else tr(label))
        button.toggled.connect(
            lambda checked, value=index: checked and self.currentIndexChanged.emit(value)
        )
        self._group.addButton(button, index)
        self._buttons.append(button)
        self._layout.addWidget(button, index // 2, index % 2)

    def retranslate_ui(self):
        for (label, _data), button in zip(self._items, self._buttons):
            bind_text(button, label)
            bind_text(button, '应用到{label}', property='toolTip', label=label if hasattr(label, "source") else tr(label))

    def currentIndex(self) -> int:
        return self._group.checkedId()

    def currentData(self) -> str | None:
        index = self.currentIndex()
        return self._items[index][1] if 0 <= index < len(self._items) else None

    def findData(self, data: str) -> int:
        return next((i for i, item in enumerate(self._items) if item[1] == data), -1)

    def setItemText(self, index: int, label: str) -> None:
        if 0 <= index < len(self._items):
            data = self._items[index][1]
            self._items[index] = (label, data)
            bind_text(self._buttons[index], label)

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)


class _StyleColorEdit(QLineEdit):
    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class _PresetManagerTree(QTreeWidget):
    select_all_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.select_all_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class StyleColorButton(QToolButton):
    """Compact color field that communicates color before technical values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("styleColorButton")
        self._color = QColor("#000000")
        self._fill_spec = FillSpec.solid("#FF000000")
        self._label = "黑色"
        self._enabled_state = True
        self.setMinimumHeight(STYLE_FIELD_HEIGHT - 2)
        self.setMaximumHeight(STYLE_FIELD_HEIGHT - 2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bind_text(self, '打开颜色选择器', property='toolTip')

    def set_color_value(self, value: str, label: str = "", enabled: bool = True) -> None:
        color = QColor(str(value or ""))
        self._color = color if color.isValid() else QColor("#000000")
        self._fill_spec = FillSpec.solid(
            self._color.name(QColor.NameFormat.HexArgb)
        )
        self._label = str(label or ("白色" if self._color.lightness() > 180 else "黑色"))
        self._enabled_state = bool(enabled)
        self.update()

    def set_fill_value(self, fill: FillSpec | Mapping[str, object] | str) -> None:
        self._fill_spec = FillSpec.from_value(fill)
        if self._fill_spec.kind == "solid":
            self._color = QColor(self._fill_spec.color)
            self._label = "纯色"
        else:
            first = self._fill_spec.stops[0] if self._fill_spec.stops else {"color": "#FFFFFFFF"}
            self._color = QColor(str(first.get("color") or "#FFFFFFFF"))
            self._label = "径向渐变" if self._fill_spec.kind == "radial-gradient" else "线性渐变"
        self._enabled_state = True
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        theme = theme_definition(theme_key())
        painter.setPen(QPen(QColor(theme.border_strong), 1))
        painter.setBrush(QColor(theme.input_surface or theme.surface_elevated))
        painter.drawRoundedRect(rect, 5, 5)
        swatch_size = min(27.0, max(24.0, rect.height() - 10.0))
        swatch = QRectF(
            rect.left() + 8,
            rect.center().y() - swatch_size / 2,
            swatch_size,
            swatch_size,
        )
        if not self._enabled_state:
            painter.setBrush(QColor("#ebe5d9"))
            painter.drawRoundedRect(swatch, 6, 6)
            painter.setPen(QColor("#8b8a83"))
            painter.drawLine(swatch.topLeft(), swatch.bottomRight())
            painter.drawLine(swatch.topRight(), swatch.bottomLeft())
        else:
            if self._fill_spec.kind != "solid":
                if self._fill_spec.kind == "radial-gradient":
                    gradient = QRadialGradient(swatch.center(), max(1.0, swatch.width() / 2))
                else:
                    gradient = QLinearGradient(swatch.left(), swatch.top(), swatch.right(), swatch.bottom())
                for stop in self._fill_spec.stops:
                    gradient.setColorAt(
                        max(0.0, min(1.0, float(stop.get("position", stop.get("pos", 0)) or 0))),
                        QColor(str(stop.get("color") or "#FFFFFFFF")),
                    )
                painter.setBrush(gradient)
                painter.drawRoundedRect(swatch, 6, 6)
            elif self._color.alpha() == 0:
                painter.setBrush(QColor("#e9e4d9"))
                painter.drawRoundedRect(swatch, 6, 6)
                painter.setBrush(QColor("#c9c3b7"))
                tile = 5
                for row in range(4):
                    for column in range(4):
                        if (row + column) % 2 == 0:
                            painter.drawRect(QRectF(swatch.left() + column * tile, swatch.top() + row * tile, tile, tile))
            else:
                painter.setBrush(self._color)
                painter.drawRoundedRect(swatch, 6, 6)
        painter.setPen(QColor(theme.text if self._enabled_state else theme.disabled))
        font = painter.font()
        font.setPointSize(9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(swatch.right() + 7, rect.top(), rect.width() - swatch.right() - 13, rect.height()), Qt.AlignmentFlag.AlignVCenter, self._label if self._enabled_state else "关闭")


class StylePreview(QWidget):
    """Small, deterministic preview of the currently edited ASS style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(78)
        self.setMaximumHeight(96)
        self._style = None
        self._gradient: dict | None = None
        self._glow: dict | None = None
        self._shadow: dict | None = None
        self._strokes: list[dict] = []
        self._decorations: list[dict] = []
        self._motion = validate_effect({"type": "none"})
        self._motion_clock = QElapsedTimer()
        self._motion_loop = False
        self._motion_hold = 420
        self._motion_timer = QTimer(self)
        self._motion_timer.setInterval(16)
        self._motion_timer.timeout.connect(self._motion_tick)
        bind_text(self, '当前字幕样式预览', property='toolTip')

    def set_style(self, style) -> None:
        self._style = copy.deepcopy(style) if style is not None else None
        self._resolved_face = None
        if style is not None:
            from .font_metadata import resolve_local_face
            self._resolved_face, warning = resolve_local_face(style.font_family,
                style.font_weight, style.font_style_name, style.bold,
                style.font_file, style.font_face_index)
            self.setToolTip(warning or f'{self._resolved_face.full_name} / {self._resolved_face.weight}')
        self.update()

    def set_gradient(self, gradient: dict | None) -> None:
        self._gradient = copy.deepcopy(gradient) if isinstance(gradient, dict) else None
        self.update()

    def set_glow(self, glow: dict | None) -> None:
        self._glow = copy.deepcopy(glow) if isinstance(glow, dict) and glow.get("enabled") else None
        self.update()

    def set_shadow(self, shadow: dict | None) -> None:
        self._shadow = copy.deepcopy(shadow) if isinstance(shadow, dict) else None
        self.update()

    def set_strokes(self, strokes: list[dict] | None) -> None:
        self._strokes = copy.deepcopy(strokes) if isinstance(strokes, list) else []
        self.update()

    def set_decorations(self, decorations: list[dict] | None) -> None:
        self._decorations = copy.deepcopy(decorations) if isinstance(decorations, list) else []
        self.update()

    def play_motion(self, effect, *, loop: bool = False, hold_ms: int | None = None) -> None:
        """Play one local sample without mutating the project or mpv state."""
        self._motion = validate_effect(effect)
        self._motion_loop = bool(loop)
        self._motion_hold = motion_preview_pacing(effect) if hold_ms is None else max(400, int(hold_ms))
        self._motion_clock.restart()
        self._motion_timer.start()
        self.update()

    def _motion_tick(self) -> None:
        entry = self._motion.get("entry", {"type": "none"})
        exit_part = self._motion.get("exit", {"type": "none"})
        duration = (
            int(entry.get("delay", 0)) + int(entry.get("duration", 0))
            + self._motion_hold + int(exit_part.get("duration", 0))
        )
        if self._motion_clock.elapsed() >= max(600, duration + 80):
            if self._motion_loop:
                self._motion_clock.restart()
            else:
                self._motion_timer.stop()
        self.update()

    def _motion_frame(self) -> tuple[float, float, float, float]:
        entry = self._motion.get("entry", {"type": "none"})
        effect_type = str(entry.get("type") or "none")
        if not self._motion_clock.isValid():
            return 1.0, 0.0, 0.0, 1.0
        delay = int(entry.get("delay", 0))
        duration = max(1, int(entry.get("duration", 180)))
        elapsed = self._motion_clock.elapsed()
        exit_part = self._motion.get("exit", {"type": "none"})
        exit_start = delay + (duration if effect_type != "none" else 0) + self._motion_hold
        if elapsed >= exit_start and str(exit_part.get("type") or "none") != "none":
            exit_duration = max(1, int(exit_part.get("duration", 140)))
            raw_exit = min(1.0, max(0.0, (elapsed - exit_start) / exit_duration))
            progress_exit = raw_exit ** max(0.1, float(exit_part.get("accel", 0.72)))
            exit_type = str(exit_part.get("type") or "none")
            opacity = 1.0 - progress_exit if exit_type in {"fade", "soft_fade", "scale"} else 1.0
            scale = 1.0 - 0.06 * progress_exit if exit_type == "scale" else 1.0
            return opacity, 0.0, 0.0, scale
        if effect_type == "none":
            return 1.0, 0.0, 0.0, 1.0
        raw = min(1.0, max(0.0, (elapsed - delay) / duration))
        accel = max(0.1, float(entry.get("accel", 0.72)))
        progress = raw ** accel
        strength = STRENGTH_PRESETS.get(str(entry.get("strength") or "medium"), 1.0)
        opacity, scale, offset_x, offset_y = 1.0, 1.0, 0.0, 0.0
        if effect_type in {"fade", "soft_fade", "blur_reveal"}:
            opacity = progress
        if effect_type in {"pop", "scale", "soft_pop", "punch", "bounce_lite", "emphasis"}:
            start = float(entry.get("scale_from", 95)) / 100.0
            overshoot = float(entry.get("overshoot", 103)) / 100.0
            if effect_type in {"pop", "scale"}:
                scale = start + (1.0 - start) * progress
            elif raw < 0.62:
                phase = progress / max(0.001, 0.62 ** accel)
                scale = start + (overshoot - start) * min(1.0, phase)
            else:
                settle = (raw - 0.62) / 0.38
                scale = overshoot + (1.0 - overshoot) * (settle ** 0.7)
        if effect_type in POSITION_EFFECT_TYPES:
            offset_x = float(entry.get("offset_x", 0)) * strength * (1.0 - progress) * 0.36
            offset_y = float(entry.get("offset_y", 0)) * strength * (1.0 - progress) * 0.36
            if effect_type != "slide":
                opacity = progress
        return opacity, offset_x, offset_y, scale

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#343a38"))
        painter.setPen(QPen(QColor("#5e6963"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if self._style is None:
            return
        style = self._style
        face = self._resolved_face
        font = QFont(face.full_name)
        font.setStyleName(face.style)
        font.setPointSizeF(max(10.0, min(30.0, float(style.font_size) * 0.42)))
        font.setWeight(QFont.Weight(face.weight))
        font.setItalic(bool(style.italic))
        # Chinese-first sample catches the common font fallback issue while
        # retaining Latin and numeric glyphs in the same compact preview.
        text = tr("示例字幕 Aa 123")
        # Keep the preview useful for oversized ASS sizes such as 500px.
        while font.pointSizeF() > 10 and QFontMetrics(font).horizontalAdvance(text) > self.width() - 24:
            font.setPointSizeF(font.pointSizeF() - 1)
        painter.setFont(font)
        bounds = painter.fontMetrics().boundingRect(text)
        x = (self.width() - bounds.width()) // 2
        y = (self.height() + bounds.height()) // 2 - 3
        opacity, offset_x, offset_y, scale = self._motion_frame()
        painter.save()
        painter.setOpacity(opacity)
        painter.translate(self.width() / 2 + offset_x, self.height() / 2 + offset_y)
        painter.scale(scale, scale)
        painter.translate(-self.width() / 2, -self.height() / 2)
        fill = self._gradient or style.primary_color
        outline = _preview_color(style.outline_color, "#FF000000")
        if os.environ.get("TWOBYTEASR_DEBUG_STYLE_PREVIEW") == "1":
            print(
                "[STYLE_PREVIEW]"
                f" fill_raw={style.primary_color!r} gradient={bool(self._gradient)}"
                f" resolved={_preview_color(style.primary_color, '#FFFFFFFF').name(QColor.NameFormat.HexArgb)}"
                f" outline={outline.name(QColor.NameFormat.HexArgb)}",
                flush=True,
            )
        if self._shadow is not None and self._shadow.get('enabled'):
            from .advanced_live_renderer import _draw_shadow_path
            spec = self._shadow
            sample_scale = font.pointSizeF() / max(1., float(style.font_size))
            shadow_path = QPainterPath()
            shadow_path.addText(QPointF(x + float(spec.get('offset_x', 0))*sample_scale,
                                       y + float(spec.get('offset_y', 0))*sample_scale), font, text)
            shadow_color = _preview_color(spec.get('color', '#FF000000'), '#FF000000')
            shadow_color.setAlphaF(shadow_color.alphaF() * float(spec.get('opacity', 1)))
            _draw_shadow_path(painter, shadow_path, color=shadow_color,
                radius=float(spec.get('blur_radius', 0))*sample_scale,
                spread=float(spec.get('spread', 0))*sample_scale)
        elif self._shadow is None and float(style.shadow or 0) > 0:
            shadow_path = QPainterPath()
            shadow_path.addText(QPointF(x + 2, y + 2), font, text)
            shadow_color = QColor(0, 0, 0, 150)
            painter.fillPath(shadow_path, QBrush(shadow_color))
        strokes = self._strokes or [{"color": outline.name(QColor.NameFormat.HexArgb), "width": float(style.outline_width or 0)}]
        for stroke in strokes:
            stroke_color = QColor(str(stroke.get("color", outline.name(QColor.NameFormat.HexArgb))))
            stroke_color.setAlphaF(max(0.0, min(1.0, float(stroke.get("opacity", 1.0)))))
            render_style_sample(
                painter,
                text=text,
                font=font,
                baseline=QPointF(x, y),
                fill=fill,
                outline=stroke_color,
                outline_width=max(1.0, float(stroke.get("width", style.outline_width or 0)) * 0.55),
                rect=QRectF(self.rect()),
                opacity=opacity,
                glow=self._glow,
            )
        if self._decorations:
            deco_color = QColor("#20D9FF")
            deco_color.setAlpha(150)
            painter.setPen(QPen(deco_color, 1.2))
            margin = 16
            if any(str(item.get("type")) in {"corner_brackets", "tech_corner"} for item in self._decorations if isinstance(item, dict)):
                painter.drawLine(margin, 18, margin + 12, 18)
                painter.drawLine(margin, 18, margin, 28)
                painter.drawLine(self.width() - margin, self.height() - 18, self.width() - margin - 12, self.height() - 18)
                painter.drawLine(self.width() - margin, self.height() - 18, self.width() - margin, self.height() - 28)
            if any(str(item.get("type")) == "underline" for item in self._decorations if isinstance(item, dict)):
                painter.drawLine(x, y + 5, x + bounds.width(), y + 5)
        painter.restore()
