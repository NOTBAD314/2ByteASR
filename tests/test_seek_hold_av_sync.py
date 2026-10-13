"""A seek during playback holds the picture until the new audio is ready.

2026-10-12: on an hour-long FLV the audio decoder needs 0.3-1.5 s before the
first PCM after a seek while mpv resumed at once; audio then trailed the
picture by that startup for the rest of the play (measured 0.7-5.5 s of media
at 4x). The seek now reuses the buffered-play gate that already protected
play start and rate changes.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from twobyteasr.studio_video_canvas import MpvCanvas


def _app():
    return QApplication.instance() or QApplication([])


def _spin(seconds):
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


class Controller:
    running = True

    def __init__(self):
        self.calls = []

    def set_paused(self, paused):
        self.calls.append(("pause", bool(paused)))

    def seek(self, seconds, accurate=True):
        self.calls.append(("seek", round(float(seconds), 3)))

    def set_speed(self, value):
        self.calls.append(("speed", float(value)))

    def source_alive(self):
        return True

    def get_property(self, name, default=None):
        return default


def _playing_canvas(ready):
    canvas = MpvCanvas()
    canvas.controller = Controller()
    canvas._startup_state = "READY"
    canvas._media_attached = True
    canvas._duration = 600.0
    canvas.playback_ready = lambda: ready[0]
    canvas.playback_prepare = lambda: None
    canvas.set_paused(False)
    assert not canvas._paused
    canvas.controller.calls.clear()
    return canvas


def test_seek_while_playing_waits_for_audio_then_resumes():
    _app()
    ready = [True]
    canvas = _playing_canvas(ready)
    states = []
    canvas.playback_state_changed.connect(states.append)
    try:
        ready[0] = False
        canvas.seek(120.0)
        # Picture held at once, the seek goes to the paused transport.
        assert canvas.controller.calls[:2] == [("pause", True), ("seek", 120.0)]
        assert canvas._seek_hold_active and canvas.playback_intended
        _spin(0.1)
        assert canvas._paused and canvas._buffered_play_pending
        # Code that re-asserts the current state keeps the user's intent.
        canvas.set_paused(not canvas.playback_intended)
        assert canvas._seek_hold_active
        ready[0] = True
        deadline = time.perf_counter() + 2
        while canvas._paused and time.perf_counter() < deadline:
            _spin(0.02)
        assert not canvas._paused and not canvas._seek_hold_active
        assert canvas.controller.calls[-1] == ("pause", False)
        assert states == [True, False]
    finally:
        canvas.controller = None
        canvas.deleteLater()


def test_user_pause_during_hold_stays_paused():
    _app()
    ready = [True]
    canvas = _playing_canvas(ready)
    states = []
    canvas.playback_state_changed.connect(states.append)
    try:
        ready[0] = False
        canvas.seek(42.0)
        _spin(0.05)
        canvas.set_paused(True)  # Space while the hold waits
        assert not canvas._seek_hold_active and not canvas.playback_intended
        ready[0] = True
        _spin(0.15)
        assert canvas._paused
        # The page receives a real pause to run its pause side effects.
        assert states[-1] is True
    finally:
        canvas.controller = None
        canvas.deleteLater()


def test_seek_while_paused_does_not_start_playback():
    _app()
    ready = [True]
    canvas = _playing_canvas(ready)
    try:
        canvas.set_paused(True)
        canvas.controller.calls.clear()
        canvas.seek(30.0)
        _spin(0.1)
        assert canvas._paused and not canvas._seek_hold_active
        assert ("pause", False) not in canvas.controller.calls
    finally:
        canvas.controller = None
        canvas.deleteLater()
