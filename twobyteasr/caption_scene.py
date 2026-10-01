"""Render the visible cue set into one atomic foreground raster.

Track order determines compositing only. Each authored cue keeps its own
placement, scale, theme and cue-local animation time.
"""
from collections import OrderedDict
from dataclasses import replace
import copy
import hashlib
import threading
import time

from PySide6.QtCore import QObject, Signal, QRect, Qt
from PySide6.QtGui import QImage, QPainter

from .i18n import bind_text

from .i18n import tr


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

    def get(self, key, web, cue_ms, stage_ms, width, height):
        with self.condition:
            cached = self.images.get(key)
            if key not in self.inflight and key not in self.errors and (cached is None or cached[1] != cue_ms):
                self.pending[key] = (web, cue_ms, stage_ms, width, height)
                if len(self.workers) < min(3, len(self.pending) + len(self.inflight)):
                    thread = threading.Thread(target=self.work, name='caption-scene-web', daemon=True)
                    self.workers.append(thread); thread.start()
                self.condition.notify()
            return cached[0] if cached else None, self.errors.get(key)

    def work(self):
        service = loaded = None
        from .renderer_service import GLOBAL_RENDERER_SERVICE, LiveRendererSession
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.closed or self.pending)
                    if self.closed: return
                    key, (web, cue, stage, width, height) = self.pending.popitem(last=False)
                    self.inflight.add(key)
                try:
                    if service is None: service = LiveRendererSession(GLOBAL_RENDERER_SERVICE)
                    page_key = (web.theme_key, width, height)
                    if page_key != loaded:
                        service.live_set(web.html, width=width, height=height); loaded = page_key
                    service.live_text(text=web.text, speaker=web.speaker, duration_ms=web.duration*1000, placement=web.placement)
                    image = QImage.fromData(service.live_frame(cue_ms=cue, stage_ms=stage))
                    if image.isNull(): raise ValueError('empty HTML raster')
                    with self.condition:
                        if self.closed: return
                        self.images[key] = (image, cue)
                        self.images.move_to_end(key)
                        while len(self.images)>1 and sum(v[0].sizeInBytes() for v in self.images.values())>48*1024*1024:
                            self.images.popitem(last=False)
                except Exception as exc:
                    loaded = None
                    with self.condition: self.errors[key] = f'{type(exc).__name__}: {exc}'
                    # Discard the failed lease. The next cue gets a fresh page;
                    # the failed key remains quarantined (no per-frame retries).
                    if service is not None:
                        try: service.close()
                        except Exception: pass
                    service = None
                finally:
                    with self.condition: self.inflight.discard(key)
                if not self.closed: self.changed()
        finally:
            if service is not None:
                try: service.close()
                except Exception: pass

    def close(self):
        with self.condition:
            self.closed = True
            self.pending.clear(); self.images.clear(); self.errors.clear()
            self.condition.notify_all()


class SceneRasterizer:
    """Worker-owned rasters and browser leases; a bad cue never aborts peers."""
    def __init__(self, web_cache=None):
        self.rasters = OrderedDict()
        self.pages = OrderedDict()
        self.web_cache = web_cache

    def frame(self, prepared_cues, milliseconds, width, height, generation=0):
        from .advanced_live_renderer import (render_live_snapshot, render_live_layers,
            composite_live_scene_layers, composition_pivot_for_snapshot)
        from .studio_live_canvas import compiled_scene_for_snapshot
        from .subtitle_stacking import StackLayout, compute_stack_layout
        output = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        output.fill(Qt.transparent)
        painter = QPainter(output)
        evidence = []
        # 2026-09-19：抢话字幕自动分层（LIVE 链）。按显示中的 cue 集合计算
        # 与 native ASS 一致的向上偏移；偏移是显示布局，只 replace 进本帧
        # snapshot，不写回样式。确定性：同一 cue 集合任何时刻结果一致。
        from .caption_playback_cache import FailedCaption as _FailedCaption
        prepared_cues = tuple((key, p.fallback if isinstance(p, _FailedCaption) and p.fallback else p)
                             for key, p in prepared_cues)

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
                painter.drawImage(output.rect(), image)
                import numpy as np
                packed = image.convertToFormat(QImage.Format_RGBA8888)
                alpha = np.ndarray((packed.height(), packed.width(), 4), dtype=np.uint8,
                    buffer=packed.constBits(), strides=(packed.bytesPerLine(), 4, 1))[:, :, 3]
                row.update(status='rendered', alpha_nonzero=int(np.count_nonzero(alpha)))
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
                    painter.drawImage(output.rect(), render_live_snapshot(basic, width=width, height=height))
                except Exception as fallback_error:
                    row.update(status='failed', fallback_error=str(fallback_error))
        painter.end()
        return output, evidence

    def native_frame(self, prepared, relative, width, height):
        from .advanced_live_renderer import (render_live_snapshot, render_live_layers,
            composite_live_scene_layers, composition_pivot_for_snapshot)
        from .studio_live_canvas import compiled_scene_for_snapshot
        snapshot = prepared.snapshot
        key = (prepared.snapshot_hash, width, height)
        cached = self.rasters.get(key)
        if cached is None:
            scene = compiled_scene_for_snapshot(snapshot)
            layers = render_live_layers(snapshot, width=width, height=height) if scene and scene.tracks else None
            image = render_live_snapshot(snapshot, width=width, height=height) if layers is None else None
            cached = (scene, layers, image)
            self.rasters[key] = cached
            def size(value):
                return sum(i.sizeInBytes() for i in value[1].values()) if value[1] else value[2].sizeInBytes()
            while len(self.rasters) > 1 and sum(size(v) for v in self.rasters.values()) > 64*1024*1024:
                self.rasters.popitem(last=False)
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
    if prepared.web:
        theme=snapshot.style_recipe.get('webTheme',{})
        return bool(theme.get('motionSpec',{}).get('tracks') or any(
            word in str(theme.get('cueCss',''))+str(theme.get('stageCss','')) for word in ('animation','@keyframes')))
    graph=snapshot.style_recipe.get('visualGraph') or {}
    return bool(snapshot.motion_recipe.get('mode','none')!='none' or graph.get('motionGraph',{}).get('tracks'))


class CaptionScene(QObject):
    ready = Signal(object, object, object)
    web_ready = Signal()

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.project = page.project
        self.active = False
        self.closed = False
        self.token = None
        self.pending = None
        self.warm_pending = OrderedDict()
        self.frames = OrderedDict()
        self.last_request = None
        self.published = None
        self.failures = {}
        self.metrics = []
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.ready.connect(self.accept)
        self.web_ready.connect(self.refresh_web)
        self.web_cache = WebSceneCache(self.web_ready.emit)
        self.thread = threading.Thread(target=self.work, name='caption-scene', daemon=True)
        self.thread.start()
        page.destroyed.connect(self.close)

    def refresh_web(self):
        if self.closed or self.page.project is not self.project:
            return
        self.last_request = None
        self.page._present_caption_scene()

    def present(self, cues, milliseconds):
        page = self.page
        if self.closed or page.project is not self.project:
            return False
        raster_only = getattr(getattr(page.video, 'controller', None), 'supports_native_subtitles', True) is False
        if not self.active and len(cues) < 2 and not raster_only:
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
        if token != self.token:
            self.token = token
            self.published = None
            # In-flight uploads from the preceding active set are no longer valid.
            page.video._web_live_epoch += 1
        if self.failures.get(token, 0) > 1:
            page.video.set_native_subtitle_visible(True)
            return True
        page.video.set_native_subtitle_visible(False)
        if not cues:
            page.video.remove_compositor_overlay(page.video.ADVANCED_OVERLAY_ID, force=True)
            return True
        prepared = tuple((cue.id, self.prepare(cue)) for cue in cues)
        from .caption_playback_cache import FailedCaption
        if any(item is None for _,item in prepared):
            # Model/style edits create a new render revision even when paused.
            # A lookup alone cannot start preparation for that revision.
            page._prepare_caption_window(milliseconds, prepare_pixels=False)
        complete = tuple(p.error if isinstance(p,FailedCaption) else p.snapshot_hash if p else None for _, p in prepared)
        animated = any(animated_caption(p) for _,p in prepared)
        request_key = (token, complete, milliseconds if animated else None)
        if request_key == self.last_request:
            return True
        self.last_request = request_key
        width,height=self.pixel_size(rect)
        with self.lock:
            cached=self.frames.get(token) if not animated else None
            if cached is None:
                self.pending = (token, prepared, milliseconds, width, height)
                self.wake.set()
        if cached is not None:self.accept(token,cached[0],dict(cached[1],sample_ms=float(milliseconds),cache_hit=True))
        self.preheat(milliseconds,rect,generation,width,height)
        return True

    def pixel_size(self,rect):
        width=max(1,round(rect.width()*self.page.video.devicePixelRatioF()))
        height=max(1,round(rect.height()*self.page.video.devicePixelRatioF()))
        factor=min(1.,(1_200_000/(width*height))**.5)
        return max(1,round(width*factor)),max(1,round(height*factor))

    def warm_current(self):
        if self.closed or self.page.project is not self.project:return
        rect=self.page.position_overlay._content_rect().toRect()
        if not rect.isEmpty():
            self.preheat(self.page._caption_sample_ms(),rect,
                self.page.video.playback_position_snapshot().playback_generation,*self.pixel_size(rect))

    def scene_token(self,cues,rect,generation):
        page=self.page;revision=page._revision_store.render
        return (id(self.project),revision.mapping_revision,revision.visual_revision,generation,tuple(c.id for c in cues),
                repr((getattr(page,'_live_edit_text_overrides',{}),getattr(page,'_live_transform_overrides',{}),
                      [(c.id,c.start_ms,c.end_ms,c.speaker_id) for c in cues])),*rect.getRect())

    def preheat(self,milliseconds,rect,generation,width,height):
        """Prepare upcoming static active sets before their first visible tick."""
        from bisect import bisect_right
        runtime=self.page.session.runtime
        if runtime is None:return
        following=bisect_right(runtime._cue_starts,int(milliseconds))
        upcoming=[runtime.cue_by_id[key] for key in runtime._cue_order[following:following+12]]
        boundaries=sorted({t for cue in [*runtime.cues_at(milliseconds),*upcoming]
                           for t in (cue.start_ms,cue.end_ms) if milliseconds<t<=milliseconds+1000})[:12]
        for at in boundaries:
            cues=active_cues(self.page,at)
            if not cues:continue
            token=self.scene_token(cues,rect,generation)
            with self.lock:
                if token in self.frames or token in self.warm_pending:continue
            prepared=tuple((c.id,self.prepare(c)) for c in cues)
            if any(p is None or animated_caption(p) for _,p in prepared):continue
            with self.lock:
                self.warm_pending[token]=(token,prepared,at,width,height)
                while len(self.warm_pending)>12:self.warm_pending.popitem(last=False)
                self.wake.set()

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
        rasterizer = SceneRasterizer(self.web_cache)
        try:
            while True:
                self.wake.wait()
                with self.lock:
                    if self.closed: return
                    task, self.pending = self.pending, None
                    if task is None and self.warm_pending:_,task=self.warm_pending.popitem(last=False)
                    if not self.warm_pending:self.wake.clear()
                if task is None: continue
                token, cues, milliseconds, width, height = task
                started = time.perf_counter()
                try:
                    image, rows = rasterizer.frame(cues, milliseconds, width, height, generation=token[3])
                    pixels = prepared_pixels(image, None, started, self.page.video._compositor_overlay_dir/'caption-scenes')
                except Exception as exc:
                    # A transient raster/upload failure gets one retry, then
                    # yields native ownership for this revision instead of
                    # leaving a dead worker holding a permanently blank layer.
                    self.ready.emit(token, None, dict(error=f'{type(exc).__name__}: {exc}'))
                    continue
                trace = dict(expected_cue_ids=[key for key, _ in cues], cue_pixels=rows,
                             sample_ms=float(milliseconds), duration_ms=(time.perf_counter()-started)*1000)
                if all(row['status']!='pending' for row in rows) and not any(animated_caption(p) for _,p in cues):
                    with self.lock:
                        self.frames[token]=(pixels,trace)
                        self.frames.move_to_end(token)
                        while len(self.frames)>1 and (len(self.frames)>32 or sum(v[0].image.sizeInBytes() for v in self.frames.values())>48*1024*1024):
                            self.frames.popitem(last=False)
                if not self.closed:
                    try: self.ready.emit(token, pixels, trace)
                    except RuntimeError: return
        finally:
            rasterizer.close()

    def accept(self, token, pixels, trace):
        page = self.page
        if not self.still_current(token):
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
                page.video.set_native_subtitle_visible(True)
                bind_text(page.save_state, '字幕合成暂不可用 · 特效字幕等待恢复')
            return
        cues = active_cues(page, page._caption_sample_ms())
        if tuple(c.id for c in cues) != token[4]:
            return
        context = dict(caller='CaptionScene', cue_id='scene:'+hashlib.sha1('|'.join(token[4]).encode()).hexdigest()[:16],
                       expected_cue_ids=list(token[4]), scene_token=token)
        accepted = page.video.publish_compositor_overlay(page.video.ADVANCED_OVERLAY_ID,
            pixels.image, QRect(*token[-4:]), prepared_pixels=pixels, context=context)
        self.published = pixels if accepted else None
        from .visual_runtime import VisualOwner
        page._visual_ownership.commit(VisualOwner.ADVANCED_LIVE if accepted else VisualOwner.NONE,
                                     cue_id=context['cue_id'] if accepted else '')
        self.metrics.append({**trace, 'posted': accepted})
        self.last_result_token = token
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
        if previous is None or previous[0] != token or abs(trace['sample_ms'] - previous[1]) >= 100:
            self._last_trace = (token, trace['sample_ms'])
            page._studio_trace('CAPTION_SCENE', **trace, posted=accepted)

    def still_current(self, token):
        """Python-only guard also checked by the asynchronous mpv uploader."""
        if self.closed or self.page.project is not self.project or token != self.token:
            return False
        revision = self.page._revision_store.render
        return (revision.mapping_revision == token[1] and revision.visual_revision == token[2]
                and self.page.video._playback_clock.generation == token[3])

    def trace(self):
        rows = self.metrics[-1]['cue_pixels'] if self.metrics and getattr(self, 'last_result_token', None)==self.token else []
        return dict(expected_cue_ids=list(self.token[4]) if self.token else [],
                    rendered_cue_ids=[r['cue_id'] for r in rows if r['status']=='rendered'],
                    cue_pixels=rows,
                    visible=self.published is not None and bool(self.published.raw_geometry['alpha_nonzero']),
                    owner='caption_scene')

    def close(self, *_):
        self.active = False
        self.web_cache.close()
        with self.lock:
            self.closed = True
            self.pending = None
            self.warm_pending.clear();self.frames.clear()
            self.published = None
            self.wake.set()
