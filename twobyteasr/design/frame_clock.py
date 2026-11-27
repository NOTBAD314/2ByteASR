"""One shared frame beat for everything that moves 兔白 (2026-11-27).

User (2026-11-27): her moves and her play with the page stutter a little. Measured: her picture
(BunnyMascot), her body (BunnyPuck physics), her errands and the edge glow each ran their own 16 ms
timer. Out of phase, each moved or redrew her on its own, so she was painted 70-80 times a second at
uneven gaps — two paints close together, then a 30 ms hole — and the translucent layer she lives on
was flushed for every one of them.

``FrameTimer`` keeps the small part of QTimer's interface those callers use, but all of them are
fired from one precise master timer, one after another in the same event-loop turn, so a frame's
moves and its paint land together: one paint per beat, at an even rhythm.

``motion_active()`` tells other GUI-thread work (idle_prepare's page building, 30-200 ms a step)
that she is in the middle of a real motion — an errand, a flight, hanging on the pointer, the first
seconds after she appears (``hold_motion``) — so it waits for her quiet breathing instead.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal

BEAT_MS = 16
SLACK_S = 0.004          # a timer of N ms fires on the first beat at least N - 4 ms after its last


class _Master(QObject):
    def __init__(self):
        super().__init__()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(BEAT_MS)
        self._timer.timeout.connect(self._beat)
        self._active: list = []

    def add(self, timer: 'FrameTimer') -> None:
        if timer not in self._active:
            self._active.append(timer)
        if not self._timer.isActive():
            self._timer.start()

    def remove(self, timer: 'FrameTimer') -> None:
        try:
            self._active.remove(timer)
        except ValueError:
            pass
        if not self._active and self._timer.isActive():
            self._timer.stop()

    def _beat(self) -> None:
        from shiboken6 import isValid
        now = time.perf_counter()
        for timer in list(self._active):
            if not isValid(timer):
                self.remove(timer)
                continue
            if timer._active and now - timer._last >= timer._interval_s - SLACK_S:
                timer._last = now
                if timer._single:
                    timer.stop()
                timer.timeout.emit()


_master: _Master | None = None
_hold_until = 0.0


def hold_motion(seconds: float) -> None:
    """Count as moving for ``seconds`` from now (e.g. her entrance)."""
    global _hold_until
    _hold_until = max(_hold_until, time.perf_counter() + seconds)


def motion_active() -> bool:
    if time.perf_counter() < _hold_until:
        return True
    if _master is None:
        return False
    from shiboken6 import isValid
    return any(timer.motion and timer._active for timer in _master._active if isValid(timer))


def master() -> _Master:
    global _master
    if _master is None:
        _master = _Master()
    return _master


class FrameTimer(QObject):
    """A QTimer look-alike (start/stop/isActive/setInterval/interval/timeout) beating with the rest."""

    timeout = Signal()

    def __init__(self, parent=None, interval: int = BEAT_MS, motion: bool = False):
        super().__init__(parent)
        self.motion = bool(motion)       # while running: a real motion (motion_active)
        self._interval_s = max(1, int(interval)) / 1000.0
        self._active = False
        self._single = False
        self._last = 0.0

    def setInterval(self, ms: int) -> None:  # noqa: N802 - QTimer's name
        self._interval_s = max(1, int(ms)) / 1000.0

    def interval(self) -> int:
        return int(round(self._interval_s * 1000))

    def setTimerType(self, _kind) -> None:  # noqa: N802 - always precise (the master is)
        pass

    def setSingleShot(self, single: bool) -> None:  # noqa: N802
        self._single = bool(single)

    def isActive(self) -> bool:  # noqa: N802
        return self._active

    def start(self, ms: int | None = None) -> None:
        if ms is not None:
            self.setInterval(ms)
        self._active = True
        self._last = time.perf_counter()
        master().add(self)

    def stop(self) -> None:
        if self._active:
            self._active = False
            master().remove(self)


__all__ = ['BEAT_MS', 'FrameTimer', 'hold_motion', 'master', 'motion_active']
