"""Bounded, content-free persistence timelines shared with local workers."""
from contextlib import contextmanager
from contextvars import ContextVar
import gc
import os
import threading
import time
from uuid import uuid4

_current = ContextVar('studio_save_trace', default=None)


class SaveTrace:
    def __init__(self, save_id=None):
        self.save_id = save_id or uuid4().hex
        self.request_ns = time.perf_counter_ns()
        self.events = []
        self.counters = {}
        self._gc_observer = None

    @contextmanager
    def activate(self):
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)

    @contextmanager
    def span(self, stage):
        started = time.perf_counter_ns()
        try:
            yield
        finally:
            self.add(stage, started, time.perf_counter_ns())

    def add(self, stage, started_ns, ended_ns, **details):
        if stage == 'gc':
            generation = details.get('generation', 0)
            key = f'gc_{generation}'
            self.counters[key+'_count'] = self.counters.get(key+'_count', 0) + 1
            self.counters[key+'_ms'] = self.counters.get(key+'_ms', 0) + (ended_ns-started_ns)/1e6
            if sum(self.counters.get(f'gc_{n}_count', 0) for n in (0, 1, 2)) > 64:
                return
        if len(self.events) < 256:
            self.events.append(dict(stage=stage, started_ns=started_ns, ended_ns=ended_ns,
                duration_ms=(ended_ns-started_ns)/1e6, pid=os.getpid(),
                thread=threading.current_thread().name, **details))

    @contextmanager
    def observe_gc(self):
        owned = self._gc_observer is None
        self.start_gc()
        try:
            yield
        finally:
            if owned:
                self.stop_gc()

    def start_gc(self):
        if self._gc_observer is not None:
            return
        pending = {}
        def observe(phase, info):
            key = (threading.get_ident(), info.get('generation'))
            if phase == 'start':
                pending[key] = time.perf_counter_ns()
            else:
                start = pending.pop(key, None)
                if start is not None:
                    self.add('gc', start, time.perf_counter_ns(), generation=key[1],
                             collected=info.get('collected'))
        self._gc_observer = observe
        gc.callbacks.append(observe)

    def stop_gc(self):
        callback, self._gc_observer = self._gc_observer, None
        if callback in gc.callbacks:
            gc.callbacks.remove(callback)

    def payload(self):
        return dict(save_id=self.save_id, request_ns=self.request_ns,
                    elapsed_ms=(time.perf_counter_ns()-self.request_ns)/1e6,
                    events=list(self.events), counters=dict(self.counters))


def current():
    return _current.get()


@contextmanager
def phase(stage):
    trace = current()
    if trace is None:
        yield
    else:
        with trace.span(stage):
            yield
