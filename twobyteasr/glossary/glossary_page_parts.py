"""Small widgets of the term library page (2026-10-17 redesign).

Plan: docs/exec-plans/active/2026-10-17-glossary-page-redesign.md.  The page
keeps its older control names (tests and acceptance scripts click them); the
redesign only moves rarely used controls into ``ActionPopup`` menus.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import (QAbstractButton, QFrame, QLabel, QLayout, QPushButton, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from ..i18n import bind_text
from ..design.typography import weighted_font


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
        weighted_font(label, QFont.Weight.Bold if self.isChecked() else QFont.Weight.DemiBold)
        small = QFont(self.font())
        small.setPixelSize(13)
        weighted_font(small, QFont.Weight.Medium)
        return label, small

    def sizeHint(self):  # noqa: N802 - Qt API
        label, small = self._fonts()
        bold = QFont(label)
        weighted_font(bold, QFont.Weight.Bold)
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


class AIMenuEntry(QPushButton):
    """One 「AI 帮忙 ▾」 entry: a tinted icon, a plain-words title, one line on
    what it does, and an optional badge (🔒 要能上网 / a count).

    2026-11-13 (user, option A): the old menu listed eight mechanisms
    (增量 / 完整建库 / 智能建词 / 联网补全); entries now say what they do.
    ``text()`` / ``setText()`` are the title, so task states such as
    「更新中（查看任务）」 still replace it."""

    def __init__(self, title: str = "", subtitle: str = "", icon: str = "", tone: str = "", parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout, QSizePolicy
        self.setObjectName("termAiEntry")
        self.setProperty("tone", tone)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(12)
        self._icon_name = icon
        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("termAiEntryIcon")
        self.icon_label.setProperty("tone", tone)
        self.icon_label.setFixedSize(34, 34)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(1)
        self.title_label = QLabel(self)
        self.title_label.setObjectName("termAiEntryTitle")
        self.subtitle_label = QLabel(self)
        self.subtitle_label.setObjectName("termAiEntrySub")
        self.subtitle_label.setWordWrap(True)
        column.addWidget(self.title_label)
        column.addWidget(self.subtitle_label)
        row.addLayout(column, 1)
        self.badge = QLabel(self)
        self.badge.setObjectName("termAiEntryBadge")
        self.badge.hide()
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setText(title)
        self.setSubtitle(subtitle)
        self.refresh_icon()

    def refresh_icon(self) -> None:
        # Qt applies "Button:disabled QLabel" whatever the button's state; the
        # labels carry the state themselves.
        dim = not self.isEnabled()
        for label in (self.title_label, self.subtitle_label):
            if bool(label.property("dim")) != dim:
                label.setProperty("dim", dim)
                label.style().unpolish(label)
                label.style().polish(label)
        if self._icon_name:
            from ..design.themed_icons import themed_icon
            self.icon_label.setPixmap(themed_icon(self._icon_name, "accent" if self.isEnabled() else "disabled")
                                      .pixmap(16, 16))

    def changeEvent(self, event):  # noqa: N802 - Qt API
        from PySide6.QtCore import QEvent
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self.refresh_icon()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt-style API
        self.title_label.setText(str(text))
        self.setAccessibleName(str(text))
        self.updateGeometry()

    def text(self) -> str:
        return self.title_label.text()

    def setSubtitle(self, text: str) -> None:  # noqa: N802 - Qt-style API (bind_text property="subtitle")
        self.subtitle_label.setText(str(text))
        self.subtitle_label.setVisible(bool(text))
        self.updateGeometry()

    def subtitle(self) -> str:
        return self.subtitle_label.text()

    def setBadge(self, text: str) -> None:  # noqa: N802 - bind_text property="badge"
        self.badge.setText(str(text))
        self.badge.setVisible(bool(text))

    def set_badge(self, text: str, tone: str = "warn") -> None:
        if self.badge.property("tone") != tone:
            self.badge.setProperty("tone", tone)
            self.badge.style().unpolish(self.badge)
            self.badge.style().polish(self.badge)
        self.setBadge(text)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt API (the subtitle wraps)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt API
        layout = self.layout()
        return layout.heightForWidth(width) if layout is not None else super().heightForWidth(width)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        layout = self.layout()
        return layout.sizeHint() if layout is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        layout = self.layout()
        return layout.minimumSize() if layout is not None else super().minimumSizeHint()


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

    def add_entry(self, entry: "AIMenuEntry", *, close: bool = True) -> "AIMenuEntry":
        self._layout.addWidget(entry)
        if close:
            entry.clicked.connect(self.hide)
        return entry

    def add_caption(self, text: str) -> QLabel:
        label = bind_text(QLabel(), text)
        label.setObjectName("termPopupCaption")
        self._layout.addWidget(label)
        return label

    def add_widget(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def clear_items(self) -> None:
        while self._layout.count():
            widget = self._layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()

    def add_separator(self) -> QFrame:
        line = QFrame()
        line.setObjectName("termPopupSeparator")
        line.setFixedHeight(1)
        self._layout.addWidget(line)
        return line

    def hideEvent(self, event):  # noqa: N802 - Qt API
        self._hidden_at = time.monotonic()
        super().hideEvent(event)

    def _needed_height(self) -> int:
        """Rows at the popup's real width (wrapped entry subtitles included);
        adjustSize under-measures a menu whose rows wrap."""
        layout = self._layout
        margins = layout.contentsMargins()
        width = self.width() - margins.left() - margins.right()
        total, rows = margins.top() + margins.bottom(), 0
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item.isEmpty():
                continue
            height = max(item.minimumSize().height(), item.sizeHint().height())
            if item.hasHeightForWidth():
                height = max(item.minimumSize().height(), item.heightForWidth(width))
            total += height
            rows += 1
        return total + layout.spacing() * max(0, rows - 1)

    def toggle(self):
        if self.isVisible():
            self.hide()
        elif time.monotonic() - self._hidden_at > 0.25:
            # A press on the anchor already closed the popup (Qt closes a
            # popup on any outside press); its click must not reopen it.
            self.show_below()

    def show_below(self):
        # Polish first: style-sheet sizes (combo heights, paddings) must be
        # known before measuring, or rows overlap on the first opening.
        self.ensurePolished()
        for index in range(self._layout.count()):
            widget = self._layout.itemAt(index).widget()
            # A nested frame (the AI service bar) was squeezed below its own
            # rows once wrapped entries made the menu height-for-width.
            if widget is not None and widget.layout() is not None and not widget.hasHeightForWidth():
                widget.setMinimumHeight(widget.minimumSizeHint().height())
        self.adjustSize()
        needed = self._needed_height()
        if needed > self.height():
            self.resize(self.width(), needed)
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
        # The window theme reaches a popup when it first shows; measure again.
        for _pass in range(3):
            needed = self._needed_height()
            if needed <= self.height():
                break
            self.resize(self.width(), needed)
        self.raise_()


class StripChip(QFrame):
    """A chip of the 待处理 strip (2026-11-13, plan 2026-11-13-glossary-library-redesign-c):
    an optional colored dot and a short count ("123 条字幕候选"); dashed for
    work that is missing. Clicking emits ``clicked(checked)``; checkable chips
    act as filters and show their checked state."""

    from PySide6.QtCore import Signal as _Signal
    clicked = _Signal(bool)

    def __init__(self, text: str = "", *, tone: str = "", dashed: bool = False, checkable: bool = False, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout
        self.setObjectName("termStripChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("dashed", dashed)
        self.setProperty("checked", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(30)
        self._checkable = checkable
        row = QHBoxLayout(self)
        row.setContentsMargins(10 if tone else 12, 0, 12, 0)
        row.setSpacing(7)
        self.dot = QLabel(self)  # parented: setVisible(True) on a parentless label flashed a window (2026-11-13)
        self.dot.setObjectName("termStripDot")
        self.dot.setProperty("tone", tone)
        self.dot.setFixedSize(7, 7)
        self.dot.setVisible(bool(tone))
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.label = QLabel(text)
        self.label.setObjectName("termStripChipText")
        row.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)

    def setText(self, text: str):  # noqa: N802 - Qt-style API
        self.label.setText(text)

    def text(self) -> str:
        return self.label.text()

    def isChecked(self) -> bool:  # noqa: N802
        return bool(self.property("checked"))

    def setChecked(self, checked: bool):  # noqa: N802
        if bool(checked) != self.isChecked():
            self.setProperty("checked", bool(checked))
            for widget in (self, self.label, self.dot):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def click(self):
        if self._checkable:
            self.setChecked(not self.isChecked())
        self.clicked.emit(self.isChecked())

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.click()
        super().mouseReleaseEvent(event)


class FlowLayout(QLayout):
    """Wrapping row of small widgets (chips); items of a line share its vertical centre."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent); self._items = []; self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item): self._items.append(item)  # noqa: N802 - Qt API

    def insertWidget(self, index, widget):  # noqa: N802 - Qt-style API
        self.addWidget(widget)
        self._items.insert(max(0, min(int(index), len(self._items) - 1)), self._items.pop())
        self.invalidate()

    def count(self): return len(self._items)
    def itemAt(self, i): return self._items[i] if 0 <= i < len(self._items) else None  # noqa: N802
    def takeAt(self, i): return self._items.pop(i) if 0 <= i < len(self._items) else None  # noqa: N802
    def expandingDirections(self): return Qt.Orientation(0)  # noqa: N802
    def hasHeightForWidth(self): return True  # noqa: N802
    def heightForWidth(self, width): return self._place(QRect(0, 0, width, 0), True)  # noqa: N802
    def setGeometry(self, rect): super().setGeometry(rect); self._place(rect, False)  # noqa: N802
    def sizeHint(self): return self.minimumSize()  # noqa: N802

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items: size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect, measure):
        """Wrap into lines; items of one line share its vertical centre."""
        lines, current, x = [], [], rect.x()
        for item in self._items:
            hint = item.sizeHint()
            if current and x + hint.width() > rect.right() + 1:
                lines.append(current); current, x = [], rect.x()
            current.append((item, hint)); x += hint.width() + self._spacing
        if current: lines.append(current)
        y = rect.y()
        for line in lines:
            height = max(hint.height() for _item, hint in line)
            x = rect.x()
            for item, hint in line:
                if not measure:
                    item.setGeometry(QRect(QPoint(x, y + (height - hint.height()) // 2), hint))
                x += hint.width() + self._spacing
            y += height + self._spacing
        return max(0, y - self._spacing - rect.y())
