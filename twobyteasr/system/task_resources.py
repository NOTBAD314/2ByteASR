"""Separate live budgets for network, CPU, acoustic models and rebuildable caches."""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass


def _limit(name, default, maximum):
    try:
        return max(1, min(maximum, int(os.environ.get(name, default))))
    except (ValueError, TypeError):
        return default


def memory_snapshot():
    import psutil
    memory = psutil.virtual_memory()
    process = psutil.Process()
    tree = [process]
    try:
        tree += process.children(recursive=True)
    except psutil.Error:
        pass
    rss = 0
    for child in tree:
        try:
            rss += child.memory_info().rss
        except psutil.Error:
            pass
    from .resource_governor import GLOBAL_RESOURCE_GOVERNOR
    foreground = GLOBAL_RESOURCE_GOVERNOR.snapshot()
    return dict(available_bytes=memory.available, total_bytes=memory.total,
                process_tree_rss_bytes=rss, process_count=len(tree),
                foreground=bool(foreground.playback or foreground.dragging))


@dataclass(frozen=True)
class TaskBudget:
    cpu_workers: int
    upload_workers: int
    moss_active: int
    moss_ceiling: int
    ai_requests: int
    shard_workers: int
    pending_shards: int
    alignment_batch: int
    reclaimable_cache_bytes: int
    memory: dict


def task_budget(snapshot=None):
    state = snapshot or memory_snapshot()
    gib = state['available_bytes'] / 1024**3
    foreground = bool(state.get('foreground'))
    cpu = max(1, min(4, (os.cpu_count() or 2) - 2))
    # Available RAM already subtracts other applications. Retained caches
    # consume at most 1/16 of it; a foreground workload keeps extra headroom.
    cache = min(_limit('TWOBYTEASR_CACHE_MIB',1024,4096)*1024**2,
                max(32*1024**2, int(state['available_bytes']/16)))
    return TaskBudget(
        cpu_workers=_limit('TWOBYTEASR_AUDIO_WORKERS', min(cpu, 2 if foreground else 4), 8),
        upload_workers=_limit('TWOBYTEASR_UPLOAD_WORKERS', 2 if gib >= 4 else 1, 8),
        moss_active=_limit('TWOBYTEASR_MOSS_ACTIVE', 4 if gib >= 4 else 2, 16),
        moss_ceiling=_limit('TWOBYTEASR_MOSS_CEILING', 8 if gib >= 8 else 4, 16),
        ai_requests=_limit('TWOBYTEASR_AI_REQUESTS', 16 if gib >= 12 else 8 if gib >= 4 else 4, 64),
        shard_workers=_limit('TWOBYTEASR_SHARD_WORKERS', 2 if foreground else 4 if gib >= 8 else 2, 8),
        pending_shards=max(2, min(32, int(gib * 2))),
        alignment_batch=_limit('TWOBYTEASR_ALIGN_BATCH', 8 if gib >= 4 else 4, 16),
        reclaimable_cache_bytes=cache // (2 if foreground else 1), memory=state)


_LIVE_LOCK=threading.Lock()
_LIVE_VALUE=None
_LIVE_AT=0.


def live_budget():
    global _LIVE_VALUE,_LIVE_AT
    with _LIVE_LOCK:
        if _LIVE_VALUE is None or time.monotonic()-_LIVE_AT>=2.:
            _LIVE_VALUE=task_budget();_LIVE_AT=time.monotonic()
        return _LIVE_VALUE


def cached_cache_budget(default, *, share=1.):
    """Read a worker's latest budget without process enumeration on the GUI.

    Admission workers refresh the immutable snapshot. Idle UI caches retain
    their conservative fallback and reclaim rebuildable data on next use.
    """
    budget=_LIVE_VALUE
    if budget is None:
        return int(default)
    value=budget.reclaimable_cache_bytes
    from .resource_governor import GLOBAL_RESOURCE_GOVERNOR
    foreground=GLOBAL_RESOURCE_GOVERNOR.snapshot()
    if (foreground.playback or foreground.dragging) and not budget.memory.get('foreground'):
        value//=2
    return max(1,int(value*share))


class AdaptiveGate:
    """Admission is held across a remote task's entire accepted lifecycle."""
    def __init__(self, initial, ceiling=None):
        self.ceiling = max(1, int(ceiling or initial))
        self.limit = max(1, min(self.ceiling, int(initial)))
        self.active = self.waiting = self.successes = 0
        self.cooldown_until = 0.
        self.condition = threading.Condition()

    @contextmanager
    def lease(self, check=lambda: None):
        with self.condition:
            self.waiting += 1
            try:
                while self.active >= self.limit or time.monotonic() < self.cooldown_until:
                    check()
                    self.condition.wait(.1)
                check()
                self.active += 1
            finally:
                self.waiting -= 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def feedback(self, success=True, *, cooldown=0.):
        with self.condition:
            if success:
                self.successes += 1
                if self.successes >= 4 and self.limit < self.ceiling:
                    self.limit += 1
                    self.successes = 0
            else:
                self.limit = max(1, self.limit // 2)
                self.successes = 0
                self.cooldown_until = max(self.cooldown_until, time.monotonic()+max(0., cooldown))
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            return dict(active=self.active, waiting=self.waiting, limit=self.limit, ceiling=self.ceiling,
                        cooldown_seconds=round(max(0.,self.cooldown_until-time.monotonic()),3))


LOCAL_ALIGNMENT_GATE = AdaptiveGate(1)
CPU_ALIGNMENT_GATE = AdaptiveGate(max(1, min(2, (os.cpu_count() or 2)//4)))


def cloud_request_workers(snapshot, configured):
    """Known direct HTTP routes can use the larger network budget; CLI and
    unknown gateways retain their explicit local ceiling."""
    from urllib.parse import urlsplit
    if snapshot is None:
        return max(1,int(configured))
    endpoint=str(getattr(snapshot,'endpoint_identity','') or '')
    if (str(getattr(snapshot,'transport','')) == 'openai_compatible'
            and urlsplit(endpoint).hostname in {'api.deepseek.com'}):
        from ..recognition.run_context import get_runtime_context
        budget=get_runtime_context().execution_budget or task_budget()
        return budget.ai_requests
    return max(1,int(configured))
