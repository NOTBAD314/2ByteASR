"""Task-local timing, cancellation and bounded validation memoization."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
import uuid


CURRENT = ContextVar('subtitle_export_work', default=None)


class SubtitleExportCancelled(RuntimeError):
    def __init__(self, published=()):
        self.published = tuple(published)
        super().__init__('字幕导出已取消')


class SubtitleExportWork:
    def __init__(self, cancel=None):
        self.task_id = uuid.uuid4().hex
        self.cancel = cancel
        self.timings = {}
        self.receipt_cache = {}
        self.evidence_cache = {}
        self.stage = 'snapshot'
        self.peak_bytes = 0
        self.receipt_hits = 0
        self.receipt_checks = 0

    def checkpoint(self, published=()):
        if self.cancel is not None and self.cancel.is_set():
            raise SubtitleExportCancelled(published)

    @contextmanager
    def activate(self):
        token = CURRENT.set(self)
        try:
            yield self
        finally:
            CURRENT.reset(token)
            self.receipt_cache.clear()
            self.evidence_cache.clear()


@contextmanager
def stage(name):
    work = CURRENT.get()
    start = perf_counter()
    if work is not None:
        work.checkpoint()
        work.stage = name
    try:
        yield
    finally:
        if work is not None:
            work.timings[name] = work.timings.get(name, 0) + perf_counter() - start
            try:
                import psutil
                info = psutil.Process().memory_info()
                work.peak_bytes = max(work.peak_bytes, getattr(info, 'peak_wset', info.rss))
            except (ImportError, OSError):
                pass


def checkpoint(published=()):
    work = CURRENT.get()
    if work is not None:
        work.checkpoint(published)


def temporary_prefix(kind):
    work = CURRENT.get()
    return f'.subtitle-{kind}-{work.task_id}-' if work is not None else f'.subtitle-{kind}-'
