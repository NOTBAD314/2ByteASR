"""Opt-in window movement reasons on the existing asynchronous event recorder.

Enable through Report problem -> detailed recording, or set
TWOBYTEASR_WINDOW_TRACE_SECONDS (1..900) for a bounded diagnostic launch.
No mouse-move disk writes, caption text, window titles or external uploads.
"""
from __future__ import annotations

import os
import time

_until = None


def enabled():
    global _until
    from .event_log import recorder
    instance = recorder()
    if _until is None:
        try:
            seconds = min(900, max(0, int(os.environ.get('TWOBYTEASR_WINDOW_TRACE_SECONDS', '0'))))
        except ValueError:
            seconds = 0
        _until = time.monotonic() + seconds if seconds else 0
    return instance is not None and (time.monotonic() < _until or instance.detailed)


def record(window, event, *, actor, reason, **fields):
    if not enabled():
        return
    try:
        from PySide6.QtGui import QCursor
        from shiboken6 import isValid
        from .event_log import emit
        from ..app.window_constraints import existing_native_handle, native_frame
        if not isValid(window):
            return
        now = time.monotonic()
        if event in {'move', 'resize', 'bounds-skip'}:
            last = getattr(window, '_motion_sample_at', {})
            if now - last.get((event, reason), 0) < .04:
                return
            last[(event, reason)] = now
            window._motion_sample_at = last
        bounds = getattr(window, '_window_bounds', None)
        screen = window.screen()
        cursor = QCursor.pos()
        native = native_frame(window)
        hwnd = existing_native_handle(window)
        details = dict(window_id=hex(hwnd) if hwnd else 'uncreated',
            operation_generation=getattr(bounds, 'generation', 0), owner=getattr(bounds, 'owner', 'idle'),
            maximized=window.isMaximized(), fullscreen=window.isFullScreen(), minimized=window.isMinimized(),
            visible=window.isVisible(), cursor_logical=[cursor.x(),cursor.y()],
            geometry_logical=list(window.geometry().getRect()), frame_logical=list(window.frameGeometry().getRect()),
            normal_logical=list(window.normalGeometry().getRect()), dpr=window.devicePixelRatioF(),
            screen_name=screen.name() if screen else None,
            work_logical=list(screen.availableGeometry().getRect()) if screen else None, native=native)
        if os.name == 'nt' and native:
            import ctypes
            from ctypes import wintypes
            point = wintypes.POINT()
            u = ctypes.WinDLL('user32', use_last_error=True)
            u.GetCursorPos(ctypes.byref(point))
            details['cursor_physical'] = [point.x,point.y]
            u.GetDpiForWindow.argtypes = [wintypes.HWND]
            details['dpi'] = int(u.GetDpiForWindow(hwnd))
        if event in {'press','gesture-end','state-change','interaction-end','repair','return-screen'}:
            from PySide6.QtWidgets import QWidget
            details['video_children'] = [dict(visible=child.isVisible(),
                geometry_logical=list(child.geometry().getRect()), native=native_frame(child))
                for child in window.findChildren(QWidget,'videoSurface')[:8]]
        emit('window.motion', module='window', action=event, actor=actor, reason=reason, **details, **fields)
    except (RuntimeError, AttributeError, OSError):
        # Diagnostics must not change window behavior during teardown.
        return
