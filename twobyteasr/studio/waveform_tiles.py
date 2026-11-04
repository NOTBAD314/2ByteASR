"""Prepare waveform geometry on one worker, with one replaceable viewport job."""
from __future__ import annotations

from collections import OrderedDict
import copy
import time
import weakref

from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QPainterPath, QPolygonF

from ..playback.waveform_cache import WaveformCache
from ..rendering.latest_work import LatestWork


def build_envelope(cache, start, end, pixels, width):
    """No widgets or pixmaps; a path is private to this job until publication."""
    import numpy as np
    began=time.perf_counter()
    level,pairs=cache.read_window(start,end,pixels)
    if not len(pairs):
        return None
    def heights(values):
        value=np.abs(values)
        return np.clip((20.0*np.log10(np.maximum(value,1e-5))+48.0)/48.0,0.0,1.0)
    stride=max(1,int(np.ceil(len(pairs)/max(1,pixels/2))))
    span=max(1e-6,float(end)-float(start))
    expected=max(1.0,span/level.milliseconds_per_frame)
    x_scale=max(1.0,width)/expected
    origin=float(getattr(getattr(cache,'metadata',None),'sample_timeline_origin_ms',0.0) or 0.0)
    lead=max(0.0,origin-float(start))*max(1.0,width)/span
    if lead:
        expected=max(1.0,(float(end)-origin)/level.milliseconds_per_frame)
    indices=np.arange(0,len(pairs),stride)
    highs=heights(np.maximum.reduceat(pairs[:,1],indices)).tolist()
    lows=heights(np.minimum.reduceat(pairs[:,0],indices)).tolist()
    xs=(lead+indices*x_scale).tolist()
    points=[QPointF(x,-v) for x,v in zip(xs,highs)]
    points.extend(QPointF(x,v) for x,v in reversed(list(zip(xs,lows))))
    path=QPainterPath();path.addPolygon(QPolygonF(points));path.closeSubpath()
    stats=dict(level=level.level,milliseconds_per_bucket=level.milliseconds_per_frame,
        buckets=len(pairs),vertices=len(points),render_ms=(time.perf_counter()-began)*1000)
    return path,stats,len(pairs)>=expected*.98


class WaveformTileWorker(QObject):
    ready=Signal(object,object,object,object)

    def __init__(self,parent):
        super().__init__(parent)
        self.work=LatestWork('timeline-waveform-tiles')
        self.serial=0;self.signature=None;self.closed=False
        self.readers=OrderedDict()
        weak=weakref.ref(self)
        def retired(*_):
            worker=weak()
            if worker is not None:worker.close()
        parent.destroyed.connect(retired)

    def submit(self,jobs,epoch):
        signature=(id(epoch),tuple(jobs))
        if self.closed or signature==self.signature:
            return
        self.signature=signature;self.serial+=1;serial=self.serial
        frozen=tuple(jobs.items())
        def run():
            for key,(cache,start,end,pixels,width) in frozen:
                if self.closed or serial!=self.serial:
                    return
                try:
                    reader=cache
                    if isinstance(cache,WaveformCache):
                        # The GUI and the worker never mutate the same mmap/
                        # bucket caches. Retain the real owner and its leases.
                        row=self.readers.get(id(cache))
                        if row is None or row[0] is not cache:
                            reader=copy.copy(cache)
                            reader._maps={};reader._tiles=OrderedDict()
                            reader.stats={'hits':0,'misses':0,'points':0};reader._storage_leases=[]
                            self.readers[id(cache)]=(cache,reader)
                        else:reader=row[1]
                        self.readers.move_to_end(id(cache))
                        while len(self.readers)>8:self.readers.popitem(last=False)
                    result=build_envelope(reader,start,end,pixels,width)
                except (OSError,ValueError):result=None
                if self.closed:return
                try:self.ready.emit(epoch,key,cache,result)
                except RuntimeError:return
            if serial==self.serial:self.signature=None
        self.work.submit(run)

    def close(self):
        self.closed=True;self.serial+=1;self.work.close()
