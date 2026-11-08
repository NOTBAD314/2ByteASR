"""Term cards of the term library page (2026-11-03, plan 2026-11-03-glossary-card-wall).

The page keeps its one table model (``_TermMappingsModel``: one row per
mapping or reference); this view only paints each row as a compact card in a
six-column grid with four visible rows, so large libraries still create no
per-row widget. Cards show the category, status, correct spelling and actual
misrecognitions only. Reference and hidden cards keep their 收下 / 恢复 action.
"""
from __future__ import annotations

import zlib
import os
from collections import Counter
from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, QPersistentModelIndex, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListView, QStyle, QStyledItemDelegate, QToolTip

from ..i18n import translate

# Hue and saturation per category; categories not listed get a stable hue
# from their name.  Neutral groups (其他, 术语 ...) stay grey.
CATEGORY_HUES = {
    "角色": (330, 0.62), "人物": (205, 0.62), "选手 ID": (220, 0.55), "技能": (265, 0.58),
    "物品": (38, 0.72), "装备": (28, 0.62), "材料": (48, 0.6), "周边": (15, 0.55),
    "地点": (170, 0.52), "Boss": (8, 0.68), "阵营": (140, 0.45), "事件": (120, 0.4),
    "活动": (120, 0.4), "方块": (90, 0.45), "模型": (250, 0.45), "机制": (190, 0.5),
    "玩家用语": (300, 0.45), "游戏术语": (280, 0.4), "货币": (50, 0.6),
    "其他": (0, 0.0), "术语": (0, 0.0), "常用搭配": (0, 0.0), "美术术语": (0, 0.0),
}


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _mix(first: QColor, second: QColor, amount: float) -> QColor:
    return QColor(
        round(first.red() + (second.red() - first.red()) * amount),
        round(first.green() + (second.green() - first.green()) * amount),
        round(first.blue() + (second.blue() - first.blue()) * amount),
    )


def category_colors(category: str, theme=None) -> tuple[QColor, QColor, QColor]:
    """(pill fill, pill text, dot) of a category on the active theme."""
    theme = theme or _theme()
    hue, saturation = CATEGORY_HUES.get(str(category or ""), (None, 0.5))
    if hue is None:
        hue = zlib.crc32(str(category).encode("utf-8")) % 360
    base = QColor(theme.surface_elevated)
    dot = QColor.fromHslF(hue / 360.0, saturation, 0.6)
    fill = _mix(base, dot, 0.2 if theme.is_light else 0.24)
    if saturation == 0.0:
        return fill, QColor(theme.text_secondary), QColor(theme.text_muted)
    ink = QColor.fromHslF(hue / 360.0, saturation * 0.85, 0.32 if theme.is_light else 0.76)
    return fill, ink, dot


def avatar_style(name: str, *, radius: int = 10, pixels: int = 14) -> str:
    """Stylesheet of a library's first-character badge: one stable hue per name."""
    hue = zlib.crc32(str(name or "").encode("utf-8")) % 360
    fill = QColor.fromHslF(hue / 360.0, 0.42, 0.46).name()
    return (f"background:{fill}; color:#ffffff; border-radius:{radius}px; "
            f"font-size:{pixels}px; font-weight:800;")


def card_parts(row: dict | None) -> dict:
    """What a card shows for one model row (pure; also used by tests)."""
    row = row or {}
    status = str(row.get("status") or "reference")
    source = str(row.get("source") or "")
    target = str(row.get("target") or source)
    heard = [str(item) for item in (row.get("heard") or ()) if item and str(item) != target]
    if status == "confirmed" and heard:
        label, chips = "听成", heard
    elif status == "confirmed" and "heard" not in row and source and source != target:
        label, chips = "听成", [source]
    else:
        label, chips = "", []
    action = {"reference": "收下", "hidden": "恢复"}.get(status, "")
    return {
        "word": target, "category": str(row.get("category") or "其他"), "status": status,
        "label": label, "chips": chips, "note": "", "action": action,
    }


@dataclass(frozen=True)
class CardMetrics:
    """Scale the complete card from the approved compact 101×77px layout."""

    scale: float

    def px(self, value: float) -> int:
        return round(value * self.scale)


class TermCardDelegate(QStyledItemDelegate):
    CARD_HEIGHT = 74

    def __init__(self, view):
        super().__init__(view)
        self.card_size = QSize(180, self.CARD_HEIGHT)

    def sizeHint(self, _option, _index):  # noqa: N802 - Qt API
        return QSize(self.card_size)

    @staticmethod
    def _row(index: QModelIndex):
        model = index.model()
        getter = getattr(model, "data_for_row", None)
        return getter(index.row()) if callable(getter) else None

    @staticmethod
    def _font(base: QFont, pixels: int, weight: QFont.Weight) -> QFont:
        font = QFont(base)
        font.setPixelSize(pixels)
        font.setWeight(weight)
        return font

    @staticmethod
    def metrics(rect: QRect) -> CardMetrics:
        return CardMetrics(max(1.0, min(rect.width() / 101, rect.height() / 77)))

    @staticmethod
    def content_rects(rect: QRect, parts: dict) -> tuple[QRect, QRect, QRect]:
        """Bounded single-line slots, shared by painting and action hit testing."""
        px = TermCardDelegate.metrics(rect).px
        pad_x, pad_y = px(12), px(6)
        content = rect.adjusted(pad_x, pad_y, -pad_x, -pad_y)
        header = QRect(content.x(), content.y(), content.width(), px(18))
        footer_height = px(18)
        footer = QRect(content.x(), content.bottom() - footer_height + 1, content.width(), footer_height)
        word_height = px(22)
        # Keep every title on the same baseline, including cards without errors.
        word_top = header.bottom() + 1 + max(px(2), (footer.top() - header.bottom() - 1 - word_height) // 2)
        word = QRect(content.x(), word_top, content.width(), word_height)
        return header, word, footer

    def helpEvent(self, event, view, option, index):  # noqa: N802 - Qt API
        if event.type() != QEvent.Type.ToolTip or not index.isValid():
            return super().helpEvent(event, view, option, index)
        row = self._row(index) or {}
        parts = card_parts(row)
        status = {"confirmed": "已确认", "reference": "参考", "hidden": "已隐藏"}.get(parts["status"], "")
        lines = [parts["word"], f'{translate(parts["category"])} · {translate(status)}']
        if parts["chips"]:
            lines.append(f'{translate("听成")}：' + "、".join(parts["chips"]))
        if row.get("tooltip") and not parts["chips"]:
            lines.append(str(row["tooltip"]))
        QToolTip.showText(event.globalPos(), "<qt>" + "<br>".join(escape(line) for line in lines) + "</qt>", view)
        return True

    def category_rect(self, rect: QRect, index: QModelIndex, font: QFont | None = None) -> QRect:
        """One geometry for the painted category and its independent hit target."""
        parts = card_parts(self._row(index))
        px = self.metrics(rect).px
        header = self.content_rects(rect, parts)[0]
        metrics = QFontMetrics(self._font(font or QApplication.font(), px(11), QFont.Weight.DemiBold))
        width = min(header.width() - px(18) - px(8), metrics.horizontalAdvance(translate(parts['category'])) + px(24))
        return QRect(header.x(), header.y(), max(px(30), width), header.height())

    def button_rect(self, rect: QRect, index: QModelIndex) -> QRect | None:
        parts = card_parts(self._row(index))
        if not parts["action"]:
            return None
        px = self.metrics(rect).px
        font = self._font(QApplication.font(), px(12), QFont.Weight.Bold)
        width = QFontMetrics(font).horizontalAdvance(translate(parts["action"])) + px(22)
        footer = self.content_rects(rect, parts)[2]
        return QRect(footer.right() - width + 1, footer.top(), width, footer.height())

    def paint(self, painter: QPainter, option, index):  # noqa: D401 - Qt API
        theme = _theme()
        parts = card_parts(self._row(index))
        rect = QRect(option.rect)
        metrics = self.metrics(rect)
        px, scale = metrics.px, metrics.scale
        painter.save()
        painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        status = parts["status"]
        if status == "hidden":
            painter.setOpacity(0.55)
        card = QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(card, px(14), px(14))
        if status == "reference":
            painter.fillPath(path, QColor(theme.surface) if not hovered else QColor(theme.surface_elevated))
            pen = QPen(QColor(theme.border_strong), 1.2 * scale, Qt.PenStyle.DashLine)
            pen.setDashPattern([4, 3])
        else:
            painter.fillPath(path, QColor(theme.surface_elevated))
            pen = QPen(QColor(theme.border_strong if hovered else theme.border), scale)
        if selected:
            pen = QPen(QColor(theme.accent), 2 * scale)
        painter.setPen(pen)
        painter.drawPath(path)

        header, word_rect, footer = self.content_rects(rect, parts)
        x = header.x()
        right = header.right()
        # row 1: category pill, status mark
        fill, ink, dot = category_colors(parts["category"], theme)
        pill_font = self._font(option.font, px(11), QFont.Weight.DemiBold)
        pill_metrics = QFontMetrics(pill_font)
        category = translate(parts["category"])
        mark_size = px(18)
        pill = QRectF(self.category_rect(rect, index, option.font))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(pill, px(9), px(9))
        painter.setBrush(dot)
        painter.drawEllipse(QPointF(pill.x() + px(9.5), pill.center().y()), px(3), px(3))
        painter.setFont(pill_font)
        painter.setPen(ink)
        painter.drawText(pill.adjusted(px(16), 0, -px(6), 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         pill_metrics.elidedText(category, Qt.TextElideMode.ElideRight, int(pill.width()) - px(22)))
        mark = QRectF(right - mark_size + 1, header.y() + (header.height() - mark_size) / 2, mark_size, mark_size)
        if status == "confirmed":
            success = QColor(theme.success)
            halo = QColor(success)
            halo.setAlphaF(0.22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(mark)
            check = QPen(success, 1.8 * scale)
            check.setCapStyle(Qt.PenCapStyle.RoundCap)
            check.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            c = mark.center()
            painter.drawPolyline([QPointF(c.x() - px(4), c.y()), QPointF(c.x() - px(1), c.y() + px(3)), QPointF(c.x() + px(4), c.y() - px(3))])
        elif status == "reference":
            ring = QPen(QColor(theme.border_strong), 1.4 * scale, Qt.PenStyle.DashLine)
            ring.setDashPattern([2, 2])
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(mark.adjusted(scale, scale, -scale, -scale))
        # row 2: the correct spelling
        word_font = self._font(option.font, px(15), QFont.Weight.Bold)
        word_metrics = QFontMetrics(word_font)
        painter.setFont(word_font)
        painter.setPen(QColor(theme.text if status != "reference" else theme.text_secondary))
        painter.drawText(word_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         word_metrics.elidedText(parts["word"], Qt.TextElideMode.ElideRight, word_rect.width()))
        # Bottom slot contains actual misrecognitions and the existing action.
        small = self._font(option.font, px(12), QFont.Weight.Normal)
        small_metrics = QFontMetrics(small)
        painter.setFont(small)
        line_top = footer.y()
        limit = right
        button = self.button_rect(rect, index)
        if button is not None:
            limit = button.left() - px(6)
            button_font = self._font(option.font, px(12), QFont.Weight.Bold)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent_soft))
            painter.drawRoundedRect(QRectF(button), px(9), px(9))
            painter.setFont(button_font)
            painter.setPen(QColor(theme.accent_text if theme.is_light else theme.text))
            painter.drawText(button, int(Qt.AlignmentFlag.AlignCenter), translate(parts["action"]))
            painter.setFont(small)
        cursor = x
        if parts["label"]:
            label = translate(parts["label"])
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(QRect(cursor, line_top, limit - cursor, footer.height()),
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
            cursor += small_metrics.horizontalAdvance(label) + px(6)
            chips = list(parts["chips"])
            if limit - cursor < px(70):
                # Compact cards should still show a spelling, rather than only
                # a +N counter when a chip and its counter cannot both fit.
                text_rect = QRect(cursor, line_top, max(0, limit - cursor), footer.height())
                painter.setPen(QColor(theme.text_secondary))
                painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                                 small_metrics.elidedText("、".join(chips), Qt.TextElideMode.ElideRight, text_rect.width()))
                painter.restore()
                return
            for position, chip in enumerate(chips):
                rest = len(chips) - position - 1
                more = f"+{rest}" if rest else ""
                width = small_metrics.horizontalAdvance(chip) + px(10)
                reserve = (small_metrics.horizontalAdvance(more) + px(14)) if more else 0
                if cursor + width + reserve > limit:
                    available = limit - cursor - reserve
                    if position == 0 and available > px(24):
                        chip = small_metrics.elidedText(chip, Qt.TextElideMode.ElideRight, available - px(10))
                        width = available
                    else:
                        more = f"+{len(chips) - position}"
                        self._chip(painter, theme, QRect(cursor, footer.y(), small_metrics.horizontalAdvance(more) + px(10), footer.height()), more, scale)
                        break
                self._chip(painter, theme, QRect(cursor, footer.y(), width, footer.height()), chip, scale)
                cursor += width + px(4)
        painter.restore()

    @staticmethod
    def _chip(painter, theme, rect: QRect, text: str, scale: float):
        painter.setPen(QPen(QColor(theme.border), scale))
        painter.setBrush(QColor(theme.input_surface))
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 7 * scale, 7 * scale)
        painter.setPen(QColor(theme.text_secondary))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)


class TermCardView(QListView):
    """Wrapping grid of term cards over the page's table model."""

    action_requested = Signal(QModelIndex)  # the painted 收下 / 恢复 button
    # A plain click (or Enter) on a confirmed card: edit it.  The press does not
    # select, so the selection bar never flashes and nothing moves under the pointer.
    edit_requested = Signal(QModelIndex)
    category_requested = Signal(str)
    GAP = 10
    COLUMNS = 6
    VISIBLE_ROWS = 4
    MIN_CARD_WIDTH = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("termCardView")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setSelectionRectVisible(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(4, 4, 4, 4)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.card_delegate = TermCardDelegate(self)
        self.setItemDelegate(self.card_delegate)
        self._pressed_action: QPersistentModelIndex | None = None
        self._pressed_edit: QPersistentModelIndex | None = None
        self._pressed_category: QPersistentModelIndex | None = None
        self._overlay = None
        self._columns = 0
        self._layout_running = False
        self._diagnostics = Counter() if os.environ.get('TWOBYTEASR_GLOSSARY_DIAGNOSTICS') == '1' else None
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._relayout)
        self.request_layout('initial')

    def set_overlay(self, widget):
        """Float ``widget`` (the selection bar) over the bottom of the cards."""
        self._overlay = widget
        widget.setParent(self)
        self.place_overlay()

    def place_overlay(self):
        widget = self._overlay
        if widget is None:
            return
        size = widget.sizeHint()
        width = min(max(size.width(), 320), max(200, self.width() - 24))
        widget.setGeometry((self.width() - width) // 2, self.height() - size.height() - 12, width, size.height())
        widget.raise_()

    @staticmethod
    def _editable(index: QModelIndex) -> bool:
        getter = getattr(index.model(), "data_for_row", None)
        row = getter(index.row()) if callable(getter) else None
        return bool(row and row.get("status") == "confirmed" and row.get("raw"))

    def columns(self) -> int:
        return self._columns

    def request_layout(self, source='resize'):
        if self._diagnostics is not None:
            self._diagnostics['request:' + source] += 1
        if not self._layout_timer.isActive():
            self._layout_timer.start(0)

    def layout_diagnostics(self):
        bar = self.verticalScrollBar()
        model = self.model()
        actual_columns = 0
        if model is not None and model.rowCount():
            top = self.visualRect(model.index(0, 0)).top()
            actual_columns = sum(self.visualRect(model.index(row, 0)).top() == top
                                 for row in range(min(self.COLUMNS + 1, model.rowCount())))
        return dict(counts=dict(self._diagnostics or {}), viewport=self.viewport().size().toTuple(),
                    columns=self._columns, actual_columns=actual_columns, grid=self.gridSize().toTuple(),
                    content_height=bar.maximum() + bar.pageStep(),
                    scrollbar_visible=bar.isVisible(), scrollbar_range=bar.maximum())

    def _relayout(self):
        if self._layout_running:
            self.request_layout('reentrant')
            return
        if self._diagnostics is not None:
            self._diagnostics['runs'] += 1
        # Reserve the same vertical gutter with and without a scrollbar. Using
        # the current viewport width feeds QListView's intermediate scrollbar
        # geometry back into the grid and can keep it resizing indefinitely.
        margins = self.viewportMargins()
        gutter = self.verticalScrollBar().sizeHint().width()
        width = max(1, self.contentsRect().width() - margins.left() - margins.right() - gutter - 1)
        height = max(1, self.viewport().height())
        columns = max(1, min(self.COLUMNS, width // (self.MIN_CARD_WIDTH + self.GAP)))
        cell = QSize(width // columns, max(TermCardDelegate.CARD_HEIGHT + self.GAP, height // self.VISIBLE_ROWS))
        card = QSize(max(1, cell.width() - self.GAP), cell.height() - self.GAP)
        self._columns = columns
        if card == self.card_delegate.card_size and cell == self.gridSize():
            return
        self._layout_running = True
        try:
            self.card_delegate.card_size = card
            self.setGridSize(cell)
            self.doItemsLayout()
            if self._diagnostics is not None:
                self._diagnostics['executed'] += 1
        finally:
            self._layout_running = False

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # QListView's icon layout can still be reserving the previous scrollbar
        # inside resizeEvent. Reflow once its viewport geometry has settled.
        self.request_layout('resize')
        self.place_overlay()

    def card_rect(self, index: QModelIndex) -> QRect:
        """Card geometry in viewport coordinates (the visual rect of the item)."""
        return self.visualRect(index)

    def _action_at(self, pos) -> QModelIndex:
        index = self.indexAt(pos)
        if not index.isValid():
            return QModelIndex()
        button = self.card_delegate.button_rect(self.visualRect(index), index)
        return index if button is not None and button.contains(pos) else QModelIndex()

    def _category_at(self, pos) -> QModelIndex:
        index = self.indexAt(pos)
        if index.isValid() and self.card_delegate.category_rect(self.visualRect(index), index, self.font()).contains(pos):
            return index
        return QModelIndex()

    def mousePressEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._category_at(event.position().toPoint())
            if index.isValid():
                self._pressed_category = QPersistentModelIndex(index)
                self._pressed_edit = self._pressed_action = None
                event.accept()
                return
            index = self._action_at(event.position().toPoint())
            if index.isValid():
                self._pressed_action = QPersistentModelIndex(index)
                event.accept()
                return
            modifiers = event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                                             | Qt.KeyboardModifier.MetaModifier)
            index = self.indexAt(event.position().toPoint())
            if not modifiers and index.isValid() and self._editable(index):
                self._pressed_edit = QPersistentModelIndex(index)
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                event.accept()
                return
        self._pressed_action = None
        self._pressed_edit = None
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802 - Qt API
        index = self.currentIndex()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and index.isValid() and self._editable(index):
            self.edit_requested.emit(index)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        if self._pressed_category is not None:
            pressed = QModelIndex(self._pressed_category)
            self._pressed_category = None
            index = self._category_at(event.position().toPoint())
            if pressed.isValid() and index == pressed:
                self.category_requested.emit(card_parts(self.card_delegate._row(index))['category'])
            event.accept()
            return
        if self._pressed_edit is not None:
            pressed = QModelIndex(self._pressed_edit)
            self._pressed_edit = None
            index = self.indexAt(event.position().toPoint())
            if pressed.isValid() and index.isValid() and index.row() == pressed.row():
                self.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.edit_requested.emit(index)
            event.accept()
            return
        if self._pressed_action is not None:
            pressed = QModelIndex(self._pressed_action)
            self._pressed_action = None
            index = self._action_at(event.position().toPoint())
            if pressed.isValid() and index.isValid() and index.row() == pressed.row():
                self.action_requested.emit(index)
            event.accept()
            return
        super().mouseReleaseEvent(event)
