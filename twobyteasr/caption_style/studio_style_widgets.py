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
    QPalette,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QStyle, QStyleOptionComboBox, QStylePainter,
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
from ..studio.studio_helpers import _preview_color, render_style_sample
from ..design.studio_theme import STYLE_FIELD_HEIGHT, StudioComboBox
from ..design.theme_manager import theme_key
from ..design.ui_theme import theme_definition


class CompactLayerComboBox(StudioComboBox):
    """A full-hit-area language picker sized from the current UI font."""
    def sizeHint(self):
        result=super().sizeHint()
        width=max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())),default=0)
        # Keep label padding and the themed arrow separate, including the
        # larger UI-font modes. This remains compact beside the preset.
        result.setWidth(width+56)
        return result

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self,event):
        option=QStyleOptionComboBox();self.initStyleOption(option)
        text=option.currentText;option.currentText=''
        painter=QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox,option)
        rect=self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,option,
                                        QStyle.SubControl.SC_ComboBoxEditField,self)
        painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,text)

from ..i18n import bind_text, tr

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


# One grid for the whole style tab (2026-10-17, user: "文字元素不太整齊"):
# every left label shares one column (at least STYLE_LABEL_WIDTH, wider for
# longer translations) and every control starts STYLE_LABEL_GAP after it;
# on/off switches sit in one trailing slot.  Property rows indent their
# title by STYLE_ROW_INSET (3 px accent border + 10 px margin), so labels
# outside a section pass that inset as ``extra`` to end on the same line.
STYLE_LABEL_WIDTH = 40
STYLE_LABEL_MAX_WIDTH = 112
STYLE_LABEL_GAP = 8
STYLE_ROW_INSET = 13
STYLE_SWITCH_SLOT = 34


class StyleGridLabel(QLabel):
    """Left-column label; tells its column when its (translated) text changes."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setObjectName("stylePropertyRowTitle")
        self._label_column = None

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        super().setText(text)
        column = getattr(self, "_label_column", None)
        if column is not None:
            column.refresh()


class StyleLabelColumn:
    """Keeps every left label of the style tab as wide as the widest one."""

    def __init__(self) -> None:
        self._labels: list[tuple[QLabel, int]] = []
        self._rows: list[StylePropertyRow] = []
        self._indents: list[tuple[QWidget, int]] = []
        self.width = STYLE_LABEL_WIDTH

    def control_indent(self, *, extra: int = 0) -> QWidget:
        """Empty label cell: a widget after it starts in the control column."""
        indent = QWidget()
        self._indents.append((indent, int(extra)))
        indent.setFixedWidth(self.width + int(extra) + STYLE_LABEL_GAP)
        return indent

    def add(self, label: QLabel, *, extra: int = 0) -> QLabel:
        label._label_column = self
        self._labels.append((label, int(extra)))
        self.refresh()
        return label

    def add_row(self, row: "StylePropertyRow") -> "StylePropertyRow":
        self._rows.append(row)
        self.add(row.title_label)
        return row

    @staticmethod
    def _text_width(label: QLabel) -> int:
        # Measured with the style-sheet font (13 px, semibold) so the column
        # is right before the label is first polished and shown.
        font = QFont(label.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.DemiBold)
        return QFontMetrics(font).horizontalAdvance(label.text()) + 4

    def refresh(self) -> None:
        live = []
        for label, extra in self._labels:
            try:
                label.text()
            except RuntimeError:  # deleted with its page
                continue
            live.append((label, extra))
        self._labels = live
        widest = max((self._text_width(label) for label, _extra in live), default=0)
        self.width = max(STYLE_LABEL_WIDTH, min(STYLE_LABEL_MAX_WIDTH, widest))
        for label, extra in live:
            label.setFixedWidth(self.width + extra)
        for indent, extra in tuple(self._indents):
            try:
                indent.setFixedWidth(self.width + extra + STYLE_LABEL_GAP)
            except RuntimeError:
                self._indents.remove((indent, extra))
        for row in self._rows:
            try:
                row.set_label_width(self.width)
            except RuntimeError:
                continue


class ElidedLabel(QLabel):
    """Single-line label that ends in "…" instead of cutting a glyph."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._apply_elision()

    def text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        width = max(0, self.contentsRect().width())
        shown = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, width)
        if shown != super().text():
            super().setText(shown)


class ElidedComboBox(StudioComboBox):
    """Combo box whose current item ends in "…" when narrow; Qt clips it
    mid-glyph. The popup list still shows every full name."""

    def set_display_label(self,text,modified=False):
        self._display_key=(self.currentData(),self.currentText())
        self._display_label=str(text);self._display_modified=bool(modified)
        self.setProperty('presetModified',bool(modified))
        self.setAccessibleDescription(str(text)+(' · 已修改'if modified else ''))
        self.update()

    def _display_parts(self):
        if getattr(self,'_display_key',None)==(self.currentData(),self.currentText()):
            return self._display_label,self._display_modified
        return self.currentText(),False

    def display_text_source(self):
        return self._display_parts()[0]

    def displayed_text(self) -> str:
        from PySide6.QtWidgets import QStyle, QStyleOptionComboBox

        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        field = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, self)
        icon = option.iconSize.width() + 4 if not option.currentIcon.isNull() else 0
        text,modified=self._display_parts()
        return self.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, max(0, field.width() - icon - 4 - (12 if modified else 0)))

    def paintEvent(self, event) -> None:
        from PySide6.QtWidgets import QStyle, QStyleOptionComboBox, QStylePainter

        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText=''
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        option.currentText = self.displayed_text()
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)
        if self._display_parts()[1]:
            field=self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,option,
                                              QStyle.SubControl.SC_ComboBoxEditField,self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(self.palette().color(QPalette.ColorRole.Link))
            painter.drawEllipse(QPointF(field.right()-4,field.center().y()),2.5,2.5)


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
        outer.setContentsMargins(10, 10, 8, 10)
        outer.setSpacing(4)
        header = QFrame()
        header.setObjectName("stylePropertyRowHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        self.title_label = StyleGridLabel(title)
        self._label_width = STYLE_LABEL_WIDTH
        header_layout.addWidget(self.title_label)
        # Inline controls and summary (M16 one-line rows); empty otherwise.
        self._inline = QHBoxLayout()
        self._inline.setContentsMargins(0, 0, 0, 0)
        self._inline.setSpacing(6)
        header_layout.addLayout(self._inline)
        self.inline_summary = ElidedLabel("")
        self.inline_summary.setObjectName("stylePropertyRowSummary")
        self.inline_summary.setMinimumWidth(0)
        self.inline_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.inline_summary.hide()
        header_layout.addWidget(self.inline_summary, 1)
        self._header_stretch = header_layout.count()
        header_layout.addStretch(1)
        self._header_layout = header_layout
        self._header = header
        self.chip = _PropertyChip()
        header_layout.addWidget(self.chip)
        self.chevron = QLabel("▸")
        self.chevron.setObjectName("stylePropertyRowChevron")
        header_layout.addWidget(self.chevron)
        if on_activate is not None:
            self.chevron.setText("✎")
        # On/off switch slot, kept (empty) on every inline row so swatches,
        # captions and chevrons line up row to row.
        self.trailing = QWidget()
        self.trailing.setObjectName("stylePropertyRowTrailing")
        trailing_layout = QHBoxLayout(self.trailing)
        trailing_layout.setContentsMargins(0, 0, 0, 0)
        trailing_layout.setSpacing(0)
        self.trailing.setFixedWidth(STYLE_SWITCH_SLOT)
        self.trailing.hide()
        header_layout.addWidget(self.trailing)
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

    def inline_layout(self) -> QHBoxLayout:
        return self._inline

    def set_trailing(self, widget: QWidget) -> None:
        """Put the row's on/off switch in the shared trailing slot."""
        self.trailing.layout().addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def set_inline(self, inline: bool = True, *, summary: bool = True, expandable: bool = True) -> None:
        """One line: title, the property's own controls, a short summary and
        (only when there is more) a chevron (2026-10-09, M16, user)."""
        self._inline_mode = bool(inline)
        self._expandable = bool(expandable)
        self._header_layout.setSpacing(STYLE_LABEL_GAP)
        self.trailing.setVisible(bool(inline))
        self.set_label_width(self._label_width)
        self.summary_label.setVisible(not inline)
        self.inline_summary.setVisible(inline and summary)
        self.chip.set_colors([])
        self.chip.setVisible(False)
        # The summary takes the spare width when it is shown.
        self._header_layout.setStretch(self._header_stretch, 0 if inline and summary else 1)
        self.chevron.setVisible(expandable or callable(self._on_activate))
        if inline and expandable and not callable(self._on_activate):
            self.chevron.setText("更多 ▸")
        layout = self.layout()
        layout.setContentsMargins(10, 5, 8, 5)

    def set_label_width(self, width: int) -> None:
        """Title column width; expanded editors start in the control column."""
        self._label_width = int(width)
        inline = getattr(self, "_inline_mode", False)
        self.title_label.setFixedWidth(self._label_width if inline else self.title_label.sizeHint().width())
        self._content_layout.setContentsMargins(
            (self._label_width + STYLE_LABEL_GAP) if inline else 4, 4, 0, 4)

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(tr(str(text)))
        self.inline_summary.setText(tr(str(text)))

    def set_chip_colors(self, colors: list[str] | None) -> None:
        self._tint_colors = [str(color) for color in (colors or []) if QColor(str(color)).isValid()][:8]
        if getattr(self, "_inline_mode", False):
            # The inline swatch already shows the colour.
            self.update()
            return
        self.chip.set_colors(self._tint_colors)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # 2026-10-18 (user): an active property shows its color at the row's
        # right edge, fading to transparent (it was a left-edge tint before
        # 2026-09). Rows that are off pass no colors.
        if not self._tint_colors or not getattr(self, "_inline_mode", False):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Only the row's own line: an expanded editor below stays on the surface.
        header = self._header.geometry()
        rect = QRectF(0.0, 0.0, float(self.width()), float(min(self.height(), header.bottom() + header.top() + 1)))
        gradient = QLinearGradient(rect.topRight(), rect.topLeft())
        colors = [QColor(value) for value in self._tint_colors]
        reach = 0.6  # share of the row width the fade covers
        if len(colors) == 1:
            colors = colors * 2
        # Black on a light theme or white on a dark one would read as a grey
        # band; scale the strength down by the contrast with the panel.
        surface = QColor(theme_definition(theme_key()).surface)
        for index, color in enumerate(colors):
            tinted = QColor(color)
            contrast = abs(tinted.lightnessF() - surface.lightnessF())
            strength = 1.0 - 0.62 * max(0.0, contrast - 0.25) / 0.75
            tinted.setAlpha(int((46 * (1.0 - index / max(1, len(colors))) + 18) * strength))
            gradient.setColorAt(reach * 0.5 * index / max(1, len(colors) - 1), tinted)
        clear = QColor(colors[-1])
        clear.setAlpha(0)
        gradient.setColorAt(reach, clear)
        gradient.setColorAt(1.0, clear)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRect(rect)
        painter.end()

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded:
            for other in self._exclusive_group or ():
                if other is not self and other.content.isVisible():
                    other.set_expanded(False)
        self.content.setVisible(expanded)
        if getattr(self, "_inline_mode", False) and not callable(self._on_activate):
            self.chevron.setText("收起 ▾" if expanded else "更多 ▸")
        else:
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
            if not getattr(self, "_expandable", True):
                super().mousePressEvent(event)
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


class _ScopeButton(QRadioButton):
    def hitButton(self, pos):
        return self.rect().contains(pos)


class StyleScopeSelector(QWidget):
    """Compact radio selector with the QComboBox API used by style persistence."""

    currentIndexChanged = Signal(int)
    activated = Signal(int)

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
        self._short: dict[str, str] = {}
        self._activating = False
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_single_row(self, short_labels: Mapping[str, str]) -> None:
        """All options on one row with short labels; the full label stays in
        the tooltip (2026-10-09, M16: scope sits at the top of the panel)."""
        self._short = dict(short_labels)
        self._layout.setHorizontalSpacing(4)
        for index, button in enumerate(self._buttons):
            self._layout.addWidget(button, 0, index)
            # Chips are as tall as the one-row selector.
            button.setFixedHeight(STYLE_FIELD_HEIGHT - 6)
            self._apply_label(index)
        self.setMinimumHeight(0)
        self.setFixedHeight(STYLE_FIELD_HEIGHT - 6)

    def _apply_label(self, index: int) -> None:
        label, data = self._items[index]
        button = self._buttons[index]
        full = label if hasattr(label, "source") else tr(label)
        if data in self._short:
            import re
            count = re.search(r"\d+", str(full))
            if count:
                bind_text(button, '{label} {count}', label=tr(self._short[data]), count=count.group(0))
            else:
                bind_text(button, self._short[data])
        else:
            bind_text(button, label)
        bind_text(button, '应用到{label}', property='toolTip', label=full)

    def addItem(self, label: str, data: str) -> None:
        index = len(self._items)
        self._items.append((label, data))
        button = bind_text(_ScopeButton(), self._short.get(data, label))
        button.setObjectName("scopeOption")
        button.setFixedHeight(STYLE_FIELD_HEIGHT - 2)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bind_text(button, '应用到{label}', property='toolTip', label=label if hasattr(label, "source") else tr(label))
        button.toggled.connect(
            lambda checked, value=index: checked and self.currentIndexChanged.emit(value)
        )
        button.clicked.connect(lambda _checked=False, value=index: self.activated.emit(value))
        button.pressed.connect(lambda: setattr(self, '_activating', True))
        button.released.connect(lambda: setattr(self, '_activating', False))
        self._group.addButton(button, index)
        self._buttons.append(button)
        self._layout.addWidget(button, index // 2, index % 2)

    def retranslate_ui(self):
        for index in range(len(self._buttons)):
            self._apply_label(index)

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
            self._apply_label(index)

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
        self._mixed_colors = ()
        self.setToolTip(self._color.name(QColor.NameFormat.HexArgb).upper() if color.isValid() else '无效颜色')
        self.setAccessibleName(label or self.toolTip())
        self.update()

    def set_mixed_colors(self, values) -> None:
        self._mixed_colors = tuple(sorted(values))
        self._label = '混合'
        self.setToolTip('混合描边/颜色：' + ' / '.join(self._mixed_colors))
        self.setAccessibleName('混合颜色')
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
        self._mixed_colors = ()
        self.update()

    def paintEvent(self, event) -> None:
        # 2026-10-18 (user: "颜色卡外面还有一层框实在太难看"): the color is the
        # control itself; no field around an inner chip. A switched-off
        # property (background) keeps its color, dimmed.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        theme = theme_definition(theme_key())
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        radius = 7.0
        if not self._enabled_state:
            painter.setOpacity(0.38)
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        if getattr(self, '_mixed_colors', ()):
            colors = self._mixed_colors
            for i, color in enumerate(colors):
                painter.fillRect(QRectF(rect.left()+rect.width()*i/len(colors), rect.top(),
                    rect.width()/len(colors)+1, rect.height()), QColor(color))
            painter.fillRect(rect, QColor(0, 0, 0, 70))
            painter.setPen(QColor('white'))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, '混合')
        elif self._fill_spec.kind != "solid":
            if self._fill_spec.kind == "radial-gradient":
                gradient = QRadialGradient(rect.center(), max(1.0, max(rect.width(), rect.height()) / 2))
            else:
                gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.bottom())
            for stop in self._fill_spec.stops:
                gradient.setColorAt(
                    max(0.0, min(1.0, float(stop.get("position", stop.get("pos", 0)) or 0))),
                    QColor(str(stop.get("color") or "#FFFFFFFF")),
                )
            painter.fillRect(rect, QBrush(gradient))
        else:
            if self._color.alpha() < 255:
                # Checkerboard behind see-through colors.
                painter.fillRect(rect, QColor("#e9e4d9"))
                tile = 6.0
                y = rect.top()
                row = 0
                while y < rect.bottom():
                    x = rect.left() + (tile if row % 2 else 0.0)
                    while x < rect.right():
                        painter.fillRect(QRectF(x, y, tile, tile), QColor("#c9c3b7"))
                        x += tile * 2
                    y += tile
                    row += 1
            painter.fillRect(rect, self._color)
        painter.setClipping(False)
        painter.setOpacity(1.0)
        hovered = self.underMouse() and self.isEnabled()
        painter.setPen(QPen(QColor(theme.accent if hovered else theme.border_strong), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()


class StylePreview(QWidget):
    """Small, deterministic preview of the currently edited ASS style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(78)
        self.setMaximumHeight(96)
        self._sample_text = ""
        self.sample_toggle = None
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

    def enable_sample_toggle(self) -> None:
        """'Aa' switches between the selected line and the fixed sample
        (2026-10-09, M16, user: preview what is being edited first)."""
        button = QToolButton(self)
        button.setObjectName("stylePreviewSample")
        button.setText("Aa")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        bind_text(button, '切换为示例字幕 Aa 123（默认预览当前选中字幕）', property='toolTip')
        button.toggled.connect(lambda _checked: self.update())
        button.resize(30, 22)
        self.sample_toggle = button
        self._place_sample_toggle()

    def _place_sample_toggle(self) -> None:
        if self.sample_toggle is not None:
            self.sample_toggle.move(self.width() - self.sample_toggle.width() - 6, 5)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_sample_toggle()

    def set_sample_text(self, text: str) -> None:
        text = " ".join(str(text or "").split())
        if text != self._sample_text:
            self._sample_text = text
            self.update()

    def display_text(self) -> str:
        if self.sample_toggle is not None and not self.sample_toggle.isChecked() and self._sample_text:
            return self._sample_text
        return tr("示例字幕 Aa 123")

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
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QLinearGradient
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        theme = theme_definition(theme_key())
        stage = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        backdrop = QLinearGradient(stage.topLeft(), stage.bottomRight())
        backdrop.setColorAt(0.0, QColor("#4a4458"))
        backdrop.setColorAt(1.0, QColor("#2c3440"))
        stage_path = QPainterPath()
        stage_path.addRoundedRect(stage, 10, 10)
        painter.fillPath(stage_path, backdrop)
        painter.setPen(QPen(QColor(theme.border_strong), 1))
        painter.drawPath(stage_path)
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
        text = self.display_text()
        room = self.width() - 24 - (40 if self.sample_toggle is not None else 0)
        # Keep the preview useful for oversized ASS sizes such as 500px.
        while font.pointSizeF() > 10 and QFontMetrics(font).horizontalAdvance(text) > room:
            font.setPointSizeF(font.pointSizeF() - 1)
        if QFontMetrics(font).horizontalAdvance(text) > room:
            text = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, max(20, room))
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
            from ..rendering.advanced_live_renderer import _draw_shadow_path
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
