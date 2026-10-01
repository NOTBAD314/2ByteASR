"""Bounded prepared-raster handoff on the existing mpv observation thread.

Only immutable pixels/geometry cross this boundary. No Qt work, font lookup,
DOM work, rasterization, or file creation happens on a media observation.
"""
from dataclasses import dataclass
import threading,time


@dataclass(frozen=True)
class BoundaryPixels:
    cue_id: str
    start_ms: int
    end_ms: int
    pixels: object
    geometry: dict


class CaptionBoundaryPublisher:
    def __init__(self,controller,overlay_id,frame_rate=None):
        self.controller=controller;self.overlay_id=overlay_id
        self.lock=threading.RLock();self.token=None;self.entries={};self.active=None
        self.observation={};self.metrics=[];self.closed=False;self.source_epoch=None
        self.frame_rate=frame_rate

    def register(self,token,entry):
        with self.lock:
            if self.closed:return
            epoch=self.controller.source_epoch
            if token!=self.token or epoch!=self.source_epoch:
                self.entries.clear();self.active=None;self.token=token;self.source_epoch=epoch
            previous=self.entries.get(entry.cue_id)
            if previous and previous.pixels is entry.pixels:return
            self.entries[entry.cue_id]=entry
            while len(self.entries)>8:
                oldest=min(self.entries,key=lambda k:self.entries[k].end_ms)
                del self.entries[oldest]

    def allows(self,cue_id):
        with self.lock:
            if self.closed or self.controller.source_epoch!=self.source_epoch or self.observation.get('paused',True) or self.active is None:return True
            if self.active=='' and cue_id not in self.entries:return True
            return self.active==cue_id

    def observe(self,observation):
        with self.lock:
            self.observation=observation
            if self.closed or observation.get('paused',True) or observation.get('seeking') or self.controller.source_epoch!=self.source_epoch:return
            value=observation.get('position')
            if value is None:return
            from .caption_frame_time import observed_frame_ms
            ms=observed_frame_ms(float(value)*1000,self.frame_rate)
            matches=[entry for entry in self.entries.values() if entry.start_ms<=ms<entry.end_ms]
            # Overlapping captions keep the existing GUI speaker/selection
            # policy. This fast path only owns unambiguous source intervals.
            if len(matches)>1:self.active=None;return
            entry=matches[0] if matches else None
            current=entry.cue_id if entry else ''
            if current==self.active:return
            previous=self.active;self.active=current;token=self.token;epoch=self.source_epoch
        # Never acquire the actor queue lock while holding this state lock:
        # coalesced callbacks can acquire the state lock in the other order.
        if entry is None:
            if previous:self.controller.post_remove_overlay(self.overlay_id)
            return
        posted=time.perf_counter()
        timing={}
        def valid():
            with self.lock:
                return not self.closed and token==self.token and epoch==self.controller.source_epoch and self.active==entry.cue_id and not self.observation.get('paused',True)
        def applied(ok,keep=entry):
            with self.lock:
                self.metrics.append(dict(cue_id=keep.cue_id,source_ms=float(ms),source_epoch=epoch,
                    posted_at=posted,applied_at=time.perf_counter(),applied=bool(ok),
                    command_started=timing.get('started'),
                    alpha_nonzero=keep.pixels.raw_geometry['alpha_nonzero']))
                del self.metrics[:-2048]
                if not ok and not self.closed and token==self.token and self.active==keep.cue_id:
                    self.active=None  # retry on a later observation, never spin
        self.controller.post_raw_overlay(self.overlay_id,entry.pixels.raw_path,
            valid_when=valid,on_applied=applied,on_started=lambda:timing.update(started=time.perf_counter()),
            coalesce_key=f'caption-boundary:{self.overlay_id}',**entry.geometry)

    def close(self):
        with self.lock:self.closed=True;self.entries.clear();self.active=None
