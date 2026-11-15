"""Icon buttons for 工程音量 and 次要角色 in the timeline bar (2026-11-14).

User (2026-11-14): the two text buttons 「工程音量 / 响度」 and 「次要角色」 were hard
to read and looked out of place; of three toolbar drafts they picked A — same
places, drawn icons instead of words:

* 工程音量: a speaker with rising bars, and beside it the predicted loudness
  (e.g. −12.4) in the colour of its state once the mix has been measured;
* 次要角色: one big and two small people, with how many speakers are in the
  group; the icon shows whether the group is expanded, collapsed or hidden.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QToolButton

from ..i18n import tr


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


class _PaintedTool(QToolButton):
    """Hover/pressed/focus look of the bar's other tool buttons, painted by hand."""

    ICON = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('studioTool')
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._watch = QTimer(self)
        self._watch.timeout.connect(self.refresh)

    def showEvent(self, event):  # noqa: N802 - Qt override
        super().showEvent(event)
        self.refresh()
        self._watch.start()

    def hideEvent(self, event):  # noqa: N802 - Qt override
        self._watch.stop()
        super().hideEvent(event)

    def refresh(self) -> None:  # overridden
        pass

    def _paint_base(self, painter: QPainter, theme) -> QRectF:
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        down = self.isDown() or (self.menu() is not None and self.menu().isVisible())
        if down or self.underMouse():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.selected if not down else theme.border))
            painter.drawRoundedRect(rect, 9, 9)
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.focus), 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), 9, 9)
        return rect

    def _paint_icon(self, painter: QPainter, name: str, left: float, role: str = 'toolbar_secondary') -> None:
        from ..design.themed_icons import themed_icon
        top = (self.height() - self.ICON) / 2
        icon = themed_icon(name, role)
        icon.paint(painter, QRectF(left, top, self.ICON, self.ICON).toRect())

    def enterEvent(self, event):  # noqa: N802 - Qt override
        self.update(); super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        self.update(); super().leaveEvent(event)


class LoudnessButton(_PaintedTool):
    """Opens 工程音量 / 响度; shows the predicted loudness of a still-valid measurement."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.readout = None
        self.setObjectName('projectLoudnessButton')
        self.setAccessibleName(str(tr('工程音量 / 响度')))
        self._watch.setInterval(1500)
        self.setFixedSize(self._width(), 34)
        self._apply_tooltip()

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(self._width(), 34)

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        return self.sizeHint()

    def _chip_text(self) -> str:
        return f'{self.readout[0]:.1f}'.replace('-', '−') if self.readout else ''

    def _width(self) -> int:
        if not self.readout:
            return 36
        font = QFont(self.font()); font.setPixelSize(11)
        from PySide6.QtGui import QFontMetrics
        return 8 + self.ICON + 5 + QFontMetrics(font).horizontalAdvance(self._chip_text()) + 14 + 6

    def refresh(self) -> None:
        readout = None
        if getattr(self.page, '_loudness_cache', None):
            try:
                from .project_loudness_panel import loudness_readout
                readout = loudness_readout(self.page)
            except Exception:  # noqa: BLE001 - a readout must never break the toolbar
                readout = None
        rounded = None if readout is None else tuple(round(value, 1) for value in readout)
        if rounded != self.readout:
            self.readout = rounded
            self.setFixedWidth(self._width())
            self._apply_tooltip()
            self.update()

    def _apply_tooltip(self) -> None:
        if self.readout:
            from .project_loudness_panel import loudness_status
            words = loudness_status(self.readout[0], self.readout[2])[1]
            self.setToolTip(str(tr('工程音量 / 响度 · 现在 {value} LUFS（{state}）', value=self._chip_text(), state=tr(words))))
        else:
            self.setToolTip(str(tr('工程音量 / 响度 · 把整部片调到平台建议的响度')))

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        from ..design.ui_theme import blend_hex
        from .project_loudness_panel import _role_color, loudness_status
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_base(painter, theme)
        if not self.readout:
            self._paint_icon(painter, 'app.project_volume', (self.width() - self.ICON) / 2)
            painter.end()
            return
        self._paint_icon(painter, 'app.project_volume', 8)
        color = QColor(_role_color(theme, loudness_status(self.readout[0], self.readout[2])[0]))
        font = QFont(self.font()); font.setPixelSize(11); font.setBold(True)
        painter.setFont(font)
        text = self._chip_text()
        width = painter.fontMetrics().horizontalAdvance(text) + 12
        chip = QRectF(8 + self.ICON + 5, (self.height() - 18) / 2, width, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(blend_hex(theme.surface_elevated, color.name(), .18)))
        painter.drawRoundedRect(chip, 9, 9)
        painter.setPen(color)
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class SecondaryRolesButton(_PaintedTool):
    """The 次要角色 menu button: icon by group state, member count as a badge."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.page = page
        self.signature = None
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._watch.setInterval(700)
        self.setFixedSize(46, 34)

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(46, 34)   # the bar's style sheet replaces the minimum; the hint keeps the width

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        return self.sizeHint()

    def _state(self):
        timeline = getattr(self.page, 'timeline', None)
        members = tuple(getattr(timeline, '_group_members', ()) or ()) if timeline is not None else ()
        if not members or getattr(timeline, 'project', None) is None:
            return 0, 'none'
        try:
            hidden = timeline._group_header_state()[0]
        except Exception:  # noqa: BLE001
            hidden = False
        return len(members), 'hidden' if hidden else 'expanded' if timeline._group_expanded else 'collapsed'

    def refresh(self) -> None:
        signature = self._state()
        if signature != self.signature:
            self.signature = signature
            count, state = signature
            words = {'none': '没有次要角色分组', 'hidden': '已隐藏', 'expanded': '已展开', 'collapsed': '已收起'}[state]
            if count:
                self.setToolTip(str(tr('次要角色 · {count} 位 · {state}（点开可展开、收起或隐藏）', count=count, state=tr(words))))
            else:
                self.setToolTip(str(tr('次要角色 · 没有次要角色分组')))
            self.update()

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        theme = _theme()
        count, state = self.signature or self._state()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_base(painter, theme)
        name = {'hidden': 'app.secondary_roles_hidden', 'collapsed': 'app.secondary_roles_collapsed'}.get(state, 'app.secondary_roles')
        self._paint_icon(painter, name, 6, 'accent' if state == 'hidden' else 'toolbar_secondary')
        # Caret: the menu opens on click.
        painter.setPen(QPen(QColor(theme.text_muted), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        x, y = self.width() - 11, self.height() / 2 + 1
        painter.drawPolyline(QPolygonF([QPointF(x - 3, y - 2), QPointF(x, y + 1), QPointF(x + 3, y - 2)]))
        if count:
            font = QFont(self.font()); font.setPixelSize(10); font.setBold(True)
            painter.setFont(font)
            text = str(count) if count < 100 else '99+'
            width = max(16., painter.fontMetrics().horizontalAdvance(text) + 8)
            badge = QRectF(6 + self.ICON - 7, 2, width, 16)
            painter.setPen(QPen(QColor(theme.surface), 2))
            painter.setBrush(QColor(theme.accent))
            painter.drawRoundedRect(badge, 8, 8)
            painter.setPen(QColor(theme.text_on_accent))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
