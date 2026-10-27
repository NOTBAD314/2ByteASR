"""Keep automatic full-heap GC out of transport ticks with bounded deferral.

Reference counting and generations 0/1 stay enabled. A 128 MiB process-private
growth guard restores normal policy even during playback. Explicit gc.collect
calls are never intercepted. Pause/hide/close restore the caller's policy.
An optional paused sweep skips active editing, an already completed full GC
and plays that grew the heap less than SWEEP_GROWTH.

In the desktop app automatic collection runs only on the GUI thread
(GuiThreadCollector); the thresholds above then steer that collector.
"""
import ctypes
import gc
import sys
import time

from PySide6.QtCore import QObject, QTimer

from ..diagnostics.playback_probe import mark

_holders = set()
_previous = None
_applied = None
_collector = None


def _collect_observed(generation=None, *, owner, reason, counts=None, thresholds=None, decision=None):
    """Record one actual full collection without adding a memory query.

    The decision uses the caller's already-read counts/private-byte predicate.
    Event serialization/logging occurs afterwards. Existing GC_PAUSE remains
    the GC callback measurement.
    """
    counts=gc.get_count() if counts is None else counts
    thresholds=gc.get_threshold() if thresholds is None else thresholds
    selected_at=time.perf_counter()
    holders=len(_holders)
    collected=None
    completed=False
    try:
        collected=gc.collect() if generation is None else gc.collect(generation)
        completed=True
        return collected
    finally:
        ended=time.perf_counter()
        try:
            from ..diagnostics.event_log import emit
            emit('gc.collection_decision',module='playback',
                result='completed' if completed else 'failed',
                owner=owner,reason=reason,generation=2 if generation is None else generation,
                counts=counts,thresholds=thresholds,full_gc_holders=holders,
                decision_qpc=selected_at,completed_qpc=ended,
                collector_call_wall_ms=(ended-selected_at)*1000,collected=collected,
                recorded_after_collection=True,**(decision or {}))
        except Exception:
            pass  # Diagnostics cannot alter collection or lifecycle policy.


def collection_enabled():
    """Automatic collection runs: Python's own, or the GUI-thread collector."""
    return gc.isenabled() or (_collector is not None and _collector.active)


def hold_full_collections(key):
    """Defer automatic generation-2 collections until every holder releases.

    Shared by playback and project loading so one never restores a policy
    the other still relies on. Returns False when GC is disabled elsewhere."""
    global _previous, _applied
    if not collection_enabled():
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


class GuiThreadCollector(QObject):
    """Run automatic garbage collection on the GUI thread only.

    2026-10-22 (two user crashes the same day): Python collects cyclic
    garbage on whichever thread happens to allocate. Full collections ran on
    the autosave, cover-backfill, filmstrip, storage-maintenance and
    process-diagnostics threads; a cycle holding Qt objects was then
    destroyed off the GUI thread, and the GUI thread later died with an
    access violation (inside the autosave thread in report-eb10; inside a
    toolbar icon while a project opened right after the tutorial closed).

    Python's automatic collection is disabled; a GUI-thread timer applies
    the same generation thresholds (gc.get_threshold, so the holds above
    still defer full collections). Python skips a full collection until the
    long-lived heap grew by a quarter; that count is not readable, so this
    uses private bytes: a quarter of the size after the last full collection,
    at least FULL_GROWTH_MIN. Explicit gc.collect() calls are unchanged.
    """
    INTERVAL_MS = 50
    FULL_GROWTH_MIN = 64 * 1024 * 1024
    FULL_GROWTH_SHARE = 0.25
    # Without a memory reading, at most one full collection per interval.
    FULL_FALLBACK_S = 30.0

    def __init__(self, parent=None, *, memory_reader=private_bytes, clock=time.monotonic):
        super().__init__(parent)
        self._memory_reader = memory_reader
        self._clock = clock
        self.active = False
        self.collections = [0, 0, 0]
        self._baseline = None
        self._last_full = clock()
        self.timer = QTimer(self)
        self.timer.setInterval(self.INTERVAL_MS)
        self.timer.timeout.connect(self.tick)

    def start(self):
        global _collector
        if self.active or _collector is not None or not gc.isenabled():
            return False  # Respect a policy owned elsewhere.
        gc.collect()
        self._full_finished()
        gc.disable()
        gc.callbacks.append(self._observe)
        self.active = True
        _collector = self
        self.timer.start()
        return True

    def stop(self):
        global _collector
        self.timer.stop()
        if self._observe in gc.callbacks:
            gc.callbacks.remove(self._observe)
        if self.active:
            self.active = False
            gc.enable()
        if _collector is self:
            _collector = None

    def _observe(self, phase, info):
        # Explicit full collections (project load settle, paused sweep) also
        # reset the growth measure, on whichever thread they ran.
        if phase == 'stop' and info.get('generation') == 2:
            self._full_finished()

    def _full_finished(self):
        self._baseline = self._memory_reader()
        self._last_full = self._clock()

    def full_due(self):
        current = self._memory_reader()
        if current is None or self._baseline is None:
            elapsed=self._clock() - self._last_full
            due=elapsed >= self.FULL_FALLBACK_S
            if due:
                self._full_decision=dict(private_bytes=current,baseline_private_bytes=self._baseline,
                    full_due_branch='unavailable_memory_elapsed',elapsed_since_full_s=elapsed,
                    full_growth_threshold_bytes=None)
            return due
        grown = current - self._baseline
        threshold=max(self.FULL_GROWTH_MIN, self._baseline * self.FULL_GROWTH_SHARE)
        due=grown >= threshold
        if due:
            self._full_decision=dict(private_bytes=current,baseline_private_bytes=self._baseline,
                private_growth_bytes=grown,full_due_branch='private_growth',
                full_growth_threshold_bytes=threshold)
        return due

    def tick(self):
        if not self.active or gc.isenabled():
            return
        counts = gc.get_count()
        thresholds = gc.get_threshold()
        if thresholds[0] <= 0:
            return  # A zero threshold disables collection (Python semantics).
        for generation in (2, 1, 0):
            if counts[generation] <= thresholds[generation]:
                continue
            if generation == 2 and not self.full_due():
                continue
            if generation==2:
                _collect_observed(generation,owner='gui_thread_collector',reason='threshold_and_full_due',
                    counts=counts,thresholds=thresholds,decision=getattr(self,'_full_decision',None))
            else:
                gc.collect(generation)
            self.collections[generation] += 1
            return


def install_gui_thread_collector(app):
    """Desktop app only: automatic collection on the GUI thread from now on."""
    import os
    if _collector is not None or os.environ.get('TWOBYTEASR_GUI_THREAD_GC', '1') == '0':
        return _collector
    collector = GuiThreadCollector(app)
    if collector.start():
        app.aboutToQuit.connect(collector.timer.stop)
    return _collector


class PlaybackGcBudget(QObject):
    MAX_PRIVATE_GROWTH = 128 * 1024 * 1024
    # 2026-10-22 (user report, 24-minute anime, 343 bilingual captions): the
    # sweep after every pause rescanned a 1.4 GB heap for 0.25-0.35 s; while
    # editing (63 play/pause in 5 min) it was 34 of 47 GUI stalls. A short
    # play defers almost nothing, so only sweep after real growth, once the
    # page has stayed paused for a moment.
    SWEEP_GROWTH = 48 * 1024 * 1024
    SWEEP_DELAY_MS = 1500

    def __init__(self, parent=None, *, memory_reader=private_bytes, busy=None):
        super().__init__(parent)
        self._memory_reader = memory_reader
        self.busy = busy or (lambda: False)
        self._collections_at_pause = None
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
        self.idle_collect.setInterval(self.SWEEP_DELAY_MS)
        self.idle_collect.timeout.connect(self._collect_paused)

    def set_playing(self, playing):
        playing = bool(playing)
        if playing == self.playing:
            return
        self.playing = playing
        self.idle_collect.stop()
        if not playing:
            # Restoring the normal policy can itself trigger a full collection
            # on any Python thread. Do not repeat that work a moment later.
            self._collections_at_pause = gc.get_stats()[2]['collections']
            grown = self._growth()
            released = self._restore('paused')
            if released and grown >= self.SWEEP_GROWTH:
                self.idle_collect.start()
            return
        if not collection_enabled():
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

    def _growth(self):
        """Private bytes added while this hold deferred full collections."""
        if not self.held or self.baseline_bytes is None:
            return 0
        current = self._memory_reader()
        if current is not None:
            self.peak_growth = max(self.peak_growth, current - self.baseline_bytes)
        return self.peak_growth

    def _restore(self, reason):
        self.guard.stop()
        if not self.held:
            return False
        self.held = False
        release_full_collections(id(self))
        mark('gc_budget_released', reason=reason, peak_growth=self.peak_growth)
        return True

    def _collect_paused(self):
        if self.playing or _holders or not collection_enabled():
            return
        due, self._collections_at_pause = self._collections_at_pause, None
        # Pausing to type is interaction, not idle. Normal automatic GC was
        # already restored; skipping this optional extra sweep does not hold
        # the heap or disable collection during a long edit.
        if self.busy() or due is None or gc.get_stats()[2]['collections'] != due:
            return
        _collect_observed(2,owner='playback_paused_sweep',reason='paused_growth_and_idle')

    def close(self):
        self.playing = False
        self._collections_at_pause = None
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
        _collect_observed(owner='project_heap_policy',reason='project_settle_idle')
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
