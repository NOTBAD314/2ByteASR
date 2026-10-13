"""mpv video canvas widget with compositor overlay publishing."""

from __future__ import annotations

import copy
import hashlib
import os
import sys
import queue
import threading
import math
import time
import traceback
import uuid
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QElapsedTimer, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QFrame, QSizePolicy

from .media_time import MediaTimeMapping
from .playback_clock import PlaybackClock, PlaybackPositionSnapshot, backward_replay_windows
from .runtime_trace import GLOBAL_STUDIO_TRACE
from .studio_mpv import (
    MpvController, MpvUnavailableError, create_preview_controller, VIDEO_OVERLAY_ID, ADVANCED_OVERLAY_ID,
    TRANSFORM_OVERLAY_ID, VIDEO_TRANSFORM_OVERLAY_ID,
)
from .studio_project import studio_data_root

# 二十七轮：web-live 发布线程的重活半成品（解码+ARGB32+bbox）。放
# live_web_preview 是因为帧格式契约在那里定义；无循环依赖。
from .live_web_preview import _decode_frame  # noqa: E402  (import order: const before class)

from .i18n import bind_text

# Snapshot sources of an ordinary running/idle clock (not seeks or rebinds).
_STEADY_CLOCK_SOURCES = frozenset(
    {"heartbeat", "visual_tick", "cached_video_frame", "audio_engine_clock"})

class MpvCanvas(QFrame):
    VIDEO_OVERLAY_ID = VIDEO_OVERLAY_ID
    ADVANCED_OVERLAY_ID = ADVANCED_OVERLAY_ID
    TRANSFORM_OVERLAY_ID = TRANSFORM_OVERLAY_ID
    VIDEO_TRANSFORM_OVERLAY_ID = VIDEO_TRANSFORM_OVERLAY_ID
    position_changed = Signal(float)
    playback_state_changed = Signal(bool)
    video_display_size_changed = Signal(int, int)
    error = Signal(str)
    workshop_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("videoSurface")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, sys.platform != 'darwin')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.controller: MpvController | None = None
        self._media_path = ""
        self._media_attached = False
        self._clock_only = False
        self._ass_path = ""
        self._subtitle_load_attempts = 0
        self._base_time = 0.0
        self._playback_rate = 1.0
        self._source_rate_multiplier = 1.0
        self._paused = True
        self._duration = 0.0
        self._duration_override = 0.0
        self._video_display_size = (0, 0)
        self._eof_reached = False
        self._pending_seek_target: float | None = None
        self._pending_seek_deadline = 0.0
        self._playback_clock = PlaybackClock()
        self._media_time_mapping = MediaTimeMapping()
        self._media_has_video = True
        self._last_mpv_time_pos_ms: float | None = None
        self._last_audio_pts_ms: float | None = None
        self._last_video_frame_pts_ms: float | None = None
        self._project_time_mapping_enabled = False
        self._project_timeline_in_ms = 0
        self._project_source_in_ms = 0
        self._project_playback_rate = 1.0
        self._fallback_observation_sequence = 0
        self._active_seek_trace: dict[str, object] | None = None
        self._seek_trace_history: deque[dict[str, object]] = deque(maxlen=512)
        self._position_trace_samples: deque[float] = deque(maxlen=96)
        self._position_trace_last_loop_key: tuple[int, int] | None = None
        self._position_trace_last_loop_at = 0.0
        self._position_mutation_logged_at = 0.0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._tick_clock = QElapsedTimer()
        self._tick_clock.start()
        self._last_visual_tick_ns = 0
        self._update_intervals_ms: list[float] = []
        self._dropped_visual_frames = 0
        self._compositor_overlay_slots: dict[int, int] = {}
        self._active_compositor_overlays: set[int] = set()
        self._compositor_overlay_contexts: dict[int, dict[str, object]] = {}
        # 二十七轮：web-live 30fps 发布通道——GUI 只算几何，裁剪/写盘/投递在
        # 专用线程（最新帧获胜；epoch 在 overlay 移除时递增作废在途帧）。
        self._web_fast_queue: "queue.Queue[object]" = queue.Queue()
        self._web_live_epoch = 0
        self._web_last_decoded = None
        self.web_publication_metrics = deque(maxlen=600)
        self.web_initial_publication_metrics = deque(maxlen=256)
        self._web_pixel_buffers = {}
        # 双轨轮：视频叠加层（1440p 全幅位图）走同样的异步通道——GUI 线程
        # 每帧同步写 ~14MB 再投递曾是心跳 p95 40ms+ 的主因之一。
        self._video_fast_queue: "queue.Queue[object]" = queue.Queue()
        self._video_overlay_epoch = 0
        self._video_upload_samples = deque(maxlen=24000)
        self._video_overlay_thread: threading.Thread | None = None
        # 二十八轮：会话门——exit 清场（canvas hideEvent → REMOVE ovl=0）后、
        # worker 退出前，回放泵仍会吐迟到帧；epoch 已 bump 但迟到帧带**新**
        # epoch 入队照样复活 overlay → libass 恢复被消抖循环无限押后（用户
        # 实测"特效字放完，下一条普通字幕直接消失"）。REMOVE 关会话、
        # 首帧 begin 重开，迟到帧一律拒发。
        self._web_live_overlay_active = False
        self._web_overlay_thread: threading.Thread | None = None
        self._overlay_file_lock = threading.RLock()
        self._subtitle_raster_publisher = None
        self._native_subtitle_visible = True
        self._native_subtitle_visibility_controller = None
        self._external_clock_provider = None
        self.playback_prepare = None
        self.playback_ready = None
        self._buffered_play_pending = False
        # Internal pause while a seek during playback waits for its audio.
        self._seek_hold_active = False
        self._seek_hold_entering = False
        self._seek_hold_token = 0
        self._embed_hwnd = 0
        self._buffered_play_timer = QTimer(self)
        self._buffered_play_timer.setInterval(10)
        self._buffered_play_timer.timeout.connect(lambda: self.set_paused(False))
        self._external_clock_sequence = -1
        self._external_clock_enabled = False
        self._external_clock_source_generation = -1
        self._startup_state = "READY"
        self._startup_play_requested = False
        self._startup_started_at = 0.0
        # Playback truth contract: the mpv media clock is the only playback
        # truth. When its transport dies (process exit or wedged IPC) the
        # canvas enters an explicit dead state instead of letting the local
        # paused/position mirrors keep advertising "Playing".
        self._playback_source_dead = False
        self._last_hwdec_snapshot: dict[str, object] = {}
        self._compositor_overlay_dir = studio_data_root() / "mpv-overlays" / uuid.uuid4().hex
        from .overlay_session import ensure_overlay_session
        ensure_overlay_session(self._compositor_overlay_dir)
        self._sync_overlay_busy = set()
        self._sync_overlay_identity = {}
        self._sync_overlay_generation = {}
        self._media_cache_leases = {}
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._visual_tick)
        self._sync_timer = QTimer(self)
        self._sync_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._sync_timer.setInterval(150)
        self._sync_timer.timeout.connect(self._reconcile_position)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # 十八轮：双击视频层 = 打开 AI 字幕工坊（播头处是特效字幕时）。
        self.workshop_requested.emit("")
        super().mouseDoubleClickEvent(event)

    @property
    def playback_source_dead(self) -> bool:
        return bool(self._playback_source_dead)

    def playback_health(self, *, reason: str = "") -> dict[str, object]:
        """Consolidated lifecycle diagnostics for one playback moment."""
        controller = self.controller
        actor_status = (
            controller.actor_status() if callable(getattr(controller, "actor_status", None)) else {}
        )
        observed = (
            controller.observed_properties()
            if callable(getattr(controller, "observed_properties", None)) else {}
        )
        clock = self._playback_clock.snapshot()
        return {
            "reason": str(reason),
            "requested_paused": bool(self._paused),
            "source_dead": bool(self._playback_source_dead),
            "clock_generation": int(clock.playback_generation),
            "clock_position_ms": round(float(clock.presentation_media_ms), 3),
            "clock_paused": bool(clock.paused),
            "clock_source": str(clock.source),
            "media_attached": bool(self._media_attached),
            "media_path": str(self._media_path or ""),
            "startup_state": str(self._startup_state),
            "external_clock": self._external_clock_active(),
            "mpv_running": bool(getattr(controller, "running", False)),
            "mpv_pause": observed.get("pause"),
            "mpv_time_pos": observed.get("time-pos"),
            "mpv_core_idle": observed.get("core-idle"),
            "mpv_eof_reached": observed.get("eof-reached"),
            "mpv_idle_active": observed.get("idle-active"),
            "mpv_path": observed.get("path"),
            "actor": actor_status,
        }

    def _enter_playback_source_dead(self, reason: str) -> None:
        """Adopt the dead-transport truth: stop pretending to play."""
        if self._playback_source_dead:
            return
        self._playback_source_dead = True
        self._timer.stop()
        self._sync_timer.stop()
        health = self.playback_health(reason=reason)
        page = self._studio_page()
        if page is not None:
            page._studio_trace("PLAYBACK_SOURCE_DEAD", **health)
        snapshot = self._playback_clock.force_position(
            self._base_time * 1000.0,
            paused=True,
            reason="playback_source_dead",
        )
        self._adopt_playback_snapshot(snapshot)
        self.error.emit("预览播放器已停止（画面/声音不可用）。点击播放按钮可恢复。")

    def _ensure_controller_started(self) -> None:
        """Start the mpv child, replacing one that died while Studio idled."""
        if self.controller is not None and self.controller.running:
            return
        if self.controller is not None:
            try:
                self.controller.close()
            except OSError:
                pass
            self.controller = None
        self.controller = create_preview_controller(self)
        log_path = studio_data_root() / "logs" / "mpv.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Qt's Mac child surface needs no native handle. winId() itself
        # promotes the canvas (and ancestors) to native windows, changing
        # the widget stack that owns decoded video and caption overlays.
        window_id = 0 if getattr(self.controller, 'backend', '') == 'qt-video-sink' else int(self.winId())
        # Plain int for the stall watchdog's native probe (no Qt off-thread).
        self._embed_hwnd = int(window_id)
        self.controller.start(window_id, log_path=str(log_path))
        self._native_subtitle_visibility_controller = None
        self._playback_source_dead = False

    def _trace_compositor_event(
        self, action: str, overlay_id: int,
        context: Mapping[str, object] | None = None,
    ) -> None:
        page = self._studio_page()
        trace = getattr(page, "_studio_trace", None)
        if not callable(trace):
            return
        fields = {**dict(context or {}), **{
            "action": str(action),
            "operation": "PUBLISH" if action in {"CREATE", "UPDATE"} else action,
            "overlay_id": int(overlay_id), "time_monotonic": time.monotonic(),
            "paused": bool(self._paused), "playing": not bool(self._paused),
        }}
        trace("COMPOSITOR_OVERLAY_LIFECYCLE", **fields)

    def _ensure_web_overlay_publisher(self) -> None:
        if self._web_overlay_thread is not None and self._web_overlay_thread.is_alive():
            return
        self._web_overlay_thread = threading.Thread(
            target=self._web_overlay_loop,
            daemon=True,
            name="web-live-overlay-publisher",
        )
        self._web_overlay_thread.start()

    def _web_overlay_loop(self) -> None:
        """web-live 帧发布线程：解码 → bbox → 裁剪 → 双缓冲写盘 → mpv 投递。

        二十七轮终版：worker 只发原始 PNG 字节，解码（~15ms）也下沉到这里
        ——在 worker 发射路径上同步解码曾把周期拖到 47ms≈22fps。
        """
        last_frames = {}
        while True:
            item = self._web_fast_queue.get()
            if item is None:
                for buffer in self._web_pixel_buffers.values():
                    buffer.close()
                self._web_pixel_buffers.clear()
                return
            epoch, overlay_id, payload, full_rect, context = item
            if epoch != self._web_live_epoch:
                continue  # overlay 已被移除/重建：在途帧作废
            controller = self.controller
            if controller is None or not controller.running:
                continue
            try:
                started=perf_counter()
                frame_identity = (epoch, self._sync_overlay_generation.get(overlay_id, 0), hashlib.sha256(payload).digest(), full_rect.getRect(),
                    tuple(context.get(k) for k in ('cue_id','web_worker_id','web_content_key','web_generation','web_clock_generation')))
                if last_frames.get(overlay_id) == frame_identity:
                    continue
                decoded = _decode_frame(payload)
                if decoded is None:
                    continue
                image, bounds = decoded
                decoded_at=perf_counter()
                if epoch != self._web_live_epoch:continue
                self._web_last_decoded=(epoch,image)
                if bounds is None:
                    # A transparent entrance/exit frame replaces the old bitmap.
                    # Keep the page lease active while clearing its pixels.
                    bounds=QRect(0,0,1,1)
                if full_rect is None or full_rect.isEmpty():
                    continue
                cropped = image if bounds == image.rect() else image.copy(bounds)
                if cropped.isNull():
                    continue
                if cropped.format() != QImage.Format.Format_ARGB32_Premultiplied:
                    cropped = cropped.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                # 全帧显示矩形按裁剪比例映射到子矩形（纯 QRect 数学，无线程
                # 依赖）。
                scale_x = full_rect.width() / max(1, image.width())
                scale_y = full_rect.height() / max(1, image.height())
                display_rect = QRect(
                    round(full_rect.x() + bounds.x() * scale_x),
                    round(full_rect.y() + bounds.y() * scale_y),
                    max(1, round(bounds.width() * scale_x)),
                    max(1, round(bounds.height() * scale_y)),
                )
                if display_rect.isEmpty():
                    continue
                cropped_at=perf_counter()
                acknowledged=threading.Event()
                applied_state={}
                def applied(ok,state=applied_state,done=acknowledged):
                    state['ok']=ok
                    state['at']=perf_counter()
                    done.set()
                with self._overlay_file_lock:
                    if epoch != self._web_live_epoch:continue
                    locked_at=perf_counter()
                    slot = 1 - self._compositor_overlay_slots.get(overlay_id, 1)
                    from .overlay_buffer import OverlayBuffer
                    path = self._compositor_overlay_dir / f"web-overlay-{overlay_id}-{slot}.rgba"
                    pixels = cropped.constBits()
                    buffer = self._web_pixel_buffers.get((overlay_id, slot))
                    if buffer is None or buffer.capacity < len(pixels):
                        self._compositor_overlay_dir.mkdir(parents=True, exist_ok=True)
                        if buffer is not None:
                            buffer.close()
                        buffer = self._web_pixel_buffers[(overlay_id, slot)] = OverlayBuffer(path, len(pixels))
                    allocated_at=perf_counter()
                    buffer.write(pixels)
                    written_at=perf_counter()
                    posted = controller.post_raw_overlay(
                        overlay_id, path,
                        cue_id=context.get('cue_id',''),
                        valid_when=lambda epoch=epoch:epoch==self._web_live_epoch,
                        on_applied=applied,
                        coalesce_key=f"web-overlay:{overlay_id}",
                        x=display_rect.x(), y=display_rect.y(),
                        width=cropped.width(), height=cropped.height(),
                        stride=cropped.bytesPerLine(),
                        display_width=display_rect.width(),
                        display_height=display_rect.height(),
                    )
                    if posted:
                        self._compositor_overlay_slots[overlay_id] = slot
                        self._active_compositor_overlays.add(overlay_id)
                        self._compositor_overlay_contexts[overlay_id] = context
                # The publisher, never Qt, waits for mpv's acknowledgement.
                # Reusing a ring file before mpv reads it can show mixed frames.
                while posted and not acknowledged.wait(.005) and controller.running:
                    pass  # invalid epochs still retain their pixels until ACK
                if applied_state.get('ok') and epoch == self._web_live_epoch:
                    last_frames[overlay_id] = frame_identity
                self.web_publication_metrics.append({**context,'wall':perf_counter(),'epoch':epoch,
                    'applied_at':applied_state.get('at'),
                    'queue_ms':(started-float(context.get('received_perf',started)))*1000,
                    'decode_ms':(decoded_at-started)*1000,'crop_copy_ms':(cropped_at-decoded_at)*1000,
                    'write_ms':(written_at-cropped_at)*1000,
                    'lock_wait_ms':(locked_at-cropped_at)*1000,
                    'allocate_ms':(allocated_at-locked_at)*1000,
                    'mmap_write_ms':(written_at-allocated_at)*1000,
                    'upload_ack_ms':(applied_state.get('at',perf_counter())-written_at)*1000,
                    'applied':applied_state.get('ok',False),'pixels':[cropped.width(),cropped.height()]})
            except (OSError, RuntimeError, ValueError):
                continue

    def _ensure_video_overlay_publisher(self) -> None:
        if self._video_overlay_thread is not None and self._video_overlay_thread.is_alive():
            return
        self._video_overlay_thread = threading.Thread(
            target=self._video_overlay_publisher_run,
            daemon=True,
            name="studio-video-overlay-publisher",
        )
        self._video_overlay_thread.start()

    def queue_video_raster(self, image, display_rect, context):
        """Thread-safe input; geometry and publisher are prepared by the GUI."""
        if not self._media_attached or self.controller is None:return
        epoch=context.get('publication_epoch')
        if epoch is None or epoch!=self._video_overlay_epoch:return
        while self._video_fast_queue.qsize() >= 1:
            try:self._video_fast_queue.get_nowait()
            except queue.Empty:break
        self._video_fast_queue.put((int(epoch),VIDEO_OVERLAY_ID,image,
                                    display_rect,context))

    def _video_overlay_publisher_run(self) -> None:
        """Write one overlay raster + post it per job, newest frame wins.

        Slot rotation stays inside this single consumer, so a queued frame can
        never overwrite the file mpv is still reading.
        """
        self._compositor_overlay_dir.mkdir(parents=True, exist_ok=True)
        from .overlay_buffer import OverlayBuffer
        buffers = {}
        last_frames = {}
        while True:
            item = self._video_fast_queue.get()
            if item is None:
                for buffer in buffers.values():
                    buffer.close()
                return
            epoch, overlay_id, image, display_rect, context = item
            if epoch != self._video_overlay_epoch:
                continue  # overlay 已被移除/隐藏：在途帧作废
            controller = self.controller
            if controller is None or not controller.running or image.isNull():
                continue
            try:
                started = perf_counter()
                frame_identity = (epoch, self._sync_overlay_generation.get(overlay_id, 0), image.cacheKey(), display_rect.getRect())
                if last_frames.get(overlay_id) == frame_identity:
                    continue
                acknowledged = threading.Event()
                outcome = {}
                def applied(ok, state=outcome, done=acknowledged):
                    state.update(ok=bool(ok), at=perf_counter())
                    done.set()
                with self._overlay_file_lock:
                    slot = 1 - self._compositor_overlay_slots.get(overlay_id, 1)
                    path = self._compositor_overlay_dir / f"overlay-{overlay_id}-{slot}.rgba"
                    pixels = image.constBits()
                    buffer = buffers.get((overlay_id, slot))
                    if buffer is None or buffer.capacity < len(pixels):
                        if buffer is not None:
                            buffer.close()
                        buffer = buffers[(overlay_id, slot)] = OverlayBuffer(path, len(pixels))
                    buffer.write(pixels)
                    written = perf_counter()
                    posted = controller.post_raw_overlay(
                        overlay_id, path,
                        valid_when=lambda epoch=epoch: epoch == self._video_overlay_epoch,
                        on_applied=applied,
                        on_started=lambda state=outcome:state.update(command_started=perf_counter()),
                        x=display_rect.x(), y=display_rect.y(),
                        width=image.width(), height=image.height(),
                        stride=image.bytesPerLine(),
                        display_width=display_rect.width(),
                        display_height=display_rect.height(),
                    )
                # Do not rotate back onto a file still being read by mpv.
                # Waiting belongs to this publisher, never the GUI. The input
                # queue remains bounded/latest-wins while an actor is busy.
                while posted and not acknowledged.wait(.005) and controller.running:
                    pass
                self._video_upload_samples.append(dict(**context, overlay_id=overlay_id,
                    epoch=epoch, started=started, write_ms=(written-started)*1000,
                    applied_at=outcome.get('at'), accepted=outcome.get('ok',False),
                    actor_queue_ms=(outcome['command_started']-written)*1000 if 'command_started' in outcome else None,
                    ipc_ack_ms=(outcome['at']-outcome['command_started'])*1000 if 'command_started' in outcome and 'at' in outcome else None,
                    total_ms=(perf_counter()-started)*1000, queue_frames=self._video_fast_queue.qsize()))
                if posted and outcome.get('ok') and epoch == self._video_overlay_epoch:
                    last_frames[overlay_id] = frame_identity
                    self._compositor_overlay_slots[overlay_id] = slot
                    self._active_compositor_overlays.add(overlay_id)
                    self._compositor_overlay_contexts[overlay_id] = context
            except (OSError, RuntimeError, ValueError):
                continue

    def begin_web_live_overlays(self) -> None:
        """开启一个 web-live overlay 会话：作废上一会话在途帧。"""
        self._web_live_epoch += 1
        self._web_last_decoded = None
        self._web_live_overlay_active = True

    def stop_web_live_overlays(self) -> None:
        """结束 web-live overlay 会话：清队列并拒绝后续快速发布。"""
        self._web_live_epoch += 1
        self._web_live_overlay_active = False
        try:
            while True:
                self._web_fast_queue.get_nowait()
        except queue.Empty:
            pass

    def publish_web_live_overlay(
        self,
        overlay_id: int,
        payload: bytes,
        full_rect: QRect,
        *,
        context: Mapping[str, object] | None = None,
    ) -> bool:
        """二十七轮：web-live 30fps 发布通道。

        旧路径每帧在 GUI 线程做 ~6 次全画布拷贝 + 3.7MB 同步写盘
        （≈30-60ms/帧，用户实测视频层 ~10fps 一卡一卡）。本通道 GUI 线程
        只算全帧几何；解码/裁剪/写盘/投递全部在发布线程；队列最新帧获胜。
        """
        if not payload:
            return False
        if full_rect is None or full_rect.isEmpty():
            return False
        if not self._web_live_overlay_active:
            return False  # 会话已关（清场/停泵后的迟到帧）——不得复活 overlay
        controller = self.controller
        if not controller or not controller.running:
            return False
        self._ensure_web_overlay_publisher()
        item = (
            int(self._web_live_epoch), int(overlay_id), bytes(payload),
            QRect(full_rect), {**dict(context or {}),'received_perf':perf_counter()},
        )
        # 最新帧获胜：丢掉尚未处理的旧帧（视频层只要最新状态）。
        try:
            while True:
                self._web_fast_queue.get_nowait()
        except queue.Empty:
            pass
        self._web_fast_queue.put(item)
        return True

    def clear_caption_boundaries(self):
        controller=self.controller
        boundary=getattr(controller,'_caption_boundary_publisher',None)
        if boundary is not None:boundary.close();controller._caption_boundary_publisher=None

    def register_caption_boundary(self,token,snapshot,pixels,target_rect,frame_rate=None):
        controller=self.controller
        if not controller or not controller.running or not self._media_attached:return
        from .caption_boundary_publisher import CaptionBoundaryPublisher,BoundaryPixels
        boundary=getattr(controller,'_caption_boundary_publisher',None)
        if boundary is None:
            boundary=controller._caption_boundary_publisher=CaptionBoundaryPublisher(controller,self.ADVANCED_OVERLAY_ID,frame_rate)
            if not hasattr(self,'_caption_boundary_metrics'):self._caption_boundary_metrics=[]
            boundary.metrics=self._caption_boundary_metrics
        raw=pixels.raw_geometry;bx,by,bw,bh=raw['bounds'];dpr=max(1.,float(self.devicePixelRatioF()))
        x,y,w,h=[round(value*dpr) for value in target_rect.getRect()]
        geometry=dict(x=round(x+bx*w/raw['source_width']),y=round(y+by*h/raw['source_height']),
            width=raw['width'],height=raw['height'],stride=raw['stride'],
            display_width=max(1,round(bw*w/raw['source_width'])),display_height=max(1,round(bh*h/raw['source_height'])))
        boundary.register(token,BoundaryPixels(snapshot.cue_id,snapshot.start_ms,snapshot.end_ms,pixels,geometry))

    def publish_compositor_overlay(
        self,
        overlay_id: int,
        source: QPixmap | QImage,
        target_rect: QRect,
        *,
        opacity: float = 1.0,
        source_bounds: QRect | None = None,
        phase: str = "",
        context: Mapping[str, object] | None = None,
        prepared_pixels=None,
    ) -> bool:
        """Mirror a Qt-owned visual into mpv without creating another HWND."""
        scene = getattr(self._studio_page(), '_caption_scene', None)
        if (getattr(scene, 'active', False) and int(overlay_id) == self.ADVANCED_OVERLAY_ID
                and (context or {}).get('caller') != 'CaptionScene'):
            return False
        if not self.controller or not self.controller.running or target_rect.isEmpty():
            return False
        boundary=getattr(self.controller,'_caption_boundary_publisher',None)
        cue_id=(context or {}).get('cue_id','')
        if int(overlay_id)==int(self.ADVANCED_OVERLAY_ID) and boundary is not None and cue_id and not boundary.allows(cue_id):
            return False
        # 四十三轮：媒体已卸载（换工程/回主页）后到达的迟到帧一律拒收——
        # 否则旧工程的字幕/特效 overlay 会被重新 add 回 mpv，钉死在新工程
        # 的视频层上（用户实录"上一个工程的字幕一直卡在上面"）。新工程
        # attach 媒体后 _media_attached 回 True，正常发布不受影响。
        if not (self._media_attached or self._clock_only):
            page = self._studio_page()
            trace = getattr(page, "_studio_trace", None)
            if callable(trace):
                trace(
                    "COMPOSITOR_PUBLISH_REJECTED_MEDIA_DETACHED",
                    overlay_id=int(overlay_id),
                    caller=str((context or {}).get("caller", "")),
                )
            return False
        image = source.toImage() if isinstance(source, QPixmap) else QImage(source)
        if image.isNull():
            self.remove_compositor_overlay(overlay_id, context=context)
            return False
        if prepared_pixels is not None and prepared_pixels.raw_path is not None and callable(getattr(self.controller,'post_raw_overlay',None)):
            # The cropped premultiplied bytes are already on disk. Do not put
            # a ready boundary through another raster/crop/write worker.
            if self._subtitle_raster_publisher is not None:self._subtitle_raster_publisher.revoke(int(overlay_id))
            geometry=prepared_pixels.raw_geometry;bx,by,bw,bh=geometry['bounds']
            dpr=max(1.,float(self.devicePixelRatioF()))
            target=QRect(round(target_rect.x()*dpr),round(target_rect.y()*dpr),round(target_rect.width()*dpr),round(target_rect.height()*dpr))
            display=QRect(round(target.x()+bx*target.width()/geometry['source_width']),round(target.y()+by*target.height()/geometry['source_height']),
                max(1,round(bw*target.width()/geometry['source_width'])),max(1,round(bh*target.height()/geometry['source_height'])))
            epoch=self._web_live_epoch;posted_at=perf_counter();cue_id=(context or {}).get('cue_id','')
            metrics=getattr(self,'_prepared_caption_publications',None)
            if metrics is None:metrics=self._prepared_caption_publications=[]
            def applied(ok,keep=prepared_pixels):
                metrics.append(dict(cue_id=cue_id,prepared_at=keep.finished,posted_at=posted_at,applied_at=perf_counter(),
                    applied=bool(ok),alpha_nonzero=keep.raw_geometry['alpha_nonzero'],
                    scene_token=(context or {}).get('scene_token')))
                del metrics[:-128]
            posted=self.controller.post_raw_overlay(int(overlay_id),prepared_pixels.raw_path,
                cue_id=cue_id,
                x=display.x(),y=display.y(),width=geometry['width'],height=geometry['height'],stride=geometry['stride'],
                display_width=display.width(),display_height=display.height(),on_applied=applied,
                valid_when=lambda epoch=epoch:epoch==self._web_live_epoch and (self._media_attached or self._clock_only)
                    and ((context or {}).get('caller')!='CaptionScene' or scene.still_current((context or {}).get('scene_token'))),
                coalesce_key=f'caption-prepared:{overlay_id}')
            if posted:
                action='UPDATE' if int(overlay_id) in self._active_compositor_overlays else 'CREATE'
                self._active_compositor_overlays.add(int(overlay_id))
                self._compositor_overlay_contexts[int(overlay_id)]=dict(context or {})
                self._trace_compositor_event(action,int(overlay_id),context)
                return True
        if (int(overlay_id)==int(self.ADVANCED_OVERLAY_ID) and not self._paused
                and (context or {}).get('web_worker_id') is None
                and str((context or {}).get('caller','')).startswith('AdvancedLiveCanvas.')
                and float(opacity)>.001 and callable(getattr(self.controller,'post_raw_overlay',None))):
            # Native cue changes used to hold the video's file lock for a
            # synchronous 10–70ms disk write. This channel owns separate files.
            if self._subtitle_raster_publisher is None:
                from .subtitle_raster_publisher import SubtitleRasterPublisher
                self._subtitle_raster_publisher=SubtitleRasterPublisher(self._compositor_overlay_dir)
            dpr=max(1.,float(self.devicePixelRatioF()))
            rect=QRect(round(target_rect.x()*dpr),round(target_rect.y()*dpr),round(target_rect.width()*dpr),round(target_rect.height()*dpr))
            posted=self._subtitle_raster_publisher.submit(int(overlay_id),image,rect,max(0,min(1,float(opacity))),self.controller,cue_id=(context or {}).get('cue_id',''))
            if posted:
                self._active_compositor_overlays.add(int(overlay_id))
                self._compositor_overlay_contexts[int(overlay_id)]=dict(context or {})
            return posted
        if int(overlay_id)==int(self.ADVANCED_OVERLAY_ID) and self._subtitle_raster_publisher is not None:
            self._subtitle_raster_publisher.revoke(int(overlay_id))
        # mpv requires premultiplied BGRA (also Qt's native raster format).
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        clamped_opacity = max(0.0, min(1.0, float(opacity)))
        if clamped_opacity <= 0.001:
            if str(phase or "").upper() == "AFTER_CUE":
                self.remove_compositor_overlay(overlay_id, context={
                    **dict(context or {}), "cue_active": False, "reason": "AFTER_CUE"})
                return False
            page = self._studio_page()
            trace = getattr(page, "_studio_trace", None)
            if callable(trace):
                trace(
                    "COMPOSITOR_TRANSPARENT_FRAME",
                    overlay_id=int(overlay_id),
                    retained=bool(int(overlay_id) in self._active_compositor_overlays),
                    opacity=clamped_opacity,
                    phase=str(phase or ""),
                )
            return False
        if clamped_opacity < 0.999:
            faded = QImage(image.size(), QImage.Format.Format_ARGB32)
            faded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(faded)
            painter.setOpacity(clamped_opacity)
            painter.drawImage(0, 0, image)
            painter.end()
            image = faded

        # Crop transparent margins in C++ before writing the raw bridge file.
        # Advanced frames are normally 1280x720 but only the subtitle/card is
        # opaque, so this keeps drag and motion updates small.
        pixmap = QPixmap.fromImage(image)
        bounds = (
            QRect(source_bounds).intersected(image.rect())
            if source_bounds is not None and not source_bounds.isEmpty()
            else image.rect() if not pixmap.hasAlphaChannel()
            else QRegion(pixmap.mask()).boundingRect().intersected(
                image.rect()
            )
        )
        if bounds.isEmpty():
            if str(phase or "").upper() == "AFTER_CUE":
                self.remove_compositor_overlay(overlay_id, context={
                    **dict(context or {}), "cue_active": False, "reason": "AFTER_CUE"})
                return False
            # A transparent animation frame is a legal intermediate state.
            # Retain the last acknowledged mpv overlay until the owner hides
            # the canvas at AFTER_CUE; deleting it here turns one empty frame
            # into a permanent subtitle disappearance.
            page = self._studio_page()
            trace = getattr(page, "_studio_trace", None)
            if callable(trace):
                trace(
                    "COMPOSITOR_TRANSPARENT_FRAME",
                    overlay_id=int(overlay_id),
                    retained=bool(int(overlay_id) in self._active_compositor_overlays),
                )
            return False
        # Full video rasters are already premultiplied and exactly bounded.
        # Keep their implicit buffer instead of cloning it twice per frame.
        cropped = (image if bounds == image.rect() else image.copy(bounds)).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        scale_x = target_rect.width() / max(1, image.width())
        scale_y = target_rect.height() / max(1, image.height())
        display_rect = QRect(
            round(target_rect.x() + bounds.x() * scale_x),
            round(target_rect.y() + bounds.y() * scale_y),
            max(1, round(bounds.width() * scale_x)),
            max(1, round(bounds.height() * scale_y)),
        )
        # QWidget geometry is device-independent; mpv overlay-add addresses
        # the physical D3D output plane. This conversion is essential at
        # 125/150/175/200% Windows scaling.
        dpr = max(1.0, float(self.devicePixelRatioF()))
        display_rect = QRect(
            round(display_rect.x() * dpr),
            round(display_rect.y() * dpr),
            max(1, round(display_rect.width() * dpr)),
            max(1, round(display_rect.height() * dpr)),
        )
        if (
            str((context or {}).get("caller", "")) == "video_compositor"
            and os.environ.get("TWOBYTEASR_SYNC_OVERLAY_PUBLISH") != "1"
            and self.controller is not None
            and self.controller.running
            and callable(getattr(self.controller, "post_raw_overlay", None))
        ):
            # 双轨轮：大位图视频层的写盘+投递全部下沉到专用线程；GUI 只做
            # 上面的几何计算与门控。队列深度封顶 2（丢旧帧），mpv 端由 actor
            # 的 overlay:{id} 合并键保序。字幕/特效 overlay 与测试宿主保持同步。
            while self._video_fast_queue.qsize() >= 2:
                try:
                    self._video_fast_queue.get_nowait()
                except queue.Empty:
                    break
            self._ensure_video_overlay_publisher()
            self._video_fast_queue.put((
                int(self._video_overlay_epoch), int(overlay_id), cropped,
                QRect(display_rect), dict(context or {}),
            ))
            return True
        if not getattr(self, "_compositor_directory_ready", False):
            self._compositor_overlay_dir.mkdir(parents=True, exist_ok=True)
            self._compositor_directory_ready = True
        with self._overlay_file_lock:
            geometry = {
                "x": display_rect.x(), "y": display_rect.y(),
                "width": cropped.width(), "height": cropped.height(),
                "stride": cropped.bytesPerLine(),
                "display_width": display_rect.width(), "display_height": display_rect.height(),
            }
            generation = self._sync_overlay_generation.get(int(overlay_id), 0)
            identity = (generation, hashlib.sha256(cropped.constBits()).digest(), tuple(geometry.values()),
                        (context or {}).get('cue_id'), self._web_live_epoch, self._video_overlay_epoch)
            if self._sync_overlay_identity.get(int(overlay_id)) == identity:
                return True
            slots = [slot for slot in (0, 1) if (int(overlay_id), slot) not in self._sync_overlay_busy]
            if not slots:
                # Two immutable submissions are already waiting for reads.
                # Do not overwrite either; the next visual tick retries.
                return False
            slot = slots[0]
            # The video publisher retains mmap-backed overlay-N-S files.
            # A gap/offline synchronous frame must not truncate those files:
            # Windows rejects it with EINVAL while the mapping is alive.
            path = self._compositor_overlay_dir / f"overlay-{int(overlay_id)}-sync-{slot}.rgba"
            path.write_bytes(cropped.constBits())
            from .overlay_session import lease_overlay_deferred
            lease = lease_overlay_deferred(path, 'mpv_sync_overlay')
            self._sync_overlay_busy.add((int(overlay_id), slot))
            released = threading.Event()
            def consumed(ok, oid=int(overlay_id), buffer_slot=slot, target=path, held=lease, frame_identity=identity, gen=generation):
                with self._overlay_file_lock:
                    if released.is_set():
                        return
                    released.set()
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        pass
                    self._sync_overlay_busy.discard((oid, buffer_slot))
                    if ok and gen == self._sync_overlay_generation.get(oid, 0):
                        self._sync_overlay_identity[oid] = frame_identity
                try:
                    held.__exit__(None, None, None)
                except Exception:
                    pass
            try:
                post = getattr(self.controller, "post_raw_overlay", None)
                web_context = dict(context or {}) if (context or {}).get('web_worker_id') is not None else None
                extra = {'on_applied': consumed}
                if (context or {}).get('cue_id'):extra['cue_id']=context['cue_id']
                if web_context is not None:
                    epoch = self._web_live_epoch
                    def web_applied(ok, immutable_context=web_context, web_epoch=epoch):
                        consumed(ok)
                        self.web_initial_publication_metrics.append({**immutable_context,
                            'epoch':web_epoch,'applied':bool(ok),'applied_at':perf_counter(),
                            'channel':'initial_native_overlay'})
                    extra.update(on_applied=web_applied,valid_when=lambda epoch=epoch:epoch==self._web_live_epoch)
                if not callable(post) or not post(int(overlay_id), path, **geometry, **extra):
                    # An asynchronous rejection has already completed its
                    # callback and released the file; never send it again.
                    if callable(post):
                        consumed(False)
                        return False
                    self.controller.set_raw_overlay(int(overlay_id), path, **geometry)
                    if web_context is not None:
                        web_applied(True)
                    else:
                        consumed(True)
            except (OSError, RuntimeError):
                consumed(False)
                return False
        overlay_id = int(overlay_id)
        action = "UPDATE" if overlay_id in self._active_compositor_overlays else "CREATE"
        self._compositor_overlay_slots[overlay_id] = slot
        self._active_compositor_overlays.add(overlay_id)
        self._compositor_overlay_contexts[overlay_id] = dict(context or {})
        self._trace_compositor_event(action, overlay_id, context)
        return True

    def remove_compositor_overlay(
        self, overlay_id: int, *, context: Mapping[str, object] | None = None,
        force: bool = False,
    ) -> bool:
        overlay_id = int(overlay_id)
        scene = getattr(self._studio_page(), '_caption_scene', None)
        if (getattr(scene, 'active', False) and overlay_id == self.ADVANCED_OVERLAY_ID
                and (context or {}).get('caller') != 'CaptionScene' and not force):
            return False
        details = dict(self._compositor_overlay_contexts.get(overlay_id, {}))
        details.update(dict(context or {}))
        illegal = bool(details.get("cue_active") and details.get("scene_alive")
                       and float(details.get("opacity") or 0.0) > 0.0)
        if illegal and not force:
            details["call_stack"] = "".join(traceback.format_stack(limit=12))
            self._trace_compositor_event("REMOVE_REJECTED", overlay_id, details)
            return False
        boundary=getattr(self.controller,'_caption_boundary_publisher',None)
        retired_by_boundary=bool(not force and boundary is not None and details.get('cue_id')
                                 and not boundary.allows(details['cue_id']))
        if (retired_by_boundary and self._compositor_overlay_contexts.get(overlay_id,{}).get('cue_id')
                != details.get('cue_id')):
            # A late hide for the old cue cannot retire a newer overlay owner.
            return False
        self._sync_overlay_identity.pop(overlay_id, None)
        self._sync_overlay_generation[overlay_id] = self._sync_overlay_generation.get(overlay_id, 0) + 1
        if self._subtitle_raster_publisher is not None:
            self._subtitle_raster_publisher.revoke(overlay_id)
        if overlay_id not in self._active_compositor_overlays and not force:
            return False
        # 二十七轮：作废 web-live 快速通道的在途帧（否则发布线程可能在 remove
        # 之后把旧帧重新 add 回 mpv——用户看到"已消失的特效字又闪回来"）。
        # The boundary thread already owns removal of an expired cue's native
        # pixels. Still retire its matching GUI bookkeeping, or the native
        # subtitle debounce believes the old layer exists forever.
        if overlay_id == int(self.ADVANCED_OVERLAY_ID):
            self._web_live_epoch += 1
            # 二十八轮：会话门——清场即关会话；迟到帧在 publish 入口被拒，
            # 直到下一次首帧 begin 重开。
            self._web_live_overlay_active = False
        if overlay_id in (int(self.VIDEO_OVERLAY_ID), int(self.VIDEO_TRANSFORM_OVERLAY_ID)):
            # 双轨轮：作废视频异步通道的在途帧（同 web-live 语义）。
            self._video_overlay_epoch += 1
        if self.controller and self.controller.running and not retired_by_boundary:
            try:
                post = getattr(self.controller, "post_remove_overlay", None)
                extra={'cue_id':details.get('cue_id')} if boundary is not None else {}
                if not callable(post) or not post(overlay_id,**extra):
                    self.controller.remove_overlay(overlay_id)
            except RuntimeError:
                pass
        self._active_compositor_overlays.discard(overlay_id)
        self._compositor_overlay_contexts.pop(overlay_id, None)
        self._trace_compositor_event("REMOVE", overlay_id, details)
        return True

    def active_compositor_overlay_ids(self) -> list[int]:
        return sorted(self._active_compositor_overlays)

    def set_native_subtitle_visible(self, visible: bool) -> None:
        """Apply owner-driven libass visibility without GUI-thread IPC."""
        if getattr(getattr(self._studio_page(), '_caption_scene', None), 'active', False):
            visible = False
        visible = bool(visible)
        controller = self.controller
        if (
            visible == self._native_subtitle_visible
            and controller is self._native_subtitle_visibility_controller
        ):
            return
        if visible and self.ADVANCED_OVERLAY_ID in self._active_compositor_overlays:
            # 十九轮（消抖）：字幕真身 overlay 仍在显示时，"恢复原生 ASS" 的
            # 请求极可能是 seek/路由双路径评估的瞬时抖动（mpv.log 实证每次
            # 切换 sub-visibility true→10-30ms→false，原生 ASS 闪一下又消失）。
            # 延迟重查：真恢复路径会先经 hideEvent 摘掉 overlay；抖动请求在
            # 窗口内被压制，用户看不到闪烁。
            self._native_subtitle_visible = visible
            timer = getattr(self, "_native_visible_debounce", None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(150)
                timer.timeout.connect(self._apply_deferred_native_visible)
                self._native_visible_debounce = timer
            timer.start()
            return
        timer = getattr(self, "_native_visible_debounce", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._native_subtitle_visible = visible
        if controller is None or not controller.running:
            self._native_subtitle_visibility_controller = None
            return
        post = getattr(controller, "post_set_subtitle_visible", None)
        if callable(post) and post(visible):
            self._native_subtitle_visibility_controller = controller
            return
        setter = getattr(controller, "set_subtitle_visible", None)
        if callable(setter):
            setter(visible)
            self._native_subtitle_visibility_controller = controller

    def _apply_deferred_native_visible(self) -> None:
        if not self._native_subtitle_visible:
            return
        if self.ADVANCED_OVERLAY_ID in self._active_compositor_overlays:
            # 真身 overlay 仍在——继续保持压制（后续真正恢复时会重走本入口）。
            self._native_visible_debounce.start()
            return
        self._native_subtitle_visible = False  # 让下方统一路径重新执行
        self.set_native_subtitle_visible(True)

    def load(self, media_path: str, ass_path: str = "", *, start_seconds: float | None = None) -> None:
        self._hold_media_cache(media_path)
        self._clock_only = False
        self._active_seek_trace = None
        self._media_path = media_path
        self._ass_path = ass_path
        self._video_display_size = (0, 0)
        try:
            self._ensure_controller_started()
            self._startup_play_requested = True
            self._startup_started_at = perf_counter()
            self._set_startup_state("MEDIA_OPENING")
            self.controller.set_paused(True)
            # Restore the clock before posting loadfile. Resetting it to zero
            # afterwards makes the initial media-graph binding seek back to
            # zero, while the saved timeline still selects its themed cue.
            # The LIVE worker then waits outside that cue and readiness stalls.
            self._set_interpolation_base(
                max(0.0, float(start_seconds or 0.0)),
                paused=True, reason="media_opening",
            )
            if start_seconds is None:
                self.controller.load(media_path)
            else:
                # One atomic loadfile-with-start. A separate seek posted
                # during mpv's asynchronous file initialization can be
                # rejected without any error reaching this side, silently
                # losing the restored playhead (post errors are fire-and-
                # forget on the actor).
                start_content = max(0.0, float(start_seconds))
                target = self._clamp_position(self._content_to_source_seconds(start_content))
                self._trace_seek(
                    "load_at_start", project_target_s=start_content,
                    mapped_media_target_s=target,
                )
                snapshot = self._playback_clock.begin_seek(int(start_content * 1000))
                self._adopt_playback_snapshot(snapshot, emit=False)
                if not self.controller.post_load_at(
                    media_path, target, generation=self._playback_clock.generation
                ):
                    self.controller.load(media_path)
            self._media_attached = True
            # 控制器跨 reload 存活且 loadfile 不重置 speed：把传输速率显式
            # 压回，防止旧 2x 残留（2026-09-18 P0 8x 根因）。
            post_speed = getattr(self.controller, "post_set_speed", None)
            transport_rate = self._decoder_speed(self._playback_rate)
            if callable(post_speed):
                post_speed(transport_rate)
            else:
                self.controller.set_speed(transport_rate)
            if ass_path and Path(ass_path).is_file():
                self._subtitle_load_attempts = 0
                self._load_subtitle_when_ready()
            self._timer.start()
            self._sync_timer.start()
            # Immediately attempt to publish real video display size (dw/dh) so the overlay
            # does not stay stuck on PlayRes fallback while the first reconcile is pending.
            QTimer.singleShot(80, self._emit_initial_video_size)
        except (MpvUnavailableError, RuntimeError, OSError) as exc:
            self.error.emit(str(exc))

    def switch_media_async(self, media_path: str, ass_path: str = "") -> bool:
        """Switch the resident mpv source through the actor without GUI IPC."""

        self._clock_only = False
        source = str(Path(media_path).absolute())
        self._hold_media_cache(source)
        self._media_path = source
        self._ass_path = str(ass_path or "")
        self._video_display_size = (0, 0)
        controller = self.controller
        if controller is None or not controller.running:
            return False
        post = getattr(controller, "post_load", None)
        if not callable(post) or not post(source):
            return False
        self._media_attached = True
        self._subtitle_load_attempts = 0
        if self._ass_path and Path(self._ass_path).is_file():
            self._load_subtitle_when_ready()
        self._timer.start()
        self._sync_timer.start()
        return True

    def switch_media_at_async(
        self,
        media_path: str,
        ass_path: str,
        *,
        source_seconds: float,
        project_ms: int,
    ) -> bool:
        """Atomically rebind mpv and seek while project time stays authoritative.

        2026-09-18（P0 8x 回归）：换绑必须迁移传输速度。mpv 控制器跨工程
        reload 存活，loadfile 新源后仍保留旧 speed（如识别前观看用的 2x），
        而重载后的传输层/UI 默认 1x——视频 2x、音频/字幕 1x、追随器风暴
        纠正=用户看到的"UI 1x 画面 8x"。每次换绑后把控制器速度显式压回
        本画布的传输速率。
        """
        self._clock_only = False
        controller = self.controller
        post = getattr(controller, "post_load_at", None)
        if controller is None or not controller.running or not callable(post):
            return False
        source = str(Path(media_path).absolute())
        self._hold_media_cache(source)
        target = max(0.0, float(source_seconds))
        display_seconds = max(0, int(project_ms)) / 1000.0
        trace = self._active_seek_trace
        if trace is None or abs(float(trace.get("target_seconds", -1.0)) - display_seconds) > 0.001:
            self.begin_seek_trace(display_seconds, source="media_rebind")
        if self._active_seek_trace is not None:
            self._active_seek_trace["decoder_target_seconds"] = target
            self._active_seek_trace['requested_project_ms'] = int(project_ms)
            self._tag_seek_project_domain(project_ms, target)
        self._trace_seek(
            "source_switch", project_target_s=display_seconds,
            mapped_media_target_s=target,
        )
        clock_ms = max(0, int(project_ms)) if self._project_time_mapping_enabled else target * 1000
        snapshot = self._playback_clock.begin_seek(clock_ms)
        self._eof_reached = False
        self._adopt_playback_snapshot(snapshot, emit=False)
        self.mark_seek_stage("T2_optimistic_playhead_visible")
        if not post(
            source,
            target,
            generation=self._playback_clock.generation,
        ):
            return False
        post_speed = getattr(controller, "post_set_speed", None)
        transport_rate = self._decoder_speed(self._playback_rate)
        if callable(post_speed):
            post_speed(transport_rate)
        else:
            controller.set_speed(transport_rate)
        self.mark_seek_stage("T3_seek_command_posted", accurate=True, media_rebind=True)
        self._media_path = source
        self._ass_path = str(ass_path or "")
        self._video_display_size = (0, 0)
        self._media_attached = True
        self._subtitle_load_attempts = 0
        if self._ass_path and Path(self._ass_path).is_file():
            self._load_subtitle_when_ready()
        self._timer.start()
        self._sync_timer.start()
        return True

    def suspend_media_async(self, *, reanchor: bool = True) -> bool:
        """Clear a gap/offline frame through the actor without blocking Qt."""

        controller = self.controller
        post = getattr(controller, "post_clear_media", None)
        if controller is None or not controller.running or not callable(post):
            return False
        if not post():
            return False
        self._media_attached = False
        self._subtitle_load_attempts = 0
        self._video_display_size = (0, 0)
        self._eof_reached = False
        self._timer.stop()
        self._sync_timer.stop()
        if reanchor:
            self._set_interpolation_base(self.visual_position(), paused=True)
        self.video_display_size_changed.emit(0, 0)
        return True

    def enter_timeline_gap(self, project_ms: int, duration_ms: int) -> None:
        """Keep the project clock and caption surface alive without a source."""
        if self._clock_only:
            return
        paused = self._paused and not self._buffered_play_pending
        self.clear_caption_boundaries()
        # Retire source observations before any Qt signal can reenter the page.
        # suspend_media_async used to publish the old 3092s source position after
        # the page had switched to project time, clamping a 458s edit to its tail.
        self._clock_only = True
        snapshot = self._playback_clock.begin_unattached_position(project_ms, paused=paused)
        self._buffered_play_pending = False
        self._buffered_play_timer.stop()
        self._duration = max(0, duration_ms) / 1000.0
        self._duration_override = self._duration
        self._adopt_playback_snapshot(snapshot, emit=False)
        self.suspend_media_async(reanchor=False)
        self._media_attached = False
        self._media_path = ''
        self._startup_state = 'READY'
        self._playback_source_dead = False
        self._eof_reached = False
        self.position_changed.emit(max(0, project_ms) / 1000.0)
        self._timer.start()

    def enter_empty_playback_state(self) -> None:
        """Clear the current frame/subtitles while preserving the mpv process."""
        self._clock_only = False
        # The observation-thread publisher writes directly to mpv, so its
        # last bitmap need not appear in the GUI's active-overlay registry.
        # Revoke producers first, then retire every reserved native slot.
        self.clear_caption_boundaries()
        self.stop_web_live_overlays()
        self._video_overlay_epoch += 1
        slots = set(self._active_compositor_overlays) | {
            self.VIDEO_OVERLAY_ID, self.ADVANCED_OVERLAY_ID,
            self.TRANSFORM_OVERLAY_ID, self.VIDEO_TRANSFORM_OVERLAY_ID,
        }
        for overlay_id in sorted(slots):
            self.remove_compositor_overlay(overlay_id, force=True)
        if self.controller and self.controller.running and self._media_attached:
            post = getattr(self.controller, "post_clear_media", None)
            if not callable(post) or not post():
                self.controller.clear_media()
        self._media_attached = False
        self._ass_path = ""
        self._subtitle_load_attempts = 0
        self._duration_override = 0.0
        self._duration = 0.0
        self._video_display_size = (0, 0)
        self._eof_reached = False
        self._timer.stop()
        self._sync_timer.stop()
        self._set_interpolation_base(0.0, paused=True)
        self._startup_state = "READY"
        self.video_display_size_changed.emit(0, 0)

    def unload_project_media(self) -> None:
        """Release project state while retaining the one reusable mpv actor."""
        self.set_external_clock_enabled(False)
        self.set_project_time_mapping(enabled=False)
        self.enter_empty_playback_state()
        self._media_path = ""
        self._ass_path = ""
        self._pending_seek_target = None
        self._pending_seek_deadline = 0.0
        self._project_timeline_in_ms = 0
        self._project_source_in_ms = 0
        self._project_playback_rate = 1.0
        self._media_time_mapping = MediaTimeMapping()
        self._source_rate_multiplier = 1.0
        self._media_has_video = True
        self._last_mpv_time_pos_ms = None
        self._last_audio_pts_ms = None
        self._last_video_frame_pts_ms = None
        self._active_seek_trace = None
        clock = PlaybackClock()
        # The mpv actor keeps its monotonic observation epoch across projects.
        # A fresh clock starting at 0 would never acknowledge the next seek
        # (generation mismatch), pinning the playhead to the seek target.
        if self.controller is not None:
            clock.advance_generation_to(self.controller.source_epoch)
        self._playback_clock = clock
        self._external_clock_sequence = -1
        self._external_clock_source_generation = -1
        self.position_changed.emit(0.0)
        self._release_media_caches_after_idle()

    def _hold_media_cache(self, path):
        """Keep every decoded project source protected through asynchronous switches."""
        key = str(Path(path).absolute())
        leases = getattr(self, '_media_cache_leases', None)
        if leases is None:
            leases = self._media_cache_leases = {}
        if key not in leases:
            from .storage_service import cache_lease
            lease = cache_lease(key); lease.__enter__()
            leases[key] = lease

    def _release_media_caches_after_idle(self):
        leases, self._media_cache_leases = getattr(self, '_media_cache_leases', {}), {}
        controller = self.controller
        def release():
            # A stop is asynchronous. Its ACK (or process termination) is the
            # point at which it is safe to remove the old file's lease.
            deadline = time.monotonic() + 5
            while controller is not None and controller.running:
                observe = getattr(controller, 'observed_properties', None)
                state = observe() if callable(observe) else {}
                if state.get('idle-active'):
                    break
                if time.monotonic() >= deadline:
                    # Keep unconfirmed leases; process death makes them stale.
                    self._media_cache_leases.update(leases)
                    return
                time.sleep(.02)
            for lease in leases.values():
                lease.__exit__(None, None, None)
        threading.Thread(target=release, name='media-cache-lease-release', daemon=True).start()

    def restore_after_empty(self, media_path: str, ass_path: str = "") -> None:
        """Reattach media to the existing mpv child; never starts a process."""
        self._media_path = str(media_path or self._media_path)
        self._ass_path = str(ass_path or "")
        if not self.controller or not self.controller.running:
            # A controller that died while the hub was open must be replaced,
            # otherwise the reopened project inherits a permanently dead one.
            try:
                self._ensure_controller_started()
            except (MpvUnavailableError, RuntimeError, OSError) as exc:
                self.error.emit(str(exc))
                return
        if not self._media_path:
            return
        if not self._media_attached:
            self.controller.load(self._media_path)
            self.controller.set_paused(True)
        self._media_attached = True
        self._set_interpolation_base(0.0, paused=True)
        if self._ass_path and Path(self._ass_path).is_file():
            self._subtitle_load_attempts = 0
            QTimer.singleShot(0, self._load_subtitle_when_ready)
        self._timer.start()
        self._sync_timer.start()

    def revive_dead_source(self, *, paused: bool) -> bool:
        """User-initiated recovery from PLAYBACK_SOURCE_DEAD.

        This is not a watchdog: nothing calls it automatically. The play
        button routes here so the human decides when to bring playback back.
        """
        if not self._playback_source_dead:
            return False
        if not self._media_path:
            self.error.emit("播放器恢复失败：当前工程没有已加载的媒体，请重新打开工程。")
            return False
        resume_seconds = self._base_time
        if self._duration > 0.0:
            resume_seconds = min(resume_seconds, self._duration)
        media_path = self._media_path
        ass_path = self._ass_path if self._ass_path and Path(self._ass_path).is_file() else ""
        try:
            self._ensure_controller_started()
            self.load(media_path, ass_path, start_seconds=max(0.0, resume_seconds))
            self.set_paused(bool(paused))
        except (MpvUnavailableError, RuntimeError, OSError) as exc:
            self.error.emit(f"播放器恢复失败：{exc}")
            return False
        return True

    def reload_subtitle(self, ass_path: str) -> None:
        self._ass_path = ass_path
        if self.controller and self.controller.running:
            self._subtitle_load_attempts = 0
            self._load_subtitle_when_ready()

    def set_external_clock_provider(self, provider, *, enabled: bool = False) -> None:
        """Bind an audio-only source clock without creating a second UI clock."""
        self._external_clock_provider = provider if callable(provider) else None
        self._external_clock_sequence = -1
        self._external_clock_source_generation = -1
        self._external_clock_enabled = bool(enabled and self._external_clock_provider)

    def set_media_time_mapping(
        self, mapping: Mapping[str, object] | MediaTimeMapping | None,
        *, has_video: bool = None,
    ) -> None:
        """Install the canonical source/stream timestamp contract for the media."""
        self._media_time_mapping = (
            mapping if isinstance(mapping, MediaTimeMapping)
            else MediaTimeMapping.from_metadata(mapping)
        )
        if has_video is not None:
            self._media_has_video = bool(has_video)

    def set_av_sync_map(self, sync_map) -> None:
        """Install the source-timestamp ↔ audio-content mapping (gappy FLVs).

        Identity/None restores exact legacy behaviour: the project timeline
        and mpv observations share one domain. With a real map the clock runs
        in audio-content time; mpv seeks and observations translate at this
        boundary only (user spec 2026-09-17 §1.6).
        """
        from .avsync import AVSyncMap
        self._av_sync_map = sync_map if isinstance(sync_map, AVSyncMap) else None
        applied = self._av_sync_map is not None and not self._av_sync_map.is_identity
        page = self._studio_page()
        if page is not None:
            page._studio_trace(
                "AV_SYNC_MAP_APPLIED", applied=bool(applied),
                total_gap_ms=(self._av_sync_map.total_gap_ms if applied else 0),
            )

    def _content_to_source_seconds(self, seconds: float) -> float:
        sync_map = getattr(self, "_av_sync_map", None)
        if sync_map is None or sync_map.is_identity:
            return float(seconds)
        return sync_map.content_to_source_ms(float(seconds) * 1000.0) / 1000.0

    def _source_to_content_ms(self, source_ms: float) -> float:
        sync_map = getattr(self, "_av_sync_map", None)
        if sync_map is None or sync_map.is_identity:
            return float(source_ms)
        return sync_map.source_to_content_ms(float(source_ms))

    def set_external_clock_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled and self._external_clock_provider)
        if enabled == self._external_clock_enabled:
            return
        self._external_clock_enabled = enabled
        self._external_clock_sequence = -1
        self._external_clock_source_generation = -1

    def _external_clock_active(self) -> bool:
        provider = self._external_clock_provider
        if not self._external_clock_enabled:
            return False
        if provider is None:
            return False
        try:
            payload = provider()
        except Exception:
            return False
        if not isinstance(payload, Mapping):
            return False
        state = str(payload.get("state") or "").upper()
        return bool(payload.get("source_path")) and state not in {
            "IDLE", "SILENT", "SHUTDOWN_BEGIN", "SHUTDOWN",
        }

    def _observe_external_clock(self) -> bool:
        """Adopt the latest AudioEngine sample into the sole PlaybackClock."""
        page = self._studio_page()
        if getattr(page, '_audio_tail_waiting', lambda:False)():
            return False  # old paused telemetry cannot undo a new play intent
        provider = self._external_clock_provider
        if not self._external_clock_enabled:
            return False
        if provider is None:
            return False
        try:
            payload = provider()
        except Exception:
            return False
        if not isinstance(payload, Mapping) or not payload.get("source_path"):
            return False
        state = str(payload.get("state") or "").upper()
        if state in {"IDLE", "SILENT", "SHUTDOWN_BEGIN", "SHUTDOWN"}:
            return False
        # Decoder/ring generations are private to the audio process. The
        # shared clock must acknowledge the transport seek epoch, not compare
        # an unrelated decoder counter with the user's seek generation.
        transport = payload.get('transport_generation') or ()
        if not transport or int(transport[0]) != self._playback_clock.generation:
            return False
        value = payload.get("estimated_source_ms")
        if value is None:
            return False
        try:
            sequence = int(payload.get("clock_sequence") or 0)
            observed_ms = float(value)
        except (TypeError, ValueError):
            return False
        if sequence <= self._external_clock_sequence:
            self._complete_external_clock_startup(payload)
            return False
        self._external_clock_sequence = sequence
        source_generation = int(payload.get("source_generation") or 0)
        # The two physical actors have independent sequence counters. Fence
        # audio telemetry above, then publish it in the shared clock's actor
        # sequence domain; a video EOF must not reject a lower audio counter.
        shared_sequence = max(sequence, self._playback_clock.snapshot().actor_sequence + 1)
        observed_at = float(payload.get("clock_monotonic_ts") or time.monotonic())
        paused = bool(payload.get("paused", self._paused))
        rate = float(payload.get("effective_rate") or self._playback_rate or 1.0)
        discontinuity = (
            source_generation != self._external_clock_source_generation
            or self._playback_clock.snapshot().source == "reset"
        )
        self._external_clock_source_generation = source_generation
        snapshot, accepted, _reason = self._playback_clock.observe(
            self._source_position_to_project_ms(observed_ms / 1000.0, content_domain=True),
            source_generation=int(transport[0]),
            actor_sequence=shared_sequence,
            observed_monotonic_ts=observed_at,
            playback_rate=rate,
            paused=paused,
            seeking=False,
            source="audio_engine_clock",
            discontinuity=discontinuity,
            presentation_media_ms=self.visual_position() * 1000.0,
        )
        if accepted:
            self._adopt_playback_snapshot(snapshot)
            self._complete_external_clock_startup(payload)
        return accepted

    def _complete_external_clock_startup(self, payload):
        if self._startup_state == 'READY' or self._playback_clock.exact_seek_pending:
            return
        page = self._studio_page()
        tail = getattr(page, '_owned_audio_tail', None)
        from .owned_audio_tail import held_video_frame_ready
        tail_frame_ready = held_video_frame_ready(tail,
            generation=self._playback_clock.generation, attached=self._media_attached,
            running=bool(self.controller is not None and self.controller.running),
            frame=getattr(self.controller, 'observed_position', lambda:{})(),
            properties=getattr(self.controller, 'observed_properties', lambda:{})())
        if (self._media_has_video and (not tail_frame_ready
                or not page._audio_tail_startup_caption_ready())):
            return
        if int(payload.get('decoded_bytes') or 0) <= 0:
            return
        play_requested = self._startup_play_requested
        self._set_startup_state('READY', media_clock_seconds=float(payload['estimated_source_ms'])/1000.)
        if play_requested:QTimer.singleShot(0, lambda:self.set_paused(False))

    def _emit_initial_video_size(self) -> None:
        """Push real video display size (dw/dh) to listeners as soon as it is known.
        Called shortly after load so the overlay can use actual letterboxed content rect
        instead of PlayRes before the first periodic reconcile tick.
        """
        if not self.controller or not self.controller.running:
            return
        if self._video_display_size != (0, 0):
            return
        try:
            observed = getattr(self.controller, "observed_property", None)
            params = observed("video-out-params", None) if callable(observed) else None
            if params is None:
                params = self.controller.get_property("video-out-params", {})
            params = params or {}
            if isinstance(params, dict):
                w = int(params.get("dw") or params.get("w") or 0)
                h = int(params.get("dh") or params.get("h") or 0)
                if w > 0 and h > 0:
                    self._video_display_size = (w, h)
                    self.video_display_size_changed.emit(w, h)
        except Exception:
            pass

    def _load_subtitle_when_ready(self) -> None:
        if not self._ass_path or not Path(self._ass_path).is_file():
            return
        if not self.controller or not self.controller.running:
            return
        try:
            post = getattr(self.controller, "post_subtitle_file", None)
            if not callable(post) or not post(self._ass_path):
                self.controller.set_subtitle_file(self._ass_path)
        except RuntimeError as exc:
            self.error.emit(str(exc))

    def _set_interpolation_base(
        self,
        seconds: float,
        *,
        paused: bool | None = None,
        rate: float | None = None,
        reason: str = "explicit_discontinuity",
    ) -> None:
        next_base = self._clamp_position(seconds)
        snapshot = self._playback_clock.force_position(
            next_base * 1000.0,
            paused=paused,
            playback_rate=rate,
            reason=reason,
        )
        self._adopt_playback_snapshot(snapshot)

    def _set_startup_state(self, state: str, **details: object) -> None:
        previous, self._startup_state = self._startup_state, str(state)
        page = self._studio_page()
        trace = getattr(page, "_studio_trace", None)
        if callable(trace) and previous != self._startup_state:
            trace("PLAYBACK_STARTUP_STATE", previous=previous, current=self._startup_state,
                  elapsed_ms=round((perf_counter() - self._startup_started_at) * 1000.0, 3),
                  **details)
        if (
            previous in {"MEDIA_OPENING", "CLOCK_SYNCING"}
            and self._startup_state == "READY"
            and getattr(page, "_deferred_source_rebind", False)
        ):
            # 加载完成：补一次被换绑风暴门延迟的源切换（见
            # _activate_multitrack_preview 的 VIDEO_REBIND_DEFERRED）。
            retry = getattr(page, "_retry_deferred_source_rebind", None)
            if callable(retry):
                QTimer.singleShot(0, retry)

    def startup_state_snapshot(self) -> dict[str, object]:
        return {"state": self._startup_state, "play_requested": self._startup_play_requested,
                "elapsed_ms": round((perf_counter() - self._startup_started_at) * 1000.0, 3)}

    def _adopt_playback_snapshot(
        self,
        snapshot: PlaybackPositionSnapshot,
        *,
        emit: bool = True,
    ) -> None:
        previous_ms = self._base_time * 1000.0
        next_base = self._clamp_position(snapshot.presentation_media_ms / 1000.0)
        position_changed = abs(next_base - self._base_time) >= 0.0005
        previous_paused = self._paused
        previous_rate = self._playback_rate
        self._base_time = next_base
        self._paused = bool(snapshot.paused)
        self._playback_rate = float(snapshot.playback_rate) / getattr(self, '_source_rate_multiplier', 1.0)
        self._clock.restart()
        self._trace_position_mutation(previous_ms, next_base * 1000.0, snapshot)
        page = self._studio_page()
        if page is not None:
            owner = ("AUDIO_WAIT" if getattr(page, '_audio_tail_waiting', lambda:False)()
                     else "AUDIO" if self._external_clock_active() else "MPV")
            # 2026-09-18 D2 心跳降采样：heartbeat 快照仅 1Hz 落盘；暂停/倍速/时钟
            # 属主/媒体源变化立即落盘。此前每 150ms 无条件两行长行——暂停态挂机
            # 数小时即数百 MB 日志，后台渲染线程持续磁盘写 + GIL 竞争。非心跳
            # 来源（seek/observe/mutation）保持全量，诊断语义不变。
            now_mono = time.monotonic()
            owner_changed = owner != getattr(self, "_media_clock_owner_logged", None)
            source_changed = str(self._media_path or "") != getattr(self, "_media_clock_source_logged", None)
            state_changed = (
                self._paused != previous_paused
                or self._playback_rate != previous_rate
                or owner_changed
                or source_changed
            )
            # The steady playback ticks (visual tick, cached frame, audio
            # clock) are a heartbeat too: ~70 two-line records a second grew
            # studio-open.log to over a gigabyte. Seeks keep full records.
            heartbeat_gated = (
                str(snapshot.source) in _STEADY_CLOCK_SOURCES
                and not getattr(snapshot, "seeking", False)
                and not state_changed
                and now_mono - getattr(self, "_media_clock_log_at", 0.0) < 1.0
            )
            if not heartbeat_gated:
                self._media_clock_log_at = now_mono
                self._media_clock_owner_logged = owner
                self._media_clock_source_logged = str(self._media_path or "")
                source_media_ms = self._last_mpv_time_pos_ms
                if source_media_ms is None:
                    source_media_ms = self._media_time_mapping.project_to_source_ms(
                        float(snapshot.presentation_media_ms),
                        timeline_in_ms=self._project_timeline_in_ms,
                        source_in_ms=self._project_source_in_ms,
                        playback_rate=self._project_playback_rate,
                    )
                media_fields = {
                    "project_time_ms": round(float(snapshot.presentation_media_ms), 3),
                    "source_media_time_ms": round(float(source_media_ms), 3),
                    "video_stream_pts_ms": round(
                        self._media_time_mapping.source_to_stream_pts_ms(source_media_ms, "video"), 3
                    ),
                    "audio_stream_pts_ms": round(
                        self._media_time_mapping.source_to_stream_pts_ms(source_media_ms, "audio"), 3
                    ),
                    "mpv_time_pos": round(float(source_media_ms) / 1000.0, 6),
                    "timeline_position_ms": round(float(snapshot.presentation_media_ms), 3),
                    "audio_clock_position_ms": (
                        round(float(source_media_ms), 3) if not self._media_has_video else None
                    ),
                    "video_frame_pts_ms": self._last_video_frame_pts_ms,
                    "audio_observed_pts_ms": self._last_audio_pts_ms,
                }
                page._studio_trace(
                    "MEDIA_CLOCK_POSITION",
                    owner=owner,
                    position_ms=round(float(snapshot.presentation_media_ms), 3),
                    **media_fields,
                    source=str(snapshot.source),
                )
                page._studio_trace(
                    "MEDIA_CLOCK_OWNER",
                    owner=owner,
                    has_video=bool(self._media_has_video),
                    source_path=str(self._media_path or ""),
                )
        if emit and (
            position_changed
            or self._paused != previous_paused
            or self._playback_rate != previous_rate
        ):
            self.position_changed.emit(self._base_time)
        if emit and self._paused != previous_paused:
            self.playback_state_changed.emit(self._paused)

    def _studio_page(self):
        """Find the owning SubtitleStudioPage through nested Qt containers."""
        current = self.parentWidget()
        while current is not None:
            if callable(getattr(current, "_studio_trace", None)):
                return current
            current = current.parentWidget()
        return None

    def _trace_position_mutation(
        self,
        old_ms: float,
        new_ms: float,
        snapshot: PlaybackPositionSnapshot,
    ) -> None:
        delta = float(new_ms) - float(old_ms)
        if abs(delta) < 0.01:
            return
        raw_reason = str(getattr(snapshot, "source", "unknown") or "unknown")
        if (raw_reason in _STEADY_CLOCK_SOURCES and not snapshot.seeking
                and not snapshot.paused and 0.0 < delta < 500.0):
            # Ordinary forward playback steps: keep the loop detector's
            # samples, write one diagnostic record per second.
            now = time.monotonic()
            if now - self._position_mutation_logged_at < 1.0:
                self._position_trace_samples.append(float(new_ms))
                return
            self._position_mutation_logged_at = now
        page = self._studio_page()
        lowered = raw_reason.casefold()
        if "seek" in lowered:
            source = "USER_SEEK"
        elif "audio" in lowered:
            source = "AUDIO_ENGINE"
        elif "mpv" in lowered or "property" in lowered:
            source = "MPV_OBSERVE"
        elif "project" in lowered or "reset" in lowered:
            source = "PROJECT_OPEN"
        elif "waveform" in lowered:
            source = "WAVEFORM"
        else:
            source = "PLAYBACK_CLOCK"
        project_id = ""
        session_id = ""
        media_id = str(self._media_path or "")
        if page is not None:
            project_id = str(getattr(page, "project_path", "") or "")
            session_id = str(getattr(page, "_studio_session_id", "") or "")
        fields = {
            "wall_time": time.time(),
            "project_id": project_id,
            "studio_session_id": session_id,
            "media_id": media_id,
            "thread": threading.current_thread().name,
            "old_ms": round(float(old_ms), 3),
            "new_ms": round(float(new_ms), 3),
            "delta": round(delta, 3),
            "source": source,
            "reason": raw_reason,
        }
        if page is not None:
            page._studio_trace("POSITION_MUTATION", **fields)
        # Explicit backwards scrub is an intent, not a decoder replay loop.
        # Mixing generations made every wide scrub synchronously serialize
        # the entire trace ring (hundreds of ms per mouse event).
        if source in {"USER_SEEK", "PROJECT_OPEN"} or snapshot.seeking:
            self._position_trace_samples.clear()
            return
        self._position_trace_samples.append(float(new_ms))
        if delta < -100.0 and not snapshot.paused:
            stack = traceback.format_stack(limit=12)
            backward_fields = {**fields, "stack": stack}
            if page is not None:
                page._studio_trace("BACKWARD_POSITION_JUMP", **backward_fields)
            key = (round(float(old_ms) / 50.0), round(float(new_ms) / 50.0))
            now = time.monotonic()
            if (
                key != self._position_trace_last_loop_key
                or now - self._position_trace_last_loop_at > 2.0
            ):
                self._position_trace_last_loop_key = key
                self._position_trace_last_loop_at = now
                windows = backward_replay_windows(
                    list(self._position_trace_samples), tolerance_ms=100.0
                )
                if windows:
                    frozen = GLOBAL_STUDIO_TRACE.freeze_async("backward_position_loop")
                    if page is not None:
                        page._studio_trace(
                            "PLAYBACK_LOOP_DETECTED",
                            **fields,
                            windows=windows[-8:],
                            trace_frozen_path=frozen,
                        )

    def _clamp_position(self, seconds: float) -> float:
        value = max(0.0, float(seconds))
        return min(value, self._duration) if self._duration > 0.0 else value

    def visual_position(self) -> float:
        elapsed_ms = 0.0 if self._paused or self._eof_reached else self._clock.elapsed()
        seconds = self._playback_clock.presentation_position_ms(
            elapsed_ms=elapsed_ms,
        ) / 1000.0
        return self._clamp_position(seconds)

    def playback_position_snapshot(self) -> PlaybackPositionSnapshot:
        return self._playback_clock.snapshot()

    def playback_position_trace(self) -> list[dict[str, object]]:
        return self._playback_clock.trace()

    def project_clock_write_audit(self) -> list[dict[str, object]]:
        return self._playback_clock.write_audit()

    def set_project_time_mapping(
        self,
        *,
        enabled: bool,
        timeline_in_ms: int = 0,
        source_in_ms: int = 0,
        playback_rate: float = 1.0,
    ) -> None:
        self._project_time_mapping_enabled = bool(enabled)
        self._project_timeline_in_ms = int(timeline_in_ms)
        self._project_source_in_ms = int(source_in_ms)
        self._project_playback_rate = max(0.01, float(playback_rate or 1.0))

    def _decoder_speed(self, transport_rate):
        return max(0.1, min(8.0, float(transport_rate or 1.0) * getattr(self, '_source_rate_multiplier', 1.0)))

    def set_source_rate_multiplier(self, value):
        """Primary mapped clips: source clock advances at edit rate × UI rate.

        Keep UI/audio transport rate separate; AudioGraph already carries each
        clip's rate, so exposing decoder speed there would apply it twice.
        """
        value=max(.01,float(value or 1.0))
        if abs(value-getattr(self,'_source_rate_multiplier',1.0))<.0001:return
        rate=self._playback_rate
        position=self.visual_position()
        self._source_rate_multiplier=value
        if self.controller:
            speed=self._decoder_speed(rate)
            post=getattr(self.controller,'post_set_speed',None)
            if not callable(post) or not post(speed):self.controller.set_speed(speed)
            snapshot=self._playback_clock.set_local_state(position*1000,playback_rate=speed,reason='clip_rate_change')
            self._adopt_playback_snapshot(snapshot,emit=False)

    def _source_position_to_project_ms(
        self, source_seconds: float, *, content_domain: bool = False
    ) -> float:
        source_ms = max(0.0, float(source_seconds) * 1000.0)
        if not content_domain:
            # mpv reports file timestamps; the project clock runs in audio
            # content time whenever an AV sync map is active.
            source_ms = self._source_to_content_ms(source_ms)
        if not self._project_time_mapping_enabled:
            return source_ms
        return self._media_time_mapping.source_to_project_ms(
            source_ms,
            timeline_in_ms=self._project_timeline_in_ms,
            source_in_ms=self._project_source_in_ms,
            playback_rate=self._project_playback_rate,
        )

    def begin_seek_trace(self, target_seconds: float, *, source: str = "studio") -> int:
        # Reject already queued pre-seek rasters immediately. The retained
        # native image stays visible until the new decode epoch is ready.
        self._video_overlay_epoch += 1
        now = perf_counter()
        target = self._clamp_position(target_seconds)
        baseline_frame = None
        if self.controller is not None:
            observed_property = getattr(self.controller, "observed_property", None)
            if callable(observed_property):
                baseline_frame = observed_property("video-frame-info", None)
        generation = self._playback_clock.generation + 1
        project_ms = target * 1000.0
        seek_mapping = self._media_time_mapping.describe_seek(
            project_ms,
            timeline_in_ms=self._project_timeline_in_ms,
            source_in_ms=self._project_source_in_ms,
            playback_rate=self._project_playback_rate,
        )
        self._active_seek_trace = {
            "generation": generation,
            "target_seconds": target,
            "source": str(source),
            "seek_was_paused": bool(self._paused),
            "baseline_frame": copy.deepcopy(baseline_frame),
            "markers": {"T0_user_input": now, "T1_handler_entered": now},
            "project_time_ms": seek_mapping["project_time_ms"],
            "source_media_time_ms": seek_mapping["source_media_time_ms"],
            "video_stream_pts_ms": seek_mapping["video_stream_pts_ms"],
            "audio_stream_pts_ms": seek_mapping["audio_stream_pts_ms"],
            "time_mapping": seek_mapping,
        }
        return generation

    def set_seek_visual_expectation(self, expectation: Mapping[str, object]) -> None:
        trace = self._active_seek_trace
        if trace is not None:
            trace["visual_expectation"] = dict(expectation)

    def _tag_seek_project_domain(self, project_ms, decoder_seconds):
        trace = self._active_seek_trace
        if trace is None:return
        mapping = self._media_time_mapping.describe_seek(int(project_ms),
            timeline_in_ms=self._project_timeline_in_ms, source_in_ms=self._project_source_in_ms,
            playback_rate=self._project_playback_rate)
        trace.update(project_time_ms=int(project_ms),source_media_time_ms=float(decoder_seconds)*1000,
            time_mapping=mapping,video_stream_pts_ms=mapping['video_stream_pts_ms'],
            audio_stream_pts_ms=mapping['audio_stream_pts_ms'])

    def mark_seek_stage(self, stage: str, **fields: object) -> None:
        trace = self._active_seek_trace
        if trace is None:
            return
        markers = trace.get("markers")
        if not isinstance(markers, dict) or stage in markers:
            return
        markers[str(stage)] = perf_counter()
        trace.update(fields)

    def _record_seek_trace(
        self,
        generation: int,
        *,
        settled: bool,
        failure: str = "",
    ) -> bool:
        trace = self._active_seek_trace
        if trace is None or int(trace.get("generation", -1)) != int(generation):
            return False
        markers = trace.get("markers")
        if not isinstance(markers, dict):
            return False
        if settled:
            self.mark_seek_stage("T9_event_loop_settled")
        t0 = float(markers.get("T0_user_input", perf_counter()))
        result = {
            key: value
            for key, value in trace.items()
            if key != "baseline_frame" and not str(key).startswith("_")
        }
        result["settled"] = bool(settled)
        if failure:
            result["failure"] = str(failure)
        result["elapsed_ms"] = {
            name: round((float(stamp) - t0) * 1000.0, 3)
            for name, stamp in markers.items()
        }
        self._seek_trace_history.append(result)
        self._active_seek_trace = None
        return True

    def _finish_seek_trace(self, generation: int) -> bool:
        trace = self._active_seek_trace
        if trace is None or int(trace.get("generation", -1)) != int(generation):
            return False
        markers = trace.get("markers")
        if not isinstance(markers, dict):
            return False
        required = {
            "T5_first_target_frame",
            "T6_seeking_false",
            "T8_active_cue_visual_owner_correct",
        }
        if not bool(trace.get("seek_was_paused", True)):
            required.add("T7_sustained_progression")
        if not required.issubset(markers) or trace.get("T8_passed") is not True:
            return False
        return self._record_seek_trace(generation, settled=True)

    def _expire_seek_trace(self, generation: int, *, reason: str) -> bool:
        return self._record_seek_trace(
            generation,
            settled=False,
            failure=str(reason),
        )

    def seek_latency_traces(self) -> list[dict[str, object]]:
        result = [copy.deepcopy(item) for item in self._seek_trace_history]
        if self._active_seek_trace is not None:
            result.append(copy.deepcopy(self._active_seek_trace))
        return result

    @property
    def at_eof(self) -> bool:
        return self._eof_reached

    def _set_eof(self, reached: bool) -> None:
        reached = bool(reached)
        self._eof_reached = reached
        if reached:
            self._set_interpolation_base(
                self._duration or self._base_time,
                paused=True,
                reason="eof_transition",
            )

    def _offer_project_eof(self):
        page = self._studio_page()
        callback = getattr(page, '_handle_source_eof', None)
        return bool(callback()) if callable(callback) else False

    def _visual_tick(self) -> None:
        page = self._studio_page()
        refresh = getattr(page, '_refresh_audio_tail_clock', None)
        if callable(refresh):
            refresh()
        now_ns = self._tick_clock.nsecsElapsed()
        if self._last_visual_tick_ns:
            interval = (now_ns - self._last_visual_tick_ns) / 1_000_000
            self._update_intervals_ms.append(interval)
            if len(self._update_intervals_ms) > 1200:
                del self._update_intervals_ms[:200]
            self._dropped_visual_frames += max(0, round(interval / 16.667) - 1)
        self._last_visual_tick_ns = now_ns
        self._observe_external_clock()
        self._observe_cached_video_clock()
        if self._paused:
            return
        snapshot = self._playback_clock.sample_presentation(
            elapsed_ms=self._clock.elapsed(),
            source="visual_tick",
        )
        seconds = self._clamp_position(snapshot.presentation_media_ms / 1000.0)
        if self._duration > 0.0 and seconds >= self._duration:
            if not self._offer_project_eof():
                self._set_eof(True)
            return
        self.position_changed.emit(seconds)

    def _observe_cached_video_clock(self) -> None:
        """Consume the actor's immutable sample, without IPC or a second clock.

        Waiting for the 150 ms lifecycle reconcile left the interpolation
        behind media frames even after their observations were in memory.
        """
        page = self._studio_page()
        waiting_tail = getattr(page, '_audio_tail_waiting', lambda:False)()
        if waiting_tail or self._clock_only or self._paused or self._external_clock_active() or not self.controller:return
        get_observation=getattr(self.controller,'observed_position',None)
        if not callable(get_observation):return
        observation=get_observation()
        if observation.get('position') is None:return
        properties = getattr(self.controller, 'observed_properties', lambda: {})()
        if properties.get('eof-reached') and self._offer_project_eof():
            return
        previous=self._playback_clock.snapshot()
        sequence=int(observation.get('actor_sequence',0))
        generation=int(observation.get('source_generation',0))
        if generation==previous.source_generation and sequence<=previous.actor_sequence:return
        snapshot,accepted,_=self._playback_clock.observe(
            self._source_position_to_project_ms(float(observation['position'])),
            source_generation=generation,actor_sequence=sequence,
            observed_monotonic_ts=float(observation['observed_monotonic_ts']),
            playback_rate=float(observation.get('playback_rate',self._playback_rate)),
            paused=bool(observation.get('paused',self._paused)),seeking=bool(observation.get('seeking',False)),
            source='cached_video_frame',presentation_media_ms=self.visual_position()*1000.,align_forward=True,
            observed_perf_counter_ts=observation.get('observed_perf_counter_ts'))
        if accepted:
            self._last_mpv_time_pos_ms=float(observation['position'])*1000.
            self._adopt_playback_snapshot(snapshot,emit=False)

    def _reconcile_position(self) -> None:
        page = self._studio_page()
        refresh = getattr(page, '_refresh_audio_tail_clock', None)
        if callable(refresh):
            refresh()
        if getattr(page, '_audio_tail_waiting', lambda:False)():
            return
        if self._eof_reached and self._paused:
            # Keep the terminal project anchor until an explicit seek/play.
            # A delayed decoder pause sample may still point at its last
            # frame (e.g. 24.967s) and must not clear the 25.000s project EOF.
            return
        if self._clock_only:
            return
        # Audio-only projects have no meaningful mpv frame clock. Keep mpv's
        # idle/eof observations from stopping the ProjectClock; AudioEngine is
        # the physical source clock and is sampled above.
        if self._external_clock_active():
            self._observe_external_clock()
            return
        if not self.controller or not self.controller.running:
            self._enter_playback_source_dead("mpv_process_exited")
            return
        if (
            self._media_attached
            and self._startup_state == "READY"
            and callable(getattr(self.controller, "source_alive", None))
            and not self.controller.source_alive()
        ):
            # The child still exists but its IPC has been silent past the
            # heartbeat budget: a wedged core is as dead as an exited one.
            self._enter_playback_source_dead("mpv_transport_stalled")
            return
        try:
            observed = getattr(self.controller, "observed_properties", None)
            snapshot = observed() if callable(observed) else {}
            if callable(observed) and not snapshot:
                # The actor will publish initial observations asynchronously.
                # A GUI heartbeat must never wait for synchronous IPC during
                # startup or immediately after a source change.
                return
            if self._video_display_size == (0, 0):
                video_params = snapshot.get("video-out-params")
                if video_params is None and not callable(observed):
                    video_params = self.controller.get_property("video-out-params", {})
                if isinstance(video_params, dict):
                    display_width = int(video_params.get("dw") or video_params.get("w") or 0)
                    display_height = int(video_params.get("dh") or video_params.get("h") or 0)
                    if display_width > 0 and display_height > 0:
                        self._video_display_size = (display_width, display_height)
                        self.video_display_size_changed.emit(display_width, display_height)
            if snapshot:
                duration = snapshot.get("duration", self._duration)
                paused = bool(snapshot.get("pause", self._paused))
                speed = float(snapshot.get("speed", self._playback_rate) or self._playback_rate)
                eof_reached = bool(snapshot.get("eof-reached", False))
                idle_active = bool(snapshot.get("idle-active", False))
                seeking = bool(snapshot.get("seeking", False))
                value = snapshot.get("time-pos")
                if value is None:
                    value = snapshot.get("playback-time")
                page = self._studio_page()
                frame_info = snapshot.get("video-frame-info")
                self._last_mpv_time_pos_ms = (
                    max(0.0, float(value) * 1000.0) if value is not None else None
                )
                try:
                    self._last_video_frame_pts_ms = (
                        float(frame_info.get("pts")) * 1000.0
                        if isinstance(frame_info, Mapping) and frame_info.get("pts") is not None
                        else None
                    )
                except (TypeError, ValueError):
                    self._last_video_frame_pts_ms = None
                audio_pts = snapshot.get("audio-pts")
                self._last_audio_pts_ms = (
                    float(audio_pts) * 1000.0 if audio_pts is not None else None
                )
                if page is not None and isinstance(frame_info, Mapping) and (
                    frame_info.get("pts") is not None
                    or frame_info.get("estimated-frame-number") is not None
                    or bool(frame_info.get("picture-type"))
                ):
                    page._studio_mark_startup_milestone(
                        "FIRST_FRAME_READY",
                        frame_info={
                            "pts": frame_info.get("pts"),
                            "estimated_frame_number": frame_info.get("estimated-frame-number"),
                            "picture_type": frame_info.get("picture-type"),
                        },
                    )
                if page is not None and snapshot.get("audio-pts") is not None:
                    page._studio_mark_startup_milestone(
                        "FIRST_AUDIO_READY",
                        audio_pts=snapshot.get("audio-pts"),
                    )
                    page._studio_mark_startup_milestone("MEDIA_CLOCK_READY", clock_owner="mpv", audio_pts=snapshot.get("audio-pts"))
                if page is not None and not self._media_has_video and value is not None:
                    page._studio_mark_startup_milestone(
                        "FIRST_AUDIO_READY",
                        audio_clock_position_ms=round(float(value) * 1000.0, 3),
                    )
                    page._studio_mark_startup_milestone("MEDIA_CLOCK_READY", clock_owner="mpv", audio_clock_position_ms=round(float(value) * 1000.0, 3))
                codec = str(snapshot.get("video-codec") or "")
                hwdec = str(snapshot.get("hwdec-current") or "")
                hwdec_snapshot = {"codec": codec, "requested": "auto-safe", "selected": hwdec,
                                   "interop": str(snapshot.get("hwdec-interop") or ""),
                                   "software_fallback": bool(codec and not hwdec)}
                if codec and hwdec_snapshot != self._last_hwdec_snapshot:
                    self._last_hwdec_snapshot = hwdec_snapshot
                    if page is not None:
                        page._studio_trace("MPV_HWDEC_SELECTION", **hwdec_snapshot)
            else:
                duration = self.controller.get_property("duration")
                paused = bool(self.controller.get_property("pause", self._paused))
                speed = float(self.controller.get_property("speed", self._playback_rate) or self._playback_rate)
                eof_reached = bool(self.controller.get_property("eof-reached", False))
                idle_active = bool(self.controller.get_property("idle-active", False))
                seeking = bool(self.controller.get_property("seeking", False))
                # Read the clock last. At 8x, anchoring to a timestamp fetched
                # before the other IPC properties can itself introduce visible drift.
                value = self.controller.get_property("time-pos")
                if value is None:
                    value = self.controller.get_property("playback-time")
                frame_info = self.controller.get_property("video-frame-info", {})
                self._last_mpv_time_pos_ms = (
                    max(0.0, float(value) * 1000.0) if value is not None else None
                )
                try:
                    self._last_video_frame_pts_ms = (
                        float(frame_info.get("pts")) * 1000.0
                        if isinstance(frame_info, Mapping) and frame_info.get("pts") is not None
                        else None
                    )
                except (TypeError, ValueError):
                    self._last_video_frame_pts_ms = None
                audio_pts = self.controller.get_property("audio-pts")
                self._last_audio_pts_ms = (
                    float(audio_pts) * 1000.0 if audio_pts is not None else None
                )
            frame_ready = bool(isinstance(frame_info, Mapping) and any(
                frame_info.get(key) is not None
                for key in ("pts", "estimated-frame-number", "picture-type")))
            audio_ready = bool(
                not self._media_has_video
                and value is not None
                and not idle_active
                and not eof_reached
            )
            startup_ready = audio_ready or frame_ready
            if self._startup_state != "READY" and value is not None and not idle_active:
                if self._startup_state == "MEDIA_OPENING":
                    self._set_startup_state("CLOCK_SYNCING")
                if startup_ready:
                    play_requested = self._startup_play_requested
                    paused = True
                    self._set_startup_state("READY", media_clock_seconds=float(value))
                    if play_requested:
                        # Cold-open Play goes through the same PCM/frame gate
                        # as a normal pause→play transition.
                        QTimer.singleShot(0, lambda: self.set_paused(False))
            if self._duration_override > 0:
                self._duration = self._duration_override
            elif duration is not None:
                self._duration = max(0.0, float(duration))
            # Decoder timestamps belong to the current source, whose in-point
            # can be beyond the entire project's duration. Clamp only after
            # mapping to the project clock; otherwise B@102s in a 15s edit is
            # mistaken for EOF and a paused seek can never settle.
            actual = max(0.0, float(value or 0.0))
            project_seconds = self._source_position_to_project_ms(actual) / 1000.0
            at_end = self._duration > 0.0 and project_seconds >= self._duration - 0.001
            if eof_reached or (at_end and (paused or idle_active)):
                if not self._offer_project_eof():
                    self._set_eof(True)
                return
            self._eof_reached = False
            position_metadata = getattr(self.controller, "observed_position", None)
            observation = position_metadata() if callable(position_metadata) else {}
            observed_value = observation.get("position")
            if observed_value is not None:
                actual = max(0.0, float(observed_value))
            if observation:
                source_generation = int(
                    observation.get("source_generation", self._playback_clock.generation)
                )
                actor_sequence = int(observation.get("actor_sequence", 0))
                observed_at = float(observation.get("observed_monotonic_ts", time.monotonic()))
                source = str(observation.get("source", "mpv_property_change"))
            else:
                self._fallback_observation_sequence += 1
                source_generation = self._playback_clock.generation
                actor_sequence = self._fallback_observation_sequence
                observed_at = time.monotonic()
                source = "legacy_property_poll"
            project_actual_ms = self._source_position_to_project_ms(actual)
            clock_snapshot, accepted, _reason = self._playback_clock.observe(
                project_actual_ms,
                source_generation=source_generation,
                actor_sequence=actor_sequence,
                observed_monotonic_ts=observed_at,
                playback_rate=speed,
                paused=paused,
                seeking=seeking,
                source=source,
                presentation_media_ms=self.visual_position() * 1000.0,
                observed_perf_counter_ts=observation.get('observed_perf_counter_ts'),
            )
            if accepted:
                self._adopt_playback_snapshot(clock_snapshot)
            trace = self._active_seek_trace
            if trace is not None:
                generation = int(trace.get("generation", -1))
                applied = getattr(self.controller, "applied_seek_state", lambda: {})()
                if int(applied.get("generation", -2)) == generation:
                    markers = trace.get("markers")
                    if isinstance(markers, dict) and "T4_mpv_seek_accepted" not in markers:
                        markers["T4_mpv_seek_accepted"] = float(
                            applied.get("perf_counter", perf_counter())
                        )
                frame_info = snapshot.get("video-frame-info")
                if isinstance(frame_info, Mapping):
                    try:
                        pts = float(frame_info.get("pts"))
                    except (TypeError, ValueError):
                        pts = -1.0
                    target_seconds = float(
                        trace.get("decoder_target_seconds", trace.get("target_seconds", 0.0))
                    )
                    frame_matches_target = (
                        abs(pts - target_seconds) <= 0.35
                        if pts >= 0.0
                        else abs(actual - target_seconds) <= 0.35
                    )
                    if frame_info != trace.get("baseline_frame") and frame_matches_target:
                        self.mark_seek_stage(
                            "T5_first_target_frame",
                            frame_signal=(
                                "video-frame-info/pts"
                                if pts >= 0.0
                                else "video-frame-info+observed-time-pos"
                            ),
                            frame_pts=pts if pts >= 0.0 else None,
                            frame_timecode=str(frame_info.get("estimated-smpte-timecode") or ""),
                        )
                markers = trace.get("markers")
                if isinstance(markers, dict) and not seeking and "T4_mpv_seek_accepted" in markers:
                    self.mark_seek_stage("T6_seeking_false")
                    if (
                        not paused
                        and "T5_first_target_frame" in markers
                        and "T7_sustained_progression" not in markers
                    ):
                        progress_now = perf_counter()
                        anchor = trace.get("_progression_anchor")
                        if not isinstance(anchor, Mapping):
                            trace["_progression_anchor"] = {
                                "position": actual,
                                "perf_counter": progress_now,
                            }
                        else:
                            anchor_position = float(anchor.get("position", actual))
                            anchor_counter = float(anchor.get("perf_counter", progress_now))
                            min_progress = max(0.03, abs(speed) * 0.025)
                            if (
                                progress_now - anchor_counter >= 0.025
                                and actual - anchor_position >= min_progress
                            ):
                                self.mark_seek_stage(
                                    "T7_sustained_progression",
                                    progression_start_seconds=anchor_position,
                                    progression_observed_seconds=actual,
                                    progression_delta_seconds=round(
                                        actual - anchor_position, 6,
                                    ),
                                )
            active_trace = self._active_seek_trace
            needs_progress_probe = bool(
                isinstance(active_trace, dict)
                and not bool(active_trace.get("seek_was_paused", True))
                and "T7_sustained_progression"
                not in active_trace.get("markers", {})
            )
            # mpv can clear seeking before video-frame-info publishes the new
            # frame. Keep observing both events; returning to 150ms after T6
            # alone adds an avoidable full idle interval to a paused seek.
            needs_target_probe = bool(
                active_trace is not None
                and not {"T5_first_target_frame", "T6_seeking_false"}.issubset(
                    active_trace.get("markers", {})
                )
            )
            self._sync_timer.setInterval(
                16 if self._playback_clock.exact_seek_pending or needs_target_probe
                else 40 if needs_progress_probe else 50 if speed >= 4.0 else 75 if speed >= 2.0 else 150
            )
        except (RuntimeError, TypeError, ValueError):
            pass

    def _trace_seek(
        self,
        reason: str,
        *,
        project_target_s: float,
        mapped_media_target_s: float,
        clamped: bool = False,
        blocked: str = "",
    ) -> None:
        """[SeekTrace]：每次程序 seek 的目标/映射/钳制可追溯（§11）。"""
        page = self._studio_page()
        if page is None:
            return
        sync_map = getattr(self, "_av_sync_map", None)
        page._studio_trace(
            "SeekTrace",
            reason=str(reason),
            project_target=round(float(project_target_s), 3),
            mapped_media_target=round(float(mapped_media_target_s), 3),
            source=str(getattr(self, "_media_path", "") or "")[-80:],
            time_domain=getattr(self, "_playback_time_domain", "source"),
            map_active=bool(sync_map is not None and not sync_map.is_identity),
            map_gaps=len(sync_map.gaps) if sync_map is not None else 0,
            duration=round(float(getattr(self, "_duration", 0.0) or 0.0), 3),
            clamped=bool(clamped),
            blocked=str(blocked),
        )

    def _set_playback_time_domain(self, domain: str) -> None:
        """§6/§7：媒体时间域显式属性化，seek/观测是否过 AVSyncMap 由它决定。"""
        normalized = domain if domain in {"source", "content"} else "source"
        if normalized == getattr(self, "_playback_time_domain", ""):
            return
        self._playback_time_domain = normalized
        page = self._studio_page()
        if page is not None:
            page._studio_trace("PlaybackTimeDomain", domain=normalized)

    def _track_playback_perf(self, *, paused: bool | None = None) -> None:
        """[PlaybackPerf]: bounded-window seek counters + mpv drop statistics.

        Continuous playback must never need per-tick seeks to stay in sync;
        a normal 10 s window showing dozens of seek_requests is a bug signal.
        """
        counters = getattr(self, "_perf_counters", None)
        if counters is None:
            counters = self._perf_counters = {
                "seek_requests": [],
                "window_started": time.monotonic(),
                "playing": False,
            }
            timer = QTimer(self)
            timer.setInterval(10_000)
            timer.timeout.connect(self._emit_playback_perf)
            self._perf_timer = timer
        if paused is not None:
            counters["playing"] = not bool(paused)
            if counters["playing"] and not self._perf_timer.isActive():
                self._perf_timer.start()
            elif paused and self._perf_timer.isActive():
                self._perf_timer.start()  # keep sampling briefly while paused too

    # mpv 累计丢帧计数 → 窗口增量字段。属性名以捆绑 mpv v0.41 实测为准，
    # 读取失败/该上下文不可用时记 "N/A"，绝不默认填 0。
    _MPV_PERF_COUNTER_PROPERTIES = (
        ("decoder-frame-drop-count", "decoder_dropped"),
        ("frame-drop-count", "vo_dropped"),
        ("vo-delayed-frame-count", "vo_delayed"),
        ("mistimed-frame-count", "mistimed"),
    )

    def _emit_playback_perf(self) -> None:
        counters = getattr(self, "_perf_counters", None)
        if counters is None:
            return
        now = time.monotonic()
        window = max(0.001, now - counters["window_started"])
        seeks = [t for t in counters["seek_requests"] if now - t <= window]
        counters["seek_requests"] = []
        counters["window_started"] = now
        controller = self.controller
        observed = getattr(controller, "observed_property", None)
        stats: dict[str, object] = {}
        last = counters.setdefault("last_cumulative", {})
        for name, key in self._MPV_PERF_COUNTER_PROPERTIES:
            value = None
            if callable(observed):
                try:
                    value = observed(name, None)
                except Exception:
                    value = None
            if not isinstance(value, (int, float)):
                stats[key] = "N/A"
                last.pop(key, None)
                continue
            previous = last.get(key)
            # 换源/重载后 mpv 累计计数归零：当前值小于上窗值即按重置重算增量。
            delta = value if (previous is None or value < previous) else value - previous
            last[key] = value
            stats[key] = int(delta)
        vf_fps = None
        if callable(observed):
            try:
                vf_fps = observed("estimated-vf-fps", None)
            except Exception:
                vf_fps = None
        page = self._studio_page()
        if page is not None:
            page._studio_trace(
                "PlaybackPerf",
                seek_requests_10s=len(seeks),
                playing=bool(counters.get("playing")),
                window_s=round(window, 1),
                decoder_dropped_10s=stats.get("decoder_dropped"),
                vo_dropped_10s=stats.get("vo_dropped"),
                vo_delayed_10s=stats.get("vo_delayed"),
                mistimed_10s=stats.get("mistimed"),
                estimated_vf_fps=(
                    round(float(vf_fps), 2) if isinstance(vf_fps, (int, float)) else "N/A"
                ),
            )
            # [PlaybackClockDebug]（§2）：UI/传输速率 vs mpv 实际 speed 失配
            # 立即点名——"UI 1x 画面 8x"回归的第一现场。
            ui_speed = self._decoder_speed(self._playback_rate)
            mpv_speed = None
            if callable(observed):
                try:
                    mpv_speed = observed("speed", None)
                except Exception:
                    mpv_speed = None
            try:
                mpv_speed_value = float(mpv_speed) if mpv_speed is not None else None
            except (TypeError, ValueError):
                mpv_speed_value = None
            if mpv_speed_value is not None and abs(mpv_speed_value - ui_speed) > 0.06:
                sync_map = getattr(self, "_av_sync_map", None)
                page._studio_trace(
                    "PlaybackClockDebug",
                    ui_speed=ui_speed,
                    mpv_speed=mpv_speed_value,
                    source=str(getattr(self, "_media_path", "") or "")[-80:],
                    time_domain=getattr(self, "_playback_time_domain", "source"),
                    map_active=bool(sync_map is not None and not sync_map.is_identity),
                )
        if not counters.get("playing"):
            self._perf_timer.stop()

    def seek(
        self,
        seconds: float,
        *,
        accurate: bool = True,
        project_ms: int | None = None,
    ) -> None:
        """Seek; while playing, hold the picture until the new audio is ready.

        The audio engine restarts its decoder at the new position. On an
        unindexed FLV that takes 0.3–1.5 s before the first PCM, while mpv
        resumed at once: audio then trailed the picture by the whole startup
        time (3.6 s of media at 4x) until the next pause or rate change. The
        hold reuses the buffered-play gate that already protects play start
        and rate changes, so both clocks resume from the same anchor.
        """
        hold = self._should_hold_for_seek()
        if hold:
            self._seek_hold_token += 1
            self._seek_hold_active = True
            self._seek_hold_started = time.monotonic()
            self._trace_playback_gate("SEEK_HOLD_BEGIN", target_s=round(float(seconds), 3))
            self._seek_hold_entering = True
            try:
                self.set_paused(True)
            finally:
                self._seek_hold_entering = False
        self._seek_now(seconds, accurate=accurate, project_ms=project_ms)
        if hold and self._seek_hold_active:
            token = self._seek_hold_token
            # The page moves its playhead and sends the new audio request
            # right after this call; resume (through the gate) after that.
            QTimer.singleShot(0, lambda: self._resume_after_seek_hold(token))

    def _playback_gate_detail(self) -> dict:
        page = self._studio_page()
        engine = getattr(page, "audio_engine", None)
        request = dict(getattr(engine, "_last_payload", {}) or {})
        state = dict(getattr(engine, "_telemetry", {}) or {})
        return {"audio_ready": bool(engine.ready_for_playback()) if engine is not None else None,
                "request_generation": request.get("transport_generation"),
                "telemetry_generation": state.get("transport_generation"),
                "telemetry_state": state.get("state"), "buffer_bytes": state.get("buffer_bytes"),
                "request_paused": request.get("paused"), "sync_inflight": getattr(engine, "_sync_inflight", None)}

    @property
    def playback_intended(self) -> bool:
        """The user's play/pause intent, not the momentary transport state.

        Buffering at play start and the seek hold pause the transport while
        the user is still "playing"; code that re-asserts the current state
        must not turn those internal pauses into a user pause.
        """
        return bool(not self._paused or self._buffered_play_pending or self._seek_hold_active)

    def _should_hold_for_seek(self) -> bool:
        return bool(
            not self._clock_only
            and self.controller is not None
            and self.controller.running
            and not self._playback_source_dead
            and self._startup_state == "READY"
            and callable(self.playback_ready)
            and (not self._paused or self._buffered_play_pending)
        )

    def _resume_after_seek_hold(self, token: int) -> None:
        if not self._seek_hold_active or token != self._seek_hold_token:
            return
        self.set_paused(False)

    def _trace_playback_gate(self, event: str, **fields) -> None:
        page = self._studio_page()
        trace = getattr(page, "_studio_trace", None)
        if callable(trace):
            trace(event, generation=int(self._playback_clock.generation), **fields)

    def _end_seek_hold(self, *, resumed: bool) -> None:
        if not self._seek_hold_active:
            return
        self._seek_hold_active = False
        fields = {}
        if not resumed:
            fields["caller"] = [f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                                for frame in traceback.extract_stack(limit=9)[:-2]]
        self._trace_playback_gate(
            "SEEK_HOLD_END", resumed=bool(resumed),
            held_ms=round((time.monotonic() - getattr(self, "_seek_hold_started", time.monotonic())) * 1000, 1),
            **fields)
        if not resumed:
            # The page skipped its pause side effects for the internal hold;
            # run them now that the pause is real (user pause or timeout).
            self.playback_state_changed.emit(True)

    def _seek_now(
        self,
        seconds: float,
        *,
        accurate: bool = True,
        project_ms: int | None = None,
    ) -> None:
        if self._clock_only:
            target_ms = max(0, int(project_ms if project_ms is not None else seconds * 1000))
            snapshot = self._playback_clock.begin_unattached_position(target_ms, paused=self._paused)
            self._eof_reached = False
            self._adopt_playback_snapshot(snapshot)
            return
        if not self.controller:
            return
        counters = getattr(self, "_perf_counters", None)
        if counters is not None:
            counters["seek_requests"].append(time.monotonic())
        self._track_playback_perf()
        # §10/§12：Python 的 max(0.0, nan) 返回 0.0——NaN 目标若先过钳位
        # 就会静默变成 seek(0)。输入先做有限性检查。
        try:
            requested = float(seconds)
        except (TypeError, ValueError):
            requested = float("nan")
        if not math.isfinite(requested):
            self._trace_seek(
                "mapping_invalid", project_target_s=-1.0,
                mapped_media_target_s=-1.0, blocked="nan_or_none",
            )
            self.set_paused(True)
            return
        content_seconds = max(0.0, requested)
        mapped = self._content_to_source_seconds(content_seconds)
        # §12 禁止静默回零：映射产物非法（NaN/None）或非零目标被映射成
        # 负值时，绝不允许 clamp 把它变成 0 播放——保持当前位置、暂停、
        # 记录错误。只有用户显式 seek 到 0 才允许落 0。
        if mapped != mapped or mapped is None:  # NaN/None guard
            self._trace_seek(
                "mapping_invalid", project_target_s=content_seconds,
                mapped_media_target_s=-1.0, blocked="nan_or_none",
            )
            self.set_paused(True)
            return
        if content_seconds > 1.0 and mapped < 0.0:
            self._trace_seek(
                "mapping_negative", project_target_s=content_seconds,
                mapped_media_target_s=mapped, blocked="negative",
            )
            self.set_paused(True)
            return
        clamped = False
        duration = float(getattr(self, "_duration", 0.0) or 0.0)
        # On secondary lanes _duration is PROJECT duration, while this is a
        # decoder SOURCE seek. A retained source offset may be much larger.
        target = max(0.0, mapped) if self._project_time_mapping_enabled else self._clamp_position(mapped)
        if not self._project_time_mapping_enabled and duration > 0 and target > duration:
            target = duration
            clamped = True
        if abs(target - mapped) > 0.001:
            clamped = True
        self._trace_seek(
            "programmatic", project_target_s=content_seconds,
            mapped_media_target_s=target, clamped=clamped,
        )
        # The playback clock must stay in one time domain. With clip mapping
        # disabled (primary route) the clock runs in the timeline (audio
        # content) domain and mpv observations are translated into it; seeding
        # begin_seek with another domain would make the acknowledgement gate
        # reject every observation for SEEK_ACK_TIMEOUT (playhead frozen at
        # the optimistic target). Multitrack playback enables the clip
        # mapping, so project ms is the clock domain there.
        if project_ms is not None and self._project_time_mapping_enabled:
            clock_ms = max(0, int(project_ms))
        else:
            clock_ms = content_seconds * 1000.0
        trace = self._active_seek_trace
        display_seconds = clock_ms / 1000.0
        if trace is None or abs(float(trace.get("target_seconds", -1.0)) - display_seconds) > 0.001:
            self.begin_seek_trace(display_seconds, source="direct")
        if self._active_seek_trace is not None:
            self._active_seek_trace["decoder_target_seconds"] = target
            if project_ms is not None:
                self._active_seek_trace['requested_project_ms'] = int(project_ms)
                self._tag_seek_project_domain(project_ms, target)
        snapshot = self._playback_clock.begin_seek(clock_ms)
        page = self._studio_page()
        prepare_tail = getattr(page, '_prepare_audio_tail_seek', None)
        if callable(prepare_tail):
            prepare_tail(content_seconds, project_ms if project_ms is not None else round(clock_ms))
        self._sync_timer.start(16)
        self._eof_reached = False
        self._adopt_playback_snapshot(snapshot)
        self.mark_seek_stage("T2_optimistic_playhead_visible")
        post = getattr(self.controller, "post_seek", None)
        posted = False
        if callable(post):
            try:
                posted = bool(post(
                    target,
                    accurate=accurate,
                    generation=self._playback_clock.generation,
                ))
            except TypeError:
                posted = bool(post(target, accurate=accurate))
        if not posted:
            if self._playback_source_dead:
                # Optimistic playhead already moved via begin_seek; the
                # deferred revive will resume from this position.
                self.mark_seek_stage("T3_seek_command_posted", accurate=bool(accurate), source_dead=True)
                return
            self.controller.seek(target, accurate=accurate)
        self.mark_seek_stage("T3_seek_command_posted", accurate=bool(accurate))

    def set_paused(self, paused: bool) -> None:
        page = self._studio_page()
        invalidate_tail = getattr(page, '_invalidate_audio_tail', None)
        if self._clock_only:
            self._eof_reached = False
            snapshot = self._playback_clock.set_local_state(
                self.visual_position() * 1000, paused=paused, reason='timeline_gap_pause')
            self._adopt_playback_snapshot(snapshot)
            return
        self._track_playback_perf(paused=paused)
        if paused:
            self._buffered_play_pending = False
            self._buffered_play_timer.stop()
            if self._seek_hold_active and not self._seek_hold_entering:
                # A pause from anyone else ends the internal seek hold.
                self._end_seek_hold(resumed=False)
        if not self.controller:
            return
        if self._playback_source_dead:
            # Transport is dead; keep the requested intent for revive only.
            self._startup_play_requested = not bool(paused)
            return
        if not self.controller.running:
            self._enter_playback_source_dead("mpv_process_exited")
            self._startup_play_requested = not bool(paused)
            return
        if self._startup_state != "READY":
            self._startup_play_requested = not bool(paused)
            return
        if not paused and self._paused and callable(self.playback_ready):
            if not self._buffered_play_pending:
                self._buffered_play_started = time.monotonic()
                if callable(self.playback_prepare):
                    self.playback_prepare()
            if not self.playback_ready():
                self._buffered_play_pending = True
                if time.monotonic()-self._buffered_play_started < 10:
                    self._buffered_play_timer.start()
                    return
                self._buffered_play_pending = False
                self._buffered_play_timer.stop()
                bind_text(self, '音频准备超时，请重试播放或检查素材。', property='toolTip')
                self._trace_playback_gate("PLAYBACK_GATE_TIMEOUT", waited_ms=round((time.monotonic()-self._buffered_play_started)*1000, 1),
                                          detail=self._playback_gate_detail())
                self._end_seek_hold(resumed=False)
                return
        if not paused and self._paused and callable(self.playback_ready) and getattr(self, "_buffered_play_started", 0.0):
            waited = (time.monotonic() - self._buffered_play_started) * 1000
            if waited >= 300:
                self._trace_playback_gate("PLAYBACK_GATE_WAIT", waited_ms=round(waited, 1))
        self._buffered_play_pending = False
        self._buffered_play_timer.stop()
        current = self.visual_position()
        post = getattr(self.controller, "post_set_paused", None)
        target = current
        if self._project_time_mapping_enabled:
            target = (self._project_source_in_ms +
                      (current*1000-self._project_timeline_in_ms)*self._project_playback_rate)/1000
        prepare_tail = getattr(page, '_prepare_audio_tail_seek', None)
        if bool(paused) != bool(self._paused) and callable(prepare_tail):
            prepare_tail(target, round(current*1000), transition=True)
        elif paused and callable(invalidate_tail):
            invalidate_tail()
        try:
            posted = callable(post) and post(paused, position_seconds=target if paused else None)
        except TypeError:
            posted = callable(post) and post(paused)
        if not posted:
            self.controller.set_paused(paused)
        if not paused:
            self._eof_reached = False
        snapshot = self._playback_clock.set_local_state(
            current * 1000.0,
            paused=paused,
            reason="local_pause_state",
        )
        self._adopt_playback_snapshot(snapshot)
        if not paused:
            self._end_seek_hold(resumed=True)

    def set_speed(self, value: float) -> None:
        if not self.controller:
            return
        resume = not self._paused or self._buffered_play_pending
        changing = abs(float(value)-self._playback_rate) > .001
        if changing:
            invalidate = getattr(self._studio_page(), '_invalidate_audio_tail', None)
            if callable(invalidate):
                invalidate()
        if changing and resume:
            # Freeze the common presentation anchor until the new atempo
            # generation has real PCM. Long FLV seeks can take seconds; letting
            # mpv advance during that preparation permanently loses sync.
            self.set_paused(True)
        current = self.visual_position()
        post = getattr(self.controller, "post_set_speed", None)
        decoder_speed=self._decoder_speed(value)
        if not callable(post) or not post(decoder_speed):
            self.controller.set_speed(decoder_speed)
        # The command is asynchronous. Reading the actor cache here returns the
        # previous speed and leaves PlaybackClock running at 2x after a 1x
        # reset until the next mpv property event. The requested rate is the
        # local transition truth; reconciliation will correct it from mpv.
        actual_rate = min(8.0, max(0.1, float(value)))
        self._sync_timer.setInterval(50 if actual_rate >= 4.0 else 75 if actual_rate >= 2.0 else 150)
        snapshot = self._playback_clock.set_local_state(
            current * 1000.0,
            playback_rate=decoder_speed,
            reason="local_speed_state",
        )
        self._adopt_playback_snapshot(snapshot)
        if changing and resume:
            self.set_paused(False)

    def playback_metrics(self) -> dict[str, float | int]:
        ordered = sorted(self._update_intervals_ms)
        p95 = ordered[min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))] if ordered else 0.0
        average = sum(ordered) / len(ordered) if ordered else 0.0
        return {
            "samples": len(ordered),
            "average_interval_ms": round(average, 3),
            "p95_interval_ms": round(p95, 3),
            "dropped_frames": self._dropped_visual_frames,
        }

    def close_player(self) -> None:
        detached = self.detach_player_for_close()
        if detached is not None:
            detached.close()

    def detach_player_for_close(self) -> MpvController | None:
        """Stop Qt activity and detach the process owner for background shutdown."""
        self._buffered_play_pending = False
        self._buffered_play_timer.stop()
        self._timer.stop()
        self._sync_timer.stop()
        for overlay_id in tuple(self._active_compositor_overlays):
            self.remove_compositor_overlay(overlay_id, force=True)
        subtitle_thread = None
        if self._subtitle_raster_publisher is not None:
            subtitle_thread = self._subtitle_raster_publisher.thread
            self._subtitle_raster_publisher.close()
            self._subtitle_raster_publisher=None
        # 二十七轮：停掉 web-live 发布线程（毒丸；线程 daemon，进程退出也无碍）。
        self._video_overlay_epoch += 1
        self._video_fast_queue.put_nowait(None)
        self._web_live_epoch += 1
        try:
            self._web_fast_queue.put_nowait(None)
        except queue.Full:
            pass
        detached = self.controller
        self.controller = None
        leases, self._media_cache_leases = getattr(self, '_media_cache_leases', {}), {}
        def release_after_close():
            deadline = time.monotonic() + 5
            while detached is not None and detached.running:
                if time.monotonic() >= deadline:
                    self._media_cache_leases.update(leases)
                    return
                time.sleep(.02)
            for lease in leases.values():
                lease.__exit__(None, None, None)
        threading.Thread(target=release_after_close, name='media-cache-close-release', daemon=True).start()
        from .overlay_session import retire_overlay_session
        retire_overlay_session(self._compositor_overlay_dir,
            workers=(self._web_overlay_thread, self._video_overlay_thread, subtitle_thread),
            controller=detached)
        return detached
