"""Opt-in Qt and Win32 top-level lifecycle audit for desktop regressions."""

from __future__ import annotations

import json
import os
import ctypes
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QFrame, QWidget


def _anonymous(widget: QWidget) -> bool:
    """A bare parentless widget is the classic accidental top-level window.

    QFrame covers tooltip/popup subclasses that can also leak as windows.
    """
    return (
        type(widget) in (QWidget, QFrame)
        and not widget.objectName()
        and not widget.windowTitle()
    )


def _rect(hwnd: int) -> list[int]:
    if os.name != "nt":
        return [0, 0, 0, 0]
    value = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(value)):
        return [0, 0, 0, 0]
    return [value.left, value.top, value.right - value.left, value.bottom - value.top]


def win32_top_level_windows(*, pids: set[int] | None = None) -> list[dict[str, object]]:
    """Return EnumWindows evidence without creating any Qt native handles."""
    if os.name != "nt":
        return []
    import ctypes.wintypes

    result: list[dict[str, object]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def text_for(hwnd: int, class_name: bool = False) -> str:
        length = 512 if class_name else max(1, int(ctypes.windll.user32.GetWindowTextLengthW(hwnd)) + 1)
        buffer = ctypes.create_unicode_buffer(length)
        if class_name:
            ctypes.windll.user32.GetClassNameW(hwnd, buffer, length)
        else:
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length)
        return buffer.value

    def visit(hwnd, _lparam):
        pid = ctypes.wintypes.DWORD()
        tid = int(ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))
        if pids is not None and int(pid.value) not in pids:
            return True
        get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
        owner = int(ctypes.windll.user32.GetWindow(hwnd, 4) or 0)  # GW_OWNER
        parent = int(ctypes.windll.user32.GetParent(hwnd) or 0)
        result.append({
            "hwnd": int(hwnd),
            "pid": int(pid.value),
            "tid": tid,
            "title": text_for(hwnd),
            "class": text_for(hwnd, True),
            "geometry": _rect(int(hwnd)),
            "visible": bool(ctypes.windll.user32.IsWindowVisible(hwnd)),
            "owner_hwnd": owner,
            "parent_hwnd": parent,
            "style": int(get_window_long(hwnd, -16)),
            "exstyle": int(get_window_long(hwnd, -20)),
        })
        return True

    try:
        ctypes.windll.user32.EnumWindows(callback_type(visit), 0)
    except (AttributeError, OSError, ValueError):
        return []
    # Never query process metadata while EnumWindows holds the desktop/window
    # manager enumeration path.  That stalls real GUI cursor, popup and paint
    # operations on some Windows builds.  Enrich once per PID afterwards.
    process_cache: dict[int, dict[str, object]] = {}
    for pid in {int(item["pid"]) for item in result}:
        try:
            import psutil
            process = psutil.Process(pid)
            process_cache[pid] = {
                "process_name": process.name(),
                "process_exe": process.exe(),
                "process_cmdline": process.cmdline(),
                "process_cwd": process.cwd(),
                "parent_pid": process.ppid(),
            }
        except Exception:
            process_cache[pid] = {}
    for item in result:
        item.update(process_cache.get(int(item["pid"]), {}))
    return result


def qt_top_level_widgets(app: QApplication) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for widget in app.topLevelWidgets():
        handle = widget.windowHandle()
        result.append({
            "class": type(widget).__name__,
            "objectName": widget.objectName(),
            "windowTitle": widget.windowTitle(),
            "geometry": list(widget.geometry().getRect()),
            "visible": widget.isVisible(),
            "parentClass": type(widget.parent()).__name__ if widget.parent() else "",
            "windowFlags": int(widget.windowFlags()),
            "native": bool(handle is not None or widget.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)),
            "winId": int(handle.winId()) if handle is not None else 0,
        })
    return result


class TopLevelWindowAudit(QObject):
    EVENTS = {
        QEvent.Type.Show: "Show",
        QEvent.Type.Hide: "Hide",
        QEvent.Type.Close: "Close",
        QEvent.Type.WinIdChange: "WinIdChange",
        QEvent.Type.PlatformSurface: "PlatformSurface",
        QEvent.Type.WindowActivate: "WindowActivate",
    }

    def __init__(
        self,
        app: QApplication,
        output: str | Path | None = None,
        *,
        capture_win32: bool = True,
    ):
        super().__init__(app)
        self.app = app
        self.output = Path(output) if output else None
        self.capture_win32 = bool(capture_win32)
        self.records: list[dict[str, object]] = []
        self._recording = False
        app.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if (
            self._recording
            or not isinstance(watched, QWidget)
            or not watched.isWindow()
            or event.type() not in self.EVENTS
        ):
            return False
        # Reading native handle metadata can itself deliver WinIdChange or
        # PlatformSurface synchronously.  Never let the diagnostic probe
        # recursively create an event storm in the product it is observing.
        self._recording = True
        try:
            record = {
                "timestamp": round(time.time(), 3),
                "event": self.EVENTS[event.type()],
                "class": type(watched).__name__,
                "objectName": watched.objectName(),
                "windowTitle": watched.windowTitle(),
                "geometry": list(watched.geometry().getRect()),
                "visible": watched.isVisible(),
                "parentClass": type(watched.parent()).__name__ if watched.parent() else "",
                "windowFlags": int(watched.windowFlags()),
                "native": bool(watched.windowHandle() is not None or watched.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)),
                "winId": int(watched.windowHandle().winId()) if watched.windowHandle() is not None else 0,
                "qtTopLevels": qt_top_level_widgets(self.app),
                "win32TopLevels": (
                    win32_top_level_windows(pids={os.getpid()})
                    if self.capture_win32 else []
                ),
            }
            self.records.append(record)
            if event.type() in {QEvent.Type.Show, QEvent.Type.WinIdChange, QEvent.Type.PlatformSurface}:
                record["stack"] = traceback.format_stack(limit=12)
            if self.output:
                self.output.parent.mkdir(parents=True, exist_ok=True)
                with self.output.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        finally:
            self._recording = False
        return False

    def close(self) -> None:
        self.app.removeEventFilter(self)
