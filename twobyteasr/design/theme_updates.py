"""Latest-theme-only GUI work, drained in short event-loop turns."""
from collections import deque
from time import perf_counter
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication


class ThemeUpdates(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.jobs = deque()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)

    def reset(self):
        self.jobs.clear()
        self.timer.stop()
        self.app._theme_update_pending = False

    def submit(self, callback):
        self.jobs.append(callback)
        self.app._theme_update_pending = True
        if not self.timer.isActive():
            self.timer.start(1)

    def tick(self):
        start = perf_counter()
        while self.jobs:
            callback = self.jobs.popleft()
            previous = getattr(self.app, '_theme_async_apply', False)
            self.app._theme_async_apply = True
            try:
                callback()
            except RuntimeError as error:
                if 'already deleted' not in str(error):
                    self.reset()
                    raise
            finally:
                self.app._theme_async_apply = previous
            if perf_counter()-start >= .004:
                break
        self.app._theme_update_pending = bool(self.jobs)
        if self.jobs:
            self.timer.start(1)


def queue():
    app = QApplication.instance()
    if not hasattr(app, '_theme_updates'):
        app._theme_updates = ThemeUpdates(app)
    return app._theme_updates


def dispatch(callback):
    if getattr(QApplication.instance(), '_theme_async_apply', False):
        queue().submit(callback)
    else:
        callback()
