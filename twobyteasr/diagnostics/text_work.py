"""One bounded, content-free performance summary per text operation."""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

_active = ContextVar('studio_text_work', default=None)


class TextWork:
    def __init__(self, operation):
        self.operation = operation
        self.started = perf_counter()
        self.calls = Counter()
        self.counts = Counter()
        self.phases = Counter()

    @contextmanager
    def activate(self, phase=None):
        token = _active.set(self)
        start = perf_counter()
        try:
            yield self
        finally:
            if phase:self.phases[phase] += (perf_counter()-start)*1000
            _active.reset(token)

    def summary(self):
        names=('relevant','rule_version','statuses','translation_view','text_entries','iter_text_entries')
        return dict(operation=self.operation, total_ms=(perf_counter()-self.started)*1000,
                    calls={**dict.fromkeys(names,0),**self.calls}, counts=dict(self.counts), phases_ms=dict(self.phases))

    def finish(self, result='completed'):
        data=self.summary()
        from .event_log import emit
        # Numeric _count fields survive the existing privacy sanitizer;
        # arbitrary keys containing "text" deliberately do not. Keep that
        # protection intact and use named timing records for phase names.
        emit('text_work.summary', module=__name__, result=result,
            operation=data['operation'],total_ms=data['total_ms'],
            calls={name+'_count':value for name,value in data['calls'].items()},
            counts={name+'_count':value for name,value in data['counts'].items()},
            phase_times=[dict(stage=name,duration_ms=value) for name,value in data['phases_ms'].items()])
        return data


def count(name, amount=1):
    work=_active.get()
    if work is not None:work.counts[name] += amount


def measured(name):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            work=_active.get()
            if work is None:return fn(*args, **kwargs)
            work.calls[name] += 1
            start=perf_counter()
            try:return fn(*args, **kwargs)
            finally:work.phases[name] += (perf_counter()-start)*1000
        return run
    return decorate


def operation_measured(name):
    def decorate(fn):
        @wraps(fn)
        def run(*args,**kwargs):
            if _active.get() is not None:return fn(*args,**kwargs)
            from ..playback.playback_gc_budget import note_gui_interaction,gui_collection_window
            note_gui_interaction()
            work=TextWork(name)
            result='completed'
            try:
                with gui_collection_window(name,max_seconds=2),work.activate():return fn(*args,**kwargs)
            except Exception:
                result='failed'
                raise
            finally:
                note_gui_interaction()
                data=work.finish(result)
                if args and hasattr(args[0],'__dict__'):args[0]._last_text_work=data
        return run
    return decorate
