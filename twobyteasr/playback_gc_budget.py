"""Keep automatic full-heap GC out of transport ticks with bounded deferral.

Reference counting and generations 0/1 stay enabled. A 128 MiB process-private
growth guard restores normal policy even during playback. Explicit gc.collect
calls are never intercepted. Pause/hide/close restore the caller's policy.
"""
import ctypes
import gc
import sys

from PySide6.QtCore import QObject, QTimer

from .playback_probe import mark

_holders = set()
_previous = None
_applied = None


def hold_full_collections(key):
    """Defer automatic generation-2 collections until every holder releases.

    Shared by playback and project loading so one never restores a policy
    the other still relies on. Returns False when GC is disabled elsewhere."""
    global _previous, _applied
    if not gc.isenabled():
        return False
    if not _holders:
        _previous = gc.get_threshold()
        _applied = (_previous[0], _previous[1], max(_previous[2], 1_000_000))
        gc.set_threshold(*_applied)
    _holders.add(key)
    return True


def release_full_collections(key):
    if key not in _holders:
        return False
    _holders.discard(key)
    if not _holders and gc.get_threshold() == _applied:
        gc.set_threshold(*_previous)
    return True


def private_bytes():
    if sys.platform != 'win32':
        return None
    from ctypes.wintypes import DWORD
    class Counters(ctypes.Structure):
        _fields_ = [('cb', DWORD), ('faults', DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                'peak_working', 'working', 'peak_paged', 'paged', 'peak_nonpaged',
                'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
    data = Counters()
    data.cb = ctypes.sizeof(data)
    if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(data), data.cb):
        return None
    return int(data.private)


class PlaybackGcBudget(QObject):
    MAX_PRIVATE_GROWTH = 128 * 1024 * 1024

    def __init__(self, parent=None, *, memory_reader=private_bytes):
        super().__init__(parent)
        self._memory_reader = memory_reader
        self.playing = False
        self.held = False
        self.baseline_bytes = None
        self.peak_growth = 0
        self.budget_exhausted = False
        self.guard = QTimer(self)
        self.guard.setInterval(1000)
        self.guard.timeout.connect(self.check_budget)
        self.idle_collect = QTimer(self)
        self.idle_collect.setSingleShot(True)
        self.idle_collect.setInterval(150)
        self.idle_collect.timeout.connect(self._collect_paused)

    def set_playing(self, playing):
        playing = bool(playing)
        if playing == self.playing:
            return
        self.playing = playing
        self.idle_collect.stop()
        if not playing:
            released = self._restore('paused')
            if released: self.idle_collect.start()
            return
        if not gc.isenabled():
            return  # Respect a policy owned elsewhere.
        self.baseline_bytes = self._memory_reader()
        if self.baseline_bytes is None:
            return  # No measurable bound: leave normal GC enabled.
        self.peak_growth = 0
        self.budget_exhausted = False
        hold_full_collections(id(self))
        self.held = True
        self.guard.start()
        mark('gc_budget_acquired', private_bytes=self.baseline_bytes, max_growth=self.MAX_PRIVATE_GROWTH)

    def check_budget(self):
        if not self.held:
            return
        current = self._memory_reader()
        if current is not None:
            self.peak_growth = max(self.peak_growth, current-self.baseline_bytes)
        if current is None or current-self.baseline_bytes > self.MAX_PRIVATE_GROWTH:
            self.budget_exhausted = True
            self._restore('memory_guard')
        mark('gc_budget_memory', private_bytes=current, peak_growth=self.peak_growth,
             exhausted=self.budget_exhausted)

    def _restore(self, reason):
        self.guard.stop()
        if not self.held:
            return False
        self.held = False
        release_full_collections(id(self))
        mark('gc_budget_released', reason=reason, peak_growth=self.peak_growth)
        return True

    def _collect_paused(self):
        if not self.playing and not _holders and gc.isenabled():
            gc.collect(2)

    def close(self):
        self.playing = False
        self.guard.stop()
        self.idle_collect.stop()
        self._restore('closed_or_hidden')


class ProjectHeapPolicy(QObject):
    """Full collections around loading a Studio project.

    Opening a 10,000-caption project ran 18 full (generation-2) collections,
    each rescanning the whole heap (~4-6 s in total) while the project was
    being built. While a project loads, full collections are deferred
    (reference counting and generations 0/1 keep running; bounded by
    LOAD_LIMIT_MS). Once it is ready, the deferred collection runs when the
    page is idle (no pointer gesture, no playback) instead of inside the
    user's first edit.

    Freezing the loaded heap (gc.freeze) was measured and rejected: each
    later full collection got cheaper, but they ran about twice as often and
    edits were not faster on a 1,000-caption project.
    """
    LOAD_LIMIT_MS = 180_000
    SETTLE_MS = 1_200

    def __init__(self, parent=None, *, busy=None):
        super().__init__(parent)
        self.busy = busy or (lambda: False)
        self.loading = False
        self.settles = 0
        self.limit = QTimer(self)
        self.limit.setSingleShot(True)
        self.limit.setInterval(self.LOAD_LIMIT_MS)
        self.limit.timeout.connect(lambda: self.load_finished(settle=False))
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.setInterval(self.SETTLE_MS)
        self.settle_timer.timeout.connect(self.settle)

    def load_started(self):
        self.settle_timer.stop()
        if not self.loading:
            self.loading = hold_full_collections(('project-load', id(self)))
        if self.loading:
            self.limit.start()

    def load_finished(self, *, settle=True):
        self.limit.stop()
        if self.loading:
            self.loading = False
            release_full_collections(('project-load', id(self)))
            if settle:
                self.settle_timer.start()

    def settle(self):
        if self.loading:
            return
        if self.busy() or _holders:
            self.settle_timer.start()  # pointer down, playing: try again later
            return
        gc.collect()
        self.settles += 1
        mark('project_load_collected')

    def release(self):
        """Project closed or switched before the deferred collection ran."""
        self.settle_timer.stop()

    def close(self):
        self.limit.stop()
        self.settle_timer.stop()
        if self.loading:
            self.loading = False
            release_full_collections(('project-load', id(self)))
