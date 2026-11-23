"""Rounded dialog motion on the dialog's own Qt backing store."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QGraphicsEffect

from . import motion_tokens as tokens
from .painted_motion import PaintedMotion


class DialogSurfaceMotion(QGraphicsEffect):
    """Paint a single captured surface, then draw live content on the same paint device."""

    def __init__(self, dialog, origin, frame_ms, retired):
        super().__init__(dialog)
        self.setObjectName('dialogCanvas')
        self.dialog = dialog
        self.origin = origin
        self.frame_ms = frame_ms
        self.retired = retired
        self.picture = QPixmap()
        self.opening = True
        self.amount = 0.0
        self.initial = 0.0
        self.result = None
        self.clock = None
        self.backdrop = None
        self._disposed = False
        self.token = tokens.SETTINGS_TRANSITION if getattr(dialog, 'UNIFIED_TRANSITION', False) else tokens.STUDIO_DIALOG
        self.curve = tokens.easing_curve(self.token)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)

    def prepare(self):
        if self._disposed or not self.dialog.isVisible():
            return
        self.dialog.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        from ..diagnostics.navigation_timing import phase
        with phase('dialog.motion.snapshot'):
            self.setEnabled(False)
            try:
                self.picture = self.dialog.grab()
            finally:
                self.setEnabled(True)
        self.backdrop = getattr(self.dialog, '_modal_backdrop', None)
        if self.picture.isNull():
            self.finish()
        else:
            self.arm()

    def arm(self):
        self.clock = PaintedMotion(self.token.ms, self.frame_ms)
        self.update()
        self.timer.start(self.frame_ms)

    def close(self, result):
        if self.result is not None:
            return
        self.result = result
        self.opening = False
        self.initial = self.amount
        # A close before the first visible frame has no panel to animate.
        if self.picture.isNull() or not self.amount:
            self.finish()
            return
        self.arm()

    def tick(self):
        from .transitions import _keep_heap_quiet
        _keep_heap_quiet()
        if self.clock.finished:
            self.finish()
        elif (p := self.clock.step()) is not None:
            k = self.curve.valueForProgress(p)
            target = 1.0 if self.opening else 0.0
            self.amount = self.initial + (target - self.initial) * k
            self.update()
            if self.backdrop is not None:
                self.backdrop.set_progress(self.backdrop.ALPHA * self.amount)

    def draw(self, painter):
        if self.picture.isNull() or self.amount <= 0.0:
            pass
        elif self.opening and self.amount >= 1.0:
            self.drawSource(painter)
        else:
            bounds = QRectF(self.dialog.rect())
            size = 1.0 - (1.0 - tokens.DIALOG_SURFACE_SCALE) * (1.0 - self.amount)
            anchor = bounds.center()
            if self.origin is not None:
                clicked = self.dialog.mapFromGlobal(self.origin.center())
                anchor = QPointF(max(0, min(bounds.width(), clicked.x())),
                                 max(0, min(bounds.height(), clicked.y())))
            rect = QRectF(anchor * (1.0 - size), bounds.size() * size)
            painter.save()
            painter.setOpacity(self.amount)
            painter.drawPixmap(rect, self.picture, QRectF(self.picture.rect()))
            painter.restore()
        if self.clock is not None:
            self.clock.painted()

    def finish(self, *, cancelled=False):
        if self._disposed:
            return
        self._disposed = True
        self.timer.stop()
        dialog, result = self.dialog, self.result
        self.retired()
        if self.backdrop is not None:
            if not cancelled and result is None:
                self.backdrop.set_progress(self.backdrop.ALPHA)
            elif result is not None:
                self.backdrop.set_progress(0)
                self.backdrop.flight_owned = False
        # During the terminal opening paint the real controls have already
        # painted into this same backing store. No native opacity change.
        if result is not None and not cancelled and dialog.isVisible():
            QDialog.done(dialog, result)
        if dialog.graphicsEffect() is self:
            dialog.setGraphicsEffect(None)
