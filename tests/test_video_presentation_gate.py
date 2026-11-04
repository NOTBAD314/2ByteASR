"""Presentation ownership is independent of decode/clock/navigation lifecycle.

Offscreen verifies the region and ownership contract only. Native child clipping
and absence of flashing require the separate real-Windows capture acceptance.
"""
import threading

from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from twobyteasr.studio.studio_video_canvas import MpvCanvas

APP = QApplication.instance() or QApplication([])


def dispose(canvas):
    canvas._timer.stop()
    canvas._sync_timer.stop()
    canvas._buffered_play_timer.stop()
    canvas.controller = None
    canvas.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_loading_gate_is_nonempty_but_cannot_expose_any_client_pixel():
    canvas = MpvCanvas()
    canvas.resize(640, 360)
    clock = canvas._playback_clock
    controller = canvas.controller = object()
    # Pure presentation ownership must not pause, touch IPC, or stop timers.
    canvas.set_paused = lambda _: (_ for _ in ()).throw(AssertionError('transport changed'))
    canvas._timer.start(19)
    canvas._sync_timer.start(150)
    try:
        canvas.set_presentation_blocked('loading', True)
        assert canvas.presentation_blocked
        assert not canvas.mask().isEmpty()
        assert canvas.mask().intersected(QRegion(canvas.rect())).isEmpty()
        assert canvas._playback_clock is clock and canvas.controller is controller
        assert canvas._timer.isActive() and canvas._sync_timer.isActive()
        assert canvas._timer.interval() == 19
        canvas.resize(1440, 900)
        assert canvas.mask().intersected(QRegion(canvas.rect())).isEmpty()
        canvas.set_presentation_blocked('loading', False)
        assert not canvas.presentation_blocked and canvas.mask().isEmpty()
    finally:
        dispose(canvas)


def test_loading_release_does_not_expose_a_navigated_away_canvas():
    canvas = MpvCanvas()
    original = QRegion(QRect(4, 8, 240, 120)) - QRegion(QRect(30, 20, 10, 10))
    canvas.setMask(original)
    try:
        canvas.set_presentation_blocked('loading', True)
        canvas.set_navigation_visible(False)
        canvas.set_presentation_blocked('loading', False)
        assert canvas.presentation_blocked
        assert canvas._presentation_block_reasons == {'navigation'}
        assert not canvas.mask().isEmpty() and canvas.mask() != original
        canvas.set_navigation_visible(True)
        assert not canvas.presentation_blocked and canvas.mask() == original
    finally:
        dispose(canvas)


def test_repeated_owners_do_not_replace_the_original_mask_or_release_each_other():
    canvas = MpvCanvas()
    original = QRegion(QRect(2, 3, 320, 180))
    canvas.setMask(original)
    try:
        canvas.set_presentation_blocked('loading', True)
        canvas.set_presentation_blocked('loading', True)
        canvas.set_presentation_blocked('navigation', True)
        canvas.set_presentation_blocked('unknown', False)
        canvas.set_presentation_blocked('navigation', False)
        assert canvas.presentation_blocked and canvas._presentation_saved_mask == original
        canvas.set_presentation_blocked('loading', False)
        canvas.set_presentation_blocked('loading', False)
        assert canvas.mask() == original
    finally:
        dispose(canvas)


def test_presentation_changes_from_a_worker_are_rejected_without_widget_mutation():
    canvas = MpvCanvas()
    errors = []
    def worker():
        try:
            canvas.set_presentation_blocked('loading', True)
        except RuntimeError as error:
            errors.append(str(error))
    try:
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(2)
        assert not thread.is_alive() and len(errors) == 1
        assert not canvas.presentation_blocked and canvas.mask().isEmpty()
    finally:
        dispose(canvas)
