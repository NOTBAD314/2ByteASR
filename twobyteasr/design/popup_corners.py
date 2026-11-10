"""Rounded corners for every popup window (menus, combo lists, tool tips).

Qt draws ``border-radius`` inside a popup, but the native window behind it
stays square, so menus showed hard corners around a rounded inner box
(2026-11-09). On Windows 11 the window manager can round the window itself
and draw a matching 1px edge; this filter asks for that whenever a popup is
about to show. Older Windows and other platforms simply keep square popups.

Popups that paint their own translucent shape are left alone: rounding their
transparent margin would draw an edge around nothing.
"""

from __future__ import annotations

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
    """Ask Windows 11 to round ``widget``'s window; returns whether it applied."""
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
    if not _windows_supports_rounding():
        return
    existing = getattr(app, "_rounded_popup_filter", None)
    if existing is not None:
        existing.border_color = border_color
        return
    app._rounded_popup_filter = RoundedPopupFilter(app, border_color)
    app.installEventFilter(app._rounded_popup_filter)
