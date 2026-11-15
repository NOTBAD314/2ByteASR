"""Opt-in Qt/Win32 window observations. Never creates a native handle."""
import json
import os
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QWidget


class WindowLifecycle(QObject):
    def __init__(self, app, target):
        super().__init__(app)
        self.target = Path(target)
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.target.open('w', encoding='utf8', buffering=1)
        self.started = time.perf_counter()
        self.count = 0
        self.hooks = []
        self.app = app
        app.installEventFilter(self)
        if os.name == 'nt':
            self._native_hooks()

    def write(self, **row):
        if self.count >= 12000 or self.stream.closed:
            return
        self.count += 1
        self.stream.write(json.dumps(dict(elapsed_ms=round((time.perf_counter()-self.started)*1000, 3),
            pid=os.getpid(), **row), ensure_ascii=False) + '\n')

    def eventFilter(self, obj, event):
        kinds = {QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.ParentAboutToChange,
                 QEvent.Type.ParentChange, QEvent.Type.WinIdChange, QEvent.Type.DeferredDelete}
        if event.type() in kinds and isinstance(obj, QWidget):
            try:
                parent = obj.parentWidget()
                # All top-level events plus embedded model objects; no winId().
                if obj.isWindow() or 'Card' in type(obj).__name__:
                    self.write(source='qt', event=event.type().name, object_type=type(obj).__name__,
                        name=obj.objectName(), title=obj.windowTitle(), object_id=id(obj),
                        parent_type=type(parent).__name__ if parent else None,
                        parent_id=id(parent) if parent else None, flags=int(obj.windowFlags()),
                        is_window=obj.isWindow(), visible=obj.isVisible(),
                        geometry=[obj.x(),obj.y(),obj.width(),obj.height()],
                        stack=traceback.format_stack(limit=14))
            except RuntimeError:
                pass
        return False

    def _native_hooks(self):
        import ctypes
        from ctypes import wintypes
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
            wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
        self.user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        self.user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
        self.user.GetAncestor.restype=wintypes.HWND
        self.user.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        self.user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        self.user.SetWinEventHook.argtypes=[wintypes.DWORD,wintypes.DWORD,wintypes.HMODULE,
            callback_type,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD]
        self.user.SetWinEventHook.restype=wintypes.HANDLE
        self.user.UnhookWinEvent.argtypes=[wintypes.HANDLE]

        def observe(hook, kind, hwnd, object_id, child_id, thread_id, timestamp):
            if not hwnd or object_id != 0 or child_id != 0:
                return
            if self.user.GetAncestor(hwnd,2) != hwnd:
                return
            pid=wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            title=ctypes.create_unicode_buffer(512)
            cls=ctypes.create_unicode_buffer(256)
            self.user.GetWindowTextW(hwnd,title,512)
            self.user.GetClassNameW(hwnd,cls,256)
            self.write(source='win32',event=hex(kind),hwnd=int(hwnd),owner_pid=pid.value,
                thread_id=thread_id,title=title.value,class_name=cls.value,system_time_ms=timestamp)
        self.callback=callback_type(observe)
        # All PIDs: captures consoles spawned by the observed GUI too.
        for low,high in ((0x8000,0x8003),(3,3)):
            handle=self.user.SetWinEventHook(low,high,None,self.callback,0,0,0)
            if handle:self.hooks.append(handle)

    def close(self):
        self.app.removeEventFilter(self)
        for handle in self.hooks:self.user.UnhookWinEvent(handle)
        self.hooks.clear()
        self.stream.close()
