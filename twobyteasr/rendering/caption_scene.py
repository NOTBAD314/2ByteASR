"""Render the visible cue set into one atomic foreground raster.

Track order determines compositing only. Each authored cue keeps its own
placement, scale, theme and cue-local animation time.
"""
from collections import OrderedDict
from dataclasses import replace
import copy
import hashlib
import math
import threading
import time

from PySide6.QtCore import QEvent, QCoreApplication, QObject, Signal, QRect, Qt
from PySide6.QtGui import QImage, QPainter

from ..i18n import bind_text

from ..i18n import tr


# Wall-clock bound for keeping the previous raster while the next cue set's
# raster is still being drawn during ordinary playback.
HOLD_PREVIOUS_MS = 300
# How often a long-lived cue set re-checks that the coming boundaries are warm.
PREHEAT_INTERVAL_S = 0.25
# Look-ahead in WALL seconds; media look-ahead scales with the preview rate.
PREHEAT_AHEAD_WALL_S = 1.5
PREHEAT_MIN_BOUNDARIES = 2
PREHEAT_MAX_BOUNDARIES = 6
FRAME_CACHE_BYTES = 256 * 1024 * 1024
GLYPH_CACHE_BYTES = 96 * 1024 * 1024
_FRAME_READY_EVENT=QEvent.Type(QEvent.registerEventType())


class _FrameReadyEvent(QEvent):
    def __init__(self):super().__init__(_FRAME_READY_EVENT)


def complete_scene_for_seek(scene, cue_id, generation):
    """An atomic bilingual/multi-cue foreground owns a scene, not one cue ID."""
    if (scene is None or not getattr(scene,'active',False) or getattr(scene,'closed',True)
            or getattr(scene,'published',None) is None):
        return False
    token = getattr(scene,'token',None)
    if (token is None or len(token)<5 or token[3]!=generation or cue_id not in token[4]
            or getattr(scene,'last_result_token',None)!=token or not scene.still_current(token)):
        return False
    state = scene.trace()
    rows = state.get('cue_pixels') or ()
    ready = {row.get('cue_id') for row in rows if row.get('status')!='pending'}
    return bool(rows and set(state.get('expected_display_cue_ids') or token[4]) <= ready
                and all(row.get('status')!='pending' for row in rows))


def active_cues(page, milliseconds):
    project = page.project
    if project is None:
        return ()
    runtime = page.session.runtime
    cues = runtime.cues_at(milliseconds) if runtime else (
        c for c in project.cues if c.start_ms <= milliseconds < c.end_ms)
    timing=getattr(page,'_cue_timing_preview',None)
    if timing is not None and timing.active:
        candidates={c.id:c for c in cues}
        by_id=runtime.cue_by_id if runtime else {c.id:c for c in project.cues}
        for key,value in timing.values.items():
            candidates.pop(key,None)
            if key in by_id and value.start_ms<=milliseconds<value.end_ms:
                candidates[key]=replace(by_id[key],start_ms=value.start_ms,end_ms=value.end_ms,speaker_id=value.speaker_id)
        cues=candidates.values()
    hidden = getattr(page.timeline, 'hidden_speakers', set())
    order = {key: index for index, key in enumerate(getattr(page.timeline, '_speaker_ids', ()))}
    return tuple(sorted((c for c in cues if c.speaker_id not in hidden
                         and page._subtitle_track_visibility.get(c.speaker_id, True)),
                        key=lambda c: (-order.get(c.speaker_id, 0), c.start_ms, c.id)))


class WebSceneCache:
    """Independent browser work cannot hold up native/static cue pixels."""
    def __init__(self, changed):
        self.changed = changed
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        self.images = OrderedDict()
        self.inflight = set()
        self.errors = {}
        self.closed = False
        self.workers = []
        self.active_keys = None
        self.prefetch_pending = OrderedDict()
        self.prefetch_errors = set()
        self.generation = None

    def _wake_workers(self):
        if len(self.workers) < min(3, len(self.pending)+len(self.prefetch_pending)+len(self.inflight)):
            thread = threading.Thread(target=self.work, name='caption-scene-web', daemon=True)
            self.workers.append(thread); thread.start()
        self.condition.notify()

    def prefetch(self, key, web, cue_ms, stage_ms, width, height):
        """Low-priority first frames use the same project/clip time as playback."""
        with self.condition:
            if self.closed or key in self.images or key in self.inflight or key in self.pending or key in self.prefetch_errors:
                return
            self.generation = key[1]
            for previous in tuple(self.prefetch_pending):
                if previous[1] != self.generation: del self.prefetch_pending[previous]
            self.prefetch_pending[key] = (web, cue_ms, stage_ms, width, height)
            while len(self.prefetch_pending)>6:self.prefetch_pending.popitem(last=False)
            self._wake_workers()

    def retain(self, keys):
        """A seek/cue change retires queued HTML frames, including old generations."""
        with self.condition:
            self.active_keys = frozenset(keys)
            if self.active_keys:
                first = next(iter(self.active_keys))
                if isinstance(first, tuple): self.generation = first[1]
            for key in tuple(self.pending):
                if key not in self.active_keys:
                    del self.pending[key]

    def get(self, key, web, cue_ms, stage_ms, width, height):
        with self.condition:
            cached = self.images.get(key)
            if key not in self.inflight and key not in self.errors and (cached is None or cached[1] != cue_ms):
                self.pending[key] = (web, cue_ms, stage_ms, width, height)
                self.pending.move_to_end(key)
                self.prefetch_pending.pop(key, None)
                self._wake_workers()
            return cached[0] if cached else None, self.errors.get(key)

    def work(self):
        service = loaded = bound = None
        from .renderer_service import GLOBAL_RENDERER_SERVICE, LiveRendererSession
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.closed or self.pending or self.prefetch_pending)
                    if self.closed: return
                    warming = not bool(self.pending)
                    key, (web, cue, stage, width, height) = (
                        self.prefetch_pending.popitem(last=False) if warming else self.pending.popitem(last=True))
                    self.inflight.add(key)
                try:
                    if service is None: service = LiveRendererSession(GLOBAL_RENDERER_SERVICE)
                    page_key = (web.theme_key, width, height)
                    if page_key != loaded:
                        service.live_set(web.html, width=width, height=height); loaded = page_key; bound = None
                    with self.condition:
                        if ((not warming and self.active_keys is not None and key not in self.active_keys)
                                or (warming and key[1] != self.generation)):
                            continue
                    if bound != web.strip_key:
                        service.live_text(text=web.text, speaker=web.speaker, duration_ms=web.duration*1000, placement=web.placement, **({'translation':web.translation} if getattr(web,'translation','') else {}))
                        bound = web.strip_key
                    image = QImage.fromData(service.live_frame(cue_ms=cue, stage_ms=stage))
                    if image.isNull(): raise ValueError('empty HTML raster')
                    with self.condition:
                        if self.closed: return
                        self.images[key] = (image, cue)
                        self.images.move_to_end(key)
                        while len(self.images)>1 and sum(v[0].sizeInBytes() for v in self.images.values())>48*1024*1024:
                            self.images.popitem(last=False)
                except Exception as exc:
                    loaded = bound = None
                    with self.condition:
                        if warming:
                            self.prefetch_errors.add(key)
                            if len(self.prefetch_errors)>64:self.prefetch_errors.clear()
                        else: self.errors[key] = f'{type(exc).__name__}: {exc}'
                    # Discard the failed lease. The next cue gets a fresh page;
                    # the failed key remains quarantined (no per-frame retries).
                    if service is not None:
                        try: service.close()
                        except Exception: pass
                    service = None
                finally:
                    with self.condition: self.inflight.discard(key)
                if not self.closed and (not warming or key in (self.active_keys or ())): self.changed()
        finally:
            if service is not None:
                try: service.close()
                except Exception: pass

    def close(self):
        with self.condition:
            self.closed = True
            self.pending.clear(); self.images.clear(); self.errors.clear()
            self.prefetch_pending.clear(); self.prefetch_errors.clear()
            self.condition.notify_all()


class SceneRasterizer:
    """Worker-owned rasters and browser leases; a bad cue never aborts peers."""
    def __init__(self, web_cache=None):
        self.rasters = OrderedDict()
        self.pages = OrderedDict()
        self.web_cache = web_cache

    def insert_raster(self, key, value):
        """Adopt a completed worker-owned raster under the existing budget."""
        if key in self.rasters:
            return
        from .caption_motion_preheater import raster_bytes
        self.rasters[key] = value
        while len(self.rasters) > 1 and sum(raster_bytes(v) for v in self.rasters.values()) > GLYPH_CACHE_BYTES:
            self.rasters.popitem(last=False)

    def frame(self, prepared_cues, milliseconds, width, height, generation=0, retire_web=True,
              measure_cue_geometry=True):
        from .advanced_live_renderer import (render_live_snapshot, render_live_layers,
            composite_live_scene_layers, composition_pivot_for_snapshot)
        from .studio_live_canvas import compiled_scene_for_snapshot
        output = painter = None
        def canvas():
            nonlocal output, painter
            if output is None:
                output = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
                output.fill(Qt.transparent)
            if painter is None:
                painter = QPainter(output)
            return painter
        evidence = []
        # Every prepared snapshot already carries its saved initial/manual
        # anchor. Visible peers never change a cue's placement during playback.
        from .caption_playback_cache import FailedCaption as _FailedCaption
        prepared_cues = tuple(prepared_cues)
        single = prepared_cues[0][1] if len(prepared_cues) == 1 else None
        share_single = bool(single is not None and not isinstance(single, _FailedCaption)
            and single.web is None and getattr(single.route, 'engine', None) == 'native'
            and not getattr(single, 'preview_error', '') and not getattr(single, 'interaction_transform', None)
            and not animated_caption(single))
        prepared_cues = tuple((key, p.fallback if isinstance(p, _FailedCaption) and p.fallback else p)
                             for key, p in prepared_cues)

        if self.web_cache is not None and retire_web:
            self.web_cache.retain((p.snapshot_hash, generation, width, height)
                for _, p in prepared_cues if p is not None and not isinstance(p, _FailedCaption) and p.web)

        for cue_id, prepared in prepared_cues:
            row = {'cue_id': cue_id, 'status': 'pending'}
            evidence.append(row)
            if prepared is None:
                continue
            from .caption_playback_cache import FailedCaption
            if isinstance(prepared,FailedCaption):
                row.update(status='failed',error=prepared.error);continue
            snapshot = prepared.snapshot
            relative = max(0, milliseconds - snapshot.start_ms)
            row.update(snapshot_hash=prepared.snapshot_hash,
                       route='html' if prepared.web else prepared.route.engine,
                       position=[snapshot.position_x, snapshot.position_y], local_ms=float(relative))
            try:
                if prepared.web:
                    web = prepared.web
                    if self.web_cache is not None:
                        image, error = self.web_cache.get((prepared.snapshot_hash, generation, width, height), web,
                            float(relative), float(milliseconds), width, height)
                        if error:
                            raise RuntimeError(error)
                        if image is None:
                            continue
                    else:
                        raise RuntimeError('HTML worker required')
                else:
                    image = self.native_frame(prepared, relative, width, height)
                if image.isNull():
                    raise ValueError('empty raster')
                gesture=getattr(prepared,'interaction_transform',None)
                if (share_single and image.width() == width and image.height() == height
                        and image.format() == QImage.Format_ARGB32_Premultiplied
                        and image.devicePixelRatio() == 1.0 and not image.colorSpace().isValid()):
                    # Both 64 MiB caches retain their existing entries/budgets,
                    # but a single immutable raster need not own two buffers.
                    # A NEW wrapper preserves Qt copy-on-write isolation from
                    # the inner cache; never return its mutable wrapper itself.
                    output = QImage(image)
                else:
                    paint = canvas()
                    paint.save()
                    if gesture:
                        px=width/max(1,snapshot.playres_x);py=height/max(1,snapshot.playres_y)
                        paint.translate(gesture['position_x']*px,gesture['position_y']*py)
                        paint.rotate(gesture.get('rotation',snapshot.rotation)-snapshot.rotation)
                        paint.scale(gesture['scale_x']/100/max(.0001,snapshot.scale_x),
                                      gesture['scale_y']/100/max(.0001,snapshot.scale_y))
                        paint.translate(-snapshot.position_x*px,-snapshot.position_y*py)
                    paint.drawImage(output.rect(), image)
                    paint.restore()
                row.update(status='rendered', viewport=[image.width(),image.height()])
                if measure_cue_geometry:
                    from .alpha_geometry import alpha_metrics
                    bounds, alpha_nonzero = alpha_metrics(image)
                    row.update(alpha_nonzero=alpha_nonzero,
                               bounds=list(bounds) if bounds is not None else None)
                if prepared.preview_error:
                    row.update(status='fallback', error=prepared.preview_error)
            except Exception as exc:
                if prepared.web or prepared.route.engine=='remotion':
                    row.update(status='failed',error=f'{type(exc).__name__}: {exc}',hidden_until_ready=True)
                    continue
                row.update(status='fallback', error=f'{type(exc).__name__}: {exc}')
                try:
                    basic = replace(snapshot, style_recipe={}, motion_recipe={'mode':'none'},
                                    shadow={}, glow={}, fill='#FFFFFFFF',
                                    strokes=({'width':2, 'color':'#FF000000', 'alignment':'OUTSIDE'},))
                    canvas().drawImage(output.rect(), render_live_snapshot(basic, width=width, height=height))
                except Exception as fallback_error:
                    row.update(status='failed', fallback_error=str(fallback_error))
        if output is None:
            canvas()
        if painter is not None:
            painter.end()
        return output, evidence

    def native_frame(self, prepared, relative, width, height):
        from .advanced_live_renderer import (render_live_snapshot, render_live_layers,
            composite_live_scene_layers, composition_pivot_for_snapshot)
        from .studio_live_canvas import compiled_scene_for_snapshot
        snapshot = prepared.snapshot
        from ..caption_style.word_animation import word_state,uniform_line_unit
        plan = getattr(snapshot, 'word_animation', None) or {}
        uniform=uniform_line_unit(plan) if snapshot.style_recipe.get('visualGraph') else None
        key = (prepared.snapshot_hash, width, height, ('uniform-line',) if uniform is not None else word_state(plan, relative))
        cached = self.rasters.get(key)
        if cached is None:
            scene = compiled_scene_for_snapshot(snapshot)
            neutral=(min(float(uniform['frames'][0][0]),
                float(uniform['loop'].get('start',0))-float(uniform['loop'].get('offset',0)))-1) if uniform is not None else relative
            layers = render_live_layers(snapshot, width=width, height=height,
                word_time_ms=neutral) if scene and (scene.tracks or uniform is not None) else None
            if layers is not None and uniform is not None:layers.uniform_unit=uniform
            image = render_live_snapshot(snapshot, width=width, height=height, word_time_ms=relative) if layers is None else None
            cached = (scene, layers, image)
            self.insert_raster(key, cached)
        self.rasters.move_to_end(key)
        scene, layers, image = cached
        if layers is not None:
            image, _ = composite_live_scene_layers(layers, scene, relative,
                pivot=composition_pivot_for_snapshot(snapshot, width, height))
        return image

    def close(self):
        self.rasters.clear()


def animated_caption(prepared):
    from .caption_playback_cache import FailedCaption
    if prepared is None or isinstance(prepared,FailedCaption):return False
    snapshot=prepared.snapshot
    if any((getattr(snapshot, 'word_animation', None) or {}).get(key) for key in ('spans','units')):
        return True
    if prepared.web:
        theme=snapshot.style_recipe.get('webTheme',{})
        return bool(theme.get('motionSpec',{}).get('tracks') or any(
            word in str(theme.get('cueCss',''))+str(theme.get('stageCss','')) for word in ('animation','@keyframes')))
    graph=snapshot.style_recipe.get('visualGraph') or {}
    return bool(snapshot.motion_recipe.get('mode','none')!='none' or graph.get('motionGraph',{}).get('tracks'))


def scene_raster_geometry(page, rect, prepared):
    """Static native pixels survive viewport moves; HTML/motion retain exact sizing."""
    dpr=max(1.,float(page.video.devicePixelRatioF()))
    width=max(1,round(rect.width()*dpr));height=max(1,round(rect.height()*dpr))
    factor=min(1.,math.sqrt(1_200_000/(width*height)))
    natural=(max(1,round(width*factor)),max(1,round(height*factor)))
    reusable=bool(prepared) and all(p is not None and hasattr(p,'snapshot') and not p.web
                                    and not animated_caption(p) for _,p in prepared)
    if reusable:
        overlay=page.position_overlay;media=page.project.media
        video_w=getattr(overlay,'video_width',0) or getattr(media,'width',0)
        video_h=getattr(overlay,'video_height',0) or getattr(media,'height',0)
        aspect=video_w/video_h if video_w and video_h else rect.width()/max(1,rect.height())
        cap=max(1,int(math.sqrt(1_200_000*aspect)))
        tiers=sorted({min(cap,n) for n in (320,640,960,1280,cap)})
        tier=next((n for n in tiers if n>=width),cap)
        natural=(tier,max(1,round(tier/aspect)))
    prepare_size=getattr(page,'_caption_tick_geometry',None)
    if prepare_size is None:
        get_size=getattr(page,'_advanced_preview_size',None)
        prepare_size=get_size() if callable(get_size) else None
    return (*natural,reusable,tuple(prepare_size) if prepare_size else None)


class CaptionScene(QObject):
    ready = Signal(object, object, object)
    web_ready = Signal()
    warm_ready = Signal()

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.project = page.project
        self.active = False
        self.closed = False
        self.token = None
        self.pending = None
        self.warm_pending = OrderedDict()
        self.wanted_times = []
        self.warm_completed = OrderedDict()
        self._priority_warm_time=None
        self._seek_reserved_frame=None
        self.frames = OrderedDict()
        self.last_request = None
        self.published = None
        self.failures = {}
        self.metrics = []
        self._delivery_pending=None
        self._delivery_scheduled=False
        self.schedule_counts = dict(replaced=0, stale_before_raster=0, stale_at_gui=0)
        self.cache_counts = dict(memory_hits=0, memory_misses=0, evictions=0)
        self.disk_stats = {}
        self._hold = None
        self._cleared_token = None
        self._last_preheat = 0.0
        self._glyph_ready_keys=frozenset()
        self._media_ms=0.
        self._short_active=False
        from .caption_motion_preheater import CaptionMotionPreheater
        self._motion_preheater = CaptionMotionPreheater(ready=self._motion_ready)
        self._motion_warm_epoch = None
        from PySide6.QtCore import QTimer
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._hold_expired)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.web_ready.connect(self.refresh_web)
        self.warm_ready.connect(self.warm_current)
        self.web_cache = WebSceneCache(self._notify_web_ready)
        self.thread = threading.Thread(target=self.work, name='caption-scene', daemon=True)
        overlay_folder = getattr(self.page.video, '_compositor_overlay_dir', None)
        self._raw_folder = overlay_folder / 'caption-scenes' if overlay_folder is not None else None
        if overlay_folder is not None:
            from .overlay_session import register_overlay_worker
            register_overlay_worker(overlay_folder, self.thread)
        self.thread.start()
        # A QObject cannot receive its own destroyed signal through its C++
        # slot table after that table has been torn down. Use a Python-only
        # weak callback, which closes worker state without reviving the widget.
        import weakref
        reference = weakref.ref(self)
        def retire(*_):
            owner = reference()
            if owner is not None:CaptionScene.close(owner)
        self._retire_callback = retire
        page.destroyed.connect(retire, Qt.ConnectionType.DirectConnection)
        self.destroyed.connect(retire, Qt.ConnectionType.DirectConnection)

    def event(self, event):
        if event.type()==_FRAME_READY_EVENT:
            with self.lock:
                pending,self._delivery_pending=self._delivery_pending,None
                self._delivery_scheduled=False
            if pending is not None and not self.closed:self.accept(*pending)
            return True
        if event.type() == QEvent.Type.DeferredDelete:
            self.close()
        return super().event(event)

    def _notify_web_ready(self):
        with self.lock:
            if self.closed:
                return
            try:self.web_ready.emit()
            except RuntimeError:return

    def _motion_ready(self):
        with self.lock:
            if not self.closed:self.wake.set()

    def _adopt_idle_motion(self,rasterizer):
        if self.closed or self._short_active:return
        values=self._motion_preheater.take(self._motion_warm_epoch,None)
        for key,value in values:rasterizer.insert_raster(key,value)
        if values:
            with self.lock:
                if self.closed:return
                self._glyph_ready_keys=frozenset(rasterizer.rasters)
                try:self.warm_ready.emit()
                except RuntimeError:return

    def _notify_ready(self, token, pixels, trace):
        # close()/DeferredDelete and worker emission share one short gate.
        # It never covers rasterization, storage I/O, or waiting for a worker.
        with self.lock:
            if self.closed:
                return False
            try:
                # Observers still see worker readiness; widgets consume one
                # guarded, coalesced GUI event instead of a second signal slot.
                self.ready.emit(token,pixels,trace)
                if self.closed:return False
                if token!=self.token:
                    if trace.get('request_kind')=='current':self.schedule_counts['stale_at_gui']+=1
                    return True
                pending=self._delivery_pending
                if pending is not None and float(pending[2].get('sample_ms',0))>float(trace.get('sample_ms',0)):
                    return True
                self._delivery_pending=(token,pixels,trace)
                if not self._delivery_scheduled:
                    self._delivery_scheduled=True
                    QCoreApplication.postEvent(self,_FrameReadyEvent(),Qt.HighEventPriority.value)
            except RuntimeError:
                return False
            return not self.closed

    def refresh_web(self):
        if self.closed or self.page.project is not self.project:
            return
        self.last_request = None
        self.page._present_caption_scene()

    def present(self, cues, milliseconds):
        page = self.page
        self._media_ms=float(milliseconds)
        speed=max(1.,float(getattr(page.video,'_playback_rate',1.) or 1.))
        self._short_active=not bool(getattr(page.video,'_paused',True)) and any((c.end_ms-c.start_ms)/speed<=140 for c in cues)
        if self.closed or page.project is not self.project:
            return False
        panel=getattr(page,'caption_transform_panel',None)
        if panel is not None:panel.refresh_gesture_targets(cues)
        raster_only = getattr(getattr(page.video, 'controller', None), 'supports_native_subtitles', True) is False
        audio_tail = getattr(page, '_audio_tail_visual_active', lambda:False)()
        from ..timeline.studio_caption_timeline import independent_captions
        independent = independent_captions(page.project)
        from ..caption_style.word_animation import word_part
        timed = any(word_part(page.project.effects.get(c.effect_id, {})) for c in cues)
        if not self.active and len(cues) < 2 and not raster_only and not audio_tail and not independent and not timed and not getattr(page,'_caption_transform_preview',{}):
            return False
        if not self.active:
            self.active = True
            page._stop_web_live_preview('cue_set_owner')
            page._revoke_advanced_preview(reason='cue_set_owner')
            page.video.clear_caption_boundaries()
        revision = page._revision_store.render
        rect = page.position_overlay._content_rect().toRect()
        if rect.isEmpty():
            return True
        generation = page.video.playback_position_snapshot().playback_generation
        token = self.scene_token(cues,rect,generation)
        token_changed = token != self.token
        warm_epoch = None if bool(getattr(page.video, '_paused', True)) else self.motion_epoch(token)
        if warm_epoch != self._motion_warm_epoch:
            self._motion_warm_epoch = warm_epoch
            self._motion_preheater.set_epoch(warm_epoch)
        if token_changed:
            previous, self.token = self.token, token
            self.published = None
            with self.lock:
                # Preheat is optional. Old visual revisions/viewport sizes can
                # never be published and must not queue behind an active edit.
                self.warm_pending = OrderedDict((key,value) for key,value in self.warm_pending.items()
                    if value[0][:3]==token[:3] and value[0][-4:]==token[-4:])
            # A chain of holds (a short cue whose raster was never shown) keeps
            # one deadline: the time the bitmap on screen first went stale.
            stale_since = self._hold[1] if self._hold is not None else None
            self._hold = None
            # In-flight uploads from the preceding active set are no longer valid.
            page.video._web_live_epoch += 1
            if previous is not None and self.shows_other_content(previous, token):
                with self.lock:
                    ready = self.frames.get(self.frame_key(token))
                if (ready is None and cues and self.continuous_handoff(previous, token)
                        and float(getattr(page.video,'_playback_rate',1.) or 1.)<=1.):
                    # 2026-10-12: ordinary playback reached the next cue set
                    # before its raster was ready. Withdrawing the old bitmap
                    # first showed an empty frame between back-to-back cues;
                    # the next raster replaces it in one overlay update. The
                    # hold is bounded: a late raster retires the old one.
                    now = time.perf_counter()
                    self._hold = (token, stale_since if stale_since is not None else now)
                    remaining = HOLD_PREVIOUS_MS - (now - self._hold[1]) * 1000.0
                    self._arm_hold_deadline(max(1, int(remaining)))
                    page._studio_trace('CAPTION_SCENE_HELD', previous_cue_ids=list(previous[4]),
                                       cue_ids=list(token[4]))
                elif ready is None:
                    self._hold_timer.stop()
                    # 2026-10-11: the published bitmap belongs to other cues or
                    # to the old video geometry. Leaving it up until the new
                    # raster is ready showed cue A over cue B's frame (review
                    # Up/Down, E/R). Withdraw it now; the new one follows.
                    page.video.remove_compositor_overlay(page.video.ADVANCED_OVERLAY_ID, force=True)
                    page._studio_trace('CAPTION_SCENE_RETIRED', previous_cue_ids=list(previous[4]),
                                       cue_ids=list(token[4]), geometry_changed=previous[-4:] != token[-4:])
                    self._cleared_token = token
        if self.failures.get(token, 0) > 1:
            page.video.set_native_subtitle_visible(not independent)
            return True
        page.video.set_native_subtitle_visible(False)
        if not cues:
            # A gap is presented on every tick. One withdrawal per active set
            # is the state change; repeating it flooded mpv's IPC queue and
            # the trace with ~126 overlay-remove commands per second.
            if self._cleared_token != token:
                self._cleared_token = token
                page.video.remove_compositor_overlay(page.video.ADVANCED_OVERLAY_ID, force=True)
            from .visual_runtime import VisualOwner
            page._visual_ownership.commit(VisualOwner.NONE, cue_id='')
            return True
        self._cleared_token = None
        prepared = self.scene_items(cues)
        from .caption_playback_cache import FailedCaption
        if any(item is None for _,item in prepared):
            # Model/style edits create a new render revision even when paused.
            # A lookup alone cannot start preparation for that revision.
            page._prepare_caption_window(milliseconds, prepare_pixels=False)
            # 2026-10-12 (night): a scene is drawn only once every caption in
            # it is prepared, including a bilingual cue's translation. A frame
            # drawn without the translation was cached under the same scene key
            # and reused: 34 of 50 frames of a 24 min Japanese episode showed no
            # Chinese line. The cache's ready signal presents the scene again.
            self.last_request = None
            return True
        complete = tuple(p.error if isinstance(p,FailedCaption) else p.snapshot_hash if p else None for _, p in prepared)
        animated = any(animated_caption(p) for _,p in prepared)
        # Per-cue pixel bounds are used by paused selection handles. During
        # animation playback they do not affect the composed image or its
        # overall upload bounds, so defer their full-image scans until pause.
        measure_geometry = not animated or bool(getattr(page.video, '_paused', True))
        request_key = (token, complete, milliseconds if animated else None, measure_geometry)
        if request_key == self.last_request:
            # Keep the next boundaries warm while one long cue stays on screen.
            if time.perf_counter() - self._last_preheat >= PREHEAT_INTERVAL_S:
                width, height = token[6][:2]
                self.preheat(milliseconds, rect, generation, width, height)
            return True
        self.last_request = request_key
        width,height=token[6][:2]
        with self.lock:
            if animated and not measure_geometry:
                cached=self.frames.get(self.animation_key(token,prepared,milliseconds))
            else:cached=self.frames.get(self.frame_key(token)) if not animated else None
            reserved=getattr(self,'_seek_reserved_frame',None)
            if not animated and reserved is not None and reserved[0]==self.frame_key(token):
                cached=reserved[1];self._seek_reserved_frame=None
            if cached is not None:
                self.cache_counts['memory_hits'] += 1
                cache_key = self.animation_key(token,prepared,milliseconds) if animated else self.frame_key(token)
                if cache_key in self.frames:self.frames.move_to_end(cache_key)
            if cached is None:
                self.cache_counts['memory_misses'] += 1
                if self.pending is not None:self.schedule_counts['replaced']+=1
                self.pending = (token, prepared, milliseconds, width, height, measure_geometry, time.perf_counter())
                self.wake.set()
        if cached is not None:self.accept(token,cached[0],dict(cached[1],sample_ms=float(milliseconds),cache_hit=True,
            ready_at=time.perf_counter(),queue_wait_ms=0,raster_ms=0,pixel_pack_ms=0))
        # Animated request times change every frame; the look-ahead boundaries
        # do not. Refresh at a bounded cadence, but never delay the first
        # preheat after a cue, seek, revision or geometry change.
        if token_changed or time.perf_counter() - self._last_preheat >= PREHEAT_INTERVAL_S:
            self.preheat(milliseconds,rect,generation,width,height)
        return True

    def pixel_size(self,rect):
        width=max(1,round(rect.width()*self.page.video.devicePixelRatioF()))
        height=max(1,round(rect.height()*self.page.video.devicePixelRatioF()))
        factor=min(1.,(1_200_000/(width*height))**.5)
        return max(1,round(width*factor)),max(1,round(height*factor))

    @staticmethod
    def motion_epoch(token):
        return tuple(token[:4]) + tuple(token[6][:2])

    def warm_current(self):
        if self.closed or self.page.project is not self.project:return
        rect=self.page.position_overlay._content_rect().toRect()
        if not rect.isEmpty():
            self.preheat(self.page._caption_sample_ms(),rect,
                self.page.video.playback_position_snapshot().playback_generation,*self.pixel_size(rect))

    @staticmethod
    def frame_key(token):
        """Raster identity: a static scene does not depend on the playback generation."""
        if isinstance(token[5], tuple) and token[5] and token[5][0] == 'content-v1':
            # Publication still checks the full revision/generation token.
            # Pixels depend on these captions only, not another cue's edit.
            geometry = token[6:7] if len(token)>10 and token[6][2] else token[6:]
            return (token[0], token[4], token[5], *geometry)
        if len(token)>10 and token[6][2]:
            return token[:3]+token[4:-4]
        return token[:3] + token[4:]

    @staticmethod
    def shows_other_content(previous, token):
        """The published raster would show other cues, or sit at the old geometry."""
        return previous[4] != token[4] or tuple(previous[-4:]) != tuple(token[-4:])

    def animation_key(self,token,prepared,milliseconds):
        from ..timeline.caption_frame_time import project_frame_rate
        rate=project_frame_rate(self.project)
        frame=round(float(milliseconds)*float(rate)/1000) if rate is not None else float(milliseconds)
        return (self.frame_key(token),tuple(getattr(p,'snapshot_hash',None) for _,p in prepared),
                'animation',token[1],frame)

    def continuous_handoff(self, previous, token):
        """Playback advanced into the next cue set: same project, revisions,
        clock generation (no seek/navigation) and video geometry."""
        video = self.page.video
        return (not bool(getattr(video, '_paused', True))
                and tuple(previous[:4]) == tuple(token[:4])
                and tuple(previous[-4:]) == tuple(token[-4:]))

    def _arm_hold_deadline(self, milliseconds=HOLD_PREVIOUS_MS):
        self._hold_timer.start(int(milliseconds))

    def _hold_expired(self):
        hold, self._hold = self._hold, None
        if self.closed or hold is None or hold[0] != self.token or self.published is not None:
            return
        page = self.page
        page.video.remove_compositor_overlay(page.video.ADVANCED_OVERLAY_ID, force=True)
        page._studio_trace('CAPTION_SCENE_RETIRED', cue_ids=list(hold[0][4]), reason='hold_timeout',
                           held_ms=round((time.perf_counter() - hold[1]) * 1000, 1))

    def warm_times(self, times, *, include_motion=False):
        """Rasterise the scenes at ``times`` ahead of a jump there (review navigation)."""
        if self.closed or self.page.project is not self.project:
            return
        rect = self.page.position_overlay._content_rect().toRect()
        if rect.isEmpty():
            return
        generation = self.page.video.playback_position_snapshot().playback_generation
        width, height = self.pixel_size(rect)
        waiting = []
        for at in times:
            cues = active_cues(self.page, int(at))
            if not cues:
                continue
            token = self.scene_token(cues, rect, generation)
            width,height=token[6][:2]
            with self.lock:
                if self.frame_key(token) in self.frames or token in self.warm_pending:
                    continue
            prepared = self.scene_items(cues)
            if any(p is None for _, p in prepared):
                waiting.append(int(at))  # retried when the caption cache is ready
                continue
            if any(animated_caption(p) for _, p in prepared) and not include_motion:
                continue
            with self.lock:
                self.warm_pending[token] = (token, prepared, int(at), width, height, True)
                self._limit_warm_pending()
                self.wake.set()
        self.wanted_times = waiting[-6:]

    def _limit_warm_pending(self):
        # A seek near the end must not spend its preheat budget at the start.
        priority=getattr(self,'_priority_warm_time',None)
        target=self._media_ms if priority is None else priority
        self.warm_pending=OrderedDict(sorted(self.warm_pending.items(),key=lambda row:abs(row[1][2]-target)))
        while len(self.warm_pending)>32:self.warm_pending.popitem(last=True)

    def scene_items(self, cues):
        """Prepared captions of one scene: every cue, then (bilingual display)
        the translation companion of every translated cue. ``None`` marks a
        caption that is not prepared yet; such a scene is not drawn or cached."""
        items = [(cue.id, self.prepare(cue)) for cue in cues]
        page = self.page
        from ..caption_style.bilingual_layout import companion_id, settings_from_state, translations_of
        if settings_from_state(page.project.studio_state).mode == "bilingual":
            translated = translations_of(page.project.generation_metadata)
            cache = getattr(page, '_caption_playback_cache', None)
            for cue in cues:
                if not str(translated.get(cue.id, '') or '').strip():
                    continue
                from ..caption_style.bilingual_layout import theme_owns_translation
                if theme_owns_translation(page.project.style_recipes, cue):
                    continue
                key = companion_id(cue.id)
                prepared = page._prepared_caption(key)
                if prepared is None and cache is not None:
                    prepared = cache.failure(page._revision_store.render, key, *page._advanced_preview_size())
                items.append((key, prepared))
        preview=getattr(page,'_caption_transform_preview',{})
        return tuple((key,replace(prepared,interaction_transform=preview[key])
                      if key in preview and prepared is not None and hasattr(prepared,'snapshot') else prepared)
                     for key,prepared in items)

    def scene_token(self,cues,rect,generation):
        page=self.page;revision=page._revision_store.render
        items = self.scene_items(cues)
        dependencies = ('content-v1', tuple((key, getattr(p,'snapshot_hash',None),
            getattr(p,'font_signature',()), repr(getattr(p,'interaction_transform',None))) for key,p in items))
        return (id(self.project),revision.mapping_revision,revision.visual_revision,generation,tuple(c.id for c in cues),
                dependencies,scene_raster_geometry(page,rect,items),*rect.getRect())

    def preheat(self,milliseconds,rect,generation,width,height):
        """Prepare upcoming static active sets before their first visible tick."""
        if getattr(self.page.video,'_paused',True) or getattr(self,'_audit_preheat_mode','normal')=='off':
            return
        from bisect import bisect_right
        self._last_preheat=time.perf_counter()
        runtime=self.page.session.runtime
        if runtime is None:return
        following=bisect_right(runtime._cue_starts,int(milliseconds))
        upcoming=[runtime.cue_by_id[key] for key in runtime._cue_order[following:following+12]]
        # The window is media time: at 4x one wall second covers four media
        # seconds, so a fixed 1000 ms window left 250 ms of real time to draw
        # the next set. Always include the next boundaries, however far.
        rate=max(1.,float(getattr(self.page.video,'_playback_rate',1.) or 1.))
        ahead=max(1000.,PREHEAT_AHEAD_WALL_S*1000.*rate)
        future=sorted({t for cue in [*runtime.cues_at(milliseconds),*upcoming]
                       for t in (cue.start_ms,cue.end_ms) if t>milliseconds})
        boundaries=[t for index,t in enumerate(future)
                    if index<PREHEAT_MIN_BOUNDARIES or t<=milliseconds+ahead][:PREHEAT_MAX_BOUNDARIES]
        motion_items=[];motion_keys=set()
        current_ids = {cue.id for cue in active_cues(self.page, milliseconds)}
        from ..caption_style.bilingual_layout import companion_id
        current_ids.update(companion_id(key) for key in tuple(current_ids))
        from .caption_motion_preheater import motion_raster_key
        for at in boundaries:
            cues=active_cues(self.page,at)
            if not cues:continue
            token=self.scene_token(cues,rect,generation)
            width,height=token[6][:2]
            with self.lock:
                if self.frame_key(token) in self.frames or token in self.warm_pending:continue
            prepared=self.scene_items(cues)
            if any(p is None for _,p in prepared):continue
            for _,p in prepared:
                if getattr(p, 'web', None):
                    self.web_cache.prefetch((p.snapshot_hash,generation,width,height),p.web,
                        max(0,at-p.snapshot.start_ms),at,width,height)
            if any(animated_caption(p) for _,p in prepared):
                for cue_id,p in prepared:
                    key=motion_raster_key(p,width,height)
                    if cue_id not in current_ids and key is not None and key not in motion_keys:
                        motion_items.append((key,p,at,width,height));motion_keys.add(key)
                # A 400ms cue has only 100ms at 4x. Prepare its actual media
                # frames ahead of the boundary, including transparent phases;
                # playback never reuses one sample for the whole animation.
                short=any((cue.end_ms-cue.start_ms)/rate<=140 for cue in cues)
                keys=[motion_raster_key(p,width,height) for _,p in prepared]
                raw=callable(getattr(getattr(self.page.video,'controller',None),'post_raw_overlay',None))
                if short and raw and all(key is not None and key in self._glyph_ready_keys for key in keys):
                    from ..timeline.caption_frame_time import project_frame_rate
                    fps=project_frame_rate(self.project)
                    if fps is not None:
                        fps=float(fps);end=min(c.end_ms for c in cues)
                        first=math.ceil(at*fps/1000-1e-7);last=math.ceil(end*fps/1000-1e-7)
                        for frame in range(first,min(last,first+32)):
                            sample=frame*1000/fps
                            key=self.animation_key(token,prepared,sample)
                            with self.lock:
                                if key in self.frames or key in self.warm_pending:continue
                                self.warm_pending[key]=(token,prepared,sample,width,height,False,time.perf_counter(),'short-frame')
                                self._limit_warm_pending()
                                self.wake.set()
                continue
            with self.lock:
                self.warm_pending[token]=(token,prepared,at,width,height,True,time.perf_counter())
                self._limit_warm_pending()
                self.wake.set()
        if motion_items and getattr(self,'_audit_preheat_mode','normal')!='motion-off':
            from .caption_motion_preheater import MAX_ITEMS
            short=[cue for cue in [*runtime.cues_at(milliseconds),*upcoming]
                        if cue.end_ms>milliseconds and (cue.end_ms-cue.start_ms)/rate<=220
                        and (cue.start_ms-milliseconds)/rate<=500]
            protected_end=max(c.end_ms for c in short) if short else None
            protect=(protected_end,max(0,(protected_end-milliseconds)/rate/1000)) if short else None
            limit=MAX_ITEMS if rate>1 else 2
            self._motion_preheater.request(self.motion_epoch(self.token or token),motion_items[:limit],
                                          current_ms=milliseconds,protect=protect)

    def prepare(self,cue):
        page=self.page;prepared=page._prepared_caption(cue.id)
        if prepared is None:
            cache=getattr(page,'_caption_playback_cache',None)
            return cache.failure(page._revision_store.render,cue.id,*page._advanced_preview_size()) if cache else None
        snapshot=prepared.snapshot
        text=getattr(page,'_live_edit_text_overrides',{}).get(cue.id,snapshot.text)
        changes=getattr(page,'_live_transform_overrides',{}).get(cue.id,{})
        timing=(cue.start_ms,cue.end_ms)!=(snapshot.start_ms,snapshot.end_ms)
        if text==snapshot.text and not changes and not timing:return prepared
        recipe=copy.deepcopy(snapshot.style_recipe);values=dict(text=text,start_ms=cue.start_ms,end_ms=cue.end_ms,style_recipe=recipe)
        for field,target in (('position_x','positionX'),('position_y','positionY')):
            if field in changes:
                values[field]=float(changes[field]);recipe.setdefault('layout',{})[target]=values[field]
        if 'font_size' in changes:
            values['font_size']=float(changes['font_size']);recipe.setdefault('typography',{})['fontSize']=values['font_size']
        snapshot=replace(snapshot,**values)
        web=prepared.web
        if web:
            placement=dict(web.placement)
            for field,target,size in (('position_x','x',page.project.render_settings.get('play_res_x',1920)),
                                      ('position_y','y',page.project.render_settings.get('play_res_y',1080))):
                if field in changes:placement[target]=float(changes[field])/max(1,size)
            web=replace(web,text=text,duration=max(.05,(cue.end_ms-cue.start_ms)/1000),placement=placement)
        return replace(prepared,snapshot=snapshot,snapshot_hash=snapshot.stable_hash(),web=web)

    def work(self):
        from .caption_pixel_cache import prepared_pixels
        from .caption_disk_cache import CaptionDiskCache
        disk = CaptionDiskCache()
        rasterizer = SceneRasterizer(self.web_cache)
        try:
            while True:
                self.wake.wait()
                with self.lock:
                    if self.closed: return
                    task, self.pending = self.pending, None
                    current_task = task is not None
                    if task is None and self.warm_pending:_,task=self.warm_pending.popitem(last=False)
                    if not self.warm_pending:self.wake.clear()
                if not current_task:self._adopt_idle_motion(rasterizer)
                if task is None: continue
                token, cues, milliseconds, width, height, measure_geometry, *queued = task
                short_warm=len(queued)>1 and queued[1]=='short-frame'
                started = time.perf_counter()
                if self.token is not None and (tuple(token[:4])!=tuple(self.token[:4]) or tuple(token[-4:])!=tuple(self.token[-4:])):
                    self.schedule_counts['stale_before_raster']+=1
                    continue
                try:
                    if current_task and self._motion_preheater.has_ready(self.motion_epoch(token)):
                        from .caption_motion_preheater import motion_raster_key
                        keys = [motion_raster_key(p,width,height) for _,p in cues]
                        rate=max(1.,float(getattr(self.page.video,'_playback_rate',1.) or 1.))
                        short=any(p is not None and hasattr(p,'snapshot') and
                                  (p.snapshot.end_ms-p.snapshot.start_ms)/rate<=220 for _,p in cues)
                        # Adopt ready future glyphs while a long cue is on
                        # screen. LRU retirement must not land in the 100ms
                        # wall window of a 400ms cue played at 4x.
                        for key,value in self._motion_preheater.take(self.motion_epoch(token), keys if short else None):
                            rasterizer.insert_raster(key, value)
                    raster_started=time.perf_counter()
                    static = (isinstance(token[5],tuple) and token[5] and token[5][0]=='content-v1'
                              and all(p is not None and getattr(p,'web',None) is None
                                      and not animated_caption(p) for _,p in cues))
                    disk_key = disk.key((self.frame_key(token)[1:], width, height)) if static else None
                    cached = disk.get(disk_key) if disk_key else None
                    if cached is not None:
                        image, rows = cached
                    else:
                        image, rows = rasterizer.frame(cues, milliseconds, width, height, generation=token[3],
                            retire_web=current_task, measure_cue_geometry=measure_geometry)
                    raster_finished=time.perf_counter()
                    if any(row['status']=='pending' for row in rows):
                        # A configured HTML page is not yet a rendered frame.
                        # Keep the last complete foreground until WebSceneCache
                        # wakes us with both language layers; never publish a
                        # transparent/half-built replacement as "ready".
                        continue
                    with self.lock:
                        if self.closed:
                            return
                    if short_warm:pixels=prepared_pixels(image,None,started,self._raw_folder,compact_image=True)
                    else:pixels = prepared_pixels(image, None, started, self._raw_folder)
                except Exception as exc:
                    # A transient raster/upload failure gets one retry, then
                    # yields native ownership for this revision instead of
                    # leaving a dead worker holding a permanently blank layer.
                    if not self._notify_ready(token, None, dict(error=f'{type(exc).__name__}: {exc}')):
                        return
                    continue
                ready_at=time.perf_counter()
                trace = dict(expected_cue_ids=[key for key, _ in cues], cue_pixels=rows, geometry_complete=measure_geometry,
                             disk_cache_hit=cached is not None,
                             animated=any(animated_caption(p) for _,p in cues),
                             request_kind='current' if current_task else 'preheat',
                             queue_wait_ms=(started-queued[0])*1000 if queued else 0,
                             adopt_ms=(raster_started-started)*1000,
                             raster_ms=(raster_finished-raster_started)*1000,
                             pixel_pack_ms=(ready_at-raster_finished)*1000, ready_at=ready_at,
                             packing=getattr(pixels,'timings',None),
                             sample_ms=float(milliseconds), duration_ms=(time.perf_counter()-started)*1000)
                with self.lock:
                    if self.closed:
                        # Dropping the unadopted PreparedPixels releases its
                        # file lease; an IPC-owned earlier frame keeps its own
                        # reference until ACK and is unaffected.
                        return
                    self._glyph_ready_keys=frozenset(rasterizer.rasters)
                    if not current_task:
                        self.warm_completed[self.frame_key(token)] = (float(milliseconds),time.perf_counter())
                        while len(self.warm_completed)>512:self.warm_completed.popitem(last=False)
                    if all(row['status']!='pending' for row in rows) and (short_warm or not any(animated_caption(p) for _,p in cues)):
                        key=self.animation_key(token,cues,milliseconds) if short_warm else self.frame_key(token)
                        self.frames[key]=(pixels,trace)
                        self.frames.move_to_end(key)
                        while self.frames and (len(self.frames)>256 or sum(v[0].image.sizeInBytes() for v in self.frames.values())>FRAME_CACHE_BYTES):
                            self.frames.popitem(last=False)
                            self.cache_counts['evictions'] += 1
                # Range warm-up may render an animated cue to prepare glyphs.
                # Its sampled time is not the current presentation time.
                if short_warm or (not current_task and trace['animated']):continue
                if not self._notify_ready(token, pixels, trace):
                    return
                # Current pixels are submitted before optional compression/I/O.
                if disk_key and cached is None and not self.closed and all(row['status']=='rendered' for row in rows):
                    with self.lock:
                        foreground_waiting = self.pending is not None
                    if not foreground_waiting:
                        disk.put(disk_key, image, rows)
                self.disk_stats = disk.stats()
        finally:
            rasterizer.close()

    def accept(self, token, pixels, trace):
        page = self.page
        if not self.still_current(token):
            self.schedule_counts['stale_at_gui']+=1
            return
        if pixels is None:
            count = self.failures.get(token, 0) + 1
            self.failures[token] = count
            if len(self.failures) > 32:
                self.failures.pop(next(iter(self.failures)))
            page._studio_trace('CAPTION_SCENE_RECOVERY', error=trace['error'], attempt=count)
            if count <= 1:
                self.last_request = None
                page._present_caption_scene()
            else:
                page.video.remove_compositor_overlay(page.video.ADVANCED_OVERLAY_ID, force=True)
                from ..timeline.studio_caption_timeline import independent_captions
                page.video.set_native_subtitle_visible(not independent_captions(page.project))
                bind_text(page.save_state, '字幕合成暂不可用 · 特效字幕等待恢复')
            return
        if (trace.get('animated') and not getattr(page.video,'_paused',True)
                and getattr(self,'_last_published_token',None)==token
                and trace.get('sample_ms',0)<getattr(self,'_last_published_sample_ms',-1)):
            self.schedule_counts['stale_at_gui']+=1
            return
        gui_received=time.perf_counter()
        current_media_ms=page._caption_sample_ms()
        cues = active_cues(page, current_media_ms)
        if tuple(c.id for c in cues) != token[4]:
            return
        context = dict(caller='CaptionScene', cue_id='scene:'+hashlib.sha1('|'.join(token[4]).encode()).hexdigest()[:16],
                       expected_cue_ids=list(token[4]), scene_token=token,sample_ms=trace.get('sample_ms'))
        accepted = page.video.publish_compositor_overlay(page.video.ADVANCED_OVERLAY_ID,
            pixels.image, QRect(*token[-4:]), prepared_pixels=pixels, context=context)
        trace=dict(trace,gui_delivery_ms=(gui_received-trace['ready_at'])*1000 if 'ready_at' in trace else 0,
                   submit_ms=(time.perf_counter()-gui_received)*1000,
                   media_age_ms=float(current_media_ms)-float(trace.get('sample_ms',current_media_ms)),
                   schedule_counts=dict(self.schedule_counts))
        self.published = pixels if accepted else None
        hold = self._hold
        if hold is not None and hold[0] == token:
            self._hold = None
            self._hold_timer.stop()
            trace = dict(trace, held_previous_ms=round((time.perf_counter() - hold[1]) * 1000, 1))
        from .visual_runtime import VisualOwner
        page._visual_ownership.commit(VisualOwner.ADVANCED_LIVE if accepted else VisualOwner.NONE,
                                     cue_id=context['cue_id'] if accepted else '')
        self.metrics.append({**trace, 'posted': accepted})
        self.last_result_token = token
        if accepted:
            self._last_published_token=token
            self._last_published_sample_ms=trace.get('sample_ms',0)
        geometry=getattr(page,'_selection_geometry',None)
        selected=getattr(page,'_cue_lookup',{}).get(getattr(page,'selected_cue_id',''))
        if geometry is not None and selected is not None:
            geometry.sync(selected,page.project.style_recipes.get(selected.style_id,{}))
        failed = [row for row in trace['cue_pixels'] if row['status'] in ('failed', 'fallback')]
        if failed:
            bind_text(page.save_state, '{value0} 条字幕主题异常 · 使用基础预览', value0=len(failed))
            by_id=page.session.runtime.cue_by_id
            bind_text(page.save_state, '\n'.join((f"轨道 {getattr(by_id.get(row['cue_id']), 'speaker_id', '?')} · {row['cue_id']}：{row['error']}" for row in failed)), property='toolTip')
        elif '使用基础预览' in page.save_state.text():
            (bind_text(page.save_state, '已保存') if page.undo_stack.isClean() else bind_text(page.save_state, '未保存'))
            page.save_state.setToolTip('')
        del self.metrics[:-128]
        previous = getattr(self, '_last_trace', None)
        now=time.perf_counter()
        if previous is None or previous[0] != token or now-previous[2]>=.25:
            self._last_trace = (token, trace['sample_ms'],now)
            page._studio_trace('CAPTION_SCENE', **trace, posted=accepted)
        if getattr(page.video, '_paused', True) and not trace.get('geometry_complete', True):
            # A frame requested just before pause may arrive after the pause
            # event. Request paused geometry from the current media time, not
            # from the stale in-flight playback frame.
            self.last_request = None
            page._present_caption_scene()

    def still_current(self, token):
        """Python-only guard also checked by the asynchronous mpv uploader."""
        if self.closed or self.page.project is not self.project or token != self.token:
            return False
        revision = self.page._revision_store.render
        return (revision.mapping_revision == token[1] and revision.visual_revision == token[2]
                and self.page.video._playback_clock.generation == token[3])

    def trace(self):
        current = self.metrics[-1] if self.metrics and getattr(self, 'last_result_token', None)==self.token else {}
        rows = current.get('cue_pixels', [])
        return dict(expected_cue_ids=list(self.token[4]) if self.token else [],
                    expected_display_cue_ids=current.get('expected_cue_ids',list(self.token[4]) if self.token else []),
                    rendered_cue_ids=[r['cue_id'] for r in rows if r['status']=='rendered'],
                    cue_pixels=rows,
                    visible=self.published is not None and bool(self.published.raw_geometry['alpha_nonzero']),
                    owner='caption_scene', memory_cache=dict(getattr(self,'cache_counts',{})),
                    disk_cache=dict(getattr(self,'disk_stats',{})))

    def close(self, *_):
        self._motion_preheater.close()
        with self.lock:
            self.closed = True
            self.active = False
            self._hold = None
            self.pending = None
            self._delivery_pending=None
            self.warm_pending.clear();self.frames.clear()
            self.warm_completed.clear()
            self._seek_reserved_frame=None
            self.published = None
            # Every guard checks `closed` first; dropping the project lets a
            # closed scene stop pinning the whole previous project in memory.
            self.project = None
            self.last_request = None
            self.wake.set()
        try:
            self._hold_timer.stop()
        except RuntimeError:
            pass
        self.web_cache.close()
