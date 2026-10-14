# SPDX-License-Identifier: GPL-3.0-only
"""Appearance picker: theme cards that paint a miniature of each interface.

2026-10-14 (user: "下拉列表裡是否可以有更直觀的視覺預覽"): the plain theme
combo became grouped cards (light / dark / high contrast).  Each card paints
its own theme's window, sidebar selection, card, input, buttons, status dots
and timeline, so the choice is made by looking, not by reading names.  The
card chrome (border, selection ring, text) follows the *active* theme, which
the settings dialog switches live while a card is chosen.

The gallery keeps the small combo-like API the settings code and audits use
(``currentData``, ``currentText``, ``findData``, ``setCurrentIndex``).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .theme_manager import theme_key
from .ui_theme import (THEME_FAMILIES, ThemeDefinition, blend_hex, ordered_themes, theme_definition,
                       theme_display_label, theme_family_label, theme_mood)
from .ui_zoom import px

CARD_MIN_WIDTH = 164
CARD_GAP = 12
MAX_COLUMNS = 3


def _color(value: str, alpha: int | None = None) -> QColor:
    color = QColor(value)
    if alpha is not None:
        color.setAlpha(alpha)
    return color


def _bar(painter: QPainter, x: float, y: float, width: float, height: float, color: str) -> None:
    if width <= 0 or height <= 0:
        return
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_color(color))
    painter.drawRoundedRect(QRectF(x, y, width, height), height / 2, height / 2)


def paint_theme_miniature(painter: QPainter, rect: QRectF, theme: ThemeDefinition) -> None:
    """A tiny, faithful sketch of the app in ``theme`` (window, nav, card, timeline)."""
    from .timeline_theme import timeline_palette

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    radius = max(4.0, rect.height() * 0.07)
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(clip)
    painter.fillRect(rect, _color(theme.app_background))
    w, h = rect.width(), rect.height()
    x0, y0 = rect.left(), rect.top()
    unit = h / 100.0

    # Title bar with a brand mark.
    title_h = 13 * unit
    painter.fillRect(QRectF(x0, y0, w, title_h), _color(theme.shell))
    painter.fillRect(QRectF(x0, y0 + title_h - 1, w, 1), _color(theme.shell_border))
    mark = 5.5 * unit
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_color(theme.accent))
    painter.drawRoundedRect(QRectF(x0 + 5 * unit, y0 + (title_h - mark) / 2, mark, mark), 1.5, 1.5)
    _bar(painter, x0 + 13 * unit, y0 + title_h / 2 - 1.2 * unit, w * 0.16, 2.4 * unit, theme.text_secondary)

    # Sidebar: one selected item (brand wash + accent bar), two quiet ones.
    side_w = w * 0.21
    painter.fillRect(QRectF(x0, y0 + title_h, side_w, h - title_h), _color(theme.panel))
    painter.fillRect(QRectF(x0 + side_w - 1, y0 + title_h, 1, h - title_h), _color(theme.border))
    item_y = y0 + title_h + 6 * unit
    for index in range(4):
        top = item_y + index * 11 * unit
        if index == 0:
            painter.setBrush(_color(theme.accent_tint))
            painter.drawRoundedRect(QRectF(x0 + 3 * unit, top - 2.5 * unit, side_w - 6 * unit, 8 * unit), 2, 2)
            painter.fillRect(QRectF(x0 + 3 * unit, top - 2.5 * unit, 1.6 * unit, 8 * unit), _color(theme.accent))
            _bar(painter, x0 + 7 * unit, top, side_w * 0.5, 2.6 * unit, theme.text)
        else:
            _bar(painter, x0 + 7 * unit, top, side_w * (0.55 - 0.08 * index), 2.6 * unit, theme.text_muted)

    # Timeline strip with three clips and the playhead.
    palette = timeline_palette(theme.key)
    strip_h = 21 * unit
    strip = QRectF(x0 + side_w, y0 + h - strip_h, w - side_w, strip_h)
    painter.fillRect(strip, _color(palette.background))
    painter.fillRect(QRectF(strip.left(), strip.top(), strip.width(), 1), _color(theme.border))
    clips = ((0.05, 0.27), (0.36, 0.25), (0.66, 0.29))
    for (start, length), speaker in zip(clips, palette.speaker_accents):
        clip_rect = QRectF(strip.left() + strip.width() * start, strip.top() + strip_h * 0.28,
                           strip.width() * length, strip_h * 0.46)
        speaker_color = QColor(speaker)
        painter.setBrush(palette.clip_fill(speaker_color))
        painter.setPen(QPen(palette.clip_border(speaker_color), 1))
        painter.drawRoundedRect(clip_rect, 2, 2)
        _bar(painter, clip_rect.left() + 3 * unit, clip_rect.center().y() - 0.9 * unit,
             clip_rect.width() * 0.5, 1.8 * unit, palette.clip_text)
    head_x = strip.left() + strip.width() * 0.6
    painter.setPen(QPen(_color(palette.playhead), max(1.2, 0.9 * unit)))
    painter.drawLine(QPointF(head_x, strip.top() + 1), QPointF(head_x, strip.bottom()))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_color(palette.playhead))
    tip = 2.6 * unit
    painter.drawPolygon([QPointF(head_x - tip, strip.top() + 1), QPointF(head_x + tip, strip.top() + 1),
                         QPointF(head_x, strip.top() + 1 + tip * 1.4)])

    # Content card: heading, text lines, status dots, an input and two buttons.
    left = x0 + side_w + 6 * unit
    top = y0 + title_h + 6 * unit
    card = QRectF(left, top, x0 + w - 6 * unit - left, strip.top() - 5 * unit - top)
    if card.height() > 20 * unit:
        painter.setBrush(_color(theme.surface))
        painter.setPen(QPen(_color(theme.border), 1))
        painter.drawRoundedRect(card, 3.5, 3.5)
        pad = 5 * unit
        cx, cy, cw = card.left() + pad, card.top() + pad, card.width() - 2 * pad
        _bar(painter, cx, cy, cw * 0.42, 3.4 * unit, theme.text)
        for index, status in enumerate((theme.success, theme.warning, theme.danger)):
            painter.setBrush(_color(status))
            dot = 3.6 * unit
            painter.drawEllipse(QRectF(card.right() - pad - (index + 1) * dot * 1.7, cy - 0.1 * unit, dot, dot))
        _bar(painter, cx, cy + 7 * unit, cw * 0.7, 2.4 * unit, theme.text_secondary)
        _bar(painter, cx, cy + 12 * unit, cw * 0.5, 2.4 * unit, theme.text_muted)
        row_y = card.bottom() - pad - 9 * unit
        field = QRectF(cx, row_y, cw * 0.46, 9 * unit)
        painter.setBrush(_color(theme.input_surface))
        painter.setPen(QPen(_color(theme.border_strong), 1))
        painter.drawRoundedRect(field, 2, 2)
        _bar(painter, field.left() + 2.5 * unit, field.center().y() - 0.9 * unit, field.width() * 0.4, 1.8 * unit,
             theme.text_muted)
        primary = QRectF(card.right() - pad - cw * 0.24, row_y, cw * 0.24, 9 * unit)
        painter.setBrush(_color(theme.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(primary, 2, 2)
        _bar(painter, primary.left() + primary.width() * 0.25, primary.center().y() - 0.9 * unit,
             primary.width() * 0.5, 1.8 * unit, theme.text_on_accent)
        secondary = QRectF(primary.left() - 3 * unit - cw * 0.2, row_y, cw * 0.2, 9 * unit)
        painter.setBrush(_color(theme.surface_elevated))
        painter.setPen(QPen(_color(theme.border_strong), 1))
        painter.drawRoundedRect(secondary, 2, 2)
        _bar(painter, secondary.left() + secondary.width() * 0.25, secondary.center().y() - 0.9 * unit,
             secondary.width() * 0.5, 1.8 * unit, theme.text_secondary)
    painter.restore()


class ThemeCard(QAbstractButton):
    """One checkable theme card: miniature on top, name and mood below."""

    def __init__(self, theme: ThemeDefinition, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("themeCard")
        self.setProperty("themeKey", theme.key)
        self.setProperty("i18nUserText", True)  # retranslate_ui owns the name
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        name, mood = theme_display_label(self.theme), theme_mood(self.theme)
        self.setText(name)
        self.setAccessibleName(name)
        self.setAccessibleDescription(mood)
        self.setToolTip(f"{name}\n{mood}")
        self.update()

    def keyPressEvent(self, event) -> None:
        # Arrows only move focus (the gallery handles them); Qt's exclusive
        # buttons would click each neighbour and re-theme the app per key.
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            event.ignore()
            return
        super().keyPressEvent(event)

    def _preview_height(self) -> int:
        return px(100)

    def _fonts(self) -> tuple[QFont, QFont]:
        name_font = QFont(self.font())
        name_font.setPixelSize(px(14))
        name_font.setWeight(QFont.Weight.DemiBold)
        mood_font = QFont(self.font())
        mood_font.setPixelSize(px(12))
        mood_font.setWeight(QFont.Weight.Normal)
        return name_font, mood_font

    def _text_height(self) -> int:
        # From the real font metrics: CJK UI fonts run taller than 1.2x size.
        name_font, mood_font = self._fonts()
        return round(QFontMetricsF(name_font).height() + px(3) + 2 * QFontMetricsF(mood_font).lineSpacing() + px(4))

    def sizeHint(self) -> QSize:
        return QSize(px(CARD_MIN_WIDTH), self._preview_height() + px(8) + self._text_height() + px(14))

    def minimumSizeHint(self) -> QSize:
        return QSize(px(CARD_MIN_WIDTH - 20), self.sizeHint().height())

    def paintEvent(self, event) -> None:
        host = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        outer = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        checked, hovered = self.isChecked(), self.underMouse() or self.isDown()
        fill = blend_hex(host.surface_elevated, host.accent, 0.08) if checked else (
            host.selected if hovered else host.surface_elevated)
        edge = host.accent if checked else (host.control_border_hover if hovered else host.border)
        painter.setPen(QPen(_color(edge), 2.0 if checked else 1.0))
        painter.setBrush(_color(fill))
        painter.drawRoundedRect(outer, px(10), px(10))
        if self.hasFocus() and not checked:
            painter.setPen(QPen(_color(host.focus), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(outer.adjusted(2, 2, -2, -2), px(8), px(8))

        pad = px(8)
        preview = QRectF(pad, pad, self.width() - 2 * pad, self._preview_height())
        paint_theme_miniature(painter, preview, self.theme)
        painter.setPen(QPen(_color(host.border), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(preview, max(4.0, preview.height() * 0.07), max(4.0, preview.height() * 0.07))

        if checked:  # check badge on the miniature's corner
            size = px(20)
            badge = QRectF(preview.right() - size - px(5), preview.top() + px(5), size, size)
            painter.setPen(QPen(_color(host.surface_elevated), 2))
            painter.setBrush(_color(host.accent))
            painter.drawEllipse(badge)
            tick = QPainterPath(QPointF(badge.left() + size * 0.28, badge.top() + size * 0.52))
            tick.lineTo(badge.left() + size * 0.44, badge.top() + size * 0.68)
            tick.lineTo(badge.left() + size * 0.73, badge.top() + size * 0.35)
            pen = QPen(_color(host.text_on_accent), max(1.6, size * 0.11))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(tick)

        text_left = pad + px(2)
        text_width = self.width() - 2 * text_left
        name_font, mood_font = self._fonts()
        painter.setFont(name_font)
        painter.setPen(_color(host.text))
        name_metrics = QFontMetricsF(name_font)
        name_top = preview.bottom() + px(8)
        name = name_metrics.elidedText(self.text(), Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(QRectF(text_left, name_top, text_width, name_metrics.height()),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)

        painter.setFont(mood_font)
        painter.setPen(_color(host.text_muted))
        mood_top = name_top + name_metrics.height() + px(3)
        self._draw_wrapped(painter, mood_font, self.accessibleDescription(),
                           QRectF(text_left, mood_top, text_width, self.height() - mood_top - px(6)))

    @staticmethod
    def _draw_wrapped(painter: QPainter, font: QFont, text: str, box: QRectF, max_lines: int = 2) -> None:
        """Up to two wrapped lines; the last one is elided when the text is longer."""
        metrics = QFontMetricsF(font)
        layout = QTextLayout(text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        lines = []
        while len(lines) < max_lines:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(box.width())
            lines.append((line.textStart(), line.textLength()))
        layout.endLayout()
        y = box.top()
        for index, (start, length) in enumerate(lines):
            piece = text[start:start + length].rstrip()
            if index == len(lines) - 1 and start + length < len(text):
                piece = metrics.elidedText(text[start:], Qt.TextElideMode.ElideRight, box.width())
            painter.drawText(QRectF(box.left(), y, box.width(), metrics.height()),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), piece)
            y += metrics.lineSpacing()


class ThemeGallery(QWidget):
    """Grouped theme cards with an exclusive selection and a combo-like API."""

    currentIndexChanged = Signal(int)
    themeChosen = Signal(str)  # user picked a different theme (click / keys)
    languageRefreshed = Signal()

    def __init__(self, current_key: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("themeGallery")
        self._themes = list(ordered_themes())
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._cards: list[ThemeCard] = []
        self._sections: list[tuple[str, QLabel, QGridLayout, list[ThemeCard]]] = []
        self._columns = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(px(10))
        for family, _labels in THEME_FAMILIES:
            members = [theme for theme in self._themes if theme.family == family]
            if not members:
                continue
            header = QLabel(theme_family_label(family))
            header.setObjectName("themeFamilyTitle")
            header.setProperty("typography", "meta")
            header.setProperty("i18nUserText", True)  # retranslate_ui owns this text
            outer.addWidget(header)
            holder = QWidget()
            holder.setObjectName("themeFamilyGrid")
            grid = QGridLayout(holder)
            grid.setContentsMargins(0, 0, 0, px(6))
            grid.setHorizontalSpacing(px(CARD_GAP))
            grid.setVerticalSpacing(px(CARD_GAP))
            cards = []
            for theme in members:
                card = ThemeCard(theme, holder)
                self._group.addButton(card)
                card.clicked.connect(lambda _checked=False, key=theme.key: self._chosen(key))
                cards.append(card)
            self._cards.extend(cards)
            self._sections.append((family, header, grid, cards))
            outer.addWidget(holder)
        self._cards.sort(key=lambda card: self._themes.index(card.theme))
        self._relayout(MAX_COLUMNS)
        self.setCurrentKey(current_key or theme_key())

    # -- combo-like API --------------------------------------------------
    def count(self) -> int:
        return len(self._cards)

    def itemData(self, index: int) -> str | None:
        return self._cards[index].theme.key if 0 <= index < len(self._cards) else None

    def itemText(self, index: int) -> str:
        return theme_display_label(self._cards[index].theme) if 0 <= index < len(self._cards) else ""

    def findData(self, key) -> int:
        return next((index for index, card in enumerate(self._cards) if card.theme.key == key), -1)

    def currentIndex(self) -> int:
        return next((index for index, card in enumerate(self._cards) if card.isChecked()), -1)

    def currentData(self) -> str | None:
        return self.itemData(self.currentIndex())

    def currentText(self) -> str:
        return self.itemText(self.currentIndex())

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._cards) or index == self.currentIndex():
            return
        self._cards[index].setChecked(True)
        self.currentIndexChanged.emit(index)

    def setCurrentKey(self, key: str) -> None:
        index = self.findData(key)
        self.setCurrentIndex(index if index >= 0 else 0)

    def card(self, key: str) -> ThemeCard | None:
        index = self.findData(key)
        return self._cards[index] if index >= 0 else None

    # -- behaviour --------------------------------------------------------
    def _chosen(self, key: str) -> None:
        self.currentIndexChanged.emit(self.findData(key))
        self.themeChosen.emit(key)

    def keyPressEvent(self, event) -> None:
        steps = {Qt.Key.Key_Left: -1, Qt.Key.Key_Up: -max(1, self._columns),
                 Qt.Key.Key_Right: 1, Qt.Key.Key_Down: max(1, self._columns)}
        focused = next((index for index, card in enumerate(self._cards) if card.hasFocus()), -1)
        if event.key() in steps and focused >= 0:
            target = max(0, min(len(self._cards) - 1, focused + steps[event.key()]))
            self._cards[target].setFocus(Qt.FocusReason.TabFocusReason)
            event.accept()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_revealed", False):
            self._revealed = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.reveal_current)

    def reveal_current(self) -> None:
        """Scroll the page so the chosen card is visible (themes low in the list)."""
        from PySide6.QtWidgets import QScrollArea
        index = self.currentIndex()
        node = self.parentWidget()
        while node is not None and not isinstance(node, QScrollArea):
            node = node.parentWidget()
        if node is not None and index >= 0:
            node.ensureWidgetVisible(self._cards[index], 0, px(24))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        columns = max(1, min(MAX_COLUMNS, (event.size().width() + px(CARD_GAP)) // (px(CARD_MIN_WIDTH) + px(CARD_GAP))))
        if columns != self._columns:
            self._relayout(columns)

    def _relayout(self, columns: int) -> None:
        self._columns = columns
        for _family, _header, grid, cards in self._sections:
            for card in cards:
                grid.removeWidget(card)
            for index, card in enumerate(cards):
                grid.addWidget(card, index // columns, index % columns)
            for column in range(MAX_COLUMNS):
                grid.setColumnStretch(column, 1 if column < columns else 0)

    def retranslate_ui(self) -> None:
        for family, header, _grid, cards in self._sections:
            header.setText(theme_family_label(family))
            for card in cards:
                card.retranslate_ui()
        self.languageRefreshed.emit()
