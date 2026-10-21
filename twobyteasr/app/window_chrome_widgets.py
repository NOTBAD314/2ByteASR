"""Main-window chrome: the in-header title bar with window controls, the
hoverable brand label and the edge handles that hand resizing to the OS.

Split out of ``app/ui.py`` on 2026-10-15; ``ui`` still exports these names.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ..design.themed_icons import install_themed_icon
from ..i18n import bind_text


class BrandLabel(QLabel):
    hover_entered = Signal()
    hover_left = Signal()

    def enterEvent(self, event):
        self.hover_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit()
        super().leaveEvent(event)


class WindowTitleBar(QFrame):
    """Native-looking window controls without a native, dark title strip.

    Keeping this small bar inside ``appHeader`` gives the desktop shell one
    visual surface while retaining the expected move/minimize/maximize/close
    behaviour for a Windows tool.
    """

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setObjectName("windowTitleBar")
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 1, 8, 1)
        row.setSpacing(4)
        # The product brand belongs to the main header below.  Keeping the
        # draggable chrome intentionally quiet prevents a duplicate wordmark
        # while the title bar still reads as part of the same warm surface.
        self.title = QLabel("2ByteASR  兔白字幕")
        self.title.setObjectName("windowChromeTitle")
        self.title.hide()
        row.addStretch(1)

        self.minimize_button = self._control_button(
            "fa5s.minus", "最小化", self._window.showMinimized
        )
        self.maximize_button = self._control_button(
            "fa5s.square", "最大化", self.toggle_maximized
        )
        self.close_button = self._control_button(
            "fa5s.times", "关闭", self._window.close, close=True
        )
        row.addWidget(self.minimize_button)
        row.addWidget(self.maximize_button)
        row.addWidget(self.close_button)

    def _control_button(self, icon_name: str, tooltip: str, callback, *, close: bool = False):
        button = QPushButton()
        button.setObjectName("windowControlClose" if close else "windowControl")
        install_themed_icon(button, icon_name, "window_control")
        button.setIconSize(QSize(12, 12))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def set_title(self, text: str):
        self.title.setText(text)

    def toggle_maximized(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_window_state()

    def sync_window_state(self):
        maximized = self._window.isMaximized()
        install_themed_icon(
            self.maximize_button,
            "fa5s.compress-alt" if maximized else "fa5s.square",
            "window_control",
        )
        (bind_text(self.maximize_button, '还原窗口', property='toolTip') if maximized else bind_text(self.maximize_button, '最大化', property='toolTip'))
        self.maximize_button.setAccessibleName(self.maximize_button.toolTip())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            if self._window.isMaximized():
                # 2026-10-15: a click (or the first click of a double-click)
                # no longer restores the window; dragging past the drag
                # distance does, under the cursor (window_constraints).
                from .window_constraints import begin_title_drag
                self._drag_offset = None
                begin_title_drag(self._window, global_pos, event.position().y())
            else:
                self._drag_offset = global_pos - self._window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _NativeResizeHandle(QWidget):
    """Thin edge overlay that delegates resizing to the window manager."""

    def __init__(self, owner: QWidget, edges: Qt.Edge, cursor: Qt.CursorShape):
        super().__init__(owner)
        self.owner = owner
        self.edges = edges
        self.setCursor(cursor)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent; border: 0;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.owner.isMaximized():
            handle = self.owner.windowHandle()
            if handle is not None and handle.startSystemResize(self.edges):
                event.accept()
                return
        super().mousePressEvent(event)
