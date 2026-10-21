"""Small widgets of the term library page (2026-10-17 redesign).

Plan: docs/exec-plans/active/2026-10-17-glossary-page-redesign.md.  The page
keeps its older control names (tests and acceptance scripts click them); the
redesign only moves rarely used controls into ``ActionPopup`` menus.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget

from ..i18n import bind_text


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


class PageTab(QAbstractButton):
    """A large underline tab (v2 of the redesign): the label, a quiet count
    beside it and an optional accent note ("1 个可更新").  ``setCount`` and
    ``setNote`` take display text, so ``bind_text(tab, ..., property="count")``
    keeps them translated."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._count = ""
        self._note = ""
        self._hovered = False

    def setCount(self, text: str):  # noqa: N802 - Qt-style setter for bind_text
        self._count = str(text or "")
        self.updateGeometry()
        self.update()

    def count(self) -> str:
        return self._count

    def setNote(self, text: str):  # noqa: N802 - Qt-style setter for bind_text
        self._note = str(text or "")
        self.updateGeometry()
        self.update()

    def note(self) -> str:
        return self._note

    def _fonts(self) -> tuple[QFont, QFont]:
        label = QFont(self.font())
        label.setPixelSize(16)
        label.setWeight(QFont.Weight.Bold if self.isChecked() else QFont.Weight.DemiBold)
        small = QFont(self.font())
        small.setPixelSize(13)
        small.setWeight(QFont.Weight.Medium)
        return label, small

    def sizeHint(self):  # noqa: N802 - Qt API
        label, small = self._fonts()
        bold = QFont(label)
        bold.setWeight(QFont.Weight.Bold)
        width = QFontMetrics(bold).horizontalAdvance(self.text()) + 4
        for part in (self._count, self._note):
            if part:
                width += 8 + QFontMetrics(small).horizontalAdvance(part)
        return QSize(width, QFontMetrics(bold).height() + 14)

    def enterEvent(self, event):  # noqa: N802 - Qt API
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt API
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):  # noqa: N802 - Qt API
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        label, small = self._fonts()
        metrics = QFontMetrics(label)
        baseline = metrics.ascent() + 2
        x = 2
        active = self.isChecked()
        painter.setFont(label)
        painter.setPen(QColor(theme.text if active or self._hovered else theme.text_secondary))
        painter.drawText(x, baseline, self.text())
        x += metrics.horizontalAdvance(self.text()) + 8
        painter.setFont(small)
        small_metrics = QFontMetrics(small)
        for part, color in ((self._count, theme.text_muted), (self._note, theme.accent)):
            if part:
                painter.setPen(QColor(color))
                painter.drawText(x, baseline, part)
                x += small_metrics.horizontalAdvance(part) + 8
        if active:
            painter.fillRect(QRect(0, self.height() - 2, self.width(), 2), QColor(theme.accent))
        elif self.hasFocus():
            painter.fillRect(QRect(0, self.height() - 1, self.width(), 1), QColor(theme.focus))
        painter.end()


class StatusDotDelegate(QStyledItemDelegate):
    """Term status as a small colored dot and text (v2: no pills in the table)."""

    def paint(self, painter, option, index):
        theme = _theme()
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(theme.selected))
        status = str(index.data(Qt.ItemDataRole.UserRole + 2) or "reference")
        dot = {"confirmed": theme.success, "hidden": theme.disabled}.get(status, theme.text_muted)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_y = option.rect.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(dot))
        painter.drawEllipse(QPoint(option.rect.x() + 12, center_y + 1), 3, 3)
        painter.setPen(QColor(theme.text_secondary))
        painter.setFont(option.font)
        text_rect = option.rect.adjusted(22, 0, -4, 0)
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                         str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        painter.restore()

    def sizeHint(self, option, index):
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        return QSize(option.fontMetrics.horizontalAdvance(text) + 30, 44)


class ActionPopup(QFrame):
    """A small menu under a button that holds real buttons and controls.

    Unlike a QMenu, the entries stay the page's own widgets (their names,
    enabled state and click handlers do not change), and the menu can also
    hold combo boxes, such as the AI service and model of 「AI 更新 ▾」.
    """

    def __init__(self, anchor: QAbstractButton, name: str = "termActionPopup", *, min_width: int = 240):
        super().__init__(anchor, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName(name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setMinimumWidth(min_width)
        self.anchor = anchor
        self._hidden_at = 0.0
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(2)
        anchor.clicked.connect(self.toggle)

    def add_button(self, button: QAbstractButton, *, danger: bool = False, close: bool = True) -> QAbstractButton:
        button.setObjectName("termPopupItemDanger" if danger else "termPopupItem")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._layout.addWidget(button)
        if close:
            button.clicked.connect(self.hide)
        return button

    def add_caption(self, text: str) -> QLabel:
        label = bind_text(QLabel(), text)
        label.setObjectName("termPopupCaption")
        self._layout.addWidget(label)
        return label

    def add_widget(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def add_separator(self) -> QFrame:
        line = QFrame()
        line.setObjectName("termPopupSeparator")
        line.setFixedHeight(1)
        self._layout.addWidget(line)
        return line

    def hideEvent(self, event):  # noqa: N802 - Qt API
        self._hidden_at = time.monotonic()
        super().hideEvent(event)

    def toggle(self):
        if self.isVisible():
            self.hide()
        elif time.monotonic() - self._hidden_at > 0.25:
            # A press on the anchor already closed the popup (Qt closes a
            # popup on any outside press); its click must not reopen it.
            self.show_below()

    def show_below(self):
        self.adjustSize()
        point = self.anchor.mapToGlobal(QPoint(0, self.anchor.height() + 4))
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = min(max(area.left(), point.x()), area.right() - self.width())
            y = point.y()
            if y + self.height() > area.bottom():
                y = self.anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4
            point = QPoint(x, max(area.top(), y))
        self.move(point)
        self.show()
        self.raise_()
