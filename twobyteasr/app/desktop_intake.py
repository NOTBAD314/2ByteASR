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
        self._studio_wait = None
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
                    self.requests.append(('media', media, replace, None))
                    media = []
                self.requests.append((kind, [path], False,
                    getattr(self.window, '_studio_navigation_cancel_generation', 0)))
        if media:
            self.requests.append(('media', media, replace, None))
        bind_text(self.window.header_status, '已收到文件，正在打开…')
        self.timer.start()
        self._next()

    def _busy(self):
        w = self.window
        page = existing_page(w, 'studio')
        gate = getattr(page, '_readiness', None)
        loading = getattr(w, '_studio_loading_session', None)
        return bool(w._run_in_progress or (w.worker and w.worker.isRunning())
                    or (gate is not None and gate.active)
                    or (loading is not None and loading.active)
                    or getattr(w, '_studio_entry_pending', None) is not None
                    or getattr(w, '_studio_entry_discarding', False)
                    or getattr(w, '_studio_construction_discarding', False)
                    or getattr(w, '_studio_close_pending', False)
                    or getattr(page, '_manual_save_in_progress', False))

    def _wait_for_studio_subtitle(self, request):
        """Construct via the normal loading owner, never via a lazy accessor."""
        token = object()
        self.active = True
        self._studio_wait = (token, None, None)
        def release():
            pending, self._studio_wait = self._studio_wait, None
            if pending is not None and pending[1] is not None:
                pending[1].changed.disconnect(pending[2])
        def ready(page):
            if self._studio_wait is None or self._studio_wait[0] is not token:
                return
            release()
            if self.requests and self.requests[0] is request:
                self.requests.popleft()
            try:
                self.window._switch_page(page)
                page._import_subtitle_file(Path(request[1][0]))
            finally:
                self.active = False
        try:
            self.window.open_studio_project(None, source='external', on_ready=ready)
            loading = getattr(self.window, '_studio_loading_session', None)
            if loading is None:
                raise RuntimeError('工作台没有建立载入会话')
            generation = loading.generation
            def changed():
                if loading.generation != generation or loading.state in {'failed', 'cancelled'}:
                    release()
                    if self.requests and self.requests[0] is request:
                        self.requests.popleft()
                    self.active = False
                    bind_text(self.window.header_status, '字幕未导入：工作台准备已取消或失败。')
            self._studio_wait = (token, loading, changed)
            loading.changed.connect(changed)
            changed()
        except Exception as exc:
            release()
            self.active = False
            if self.requests and self.requests[0] is request:
                self.requests.popleft()
            bind_text(self.window.header_status, '字幕未导入：{error}', error=str(exc))

    def _next(self):
        generation = getattr(self.window, '_studio_navigation_cancel_generation', 0)
        cancelled = 0
        while (self.requests and self.requests[0][0] in {'project', 'subtitle'}
               and self.requests[0][3] != generation):
            self.requests.popleft()
            cancelled += 1
        if cancelled:
            from ..diagnostics.event_log import emit
            emit('desktop.open_cancelled', result='cancelled', requests=cancelled,
                 cancel_generation=generation)
            bind_text(self.window.header_status, '已取消此前的工程／字幕打开请求。')
        if self.active or self._busy():
            return
        if not self.requests:
            self.timer.stop()
            return
        request = self.requests[0]
        kind, paths, replace, _generation = request
        if kind == 'subtitle' and existing_page(self.window, 'studio') is None:
            self._wait_for_studio_subtitle(request)
            return
        self.requests.popleft()
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
                page = existing_page(self.window, 'studio')
                self.window._switch_page(page)
                page._import_subtitle_file(Path(paths[0]))
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
