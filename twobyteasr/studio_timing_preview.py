"""Transient timing view feeding Studio's existing LIVE canvas and owner.

Rasters and scene bindings are prepared before gestures on workers; pointer frames only change
intervals and sample the existing canvas. No project/revision/undo writes.
"""
from __future__ import annotations

import threading
from dataclasses import replace

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtGui import QPixmap

from .advanced_live_renderer import render_live_snapshot
from .visual_snapshot import build_visual_cue_snapshot
from .visual_runtime import VisualOwner


class CueTimingPreview(QObject):
    ready = Signal(int, str, object, object)

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.active = False
        self.generation = 0
        self.values = {}
        self.frames = {}
        self.bound_cue = ""
        self.ready.connect(self._ready)
        self._cache = {}
        self._warm_generation = 0
        self._warm_timer = QTimer(self)
        self._warm_timer.setSingleShot(True)
        self._warm_timer.setInterval(35)
        self._warm_timer.timeout.connect(self._warm)

    def request_warm(self):
        page = self.page
        if (not self.active and not self._warm_timer.isActive()
                and not getattr(page.timeline, '_scrub_drag', False)
                and not getattr(page.timeline, '_pan_drag', None)
                and bool(getattr(page.video, '_paused', True))):
            self._warm_timer.start()

    def _warm(self):
        page=self.page
        if (self.active or not page.project or getattr(page,"_close_requested",False)
                or getattr(page.timeline, '_scrub_drag', False)
                or getattr(page.timeline, '_pan_drag', None)
                or not bool(getattr(page.video, '_paused', True))):return
        self._warm_generation+=1
        generation=self._warm_generation
        width,height=page._advanced_preview_size()
        selected=set(page.timeline.selected_ids)
        selected.add(page.selected_cue_id)
        # Prepare visible neighbours too: moving off the playhead may reveal one.
        candidates=page.timeline._cues_intersecting(max(0,page.timeline.playhead_ms-8000),page.timeline.playhead_ms+8000)
        by_id={c.id:c for c in candidates}
        by_id.update({key:page.timeline._timeline_cue_by_id[key] for key in selected if key in page.timeline._timeline_cue_by_id})
        self._warm_ids=[c.id for c in sorted(by_id.values(),key=lambda c:(c.id not in selected,abs(c.start_ms-page.timeline.playhead_ms)))[:8]]
        self._warm_next()

    def _warm_next(self):
        page=self.page
        if getattr(self,'_warm_busy',False):return
        if (self.active or getattr(page,'_close_requested',False) or not page.project
                or getattr(page.timeline,'_scrub_drag',False) or getattr(page.timeline,'_pan_drag',None)
                or not bool(getattr(page.video,'_paused',True))):
            self._warm_ids=[]
            return
        ids=getattr(self,'_warm_ids',[])
        if not ids:return
        cue_id=ids.pop(0)
        if cue_id not in page.timeline._timeline_cue_by_id:
            QTimer.singleShot(0,self._warm_next);return
        generation=self._warm_generation
        width,height=page._advanced_preview_size()
        snapshot=build_visual_cue_snapshot(page.project,cue_id,width=width,height=height,fps=30.)
        if snapshot is None:  # 派生 id 已随视图重建失效：跳过该预热项
            QTimer.singleShot(0,self._warm_next);return
        if snapshot.stable_hash() in self._cache:
            QTimer.singleShot(0,self._warm_next);return
        self._warm_busy=True
        def prepare():
            from .studio_live_canvas import compiled_scene_for_snapshot
            from .advanced_live_renderer import render_live_layers
            from .live_layer_cache import GLOBAL_LIVE_LAYER_CACHE,live_layer_cache_key
            try:
                scene=compiled_scene_for_snapshot(snapshot)
                image=render_live_snapshot(snapshot,width=width,height=height,device_pixel_ratio=1.)
                if scene is not None and not self.active:
                    key=live_layer_cache_key(snapshot,width=width,height=height,device_pixel_ratio=1.)
                    if GLOBAL_LIVE_LAYER_CACHE.materialize(key,snapshot=snapshot) is None:
                        GLOBAL_LIVE_LAYER_CACHE.store(key,render_live_layers(snapshot,width=width,height=height,device_pixel_ratio=1.))
                self.ready.emit(generation,snapshot.cue_id,(image,scene),snapshot)
            except Exception:
                self.ready.emit(generation,snapshot.cue_id,None,snapshot)
        threading.Thread(target=prepare,daemon=True,name="timeline-live-warm").start()

    def start(self, values):
        page = self.page
        self.generation += 1
        generation = self.generation
        self.active = True
        self.values = dict(values)
        self.frames = {}
        self.bound_cue = ""
        self._warm_timer.stop()
        page._advanced_live_inflight_key = ""
        page._visual_update_timer.stop()
        page._initial_preview_timer.stop()
        width, height = page._advanced_preview_size()
        # Include the cue beneath the playhead, so moving the selection off it
        # can expose the unchanged neighbour without consulting stale ASS.
        cue_ids = set(values)
        cue_ids.update(c.id for c in page.project.cues
                       if c.start_ms <= page.timeline.playhead_ms < c.end_ms)
        snapshots = [build_visual_cue_snapshot(page.project, key, width=width,
                                              height=height, fps=30.) for key in cue_ids]
        canvas = page.advanced_cue_overlay
        for snapshot in snapshots:
            if (canvas._snapshot is not None
                    and canvas._snapshot.stable_hash() == snapshot.stable_hash()
                    and not canvas._source.isNull()):
                self.frames[snapshot.cue_id] = (QPixmap(canvas._source), snapshot, canvas._compiled_scene)

        for snapshot in snapshots:
            cached=self._cache.get(snapshot.stable_hash())
            if cached is not None:self.frames[snapshot.cue_id]=cached
        self.present()

    def _ready(self, generation, cue_id, image, snapshot):
        self._warm_busy=False
        QTimer.singleShot(0,self._warm_next)
        if generation != self._warm_generation or image is None:return
        raster,scene=image
        entry=(QPixmap.fromImage(raster),snapshot,scene)
        self._cache[snapshot.stable_hash()]=entry
        if len(self._cache)>96:self._cache.pop(next(iter(self._cache)))
        if self.active:
            width,height=self.page._advanced_preview_size()
            current=build_visual_cue_snapshot(self.page.project,cue_id,width=width,height=height,fps=30.)
            if current.stable_hash()==snapshot.stable_hash():
                self.frames[cue_id]=entry
                self.present()

    def update(self, values):
        if not self.active:
            return
        self.values = dict(values)
        page = self.page
        selected = values.get(page.selected_cue_id)
        if selected is not None:
            page._updating_editor = True
            try:
                page.start_ms.setValue(selected.start_ms)
                page.duration_ms.setValue(selected.end_ms-selected.start_ms)
            finally:
                page._updating_editor = False
        self.present()

    def cue_at_playhead(self):
        page = self.page
        position = page.timeline.playhead_ms
        candidates = []
        for cue in page.project.cues:
            value = self.values.get(cue.id)
            if value:
                cue = replace(cue, start_ms=value.start_ms, end_ms=value.end_ms,
                              speaker_id=value.speaker_id)
            if (cue.start_ms <= position < cue.end_ms
                    and page._subtitle_track_visibility.get(cue.speaker_id, True)
                    and cue.speaker_id not in page.timeline.hidden_speakers):
                candidates.append(cue)
        return next((c for c in candidates if c.id == page.selected_cue_id),
                    candidates[0] if candidates else None)

    def present(self):
        page = self.page
        if getattr(page,'_present_caption_scene',lambda:False)():return page.subtitle_visibility_trace(reason='timing_preview')
        canvas = page.advanced_cue_overlay
        cue = self.cue_at_playhead() if self.active else None
        frame = self.frames.get(cue.id) if cue else None
        page.video.set_native_subtitle_visible(False)
        worker=getattr(page,'_web_live_worker',None)
        recipe=page.project.style_recipes.get(cue.style_id,{}) if cue else {}
        if (cue and recipe.get('webTheme') and worker is not None and worker.running
                and getattr(page,'_web_live_cue_id','')==cue.id):
            # Keep the actual HTML foreground during a timing gesture. Only
            # cue-local clock/span change; the worker coalesces DOM updates on
            # its existing page without compiling an ASS or Graph scene.
            span=max(.05,(cue.end_ms-cue.start_ms)/1000.)
            if abs(worker._strip_span_ms-span*1000)>.5:
                worker.configure(theme=recipe['webTheme'],text=cue.text,
                    speaker=worker._strip_speaker,duration_seconds=span)
            canvas.setVisible(True)
            page._visual_ownership.commit(VisualOwner.ADVANCED_LIVE,cue_id=cue.id,
                snapshot_hash=getattr(canvas._snapshot,'stable_hash',lambda:'')(),request_key='timeline-web-preview')
            return
        if frame:
            pixmap, snapshot, scene = frame
            if self.bound_cue != cue.id:
                canvas.set_base_geometry(page.position_overlay._content_rect().toRect())
                canvas.set_visual(pixmap, snapshot, prepared_scene=scene)
                self.bound_cue = cue.id
            canvas.set_timing_preview(cue.start_ms, cue.end_ms)
            canvas.setVisible(True)
            canvas.sync_time(page.timeline.playhead_ms, paused=bool(page.video._paused))
            page._visual_ownership.commit(VisualOwner.ADVANCED_LIVE, cue_id=cue.id,
                                           snapshot_hash=snapshot.stable_hash(), request_key="timeline-preview")
        else:
            canvas.hide()
            self.bound_cue = ""
            page._visual_ownership.commit(VisualOwner.NONE, cue_id="", snapshot_hash="", request_key="")
        return page.subtitle_visibility_trace(reason="timing_preview")

    def finish(self, committed):
        if not self.active:
            return
        self.active = False
        self.generation += 1
        self.page.advanced_cue_overlay.set_timing_preview()
        self.values = {}
        self.frames = {}
        self.bound_cue = ""
        page = self.page
        page._advanced_active_cue_id = ""
        if page.project and page.selected_cue_id:
            page.cue_controller._select_cue_ui(page.selected_cue_id, refresh_advanced=False)
        page._activate_selected_advanced_if_needed(force=True)
        page.ensure_active_subtitle_renderer(reason="timing_finished")
        self.request_warm()
