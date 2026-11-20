"""Small top-level windows that sit over the main window, placed in physical pixels (2026-11-19).

User (2026-11-19, three screens at 175 % / 125 % / 100 %): the 兔白 that is there by default went
to another screen, outside the app's frame; picked up at the lower right she was at once in the
upper left.

On Windows she, her chat card and her carrier are frameless tool windows above the main window
(its pages hold native child windows that would cover a child widget). They were placed with
``move(window.mapToGlobal(point))`` and dragged by ``event.globalPosition()``. Both go through
Qt's device-independent coordinates, and with different scales per screen that space is not one
plane: every screen keeps its physical origin but has its own scale, so there are gaps between
the screens, and a point is turned into pixels with the scale of the screen Qt believes the
*moved* window is on. That belief changes on its own (Windows reports a new DPI for the small
window as soon as most of it lies on the other screen, which happens where the main window
reaches over a screen edge), and then the same point lands somewhere else and the pointer's
position jumps by hundreds of pixels in the middle of a drag.

Here nothing is asked of Qt's screens. The main window's client area is read from Windows in
physical pixels, a window point is ``origin + point * scale of the main window`` (the scale its
content is really drawn at, wherever it lies), the pointer is read with ``GetCursorPos``, and the
small window is put there with ``SetWindowPos`` and kept inside the client area in pixels.

Everything returns ``None`` / ``False`` where it cannot work (not Windows, no native window yet,
the offscreen platform); the callers then use Qt's own ``move`` as before.
"""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer

SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_NOOWNERZORDER = 0x0001, 0x0004, 0x0010, 0x0200
FOLLOW_FRAME_MS = 16        # at most one place per frame while she is dragged or the window moves
FOLLOW_SHARE = 0.4          # ... and placing may take at most this share of the GUI thread

_API = None


def _api():
    global _API
    if _API is None:
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.GetClientRect.restype = wintypes.BOOL
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.GetWindowRect.restype = wintypes.BOOL
        user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user.ClientToScreen.restype = wintypes.BOOL
        user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user.GetCursorPos.restype = wintypes.BOOL
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos.restype = wintypes.BOOL
        user.IsIconic.argtypes = [wintypes.HWND]
        user.IsIconic.restype = wintypes.BOOL
        _API = user
    return _API


def _handle(widget) -> int:
    """The widget's existing native window (never creates one)."""
    if sys.platform != 'win32':
        return 0
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.platformName() != 'windows' or not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return 0
        return int(widget.internalWinId() or 0)
    except (RuntimeError, AttributeError, TypeError, ValueError):
        return 0


def _scale(window) -> float:
    try:
        return max(0.25, float(window.devicePixelRatioF()))
    except (RuntimeError, AttributeError):
        return 1.0


def client_pixels(window):
    """The main window's inside on the desktop, ``(left, top, width, height)`` in physical pixels."""
    hwnd = _handle(window)
    if not hwnd:
        return None
    from ctypes import byref, wintypes
    api = _api()
    if api.IsIconic(hwnd):
        return None
    rect, origin = wintypes.RECT(), wintypes.POINT(0, 0)
    if not api.GetClientRect(hwnd, byref(rect)) or not api.ClientToScreen(hwnd, byref(origin)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    return origin.x, origin.y, width, height


def to_pixels(frame, scale: float, point) -> tuple:
    """A window point (logical) as desktop pixels, for a client area ``frame``."""
    return frame[0] + round(point.x() * scale), frame[1] + round(point.y() * scale)


def to_window(frame, scale: float, x: float, y: float) -> QPointF:
    """Desktop pixels as a window point (logical)."""
    return QPointF((x - frame[0]) / scale, (y - frame[1]) / scale)


def keep_inside(frame, x: int, y: int, width: int, height: int) -> tuple:
    """``(x, y)`` moved so a ``width`` x ``height`` box stays in the client area (its top-left wins
    where the box is larger than the area)."""
    left, top, frame_width, frame_height = frame
    x = max(left, min(x, left + frame_width - width))
    y = max(top, min(y, top + frame_height - height))
    return x, y


def cursor_point(window):
    """Where the pointer is in ``window`` coordinates, or None. Outside the window the point is
    simply beyond its edges (also on another screen): it never jumps."""
    frame = client_pixels(window)
    at = _cursor_pixels() if frame is not None else None
    if at is None:
        return None
    return to_window(frame, _scale(window), *at)


def _cursor_pixels():
    from ctypes import byref, wintypes
    at = wintypes.POINT()
    if not _api().GetCursorPos(byref(at)):
        return None
    return at.x, at.y


def event_pixels(widget, event):
    """A mouse event's place on the desktop in physical pixels: Qt's own conversion undone with the
    screen it was made with (the one the receiving window is on), so it holds whatever that is."""
    try:
        handle = widget.window().windowHandle()
        screen = handle.screen() if handle is not None else None
        if screen is None:
            return None
        origin, factor = screen.geometry().topLeft(), float(screen.devicePixelRatio())
        seen = event.globalPosition()
        return (origin.x() + (seen.x() - origin.x()) * factor, origin.y() + (seen.y() - origin.y()) * factor)
    except (RuntimeError, AttributeError):
        return None


class Pointer:
    """The pointer through one drag over ``window``, in window coordinates.

    Made at the press on ``widget``. Where the press lies under the real pointer, the drag reads
    the real pointer in pixels from then on: nothing in it depends on which screen Qt has the
    dragged window on, which changes while it is carried across a screen edge. Events that are
    not the real pointer (tests and audits send their own) are used as they are."""

    SLACK = 48          # px between the press event and the real pointer that still count as the same

    def __init__(self, window, widget, event):
        self.window, self.widget = window, widget
        self.real = False
        self._key, self._frame = None, None
        if self._client() is not None:
            seen, at = event_pixels(widget, event), _cursor_pixels()
            self.real = (seen is not None and at is not None
                         and abs(seen[0] - at[0]) + abs(seen[1] - at[1]) <= self.SLACK)

    def _client(self):
        """The window's client area, read from Windows again only when Qt saw it move or change
        size (2026-11-19: three native calls for every mouse move of a drag)."""
        try:
            key = (self.window.geometry().getRect(), _scale(self.window))
        except RuntimeError:
            return None
        if key != self._key or self._frame is None:
            self._key, self._frame = key, client_pixels(self.window)
        return self._frame

    def at(self, event) -> QPointF:
        frame = self._client()
        if frame is not None:
            pixels = _cursor_pixels() if self.real else None
            if pixels is None:
                pixels = event_pixels(self.widget, event)
            if pixels is not None:
                return to_window(frame, _scale(self.window), *pixels)
        return QPointF(self.window.mapFromGlobal(event.globalPosition().toPoint()))


def move_over(widget, window, at: QPoint, *, inside: bool = True, size=None) -> bool:
    """Put the top-level ``widget``'s top-left on the ``window`` point ``at``; True when done here.

    ``inside`` keeps the whole widget in the window's client area, measured in pixels (the widget
    may be drawn at another scale than the window while it lies on another screen).

    ``size`` (logical, 2026-11-19): the widget's new size, set in the same ``SetWindowPos`` as the
    place, at the scale the widget is drawn at. A card that grows upward then never shows a frame
    grown downward from its old top before being moved back up."""
    frame = client_pixels(window)
    hwnd = _handle(widget)
    if frame is None or not hwnd:
        return False
    from ctypes import byref, wintypes
    api = _api()
    now = wintypes.RECT()
    if not api.GetWindowRect(hwnd, byref(now)):
        return False
    width, height = now.right - now.left, now.bottom - now.top
    resize = size is not None and (size.width(), size.height()) != (widget.width(), widget.height())
    if resize:
        own = _scale(widget)
        width, height = max(1, round(size.width() * own)), max(1, round(size.height() * own))
    x, y = to_pixels(frame, _scale(window), at)
    if inside:
        x, y = keep_inside(frame, x, y, width, height)
    if not resize and (x, y) == (now.left, now.top):
        return True
    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER | (0 if resize else SWP_NOSIZE)
    if not api.SetWindowPos(hwnd, None, x, y, width, height, flags):
        return False
    if resize and (widget.width(), widget.height()) != (size.width(), size.height()):
        widget.resize(size)          # Qt's own record, should the native change reach it later (no move)
    return True


def no_system_animation(widget) -> bool:
    """Windows does not animate this top-level window in or out (its own fade is the motion).

    A picture window that appears over the page and fades out must be there in full at once: with
    the system's opening animation it faded *in* over what was already shown, which looked like
    the old page flashing back."""
    hwnd = _handle(widget)
    if not hwnd:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        dwm = ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        off = ctypes.c_int(1)
        return dwm.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(off), ctypes.sizeof(off)) == 0   # TRANSITIONS_FORCEDISABLED
    except (OSError, AttributeError):
        return False


class Coalesced:
    """``apply`` (a place) run at most once per frame, never inside the event that asked for it.

    2026-11-19 (user, three screens at 175 % / 125 % / 100 %, a page with the embedded mpv video):
    opening a project in the workbench froze the window for up to 1.6 s, and most samples were in
    ``SetWindowPos`` from 兔白's drag, one per mouse move. Moving her window under the pointer
    makes Windows send another mouse move, so with costly native moves the queue never ran dry
    and nothing else (the video's timers, her own animation) got a turn.

    Requests in between only ask for the newest state: ``apply`` reads where she should be when
    it runs. The gap grows with what the last place cost, so placing never takes more than
    ``FOLLOW_SHARE`` of the GUI thread however slow the native move is on that machine."""

    def __init__(self, owner, apply):
        self._apply = apply
        self._timer = QTimer(owner)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._run)
        self._last = -1e9
        self._cost = 0.0
        self.runs = 0

    def request(self):
        if self._timer.isActive():
            return
        gap = max(FOLLOW_FRAME_MS / 1000.0, self._cost / FOLLOW_SHARE)
        wait = gap - (time.perf_counter() - self._last)
        self._timer.start(max(0, int(wait * 1000 + 0.5)))

    def pending(self) -> bool:
        return self._timer.isActive()

    def cancel(self):
        self._timer.stop()

    def flush(self):
        """What is still waiting, now (a drag that ended, a window about to be shown)."""
        if self._timer.isActive():
            self._timer.stop()
            self._run()

    def _run(self):
        started = time.perf_counter()
        try:
            self._apply()
        except RuntimeError:            # the widget is already gone
            return
        finally:
            self.runs += 1
        self._last = started
        self._cost = time.perf_counter() - started


def place(widget, window, at: QPoint, *, inside: bool = True, size=None):
    """``widget`` (a top-level over ``window``) at the window point ``at``: in pixels where that
    works, else by Qt. ``size``: its new size, in the same step (``move_over``)."""
    if move_over(widget, window, at, inside=inside, size=size):
        return
    if size is not None and widget.size() != size:
        widget.setGeometry(QRect(window.mapToGlobal(at), size))
    else:
        widget.move(window.mapToGlobal(at))


def cover_window(widget, window):
    """Lay the top-level ``widget`` exactly over the ``window``'s inside: Qt's size (both are drawn
    at the window's scale, they lie on the same screen), the place in pixels."""
    if widget.size() != window.size():
        widget.resize(window.size())
    if not move_over(widget, window, QPoint(0, 0), inside=False):
        at = window.mapToGlobal(QPoint(0, 0))
        if widget.pos() != at:
            widget.move(at)


__all__ = ['Coalesced', 'Pointer','client_pixels', 'cover_window', 'no_system_animation', 'cursor_point', 'event_pixels', 'keep_inside',
           'move_over', 'place', 'to_pixels', 'to_window']
