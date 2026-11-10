"""Menu rows with a title and a muted one-line caption, plus group headers.

2026-11-10 (user): menus listed bare commands, so people could not tell what
a command did without trying it. A ``RichMenuAction`` is an ordinary
``QAction`` (``trigger()``, ``triggered``, ``setEnabled`` and ``menu.actions()``
behave as usual) drawn as an icon, a title and a caption underneath.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QPainter, QColor
from PySide6.QtWidgets import QApplication, QMenu, QWidget, QWidgetAction

ROW_HEIGHT = 48
HEADER_HEIGHT = 26
ICON = 18
PAD = 10


def _theme():
    from .themed_icons import _active_theme
    return _active_theme(None)


def close_popup_chain() -> None:
    """Close every open popup menu (the row's menu and its parents)."""
    for _ in range(8):
        popup = QApplication.activePopupWidget()
        if not isinstance(popup, QMenu):
            return
        popup.close()


class _RichRow(QWidget):
    def __init__(self, action: "RichMenuAction", parent=None):
        super().__init__(parent)
        self._action = action
        self._hover = False
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setEnabled(action.isEnabled())
        action.changed.connect(self._sync)

    def _sync(self):
        self.setEnabled(self._action.isEnabled())
        self.setToolTip(self._action.toolTip() if self._action.toolTip() != self._action.text() else "")
        self.updateGeometry()
        self.update()

    def _fonts(self):
        title = QFont(self.font())
        title.setWeight(QFont.Weight.DemiBold)
        caption = QFont(self.font())
        caption.setPointSizeF(max(7.5, self.font().pointSizeF() - 1.5))
        return title, caption

    def sizeHint(self):
        title, caption = self._fonts()
        width = max(QFontMetrics(title).horizontalAdvance(self._action.text()),
                    QFontMetrics(caption).horizontalAdvance(self._action.caption))
        return QSize(max(250, width + PAD * 3 + ICON + 18), ROW_HEIGHT)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled() and self.rect().contains(event.position().toPoint()):
            close_popup_chain()
            self._action.trigger()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        if self._hover and enabled:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.selected))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(4, 1, -4, -1), 8, 8)
        icon: QIcon = self._action.icon()
        x = PAD + 4
        if not icon.isNull():
            mode = QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled
            icon.paint(painter, x, (self.height() - ICON) // 2, ICON, ICON, Qt.AlignmentFlag.AlignCenter, mode)
        x += ICON + PAD
        title, caption = self._fonts()
        width = self.width() - x - PAD
        painter.setFont(title)
        painter.setPen(QColor(theme.text if enabled else theme.disabled))
        painter.drawText(QRectF(x, 6, width, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(title).elidedText(self._action.text(), Qt.TextElideMode.ElideRight, int(width)))
        painter.setFont(caption)
        painter.setPen(QColor(theme.text_muted if enabled else theme.disabled))
        painter.drawText(QRectF(x, 25, width, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(caption).elidedText(self._action.caption, Qt.TextElideMode.ElideRight, int(width)))


class RichMenuAction(QWidgetAction):
    """A command row: icon, title and a muted caption on the second line."""

    def __init__(self, icon: QIcon, text: str, caption: str, parent=None):
        super().__init__(parent)
        self.setIcon(icon)
        self.setText(text)
        self.caption = caption

    def set_caption(self, caption: str) -> None:
        self.caption = caption
        self.changed.emit()

    def createWidget(self, parent):
        return _RichRow(self, parent)


class _Header(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text

    def sizeHint(self):
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self._text) + PAD * 3, HEADER_HEIGHT)

    def paintEvent(self, _event):
        theme = _theme()
        painter = QPainter(self)
        font = QFont(self.font())
        font.setPointSizeF(max(7.5, self.font().pointSizeF() - 1.5))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(theme.accent_text))
        painter.drawText(QRectF(PAD + 4, 6, self.width() - PAD * 2, HEADER_HEIGHT - 6),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)


class MenuHeaderAction(QWidgetAction):
    """A non-interactive group title inside a menu."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setEnabled(False)

    def createWidget(self, parent):
        return _Header(self.text(), parent)


def add_header(menu: QMenu, text: str) -> MenuHeaderAction:
    action = MenuHeaderAction(text, menu)
    menu.addAction(action)
    return action


def add_rich(menu: QMenu, icon: QIcon, text: str, caption: str, slot=None) -> RichMenuAction:
    action = RichMenuAction(icon, text, caption, menu)
    if slot is not None:
        action.triggered.connect(lambda _checked=False: slot())
    menu.addAction(action)
    return action
