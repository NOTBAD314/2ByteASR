"""Term cards of the term library page (2026-11-03, plan 2026-11-03-glossary-card-wall).

The page keeps its one table model (``_TermMappingsModel``: one row per
mapping or reference); this view only paints each row as a compact card, so
large libraries still create no per-row widget. 2026-11-13 (plan
2026-11-13-glossary-library-redesign-c): cards keep a fixed height and wrap
into as many columns as the width allows. A card shows its spelling and
category, the chosen display language's translation with its state, and the
actual misrecognitions. Reference and hidden cards keep their 收下 / 恢复 action.
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
from ..design.typography import emphasized, weighted_font

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


@emphasized
def avatar_style(name: str, *, radius: int = 10, pixels: int = 14) -> str:
    """Stylesheet of a library's first-character badge: one stable hue per name."""
    hue = zlib.crc32(str(name or "").encode("utf-8")) % 360
    fill = QColor.fromHslF(hue / 360.0, 0.42, 0.46).name()
    return (f"background:{fill}; color:#ffffff; border-radius:{radius}px; "
            f"font-size:{pixels}px; font-weight:800;")


TRANSLATION_STATES = {"confirmed": "译名已确认", "pending": "译名待确认", "candidate": "AI 候选，待确认", "missing": "缺译名"}


def card_parts(row: dict | None) -> dict:
    """What a card shows for one model row (pure; also used by tests)."""
    row = row or {}
    status = str(row.get("status") or "reference")
    source = str(row.get("source") or "")
    target = str(row.get("target") or source)
    heard = [str(item) for item in (row.get("heard") or ()) if item and str(item) != target]
    if status in ("confirmed", "candidate") and heard:
        label, chips = "听成", heard
    elif status == "confirmed" and "heard" not in row and source and source != target:
        label, chips = "听成", [source]
    else:
        label, chips = "", []
    action = {"reference": "收下", "hidden": "恢复"}.get(status, "")
    return {
        "word": target, "category": str(row.get("category") or "其他"), "status": status,
        "label": label, "chips": chips, "note": row.get('language_note', ''), "action": action,
        "language_tag": row.get('language_tag', ''),
        "translation_code": str(row.get('translation_code') or ''),
        "translation": str(row.get('translation') or ''),
        "translation_state": str(row.get('translation_state') or ''),
    }


@dataclass(frozen=True)
class CardMetrics:
    """Card geometry in device-independent pixels (Qt scales for DPI)."""

    scale: float

    def px(self, value: float) -> int:
        return round(value * self.scale)


class TermCardDelegate(QStyledItemDelegate):
    # 2026-11-13 (plan 2026-11-13-glossary-library-redesign-c): fixed heights.
    # Name + one detail line, or name + translation + detail line.
    CARD_HEIGHT = 62
    TRANSLATION_HEIGHT = 84
    TOP_HEIGHT, LINE_HEIGHT, LINE_GAP, PAD_X = 22, 18, 3, 12

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
        weighted_font(font, weight)
        return font

    @staticmethod
    def metrics(_rect: QRect) -> CardMetrics:
        return CardMetrics(1.0)

    @classmethod
    def content_rects(cls, rect: QRect, parts: dict) -> tuple[QRect, QRect, QRect]:
        """(top, middle, bottom) single-line slots: name and category, the
        display-language translation, and misrecognitions or the action.
        Shared by painting and hit testing; always inside ``rect``."""
        lines = 3 if parts.get("translation_code") else 2
        needed = cls.TOP_HEIGHT + (lines - 1) * (cls.LINE_HEIGHT + cls.LINE_GAP)
        pad_y = max(3, min(10, (rect.height() - needed) // 2))
        content = rect.adjusted(cls.PAD_X, pad_y, -cls.PAD_X, -pad_y)
        top = QRect(content.x(), content.y(), content.width(), cls.TOP_HEIGHT)
        bottom = QRect(content.x(), content.bottom() - cls.LINE_HEIGHT + 1, content.width(), cls.LINE_HEIGHT)
        space_top, space_bottom = top.bottom() + 1, bottom.top() - 1
        space = max(1, space_bottom - space_top + 1)
        if lines == 3:
            height = min(cls.LINE_HEIGHT, space)
            middle = QRect(content.x(), space_top + (space - height) // 2, content.width(), height)
        else:
            middle = QRect(content.x(), space_top, content.width(), space)
        return top, middle, bottom

    def helpEvent(self, event, view, option, index):  # noqa: N802 - Qt API
        if event.type() != QEvent.Type.ToolTip or not index.isValid():
            return super().helpEvent(event, view, option, index)
        row = self._row(index) or {}
        parts = card_parts(row)
        status = {"confirmed": "已确认", "reference": "参考", "hidden": "已隐藏", "candidate": "待确认"}.get(parts["status"], "")
        lines = [parts["word"], f'{translate(parts["category"])} · {translate(status)}']
        if parts["translation_code"]:
            state = translate(TRANSLATION_STATES.get(parts["translation_state"], ""))
            lines.append(f'{parts["translation_code"]}：{parts["translation"] or "—"}（{state}）')
        if parts["chips"]:
            lines.append(f'{translate("听成")}：' + "、".join(parts["chips"]))
        if row.get("tooltip") and not parts["chips"]:
            lines.append(str(row["tooltip"]))
        QToolTip.showText(event.globalPos(), "<qt>" + "<br>".join(escape(line) for line in lines) + "</qt>", view)
        return True

    WORD_SIZES = (16, 15, 14, 13)

    def _word_room(self, top: QRect, parts: dict) -> int:
        return top.width() - (11 if parts["status"] == "candidate" else 0)

    def _tag_width(self, base: QFont, parts: dict) -> int:
        metrics = QFontMetrics(self._font(base, 11, QFont.Weight.DemiBold))
        return metrics.horizontalAdvance(translate(parts["category"])) + 14

    def tag_on_top(self, rect: QRect, parts: dict, font: QFont | None = None) -> bool:
        """2026-11-13 (user: names and tags were cut off): the name comes
        first. When the name and the whole category tag do not share the top
        line, the tag moves to the card's last line."""
        base = font or QApplication.font()
        top = self.content_rects(rect, parts)[0]
        word = QFontMetrics(self._font(base, self.WORD_SIZES[0], QFont.Weight.Bold)).horizontalAdvance(parts["word"])
        return word + 8 + self._tag_width(base, parts) <= self._word_room(top, parts)

    def word_font(self, base: QFont, width: int, word: str) -> QFont:
        """The largest of WORD_SIZES that fits the whole name; elided only below the smallest."""
        for size in self.WORD_SIZES:
            font = self._font(base, size, QFont.Weight.Bold)
            if QFontMetrics(font).horizontalAdvance(word) <= width:
                return font
        return font

    def _line_used(self, base: QFont, rect: QRect, index: QModelIndex, parts: dict) -> dict[str, int]:
        """Width the middle (translation) and bottom (misheard / action) lines
        need for their whole content; the moved tag goes where it cuts least."""
        small = QFontMetrics(self._font(base, 12, QFont.Weight.Normal))
        used = {"middle": 1 << 20, "bottom": 0}
        if parts["translation_code"]:
            code = QFontMetrics(self._font(base, 10, QFont.Weight.Bold)).horizontalAdvance(parts["translation_code"]) + 6
            text_metrics = QFontMetrics(self._font(base, 13, QFont.Weight.Normal))
            state = parts["translation_state"]
            if state == "missing" or not parts["translation"]:
                used["middle"] = code + text_metrics.horizontalAdvance(translate("缺译名"))
            else:
                badge = {"pending": "待确认", "candidate": "AI"}.get(state, "")
                badge_width = (QFontMetrics(self._font(base, 10, QFont.Weight.DemiBold)).horizontalAdvance(translate(badge))
                               + 10 if badge else (12 if state == "confirmed" else 0))
                used["middle"] = code + text_metrics.horizontalAdvance(parts["translation"]) + badge_width + 9
        button = self.button_rect(rect, index)
        bottom = (button.width() + 6) if button is not None else 0
        if parts["label"]:
            bottom += small.horizontalAdvance(translate(parts["label"]) + " " + "、".join(parts["chips"]))
        elif parts["note"] and not parts["translation_code"]:
            bottom += small.horizontalAdvance(parts["note"])
        used["bottom"] = bottom
        return used

    def category_rect(self, rect: QRect, index: QModelIndex, font: QFont | None = None) -> QRect:
        """One geometry for the painted category and its independent hit target."""
        parts = card_parts(self._row(index))
        base = font or QApplication.font()
        top, middle, bottom = self.content_rects(rect, parts)
        full = self._tag_width(base, parts)
        if self.tag_on_top(rect, parts, base):
            height = min(18, top.height())
            return QRect(top.right() - full + 1, top.y() + (top.height() - height) // 2, full, height)
        used = self._line_used(base, rect, index, parts)
        line = middle if used["middle"] < used["bottom"] or (
            parts["translation_code"] and used["middle"] + 8 + full <= middle.width()) else bottom
        right = line.right()
        if line is bottom:
            button = self.button_rect(rect, index)
            if button is not None:
                right = button.left() - 6
        width = max(34, min(full, (right - line.x()) * 2 // 3))
        height = min(16, line.height())
        return QRect(right - width + 1, line.y() + (line.height() - height) // 2, width, height)

    def button_rect(self, rect: QRect, index: QModelIndex) -> QRect | None:
        parts = card_parts(self._row(index))
        if not parts["action"]:
            return None
        font = self._font(QApplication.font(), 12, QFont.Weight.Bold)
        width = QFontMetrics(font).horizontalAdvance(translate(parts["action"])) + 20
        bottom = self.content_rects(rect, parts)[2]
        return QRect(bottom.right() - width + 1, bottom.top(), width, bottom.height())

    def paint(self, painter: QPainter, option, index):  # noqa: D401 - Qt API
        theme = _theme()
        parts = card_parts(self._row(index))
        rect = QRect(option.rect)
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
        path.addRoundedRect(card, 11, 11)
        if status == "reference":
            painter.fillPath(path, QColor(theme.surface) if not hovered else QColor(theme.surface_elevated))
            pen = QPen(QColor(theme.border_strong), 1.2, Qt.PenStyle.DashLine)
            pen.setDashPattern([4, 3])
        else:
            painter.fillPath(path, QColor(theme.surface_elevated))
            pen = QPen(QColor(theme.border_strong if hovered else theme.border), 1)
        if selected:
            pen = QPen(QColor(theme.accent), 2)
        painter.setPen(pen)
        painter.drawPath(path)

        top, middle, bottom = self.content_rects(rect, parts)
        # Top line: the spelling, with the category tag on the right.
        fill, ink, _dot = category_colors(parts["category"], theme)
        pill = QRectF(self.category_rect(rect, index, option.font))
        pill_font = self._font(option.font, 11, QFont.Weight.DemiBold)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(pill, 6, 6)
        painter.setFont(pill_font)
        painter.setPen(ink)
        painter.drawText(pill.adjusted(6, 0, -6, 0), int(Qt.AlignmentFlag.AlignCenter),
                         QFontMetrics(pill_font).elidedText(translate(parts["category"]), Qt.TextElideMode.ElideRight,
                                                            max(0, int(pill.width()) - 12)))
        word_left = top.x()
        if status == "candidate":  # the card's own name is not confirmed yet
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.warning))
            painter.drawEllipse(QPointF(word_left + 3, top.center().y() + 1), 3, 3)
            word_left += 11
        on_top = pill.top() < top.bottom()
        right = int(pill.left()) - 8 if on_top else top.right() + 1
        word_rect = QRect(word_left, top.y(), max(0, right - word_left), top.height())
        word_font = self.word_font(option.font, word_rect.width(), parts["word"])
        painter.setFont(word_font)
        painter.setPen(QColor(theme.text if status != "reference" else theme.text_secondary))
        painter.drawText(word_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         QFontMetrics(word_font).elidedText(parts["word"], Qt.TextElideMode.ElideRight, word_rect.width()))
        if parts["translation_code"]:
            if middle.top() <= pill.center().y() <= middle.bottom():  # the tag moved to this line
                middle = middle.adjusted(0, 0, -(middle.right() - int(pill.left()) + 6), 0)
            self._paint_translation(painter, theme, option.font, middle, parts)
        self._paint_bottom(painter, theme, option.font, rect, index, bottom, parts)
        painter.restore()

    def _paint_translation(self, painter, theme, base, line: QRect, parts: dict):
        code_font = self._font(base, 10, QFont.Weight.Bold)
        text_font = self._font(base, 13, QFont.Weight.Normal)
        badge_font = self._font(base, 10, QFont.Weight.DemiBold)
        code = parts["translation_code"]
        code_width = QFontMetrics(code_font).horizontalAdvance(code)
        painter.setFont(code_font)
        painter.setPen(QColor(theme.text_muted))
        painter.drawText(QRect(line.x(), line.y(), code_width, line.height()), int(Qt.AlignmentFlag.AlignVCenter), code)
        x = line.x() + code_width + 6
        state = parts["translation_state"]
        text_metrics = QFontMetrics(text_font)
        painter.setFont(text_font)
        if state == "missing" or not parts["translation"]:
            label = translate("缺译名")
            width = text_metrics.horizontalAdvance(label)
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(QRect(x, line.y(), width, line.height()), int(Qt.AlignmentFlag.AlignVCenter), label)
            dash = QPen(QColor(theme.border_strong), 1, Qt.PenStyle.DashLine)
            dash.setDashPattern([3, 2])
            painter.setPen(dash)
            baseline = line.y() + (line.height() + text_metrics.ascent()) // 2 + 2
            painter.drawLine(x, baseline, x + width, baseline)
            return
        badge = {"pending": "待确认", "candidate": "AI"}.get(state, "")
        badge_width = QFontMetrics(badge_font).horizontalAdvance(translate(badge)) + 10 if badge else (12 if state == "confirmed" else 0)
        limit = line.right() - badge_width - 4
        text = text_metrics.elidedText(parts["translation"], Qt.TextElideMode.ElideRight, max(0, limit - x))
        painter.setPen(QColor(theme.text if state == "confirmed" else theme.text_secondary))
        painter.drawText(QRect(x, line.y(), max(0, limit - x), line.height()), int(Qt.AlignmentFlag.AlignVCenter), text)
        x += text_metrics.horizontalAdvance(text) + 5
        if state == "confirmed":
            check = QPen(QColor(theme.success), 1.8)
            check.setCapStyle(Qt.PenCapStyle.RoundCap)
            check.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check)
            c = QPointF(x + 5, line.center().y() + 1)
            painter.drawPolyline([QPointF(c.x() - 4, c.y()), QPointF(c.x() - 1, c.y() + 3), QPointF(c.x() + 4, c.y() - 3)])
        elif badge:
            info = QColor(getattr(theme, "info", "") or "#2b5c9a")
            tone = QColor(theme.warning) if state == "pending" else info
            pill = QRectF(x, line.center().y() - 7, badge_width, 14)
            soft = _mix(QColor(theme.surface_elevated), tone, 0.18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(soft)
            painter.drawRoundedRect(pill, 7, 7)
            painter.setFont(badge_font)
            painter.setPen(_mix(tone, QColor(theme.text), 0.35))
            painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), translate(badge))

    def _paint_bottom(self, painter, theme, base, rect: QRect, index: QModelIndex, line: QRect, parts: dict):
        small = self._font(base, 12, QFont.Weight.Normal)
        small_metrics = QFontMetrics(small)
        limit = line.right()
        button = self.button_rect(rect, index)
        if button is not None:
            limit = button.left() - 6
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.accent_soft))
            painter.drawRoundedRect(QRectF(button), 8, 8)
            painter.setFont(self._font(base, 12, QFont.Weight.Bold))
            painter.setPen(QColor(theme.accent_text if theme.is_light else theme.text))
            painter.drawText(button, int(Qt.AlignmentFlag.AlignCenter), translate(parts["action"]))
        tag = self.category_rect(rect, index, base)
        if tag.top() >= line.top():  # the category tag moved down to this line
            limit = min(limit, tag.left() - 6)
        painter.setFont(small)
        painter.setPen(QColor(theme.text_muted))
        if not parts["label"]:
            if parts["note"] and not parts["translation_code"]:
                painter.drawText(QRect(line.x(), line.y(), max(0, limit - line.x()), line.height()), int(Qt.AlignmentFlag.AlignVCenter),
                                 small_metrics.elidedText(parts["note"], Qt.TextElideMode.ElideRight, max(0, limit - line.x())))
            return
        label = translate(parts["label"]) + " "
        painter.drawText(QRect(line.x(), line.y(), max(0, limit - line.x()), line.height()), int(Qt.AlignmentFlag.AlignVCenter), label)
        x = line.x() + small_metrics.horizontalAdvance(label)
        chips = list(parts["chips"])
        shown = []
        for position in range(len(chips)):
            rest = len(chips) - position - 1
            candidate = "、".join(chips[:position + 1]) + (f" +{rest}" if rest else "")
            if small_metrics.horizontalAdvance(candidate) > limit - x:
                break
            shown = chips[:position + 1]
        if shown:
            rest = len(chips) - len(shown)
            text = "、".join(shown) + (f" +{rest}" if rest else "")
        else:
            text = small_metrics.elidedText("、".join(chips), Qt.TextElideMode.ElideRight, max(0, limit - x))
        painter.setPen(QColor(theme.text_secondary))
        painter.drawText(QRect(x, line.y(), max(0, limit - x), line.height()), int(Qt.AlignmentFlag.AlignVCenter), text)


class TermCardView(QListView):
    """Wrapping grid of term cards over the page's table model."""

    action_requested = Signal(QModelIndex)  # the painted 收下 / 恢复 button
    # A plain click (or Enter) on a confirmed card: edit it.  The press does not
    # select, so the selection bar never flashes and nothing moves under the pointer.
    edit_requested = Signal(QModelIndex)
    category_requested = Signal(str)
    GAP = 10
    COLUMNS = 8  # at most; fewer when the width does not allow MIN_CARD_WIDTH
    MIN_CARD_WIDTH = 168

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("termCardView")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        # Every card uses the same grid cell. Let Qt lay out only a bounded
        # batch when a large model becomes visible, rather than all rows in
        # setVisible() on the GUI thread.
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(64)
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
        self._translation_line = False
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
        return bool(row and (row.get('concept_id') or row.get("status") == "confirmed") and row.get("raw"))

    def columns(self) -> int:
        return self._columns

    def set_translation_line(self, shown: bool):
        """Cards get a third line when a display language is chosen."""
        if bool(shown) != self._translation_line:
            self._translation_line = bool(shown)
            self.request_layout('translation')

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
        columns = max(1, min(self.COLUMNS, width // (self.MIN_CARD_WIDTH + self.GAP)))
        height = TermCardDelegate.TRANSLATION_HEIGHT if self._translation_line else TermCardDelegate.CARD_HEIGHT
        cell = QSize(width // columns, height + self.GAP)
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
