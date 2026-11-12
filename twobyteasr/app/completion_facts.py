"""Summary bodies of the two completion info panels (2026-11-11, user, design A).

「任务与输出」 shows a row of number tiles and a short key/value list;
「运行日志」 shows each stage's time as a bar, then a few fact pills. Both are
painted from plain strings the summary prepared, wrap instead of cutting text,
and report the height they need for a width so the panel can size itself.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..design.theme_manager import theme_key
from ..design.typography import UI_FONT_FAMILIES
from ..design.ui_theme import blend_hex, theme_definition
from .ui_zoom import px as _zpx

WRAP = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWrapAnywhere
GAP = 8


def _font(base, size, weight=QFont.Weight.Medium):
    font = QFont(base)
    font.setFamilies(list(UI_FONT_FAMILIES))
    font.setPixelSize(_zpx(size))
    font.setWeight(weight)
    return font


class _Body(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty('uiZoomOwnSize', True)  # measured from its fonts
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

    def theme(self):
        return theme_definition(theme_key())

    def tile_fill(self):
        theme = self.theme()
        return blend_hex(theme.surface, theme.text, 0.055)

    def refresh_theme_palette(self):
        self.update()

    def apply_ui_zoom(self, _factor):
        self.updateGeometry()
        self.update()


class CompletionFactsBody(_Body):
    """Number tiles, then ``key  value`` rows whose values wrap."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tiles = ()   # ((value, caption), ...)
        self.facts = ()   # ((key, value), ...)

    def set_content(self, tiles, facts):
        self.tiles = tuple((str(value), str(caption)) for value, caption in tiles)
        self.facts = tuple((str(key), str(value)) for key, value in facts)
        self.setToolTip('')
        self.updateGeometry()
        self.update()

    def has_content(self):
        return bool(self.tiles or self.facts)

    def value_font(self):
        return _font(self.font(), 17, QFont.Weight.Bold)

    def caption_font(self):
        return _font(self.font(), 12)

    def fact_font(self):
        return _font(self.font(), 13)

    def tile_columns(self, width):
        if not self.tiles:
            return 0
        value, caption = QFontMetrics(self.value_font()), QFontMetrics(self.caption_font())
        widest = max(max(value.horizontalAdvance(tile[0]), caption.horizontalAdvance(tile[1])) for tile in self.tiles) + 22
        count = len(self.tiles)
        for columns in (count, 2, 1):
            if columns <= count and widest * columns + GAP * (columns - 1) <= width:
                return columns
        return 1

    def tile_height(self):
        return QFontMetrics(self.value_font()).height() + QFontMetrics(self.caption_font()).height() + 16

    def tile_rects(self, width):
        columns = self.tile_columns(width)
        if not columns:
            return []
        tile_width = (width - GAP * (columns - 1)) / columns
        height = self.tile_height()
        return [QRectF((index % columns) * (tile_width + GAP), (index // columns) * (height + GAP), tile_width, height)
                for index in range(len(self.tiles))]

    def key_width(self):
        metrics = QFontMetrics(self.fact_font())
        return max((metrics.horizontalAdvance(key) for key, _value in self.facts), default=0) + 12

    def fact_rects(self, width):
        """[(key rect, value rect)] below the tiles."""
        tiles = self.tile_rects(width)
        y = (tiles[-1].bottom() + 10) if tiles else 0
        metrics = QFontMetrics(self.fact_font())
        key_width = self.key_width()
        room = max(1, int(width - key_width))
        rows = []
        for _key, value in self.facts:
            height = max(metrics.height(), metrics.boundingRect(QRect(0, 0, room, 10000), int(WRAP), value).height())
            rows.append((QRectF(0, y, key_width, metrics.height()), QRectF(key_width, y, room, height)))
            y += height + 5
        return rows

    def height_for(self, width):
        width = max(1, int(width))
        facts = self.fact_rects(width)
        if facts:
            return int(facts[-1][1].bottom()) + 1
        tiles = self.tile_rects(width)
        return int(tiles[-1].bottom()) + 1 if tiles else 0

    def paintEvent(self, event):
        theme = self.theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        value_font, caption_font = self.value_font(), self.caption_font()
        value_height = QFontMetrics(value_font).height()
        for (value, caption), rect in zip(self.tiles, self.tile_rects(self.width())):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.tile_fill()))
            painter.drawRoundedRect(rect, 10, 10)
            inner = rect.adjusted(11, 7, -8, -7)
            painter.setFont(value_font)
            painter.setPen(QColor(theme.text))
            painter.drawText(QRectF(inner.left(), inner.top(), inner.width(), value_height),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
            painter.setFont(caption_font)
            painter.setPen(QColor(theme.text_secondary))
            painter.drawText(QRectF(inner.left(), inner.top() + value_height, inner.width(), inner.height() - value_height),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, caption)
        painter.setFont(self.fact_font())
        for (key, value), (key_rect, value_rect) in zip(self.facts, self.fact_rects(self.width())):
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(key_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, key)
            painter.setPen(QColor(theme.text))
            painter.drawText(value_rect, int(WRAP), value)
        painter.end()


class CompletionTimingBody(_Body):
    """One bar per stage, scaled to the longest; then wrapped fact pills."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timings = ()  # ((name, fraction 0..1 or None, value text, kind, finished), ...)
        self.chips = ()    # ((text, tone), ...)

    def set_content(self, timings, chips):
        self.timings = tuple(timings)
        self.chips = tuple((str(text), str(tone)) for text, tone in chips)
        self.updateGeometry()
        self.update()

    def has_content(self):
        return bool(self.timings or self.chips)

    def name_font(self):
        return _font(self.font(), 13)

    def value_font(self):
        return _font(self.font(), 15, QFont.Weight.Bold)

    def chip_font(self):
        return _font(self.font(), 13)

    def row_height(self):
        return max(QFontMetrics(self.name_font()).height(), QFontMetrics(self.value_font()).height()) + 4

    def columns(self, width):
        """(name width, value width, bar rect x, bar width)."""
        name = max((QFontMetrics(self.name_font()).horizontalAdvance(row[0]) for row in self.timings), default=0) + 12
        value = max((QFontMetrics(self.value_font()).horizontalAdvance(row[2]) for row in self.timings), default=0) + 12
        return name, value, name, max(24, width - name - value)

    def chip_rects(self, width):
        """[(pill rect, text rect)] flowing left to right under the bars."""
        metrics = QFontMetrics(self.chip_font())
        y = len(self.timings) * self.row_height() + (10 if self.timings else 0)
        x, line_height, rects = 0, 0, []
        for text, _tone in self.chips:
            room = max(1, int(width) - 24)
            text_rect = metrics.boundingRect(QRect(0, 0, room, 10000), int(WRAP), text)
            pill_width = min(width, max(text_rect.width(), metrics.horizontalAdvance(text) if text_rect.height() <= metrics.height() else 0) + 24)
            pill_height = max(metrics.height(), text_rect.height()) + 8
            if x and x + pill_width > width:
                x, y, line_height = 0, y + line_height + 6, 0
            pill = QRectF(x, y, pill_width, pill_height)
            rects.append((pill, pill.adjusted(12, 4, -12, -4)))
            x += pill_width + 6
            line_height = max(line_height, pill_height)
        return rects

    def height_for(self, width):
        width = max(1, int(width))
        chips = self.chip_rects(width)
        if chips:
            return int(max(pill.bottom() for pill, _text in chips)) + 1
        return len(self.timings) * self.row_height()

    def bar_color(self, kind, finished):
        theme = self.theme()
        if not finished:
            return theme.danger
        return theme.zone_colors.get('ai', theme.accent) if kind == 'ai' else theme.success

    def paintEvent(self, event):
        theme = self.theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        name_width, value_width, bar_x, bar_width = self.columns(self.width())
        row = self.row_height()
        for index, (name, fraction, value, kind, finished) in enumerate(self.timings):
            y = index * row
            painter.setFont(self.name_font())
            painter.setPen(QColor(theme.text_secondary))
            painter.drawText(QRectF(0, y, name_width, row), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
            track = QRectF(bar_x, y + (row - 10) / 2, bar_width - 4, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(blend_hex(theme.surface, theme.text, 0.09)))
            painter.drawRoundedRect(track, 5, 5)
            if fraction is not None:
                fill = QRectF(track.left(), track.top(), max(10.0, track.width() * max(0.0, min(1.0, fraction))), track.height())
                painter.setBrush(QColor(self.bar_color(kind, finished)))
                painter.drawRoundedRect(fill, 5, 5)
            painter.setFont(self.value_font())
            painter.setPen(QColor(theme.text if finished else theme.danger))
            painter.drawText(QRectF(self.width() - value_width, y, value_width, row),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, value)
        painter.setFont(self.chip_font())
        ai = theme.zone_colors.get('ai', theme.accent)
        for (text, tone), (pill, text_rect) in zip(self.chips, self.chip_rects(self.width())):
            fill = (blend_hex(theme.surface, ai, 0.16) if tone == 'ai' else theme.warning_soft if tone == 'warning'
                    else self.tile_fill())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            radius = min(12.0, pill.height() / 2)
            painter.drawRoundedRect(pill, radius, radius)
            painter.setPen(QColor(theme.warning if tone == 'warning' else theme.text))
            painter.drawText(text_rect, int(WRAP), text)
        painter.end()
