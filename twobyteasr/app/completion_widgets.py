"""Native completion controls sharing the current application theme."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLayout, QPushButton,
    QSizePolicy, QStyle, QStyleOptionComboBox, QStylePainter, QWidget, QLabel, QToolButton, QVBoxLayout)

from .ui_zoom import px as _zpx  # painted text follows the interface zoom
from ..i18n import current_language, translate
from ..design.theme_manager import theme_key
from ..design.themed_icons import themed_icon
from ..design.ui_theme import blend_hex, theme_definition
from ..design.ui_widgets import AnimatedButton
from .completion_summary import completion_translate
from ..design.typography import MONO_FONT_STACK, TITLE_FONT_FAMILIES, UI_FONT_FAMILIES


def _ui_font(base, size, weight=QFont.Weight.Medium):
    font = QFont(base)
    font.setFamilies(list(UI_FONT_FAMILIES))
    font.setPixelSize(_zpx(size))
    font.setWeight(weight)
    return font


COMPLETION_RADIUS_MAIN = 12
COMPLETION_RADIUS_SMALL = 8
COMPLETION_SECONDARY_GAP = 16
COMPLETION_SECONDARY_HORIZONTAL_GAP = 18
COMPLETION_SECONDARY_WIDTH = 272
COMPLETION_SECONDARY_HEIGHT = 44
COMPLETION_MAIN_HEIGHT = 148
# Main action card inner geometry: padding, icon chip, gaps (2026-10-07).
CARD_PAD = 20
CARD_ICON = 56
CARD_ICON_GAP = 16
CARD_TEXT_GAP = 4
COMPLETION_MAX_WIDTH = 3400
COMPLETION_TOP_GAP = 28


class CompletionTaskSelector(QComboBox):
    """Elide the painted filename, keeping full selection and tooltip data."""

    def _elided_style_option(self):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        field = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                           QStyle.SubControl.SC_ComboBoxEditField, self)
        available = max(0, field.width() - 8)
        if not option.currentIcon.isNull():
            available = max(0, available - option.iconSize.width() - 4)
        option.currentText = self.fontMetrics().elidedText(option.currentText, Qt.TextElideMode.ElideMiddle, available)
        return option

    def paintEvent(self, event):
        if self.isEditable():
            return super().paintEvent(event)
        painter = QStylePainter(self)
        option = self._elided_style_option()
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)


class CompletionFilename(QLabel):
    """A single filename never sets the page minimum width."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTextFormat(Qt.TextFormat.PlainText)

    def set_full_name(self, name):
        self._full_name = name
        self.setToolTip(name)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(getattr(self, '_full_name', ''),
            Qt.TextElideMode.ElideMiddle, max(0, self.width())))

    def minimumSizeHint(self):
        return QSize(0, self.fontMetrics().height())

    def sizeHint(self):
        return QSize(300, self.fontMetrics().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class CompletionTitle(QLabel):
    """Result headline plus a status qualifier pill.

    ``text()`` keeps the shared outcome title (history/report use the same
    string); the qualifier after " · " is painted as a tone pill so the
    usable result and the unfinished part read as two facts, not one shout.
    """

    TONES = ('success', 'warning', 'danger', 'muted')
    # The qualifier can lead to its remedy (2026-10-09, M15, user: an
    # unfinished AI check opens AI proofreading from the pill itself).
    qualifier_clicked = Signal()

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._tone = 'warning'
        self._action = ''
        self._action_tip = ''
        self._hover = False
        self.setObjectName('resultTitle')
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setMouseTracking(True)

    def set_tone(self, tone):
        self._tone = tone if tone in self.TONES else 'warning'
        self.update()

    def set_qualifier_action(self, action='', tooltip=''):
        """``action`` (e.g. 'AI 校对 ›') makes the pill a button."""
        self._action, self._action_tip = str(action or ''), str(tooltip or '')
        self._hover = False
        self.setToolTip('')
        self.updateGeometry()
        self.update()

    def qualifier_action(self):
        return self._action

    def pill_rect(self):
        return self._geometry(self.width())[1]

    def _pill_text(self):
        _head, tail = self.parts()
        action = getattr(self, '_action', '')
        return tail + ('   ' + action if action and tail else '')

    def mouseMoveEvent(self, event):
        pill = self.pill_rect()
        hover = bool(self._action and pill is not None and pill.contains(event.position()))
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor)
            self.setToolTip(self._action_tip if hover else '')
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover:
            self._hover = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        pill = self.pill_rect()
        if (self._action and event.button() == Qt.MouseButton.LeftButton
                and pill is not None and pill.contains(event.position())):
            self.qualifier_clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def parts(self):
        head, _, tail = self.text().partition(' · ')
        return head, tail

    def head_font(self):
        font = QFont(self.font())
        font.setFamilies(list(TITLE_FONT_FAMILIES))
        font.setPixelSize(_zpx(26))
        font.setWeight(QFont.Weight.ExtraBold)
        return font

    def pill_font(self):
        return _ui_font(self.font(), 13)

    def _geometry(self, width):
        head, tail = self.parts()
        head_metrics, pill_metrics = QFontMetrics(self.head_font()), QFontMetrics(self.pill_font())
        head_width = head_metrics.horizontalAdvance(head)
        head_rect = QRectF(0, 0, min(width, head_width), head_metrics.height())
        if not tail:
            return head_rect, None
        # +6px slack: metrics at fractional DPR can round wider at paint time.
        pill_width = pill_metrics.horizontalAdvance(self._pill_text()) + 28
        pill_height = pill_metrics.height() + 8
        if head_width + 14 + pill_width <= width:
            pill = QRectF(head_width + 14, (head_metrics.height() - pill_height) / 2 + 1, pill_width, pill_height)
        else:
            pill = QRectF(0, head_metrics.height() + 6, min(width, pill_width), pill_height)
        return head_rect, pill

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        head, pill = self._geometry(max(1, width))
        return int(max(head.bottom(), pill.bottom() if pill else 0)) + 2

    def sizeHint(self):
        head, tail = self.parts()
        # Exactly the one-line width _geometry needs (head + gap + pill):
        # a narrower hint made layouts reserve a second, empty line (M15).
        width = QFontMetrics(self.head_font()).horizontalAdvance(head) + (
            14 + QFontMetrics(self.pill_font()).horizontalAdvance(self._pill_text()) + 28 if tail else 0)
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        # One line; a narrow width asks for the second line through
        # heightForWidth. Measuring the current (possibly stale, narrow)
        # width here kept a two-line minimum on wide pages (M15).
        return QSize(0, self.heightForWidth(1 << 15))

    def paintEvent(self, event):
        t = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        head, tail = self.parts()
        head_rect, pill = self._geometry(self.width())
        painter.setFont(self.head_font())
        painter.setPen(QColor(t.text))
        painter.drawText(head_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(self.head_font()).elidedText(head, Qt.TextElideMode.ElideRight, int(head_rect.width())))
        if pill is not None:
            color = {'success': t.success, 'warning': t.warning, 'danger': t.danger}.get(self._tone, t.text_secondary)
            fill = {'success': t.success_soft, 'warning': t.warning_soft, 'danger': t.danger_soft}.get(self._tone, t.surface_elevated)
            if self._action:
                # A button, not a label: outlined, brighter on hover.
                painter.setPen(QPen(QColor(blend_hex(fill, color, 0.75 if self._hover else 0.45)), 1))
                painter.setBrush(QColor(blend_hex(fill, color, 0.18) if self._hover else fill))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(fill))
            painter.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), pill.height() / 2, pill.height() / 2)
            painter.setFont(self.pill_font())
            painter.setPen(QColor(color))
            metrics = QFontMetrics(self.pill_font())
            room = int(pill.width()) - 22
            if self._action:
                action_font = QFont(self.pill_font())
                action_font.setWeight(QFont.Weight.Bold)
                action_font.setUnderline(self._hover)
                action_width = QFontMetrics(action_font).horizontalAdvance(self._action)
                tail_room = max(0, room - action_width - 12)
                shown = tail if metrics.horizontalAdvance(tail) <= tail_room + 4 else metrics.elidedText(tail, Qt.TextElideMode.ElideRight, tail_room)
                x = pill.left() + 14
                painter.drawText(QRectF(x, pill.top(), tail_room + 4, pill.height()),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, shown)
                painter.setFont(action_font)
                painter.setPen(QColor(t.accent_text if hasattr(t, 'accent_text') else t.accent))
                painter.drawText(QRectF(pill.right() - 14 - action_width, pill.top(), action_width + 2, pill.height()),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._action)
            else:
                text = tail if metrics.horizontalAdvance(tail) <= room + 4 else metrics.elidedText(tail, Qt.TextElideMode.ElideRight, room)
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class CompletionContent(QWidget):
    """Page-scoped surfaces and responsive spacing, without result semantics."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('completionContent')
        self.setProperty("uiZoomOwnSize", True)  # height follows its own layout
        self.refresh_theme_palette()

    def refresh_theme_palette(self):
        t = theme_definition(theme_key())
        self.setStyleSheet(f"""
QFrame#resultSummaryCard {{ background:{t.surface}; border:1px solid {t.border}; border-radius:{COMPLETION_RADIUS_MAIN}px; }}
QFrame#resultSummaryCard[outcome="success"] {{ background:{blend_hex(t.surface, t.success, 0.08)}; border-color:{blend_hex(t.surface, t.success, 0.42)}; }}
QFrame#resultSummaryCard[outcome="warning"] {{ background:{blend_hex(t.surface, t.warning, 0.08)}; border-color:{blend_hex(t.surface, t.warning, 0.42)}; }}
QFrame#resultSummaryCard[outcome="danger"] {{ background:{blend_hex(t.surface, t.danger, 0.08)}; border-color:{blend_hex(t.surface, t.danger, 0.42)}; }}
QToolButton#completionReviewChip {{ background:{t.warning_soft}; color:{t.warning}; border:1px solid {blend_hex(t.surface, t.warning, 0.45)}; }}
QToolButton#completionReviewChip:hover {{ background:{blend_hex(t.surface, t.warning, 0.24)}; border-color:{t.warning}; }}
QToolButton#completionReviewChip:focus {{ border-color:{t.focus}; }}
QFrame#resultSummaryRule {{ background:{t.border}; border:0; min-height:1px; max-height:1px; }}
QFrame#completionPreview {{ background:{t.surface}; border:1px solid {t.border}; border-radius:{COMPLETION_RADIUS_MAIN}px; }}
QLabel#completionPreviewTitle {{ color:{t.text}; font-size:15px; font-weight:600; background:transparent; }}
QLabel#completionPreviewNote {{ color:{t.text_muted}; font-size:13px; font-weight:500; background:transparent; }}
QFrame#completionPreviewRow {{ background:transparent; border:0; border-top:1px solid {t.hairline}; }}
QFrame#completionPreviewRow[first="true"] {{ border-top:0; }}
QLabel#completionPreviewTime {{ color:{t.text_muted}; font-family:{MONO_FONT_STACK}; font-size:13px; background:transparent; }}
QLabel#completionPreviewText {{ color:{t.text}; font-size:15px; font-weight:500; background:transparent; }}
QLabel#resultSummaryStats {{ color:{t.text_secondary}; font-size:14px; font-weight:500; background:transparent; }}
QLabel#resultSummaryMeta {{ color:{t.text_secondary}; font-size:14px; font-weight:500; background:transparent; }}
QLabel#resultStatValue {{ color:{t.text}; font-size:24px; font-weight:800; background:transparent; }}
QLabel#resultStatCaption {{ color:{t.text_muted}; font-size:13px; font-weight:500; background:transparent; }}
QLabel#resultSummaryFile {{ color:{t.text_secondary}; font-size:14px; font-weight:500; background:transparent; }}
QLabel#resultSummaryNote {{ color:{t.text_secondary}; font-size:13px; font-weight:500; background:transparent; }}
QTextEdit#resultFiles, QTextEdit#resultConsole {{ background:transparent; color:{t.text}; border:0; border-radius:0; padding:16px 18px; }}
QTextEdit#resultConsole {{ background:{t.log_background}; color:{t.log_text}; }}
QPushButton[completionRole="secondary"], QToolButton[completionRole="secondary"] {{
 background:{t.surface}; color:{t.text}; border:1px solid {t.border_strong}; border-radius:{COMPLETION_RADIUS_SMALL}px;
 font-size:14px; font-weight:500; padding:6px 16px;
}}
QPushButton[completionRole="secondary"]:hover, QToolButton[completionRole="secondary"]:hover {{ background:{t.selected}; border-color:{t.text_muted}; }}
QPushButton[completionRole="secondary"]:pressed, QToolButton[completionRole="secondary"]:pressed {{ background:{t.accent_tint}; border-color:{t.accent}; }}
QPushButton[completionRole="secondary"]:focus, QToolButton[completionRole="secondary"]:focus {{ border:1px solid {t.focus}; }}
QPushButton[completionRole="secondary"]:disabled, QToolButton[completionRole="secondary"]:disabled {{ color:{t.disabled}; border-color:{t.border}; background:{t.panel}; }}
QToolButton[completionRole="chip"], QPushButton[completionRole="chip"] {{ background:{t.surface_elevated}; color:{t.text}; border:1px solid {t.border_strong};
 border-radius:{COMPLETION_RADIUS_SMALL}px; font-size:13px; font-weight:500; padding:4px 12px; min-height:30px; }}
QToolButton[completionRole="chip"]:hover, QPushButton[completionRole="chip"]:hover {{ background:{t.selected}; border-color:{t.text_muted}; }}
QToolButton[completionRole="chip"]:focus, QPushButton[completionRole="chip"]:focus {{ border-color:{t.focus}; }}
QComboBox[completionRole="secondary"] {{ border-radius:{COMPLETION_RADIUS_SMALL}px; }}
QMenu[completionRole="secondary"] {{ border-radius:{COMPLETION_RADIUS_SMALL}px; }}
QMenu[completionRole="secondary"]::item {{ border-radius:6px; }}
""")

    def bind_actions(self, layout, cards, *, viewport=None,
                     summary_layout=None, summary_copy=None, page_layout=None, panels=(), action_grid=None):
        self._action_layout = layout
        self._action_cards = tuple(cards)
        self._viewport = viewport
        self._summary_layout = summary_layout
        self._summary_copy = summary_copy
        self._page_layout = page_layout
        self._panels = tuple(panels)
        self._action_grid = action_grid
        self._adapt_pending = False
        for panel in self._panels:
            panel.mode_changed.connect(self.request_adapt)
            panel.content_changed.connect(self.request_adapt)
        if viewport is not None:
            viewport.installEventFilter(self)
        self._adapt_width()

    def apply_ui_zoom(self, _factor):
        self.request_adapt()

    def request_adapt(self):
        if not self._adapt_pending:
            self._adapt_pending = True
            QTimer.singleShot(0, self, self._adapt_width)

    def _adapt_width(self):
        self._adapt_pending = False
        if not hasattr(self, '_action_layout'):
            return
        if self._viewport is not None and self._page_layout is not None:
            # Width follows the actual scroll viewport. Short windows scroll;
            # they never shrink the font or cards to fit the viewport height.
            side = round(self._viewport.width() * .06)
            self._page_layout.setContentsMargins(side, COMPLETION_TOP_GAP, side, COMPLETION_TOP_GAP)
        if not self._panels or self._viewport is None:
            return
        height = self._viewport.height()
        compact = height < 760
        self._action_layout.setSpacing(8 if compact else 12)
        for index, panel in enumerate(self._panels):
            panel.set_summary_limit((2 if compact else 4) if index == 0 else (4 if compact else 6))
            panel.set_extra_height(0)
        if self._action_grid is not None:
            self._action_grid.set_height_allowance(0)
        self._action_layout.invalidate()
        self._action_layout.activate()
        margins = self._page_layout.contentsMargins()
        required = self._action_layout.sizeHint().height()
        available = max(0, height - margins.top() - margins.bottom())
        spare = max(0, available - required)
        default_summary = all(panel.mode == 'summary' and panel.visible_summary_rows() for panel in self._panels)
        if default_summary and not compact and spare:
            # Spread extra room among real rows first. There is no empty spacer,
            # tall one-line log shell or viewport-sized accent card.
            action_extra = min(24, round(spare * .16))
            if self._action_grid is not None:
                self._action_grid.set_height_allowance(action_extra)
            remaining = spare - action_extra
            row_counts = [max(1, len(panel.visible_summary_rows())) for panel in self._panels]
            total = sum(row_counts)
            for index, panel in enumerate(self._panels):
                extra = round(remaining * row_counts[index] / total)
                panel.set_extra_height(extra)
        self._action_layout.invalidate()
        self.setFixedHeight(self._action_layout.sizeHint().height())
        self.updateGeometry()

    def eventFilter(self, watched, event):
        if watched is getattr(self, '_viewport', None) and event.type() == QEvent.Type.Resize:
            self.request_adapt()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adapt_width()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class CompletionAccordionHeader(QToolButton):
    """A full-width native toggle with its label and chevron at opposite ends."""
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setText(title)
        self.setCheckable(True)
        self.setArrowType(Qt.ArrowType.RightArrow)
        self.setProperty('completionRadius', COMPLETION_RADIUS_MAIN)
        self.setObjectName('completionAccordionHeader')
        self.setStyleSheet('font-size:15px; font-weight:600;')
        self.setFixedHeight(48)
        self.preview_text = ''
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.refresh_theme_palette()

    def sizeHint(self):
        return QSize(300, 48)

    def minimumSizeHint(self):
        return QSize(0, 48)

    def refresh_theme_palette(self):
        self._theme = theme_definition(theme_key())
        self.update()

    def content_rects(self):
        left = self._mode_rect().left()-12 if hasattr(self, 'mode') else self.width()-56
        return (QRectF(20, 0, max(0, left-20), self.height()),
                QRectF(self.width()-38, (self.height()-16)/2, 16, 16))

    def _mode_text(self):
        return completion_translate({'summary': '摘要 · 查看全部', 'full': '全部 · 返回摘要',
            'collapsed': '展开'}[self.mode], current_language())

    def _mode_rect(self):
        font = QFont(self.font()); font.setPixelSize(_zpx(13))
        width = QFontMetrics(font).horizontalAdvance(self._mode_text()) + 4
        collapse_width = QFontMetrics(font).horizontalAdvance(completion_translate('收起', current_language())) + 12
        right = self.width()-48-(collapse_width+8 if self.mode != 'collapsed' else 0)
        return QRectF(max(20, right-width), 0, width, self.height())

    def paintEvent(self, event):
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = t.selected if self.isDown() else t.surface_elevated if self.underMouse() else t.surface
        in_panel = isinstance(self.parentWidget(), CompletionInfoPanel)
        expanded = in_panel and getattr(self, 'mode', 'collapsed') != 'collapsed'
        painter.setPen(Qt.PenStyle.NoPen if in_panel else QPen(QColor(t.border), 1))
        painter.setBrush(QColor(fill))
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, COMPLETION_RADIUS_MAIN, COMPLETION_RADIUS_MAIN)
        if expanded:
            path.addRect(QRectF(rect.left(), rect.bottom()-COMPLETION_RADIUS_MAIN,
                                rect.width(), COMPLETION_RADIUS_MAIN+1))
        painter.drawPath(path.simplified())
        if expanded:
            painter.setPen(QPen(QColor(t.border), 1))
            painter.drawLine(QPointF(20, self.height()-1), QPointF(self.width()-20, self.height()-1))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.focus), 2))
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), COMPLETION_RADIUS_MAIN-3, COMPLETION_RADIUS_MAIN-3)
        title, arrow = self.content_rects()
        font = _ui_font(self.font(), 15, QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(t.text if self.isEnabled() else t.text_muted))
        painter.drawText(title, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        small = _ui_font(self.font(), 13)
        if getattr(self, 'mode', '') == 'collapsed' and self.preview_text:
            # A folded section still states its first real fact.
            offset = QFontMetrics(font).horizontalAdvance(self.text()) + 16
            preview = title.adjusted(offset, 0, 0, 0)
            painter.setFont(small)
            painter.setPen(QColor(t.text_muted))
            painter.drawText(preview, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(small).elidedText(self.preview_text, Qt.TextElideMode.ElideRight, int(max(0, preview.width()))))
        if hasattr(self, 'mode'):
            painter.setPen(QColor(t.text_secondary))
            painter.setFont(small)
            painter.drawText(self._mode_rect(),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._mode_text())
        x, y = arrow.left(), arrow.top()
        points = ([(x+3,y+5),(x+8,y+10),(x+13,y+5)] if self.arrowType() == Qt.ArrowType.DownArrow
                  else [(x+5,y+3),(x+10,y+8),(x+5,y+13)])
        pen = QPen(QColor(t.text_secondary), 2);pen.setCapStyle(Qt.PenCapStyle.RoundCap);pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(px,py) for px,py in points]))


class CompletionInfoPanel(QWidget):
    """Explicit summary, full technical detail and user-owned collapse modes."""
    mode_changed = Signal()
    content_changed = Signal()

    def __init__(self, header, detail, parent=None):
        super().__init__(parent)
        self.header, self.detail = header, detail
        # 2026-10-07: both completion folds start collapsed (user contract).
        self.mode = 'collapsed'
        self._summary_limit = 6
        self._extra_height = 0
        self._rows = []
        self.setObjectName('completionInfoPanel')
        self.setProperty("uiZoomOwnSize", True)  # rows are measured from their fonts
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(1, 1, 1, 1)
        self.layout_box.setSpacing(0)
        self.layout_box.addWidget(header)
        self.summary = QWidget()
        self.summary.setObjectName('completionInfoSummary')
        self.summary.setProperty("uiZoomOwnSize", True)
        self.summary_box = QVBoxLayout(self.summary)
        self.summary_box.setContentsMargins(18, 16, 18, 18)
        self.summary_box.setSpacing(5)
        self.layout_box.addWidget(self.summary)
        self.layout_box.addWidget(detail)
        detail.setMinimumHeight(170)
        detail.setFixedHeight(210)
        self.collapse_button = QToolButton(header)
        self.collapse_button.setText(completion_translate('收起', current_language()))
        self.collapse_button.setProperty('i18nText', '收起')
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_button.setStyleSheet('border:none; background:transparent; font-size:13px; padding:4px;')
        self.collapse_button.clicked.connect(lambda: self.set_mode('collapsed'))
        header.installEventFilter(self)
        header.clicked.connect(self._header_clicked)
        header.toggled.connect(self._header_toggled)
        self._apply_mode()

    def paintEvent(self, event):
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(theme.surface))
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                                COMPLETION_RADIUS_MAIN, COMPLETION_RADIUS_MAIN)

    def _header_clicked(self):
        if self.mode == 'collapsed':
            self.set_mode('summary')

    def _header_toggled(self, checked):
        if self.mode != 'collapsed':
            self.set_mode('full' if checked else 'summary')

    def eventFilter(self, watched, event):
        if watched is self.header and event.type() == QEvent.Type.Resize:
            self._place_collapse()
        return super().eventFilter(watched, event)

    def _place_collapse(self):
        width = self.collapse_button.fontMetrics().horizontalAdvance(self.collapse_button.text()) + 12
        self.collapse_button.setGeometry(max(0, self.header.width()-48-width), 8, width, 32)

    def set_mode(self, mode):
        if mode not in {'summary', 'full', 'collapsed'}:
            raise ValueError(mode)
        if self.mode == mode:
            return
        self.mode = mode
        self._apply_mode()
        self.mode_changed.emit()

    def _apply_mode(self):
        self.header.mode = self.mode
        self.header.blockSignals(True)
        self.header.setChecked(self.mode == 'full')
        self.header.blockSignals(False)
        self.header.setArrowType(Qt.ArrowType.RightArrow if self.mode == 'collapsed' else Qt.ArrowType.DownArrow)
        self.collapse_button.setText(completion_translate('收起', current_language()))
        self._place_collapse()
        self.header.setAccessibleDescription(completion_translate({'summary': '摘要 · 查看全部', 'full': '全部 · 返回摘要', 'collapsed': '已收起 · 展开摘要'}[self.mode], current_language()))
        self.collapse_button.setVisible(self.mode != 'collapsed')
        self.summary.setVisible(self.mode == 'summary')
        self.detail.setVisible(self.mode == 'full')
        self._refresh_rows()
        self.header.update()
        self.update()
        self.updateGeometry()

    def set_summary_lines(self, lines):
        for row in self._rows:
            self.summary_box.removeWidget(row)
            row.deleteLater()
        self._rows = []
        for text in lines:
            row = CompletionFilename()
            row.setStyleSheet('font-size:14px;')
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.set_full_name(str(text))
            self.summary_box.addWidget(row)
            row.setProperty("uiZoomOwnSize", True)  # measured from its font
            self._rows.append(row)
        self.header.preview_text = ' · '.join(str(text) for text in list(lines)[:2])
        self.header.update()
        self._refresh_rows()
        self._apply_mode()
        self.content_changed.emit()

    def set_summary_limit(self, count):
        if count != self._summary_limit:
            self._summary_limit = count
            self._refresh_rows()

    def visible_summary_rows(self):
        return self._rows[:self._summary_limit]

    def set_extra_height(self, height):
        self._extra_height = max(0, min(int(height), self.max_extra_height()))
        self._refresh_rows()

    def max_extra_height(self):
        # A very large controlled-DPI desktop is not permission to turn ten
        # actual lines into metres of blank list rows. Keep the row cadence
        # tied to its real font; unsupported excess viewport stays unfilled.
        return sum(round(row.fontMetrics().height() * 1.5) for row in self.visible_summary_rows())

    def apply_ui_zoom(self, _factor):
        self._refresh_rows()

    def _refresh_rows(self):
        visible = self.visible_summary_rows()
        count = max(1, len(visible))
        for index, row in enumerate(self._rows):
            row.setVisible(index < self._summary_limit)
            row.setFixedHeight(row.fontMetrics().height() + 3 + self._extra_height // count
                + (1 if index < self._extra_height % count else 0))
        margins = self.summary_box.contentsMargins()
        height = margins.top() + margins.bottom() + sum(row.height() for row in visible)
        height += max(0, len(visible)-1) * self.summary_box.spacing()
        self.summary.setFixedHeight(height)
        self.setFixedHeight(2 + self.header.height() + (height if self.mode == 'summary' else self.detail.height() if self.mode == 'full' else 0))
        self.updateGeometry()


class CompletionActionCard(QPushButton):
    """A whole-card button; native keyboard and click semantics stay intact."""

    def __init__(self, title, description, icon_name, parent=None, *, hue="brand"):
        super().__init__(title, parent)
        self.description = description
        self.icon_name = icon_name
        # Identity hue (category, never status): export blue / Studio brand /
        # finish teal, from theme.role_colors. All three keep equal weight.
        self.hue = hue
        self.setObjectName("completionActionCard")
        self.setProperty("uiZoomOwnSize", True)  # height measured from its text
        self.setProperty("completionRadius", COMPLETION_RADIUS_MAIN)
        self.setProperty("i18nText", title)
        self.setAccessibleDescription(description)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(COMPLETION_MAIN_HEIGHT)
        self.setMouseTracking(True)
        self.refresh_theme_palette()

    def sizeHint(self):
        return QSize(300, self.height())

    def minimumSizeHint(self):
        return QSize(240, self.height())

    def refresh_theme_palette(self):
        import qtawesome as qta

        self._theme = theme_definition(theme_key())
        self._card_icon = qta.icon(self.icon_name, color=self._theme.on_vivid,
                                   color_disabled=self._theme.disabled)
        self.update()

    def hue_color(self):
        theme = self._theme
        if self.hue == "finish":
            # Teal or orchid, whichever stays farther from the brand hue (green
            # brands such as warm/plum would otherwise read like teal).
            brand = QColor(theme.accent_text).hslHue()
            def distance(color):
                gap = abs(QColor(color).hslHue() - brand) % 360
                return min(gap, 360 - gap)
            return max((theme.role_colors["timeline"], theme.role_colors["review"]), key=distance)
        return theme.role_colors.get(self.hue, theme.accent_text)

    def card_colors(self):
        """(background, border) for the current interaction state."""
        theme, hue = self._theme, self.hue_color()
        if not self.isEnabled():
            return theme.panel, theme.border
        rest, hover, edge = theme.role_wash
        if self.isDown():
            return blend_hex(theme.surface, hue, hover + 0.06), hue
        if self.underMouse():
            return blend_hex(theme.surface, hue, hover), hue
        return blend_hex(theme.surface, hue, rest), blend_hex(theme.surface, hue, edge)

    def title_font(self):
        return _ui_font(self.font(), 22, QFont.Weight.DemiBold)

    def description_font(self):
        return _ui_font(self.font(), 14)

    def _text_heights(self, width):
        available = max(1, int(width) - 2 * CARD_PAD - CARD_ICON - CARD_ICON_GAP)
        flags = Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap
        title_metrics = QFontMetrics(self.title_font())
        description_metrics = QFontMetrics(self.description_font())
        title = title_metrics.boundingRect(QRect(0, 0, available, 10000), flags, self.text()).height()
        description = description_metrics.boundingRect(QRect(0, 0, available, 10000), flags,
            translate(self.description, self.copy_language())).height()
        return max(title_metrics.height(), title), max(description_metrics.height(), description)

    def copy_language(self):
        source = self.property('i18nText') or self.text()
        return next((language for language in (current_language(), 'zh', 'en', 'ja')
                     if translate(source, language) == self.text()), current_language())

    def desired_height(self, width):
        title, description = self._text_heights(width)
        if getattr(self, '_slots_width', None) == width:
            title, description = self._content_slots
        return max(COMPLETION_MAIN_HEIGHT, 2 * CARD_PAD + title + CARD_TEXT_GAP + description)

    def content_rects(self):
        title_height, description_height = getattr(self, '_content_slots', self._text_heights(self.width()))
        group_height = title_height + CARD_TEXT_GAP + description_height
        top = (self.height() - group_height) / 2
        # Center the icon + text group in wide cards; wrap from the padding
        # edge when the copy is longer than the card.
        available = max(0, self.width() - 2 * CARD_PAD - CARD_ICON - CARD_ICON_GAP)
        natural = max(QFontMetrics(self.title_font()).horizontalAdvance(self.text()),
                      QFontMetrics(self.description_font()).horizontalAdvance(
                          translate(self.description, self.copy_language())))
        text_width = min(available, natural + 2)
        left = max(CARD_PAD, (self.width() - (CARD_ICON + CARD_ICON_GAP + text_width)) / 2)
        text_left = left + CARD_ICON + CARD_ICON_GAP
        return (
            QRectF(left, (self.height() - CARD_ICON) / 2, CARD_ICON, CARD_ICON),
            QRectF(text_left, top, text_width, title_height),
            QRectF(text_left, top + title_height + CARD_TEXT_GAP, text_width, description_height),
        )

    def paintEvent(self, event):
        theme = self._theme
        enabled = self.isEnabled()
        background, border = self.card_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(frame, COMPLETION_RADIUS_MAIN, COMPLETION_RADIUS_MAIN)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.focus), 2))
            painter.drawRoundedRect(frame.adjusted(2, 2, -2, -2), COMPLETION_RADIUS_MAIN-2, COMPLETION_RADIUS_MAIN-2)
        icon_rect, title_rect, description_rect = self.content_rects()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.hue_color() if enabled else theme.surface))
        painter.drawRoundedRect(icon_rect, 14, 14)
        self._card_icon.paint(painter, icon_rect.adjusted(14, 14, -14, -14).toRect(),
                              mode=self._card_icon.Mode.Normal if enabled else self._card_icon.Mode.Disabled)
        painter.setFont(self.title_font())
        painter.setPen(QColor(theme.text if enabled else theme.disabled))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, self.text())
        painter.setFont(self.description_font())
        painter.setPen(QColor(theme.text_secondary if enabled else theme.disabled))
        description = translate(self.description, self.copy_language())
        painter.drawText(description_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, description)


COMPLETION_PREVIEW_ROWS = 12  # visible rows; the list scrolls through all cues


class _ElidedLine(CompletionFilename):
    """One subtitle line, elided at the end; never widens the page."""
    def _elide(self):
        self.setText(self.fontMetrics().elidedText(getattr(self, '_full_name', ''),
            Qt.TextElideMode.ElideRight, max(0, self.width())))


class _PreviewList(QWidget):
    """Painted, scrollable rows: time · speaker chip · text (all cues)."""

    ROW = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QScrollBar
        self._rows = []
        self._offset = 0
        self._hover = -1
        self.setMouseTracking(True)
        self.bar = QScrollBar(Qt.Orientation.Vertical, self)
        self.bar.valueChanged.connect(self._scrolled)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_rows(self, rows):
        self._rows = list(rows)
        self._sync_bar()
        self.bar.setValue(0)
        self.update()

    def _sync_bar(self):
        total = len(self._rows) * self.ROW
        self.bar.setRange(0, max(0, total - self.height()))
        self.bar.setPageStep(max(1, self.height()))
        self.bar.setSingleStep(self.ROW)
        self.bar.setVisible(total > self.height())
        self.bar.setGeometry(self.width() - 10, 0, 10, self.height())

    def _scrolled(self, value):
        self._offset = int(value)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_bar()

    def wheelEvent(self, event):
        self.bar.setValue(self.bar.value() - event.angleDelta().y() // 120 * self.ROW * 3)
        event.accept()

    def mouseMoveEvent(self, event):
        index = (int(event.position().y()) + self._offset) // self.ROW
        if index != self._hover:
            self._hover = index
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def paintEvent(self, event):
        theme = theme_definition(theme_key())
        dark = QColor(theme.app_background).lightness() < 128
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        right = self.width() - (14 if self.bar.isVisible() else 0)
        time_font = QFont(self.font()); time_font.setFamilies([part.strip().strip("'\"") for part in MONO_FONT_STACK.split(",")])
        time_font.setPixelSize(_zpx(13))
        chip_font = _ui_font(self.font(), 12, QFont.Weight.DemiBold)
        text_font = _ui_font(self.font(), 15)
        time_width = QFontMetrics(time_font).horizontalAdvance('00:00:00.0') + 14
        first = self._offset // self.ROW
        last = min(len(self._rows), (self._offset + self.height()) // self.ROW + 2)
        for index in range(first, last):
            time_text, speaker, color, line = self._rows[index]
            y = index * self.ROW - self._offset
            row = QRectF(0, y, right, self.ROW)
            if index == self._hover:
                painter.fillRect(row, QColor(theme.selected))
            if index:
                painter.fillRect(QRectF(4, y, right - 8, 1), QColor(theme.hairline))
            painter.setFont(time_font)
            painter.setPen(QColor(theme.text_muted))
            painter.drawText(QRectF(4, y, time_width, self.ROW), int(Qt.AlignmentFlag.AlignVCenter), time_text)
            painter.setFont(chip_font)
            chip_metrics = QFontMetrics(chip_font)
            chip_width = max(52, chip_metrics.horizontalAdvance(speaker) + 16)
            chip = QRectF(4 + time_width, y + (self.ROW - 22) / 2, chip_width, 22)
            base = QColor(color or theme.text_secondary)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(blend_hex(theme.surface, base.name(), 0.22)))
            painter.drawRoundedRect(chip, 6, 6)
            painter.setPen(base if dark else base.darker(160))
            painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), chip_metrics.elidedText(speaker, Qt.TextElideMode.ElideRight, int(chip_width - 8)))
            painter.setFont(text_font)
            painter.setPen(QColor(theme.text))
            left = chip.right() + 14
            available = max(0, int(right - left - 8))
            painter.drawText(QRectF(left, y, available, self.ROW), int(Qt.AlignmentFlag.AlignVCenter),
                             QFontMetrics(text_font).elidedText(line, Qt.TextElideMode.ElideRight, available))
        painter.end()


class CompletionPreview(QFrame):
    """The delivered subtitles (real project cues), all of them, scrollable.

    2026-10-09 (M14, user): not only the first 8 lines — a fixed-height list
    with its own scroll bar shows every cue; editing stays in Studio.
    """

    VISIBLE_ROWS = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        from ..i18n_widgets import bind_text
        self.setObjectName('completionPreview')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 12, 12)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(10)
        self.title = bind_text(QLabel(), '字幕预览')
        self.title.setObjectName('completionPreviewTitle')
        header.addWidget(self.title)
        self.note = QLabel('')
        self.note.setObjectName('completionPreviewNote')
        header.addWidget(self.note)
        header.addStretch(1)
        layout.addLayout(header)
        self.list = _PreviewList(self)
        layout.addWidget(self.list)
        self._rows = []
        self.hide()

    def set_rows(self, rows, total):
        """rows: [(time_text, speaker_name, speaker_hex, text)] for every cue."""
        from ..i18n_widgets import bind_text
        self._rows = list(rows)
        self.list.setFixedHeight(_PreviewList.ROW * max(1, min(self.VISIBLE_ROWS, len(self._rows))))
        self.list.set_rows(self._rows)
        if len(self._rows) > self.VISIBLE_ROWS:
            bind_text(self.note, '共 {total} 条 · 滚动查看全部', total=int(total))
        else:
            bind_text(self.note, '共 {total} 条', total=int(total))
        self.setVisible(bool(self._rows))

    def rows(self):
        return list(self._rows)

    def refresh_theme_palette(self):
        self.list.update()


class CompletionMoreButton(QToolButton):
    """Native popup activation with a vertically centered disclosure arrow."""
    def content_rects(self):
        return (QRectF(20, 0, max(0, self.width()-64), self.height()),
                QRectF(self.width()-34, (self.height()-16)/2, 16, 16))

    def paintEvent(self, event):
        theme = theme_definition(theme_key())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        border = theme.focus if self.hasFocus() else theme.text_muted if self.underMouse() else theme.border_strong
        painter.setPen(QPen(QColor(border), 1))
        painter.setBrush(QColor(theme.selected if self.underMouse() or self.isDown() else theme.surface))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), COMPLETION_RADIUS_SMALL, COMPLETION_RADIUS_SMALL)
        title, arrow = self.content_rects()
        painter.setFont(_ui_font(self.font(), 14))
        painter.setPen(QColor(theme.text if self.isEnabled() else theme.disabled))
        painter.drawText(title, Qt.AlignmentFlag.AlignCenter, self.text())
        x, y = arrow.left(), arrow.top()
        pen = QPen(QColor(theme.text_secondary), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([QPointF(x+3, y+5), QPointF(x+8, y+10), QPointF(x+13, y+5)]))


class CompletionSecondaryButton(AnimatedButton):
    """A local preferred height survives native theme/translation minima.

    Short completion windows scroll instead of compressing native supporting
    buttons to their platform's smaller default size hint.
    """
    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(max(COMPLETION_SECONDARY_HEIGHT, hint.height(), self.fontMetrics().height()+22))
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setHeight(self.sizeHint().height())
        return hint


class CompletionActionGrid(QWidget):
    """Main and supporting actions share one equal-column responsive grid."""

    def __init__(self, cards, parent=None):
        super().__init__(parent)
        self.cards = tuple(cards)
        self.buttons = ()
        self.secondary_actions = ()
        self.retry_button = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setHorizontalSpacing(COMPLETION_SECONDARY_HORIZONTAL_GAP)
        self.grid.setVerticalSpacing(COMPLETION_SECONDARY_GAP)
        self.columns = 0
        self._height_allowance = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._arrange(3)

    @property
    def _columns(self):
        return self.columns

    def set_secondary_actions(self, buttons, *, retry_button=None):
        self.secondary_actions = tuple(buttons)
        self.retry_button = retry_button
        self.buttons = ((retry_button,) if retry_button is not None else ()) + self.secondary_actions
        for button in self.buttons:
            button.setFixedHeight(COMPLETION_SECONDARY_HEIGHT)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setProperty('completionRole', 'secondary')
            button.setProperty('completionRadius', COMPLETION_RADIUS_SMALL)
            button.setStyleSheet('font-size:14px; padding:6px 16px;')
        columns = self.columns
        self.columns = 0
        self._arrange(columns)

    def _arrange(self, columns):
        if columns == self.columns:
            return
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(3):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)
        secondary_row = (len(self.cards) + columns - 1) // columns
        for index, button in enumerate(self.secondary_actions):
            self.grid.addWidget(button, secondary_row + index // columns, index % columns)
        if self.retry_button is not None:
            retry_row = secondary_row + (len(self.secondary_actions) + columns - 1) // columns
            self.grid.addWidget(self.retry_button, retry_row, 0, 1, columns)
        self.columns = columns
        self._refresh_card_heights()
        self.updateGeometry()

    def apply_ui_zoom(self, _factor):
        self._refresh_card_heights()

    def _refresh_card_heights(self):
        if not self.columns:
            return
        width = (self.width() - (self.columns-1)*self.grid.horizontalSpacing()) // self.columns
        measured = [card._text_heights(width) for card in self.cards]
        slots = (max(item[0] for item in measured), max(item[1] for item in measured))
        height = max(COMPLETION_MAIN_HEIGHT, 2 * CARD_PAD + slots[0] + CARD_TEXT_GAP + slots[1]) + self._height_allowance
        for card in self.cards:
            card._content_slots = slots
            card._slots_width = width
            card.update()
            if card.height() != height:
                card.setFixedHeight(height)

    def set_height_allowance(self, pixels):
        pixels = max(0, min(24, int(pixels)))
        if pixels != self._height_allowance:
            self._height_allowance = pixels
            self._refresh_card_heights()
            self.updateGeometry()

    def _reflow(self):
        minimum = max((max(280, button.minimumWidth(), button.fontMetrics().horizontalAdvance(button.text())
            + (64 if isinstance(button, CompletionMoreButton) else 40)) for button in self.secondary_actions), default=280)
        self._arrange(3 if self.width() >= minimum*3+2*self.grid.horizontalSpacing() else 1)
        self._refresh_card_heights()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.FontChange, QEvent.Type.Show) and hasattr(self, 'grid'):
            self._reflow()
        return result

    def minimumSizeHint(self):
        # Parent scroll areas must be able to shrink us *before* resizeEvent
        # switches the grid. A three-column layout minimum would deadlock it.
        return QSize(230, self.grid.sizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()


class CompletionSecondaryGroup(QWidget):
    """Standalone compatibility group using the same responsive column tokens."""
    def __init__(self, buttons, parent=None):
        super().__init__(parent)
        self.buttons = tuple(buttons)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(COMPLETION_SECONDARY_HORIZONTAL_GAP)
        self.grid.setVerticalSpacing(16)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._columns = 0
        self._visible_signature = None
        self._arranging = False
        for button in self.buttons:
            button.setFixedHeight(COMPLETION_SECONDARY_HEIGHT)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setProperty('completionRole', 'secondary')
            button.setProperty('completionRadius', COMPLETION_RADIUS_SMALL)
            button.setStyleSheet('font-size:14px; padding:6px 16px;')
            self.grid.addWidget(button, 0, self.grid.count())
            button.installEventFilter(self)
        self._reflow()

    def _arrange(self, columns):
        visible = tuple(button for button in self.buttons if not button.isHidden())
        signature = tuple(self.buttons.index(button) for button in visible)
        if columns == self._columns and signature == self._visible_signature:
            return
        self._arranging = True
        try:
            while self.grid.count():
                self.grid.takeAt(0)
            for column in range(4):
                self.grid.setColumnStretch(column, 1 if column < columns else 0)
                self.grid.setColumnMinimumWidth(column, 0)
            for index, button in enumerate(visible):
                self.grid.addWidget(button, index // columns, index % columns)
            self._columns = columns
            self._visible_signature = signature
        finally:
            self._arranging = False
        self.updateGeometry()

    def _reflow(self):
        if self._arranging:
            return
        # CompletionPage uses CompletionActionGrid for both action rows.
        from .ui_zoom import logical
        self._arrange(3 if logical(self.width()) >= 960 else 1)

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Show) and hasattr(self, 'grid'):
            self._reflow()
        return result

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.FontChange):
            self._reflow()
        return super().eventFilter(watched, event)

    def minimumSizeHint(self):
        return QSize(0, self.grid.minimumSize().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()
