"""Advanced LIVE preview pipeline: preview workers, prefetch, frame
publishing, fidelity gates, and subtitle renderer activation for
Subtitle Studio."""

from __future__ import annotations
from .playback_probe import measured
from .caption_frame_time import caption_sample_transaction

import copy
import os
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from PySide6.QtCore import (QObject, QRect, QSize, QTimer, Qt, Signal)
from PySide6.QtGui import (QImage, QPixmap)
from PySide6.QtWidgets import (QApplication)
from .advanced_live_renderer import (LIVE_RENDERER_VERSION, render_live_layers, render_live_snapshot)
from .live_layer_cache import GLOBAL_LIVE_LAYER_CACHE, live_layer_cache_key
from .advanced_preview import (AdvancedPreviewIdentity, AdvancedPreviewPhase)
from .resource_governor import (GLOBAL_RESOURCE_GOVERNOR, ResourceKind)
from .runtime_cache import GLOBAL_RUNTIME_CACHE
from .studio_edit_sequence import sequence_of
from .studio_live_canvas import (_canonical_fill_colors, _count_stroke_pixels, _pixmap_alpha_metrics)
from .studio_project import StudioCue
from .studio_sequence_mapper import source_to_timeline
from .style_recipe import (MOTION_MODE_NONE, motion_mode, recipe_payload_for_style, route_recipe)
from .visual_runtime import (VisualOwner, VisualRenderer, renderer_capability_gaps)
from .visual_snapshot import build_visual_cue_snapshot

from .i18n import bind_text

from .i18n import tr

class _LiveRenderBridge(QObject):
    """Deliver worker-rendered LIVE images to the GUI thread (queued)."""

    ready = Signal(str, QImage, object, object, int)


class _WebLiveBridge(QObject):
    """Live web preview signals hop from the pump thread to the GUI thread."""

    frame = Signal(object, float, float)
    configured = Signal(str)
    failed = Signal(str)
    exited = Signal()


class StudioAdvancedFlowMixin:
    """Feature-domain mixin; host class provides widgets and state."""

    def _present_caption_scene(self):
        if self.project is None or not self.isVisible() or getattr(self, '_empty_playback_state', False):
            return False
        from .caption_scene import CaptionScene, active_cues
        milliseconds = self._caption_sample_ms()
        cues = active_cues(self, milliseconds)
        scene = getattr(self, '_caption_scene', None)
        if scene is None:
            raster_only = getattr(getattr(self.video, 'controller', None), 'supports_native_subtitles', True) is False
            if len(cues) < 2 and not raster_only:
                return False
            scene = self._caption_scene = CaptionScene(self)
        return scene.present(cues, milliseconds)

    @measured('prepare_window')
    def _prepare_caption_window(self, milliseconds, *, prepare_pixels=True):
        store = getattr(self, '_revision_store', None)
        runtime = getattr(getattr(self, 'session', None), 'runtime', None)
        if store is None or runtime is None or not self.project:
            return
        from bisect import bisect_right
        from .caption_playback_cache import PlaybackCaptionCache
        cache = getattr(self, '_caption_playback_cache', None)
        if cache is None:
            cache = PlaybackCaptionCache(self)
            cache.ready.connect(self._caption_window_ready)
            cache.failed.connect(lambda error: self._studio_trace('CAPTION_PREPARE_FAILED', error=error))
            self._caption_playback_cache = cache
        current = [cue.id for cue in runtime.cues_at(milliseconds)]
        following = bisect_right(runtime._cue_starts, int(milliseconds))
        # At least two future cues per active speaker; no whole-project scan.
        count = max(2, 2*len(self.project.speakers))
        ids = tuple(dict.fromkeys((*current, *runtime._cue_order[following:following+count])))
        width,height = getattr(self,'_caption_tick_geometry',None) or self._advanced_preview_size()
        cache.prepare(store.render, ids, width, height)
        if prepare_pixels:self._prepare_caption_pixels(ids)

    def _caption_window_ready(self, key, cue_ids):
        store = getattr(self, '_revision_store', None)
        if store is None or getattr(self, '_close_requested', False): return
        from .caption_playback_cache import revision_key
        if key != revision_key(store.render, *self._advanced_preview_size()): return
        self._prepare_caption_pixels(cue_ids)
        scene=getattr(self,'_caption_scene',None)
        if scene is not None and scene.active:scene.warm_current()
        worker = getattr(self, '_web_live_worker', None)
        if worker is not None:
            for cue_id in cue_ids:
                prepared = self._prepared_caption(cue_id)
                if prepared is not None and prepared.web is not None:
                    worker.warm_prepared(prepared.web)
        cue = self._renderer_cue_at_playhead()
        if cue is not None and cue.id in cue_ids:
            self._activate_selected_advanced_if_needed(force=True)

    def _caption_pixel_target(self, prepared):
        content=self.position_overlay._content_rect()
        if prepared.web is not None:
            dpr=max(1.,float(self.video.devicePixelRatioF()))
            width,height=max(1,round(content.width()*dpr)),max(1,round(content.height()*dpr))
            factor=min(1.,(960*540/(width*height))**.5)
            return max(1,round(width*factor)),max(1,round(height*factor)),1.
        dpr=float(self.advanced_cue_overlay.devicePixelRatioF() or 1.)
        rect=content.toRect()
        width,height=(rect.width(),rect.height()) if not rect.isEmpty() else self._advanced_preview_size()
        factor=min(1.,(1_200_000/(width*height*max(1.,dpr)**2))**.5)
        return max(1,round(width*factor)),max(1,round(height*factor)),dpr

    def _caption_pixel_key(self, prepared):
        store=getattr(self,'_revision_store',None)
        revision=store.render if store is not None else None
        return (getattr(revision,'project_id',''),getattr(revision,'mapping_revision',0),
                getattr(revision,'visual_revision',0),prepared.pixel_content_key or prepared.snapshot_hash,*self._caption_pixel_target(prepared))

    def _prepare_caption_pixels(self, cue_ids):
        if getattr(getattr(self, '_caption_scene', None), 'active', False):
            self._present_caption_scene()
            return
        direct=(not getattr(self.video,'_paused',True) and getattr(self,'_playback_mode','source')=='source'
            and not getattr(self,'_subtitle_transform_interactive',False)
            and not getattr(self,'_live_edit_text_overrides',{})
            and not getattr(self,'_live_transform_overrides',{})
            and not getattr(self,'_multitrack_composition_active',False)
            and not getattr(getattr(self.video,'_playback_clock',None),'exact_seek_pending',False))
        revision=getattr(getattr(self,'_revision_store',None),'render',None)
        target=self.position_overlay._content_rect().toRect()
        token=(getattr(revision,'project_id',''),getattr(revision,'mapping_revision',0),getattr(revision,'visual_revision',0),
            *target.getRect(),tuple(sorted(getattr(self,'_subtitle_track_visibility',{}).items())))
        boundary=getattr(getattr(self.video,'controller',None),'_caption_boundary_publisher',None)
        if boundary is not None and boundary.token!=token:self.video.clear_caption_boundaries()
        if not direct:
            clear=getattr(self.video,'clear_caption_boundaries',None)
            if callable(clear):clear()
        prepared_cues=[self._prepared_caption(cue_id) for cue_id in cue_ids]
        prepared_cues=[item for item in prepared_cues if item is not None and item.route.engine=='remotion']
        if not prepared_cues:return
        cache=getattr(self,'_caption_pixel_cache',None)
        if cache is None:
            from .caption_pixel_cache import CaptionPixelCache
            cache=self._caption_pixel_cache=CaptionPixelCache(self,raw_folder=self.video._compositor_overlay_dir/'caption-prepared')
            cache.ready.connect(self._caption_pixels_ready)
            cache.failed.connect(lambda key,error:self._studio_trace('CAPTION_PIXELS_FAILED',key=str(key),error=error))
        for prepared in prepared_cues:
            key=self._caption_pixel_key(prepared)
            cache.request(key,prepared.snapshot,prepared.web,*self._caption_pixel_target(prepared))
            pixels=cache.get(key)
            snapshot=prepared.snapshot
            cue=self.session.runtime.cue_by_id.get(snapshot.cue_id)
            if (direct and pixels is not None and pixels.raw_path is not None and cue is not None
                    and self._subtitle_track_visibility.get(cue.speaker_id,True)
                    and cue.speaker_id not in getattr(self.timeline,'hidden_speakers',set())):
                self.video.register_caption_boundary(token,snapshot,pixels,target,getattr(revision,'frame_rate',None))

    def _caption_pixels_ready(self, key):
        if getattr(self,'_close_requested',False):return
        cue=self._renderer_cue_at_playhead()
        prepared=self._prepared_caption(cue.id) if cue is not None else None
        if prepared is not None and key==self._caption_pixel_key(prepared):
            self._activate_selected_advanced_if_needed(force=True)

    def _prepared_caption_pixels(self, snapshot):
        cache=getattr(self,'_caption_pixel_cache',None)
        prepared=self._prepared_caption(snapshot.cue_id)
        if cache is None or prepared is None or prepared.snapshot_hash!=self._caption_snapshot_hash(snapshot):return None
        return cache.get(self._caption_pixel_key(prepared))

    def _prepared_caption_snapshot(self, cue_id, width, height):
        store = getattr(self, '_revision_store', None)
        cache = getattr(self, '_caption_playback_cache', None)
        if store is None:
            # Lightweight controller fixtures without a canonical revision.
            return build_visual_cue_snapshot(self.project,cue_id,width=width,height=height,fps=30.)
        snapshot = cache.snapshot(store.render,cue_id,width,height) if cache is not None else None
        if snapshot is None:
            self._prepare_caption_window(int(self.timeline.playhead_ms))
        return snapshot

    def _prepared_caption(self, cue_id):
        cache = getattr(self, '_caption_playback_cache', None)
        store = getattr(self, '_revision_store', None)
        if cache is None or store is None: return None
        geometry=getattr(self,'_caption_tick_geometry',None) or self._advanced_preview_size()
        return cache.prepared(store.render,cue_id,*geometry)

    def _caption_is_advanced(self, cue, payload):
        prepared = self._prepared_caption(cue.id) if cue else None
        if prepared is not None: return prepared.route.engine == 'remotion'
        if not payload: return False
        if payload.get('webTheme') or payload.get('visualGraph') or payload.get('engine')=='remotion': return True
        return route_recipe(payload).engine=='remotion'

    def _caption_snapshot_hash(self, snapshot):
        prepared = self._prepared_caption(snapshot.cue_id)
        if prepared is not None and prepared.snapshot is snapshot: return prepared.snapshot_hash
        return snapshot.stable_hash()

    def _caption_binding_options(self, snapshot):
        prepared=self._prepared_caption(snapshot.cue_id)
        return {'known_snapshot_hash':prepared.snapshot_hash} if prepared is not None and prepared.snapshot is snapshot else {}

    # ------------------------------------------------------------------
    # Live web preview（十九轮：视频层真身实时渲染）
    # ------------------------------------------------------------------

    _WEB_LIVE_RETRY_SECONDS = 30.0
    _WEB_LIVE_FRESH_SECONDS = 2.5
    _WEB_LIVE_WATCHDOG_MS = 1500
    # 二十七轮：发布门周期（≈30fps）；冲洗定时器按门的剩余时间起表。
    _WEB_LIVE_GATE_SECONDS = 0.016

    @staticmethod
    def _web_live_preview_enabled() -> bool:
        from .live_web_preview import live_preview_enabled

        return live_preview_enabled()

    def _ensure_web_live_preview(self, cue, snapshot) -> bool:
        """Own the video layer for a web-theme cue with the live pump.

        Returns True when the worker is (being) configured; the caller must
        then skip the mirror/grid path entirely. Any failure trips a breaker
        for ~30s and the legacy mirror/fidelity path takes over unchanged.
        """
        if not self._web_live_preview_enabled():
            return False
        # 二十七轮修复：看门狗必须在一切早退**之前**就位——首次调度撞上媒体
        # 加载窗口（startup_state != READY）时 web 接管让位 fidelity，但看门狗
        # 尚未创建 → 暂停态没有任何后续 tick 会重排（用户打开工程播头正好在
        # 特效字幕上 = 永久 fidelity 镜像）。READY 后由看门狗 1.5s 内自然接管。
        self._ensure_web_live_watchdog()
        # 二十六轮：媒体未 READY 前不接管——恢复播头落在特效字幕上时，打开即
        # live_set 会把冷 bundle（重 CPU/IO）砸进挂载窗口（用户实测"整个视频
        # 层黑屏约两分钟才开始播放"）。让位走镜像路径；READY 后水平触发看门狗
        # 1.5s 内自然接管。
        if getattr(getattr(self, "video", None), "_startup_state", "READY") != "READY":
            return False
        theme = (
            snapshot.style_recipe.get("webTheme")
            if isinstance(snapshot.style_recipe, Mapping)
            else None
        )
        if not isinstance(theme, Mapping) or not theme:
            self._stop_web_live_preview("not_web")
            return False
        failed_at = float(getattr(self, "_web_live_failed_at", 0.0) or 0.0)
        if failed_at and time.monotonic() - failed_at < self._WEB_LIVE_RETRY_SECONDS:
            return False
        if failed_at:
            self._web_live_failed_at = 0.0
        duration_seconds = max(0.05, (cue.end_ms - cue.start_ms) / 1000.0)
        # Rasterize at the physical video viewport. A fixed 1280x720 page
        # wastes decode/copy bandwidth in a small pane and blurs a larger one.
        content = self.position_overlay._content_rect()
        dpr = max(1., float(self.video.devicePixelRatioF()))
        viewport = (max(1, round(content.width()*dpr)), max(1, round(content.height()*dpr)))
        # A full-stage animated page needs a bounded LIVE raster even on a
        # high-DPI display. Scale the whole composition, never crop its stage.
        # Exact stills and export keep their requested output resolution.
        quality_control = getattr(self,'advanced_preview_quality',None)
        quality = str(quality_control.currentData() or 'auto') if quality_control is not None else 'auto'
        pixel_budget = {'draft':640*360,'high':1280*720}.get(quality,960*540)
        if viewport[0] * viewport[1] > pixel_budget:
            scale = (pixel_budget / (viewport[0] * viewport[1])) ** .5
            viewport = (max(1, round(viewport[0]*scale)), max(1, round(viewport[1]*scale)))
        speaker = ""
        if self.project:
            for item in self.project.speakers or []:
                if getattr(item, "id", "") == cue.speaker_id:
                    speaker = str(getattr(item, "name", "") or "")
                    break
        # 二十八轮（入场闪烁）：同 cue+同内容重复 configure 是入场连闪的根因
        # ——调度器每个播放 tick 都会走到这里，每次都换 snapshot 对象+重配
        # worker → _publish_web_live_frame 判 identity 变化 → 首帧整幅重发
        # （探针实测 wt3 入场 175ms 内 3 次 SLOW_PUBLISH+2 次 set_visual）。
        # 内容没变就只保活，不重配。
        config_key = (
            f"{cue.id}:{self._caption_snapshot_hash(snapshot)}"
            f":{duration_seconds:.3f}:{speaker}:{viewport}:{quality}"
        )
        existing = getattr(self, "_web_live_worker", None)
        if (
            existing is not None and existing.running
            and str(getattr(self, "_web_live_cue_id", "")) == str(cue.id)
            and getattr(self, "_web_live_config_key", "") == config_key
        ):
            self._publish_prepared_web_caption(cue,snapshot,existing)
            self._ensure_web_live_watchdog()
            return True
        worker = getattr(self, "_web_live_worker", None)
        bridge = getattr(self, "_web_live_bridge", None)
        if worker is None or bridge is None or not worker.running or (worker._width,worker._height)!=viewport or getattr(worker,'_quality','full')!=quality:
            if worker is not None:
                worker.stop()
            from .live_web_preview import LiveWebPreviewWorker

            # 测试 harness 可能不是 QObject——bridge 无父对象也能正常收发信号。
            bridge = _WebLiveBridge(self if isinstance(self, QObject) else None)
            bridge.frame.connect(self._on_web_live_frame)
            bridge.failed.connect(self._on_web_live_failed)
            bridge.exited.connect(self._on_web_live_exited)
            worker = LiveWebPreviewWorker(
                time_provider=self._web_live_time_provider(),
                width=viewport[0],height=viewport[1],
                name="web-live-video-layer",
                proxy_cache=True,quality=quality,
            )
            worker.frame_ready.connect(bridge.frame.emit)
            worker.failed.connect(bridge.failed.emit)
            worker.exited.connect(bridge.exited.emit)
            self._web_live_bridge = bridge
            self._web_live_worker = worker
        self._web_live_snapshot = snapshot
        if getattr(self, '_web_frame_decode_runner', None) is None:
            from .latest_work import LatestWork
            self._web_frame_decode_runner=LatestWork('web-first-frame-decode')
        self._web_live_cue_id = str(cue.id)
        self._web_live_config_key = config_key
        self._web_live_last_frame_at = float(
            getattr(self, "_web_live_last_frame_at", 0.0) or 0.0
        )
        prepared = self._prepared_caption(cue.id)
        if prepared is not None and prepared.snapshot is snapshot and prepared.web is not None:
            worker.configure_prepared(prepared.web)
        else:
            worker.configure(theme=theme,text=snapshot.text,speaker=speaker,duration_seconds=duration_seconds,
                placement=snapshot.style_recipe.get('layout', {}).get('webPlacement'))
        runtime = getattr(getattr(self, 'session', None), 'runtime', None)
        if runtime is not None:
            from bisect import bisect_right
            following=bisect_right(runtime._cue_starts, int(cue.start_ms))
            for cue_id in runtime._cue_order[following:following+max(2,2*len(self.project.speakers))]:
                upcoming=self._prepared_caption(cue_id)
                if upcoming is not None and upcoming.web is not None:
                    worker.warm_prepared(upcoming.web)
        worker.start()
        self._prepare_caption_pixels([cue.id,*runtime._cue_order[following:following+2]] if runtime is not None else [cue.id])
        self._publish_prepared_web_caption(cue,snapshot,worker)
        self._ensure_web_live_watchdog()
        return True

    def _publish_prepared_web_caption(self, cue, snapshot, worker):
        if (getattr(getattr(self.advanced_cue_overlay,'_snapshot',None),'cue_id','')==cue.id
                and getattr(self,'_web_live_published_cue','')==cue.id):return
        pixels=self._prepared_caption_pixels(snapshot)
        if pixels is None or pixels.png is None:return
        now_ms=float(self.timeline.playhead_ms)
        theme=snapshot.style_recipe.get('webTheme',{})
        animated=bool(theme.get('motionSpec') or 'animation' in str(theme.get('cueCss','')).lower()
                      or 'animation' in str(theme.get('stageCss','')).lower())
        if not cue.start_ms<=now_ms<cue.end_ms:return
        if animated and now_ms-cue.start_ms>1000/60:return
        from .live_web_preview import WebFrame
        frame=WebFrame(pixels.png,id(worker),worker.strip_key,worker._configuration_generation,
                       self.video.playback_position_snapshot().playback_generation)
        frame.decoded_image=pixels.image
        frame.prepared_pixels=pixels
        self._publish_web_live_frame(frame,now_ms-cue.start_ms,now_ms,snapshot,self.advanced_cue_overlay)
        self._studio_trace('CAPTION_PIXELS_HANDOFF',cue_id=cue.id,prepared_at=pixels.finished,stage_ms=now_ms)

    def _ensure_web_live_watchdog(self) -> None:
        """二十五轮：水平触发看门狗——调度是边沿触发（cue 变化才发生），
        worker 被启动期竞争/失败/换绑竞争搞死后，暂停态没有任何 tick 会重建
        它（用户实测"刚打开全程镜像、特效字静止"）。看门狗周期检查：播头
        在 web cue 内 + 无活 worker + 熔断清 → 强制重排。
        """
        timer = getattr(self, "_web_live_watchdog_timer", None)
        if timer is not None:
            return
        timer = QTimer(self if isinstance(self, QObject) else None)
        timer.setInterval(self._WEB_LIVE_WATCHDOG_MS)
        timer.timeout.connect(self._web_live_watchdog_tick)
        self._web_live_watchdog_timer = timer
        timer.start()

    def _web_live_watchdog_tick(self) -> None:
        try:
            if not self._web_live_preview_enabled():
                return
            # 媒体未就绪前不重排（避免启动窗口里反复做快照/镜像调度）。
            if getattr(getattr(self, "video", None), "_startup_state", "READY") != "READY":
                return
            worker = getattr(self, "_web_live_worker", None)
            if worker is not None and worker.running:
                return
            failed_at = float(getattr(self, "_web_live_failed_at", 0.0) or 0.0)
            if failed_at and time.monotonic() - failed_at < self._WEB_LIVE_RETRY_SECONDS:
                return
            if failed_at:
                self._web_live_failed_at = 0.0
            if self.project is None or not getattr(self, "_cue_lookup", None):
                return
            cue = self._renderer_cue_at_playhead()
            if cue is None:
                return
            payload = self.project.style_recipes.get(cue.style_id, {}) or {}
            if not (
                isinstance(payload, Mapping)
                and isinstance(payload.get("webTheme"), Mapping)
                and payload["webTheme"]
            ):
                return
            self._studio_trace("WEB_LIVE_WATCHDOG_REARM", cue_id=str(cue.id))
            self._schedule_advanced_preview(payload, force=True)
        except Exception:
            return

    def _web_live_time_provider(self):
        """二十三轮：provider 动态解析当前 web cue——worker 跨 cue 存活。

        此前 provider 闭包绑定创建时的 cue，跨 cue 必算出出界→worker 自毁
        →每条 cue 整页重载（间隙无帧="预览卡住"根因）。现在按 _web_live_cue_id
        /播头解析当前 cue 并换绑；无 web cue 在播头才真正退出。
        """
        def provide():
            cue = None
            if getattr(self, "_cue_lookup", None):
                cue = self._cue_lookup.get(str(getattr(self, "_web_live_cue_id", "") or ""))
            if cue is None:
                candidate = self._renderer_cue_at_playhead()
                if candidate is not None and self.project:
                    payload = self.project.style_recipes.get(candidate.style_id, {}) or {}
                    if isinstance(payload.get("webTheme"), Mapping) and payload["webTheme"]:
                        cue = candidate
                        self._web_live_cue_id = candidate.id  # 换绑（同 worker 服务新 cue）
            if cue is None:
                return None
            timing=getattr(self,'_cue_timing_preview',None)
            if timing is not None and timing.active and cue.id in timing.values:
                interval=timing.values[cue.id]
                cue=replace(cue,start_ms=interval.start_ms,end_ms=interval.end_ms,speaker_id=interval.speaker_id)
            try:
                playback = self.video.playback_position_snapshot()
            except Exception:
                return None
            clock = getattr(self.video, '_playback_clock', None)
            # The worker polls faster than the GUI snapshot is refreshed.
            # Read the sole clock's current presentation time; stale samples
            # otherwise look like drift at 2x/4x and repeatedly restart CDP.
            position_ms = float(clock.presentation_position_ms() if clock is not None
                                else playback.presentation_media_ms)
            if getattr(self, "_playback_mode", "source") == "mapped" and self.project:
                mapped = source_to_timeline(sequence_of(self.project), int(position_ms))
                if mapped is not None:
                    position_ms = mapped.timeline_ms
            # 二十五轮：mpv 位置与 UI 播头失联（打开初期媒体未挂载 / seek 飞行 /
            # 空媒体 0 位）时，条带按 UI 播头驱动——cue 区间与 playhead_ms 同为
            # timeline 域，自洽且语义正确（预览跟随用户看到的时间）。此前直接
            # 判出界 → exited → worker 反复死亡churn（用户实测"刚打开全程镜像/
            # 特效字静止"的最终根因）。
            try:
                ui_playhead_ms = float(
                    getattr(getattr(self, "timeline", None), "playhead_ms", 0) or 0
                )
            except Exception:
                ui_playhead_ms = 0.0
            if ui_playhead_ms > 0.0 and abs(position_ms - ui_playhead_ms) > 2000.0:
                position_ms = ui_playhead_ms

            def _resolve(candidate_cue):
                local_ms = position_ms - float(candidate_cue.start_ms)
                span = float(candidate_cue.end_ms - candidate_cue.start_ms)
                # All exit motion lives inside the half-open cue interval.
                # A late clear frame cannot extend visibility into the next turn.
                if (timing is None or not timing.active) and (local_ms < 0.0 or local_ms >= span):
                    return None
                return candidate_cue, local_ms, span

            resolved = _resolve(cue)
            if resolved is None:
                # 绑定的 cue 出界——先尝试换绑播头处的新 web cue（跨 cue 不
                # 自毁，换字快路径全程生效）；没有才真正退出（worker exited）。
                candidate = self._renderer_cue_at_playhead()
                if (
                    candidate is not None
                    and candidate.id != cue.id
                    and self.project
                    and isinstance(
                        (self.project.style_recipes.get(candidate.style_id, {}) or {}).get("webTheme"),
                        Mapping,
                    )
                ):
                    rebind = _resolve(candidate)
                    if rebind is not None:
                        self._web_live_cue_id = candidate.id
                        cue, cue_ms, span = rebind
                    else:
                        return None
                else:
                    return None
            else:
                cue, cue_ms, span = resolved
            playing = not bool(getattr(playback, "paused", True))
            rate = float(
                getattr(playback, "playback_rate", 0.0)
                or getattr(self.video, "_project_playback_rate", 0.0)
                or 1.0
            )
            return (
                max(0.0, min(cue_ms, span)),
                max(0.0, position_ms),
                playing,
                rate,
            )

        provide.discontinuity_generation = lambda: getattr(
            self.video.playback_position_snapshot(), 'playback_generation', None)
        return provide

    def _web_live_is_fresh(self) -> bool:
        if str(getattr(self, "_advanced_canvas_source_kind", "")) != "web_live":
            return False
        return (
            time.monotonic() - float(getattr(self, "_web_live_last_frame_at", 0.0) or 0.0)
            < self._WEB_LIVE_FRESH_SECONDS
        )

    def _queue_web_strip_warm(self, cue_ids: list[str]) -> None:
        """二十四轮：为指定 web cue 排队条带预热（record-once→replay 的后台录）。

        应用于范围（当前/说话人/全部）与播放预取都会走这里——预热过的 cue
        切换即查即得，且录制完成后播放完全不依赖 Chromium 存活。
        """
        worker = getattr(self, "_web_live_worker", None)
        if worker is None or not getattr(worker, "running", False):
            return
        if self.project is None:
            return
        for cue_id in list(cue_ids)[:8]:
            cue = (getattr(self, "_cue_lookup", None) or {}).get(str(cue_id))
            if cue is None:
                continue
            payload = self.project.style_recipes.get(cue.style_id, {}) or {}
            theme = (
                payload.get("webTheme")
                if isinstance(payload, Mapping)
                else None
            )
            if not isinstance(theme, Mapping) or not theme:
                continue
            speaker = ""
            for item in self.project.speakers or []:
                if getattr(item, "id", "") == cue.speaker_id:
                    speaker = str(getattr(item, "name", "") or "")
                    break
            try:
                worker.warm(
                    theme=theme,
                    text=str(cue.text or ""),
                    speaker=speaker,
                    duration_seconds=max(0.3, (cue.end_ms - cue.start_ms) / 1000.0),
                )
            except Exception:
                continue

    def _on_web_live_frame(self, png: bytes, cue_ms: float, stage_ms: float) -> None:
        if not self._web_frame_is_current(png):
            return
        if hasattr(png, 'clock_generation'):
            identity=(png.worker_id,png.content_key,png.generation,png.clock_generation)
            if identity != getattr(self,'_web_live_published_identity',None) and not hasattr(png,'decoded_image'):
                runner=getattr(self,'_web_frame_decode_runner',None)
                bridge=getattr(self,'_web_live_bridge',None)
                if runner is not None and bridge is not None:
                    def decode_first():
                        png.decoded_image=QImage.fromData(bytes(png))
                        bridge.frame.emit(png,cue_ms,stage_ms)
                    runner.submit(decode_first)
                    return
        snapshot = getattr(self, "_web_live_snapshot", None)
        cue = (getattr(self, '_cue_lookup', None) or {}).get(str(getattr(snapshot,'cue_id','')))
        if cue is not None:
            timing=getattr(self,'_cue_timing_preview',None)
            interval=timing.values.get(cue.id,cue) if timing is not None and timing.active else cue
            now_ms=getattr(getattr(self,'timeline',None),'playhead_ms',stage_ms)
            if not (interval.start_ms<=stage_ms<interval.end_ms and interval.start_ms<=now_ms<interval.end_ms):return
        overlay = getattr(self, "advanced_cue_overlay", None)
        if snapshot is None or overlay is None:
            return
        # 二十四轮发布门控（~30fps 上限）：录制期回放泵与录制线程都会发帧，
        # 不设上限时 GUI 线程会被推满（像素 publishes 饱和=掉帧）。
        # 二十五轮：被拦下的帧必须保底落地（出场清屏帧之后不再有新帧，
        # 丢弃会残留最后的不透明帧——"特效字静止卡屏"）。
        # 二十七轮终版：到达只存 pending（不判断、不起表），常驻 33ms 重复
        # drain 定时器发布最新一帧——旧"按门剩余时间起表"的实现里定时器
        # 与到达流互相推让，把 46fps 输入量化成 47ms 周期（21fps）；常驻
        # drain 与到达节奏完全解耦，稳态恒 ≈30fps、尾帧必然落地（空转 3
        # tick 停表）。门开着的到达帧仍立即发布（首帧/恢复低延迟）。
        self._web_live_pending_frame = (png, cue_ms, stage_ms, snapshot, overlay)
        flush_timer = self._ensure_web_live_flush_timer()
        if not flush_timer.isActive():
            self._web_live_empty_ticks = 0
            flush_timer.start(int(self._WEB_LIVE_GATE_SECONDS * 1000))
        now = time.perf_counter()
        if now - float(getattr(self, "_web_live_publish_gate", 0.0)) >= self._WEB_LIVE_GATE_SECONDS:
            self._drain_web_live_pending_frame()

    def _ensure_web_live_flush_timer(self):
        flush_timer = getattr(self, "_web_live_flush_timer", None)
        if flush_timer is None:
            flush_timer = QTimer(self if isinstance(self, QObject) else None)
            # 二十七轮关键：必须 PreciseTimer——Qt 默认 CoarseTimer 在 Windows
            # 对齐 15.6ms 系统节拍，33ms 间隔实际按 3 节拍=47ms 触发（实测
            # 恰好解释"~22fps 一卡一卡"的最后一段）。mpv 的 16ms tick 同款处理。
            flush_timer.setTimerType(Qt.TimerType.PreciseTimer)
            flush_timer.setSingleShot(False)
            flush_timer.timeout.connect(self._flush_web_live_pending_frame)
            self._web_live_flush_timer = flush_timer
            self._web_live_empty_ticks = 0
        return flush_timer

    def _flush_web_live_pending_frame(self) -> None:
        self._drain_web_live_pending_frame()

    def _drain_web_live_pending_frame(self) -> None:
        pending = getattr(self, "_web_live_pending_frame", None)
        if pending is None:
            # 空转宽限：连续 3 个 tick 无帧（尾帧已落地/泵已停）→ 停表。
            empty = int(getattr(self, "_web_live_empty_ticks", 0) or 0) + 1
            self._web_live_empty_ticks = empty
            if empty >= 3:
                timer = getattr(self, "_web_live_flush_timer", None)
                if timer is not None and timer.isActive():
                    timer.stop()
            return
        self._web_live_empty_ticks = 0
        self._web_live_pending_frame = None
        png, cue_ms, stage_ms, snapshot, overlay = pending
        self._web_live_publish_gate = time.perf_counter()
        self._publish_web_live_frame(png, cue_ms, stage_ms, snapshot, overlay)

    def _publish_web_live_frame(
        self, data, cue_ms: float, stage_ms: float, snapshot, overlay,
    ) -> None:
        timing=getattr(self,'_cue_timing_preview',None)
        if timing is not None and timing.active:
            active=timing.cue_at_playhead()
            if active is None or active.id!=snapshot.cue_id:return
        if not self._web_frame_is_current(data):
            return
        if getattr(self, "_web_live_snapshot", snapshot) is not snapshot:
            return
        cue = (getattr(self, '_cue_lookup', None) or {}).get(str(getattr(snapshot,'cue_id','')))
        if cue is not None:
            interval=timing.values.get(cue.id,cue) if timing is not None and timing.active else cue
            now_ms=getattr(getattr(self,'timeline',None),'playhead_ms',stage_ms)
            if not (interval.start_ms<=stage_ms<interval.end_ms and interval.start_ms<=now_ms<interval.end_ms):return
        # 二十七轮：worker 发原始 PNG bytes——解码（~15ms）在发布线程，
        # GUI 只算几何+门控。首帧（cue 切换/换绑）走完整 set_visual 绑定
        # snapshot/可见性；稳态帧走快速通道（旧路径每帧 ~6 次全画布拷贝+
        # 3.7MB 同步写盘 ≈30-60ms，用户实测视频层 ~10fps 一卡一卡）。
        payload = data if isinstance(data, (bytes, bytearray)) else None
        image = getattr(data, 'decoded_image', None)
        if payload is None:
            # 兼容 QImage/tuple 旧形态（测试桩）。
            if isinstance(data, tuple):
                image = data[0]
            elif isinstance(data, QImage):
                image = data
            if image is None or image.isNull():
                return
        now = time.monotonic()
        self._advanced_canvas_source_kind = "web_live"
        overlay._web_frame_context = dict(web_worker_id=getattr(data,'worker_id',None),
            web_content_key=getattr(data,'content_key',''),web_generation=getattr(data,'generation',None),
            web_clock_generation=getattr(data,'clock_generation',None),
            web_cue_ms=float(cue_ms),web_stage_ms=float(stage_ms))
        self._web_live_last_frame_at = now
        frame_identity = ((data.worker_id, data.content_key, data.generation, data.clock_generation)
                          if hasattr(data, 'clock_generation') else None)
        first_frame = (
            str(getattr(self, "_web_live_published_cue", "")) != str(getattr(self, "_web_live_cue_id", "") or "")
            or getattr(self, "_web_live_snapshot", None) is not snapshot
            or (frame_identity is not None and frame_identity != getattr(self, '_web_live_published_identity', None))
        )
        pixel_base=None
        if payload is not None:
            import hashlib
            digest=getattr(data,'pixel_digest',None) or hashlib.blake2s(payload,digest_size=16).digest()
            geometry=getattr(overlay,'geometry',None)
            rect=tuple(geometry().getRect()) if callable(geometry) else None
            pixel_base=(frame_identity,id(snapshot),snapshot.cue_id,rect,digest)
            signature=(pixel_base,getattr(getattr(self,'video',None),'_web_live_epoch',0))
            if not first_frame and signature==getattr(self,'_web_live_pixel_signature',None):
                # Refresh liveness above, but identical pixels need no decode,
                # bitmap replacement or IPC command. Identity changes still bind.
                self._web_live_duplicate_pixels=getattr(self,'_web_live_duplicate_pixels',0)+1
                return True
        if first_frame:
            # 二十八轮：开启 overlay 会话（清场 REMOVE 会关掉它；重开由首帧
            # 触发，稳态迟到帧不再复活已清场的 overlay）。
            begin = getattr(getattr(self, "video", None), "begin_web_live_overlays", None)
            if callable(begin):
                begin()
            if image is None:
                image = QImage.fromData(bytes(payload))
                if image.isNull():
                    return
            # The first frame binds the canvas through the normal overlay
            # route. Record its actual decoded image just as the fast route
            # does; an imported theme may remain paused on this one frame.
            # Without it StudioReadiness waits 30 s for a second frame that
            # correct paused-content deduplication will never produce.
            video = getattr(self, 'video', None)
            if video is not None:
                video._web_last_decoded = (getattr(video, '_web_live_epoch', 0), image)
            pixmap = QPixmap.fromImage(image)
            self._advanced_cue_pixmap = QPixmap(pixmap)
            self._web_live_mirror_at = now
            prepared_pixels=getattr(data,'prepared_pixels',None)
            overlay._prepared_raw_pixels=(pixmap.cacheKey(),prepared_pixels) if prepared_pixels is not None and prepared_pixels.raw_path is not None else None
            try:
                overlay.set_visual(pixmap, snapshot, animate_graph=False, **self._caption_binding_options(snapshot))
            except Exception:
                return
            self._web_live_published_cue = str(getattr(self, "_web_live_cue_id", "") or "")
            self._web_live_published_identity = frame_identity
        else:
            # Qt 侧镜像降频（被 mpv 原生窗口盖住，只服务测试/诊断）；
            # 解码仅在镜像档发生（8fps×~12ms，GUI 占用 ~10%）。
            if now - float(getattr(self, "_web_live_mirror_at", 0.0) or 0.0) > 0.12:
                self._web_live_mirror_at = now
                if image is None:
                    decoded = getattr(self.video,"_web_last_decoded",None)
                    if decoded and decoded[0] == self.video._web_live_epoch:
                        image = decoded[1]
                if image is not None and not image.isNull():
                    pixmap = QPixmap.fromImage(image)
                    self._advanced_cue_pixmap = QPixmap(pixmap)
                    mirror = getattr(overlay, "set_web_mirror_frame", None)
                    if callable(mirror):
                        try:
                            mirror(pixmap)
                        except Exception:
                            pass
            publish = getattr(overlay, "publish_web_frame", None)
            if callable(publish):
                try:
                    posted = publish(bytes(payload) if payload is not None else image)
                except Exception:
                    return
                if posted is False:
                    # 会话已被清场 REMOVE 关闭（exit/换手）。此时到达的都是
                    # 回放泵的迟到帧——直接丢弃。绝不能在这里重走首帧重开会话：
                    # 那会让迟到帧"复活"已清场的 overlay，libass 恢复被消抖循环
                    # 无限押后（二十八轮探针实证：REMOVE 后 10ms 内 4 帧复活）。
                    return
            else:
                # 兼容只有 set_visual 的画布/测试桩：稳态帧降级整帧 set_visual。
                target_image = image
                if target_image is None and payload is not None:
                    target_image = QImage.fromData(bytes(payload))
                if target_image is None or target_image.isNull():
                    return
                try:
                    overlay.set_visual(
                        QPixmap.fromImage(target_image), snapshot, animate_graph=False,
                        **self._caption_binding_options(snapshot),
                    )
                except Exception:
                    return
        if pixel_base is not None:
            self._web_live_pixel_signature=(pixel_base,getattr(getattr(self,'video',None),'_web_live_epoch',0))
        self._studio_trace(
            "WEB_LIVE_FRAME",
            cue_id=str(getattr(self, "_web_live_cue_id", "") or ""),
            cue_ms=round(float(cue_ms), 1),
            stage_ms=round(float(stage_ms), 1),
        )
        return True

    def _on_web_live_failed(self, message: str) -> None:
        self._web_live_failed_at = time.monotonic()
        self._stop_web_live_preview(f"failed: {str(message)[:100]}")
        self._studio_trace("WEB_LIVE_FAILED", reason=str(message)[:200])
        # 立即回退：旧镜像/网格路径重新接管当前 cue。
        self.ensure_active_subtitle_renderer(reason="web_live_failed")
        # 二十轮自愈：3 秒后清熔断重试 live 泵（播放中调度器不再周期触发，
        # 曾导致重播十次后永久退化为镜像——用户实测"图二"状态）。
        def retry(attempts: int = 3) -> None:
            self._web_live_failed_at = 0.0
            cue = self._renderer_cue_at_playhead()
            if cue is None:
                # 二十五轮：播头暂在空隙（gap）不是终点——再排一次，
                # 三次都空才放弃（此前一次静默 return 曾让恢复链断掉）。
                if attempts > 1:
                    QTimer.singleShot(3000, lambda: retry(attempts - 1))
                return
            payload = recipe_payload_for_style(self.project.style_recipes, cue.style_id) if self.project else {}
            if isinstance(payload, Mapping) and isinstance(payload.get("webTheme"), Mapping):
                self._schedule_advanced_preview(payload, force=True)

        QTimer.singleShot(3000, retry)

    def _web_frame_is_current(self, frame):
        if not hasattr(frame, "worker_id"):
            return True  # diagnostic fixtures / pre-tagged transports
        worker = getattr(self, "_web_live_worker", None)
        clock_generation = getattr(frame, 'clock_generation', None)
        if clock_generation is not None:
            snapshot = self.video.playback_position_snapshot()
            if clock_generation != snapshot.playback_generation:
                return False
        return bool(worker and frame.worker_id == id(worker)
            and frame.content_key == worker.strip_key
            and frame.generation == worker._configuration_generation)

    def _on_web_live_exited(self) -> None:
        """Cue 结束（播头出界）：worker 自停，画布按 ownership 重判隐藏。"""
        # 迟到 exited 防御（二十四轮）：exited 是跨线程排队信号，送达时播头
        # 可能已经回到 web cue 且 worker 还在服务（跨间隙快速往返 seek）。
        # 此时忽略，否则 worker 被误杀、暂停态没有调度 tick 无人重建——
        # 用户实测"应用/seek 后字幕消失"的一类根因。
        worker = getattr(self, "_web_live_worker", None)
        if worker is not None and worker.running and self.project:
            cue = self._renderer_cue_at_playhead()
            if cue is not None:
                payload = self.project.style_recipes.get(cue.style_id, {}) or {}
                if isinstance(payload.get("webTheme"), Mapping) and payload["webTheme"]:
                    self._studio_trace(
                        "WEB_LIVE_EXITED_STALE_IGNORED", cue_id=str(cue.id),
                    )
                    return
        self._stop_web_live_preview("cue_exited")
        self._studio_trace("WEB_LIVE_EXITED", cue_id=str(getattr(self, "_web_live_cue_id", "") or ""))
        self.ensure_active_subtitle_renderer(reason="web_live_exited")

    def _stop_web_live_preview(self, reason: str = "") -> None:
        decoder=getattr(self,'_web_frame_decode_runner',None)
        if decoder is not None:
            decoder.close()
            self._web_frame_decode_runner=None
        worker = getattr(self, "_web_live_worker", None)
        if worker is not None:
            worker.stop()
        self._web_live_worker = None
        # 二十五轮：清干净 web_live 的全部残留状态——残留的 snapshot/cue_id/
        # 旧 pixmap 会让 ownership 重判时"复活"上一条 cue 的旧帧（用户实测
        # 旧特效帧与新字幕同轴叠印、其它字幕不显示）。
        self._web_live_snapshot = None
        self._web_live_cue_id = ""
        self._web_live_config_key = ""
        self._web_live_pending_frame = None
        self._web_live_mirror_key = ""
        # 二十八轮：关闭快速 overlay 会话并清空在途帧队列（worker 退出前回放
        # 泵的迟到帧不再可能复活已清场的 overlay）。
        stop_session = getattr(getattr(self, "video", None), "stop_web_live_overlays", None)
        if callable(stop_session):
            stop_session()
        # 二十七轮：停掉常驻 drain 定时器 + 快速通道首帧标记复位（下个 cue
        # 首帧重新走 set_visual 绑 snapshot）。
        flush_timer = getattr(self, "_web_live_flush_timer", None)
        if flush_timer is not None and flush_timer.isActive():
            flush_timer.stop()
        self._web_live_empty_ticks = 0
        self._web_live_published_cue = ""
        self._web_live_published_identity = None
        self._web_live_mirror_at = 0.0
        if str(getattr(self, "_advanced_canvas_source_kind", "")) == "web_live":
            # 让后续 LIVE/fidelity 正常接管（不再声明 web_live 归属）。
            self._advanced_canvas_source_kind = "live"
            self._advanced_cue_pixmap = None
        if reason:
            pass

    def _queue_advanced_preview(
        self, payload: Mapping[str, object], *, force: bool = False, delay_ms: int = 220,
    ) -> None:
        component_started = perf_counter()
        invalidated_generation = self._advanced_preview_state.invalidate_current()
        self._advanced_preview_generation = invalidated_generation
        self._advanced_preview_pending_payload = copy.deepcopy(dict(payload))
        self._advanced_preview_pending_force = bool(force)
        delay_ms = max(0, int(delay_ms))
        if delay_ms == 0:
            self._advanced_preview_timer.stop()
            self._flush_advanced_preview_request()
        else:
            self._advanced_preview_timer.start(delay_ms)
        self._interaction_runtime_audit.add_component(
            "preview_request_ms", (perf_counter() - component_started) * 1000.0
        )

    def _queue_selected_advanced_preview(self) -> None:
        if not self.project or not self.selected_cue_id:
            return
        cue = self._cue_lookup.get(self.selected_cue_id)
        payload = self.project.style_recipes.get(cue.style_id, {}) if cue else {}
        if payload and route_recipe(payload).engine == "remotion":
            self._queue_advanced_preview(payload, delay_ms=0)

    def _flush_advanced_preview_request(self) -> None:
        payload = self._advanced_preview_pending_payload
        force = self._advanced_preview_pending_force
        self._advanced_preview_pending_payload = None
        self._advanced_preview_pending_force = False
        if payload:
            self._schedule_advanced_preview(payload, force=force)

    def _publish_advanced_live(
        self,
        snapshot,
        identity: AdvancedPreviewIdentity,
    ) -> float:
        """Publish Qt-capable recipes; HTML must wait for its actual pixels."""
        if snapshot.style_recipe.get('webTheme'):
            return 0.0
        started = perf_counter()
        dpr = float(self.advanced_cue_overlay.devicePixelRatioF() or 1.0)
        overlay_rect = QRect()
        if hasattr(self, "position_overlay"):
            overlay_rect = self.position_overlay._content_rect().toRect()
        live_resolution = (
            max(1, overlay_rect.width()),
            max(1, overlay_rect.height()),
        ) if not overlay_rect.isEmpty() else identity.resolution
        # 2026-09-02 修复（倍速卡顿）：LIVE 只是近似层，fidelity 数秒内接管。
        # 4K 画布（1501×844 逻辑 × 1.75 DPR ≈ 390 万设备像素）同步光栅化曾让
        # 单次发布高达 444ms、GUI 线程整段冻结——按像素预算降采样渲染，
        # 画布端放大显示（实测真机 2x 段 1.24s/10s 的 GUI 阻塞源）。
        max_live_device_pixels = 1_200_000
        dpr_for_budget = max(1.0, dpr)
        device_pixels = live_resolution[0] * live_resolution[1] * dpr_for_budget * dpr_for_budget
        if device_pixels > max_live_device_pixels:
            factor = (max_live_device_pixels / device_pixels) ** 0.5
            live_resolution = (
                max(1, round(live_resolution[0] * factor)),
                max(1, round(live_resolution[1] * factor)),
            )
        live_key = snapshot.pixel_hash(
            renderer_version=LIVE_RENDERER_VERSION,
            resolution=live_resolution,
            device_pixel_ratio=dpr,
        )
        pixmap = self._advanced_live_memory.get(live_key)
        if pixmap is None:
            prepared_pixels=self._prepared_caption_pixels(snapshot)
            if prepared_pixels is not None and prepared_pixels.png is None:
                pixmap=QPixmap.fromImage(prepared_pixels.image)
                self._advanced_live_memory[live_key]=pixmap
                self._studio_trace('CAPTION_PIXELS_HANDOFF',cue_id=snapshot.cue_id,prepared_at=prepared_pixels.finished,
                                   stage_ms=self.timeline.playhead_ms)
        memory_hit = pixmap is not None and not pixmap.isNull()
        from .static_caption_contract import shared_static_recipe
        if not memory_hit and shared_static_recipe(snapshot.style_recipe):
            # A cold static cue must not first expose libass's different
            # line-box anchor (or its solid-color gradient approximation).
            # Prepared frames are preferred; the bounded on-demand raster uses
            # the identical layout, with no sleep or hidden leading frames.
            pixmap = QPixmap.fromImage(render_live_snapshot(snapshot,
                width=live_resolution[0], height=live_resolution[1], device_pixel_ratio=dpr))
            self._advanced_live_memory[live_key] = pixmap
            while len(self._advanced_live_memory) > self._advanced_live_memory_limit:
                self._advanced_live_memory.pop(next(iter(self._advanced_live_memory)))
            return self._commit_advanced_live(pixmap, snapshot, identity, live_key, False,
                                             (perf_counter()-started)*1000)
        if not memory_hit:
            # 2026-09-02 修复（倍速卡顿）：LIVE 光栅化曾在 GUI 线程同步执行，
            # 全 advanced 工程里每个 cue 入场冻结 90-450ms（真机实测）。
            # QImage 离屏渲染是本库既有模式（live layer pipeline 同款）；
            # QPixmap 转换与发布回 GUI。旧请求由 key 失配自然作废。
            inflight = getattr(self, "_advanced_live_inflight_key", "")
            if inflight == live_key:
                return 0.0
            self._advanced_live_inflight_key = live_key
            generation = getattr(self, "_advanced_live_render_generation", 0) + 1
            self._advanced_live_render_generation = generation
            bridge = self._ensure_advanced_live_bridge()
            render_w, render_h = live_resolution
            render_dpr = float(dpr)

            def render_off_gui() -> None:
                try:
                    image = render_live_snapshot(
                        snapshot,
                        width=render_w,
                        height=render_h,
                        device_pixel_ratio=render_dpr,
                    )
                except Exception:
                    self._advanced_live_inflight_key = ""
                    return
                bridge.ready.emit(live_key, image, snapshot, identity, generation)

            runner = getattr(self, '_live_raster_runner', None)
            if runner is None or runner.closed:
                from .latest_work import LatestWork
                runner = self._live_raster_runner = LatestWork('advanced-live-render')
                if hasattr(self, 'destroyed'):self.destroyed.connect(lambda *_:runner.close())
            runner.submit(render_off_gui)
            return 0.0
        else:
            self._advanced_live_memory.pop(live_key, None)
            self._advanced_live_memory[live_key] = pixmap
        elapsed_ms = (perf_counter() - started) * 1000.0
        return self._commit_advanced_live(pixmap, snapshot, identity, live_key, memory_hit, elapsed_ms)

    def _ensure_advanced_live_bridge(self) -> _LiveRenderBridge:
        bridge = getattr(self, "_advanced_live_bridge", None)
        if bridge is None:
            bridge = _LiveRenderBridge(self)
            bridge.ready.connect(self._on_advanced_live_render_ready)
            self._advanced_live_bridge = bridge
        return bridge

    def _on_advanced_live_render_ready(
        self, live_key: str, image: QImage, snapshot, identity, generation=None,
    ) -> None:
        if generation is not None and generation != getattr(self, "_advanced_live_render_generation", 0):
            return
        if getattr(self, "_advanced_live_inflight_key", "") != live_key:
            return  # a newer publish superseded this render
        self._advanced_live_inflight_key = ""
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        self._advanced_live_memory[live_key] = QPixmap(pixmap)
        while len(self._advanced_live_memory) > self._advanced_live_memory_limit:
            oldest = next(iter(self._advanced_live_memory))
            if oldest == live_key and len(self._advanced_live_memory) > 1:
                oldest = next(key for key in self._advanced_live_memory if key != live_key)
            self._advanced_live_memory.pop(oldest, None)
        self._commit_advanced_live(pixmap, snapshot, identity, live_key, False, 0.0)

    def _commit_advanced_live(
        self, pixmap: QPixmap, snapshot, identity, live_key: str,
        memory_hit: bool, elapsed_ms: float,
    ) -> float:
        # Reject already queued Qt mirrors too (cold load/seek/style edits).
        if snapshot.style_recipe.get('webTheme'):
            return elapsed_ms
        if getattr(getattr(self, '_caption_scene', None), 'active', False):
            return elapsed_ms
        active_snapshot = (getattr(self, "_web_live_snapshot", None)
            if self._web_live_preview_enabled() and getattr(self, "_web_live_worker", None)
            else getattr(self, "_advanced_preview_snapshot", None))
        if active_snapshot is not None and self._caption_snapshot_hash(active_snapshot) != self._caption_snapshot_hash(snapshot):
            return elapsed_ms
        cue = self._cue_lookup.get(snapshot.cue_id)
        payload = recipe_payload_for_style(self.project.style_recipes, cue.style_id) if self.project and cue else {}
        native = not payload or route_recipe(payload).engine != "remotion"
        if native and not (
            getattr(self, "_multitrack_composition_active", False)
            or getattr(self, "_audio_only_subtitle_active", False)
            or self._subtitle_live_interaction_owns(snapshot.cue_id)
        ):
            # A drag's asynchronous LIVE result can finish after release has
            # restored ASS ownership. Do not publish that stale second copy.
            return elapsed_ms
        if (
            str(getattr(self, "_advanced_canvas_source_kind", "")) == "fidelity"
            and str(getattr(self, "_advanced_fidelity_request_key", ""))
            == str(identity.request_key)
        ):
            # 2026-09-02（十六轮）：同一请求的真身帧已在画布上时，冗余的
            # LIVE 发布不得把它降级回镜像近似（暂停期补水合/学习词提交会
            # 连发同键 LIVE，曾把刚接管的 fidelity 在 0.15s 后盖回 live）。
            self._advanced_preview_state.mark_live(identity)
            self._studio_trace(
                "LIVE_SKIPPED_FIDELITY_CURRENT",
                cue_id=snapshot.cue_id, request_key=identity.request_key,
            )
            return elapsed_ms
        if self._web_live_is_fresh() and str(
            getattr(self, "_web_live_cue_id", "")
        ) == str(snapshot.cue_id):
            # 十九轮：实时 HTML 泵正在发布真身帧——镜像不得盖回。
            self._advanced_preview_state.mark_live(identity)
            self._studio_trace(
                "LIVE_SKIPPED_WEB_LIVE",
                cue_id=snapshot.cue_id,
            )
            return elapsed_ms
        self._advanced_cue_pixmap = QPixmap(pixmap)
        if not getattr(self, "_subtitle_transform_interactive", False):
            # Replace text/stroke/shadow as one binding, without first showing
            # the untransformed source raster from the previous generation.
            self.advanced_cue_overlay._transform_preview = {}
            self._subtitle_transform_handoff_cue_id = ""
        prepared_pixels=self._prepared_caption_pixels(snapshot)
        self.advanced_cue_overlay._prepared_raw_pixels=(pixmap.cacheKey(),prepared_pixels) if prepared_pixels is not None and prepared_pixels.raw_path is not None else None
        self.advanced_cue_overlay.set_visual(pixmap, snapshot, animate_graph=True)
        if getattr(self, "_subtitle_transform_interactive", False):
            self.advanced_cue_overlay.set_transform_preview(self._live_transform_overrides.get(snapshot.cue_id, {}))
        playback = self.video.playback_position_snapshot()
        # Snapshot cue times are project-timeline ms; in "mapped" playback the
        # clock holds source ms. Seed sync_time in the cue's own domain, the
        # same value _position_changed would deliver on the next tick.
        position_ms = float(playback.presentation_media_ms)
        if getattr(self, "_playback_mode", "source") == "mapped" and self.project:
            mapped = source_to_timeline(sequence_of(self.project), int(position_ms))
            if mapped is not None:
                position_ms = mapped.timeline_ms
        self.advanced_cue_overlay.sync_time(
            round(position_ms), paused=playback.paused,
        )
        self._advanced_canvas_source_kind = "live"
        self._advanced_preview_state.mark_live(identity)
        self._studio_trace(
            "LIVE_READY",
            job_id=identity.job_id,
            job_kind=identity.job_kind,
            cue_id=snapshot.cue_id,
            project_id=identity.project_id,
            appearance_generation=identity.appearance_generation,
            snapshot_hash=identity.snapshot_hash,
            graph_hash=identity.graph_hash,
            request_key=identity.request_key,
            live_key=live_key,
            memory_hit=memory_hit,
            generation_ms=round(elapsed_ms, 3),
            residency=self._advanced_preview_state.residency.value,
        )
        self._sync_advanced_cue_overlay()
        # The pixels just landed; re-commit foreground ownership immediately.
        # During playback the next position tick does this anyway, but a
        # paused seek (or the async render path) has no tick to rely on.
        ensure = getattr(self, "ensure_active_subtitle_renderer", None)
        if callable(ensure):
            ensure(reason="live_ready")
        return elapsed_ms

    def _schedule_advanced_preview(
        self,
        payload: Mapping[str, object],
        *,
        force: bool = False,
        queue_fidelity: bool = True,
    ) -> None:
        if self._present_caption_scene():
            return
        if getattr(getattr(self, "_cue_timing_preview", None), "active", False):
            return
        if not self.project or not hasattr(self, "advanced_preview_image"):
            return
        cue = self._renderer_cue_at_playhead()
        if cue is None:
            return
        preview_width, preview_height = self._advanced_preview_size()
        snapshot = self._prepared_caption_snapshot(cue.id, preview_width, preview_height)
        if snapshot is None:
            return
        text_override = self._live_edit_text_overrides.get(cue.id)
        if text_override is not None and text_override != snapshot.text:
            snapshot = replace(snapshot, text=str(text_override))
        transform_override = self._live_transform_overrides.get(cue.id, {})
        if transform_override:
            recipe = copy.deepcopy(snapshot.style_recipe)
            layout = recipe.setdefault("layout", {})
            typography = recipe.setdefault("typography", {})
            changes: dict[str, object] = {"style_recipe": recipe}
            if "position_x" in transform_override:
                value = float(transform_override["position_x"])
                changes["position_x"] = value
                layout["positionX"] = value
            if "position_y" in transform_override:
                value = float(transform_override["position_y"])
                changes["position_y"] = value
                layout["positionY"] = value
            if "font_size" in transform_override:
                value = float(transform_override["font_size"])
                changes["font_size"] = value
                typography["fontSize"] = value
            snapshot = replace(snapshot, **changes)
        # Web-theme cues quantize the sampled moment onto a fixed grid so
        # playback ticks hit warm cache entries: the grid frames act as a
        # prerendered sprite sequence for entrance/hold/exit (each still is
        # exact — only the sampling instant snaps to the nearest grid point).
        # 2026-09-02 修复：量化必须放在 relative_ms 求值之后——此前引用先于
        # 赋值，任何 web 主题 cue 进入本函数即 UnboundLocalError（被 Qt slot
        # 静默吞掉），LIVE 永不发布而原生字幕已被压制=字幕完全消失。
        recipe_payload = (
            snapshot.style_recipe
            if isinstance(snapshot.style_recipe, Mapping)
            else {}
        )
        # Fidelity samples the current project-time frame. LIVE remains driven
        # exclusively by PlaybackClock while video is running.
        playhead_ms = int(getattr(self.timeline, "playhead_ms", cue.start_ms) or 0)
        relative_ms = max(
            0,
            min(cue.end_ms - cue.start_ms - 1, playhead_ms - cue.start_ms),
        )
        if isinstance(recipe_payload.get("webTheme"), Mapping) and recipe_payload["webTheme"]:
            relative_ms = self._web_theme_grid_ms(
                relative_ms, max(1, cue.end_ms - cue.start_ms)
            )
            # 二十轮接管分支上移（二十一轮修复）：必须先于 state/identity
            # 簿记与 PREPARING 同键早退——worker exited 后重播 seek 若撞上
            # 早退条件，泵永远不重建（重播 0/15 根因）。
            if self._ensure_web_live_preview(cue, snapshot):
                self._studio_trace(
                    "WEB_LIVE_TAKEOVER",
                    cue_id=cue.id,
                    html_key=getattr(self._web_live_worker, "html_key", ""),
                )
                # Keep preloading, but wait hidden for actual authored pixels.
                # A Qt text mirror here would flash the ordinary caption first.
                return
            self._stop_web_live_preview("breaker_open")
        diagnostic_mode = os.environ.get("TWOBYTEASR_R31_STROKE_PROBE", "") == "1"
        identity = self._advanced_preview_cache.identity(
            snapshot,
            relative_ms=relative_ms,
            width=preview_width,
            height=preview_height,
            job_kind="diagnostic" if diagnostic_mode else "production",
        )
        from .static_caption_contract import shared_static_recipe
        if identity.job_kind == 'production' and shared_static_recipe(snapshot.style_recipe):
            # No Qt-ink -> browser-line-box takeover for static captions.
            # Export consumes these same glyph rasters and the same anchor.
            state = self._advanced_preview_state
            self._advanced_preview_generation = state.select(identity, cache_hit=True, force=force)
            self._advanced_preview_expected_key = identity.request_key
            self._advanced_preview_snapshot = snapshot
            self._publish_advanced_live(snapshot, identity)
            bind_text(self.advanced_style_status, '静态字幕 · 预览与导出共用字形布局')
            return
        state = self._advanced_preview_state
        self._studio_trace(
            "ADVANCED_SELECT", cue_id=cue.id, request_key=identity.request_key,
            snapshot_hash=identity.snapshot_hash, motion_time=relative_ms,
            resolution=list(identity.resolution), force=force,
        )
        self._studio_trace(
            "SNAPSHOT_CREATED", cue_id=cue.id, snapshot_hash=identity.snapshot_hash,
            glyph_key=identity.glyph_key, motion_key=identity.motion_key,
        )
        if (
            not force
            and state.identity is not None
            and state.identity.request_key == identity.request_key
            and state.identity.snapshot_hash == identity.snapshot_hash
            and state.phase == AdvancedPreviewPhase.PREPARING
        ):
            return
        cached_path = self._advanced_preview_cache.path_for(identity.request_key)
        memory_frame = self._advanced_frame_memory.get(identity.request_key)
        if memory_frame is not None:
            # Move-to-end so the LRU order tracks real playback re-entry.
            self._advanced_frame_memory.pop(identity.request_key, None)
            self._advanced_frame_memory[identity.request_key] = memory_frame
        memory_hit = bool(
            not force and memory_frame is not None and not memory_frame.isNull()
        )
        disk_hit = bool(
            not force and cached_path.is_file() and cached_path.stat().st_size > 0
        )
        generation = state.select(identity, cache_hit=memory_hit, force=force)
        self._advanced_preview_generation = generation
        key = identity.request_key
        self._advanced_preview_expected_key = key
        self._advanced_preview_snapshot = snapshot
        live_gaps = renderer_capability_gaps(
            VisualRenderer.LIVE, snapshot.style_recipe,
        )
        if memory_hit:
            self._studio_trace("CACHE_HIT", cue_id=cue.id, request_key=key, memory=True)
            if identity.job_kind != "production":
                self._studio_trace(
                    "DIAGNOSTIC_RENDER_ISOLATED",
                    cue_id=cue.id,
                    job_id=identity.job_id,
                    job_kind=identity.job_kind,
                )
                return
            frame_path = str(cached_path) if disk_hit else state.frame_path
            # LIVE is always published for production cues. A capability gap
            # downgrades the caption to "approximate", never to "invisible":
            # suppressing LIVE here left a native-suppressed cue with no
            # foreground until the Fidelity worker finished (seconds).
            self._publish_advanced_live(snapshot, identity)
            cached_frame = QPixmap(memory_frame)
            QTimer.singleShot(
                50,
                lambda: self._publish_advanced_frame(
                    identity, generation, frame_path, True,
                    pixmap=cached_frame,
                ),
            )
            return
        self._studio_trace(
            "CACHE_HIT" if disk_hit else "CACHE_MISS",
            cue_id=cue.id,
            request_key=key,
            memory=False,
            disk=disk_hit,
        )
        if identity.job_kind != "production":
            self._studio_trace(
                "DIAGNOSTIC_RENDER_ISOLATED",
                cue_id=cue.id,
                job_id=identity.job_id,
                job_kind=identity.job_kind,
            )
            bind_text(self.advanced_preview_image, '开发诊断渲染已隔离')
            bind_text(self.advanced_style_status, '诊断任务不会接管前景')
        else:
            # Always publish the LIVE approximation immediately. The previous
            # gap gate kept the canvas empty for the whole Fidelity round trip
            # (measured 1.6-2.4s in packaged traces), which the user saw as
            # "the AI subtitle flashes 1-2 frames then disappears".
            self._publish_advanced_live(snapshot, identity)
            if live_gaps:
                self._studio_trace(
                    "LIVE_CAPABILITY_GAP",
                    cue_id=cue.id,
                    request_key=key,
                    capabilities=[gap.capability.value for gap in live_gaps],
                )
                bind_text(self.advanced_preview_image, '复杂视觉 · 近似预览已就绪…')
                bind_text(self.advanced_style_status, '⚡ LIVE 近似预览中 · 高保真预览后台准备中')
            else:
                bind_text(self.advanced_preview_image, '⚡ 复杂视觉 · 正在准备实时预览…')
                bind_text(self.advanced_style_status, '⚡ LIVE 已就绪 · 高保真预览后台准备中')

        if not queue_fidelity:
            return

        self._queue_advanced_preview_job(
            identity, generation, snapshot, force, relative_ms,
            preview_width, preview_height, cue.id, key,
        )

    def _queue_advanced_preview_job(
        self,
        identity: AdvancedPreviewIdentity,
        generation: int,
        snapshot: object,
        force: bool,
        relative_ms: int,
        preview_width: int,
        preview_height: int,
        cue_id: str,
        key: str,
    ) -> None:
        job = (
            identity, int(generation), snapshot, bool(force), int(relative_ms),
            int(preview_width), int(preview_height), str(cue_id), str(key),
        )
        with self._advanced_preview_condition:
            if self._advanced_preview_worker_stopping:
                return
            self._advanced_preview_pending_job = job
            thread = self._advanced_preview_thread
            if thread is None or not thread.is_alive():
                thread = threading.Thread(
                    target=self._advanced_preview_worker,
                    daemon=True,
                    name="advanced-style-preview",
                )
                self._advanced_preview_thread = thread
                thread.start()
            self._advanced_preview_condition.notify_all()

    def _advanced_preview_worker(self) -> None:
        resource_governor = getattr(
            self, "_resource_governor", GLOBAL_RESOURCE_GOVERNOR,
        )
        runtime_cache = getattr(self, "_runtime_cache", GLOBAL_RUNTIME_CACHE)
        while True:
            with self._advanced_preview_condition:
                while (
                    self._advanced_preview_pending_job is None
                    and not self._advanced_preview_worker_stopping
                ):
                    self._advanced_preview_condition.wait()
                if self._advanced_preview_worker_stopping:
                    break
                job = self._advanced_preview_pending_job
                self._advanced_preview_pending_job = None
                self._advanced_preview_worker_running = True
            assert job is not None
            (
                identity, generation, snapshot, force, relative_ms,
                preview_width, preview_height, cue_id, key,
            ) = job
            try:
                self._studio_trace("WORKER_START", cue_id=cue_id, request_key=key, generation=generation)
                def produce():
                    with self._advanced_render_lock:
                        return self._advanced_preview_cache.render_snapshot(
                            snapshot, force=force, relative_ms=relative_ms,
                            width=preview_width, height=preview_height,
                            generation=generation,
                            batch_group=(
                                f"studio-diagnostic:{cue_id}"
                                if identity.job_kind != "production"
                                else f"studio-fidelity:{cue_id}"
                            ),
                            identity=identity,
                        )

                with resource_governor.lease(
                    ResourceKind.ADVANCED_PREVIEW,
                    foreground=identity.job_kind == "production",
                ) as allowed:
                    if not allowed:
                        raise InterruptedError("advanced preview cancelled")
                    (result_key, path, hit), _produced = runtime_cache.get_or_create(
                        f"advanced-fidelity:{key}", produce, store_memory=False,
                    )
                if Path(path).is_file():
                    try:
                        runtime_cache.register_artifact(
                            f"advanced-fidelity:{key}", path,
                        )
                    except OSError:
                        pass
                self._studio_trace("WORKER_FINISH", cue_id=cue_id, request_key=result_key, generation=generation, cache_hit=hit)
                if not self._advanced_preview_cache.discard_if_stale(generation, self._advanced_preview_state.generation):
                    self._studio_trace("WORKER_ENQUEUE", cue_id=cue_id, request_key=result_key, generation=generation)
                    self._advanced_preview_publish_queue.put(
                        ("ready", identity, generation, str(path), bool(hit))
                    )
                else:
                    self._studio_trace("WORKER_STALE", cue_id=cue_id, request_key=result_key, generation=generation)
            except Exception as exc:
                if generation == self._advanced_preview_state.generation:
                    self._advanced_preview_publish_queue.put(
                        ("failed", identity, generation, str(exc), False)
                    )
            finally:
                with self._advanced_preview_condition:
                    self._advanced_preview_worker_running = False
                    self._advanced_preview_condition.notify_all()

    def _wait_advanced_preview_idle(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._advanced_preview_condition:
            while (
                self._advanced_preview_pending_job is not None
                or self._advanced_preview_worker_running
            ) and time.monotonic() < deadline:
                self._advanced_preview_condition.wait(
                    min(0.05, max(0.0, deadline - time.monotonic()))
                )
            return bool(
                self._advanced_preview_pending_job is None
                and not self._advanced_preview_worker_running
            )

    def _upcoming_advanced_cue_ids(self, cue_id: str, *, lookahead: int = 2) -> list[str]:
        """Remotion cues that playback is likely to reach next."""
        if not self.project:
            return []
        runtime = self.session.runtime
        cue = self._cue_lookup.get(cue_id)
        if runtime is None or cue is None:
            return []
        from bisect import bisect_right
        index = bisect_right(runtime._cue_starts, cue.start_ms)
        upcoming: list[str] = []
        for item in runtime._cue_order[index:index+lookahead]:
            cue = runtime.cue_by_id[item]
            payload = self.project.style_recipes.get(cue.style_id)
            if payload and route_recipe(payload).engine == "remotion":
                upcoming.append(cue.id)
        return upcoming

    def _queue_advanced_prefetch(self, cue_ids: list[str]) -> None:
        """Warm the disk cache for the next cues while the user watches this one."""
        project = self.project
        if project is None:
            return
        width, height = self._advanced_preview_size()
        queued_keys = {
            job[1].request_key
            for job in self._advanced_prefetch_queue
            if isinstance(job, tuple) and len(job) >= 2
        }
        for cue_id in cue_ids:
            cue = self._cue_lookup.get(cue_id)
            payload = project.style_recipes.get(cue.style_id) if cue else None
            if not (cue and payload and route_recipe(payload).engine == "remotion"):
                continue
            snapshot = self._prepared_caption_snapshot(cue.id,width,height)
            if snapshot is None: continue
            web_theme = (
                payload.get("webTheme")
                if isinstance(payload, Mapping)
                else None
            )
            if isinstance(web_theme, Mapping) and web_theme:
                # 二十四轮：live/条带可用时 web cue 不做 still 网格预取
                # （renderStill 与 live 页抢同一浏览器，二十轮教训），改为
                # **条带预热**——空闲时把后续 web cue 的完整动画录成帧序列，
                # cue 切换即查即得（应用范围后逐条有帧，不再消失）。
                if self._web_live_preview_enabled():
                    self._queue_web_strip_warm([cue_id])
                    continue
                # Warm the whole quantized grid so playback snaps through a
                # prerendered entrance/hold/exit sequence. At review speeds
                # (>=2x) the grid cannot warm faster than playback crosses
                # cues, and the per-frame Chromium stills starve the very
                # pipeline meant to benefit — thin to a single hold frame.
                playback_rate = float(getattr(self.video, "_playback_rate", 1.0) or 1.0)
                if playback_rate >= 2.0:
                    sample_moments = [
                        max(0, min(cue.end_ms - cue.start_ms - 1, 300))
                    ]
                else:
                    sample_moments = self._web_theme_grid_frames(
                        max(1, cue.end_ms - cue.start_ms)
                    )
            else:
                sample_moments = [
                    max(0, min(cue.end_ms - cue.start_ms - 1, 300))
                ]
            for relative_ms in sample_moments:
                identity = self._advanced_preview_cache.identity(
                    snapshot, relative_ms=relative_ms, width=width, height=height,
                    job_kind="thumbnail",
                )
                if identity.request_key in queued_keys:
                    continue
                queued_keys.add(identity.request_key)
                self._advanced_prefetch_queue.append(
                    (cue.id, identity, snapshot, relative_ms, width, height)
                )
        if self._advanced_prefetch_running or not self._advanced_prefetch_queue:
            return
        self._advanced_prefetch_running = True
        threading.Thread(target=self._advanced_prefetch_worker, daemon=True, name="advanced-prefetch").start()

    def _advanced_prefetch_worker(self) -> None:
        import time as _time

        while self._advanced_prefetch_queue:
            cue_id, identity, snapshot, relative_ms, width, height = (
                self._advanced_prefetch_queue.popleft()
            )
            try:
                already = (
                    self._advanced_frame_memory.get(identity.request_key) is not None
                    or self._advanced_preview_cache.path_for(identity.request_key).is_file()
                )
                if not already:
                    self._studio_trace("PREFETCH_START", cue_id=cue_id, request_key=identity.request_key)

                    def produce():
                        with self._advanced_render_lock:
                            return self._advanced_preview_cache.render_snapshot(
                                snapshot, relative_ms=relative_ms, width=width, height=height,
                                batch_group=f"prefetch:{cue_id}",
                                job_kind="thumbnail",
                                identity=identity,
                            )

                    with self._resource_governor.lease(
                        ResourceKind.ADVANCED_PREVIEW,
                        foreground=False,
                        cancelled=lambda: self._advanced_preview_worker_stopping,
                    ) as allowed:
                        if not allowed:
                            continue
                        result, _produced = self._runtime_cache.get_or_create(
                            f"advanced-fidelity:{identity.request_key}",
                            produce,
                            prefetch=True,
                            store_memory=False,
                        )
                    _result_key, result_path, _hit = result
                    if Path(result_path).is_file():
                        try:
                            self._runtime_cache.register_artifact(
                                f"advanced-fidelity:{identity.request_key}", result_path,
                            )
                        except OSError:
                            pass
                    self._studio_trace("PREFETCH_DONE", cue_id=cue_id, request_key=identity.request_key)
            except Exception as exc:
                self._studio_trace("PREFETCH_FAILED", cue_id=cue_id, error=str(exc)[:200])
                continue
            _time.sleep(0.2)
        self._advanced_prefetch_running = False

    def _advanced_preview_ready(
        self, identity: AdvancedPreviewIdentity, generation: int, path: str, cache_hit: bool,
    ) -> None:
        self._publish_advanced_frame(identity, generation, path, cache_hit)

    def _drain_advanced_preview_results(self) -> None:
        while True:
            try:
                kind, identity, generation, value, cache_hit = (
                    self._advanced_preview_publish_queue.get_nowait()
                )
            except queue.Empty:
                return
            if kind == "ready":
                self._studio_trace(
                    "WORKER_PUBLISH",
                    cue_id=identity.cue_id,
                    request_key=identity.request_key,
                    generation=generation,
                )
                self._advanced_preview_ready(
                    identity, generation, value, bool(cache_hit)
                )
            else:
                self._advanced_preview_failed(identity, generation, value)

    def _publish_advanced_frame(
        self,
        identity: AdvancedPreviewIdentity,
        generation: int,
        path: str,
        cache_hit: bool,
        *,
        pixmap: QPixmap | None = None,
    ) -> None:
        if getattr(getattr(self, '_caption_scene', None), 'active', False):
            return
        if not hasattr(self, "advanced_preview_image"):
            return
        if self._web_live_is_fresh() and str(
            getattr(self, "_web_live_cue_id", "")
        ) == str(identity.cue_id):
            # 十九轮：实时 HTML 泵正在发布真身——still 帧（网格/单帧预热）
            # 只进缓存，不上画布（曾把真身盖回镜像观感）。
            self._advanced_frame_memory[identity.request_key] = QPixmap(
                pixmap if pixmap is not None else path
            )
            return
        current_identity = getattr(self._advanced_preview_state, "identity", None)
        if current_identity is None:
            # Compatibility for isolated renderer harnesses. Product state is
            # always AdvancedPreviewStateMachine and always owns an identity.
            current_identity = identity
        current_snapshot = getattr(self, "_advanced_preview_snapshot", None)
        from .static_caption_contract import shared_static_recipe
        if current_snapshot is not None and shared_static_recipe(current_snapshot.style_recipe):
            return  # Reject a pre-existing/delayed browser still for this route.
        identity_generation = int(getattr(
            identity,
            "appearance_generation",
            getattr(current_snapshot, "appearance_generation", 0),
        ))
        current_identity_generation = int(getattr(
            current_identity,
            "appearance_generation",
            getattr(current_snapshot, "appearance_generation", 0),
        ))
        contract_matches = bool(
            current_identity is not None
            and current_snapshot is not None
            and getattr(identity, "job_kind", "production") == "production"
            and getattr(current_identity, "job_kind", "production") == "production"
            and (
                (
                    bool(getattr(identity, "job_id", ""))
                    and getattr(identity, "job_id", "")
                    == getattr(current_identity, "job_id", "")
                )
                or (
                    not getattr(identity, "project_id", "")
                    and not getattr(current_identity, "project_id", "")
                )
            )
            and generation == getattr(self, "_advanced_preview_generation", generation)
            and generation == getattr(self._advanced_preview_state, "generation", generation)
            and identity.cue_id == current_identity.cue_id == current_snapshot.cue_id
            and getattr(identity, "project_id", "")
            == getattr(current_identity, "project_id", "")
            and getattr(identity, "project_id", "")
            == str(getattr(getattr(self, "project", None), "project_id", ""))
            and getattr(identity, "project_id", "")
            == str(getattr(current_snapshot, "project_id", ""))
            and identity.snapshot_hash == current_identity.snapshot_hash == self._caption_snapshot_hash(current_snapshot)
            and getattr(identity, "graph_hash", "") == getattr(current_identity, "graph_hash", "")
            and identity.request_key == current_identity.request_key
            and identity_generation == current_identity_generation == int(
                getattr(current_snapshot, "appearance_generation", 0)
            )
        )
        if not contract_matches:
            self._studio_trace(
                "FIDELITY_IDENTITY_DROP",
                job_id=getattr(identity, "job_id", ""),
                job_kind=getattr(identity, "job_kind", ""),
                cue_id=identity.cue_id,
                project_id=getattr(identity, "project_id", ""),
                style_generation=generation,
                current_generation=self._advanced_preview_generation,
                snapshot_hash=identity.snapshot_hash,
                graph_hash=getattr(identity, "graph_hash", ""),
                request_key=identity.request_key,
            )
            return
        if not self._advanced_preview_state.publish_ready(
            identity, generation, path, cache_hit=cache_hit,
        ):
            self._studio_trace("WORKER_STALE", cue_id=identity.cue_id, request_key=identity.request_key, generation=generation)
            return
        pixmap = QPixmap(pixmap) if pixmap is not None else QPixmap(path)
        if pixmap.isNull():
            bind_text(self.advanced_preview_image, '预览缓存不可读')
            self._advanced_preview_state.fail(identity, generation, "preview cache unreadable")
            return
        self._advanced_frame_memory[identity.request_key] = QPixmap(pixmap)
        while len(self._advanced_frame_memory) > self._advanced_frame_memory_limit:
            self._advanced_frame_memory.pop(next(iter(self._advanced_frame_memory)), None)
        # Scale to the label's physical pixels and tag the ratio, so a DPR=2
        # display never re-upscales a correctly sized frame into blur.
        dpr = float(self.advanced_preview_image.devicePixelRatioF() or 1.0)
        physical = QSize(
            max(1, round(self.advanced_preview_image.width() * dpr)),
            max(1, round(self.advanced_preview_image.height() * dpr)),
        )
        display = pixmap.scaled(physical, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        display.setDevicePixelRatio(dpr)
        self.advanced_preview_image.setPixmap(display)
        (bind_text(self.advanced_preview_image, '缓存命中', property='toolTip') if cache_hit else bind_text(self.advanced_preview_image, 'Remotion 新预览', property='toolTip'))
        snapshot = current_snapshot
        if (
            hasattr(self, "advanced_cue_overlay") and snapshot is not None
            and snapshot.cue_id == getattr(self._renderer_cue_at_playhead(), "id", "")
            and self._caption_snapshot_hash(snapshot) == identity.snapshot_hash
        ):
            recipe_payload = (
                snapshot.style_recipe
                if isinstance(snapshot.style_recipe, Mapping) else {}
            )
            is_web_theme = isinstance(recipe_payload.get("webTheme"), Mapping) and bool(
                recipe_payload["webTheme"]
            )
            if is_web_theme:
                # Web themes own their stage geometry (cards/sweeps position
                # text themselves); comparing them against the native-mirror
                # LIVE bbox always fails (real-world bbox_center_delta≈0.32)
                # and kept the real render in the background forever — the
                # fidelity frame IS the ground truth for web cues.
                can_replace_live = self._fidelity_can_replace_live(snapshot)
            else:
                can_replace_live = (
                    self._fidelity_can_replace_live(snapshot)
                    and self._fidelity_stroke_parity_ok(pixmap, snapshot)
                    and self._fidelity_geometry_ok(pixmap, snapshot)
                )
            if not can_replace_live:
                self._studio_trace(
                    "FIDELITY_BACKGROUND_READY",
                    cue_id=snapshot.cue_id,
                    job_id=identity.job_id,
                    job_kind=identity.job_kind,
                    request_key=identity.request_key,
                    foreground_owner=self._advanced_canvas_source_kind,
                    parity_drop=getattr(self, "_fidelity_parity_drop_reason", ""),
                )
                self._sync_advanced_cue_overlay()
                bind_text(self.advanced_style_status, '⚡ LIVE 播放中 · 高保真帧已在后台就绪')
                return
            self._advanced_cue_pixmap = pixmap
            self.advanced_cue_overlay.set_visual(
                pixmap, snapshot, animate_graph=False
            )
            self._advanced_canvas_source_kind = "fidelity"
            self._advanced_fidelity_request_key = str(identity.request_key)
            # 2026-09-02（十六轮）：迟到的 seek 回调可能在 playhead 瞬时不
            # 一致时把刚显示的画布藏掉且无人再触发 ensure——阶梯重判兜底。
            for delay in (350, 900, 1800, 3200):
                QTimer.singleShot(
                    delay,
                    lambda: self.ensure_active_subtitle_renderer(reason="fidelity_settle"),
                )
            self._studio_trace(
                "CANVAS_FRAME_SET",
                cue_id=snapshot.cue_id,
                job_id=identity.job_id,
                job_kind=identity.job_kind,
                project_id=identity.project_id,
                appearance_generation=identity.appearance_generation,
                snapshot_hash=identity.snapshot_hash,
                graph_hash=identity.graph_hash,
                request_key=identity.request_key,
            )
            self._sync_advanced_cue_overlay()
            bind_text(self.advanced_style_status, '⚡ 实时预览已就绪')

    # 播放期保真帧网格（十七轮用户反馈"1 秒一帧"太卡）：入场/出场 100ms
    # 步长（10fps），持住段 200ms（5fps）——旧版尾部 1600/2400/3600 的稀疏
    # 采样让持住+出场看起来一秒一跳。预热成本：3s cue ≈22 帧。
    _WEB_THEME_GRID_STEPS = (
        0, 100, 200, 300, 400, 500, 600,
        800, 1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800,
    )

    @classmethod
    def _web_theme_grid_ms(cls, relative_ms: int, duration_ms: int) -> int:
        """Snap to the entrance-dense grid; the tail maps onto exit samples."""
        duration_ms = max(1, int(duration_ms))
        grid = [step for step in cls._WEB_THEME_GRID_STEPS if step < duration_ms]
        exit_grid = [duration_ms - offset for offset in (600, 400, 250, 120, 40)]
        grid = sorted({max(0, min(duration_ms - 1, step)) for step in grid + exit_grid})
        value = max(0, min(duration_ms - 1, int(relative_ms)))
        return min(grid, key=lambda step: abs(step - value))

    @classmethod
    def _web_theme_grid_frames(cls, duration_ms: int) -> list[int]:
        duration_ms = max(1, int(duration_ms))
        grid = [step for step in cls._WEB_THEME_GRID_STEPS if step < duration_ms]
        exit_grid = [duration_ms - offset for offset in (600, 400, 250, 120, 40)]
        return sorted({max(0, min(duration_ms - 1, step)) for step in grid + exit_grid})

    def _fidelity_can_replace_live(self, snapshot) -> bool:
        from .style_recipe import MOTION_SOURCE_VISUAL_GRAPH, motion_source

        recipe = snapshot.style_recipe if isinstance(snapshot.style_recipe, Mapping) else {}
        if isinstance(recipe.get("webTheme"), Mapping) and recipe["webTheme"]:
            return False  # The LIVE browser page owns pause and playback.
        graph = recipe.get("visualGraph") if isinstance(recipe, Mapping) else {}
        source = motion_source(snapshot.motion_recipe, visual_graph=graph if isinstance(graph, Mapping) else {})
        if source == MOTION_SOURCE_VISUAL_GRAPH:
            return False  # Applied Graph Motion has one owner, including pause.
        return bool(
            not getattr(self, "_subtitle_transform_interactive", False)
            and (
                self.video.playback_position_snapshot().paused
                or motion_mode(snapshot.motion_recipe) == MOTION_MODE_NONE
            )
        )

    def _fidelity_stroke_parity_ok(self, fidelity_pixmap, snapshot) -> bool:
        """P8C-R3.1 C4: Fidelity must not degrade stroke correctness.

        Gates the foreground takeover on actual pixels: when the canonical
        snapshot requests a stroke (width > 0) and the LIVE frame really
        shows stroke-colored pixels, the Fidelity frame must show a
        comparable amount. A fully transparent / dropped stroke ring (the
        reported "3 秒后描边消失") fails parity and stays background —
        LIVE keeps the foreground. Serialized values alone are never
        trusted (C5).
        """
        self._fidelity_parity_drop_reason = ""
        try:
            strokes = [dict(item) for item in (getattr(snapshot, "strokes", ()) or []) if isinstance(item, dict)]
        except Exception:
            strokes = []
        expected = []
        for stroke in strokes:
            try:
                width = float(stroke.get("width") or 0)
            except (TypeError, ValueError):
                width = 0.0
            color_text = str(stroke.get("color") or "")
            if width > 0 and color_text:
                expected.append(color_text)
        if not expected:
            return True
        live_pixmap = getattr(self, '_advanced_cue_pixmap', None)
        if live_pixmap is None or live_pixmap.isNull():
            return True  # no LIVE baseline; do not block the takeover
        try:
            live_count = _count_stroke_pixels(live_pixmap, expected)
            fidelity_count = _count_stroke_pixels(fidelity_pixmap, expected)
        except Exception:
            return True
        min_baseline = 60
        if live_count < min_baseline:
            # LIVE baseline too small to judge (tiny/hidden stroke at this
            # preview size) — do not block on an unreadable baseline.
            return True
        if fidelity_count < max(24, int(live_count * 0.15)):
            self._fidelity_parity_drop_reason = (
                f"stroke_pixels live={live_count} fidelity={fidelity_count}"
            )
            self._studio_trace(
                "FIDELITY_STROKE_PARITY_DROP",
                cue_id=getattr(snapshot, "cue_id", ""),
                live_stroke_samples=live_count,
                fidelity_stroke_samples=fidelity_count,
            )
            return False
        return True

    def _fidelity_geometry_ok(self, fidelity_pixmap, snapshot) -> bool:
        """Reject fidelity frames whose occupied geometry cannot be this cue."""
        live_pixmap = getattr(self, "_advanced_cue_pixmap", None)
        live = _pixmap_alpha_metrics(live_pixmap)
        fidelity = _pixmap_alpha_metrics(fidelity_pixmap)
        if not live.get("bbox"):
            return True

        reason = ""
        live_alpha = int(live.get("alpha") or 0)
        fidelity_alpha = int(fidelity.get("alpha") or 0)
        live_coverage = float(live.get("coverage") or 0.0)
        fidelity_coverage = float(fidelity.get("coverage") or 0.0)
        live_occupancy = float(live.get("occupancy") or 0.0)
        fidelity_occupancy = float(fidelity.get("occupancy") or 0.0)
        if not fidelity.get("bbox") or fidelity_alpha < max(20, round(live_alpha * 0.18)):
            reason = f"alpha live={live_alpha} fidelity={fidelity_alpha}"
        elif fidelity_coverage > max(0.45, live_coverage * 4.0 + 0.03):
            reason = f"coverage live={live_coverage:.4f} fidelity={fidelity_coverage:.4f}"
        elif fidelity_occupancy < max(0.02, live_occupancy * 0.12):
            reason = f"occupancy live={live_occupancy:.4f} fidelity={fidelity_occupancy:.4f}"
        else:
            live_box = live["bbox"]
            fidelity_box = fidelity["bbox"]
            live_area = max(1, live_box[2] * live_box[3])
            fidelity_area = max(1, fidelity_box[2] * fidelity_box[3])
            area_ratio = fidelity_area / live_area
            canvas_width, canvas_height = fidelity.get("size") or (1, 1)
            live_center = (live_box[0] + live_box[2] / 2, live_box[1] + live_box[3] / 2)
            fidelity_center = (
                fidelity_box[0] + fidelity_box[2] / 2,
                fidelity_box[1] + fidelity_box[3] / 2,
            )
            center_delta = max(
                abs(live_center[0] - fidelity_center[0]) / max(1, canvas_width),
                abs(live_center[1] - fidelity_center[1]) / max(1, canvas_height),
            )
            if not 0.15 <= area_ratio <= 5.0:
                reason = f"bbox_area_ratio={area_ratio:.3f}"
            elif center_delta > 0.25:
                reason = f"bbox_center_delta={center_delta:.3f}"

        fill_colors = _canonical_fill_colors(getattr(snapshot, "fill", None))
        if not reason and fill_colors:
            live_fill = _count_stroke_pixels(live_pixmap, fill_colors)
            fidelity_fill = _count_stroke_pixels(fidelity_pixmap, fill_colors)
            if live_fill >= 40 and fidelity_fill < max(16, round(live_fill * 0.10)):
                reason = f"fill_pixels live={live_fill} fidelity={fidelity_fill}"
        if not reason:
            return True
        self._fidelity_parity_drop_reason = reason
        self._studio_trace(
            "FIDELITY_GEOMETRY_DROP",
            cue_id=getattr(snapshot, "cue_id", ""),
            reason=reason,
            live_bbox=live.get("bbox"),
            fidelity_bbox=fidelity.get("bbox"),
            live_alpha=live_alpha,
            fidelity_alpha=fidelity_alpha,
            live_coverage=round(live_coverage, 5),
            fidelity_coverage=round(fidelity_coverage, 5),
        )
        return False

    def _advanced_preview_failed(
        self, identity: AdvancedPreviewIdentity, generation: int, message: str,
    ) -> None:
        if self._advanced_preview_state.fail(identity, generation, message) and hasattr(self, "advanced_preview_image"):
            bind_text(self.advanced_preview_image, '预览不可用 · 使用 Studio 近似预览')
            self.advanced_preview_image.setToolTip(message)
            stale = getattr(self.advanced_cue_overlay, "_snapshot", None)
            has_stale = bool(
                stale is not None
                and stale.cue_id == identity.cue_id
                and not getattr(self.advanced_cue_overlay, "_source", QPixmap()).isNull()
            )
            (bind_text(self.advanced_style_status, '⚡ 高保真预览不可用 · 保留上个有效预览') if has_stale else bind_text(self.advanced_style_status, '⚡ 高保真预览不可用 · 已回退可读近似'))
            self._studio_trace("ASS_FALLBACK_SHOW", cue_id=identity.cue_id, reason="failed", error=message)
            self.ensure_active_subtitle_renderer(reason="advanced_failed")

    def _sync_advanced_cue_overlay(self) -> None:
        if not hasattr(self, "advanced_cue_overlay") or not hasattr(self, "position_overlay"):
            return
        content_rect = self.position_overlay._content_rect().toRect()
        if content_rect != self.advanced_cue_overlay._base_rect:
            self._studio_trace(
                "CANVAS_GEOMETRY_SYNC",
                content_rect=tuple(content_rect.getRect()),
                local_rect=tuple(content_rect.getRect()),
                video_rect=tuple(self.video.rect().getRect()),
                previous_base_rect=tuple(self.advanced_cue_overlay._base_rect.getRect()),
                previous_geometry=tuple(self.advanced_cue_overlay.geometry().getRect()),
                device_pixel_ratio=self.advanced_cue_overlay.devicePixelRatioF(),
            )
        self.advanced_cue_overlay.set_base_geometry(content_rect)
        # Geometry is not a visual revision. Rebinding the cached initial
        # composite here alternated it with the animated layer composite,
        # restarting the layer pipeline and reviving an old shadow/position.
        self.ensure_active_subtitle_renderer(reason="overlay_sync")

    def _selected_cue_is_at_playhead(self, cue: StudioCue | None) -> bool:
        if cue is None or not hasattr(self, "timeline"):
            return False
        sample=getattr(self,'_caption_sample_ms',None)
        playhead=sample() if callable(sample) else int(getattr(self.timeline, "playhead_ms", 0) or 0)
        return int(cue.start_ms) <= playhead < int(cue.end_ms)

    def _subtitle_live_interaction_owns(self, cue_id):
        return bool((getattr(self, "_subtitle_transform_interactive", False)
                     and cue_id == self.selected_cue_id)
                    or getattr(self, "_subtitle_transform_handoff_cue_id", "") == cue_id)

    def _renderer_cue_at_playhead(self) -> StudioCue | None:
        """Return the visual owner independently of editor selection."""
        timing = getattr(self, "_cue_timing_preview", None)
        if timing is not None and timing.active:
            return timing.cue_at_playhead()
        if not self.project or not hasattr(self, "timeline"):
            return None
        sample=getattr(self,'_caption_sample_ms',None)
        playhead=sample() if callable(sample) else int(getattr(self.timeline, "playhead_ms", 0) or 0)
        runtime = self.session.runtime
        candidates = list(runtime.cues_at(playhead)) if runtime else [
            cue for cue in self.project.cues
            if cue.start_ms <= playhead < cue.end_ms
        ]
        candidates = [
            cue for cue in candidates
            if self._subtitle_track_visibility.get(cue.speaker_id, True)
            and cue.speaker_id not in getattr(self.timeline, "hidden_speakers", set())
        ]
        selected = next(
            (cue for cue in candidates if cue.id == self.selected_cue_id), None,
        )
        if selected is not None:
            return selected
        return min(
            candidates,
            key=lambda cue: (abs(cue.start_ms - playhead), cue.end_ms - cue.start_ms),
            default=None,
        )

    def _subtitle_visibility_changed(self, speaker_id: str, visible: bool) -> None:
        """Make the timeline eye action the source for rendered subtitle visibility."""
        speaker_id = str(speaker_id or "")
        clear=getattr(self.video,'clear_caption_boundaries',None)
        if callable(clear):clear()
        self._subtitle_track_visibility[speaker_id] = bool(visible)
        if self.project is not None:
            state = self.project.studio_state.setdefault("subtitle_track_visibility", {})
            if isinstance(state, dict):
                state[speaker_id] = bool(visible)
        self._advanced_preview_state.generation += 1
        if not visible:
            self._revoke_advanced_preview(reason="subtitle_track_hidden")
            self.video.set_native_subtitle_visible(False)
            if hasattr(self, "position_overlay"):
                self.position_overlay.hide()
        # Recompile the Native ASS view with the track's cues removed (or
        # restored). This keeps per-track visibility independent from mpv's
        # global sub-visibility property and prevents stale hidden events from
        # resurfacing after a later renderer route change.
        self._refresh_ass_preview()
        self.ensure_active_subtitle_renderer(reason="subtitle_visibility")
        if visible:
            self._activate_selected_advanced_if_needed(force=True)
        if hasattr(self, "timeline"):
            self.timeline.update()

    @measured('activate_renderer')
    @caption_sample_transaction
    def _activate_selected_advanced_if_needed(self, *, force: bool = False) -> None:
        if self._present_caption_scene():
            return
        cue = self._renderer_cue_at_playhead()
        sample=getattr(self,'_caption_sample_ms',None)
        playhead_ms=sample() if callable(sample) else int(getattr(getattr(self, "timeline", None), "playhead_ms", 0) or 0)
        audio_cue_inside = bool(
            cue is not None and int(cue.start_ms) <= playhead_ms < int(cue.end_ms)
        )
        payload = self.project.style_recipes.get(cue.style_id, {}) if self.project and cue else {}
        canonical_advanced = bool(
            isinstance(payload, Mapping)
            and payload
            and self._caption_is_advanced(cue, payload)
        )
        compositor_promotion = bool(
            cue
            and (getattr(self, "_multitrack_composition_active", False)
                 or self._subtitle_live_interaction_owns(cue.id))
            and not canonical_advanced
        )
        audio_only_promotion = bool(
            cue
            and getattr(self, "_audio_only_subtitle_active", False)
            and not canonical_advanced
        )
        active = bool(
            cue
            and self.isVisible()
            and not getattr(self, "_empty_playback_state", False)
            and (
                self._selected_cue_is_at_playhead(cue)
                or (audio_only_promotion and audio_cue_inside)
            )
            and (canonical_advanced or compositor_promotion or audio_only_promotion)
        )
        if not active:
            self._advanced_active_cue_id = ""
            return
        if force or self._advanced_active_cue_id != cue.id:
            self._advanced_active_cue_id = cue.id
            self._schedule_advanced_preview(
                payload or {"name": "Multi-track subtitle foreground", "engine": "native"},
                force=force,
                queue_fidelity=canonical_advanced,
            )
            self._studio_trace(
                "MULTITRACK_SUBTITLE_PROMOTION",
                cue_id=cue.id,
                active=compositor_promotion or audio_only_promotion,
                audio_only=audio_only_promotion,
                canonical_route="advanced" if canonical_advanced else "native",
            )
            upcoming = self._upcoming_advanced_cue_ids(cue.id) if canonical_advanced else []
            if upcoming:
                QTimer.singleShot(
                    0,
                    lambda cue_ids=upcoming: self._queue_advanced_prefetch(cue_ids),
                )
                QTimer.singleShot(
                    0,
                    lambda cue_ids=[cue.id, *upcoming]: self._queue_live_layer_prefetch(cue_ids),
                )

    def _queue_live_layer_prefetch(self, cue_ids: list[str]) -> None:
        """Pre-rasterize LIVE layers for the current + next advanced cues.

        The first play of a complex cue may pay a short background cost; the
        goal is that by the time playback reaches each upcoming cue its layer
        rasters are already in the bbox-local cache. A cache miss never blocks
        or changes rendering — activation still falls back to the normal
        asynchronous layer pipeline.
        """
        project = self.project
        overlay = getattr(self, "advanced_cue_overlay", None)
        if not cue_ids or project is None or overlay is None:
            return
        width, height, dpr = getattr(overlay, "_layer_render_geometry", (0, 0, 1.0))
        if width < 1 or height < 1:
            return
        pending: list[tuple[str, object]] = []
        for cue_id in cue_ids:
            cue = self._cue_lookup.get(cue_id)
            payload = project.style_recipes.get(cue.style_id) if cue else None
            if isinstance(payload, Mapping) and payload.get('webTheme'):
                # Qt layer prefetch cannot warm Chromium themes. It formerly
                # started a new unrelated raster thread at every web cue.
                continue
            if not (cue and payload and route_recipe(payload).engine == "remotion"):
                continue
            snapshot = self._prepared_caption_snapshot(cue.id,width,height)
            if snapshot is None: continue
            key = live_layer_cache_key(
                snapshot, width=width, height=height, device_pixel_ratio=dpr,
            )
            if key in self._live_layer_prefetch_keys or GLOBAL_LIVE_LAYER_CACHE.contains(key):
                continue
            self._live_layer_prefetch_keys.add(key)
            pending.append((key, snapshot))
        if not pending or self._live_layer_prefetch_running:
            return
        if len(self._live_layer_prefetch_keys) > 64:
            self._live_layer_prefetch_keys.clear()
        self._live_layer_prefetch_running = True

        def work() -> None:
            try:
                for key, snapshot in pending:
                    if self._close_requested or GLOBAL_LIVE_LAYER_CACHE.contains(key):
                        continue
                    try:
                        with self._advanced_render_lock:
                            layers = render_live_layers(
                                snapshot,
                                width=width,
                                height=height,
                                device_pixel_ratio=dpr,
                            )
                            GLOBAL_LIVE_LAYER_CACHE.store(key, layers)
                    except (RuntimeError, TypeError, ValueError):
                        continue
                    self._studio_trace(
                        "LIVE_LAYER_PREFETCH_DONE",
                        cue_id=str(getattr(snapshot, "cue_id", "") or ""),
                        cache_stats=GLOBAL_LIVE_LAYER_CACHE.stats(),
                    )
            finally:
                self._live_layer_prefetch_running = False

        threading.Thread(target=work, daemon=True, name="advanced-live-prefetch").start()

    def _active_window_belongs_to_studio(self) -> bool:
        app = QApplication.instance()
        if app is not None and app.applicationState() != Qt.ApplicationState.ApplicationActive:
            return False
        active = QApplication.activeWindow()
        if active is None or active is self.window():
            return True
        current = active
        while current is not None:
            if current is self.window():
                return True
            current = current.parentWidget()
        return False

    def _cue_list_has_focus(self) -> bool:
        table = getattr(self, "cue_table", None)
        focus = QApplication.focusWidget()
        return bool(
            table is not None
            and focus is not None
            and (focus is table or table.isAncestorOf(focus))
        )

    @measured('ensure_renderer')
    @caption_sample_transaction
    def ensure_active_subtitle_renderer(self, *, reason: str = "sync") -> dict[str, object]:
        """Commit exactly one foreground owner without creating a new window."""
        if self._present_caption_scene():
            return self.subtitle_visibility_trace(reason=reason)
        timing = getattr(self, "_cue_timing_preview", None)
        if timing is not None and timing.active:
            return timing.present()
        cue = self._renderer_cue_at_playhead()
        payload = (
            recipe_payload_for_style(self.project.style_recipes, cue.style_id)
            if self.project and cue else {}
        ) or {}
        advanced = bool(
            isinstance(payload, Mapping)
            and payload
            and self._caption_is_advanced(cue, payload)
        )
        cue_inside = self._selected_cue_is_at_playhead(cue)
        sample=getattr(self,'_caption_sample_ms',None)
        playhead_ms=sample() if callable(sample) else int(getattr(getattr(self,"timeline",None),'playhead_ms',0) or 0)
        audio_cue_inside = bool(
            cue is not None and int(cue.start_ms) <= playhead_ms < int(cue.end_ms)
        )
        compositor_promotion = bool(
            cue
            and cue_inside
            and (getattr(self, "_multitrack_composition_active", False)
                 or self._subtitle_live_interaction_owns(cue.id))
            and not advanced
        )
        audio_only_promotion = bool(
            cue
            and audio_cue_inside
            and getattr(self, "_audio_only_subtitle_active", False)
            and not advanced
        )
        page_ready = bool(
            self.project
            and self.isVisible()
            and not getattr(self, "_empty_playback_state", False)
        )
        canvas = getattr(self, "advanced_cue_overlay", None)
        # A new video overlay or an audio-only gap can change ownership while
        # the cue stays selected. Ensure it has a matching foreground raster.
        if (
            (audio_only_promotion or compositor_promotion)
            and canvas is not None
            and getattr(getattr(canvas, "_snapshot", None), "cue_id", "") != cue.id
        ):
            self._advanced_active_cue_id = cue.id
            self._schedule_advanced_preview(
                payload or {"name": "Audio-only subtitle foreground", "engine": "native"},
                force=False,
                queue_fidelity=False,
            )
        live_snapshot = getattr(canvas, "_snapshot", None) if canvas is not None else None
        # Resolve once for this tick. Nested recipes are mutable, so a cache
        # retained across ticks could conceal an appearance edit.
        live_snapshot_hash = self._caption_snapshot_hash(live_snapshot) if live_snapshot is not None else ""
        source = getattr(canvas, "_source", QPixmap()) if canvas is not None else QPixmap()
        identity = self._advanced_preview_state.identity
        # 2026-09-02（十六轮）：已发布的 fidelity 帧通过了 generation 校验，
        # 不能因为后台又排了一个新 identity（学习词提交/补水合会改快照
        # hash）就把仍在画布上的真身帧判成"无像素"而隐藏——旧帧继续显示，
        # 新帧就绪后自然替换。
        fidelity_on_canvas = (
            getattr(self, "_advanced_canvas_source_kind", "") == "fidelity"
            and str(getattr(self, "_advanced_fidelity_request_key", "")) != ""
        )
        current_snapshot = bool(
            live_snapshot is not None
            and (
                identity is None
                or fidelity_on_canvas
                or (getattr(self,'_advanced_canvas_source_kind','')=='web_live'
                    and live_snapshot is getattr(self,'_web_live_snapshot',None)
                    and getattr(self,'_web_live_published_cue','')==getattr(cue,'id',None))
                or live_snapshot_hash == identity.snapshot_hash
            )
        )
        canvas_has_pixels = bool(
            canvas is not None
            and live_snapshot is not None
            and cue is not None
            and live_snapshot.cue_id == cue.id
            and current_snapshot
            and not source.isNull()
            and not canvas._base_rect.isEmpty()
            and (not payload.get('webTheme') or (
                getattr(self,'_advanced_canvas_source_kind','') in {'web_live','fidelity'}
                and live_snapshot.style_recipe.get('webTheme')))
        )
        canvas_should_show = bool(
            (advanced or compositor_promotion or audio_only_promotion)
            and (cue_inside or audio_only_promotion)
            and page_ready
            and canvas_has_pixels
        )
        desired_owner = VisualOwner.NONE
        snapshot_hash = ""
        request_key = ""
        if canvas_should_show:
            desired_owner = (
                VisualOwner.ADVANCED_FIDELITY
                if advanced and self._advanced_canvas_source_kind == "fidelity"
                else VisualOwner.ADVANCED_LIVE
            )
            snapshot_hash = live_snapshot_hash
            request_key = identity.request_key if identity is not None else ""
        elif (
            cue is not None
            # 二十八轮修复：native 恢复以"播头确实在该 cue 内"为准（audio_cue_inside，
            # 与选择无关），不能用 cue_inside（选中 cue 在播头）——用户点过 web cue 后
            # 手动选择锁生效、播放跟随不再抢选择，web cue 放完后选择仍钉在旧 cue 上，
            # cue_inside=False → desired_owner=NONE → 每个位置 tick 都重复
            # set_native_subtitle_visible(False)，衔接的下一条普通字幕被压成不可见
            # （用户实测"特效字幕结束后下一条普通字幕直接消失"）。
            and (audio_cue_inside or audio_only_promotion)
            and page_ready
            # Until authored pixels are ready, leave this cue hidden. A native
            # stand-in is visibly a different subtitle even for a single frame.
            and not advanced
            and not audio_only_promotion
        ):
            desired_owner = VisualOwner.NATIVE

        previous_owner, current_owner = self._visual_ownership.commit(
            desired_owner,
            cue_id=cue.id if desired_owner != VisualOwner.NONE and cue is not None else "",
            snapshot_hash=snapshot_hash,
            request_key=request_key,
        )
        # libass already evaluates its timed events against media PTS. A GUI
        # gap must not suppress it one frame early or restore it one frame
        # late; an empty native event interval naturally contains no pixels.
        native_should_show = desired_owner == VisualOwner.NATIVE or (
            desired_owner==VisualOwner.NONE and cue is None and page_ready
            and bool(getattr(self.video,'_native_subtitle_visible',False)))
        if not native_should_show:
            self.video.set_native_subtitle_visible(False)
        if canvas is not None:
            canvas_was_visible = canvas.isVisible()
            canvas.set_overlay_lifecycle_context(
                reason=reason,
                cue_active=bool(cue is not None and audio_cue_inside and page_ready
                                and live_snapshot is not None and live_snapshot.cue_id == cue.id
                                and (advanced or compositor_promotion or audio_only_promotion)),
            )
            canvas.setVisible(canvas_should_show)
            if canvas_should_show:
                canvas.raise_()
                if (
                    identity is not None
                    and live_snapshot_hash == identity.snapshot_hash
                ):
                    self._advanced_preview_state.mark_visible(identity)
                    if not canvas_was_visible:
                        self._studio_trace(
                            "ADVANCED_READY",
                            cue_id=cue.id,
                            request_key=identity.request_key,
                        )
                if not canvas_was_visible:
                    self._studio_trace("CANVAS_SHOW", cue_id=cue.id, reason=reason)
            elif canvas_was_visible:
                self._studio_trace(
                    "CANVAS_HIDE",
                    cue_id=getattr(live_snapshot, "cue_id", ""),
                    reason=reason,
                )
        if native_should_show:
            # Overlay ID 0 is removed by hideEvent before libass is restored,
            # so a route swap cannot expose two complete foreground layers.
            self.video.set_native_subtitle_visible(True)

        self._advanced_visual_owner_cue_id = (
            current_owner.cue_id
            if current_owner.owner in {
                VisualOwner.ADVANCED_LIVE,
                VisualOwner.ADVANCED_FIDELITY,
            }
            else ""
        )
        transform = getattr(self, "position_overlay", None)
        transform_should_show = bool(
            transform is not None
            and getattr(self, "export_workspace", None) is None
            and page_ready
            and cue_inside
            and bool(self.selected_cue_id) and cue is not None and cue.id == self.selected_cue_id
            and bool(getattr(self.video, "_paused", True))
            and getattr(self, "position_edit_button", None) is not None
            and self.position_edit_button.isChecked()
            and getattr(self, "_canvas_editor", None) is None
        )
        if transform is not None:
            transform.setVisible(transform_should_show)
            if transform_should_show:
                transform.sync_to_video(self.video)
                if not hasattr(self,'_selection_geometry'):
                    from .selection_geometry import SelectionGeometryController
                    self._selection_geometry=SelectionGeometryController(self)
                self._selection_geometry.sync(cue,payload)
                # Required stack: mpv -> Advanced -> interaction overlay.
                transform.raise_()
                transform._schedule_compositor_publish()

        if previous_owner is not current_owner:
            self._studio_trace(
                "RENDERER_OWNER_CHANGED",
                previous=previous_owner.owner.value,
                current=current_owner.owner.value,
                previous_cue=previous_owner.cue_id,
                current_cue=current_owner.cue_id,
                snapshot_hash=current_owner.snapshot_hash,
                request_key=current_owner.request_key,
                foreground_owner_count=current_owner.foreground_owner_count,
                advanced_overlay_id=(
                    self.video.ADVANCED_OVERLAY_ID
                    if current_owner.owner in {
                        VisualOwner.ADVANCED_LIVE,
                        VisualOwner.ADVANCED_FIDELITY,
                    }
                    else None
                ),
                reason=reason,
            )
        trace = self.subtitle_visibility_trace(reason=reason)
        self._last_subtitle_visibility_trace = trace
        signature = (
            trace["cue_id"],
            trace["visible"],
            trace["renderer_route"],
            trace["native_overlay_visible"],
            trace["native_track_visible"],
            trace["native_track_observed_visible"],
            trace["advanced_canvas_visible"],
            trace["foreground_owner"],
            trace["foreground_owner_count"],
            trace["transform_visible"],
            tuple(trace["advanced_geometry"]),
            tuple(trace["transform_geometry"]),
        )
        if signature != self._last_visibility_trace_signature:
            self._last_visibility_trace_signature = signature
            self._studio_trace("SUBTITLE_VISIBILITY", **trace)
        return trace

    def subtitle_visibility_trace(self, *, reason: str = "manual") -> dict[str, object]:
        cue = self._renderer_cue_at_playhead() if self.project else None
        playhead = int(getattr(getattr(self, "timeline", None), "playhead_ms", 0) or 0)
        payload = (
            recipe_payload_for_style(self.project.style_recipes, cue.style_id)
            if self.project and cue else {}
        )
        route = "native"
        if isinstance(payload, Mapping) and payload:
            route = 'remotion' if self._caption_is_advanced(cue, payload) else 'native'
        audio_cue_inside = bool(
            cue is not None and int(cue.start_ms) <= playhead < int(cue.end_ms)
        )
        compositor_promotion = bool(
            cue
            and self._selected_cue_is_at_playhead(cue)
            and (getattr(self, "_multitrack_composition_active", False)
                 or self._subtitle_live_interaction_owns(cue.id))
            and route != "remotion"
        )
        audio_only_promotion = bool(
            cue
            and audio_cue_inside
            and getattr(self, "_audio_only_subtitle_active", False)
            and route != "remotion"
        )
        canvas = getattr(self, "advanced_cue_overlay", None)
        transform = getattr(self, "position_overlay", None)
        if not self._widget_alive(canvas):
            canvas = None
        if not self._widget_alive(transform):
            transform = None
        opacity_effect = getattr(canvas, "_opacity", None) if canvas is not None else None
        preview_path = getattr(self, "_preview_path", None)
        ass_event_count = self._visibility_trace_ass_event_count
        current_ass_path = str(preview_path or "")
        ass_path_changed = current_ass_path != self._visibility_trace_ass_path
        if ass_path_changed:
            self._visibility_trace_ass_path = current_ass_path
            ass_event_count = 0
        if ass_path_changed and current_ass_path and Path(current_ass_path).is_file():
            try:
                ass_event_count = sum(
                    1
                    for line in Path(preview_path).read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                    if line.startswith("Dialogue:")
                )
            except OSError:
                ass_event_count = 0
            self._visibility_trace_ass_event_count = ass_event_count
        live_snapshot = getattr(canvas, "_snapshot", None) if canvas is not None else None
        recipe_id = ""
        if isinstance(payload, Mapping):
            recipe_id = str(payload.get("id") or payload.get("name") or "")
        cue_inside = self._selected_cue_is_at_playhead(cue)
        ownership = self._visual_ownership.current
        compositor_overlays = (
            self.video.active_compositor_overlay_ids()
            if hasattr(self.video, "active_compositor_overlay_ids")
            else []
        )
        controller = self.video.controller
        applied_visual_state = (
            controller.applied_visual_state()
            if controller is not None
            and hasattr(controller, "applied_visual_state")
            else {}
        )
        result = {
            "reason": str(reason),
            "cue_id": cue.id if cue else "",
            "start_ms": int(cue.start_ms) if cue else 0,
            "end_ms": int(cue.end_ms) if cue else 0,
            "playhead_ms": playhead,
            "enabled": bool(cue),
            "visible": bool(
                cue and (cue_inside or audio_only_promotion) and ownership.cue_id == cue.id
                and ownership.foreground_owner_count == 1
            ),
            "style_id": cue.style_id if cue else "",
            "preset_id": cue.style_id if cue else "",
            "recipe_id": recipe_id,
            "renderer_route": (
                "advanced"
                if route == "remotion" or compositor_promotion or audio_only_promotion
                else "native"
            ),
            "canonical_renderer_route": "advanced" if route == "remotion" else "native",
            "multitrack_foreground_promotion": compositor_promotion,
            "audio_only_subtitle_promotion": audio_only_promotion,
            "foreground_owner": ownership.owner.value,
            "foreground_owner_cue_id": ownership.cue_id,
            "foreground_owner_count": ownership.foreground_owner_count,
            "foreground_snapshot_hash": ownership.snapshot_hash,
            "foreground_request_key": ownership.request_key,
            "ass_event_count": ass_event_count,
            "advanced_snapshot_count": int(live_snapshot is not None),
            "native_cue_suppressed": bool(
                cue
                and (
                    (route == "remotion" and cue.id in self._advanced_ass_hidden)
                    or compositor_promotion
                    or audio_only_promotion
                )
            ),
            "native_overlay_visible": bool(
                cue and cue_inside and ownership.owner == VisualOwner.NATIVE
            ),
            "native_track_visible": bool(
                getattr(self.video, "_native_subtitle_visible", False)
            ),
            "native_track_observed_visible": (
                getattr(
                    controller, "observed_property", lambda *_args: None
                )("sub-visibility", None)
                if controller is not None
                else None
            ),
            "mpv_applied_visual_state": applied_visual_state,
            "advanced_canvas_visible": bool(canvas and canvas.isVisible()),
            "advanced_live_visible": ownership.owner == VisualOwner.ADVANCED_LIVE,
            "advanced_fidelity_visible": ownership.owner == VisualOwner.ADVANCED_FIDELITY,
            "transform_visible": bool(transform and transform.isVisible()),
            "advanced_opacity": float(opacity_effect.opacity()) if opacity_effect is not None else 0.0,
            "advanced_geometry": list(canvas.geometry().getRect()) if canvas is not None else [0, 0, 0, 0],
            "transform_geometry": list(transform.geometry().getRect()) if transform is not None else [0, 0, 0, 0],
            "advanced_is_window": bool(canvas and canvas.isWindow()),
            "transform_is_window": bool(transform and transform.isWindow()),
            "transform_native": bool(
                transform
                and transform.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            ),
            "mpv_compositor_overlay_ids": compositor_overlays,
            "video_device_pixel_ratio": float(self.video.devicePixelRatioF()),
            "z_order": "mpv V1 < bitmap V2+ < subtitle foreground < transform",
        }
        scene = getattr(self, '_caption_scene', None)
        if getattr(scene, 'active', False):
            result.update(scene.trace())
            result['renderer_route'] = 'advanced'
            result['foreground_owner_cue_id'] = ownership.cue_id
        return result
