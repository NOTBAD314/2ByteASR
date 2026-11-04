"""Bounded, revocable preparation of upcoming affine caption rasters.

The worker owns only immutable prepared snapshots and QImages.  Completed
rasters are handed to the scene worker, never to widgets or directly to mpv.
"""
from collections import OrderedDict
import threading
import time

MAX_READY_BYTES = 64 * 1024 * 1024
MAX_ITEMS = 4
MAX_SEEN = 32


def raster_bytes(value):
    _scene, layers, image = value
    return (sum(item.sizeInBytes() for item in layers.values()) if layers
            else image.sizeInBytes() if image is not None else 0)


def motion_raster_key(prepared, width, height):
    """Only complete-line affine effects have a time-independent raster key."""
    if prepared is None or getattr(prepared, 'web', None) is not None:
        return None
    snapshot = getattr(prepared, 'snapshot', None)
    if snapshot is None or not (getattr(snapshot, 'style_recipe', None) or {}).get('visualGraph'):
        return None
    from ..caption_style.word_animation import uniform_line_unit
    if uniform_line_unit(getattr(snapshot, 'word_animation', None) or {}) is None:
        return None
    return (prepared.snapshot_hash, int(width), int(height), ('uniform-line',))


def _render(item):
    key, prepared, sample_ms, width, height = item
    from .caption_scene import SceneRasterizer
    rasterizer = SceneRasterizer()
    try:
        rasterizer.native_frame(prepared, max(0, sample_ms - prepared.snapshot.start_ms), width, height)
        value=rasterizer.rasters.pop(key,None)
        return value
    finally:
        rasterizer.close()


class CaptionMotionPreheater:
    """One latest-request worker; no result survives its session epoch."""
    def __init__(self, *, builder=_render, budget_bytes=MAX_READY_BYTES, ready=None):
        self._builder = builder
        self._ready_callback=ready
        self._budget = int(budget_bytes)
        self._condition = threading.Condition()
        self._epoch = None
        self._version = 0
        self._pending = OrderedDict()
        self._ready = OrderedDict()
        self._seen = OrderedDict()
        self._inflight = None
        self._closed = False
        self._current_ms = None
        self._protected_end_ms=None
        self._protected_until=0.
        self.thread = None
        self.requested = self.built = self.used = self.discarded = 0

    def set_epoch(self, epoch):
        with self._condition:
            if epoch == self._epoch:
                return
            self._epoch = epoch
            self._version += 1
            self._pending.clear()
            self._ready.clear()
            self._seen.clear()
            self._current_ms=None
            self._protected_end_ms=None;self._protected_until=0.
            self._condition.notify_all()

    def request(self, epoch, items, *, current_ms=None, protect=None):
        with self._condition:
            if self._closed or epoch is None or self._epoch != epoch:
                return
            self._protected_end_ms=protect[0] if protect else None
            self._protected_until=time.perf_counter()+protect[1] if protect else 0.
            if current_ms is not None:
                self._current_ms=float(current_ms)
                for key,item in tuple(self._pending.items()):
                    snapshot=getattr(item[1],'snapshot',None) if len(item)>1 else None
                    if snapshot is not None and snapshot.end_ms<=current_ms:
                        self._pending.pop(key,None);self._seen.pop(key,None)
                for key,value in tuple(self._ready.items()):
                    if value[2] is not None and value[2]<=current_ms:
                        self._ready.pop(key,None);self._seen.pop(key,None)
            for item in items:
                key = item[0]
                if key is None or key in self._seen or key in self._pending or key in self._ready or key == self._inflight:
                    continue
                self._seen[key] = None
                while len(self._seen) > MAX_SEEN:
                    self._seen.popitem(last=False)
                self._pending[key] = item
                self.requested += 1
                self._pending=OrderedDict(sorted(self._pending.items(),key=lambda row:row[1][2] if len(row[1])>2 else 0))
                while len(self._pending) > MAX_ITEMS:
                    dropped, _ = self._pending.popitem(last=True)
                    self._seen.pop(dropped, None)
            if self._pending and self.thread is None:
                self.thread = threading.Thread(target=self._work, name='caption-motion-preheat', daemon=True)
                self.thread.start()
            self._condition.notify()

    def take(self, epoch, keys):
        with self._condition:
            if self._closed or self._epoch != epoch:
                return ()
            if keys is None:keys=tuple(self._ready)
            result = tuple((key, self._ready.pop(key)[0]) for key in keys if key in self._ready)
            self.used += len(result)
            return result

    def has_ready(self, epoch):
        with self._condition:
            return not self._closed and self._epoch == epoch and bool(self._ready)

    def _work(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending)
                if self._closed:
                    return
                first=next(iter(self._pending.values()))
                snapshot=getattr(first[1],'snapshot',None) if len(first)>1 else None
                delay=self._protected_until-time.perf_counter()
                if (delay>0 and snapshot is not None and self._protected_end_ms is not None
                        and snapshot.start_ms>=self._protected_end_ms):
                    self._condition.wait(delay)
                    continue
                key, item = self._pending.popitem(last=False)
                self._inflight = key
                version = self._version
            try:
                value = self._builder(item)
                size = raster_bytes(value) if value is not None else 0
            except Exception:
                value, size = None, 0
            with self._condition:
                self._inflight = None
                if self._closed:
                    return
                if version != self._version or value is None or size > self._budget:
                    self.discarded += 1
                    continue
                snapshot=getattr(item[1],'snapshot',None) if len(item)>1 else None
                end_ms=snapshot.end_ms if snapshot is not None else None
                if end_ms is not None and self._current_ms is not None and end_ms<=self._current_ms:
                    self.discarded+=1;self._seen.pop(key,None)
                    continue
                self._ready[key] = (value, size, end_ms, item[2] if len(item)>2 else 0)
                self.built += 1
                while len(self._ready) > MAX_ITEMS or sum(v[1] for v in self._ready.values()) > self._budget:
                    farthest=max(self._ready,key=lambda key:self._ready[key][3])
                    self._ready.pop(farthest)
                    self._seen.pop(farthest,None)
                callback=self._ready_callback
            if callback is not None:callback()

    def stats(self):
        with self._condition:
            return dict(requested=self.requested, built=self.built, used=self.used, discarded=self.discarded,
                        pending=len(self._pending), ready=len(self._ready),
                        ready_bytes=sum(v[1] for v in self._ready.values()), inflight=int(self._inflight is not None))

    def close(self):
        with self._condition:
            self._closed = True
            self._ready_callback=None
            self._version += 1
            self._pending.clear()
            self._ready.clear()
            self._seen.clear()
            self._condition.notify_all()
