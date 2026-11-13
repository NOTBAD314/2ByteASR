"""The home page's 说明 menu: a round, friendly card with 兔白 on top (2026-11-11).

User: the menu should look rounder and cuter, and only keep what people come
for: the tutorial, the sample project, choosing the recognition plan, the
diagnostics and the workbench hints (API setup, the API key explainer,
feature search and shortcuts have their own places elsewhere).

Each row is an ordinary ``QAction`` (``menu.actions()``, ``trigger()``) drawn
as a pastel icon bubble, a title and a one-line caption; the highlighted row
(mouse or arrow keys) gets a soft pill. The card paints its own rounded
background and shadow on a translucent popup, so the corners are really round.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QMenu, QWidget, QWidgetAction

from ..i18n import tr
from ..design.typography import weighted_font

SHADOW = 10
RADIUS = 22
ROW_HEIGHT = 54
BUBBLE = 34
HUES = ('#a07cc8', '#e48a63', '#4f9bd9', '#58ad8a', '#d6a13a', '#d4708f')


def _theme():
    from ..design.theme_manager import theme_key
    from ..design.ui_theme import theme_definition
    return theme_definition(theme_key())


def _light(theme) -> bool:
    return QColor(theme.surface_elevated).lightness() > 128


class _Row(QWidget):
    def __init__(self, action: 'CuteMenuAction', parent=None):
        super().__init__(parent)
        self._action = action
        self._hover = False
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _fonts(self):
        title = QFont(self.font())
        title.setPixelSize(14)
        weighted_font(title, QFont.Weight.DemiBold)
        caption = QFont(self.font())
        caption.setPixelSize(12)
        return title, caption

    def sizeHint(self):  # noqa: N802 - Qt override
        title, caption = self._fonts()
        width = max(QFontMetrics(title).horizontalAdvance(self._action.text()),
                    QFontMetrics(caption).horizontalAdvance(self._action.caption))
        return QSize(max(272, width + BUBBLE + 52), ROW_HEIGHT)

    def enterEvent(self, event):  # noqa: N802 - Qt override
        self._hover = True
        menu = self.parentWidget()
        if isinstance(menu, QMenu):
            menu.setActiveAction(self._action)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            menu = self.parentWidget()
            if isinstance(menu, QMenu):
                menu.close()
            self._action.trigger()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        from ..design.themed_icons import cached_icon_pixmap
        from ..design.ui_theme import blend_hex
        theme = _theme()
        light = _light(theme)
        menu = self.parentWidget()
        active = self._hover or (isinstance(menu, QMenu) and menu.activeAction() is self._action)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(blend_hex(theme.surface_elevated, theme.accent, 0.13 if light else 0.22)))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 18, 18)
        hue = self._action.hue
        top = (self.height() - BUBBLE) / 2
        circle = QRectF(10, top, BUBBLE, BUBBLE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(blend_hex(theme.surface_elevated, hue, 0.24 if light else 0.34)))
        painter.drawEllipse(circle)
        glyph = blend_hex(hue, '#000000', 0.18) if light else blend_hex(hue, '#ffffff', 0.25)
        ratio = self.devicePixelRatioF()
        icon = cached_icon_pixmap(self._action.icon_name, glyph, QSize(16, 16), device_pixel_ratio=ratio)
        painter.drawPixmap(round(circle.center().x() - 8), round(circle.center().y() - 8), icon)
        title, caption = self._fonts()
        x = circle.right() + 12
        width = self.width() - x - 12
        painter.setFont(title)
        painter.setPen(QColor(theme.text))
        painter.drawText(QRectF(x, 8, width, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(title).elidedText(self._action.text(), Qt.TextElideMode.ElideRight, int(width)))
        painter.setFont(caption)
        painter.setPen(QColor(theme.text_muted))
        painter.drawText(QRectF(x, 28, width, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(caption).elidedText(self._action.caption, Qt.TextElideMode.ElideRight, int(width)))
        painter.end()


class CuteMenuAction(QWidgetAction):
    """A row: pastel icon bubble, title, caption. ``text()`` is the title."""

    def __init__(self, text: str, caption: str, icon_name: str, hue: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.caption = caption
        self.icon_name = icon_name
        self.hue = hue

    def createWidget(self, parent):  # noqa: N802 - Qt override
        return _Row(self, parent)


class _Hello(QWidget):
    """兔白's face and a hello on top of the menu."""

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(272, 62)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        from ..design.bunny_mascot import bunny_face_pixmap
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ratio = self.devicePixelRatioF()
        face = bunny_face_pixmap(42, ratio)
        circle = QRectF(6, 8, 42, 42)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.accent))
        painter.drawEllipse(circle.adjusted(-2, -2, 2, 2))
        painter.drawPixmap(circle.topLeft().toPoint(), face)
        title = QFont(self.font())
        title.setPixelSize(15)
        weighted_font(title, QFont.Weight.Bold)
        caption = QFont(self.font())
        caption.setPixelSize(12)
        x = circle.right() + 12
        painter.setFont(title)
        painter.setPen(QColor(theme.text))
        painter.drawText(QRectF(x, 10, self.width() - x, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         str(tr('需要帮忙吗？')))
        painter.setFont(caption)
        painter.setPen(QColor(theme.accent_text))
        painter.drawText(QRectF(x, 30, self.width() - x, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         str(tr('兔白在这儿，点一项就好～')))
        painter.end()


class _Dots(QWidget):
    """A row of little dots instead of a hard separator line."""

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(120, 14)

    def paintEvent(self, _event):  # noqa: N802 - Qt override
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.hairline))
        x, y = 18.0, self.height() / 2
        while x < self.width() - 18:
            painter.drawEllipse(QRectF(x - 1.5, y - 1.5, 3, 3))
            x += 9
        painter.end()


class _Still(QWidgetAction):
    def __init__(self, widget_type, parent=None):
        super().__init__(parent)
        self._widget_type = widget_type
        self.setEnabled(False)

    def createWidget(self, parent):  # noqa: N802 - Qt override
        return self._widget_type(parent)


class CuteMenu(QMenu):
    """A translucent popup that paints a round card with a soft shadow under its rows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('helpMenu')
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(f"QMenu#helpMenu {{ background: transparent; border: 0;"
                           f" padding: {SHADOW + 8}px {SHADOW + 6}px {SHADOW + 10}px {SHADOW + 6}px; }}")
        self.hovered.connect(lambda _action: self._repaint_rows())

    def _repaint_rows(self):
        for child in self.findChildren(_Row):
            child.update()

    def add_row(self, text: str, caption: str, icon_name: str, slot=None) -> CuteMenuAction:
        rows = [a for a in self.actions() if isinstance(a, CuteMenuAction)]
        action = CuteMenuAction(str(tr(text)), str(tr(caption)), icon_name, HUES[len(rows) % len(HUES)], self)
        if slot is not None:
            action.triggered.connect(lambda _checked=False: slot())
        self.addAction(action)
        return action

    def add_hello(self):
        self.addAction(_Still(_Hello, self))

    def add_dots(self):
        self.addAction(_Still(_Dots, self))

    def paintEvent(self, event):  # noqa: N802 - Qt override
        from ..design.ui_theme import blend_hex
        theme = _theme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(SHADOW, SHADOW - 2, -SHADOW, -SHADOW - 2)
        painter.setPen(Qt.PenStyle.NoPen)
        for spread, alpha in ((10, 14), (6, 22), (3, 30)):
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(card.adjusted(-spread / 2, -spread / 2 + 3, spread / 2, spread / 2 + 4),
                                    RADIUS + spread / 2, RADIUS + spread / 2)
        path = QPainterPath()
        path.addRoundedRect(card, RADIUS, RADIUS)
        painter.fillPath(path, QColor(theme.surface_elevated))
        pen = QColor(blend_hex(theme.surface_elevated, theme.accent, 0.35))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.end()
        super().paintEvent(event)


__all__ = ['CuteMenu', 'CuteMenuAction']
