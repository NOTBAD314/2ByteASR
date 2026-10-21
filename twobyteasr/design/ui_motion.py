"""Small, interruptible motion policy for independent UI surfaces."""

from __future__ import annotations

import os
from contextlib import contextmanager

from PySide6.QtCore import QCoreApplication, QEvent, QEasingCurve, QVariantAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget, QSplitter


MOTION_FAST_MS = 120
MOTION_STANDARD_MS = 180
MOTION_EMPHASIS_MS = 280
MOTION_PANEL_MS = 240


def system_reduced_motion() -> bool:
    if os.environ.get("TWOBYTEASR_REDUCE_MOTION") == "1":
        return True
    if os.name == "nt":
        try:
            import ctypes

            enabled = ctypes.c_int(1)
            # SPI_GETCLIENTAREAANIMATION: Windows accessibility animation policy.
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
            return not bool(enabled.value)
        except (AttributeError, OSError):
            pass
    return False


def reduced_motion() -> bool:
    app = QApplication.instance()
    explicit = app.property("reduceMotion") if app is not None else None
    return bool(explicit) if explicit is not None else system_reduced_motion()


def motion_duration(token_ms: int) -> int:
    return 0 if reduced_motion() else max(0, int(token_ms))


def settle_layout(root: QWidget) -> None:
    """Drain geometry work only. Never run timers, input, network or paint."""
    root.ensurePolished()
    # Hidden pages can contain thousands of controls. They do not participate
    # in this transition's geometry and will settle naturally when shown.
    # Walk only the visible tree (pruning hidden subtrees at their top) instead
    # of listing every descendant of the window and testing each one
    # (2026-10-12: a page switch enumerated all pages' widgets).
    direct = Qt.FindChildOption.FindDirectChildrenOnly
    layout_request = QEvent.Type.LayoutRequest
    stack = [root]
    while stack:
        widget = stack.pop()
        if widget.layout() is not None:
            widget.layout().activate()
        QCoreApplication.sendPostedEvents(widget, layout_request)
        if isinstance(widget, QSplitter):
            widget.refresh()
        children = [child for child in widget.findChildren(QWidget, options=direct) if not child.isHidden()]
        stack.extend(reversed(children))


@contextmanager
def atomic_layout(root: QWidget):
    """Nested-safe first-frame boundary; native media ownership is unchanged."""
    enabled = root.updatesEnabled()
    if enabled:
        root.setUpdatesEnabled(False)
    try:
        yield
        settle_layout(root)
    finally:
        if enabled:
            root.setUpdatesEnabled(True)
            root.update()


class _RevealCue(QWidget):
    """A local 2px edge cue; never animates a layout or the video surface."""
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(0, 0, parent.width(), 2)
        self._progress = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(motion_duration(MOTION_STANDARD_MS))
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._advance)
        self.animation.finished.connect(self.deleteLater)

    def _advance(self, value):
        self._progress = float(value)
        self.update()

    def paintEvent(self, event):
        from .theme_manager import theme_key
        from .ui_theme import theme_definition
        color = QColor(theme_definition(theme_key()).accent)
        color.setAlphaF((1.0-self._progress)*.65)
        painter = QPainter(self)
        painter.fillRect(self.rect(), color)


def reveal_cue(widget: QWidget) -> None:
    if reduced_motion() or not widget.isVisible():
        return
    old = getattr(widget, '_reveal_cue', None)
    if old is not None:
        try:
            old.animation.stop(); old.hide(); old.deleteLater()
        except RuntimeError:
            pass
    cue = _RevealCue(widget)
    widget._reveal_cue = cue
    cue.show(); cue.raise_(); cue.animation.start()


__all__ = [
    "MOTION_EMPHASIS_MS", "MOTION_FAST_MS", "MOTION_STANDARD_MS",
    "motion_duration", "reduced_motion", "system_reduced_motion",
]
