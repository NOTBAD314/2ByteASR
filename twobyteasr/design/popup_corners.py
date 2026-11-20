"""Rounded corners for every popup window (menus, combo lists, tool tips).

Qt draws ``border-radius`` inside a popup, but the native window behind it
stays square, so menus showed hard corners around a rounded inner box
(2026-11-09). On Windows 11 the window manager can round the window itself
and draw a matching 1px edge; this filter asks for that whenever a popup is
about to show. On Windows 10, a window region provides the rounded shape.

2026-11-19 (user, on Windows 10: the tutorial window is square and sharp, it looks bad): Windows
10 has no rounding of its own, so every dialog and popup there was a hard rectangle around a
rounded inside. There the window is now cut to a rounded shape (a window region, kept to the
window's size); the edge is not smoothed, but the corners are round. ``TWOBYTEASR_ROUND_REGION=1``
uses this on Windows 11 too (to check it), ``=0`` turns it off.

Popups that paint their own translucent shape are left alone: rounding their
transparent margin would draw an edge around nothing.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWCP_ROUND = 2


def _windows_supports_rounding() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False


def _colorref(hex_color: str) -> int:
    value = hex_color.lstrip("#")[:6]
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def round_native_window(widget: QWidget, border_color: str | None) -> bool:
    """Ask Windows 11 to round ``widget``'s window (Windows 10: cut it round); returns whether it applied."""
    choice = os.environ.get('TWOBYTEASR_ROUND_REGION', '')
    if sys.platform == 'win32' and (choice == '1' or (choice != '0' and not _windows_supports_rounding())):
        return round_with_region(widget)
    if not _windows_supports_rounding():
        return False
    import ctypes
    from ctypes import wintypes

    try:
        hwnd = wintypes.HWND(int(widget.winId()))
        dwm = ctypes.windll.dwmapi
        corner = ctypes.c_int(_DWMWCP_ROUND)
        if dwm.DwmSetWindowAttribute(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE,
                                     ctypes.byref(corner), ctypes.sizeof(corner)) != 0:
            return False
        if border_color:
            color = wintypes.DWORD(_colorref(border_color))
            dwm.DwmSetWindowAttribute(hwnd, _DWMWA_BORDER_COLOR,
                                      ctypes.byref(color), ctypes.sizeof(color))
        return True
    except Exception:
        return False


REGION_RADIUS = 12          # logical px, the radius Windows 11 uses for its rounded windows


class _RegionKeeper(QObject):
    """Keeps a window's rounded region matching its size (a region is in pixels and fixed)."""

    def __init__(self, widget: QWidget, radius: int):
        super().__init__(widget)
        self.widget = widget
        self.radius = radius
        self._size = None
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        if watched is self.widget and event.type() in (QEvent.Type.Resize, QEvent.Type.Show,
                                                       QEvent.Type.WindowStateChange):
            self.apply()
        return False

    def apply(self) -> bool:
        widget = self.widget
        if not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return False
        try:
            import ctypes
            from ctypes import wintypes
            ratio = widget.devicePixelRatioF() or 1.0
            width, height = round(widget.width() * ratio), round(widget.height() * ratio)
            full = widget.isMaximized() or widget.isFullScreen()
            key = (width, height, full)
            if key == self._size:
                return True
            self._size = key
            hwnd = wintypes.HWND(int(widget.winId()))
            user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
            gdi.CreateRoundRectRgn.restype = wintypes.HRGN
            user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
            if full:
                applied = bool(user.SetWindowRgn(hwnd, None, True))
            else:
                diameter = max(2, round(self.radius * 2 * ratio))
                region = gdi.CreateRoundRectRgn(0, 0, width + 1, height + 1, diameter, diameter)
                applied = bool(region) and bool(user.SetWindowRgn(hwnd, region, True))
                if region and not applied:
                    gdi.DeleteObject(wintypes.HANDLE(region))
            if not applied:
                self._size = None
            return applied
        except Exception:  # noqa: BLE001
            self._size = None
            return False


def round_with_region(widget: QWidget, radius: int = REGION_RADIUS) -> bool:
    """Cut ``widget``'s window to a rounded shape that follows its size (Windows 10)."""
    if widget is None or not widget.isWindow() or widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
        return False
    keeper = getattr(widget, '_rounded_region', None)
    if keeper is None:
        keeper = widget._rounded_region = _RegionKeeper(widget, radius)
    return keeper.apply()


def _is_plain_popup(widget: QWidget) -> bool:
    if not widget.isWindow():
        return False
    kind = widget.windowType()
    if kind not in (Qt.WindowType.Popup, Qt.WindowType.ToolTip):
        return False
    return not widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


class RoundedPopupFilter(QObject):
    """Application event filter that rounds popups just before they show."""

    def __init__(self, parent=None, border_color: str | None = None):
        super().__init__(parent)
        self.border_color = border_color

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
            if _is_plain_popup(watched):
                round_native_window(watched, self.border_color)
        return False


def install_rounded_popups(app, border_color: str | None) -> None:
    """Install once per application; later calls only update the edge colour."""
    if sys.platform != "win32":
        return
    existing = getattr(app, "_rounded_popup_filter", None)
    if existing is not None:
        existing.border_color = border_color
        return
    app._rounded_popup_filter = RoundedPopupFilter(app, border_color)
    from .app_events import listen
    listen(app._rounded_popup_filter, (QEvent.Type.Show,))
