"""One latest pointer intent; playback time still belongs to PlaybackClock."""
from time import perf_counter
from collections import deque
from PySide6.QtCore import QObject, QTimer, Qt


class TimelineScrub(QObject):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.pending = None
        self.inflight = False
        self.active = False
        self.pressed = False
        self.resume = False
        self.samples = deque(maxlen=2048)
        self.replaced = 0
        self.pending_discarded_on_release = 0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._flush)

    def request(self, seconds):
        if not self.page.timeline._scrub_drag:
            self.page._seek(seconds)
            return
        if not self.pressed:
            # Ruler press may still be a click. Do not pause the transport or
            # issue a coarse decode until the pointer actually moves.
            self.pressed = True
            self.resume = (not self.page.video.playback_position_snapshot().paused
                           or bool(getattr(self.page.video,'_buffered_play_pending',False))
                           or bool(getattr(self.page.video,'_seek_hold_active',False)))
            return
        if not self.active:
            self.active = self.page._timeline_scrub_active = True
            if self.resume:
                self.page.video.set_paused(True)
            warm = getattr(self.page, '_cue_timing_preview', None)
            if warm:
                warm._warm_timer.stop()
                warm._warm_generation += 1
        if self.pending is not None:
            self.replaced += 1
        self.pending = float(seconds)
        self.samples.append({'at':perf_counter(), 'event':'pointer', 'target':seconds})
        if not self.timer.isActive():
            self.timer.start()

    def _flush(self):
        if self.pending is None:
            return
        # post_seek already has one replaceable actor slot. Do not start
        # another coarse decode while the current request is unacknowledged.
        if self.inflight and self.page.video.playback_position_snapshot().seeking:
            return
        target, self.pending = self.pending, None
        self.inflight = True
        started = perf_counter()
        self.page._seek(target, accurate=False)
        self.samples.append({'at':started, 'event':'coarse', 'target':target,
            'gui_ms':(perf_counter()-started)*1000})

    def finish(self, seconds):
        self.timer.stop()
        if self.pending is not None:
            self.pending_discarded_on_release += 1
        self.pending = None
        self.inflight = False
        was_dragging = self.active
        self.pressed = self.active = self.page._timeline_scrub_active = False
        started = perf_counter()
        self.page._seek(float(seconds), accurate=True)
        self.samples.append({'at':started, 'event':'precise', 'target':seconds,
            'gui_ms':(perf_counter()-started)*1000, 'pointer_replaced_total':self.replaced,
            'pending_discarded_on_release_total':self.pending_discarded_on_release})
        if was_dragging and self.resume:
            self.page.video.set_paused(False)
        self.resume = False
