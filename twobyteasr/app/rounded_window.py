"""Frameless top-level window with slightly rounded corners and its own title bar.

2026-10-26 (user, link download window): replace the Windows title bar and
give the window slightly rounded corners, like the rest of the product.

Windows 10 draws no rounded corners for us, so the window is translucent: the
content sits inside a margin where a soft shadow is painted, and an overlay on
top of the content clears the four corners with antialiasing (whatever square
backgrounds lie underneath) and draws the 1 px border. Maximized, the margin,
shadow and corners go away. The window maximizes itself (fills the screen's
work area, remembers its size): Windows only moves a frameless dialog to the
corner and keeps its size (10-26, real window). Edges resize through the system (thin handles
over the border); the title areas move the window and double-click maximizes.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

RADIUS = 12
SHADOW = 16
GRIP = 6


def _theme():
    from ..design.theme_manager import theme_definition, theme_key
    return theme_definition(theme_key())


class _CornerMask(QWidget):
    """Clears the corners outside the rounded content and draws its border."""

    def __init__(self, window: QWidget, radius: int, shadow_painter):
        super().__init__(window)
        self.radius = radius
        self.shadow_painter = shadow_painter
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

    def paintEvent(self, event):
        from .ui_zoom import px
        radius = px(self.radius)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rounded = QPainterPath()
        rounded.addRoundedRect(rect, radius, radius)
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        corners = outside.subtracted(rounded)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillPath(corners, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        # The shadow under the cleared corners, as the window painted it there.
        painter.save()
        painter.setClipPath(corners)
        self.shadow_painter(painter, QRectF(self.rect()))
        painter.restore()
        painter.setPen(QPen(QColor(_theme().border_strong), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(rounded)
        painter.end()


class _Grip(QWidget):
    """An edge or corner the system resizes the window from."""

    def __init__(self, window: QWidget, edges, cursor):
        super().__init__(window)
        self.window_ = window
        self.edges = edges
        self.setCursor(cursor)

    def paintEvent(self, event):
        # Almost transparent, never fully: a layered window passes clicks
        # through pixels whose alpha is 0.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        painter.end()

    def mousePressEvent(self, event):
        handle = self.window_.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None and handle.startSystemResize(self.edges):
            event.accept()
            return
        super().mousePressEvent(event)


class WindowButtons(QWidget):
    """Maximize / restore and close, styled like the main window's controls."""

    def __init__(self, window: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.window_ = window
        self.on_toggle = None      # set by RoundedWindow
        self.is_maximized = window.isMaximized
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.maximize_button = self._button("fa5s.square", "最大化", self.toggle_maximized)
        self.close_button = self._button("fa5s.times", "关闭", window.close, close=True)
        row.addWidget(self.maximize_button)
        row.addWidget(self.close_button)

    def _button(self, icon, tip, callback, *, close=False):
        from ..design.themed_icons import install_themed_icon
        from ..i18n import bind_text
        button = QPushButton()
        button.setObjectName("windowControlClose" if close else "windowControl")
        install_themed_icon(button, icon, "window_control")
        button.setIconSize(QSize(12, 12))
        button.setFixedSize(40, 30)
        bind_text(button, tip, property="toolTip")
        bind_text(button, tip, property="accessibleName")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    def toggle_maximized(self):
        if callable(self.on_toggle):
            self.on_toggle()
        elif self.window_.isMaximized():
            self.window_.showNormal()
        else:
            self.window_.showMaximized()

    def sync(self):
        from ..design.themed_icons import install_themed_icon
        from ..i18n import bind_text
        maximized = self.is_maximized()
        install_themed_icon(self.maximize_button, "fa5s.compress-alt" if maximized else "fa5s.square", "window_control")
        tip = "还原窗口" if maximized else "最大化"
        bind_text(self.maximize_button, tip, property="toolTip")
        bind_text(self.maximize_button, tip, property="accessibleName")


class RoundedWindow(QObject):
    """Make ``window`` (a top-level QWidget whose layout holds ``content``)
    frameless and rounded. ``title_areas`` move it; call before it is shown."""

    def __init__(self, window: QWidget, content: QWidget, title_areas=(), buttons: WindowButtons | None = None,
                 *, radius: int = RADIUS, shadow: int = SHADOW):
        super().__init__(window)
        self.window = window
        self.content = content
        self.radius = radius
        self.shadow = shadow
        self.buttons = buttons
        self.title_areas = list(title_areas)
        self.maximized = False
        self._normal: QRect | None = None
        if buttons is not None:
            buttons.on_toggle = self.toggle_maximized
            buttons.is_maximized = lambda: self.maximized
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.mask = _CornerMask(window, radius, self._shadow_layers)
        edges = Qt.Edge
        cursors = Qt.CursorShape
        self.grips = {
            "left": _Grip(window, edges.LeftEdge, cursors.SizeHorCursor),
            "right": _Grip(window, edges.RightEdge, cursors.SizeHorCursor),
            "top": _Grip(window, edges.TopEdge, cursors.SizeVerCursor),
            "bottom": _Grip(window, edges.BottomEdge, cursors.SizeVerCursor),
            "top_left": _Grip(window, edges.TopEdge | edges.LeftEdge, cursors.SizeFDiagCursor),
            "bottom_right": _Grip(window, edges.BottomEdge | edges.RightEdge, cursors.SizeFDiagCursor),
            "top_right": _Grip(window, edges.TopEdge | edges.RightEdge, cursors.SizeBDiagCursor),
            "bottom_left": _Grip(window, edges.BottomEdge | edges.LeftEdge, cursors.SizeBDiagCursor),
        }
        window.installEventFilter(self)
        for area in self.title_areas:
            area.installEventFilter(self)
        self._sync()

    # --------------------------------------------------------------- state
    def margin(self) -> int:
        from .ui_zoom import px
        return 0 if self.maximized or self.window.isFullScreen() else px(self.shadow)

    def toggle_maximized(self):
        if self.maximized:
            self.maximized = False
            self._sync()
            if self._normal is not None:
                self.window.setGeometry(self._normal)
        else:
            self._normal = self.window.geometry()
            screen = self.window.screen() or QGuiApplication.primaryScreen()
            self.maximized = True
            self._sync()
            self.window.setGeometry(screen.availableGeometry())
        self._sync()

    def _sync(self):
        margin = self.margin()
        layout = self.window.layout()
        if layout is not None:
            layout.setContentsMargins(margin, margin, margin, margin)
        rounded = margin > 0
        self.mask.setVisible(rounded)
        for grip in self.grips.values():
            grip.setVisible(rounded)
        if self.buttons is not None:
            self.buttons.sync()
        self._place()
        self.window.update()

    def _place(self):
        rect = self.content_rect()
        self.mask.setGeometry(rect)
        self.mask.raise_()
        g = GRIP
        outer = rect.adjusted(-g + 2, -g + 2, g - 2, g - 2)
        x0, y0, x1, y1 = outer.left(), outer.top(), outer.right(), outer.bottom()
        places = {
            "left": QRect(x0, y0 + g, g, outer.height() - 2 * g),
            "right": QRect(x1 - g + 1, y0 + g, g, outer.height() - 2 * g),
            "top": QRect(x0 + g, y0, outer.width() - 2 * g, g),
            "bottom": QRect(x0 + g, y1 - g + 1, outer.width() - 2 * g, g),
            "top_left": QRect(x0, y0, g, g),
            "top_right": QRect(x1 - g + 1, y0, g, g),
            "bottom_left": QRect(x0, y1 - g + 1, g, g),
            "bottom_right": QRect(x1 - g + 1, y1 - g + 1, g, g),
        }
        for name, grip in self.grips.items():
            grip.setGeometry(places[name])
            grip.raise_()

    def content_rect(self) -> QRect:
        margin = self.margin()
        return self.window.rect().adjusted(margin, margin, -margin, -margin)

    # -------------------------------------------------------------- events
    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.window:
            if kind == QEvent.Type.Paint and self.margin():
                self._paint_shadow()
            elif kind == QEvent.Type.WindowStateChange:
                self._sync()
            elif kind in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
                self._place()
            return False
        if kind == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            return True
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            handle = self.window.windowHandle()
            if handle is not None and not self.maximized:
                handle.startSystemMove()
                return True
        return False

    def _paint_shadow(self):
        painter = QPainter(self.window)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._shadow_layers(painter, QRectF(self.content_rect()))
        painter.end()

    def _shadow_layers(self, painter: QPainter, rect: QRectF):
        """A soft shadow around ``rect`` (the content), slightly below it."""
        from .ui_zoom import px
        radius = px(self.radius)
        steps = max(1, self.margin())
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(steps, 0, -1):
            strength = (1 - step / (steps + 1)) ** 2
            painter.setBrush(QColor(40, 26, 14, int(26 * strength)))
            grown = rect.adjusted(-step, -step + 3, step, step + 3)
            painter.drawRoundedRect(grown, radius + step, radius + step)
