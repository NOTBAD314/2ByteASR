"""Async input adapter; the main window continues to own the media selection."""
from collections import deque
from threading import Thread
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtWidgets import QMessageBox
from ..media.media_intake import validate_media_paths
from .external_open import classify_open_paths
from .main_ui_helpers import _merge_media_paths, _remember_media_directory

from ..i18n import bind_text
from .lazy_pages import existing_page


class DesktopIntake(QObject):
    validated = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.requests = deque()
        self.active = False
        self.validated.connect(self._apply)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._next)

    def receive_external(self, paths):
        window = self.window
        from .window_constraints import restore_minimized_window
        restore_minimized_window(window)
        window.raise_()
        window.activateWindow()
        import os
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(int(window.winId())))
        if paths:
            self.submit(paths)

    def submit(self, paths, *, replace=False):
        typed = classify_open_paths(paths)
        media = []
        for kind, path in typed:
            if kind in {'media', 'unsupported'}:
                media.append(path)
            else:
                if media:
                    self.requests.append(('media', media, replace))
                    media = []
                self.requests.append((kind, [path], False))
        if media:
            self.requests.append(('media', media, replace))
        bind_text(self.window.header_status, '已收到文件，正在打开…')
        self.timer.start()
        self._next()

    def _busy(self):
        w = self.window
        gate = getattr(existing_page(w, 'studio'), '_readiness', None)
        return bool(w._run_in_progress or (w.worker and w.worker.isRunning())
                    or (gate is not None and gate.active))

    def _next(self):
        if self.active or self._busy():
            return
        if not self.requests:
            self.timer.stop()
            return
        kind, paths, replace = self.requests.popleft()
        if kind == 'project':
            self.active = True
            try:
                self.window.open_studio_project(paths[0], mode='edit', source='external')
            finally:
                self.active = False
            # The Studio readiness gate owns asynchronous loading. The queue
            # resumes only when that gate ends, including cancellation/failure.
            return
        if kind == 'subtitle':
            self.active = True
            try:
                self.window._switch_page(self.window.studio_page)
                self.window.studio_page._import_subtitle_file(Path(paths[0]))
            finally:
                self.active = False
            return
        self.active = True
        def validate():
            accepted, rejected = validate_media_paths(paths)
            try:
                self.validated.emit((accepted, rejected, replace))
            except RuntimeError:
                pass  # Window closed while a slow network path was being checked.
        Thread(target=validate, daemon=True, name="media-intake").start()

    def _apply(self, result):
        accepted, rejected, replace = result
        if self._busy():
            QTimer.singleShot(250, lambda: self._apply(result))
            return
        w = self.window
        if accepted:
            # New home media must not retain a previous Studio recognition target.
            w._studio_recognition_context = None
            ensure_home = getattr(w, '_ensure_recognition_page', None)
            if callable(ensure_home):
                ensure_home()
            if hasattr(w, "settings_scroll"):
                w._switch_page(w.settings_scroll)
            w.media_paths = _merge_media_paths([] if replace else w.media_paths, accepted)
            _remember_media_directory(accepted)
            w._refresh_media_summary()
        bind_text(w.header_status, '已接收 {value0} 个素材，已跳过 {value1} 个文件', value0=len(accepted), value1=len(rejected))
        if rejected:
            box = QMessageBox(QMessageBox.Icon.Warning, "素材导入",
                              f"已跳过 {len(rejected)} 个文件。\n" + "\n".join(rejected[:5]),
                              QMessageBox.StandardButton.Ok, w)
            box.setDetailedText("\n".join(rejected))
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            box.open()
        self.active = False
        self._next()
