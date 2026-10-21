"""Opt-in bounded in-memory timeline evidence. No file I/O on playback threads."""
from collections import deque
from functools import wraps
import os
from time import perf_counter, thread_time
from threading import get_ident

ENABLED = os.environ.get('TWOBYTEASR_PLAYBACK_PROBE') == '1'
LIGHT = os.environ.get('TWOBYTEASR_PLAYBACK_PROBE_DETAIL') == 'light'
LIGHT_STAGES = frozenset({'apply_playhead', 'playhead_target', 'playhead_paint',
    'playhead_update_request', 'cursor_paint_begin', 'cursor_paint_end',
    'gui_heartbeat', 'python_gc_start', 'python_gc_stop',
    'gc_budget_acquired', 'gc_budget_released', 'gc_budget_memory'})
EVENTS = deque(maxlen=min(2000000, max(100000, int(os.environ.get('TWOBYTEASR_PLAYBACK_PROBE_LIMIT', '100000')))))


def mark(stage, **values):
    if ENABLED and (not LIGHT or stage in LIGHT_STAGES):
        EVENTS.append({'at': perf_counter(), 'stage': stage, 'thread': get_ident(), **values})


def measured(stage):
    def decorate(function):
        if not ENABLED or (LIGHT and stage not in LIGHT_STAGES):
            return function
        @wraps(function)
        def call(self, *args, **kwargs):
            started = perf_counter()
            cpu_started = thread_time()
            try:
                return function(self, *args, **kwargs)
            finally:
                row = {'at': started, 'stage': stage, 'ms': (perf_counter()-started)*1000,
                       'cpu_ms': (thread_time()-cpu_started)*1000, 'thread': get_ident()}
                timeline = getattr(self, 'timeline', self)
                if hasattr(timeline, 'playhead_ms'):row['project_ms'] = timeline.playhead_ms
                if stage == 'clock_observe':
                    row.update(media_ms=self._observed_media_ms, generation=self.generation)
                if stage == 'clock_sample':
                    row.update(media_ms=self._snapshot.presentation_media_ms, generation=self.generation,source=kwargs.get('source'))
                EVENTS.append(row)
        return call
    return decorate


def take():
    return list(EVENTS)
