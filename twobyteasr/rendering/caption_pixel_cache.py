"""Bounded, revision-keyed first-frame pixels prepared away from the GUI.

Snapshot/DOM readiness is insufficient for an atomic cue handoff. This cache
owns a separate browser lease for prefetch and never navigates the live page.
"""
from collections import OrderedDict
from dataclasses import dataclass
import threading
import time
import uuid
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage


@dataclass(frozen=True)
class PreparedPixels:
    image: QImage
    png: bytes | None
    started: float
    finished: float
    raw_path: object = None
    raw_geometry: object = None
    raw_lease: object = None

    def __del__(self):
        # The actor callback retains this object until the immutable file has
        # been consumed. Eviction/close then removes only this owned leaf.
        if self.raw_path is not None:
            try:self.raw_path.unlink(missing_ok=True)
            except OSError:pass
        if self.raw_lease is not None:
            try:self.raw_lease.__exit__(None, None, None)
            except Exception:pass


def prepared_pixels(image, png, started, raw_folder=None):
    """Pack immutable pixels on a worker before a GUI/actor handoff."""
    raw_path = geometry = lease = None
    if raw_folder is not None:
        import numpy as np
        from PySide6.QtCore import QRect
        packed = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        alpha = np.ndarray((packed.height(), packed.width(), 4), dtype=np.uint8,
            buffer=packed.constBits(), strides=(packed.bytesPerLine(), 4, 1))[:, :, 3]
        rows = np.flatnonzero(np.any(alpha, axis=1)); cols = np.flatnonzero(np.any(alpha, axis=0))
        bounds = QRect(int(cols[0]), int(rows[0]), int(cols[-1]-cols[0]+1), int(rows[-1]-rows[0]+1)) if rows.size and cols.size else QRect(0, 0, 1, 1)
        cropped = packed.copy(bounds)
        Path(raw_folder).mkdir(parents=True, exist_ok=True)
        raw_path = Path(raw_folder)/(uuid.uuid4().hex+'.rgba')
        raw_path.write_bytes(cropped.constBits())
        from .overlay_session import lease_overlay
        lease = lease_overlay(raw_path, 'caption_pixel_cache')
        geometry = dict(bounds=bounds.getRect(), source_width=packed.width(), source_height=packed.height(),
            width=cropped.width(), height=cropped.height(), stride=cropped.bytesPerLine(),
            bytes=cropped.sizeInBytes(), alpha_nonzero=int(np.count_nonzero(alpha)))
    return PreparedPixels(image, png, started, time.perf_counter(), raw_path, geometry, lease)


class CaptionPixelCache(QObject):
    ready = Signal(object)
    failed = Signal(object, str)

    def __init__(self, parent=None, *, budget_bytes=32*1024*1024, raw_folder=None):
        super().__init__(parent)
        self._budget=budget_bytes
        self._lock=threading.Lock()
        self._wake=threading.Event()
        self._closed=False
        self._pending=OrderedDict()
        self._images=OrderedDict()
        self._inflight=None
        self._thread=None
        self.metrics=[]
        self.raw_folder=Path(raw_folder) if raw_folder is not None else None
        if parent is not None: parent.destroyed.connect(self.close)

    def get(self, key):
        with self._lock:
            value=self._images.get(key)
            if value is not None:self._images.move_to_end(key)
            return value

    def request(self, key, snapshot, web, width, height, dpr):
        with self._lock:
            if self._closed or key in self._images or key==self._inflight:return
            self._pending[key]=(snapshot,web,width,height,dpr)
            while len(self._pending)>8:self._pending.popitem(last=False)
            self._wake.set()
            if self._thread is None:
                self._thread=threading.Thread(target=self._run,name='caption-pixels',daemon=True)
                if self.raw_folder is not None:
                    from .overlay_session import register_overlay_worker
                    register_overlay_worker(self.raw_folder.parent, self._thread)
                self._thread.start()

    def _run(self):
        service=None;loaded=None
        try:
            while True:
                self._wake.wait()
                with self._lock:
                    if self._closed:return
                    if not self._pending:self._wake.clear();continue
                    key,task=self._pending.popitem(last=False);self._inflight=key
                snapshot,web,width,height,dpr=task
                started=time.perf_counter()
                try:
                    png=None
                    if web is None:
                        from .advanced_live_renderer import render_live_snapshot
                        image=render_live_snapshot(snapshot,width=width,height=height,device_pixel_ratio=dpr)
                    else:
                        from .renderer_service import GLOBAL_RENDERER_SERVICE,LiveRendererSession
                        if service is None:service=LiveRendererSession(GLOBAL_RENDERER_SERVICE)
                        page=(web.theme_key,width,height)
                        if loaded!=page:
                            service.live_set(web.html,width=width,height=height);loaded=page
                        service.live_text(text=web.text,speaker=web.speaker,duration_ms=web.duration*1000,placement=web.placement)
                        png=service.live_frame(cue_ms=0,stage_ms=snapshot.start_ms)
                        image=QImage.fromData(png)
                    if image.isNull():raise ValueError('Empty prepared caption raster')
                    raw_path=None;geometry=None;lease=None
                    if self.raw_folder is not None:
                        import numpy as np
                        from PySide6.QtCore import QRect
                        packed=image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                        alpha=np.ndarray((packed.height(),packed.width(),4),dtype=np.uint8,buffer=packed.constBits(),strides=(packed.bytesPerLine(),4,1))[:,:,3]
                        rows=np.flatnonzero(np.any(alpha,axis=1));cols=np.flatnonzero(np.any(alpha,axis=0))
                        bounds=QRect(int(cols[0]),int(rows[0]),int(cols[-1]-cols[0]+1),int(rows[-1]-rows[0]+1)) if rows.size and cols.size else QRect(0,0,1,1)
                        cropped=packed.copy(bounds)
                        self.raw_folder.mkdir(parents=True,exist_ok=True)
                        raw_path=self.raw_folder/(uuid.uuid4().hex+'.rgba')
                        raw_path.write_bytes(cropped.constBits())
                        from .overlay_session import lease_overlay
                        lease=lease_overlay(raw_path, 'caption_pixel_cache')
                        geometry=dict(bounds=bounds.getRect(),source_width=packed.width(),source_height=packed.height(),
                            width=cropped.width(),height=cropped.height(),stride=cropped.bytesPerLine(),bytes=cropped.sizeInBytes(),
                            alpha_nonzero=int(np.count_nonzero(alpha)))
                    value=PreparedPixels(image,png,started,time.perf_counter(),raw_path,geometry,lease)
                    with self._lock:
                        if self._closed:return
                        self._images[key]=value
                        total=sum(v.image.sizeInBytes()+len(v.png or b'')+(v.raw_geometry or {}).get('bytes',0) for v in self._images.values())
                        while total>self._budget and len(self._images)>1:
                            _,old=self._images.popitem(last=False)
                            total-=old.image.sizeInBytes()+len(old.png or b'')+(old.raw_geometry or {}).get('bytes',0)
                    self.metrics.append(dict(cue_id=snapshot.cue_id,started=started,finished=value.finished,
                                             route='html' if web else 'static',bytes=image.sizeInBytes(),raw_geometry=geometry))
                    self.metrics=self.metrics[-128:]
                    # A closed cache is deleted with its project session.
                    try:self.ready.emit(key)
                    except RuntimeError:return
                except Exception as exc:
                    loaded=None
                    try:self.failed.emit(key,f'{type(exc).__name__}: {exc}')
                    except RuntimeError:return
                finally:
                    with self._lock:self._inflight=None
        finally:
            if service is not None:
                try:service.close()
                except Exception:pass

    def close(self, *_):
        with self._lock:
            self._closed=True;self._pending.clear();self._images.clear();self._wake.set()
