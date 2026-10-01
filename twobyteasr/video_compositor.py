"""Qt video-frame compositor for overlapping Studio video tracks.

The lowest visible layer is the mpv base. This widget paints only overlays.
Each overlay is a SecondaryVideoSource that follows Project PlaybackClock via
ClipTimeMapper source timestamps. Overlay players never write the clock.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from time import perf_counter, perf_counter_ns
from typing import Any, Mapping

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

from .clip_time_mapper import frame_tolerance_ms
from .audio_playback_graph import AudioPlaybackDecision, AudioPlaybackGraph
from .secondary_video import SecondaryVideoSource, SourceState
from .studio_mpv import VIDEO_OVERLAY_ID, VIDEO_TRANSFORM_OVERLAY_ID


# ADR-0005（四十五轮）：混合模式 → QPainter 合成模式。
_BLEND_COMPOSITION_MODES = {
    "normal": QPainter.CompositionMode.CompositionMode_SourceOver,
    "screen": QPainter.CompositionMode.CompositionMode_Screen,
    "multiply": QPainter.CompositionMode.CompositionMode_Multiply,
    "overlay": QPainter.CompositionMode.CompositionMode_Overlay,
    "softLight": QPainter.CompositionMode.CompositionMode_SoftLight,
    "addition": QPainter.CompositionMode.CompositionMode_Plus,
}


def _hex_rgb(color: str) -> tuple[int, int, int]:
    value = QColor(str(color or "#00FF00"))
    return value.red(), value.green(), value.blue()


def apply_chroma_key(image: QImage, chroma: Mapping[str, Any]) -> QImage:
    """numpy 色键：RGB 距离掩码 → alpha；similarity 内全透，smoothness 带内渐变。

    spillSuppression：掩码边缘的绿色溢出钳制（g 不超过 max(r,b)+30）。
    输入假定 Format_ARGB32（set_composition 已统一转换）。
    """
    similarity = max(0.0, min(1.0, float(chroma.get("similarity", 0.32) or 0.0)))
    smoothness = max(0.0, min(1.0, float(chroma.get("smoothness", 0.10) or 0.0)))
    key_r, key_g, key_b = _hex_rgb(str(chroma.get("color") or "#00FF00"))
    spill = bool(chroma.get("spillSuppression", True))
    width, height = image.width(), image.height()
    if width <= 0 or height <= 0:
        return image
    source = image.convertToFormat(QImage.Format.Format_ARGB32)
    pixels = np.frombuffer(
        source.constBits(), dtype=np.uint8, count=source.sizeInBytes()
    ).reshape(source.height(), source.bytesPerLine() // 4, 4)[:, :width, :].copy()
    bgr = pixels[:, :, :3].astype(np.float32)
    # ARGB32 在小端 Windows 上按字节序是 B,G,R,A。
    blue = bgr[:, :, 0]
    green = bgr[:, :, 1]
    red = bgr[:, :, 2]
    distance = np.sqrt(
        (red - key_r) ** 2 + (green - key_g) ** 2 + (blue - key_b) ** 2
    ) / 441.673
    mask = np.clip((distance - similarity) / max(smoothness, 1e-3), 0.0, 1.0)
    if spill:
        edge = mask < 1.0
        green[edge] = np.minimum(green[edge], np.maximum(red[edge], blue[edge]) + 30.0)
        pixels[:, :, 1] = green.astype(np.uint8)
    pixels[:, :, 3] = (pixels[:, :, 3].astype(np.float32) * mask).astype(np.uint8)
    result = QImage(
        pixels.tobytes(), width, height, source.bytesPerLine(), QImage.Format.Format_ARGB32
    )
    return result.copy()


def _transform_dict(value: object) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


@dataclass(frozen=True)
class CompositionSample:
    project_ms: int
    track_id: str
    clip_id: str
    source_ms: int
    frame_pts_ms: int
    frame_age_ms: float
    decoder_generation: int
    visible: bool


def layer_geometry(width: float, height: float, layer: Mapping[str, Any], source_w: float = 0., source_h: float = 0.):
    transform = _transform_dict(layer.get("transform"))
    width = max(1.0, float(width))
    height = max(1.0, float(height))
    source_w = max(1.0, float(source_w or width))
    source_h = max(1.0, float(source_h or height))
    fit_mode = str(transform.get("fit_mode") or "contain")
    if fit_mode == "stretch":
        fitted_w, fitted_h = width, height
    else:
        factor = (
            max(width / source_w, height / source_h)
            if fit_mode == "cover"
            else min(width / source_w, height / source_h)
        )
        fitted_w, fitted_h = source_w * factor, source_h * factor
    fitted_w *= max(0.01, float(transform.get("scale_x", 1.0)))
    fitted_h *= max(0.01, float(transform.get("scale_y", 1.0)))
    anchor_x = max(0.0, min(1.0, float(transform.get("anchor_x", 0.5))))
    anchor_y = max(0.0, min(1.0, float(transform.get("anchor_y", 0.5))))
    local = QRectF(-anchor_x * fitted_w, -anchor_y * fitted_h, fitted_w, fitted_h)
    matrix = QTransform()
    matrix.translate(
        float(transform.get("position_x", 0.5)) * width,
        float(transform.get("position_y", 0.5)) * height,
    )
    matrix.rotate(float(transform.get("rotation", 0.0)))
    return local, matrix



class VideoCompositionScene(QWidget):
    """Paint overlay video clips above the dynamic mpv base and edit transforms."""

    transform_preview = Signal(str, str, object)
    transform_committed = Signal(str, str, object)

    HANDLE_SIZE = 14.0
    # 渲染合帧下限：多轨播放时每个播放器独立供帧（2x 下合计可达 N×120 次/秒），
    # 合成+发布只需要显示级速率。到达突发合并为单次全量渲染。
    MIN_RENDER_INTERVAL_S = 0.012

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studioVideoCompositionScene")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self._players: dict[str, SecondaryVideoSource] = {}
        self._warm_ids: set[str] = set()
        self._layers: list[dict[str, Any]] = []
        self._selected_clip_id = ""
        self._interaction_enabled = True
        self._video_aspect = 16 / 9
        if parent is not None:
            parent.installEventFilter(self)
        self._layer_polygons: dict[str, QPolygonF] = {}
        # 五十轮：mpv 承载的主轨层（served_by_mpv）不参与叠加绘制，但要保留
        # 引用——选中主轨片段时画布也要有变换框（此前只有叠加层可框选/拖拽）。
        self._base_layer: dict[str, Any] | None = None
        self._composes_base = False
        self._async_compositor = None
        self._async_video_active = False
        self._drag: dict[str, Any] | None = None
        self._secondary_frame_timestamps_ns: list[int] = []
        self._samples: deque[CompositionSample] = deque(maxlen=512)
        self._project_ms = 0
        # ADR-0005：色键结果按 (clip, pts, 参数签名) LRU——暂停/往复 scrub 命中。
        self._chroma_cache: dict[str, OrderedDict[tuple, QImage]] = {}
        self.audio_graph = AudioPlaybackGraph()
        self.audio_decision = AudioPlaybackDecision("")
        self._native_frames: tuple[QImage, QImage] | None = None
        self._rendered_frames: tuple[QImage, QImage] | None = None
        # A paint can arrive before the first update_layers (fresh scene,
        # offscreen first exposure); paintEvent must not raise on _paused.
        self._paused = True
        self._native_publish_timer = QTimer(self)
        self._native_publish_timer.setSingleShot(True)
        self._native_publish_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._native_publish_timer.timeout.connect(self._publish_native_frames)
        self._last_native_publish = 0.0
        self._native_publish_ms: deque[float] = deque(maxlen=512)
        self._native_publish_times: deque[float] = deque(maxlen=1200)
        self._composition_render_ms: deque[float] = deque(maxlen=512)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._render_timer.timeout.connect(self._render_timer_fired)
        self._render_dirty = False
        self._last_render_ts = 0.0
        self.hide()

    @property
    def has_video_overlays(self) -> bool:
        return bool(self._layers)

    def _publish_native_frames(self) -> None:
        frames, self._native_frames = self._native_frames, None
        owner = self.parentWidget()
        publish = getattr(owner, "publish_compositor_overlay", None)
        if not self.isVisible() or frames is None or not callable(publish):
            return
        start = perf_counter()
        for slot, frame in zip((VIDEO_OVERLAY_ID, VIDEO_TRANSFORM_OVERLAY_ID), frames):
            if slot == VIDEO_OVERLAY_ID and self._async_video_active:
                continue
            if slot == VIDEO_TRANSFORM_OVERLAY_ID:
                signature = (frame.cacheKey(), self.geometry().getRect())
                if signature == getattr(self, '_published_handles_signature', None):
                    continue
                self._published_handles_signature = signature
            if frame.isNull():
                owner.remove_compositor_overlay(slot, force=True)
            else:
                publish(slot, frame, self.geometry(), source_bounds=frame.rect(),
                        context={"caller": "video_compositor", "project_ms": self._project_ms})
        self._last_native_publish = perf_counter()
        self._native_publish_times.append(self._last_native_publish)
        self._native_publish_ms.append((self._last_native_publish - start) * 1000)

    def hideEvent(self, event) -> None:
        self._async_video_active=False
        if self._async_compositor is not None:self._async_compositor.configure(None)
        # Cancel queued work before clearing: a late decoder frame must not
        # resurrect a hidden track or an old project's bitmap.
        self._native_publish_timer.stop()
        self._render_timer.stop()
        self._render_dirty = False
        self._native_frames = None
        self._published_handles_signature = None
        remove = getattr(self.parentWidget(), "remove_compositor_overlay", None)
        if callable(remove):
            remove(VIDEO_OVERLAY_ID, force=True)
            remove(VIDEO_TRANSFORM_OVERLAY_ID, force=True)
        super().hideEvent(event)

    def _chroma_keyed_image(self, clip_id: str, image: QImage, chroma: Mapping[str, Any], pts_ms: int) -> QImage:
        signature = (
            int(pts_ms),
            str(chroma.get("color") or ""),
            round(float(chroma.get("similarity", 0.32) or 0.0), 4),
            round(float(chroma.get("smoothness", 0.10) or 0.0), 4),
            bool(chroma.get("spillSuppression", True)),
        )
        cache = self._chroma_cache.setdefault(clip_id, OrderedDict())
        hit = cache.get(signature)
        if hit is not None:
            cache.move_to_end(signature)
            return hit
        keyed = apply_chroma_key(image, chroma)
        cache[signature] = keyed
        while len(cache) > 6:
            cache.popitem(last=False)
        return keyed

    def _secondary_frame_arrived(self) -> None:
        self._secondary_frame_timestamps_ns.append(perf_counter_ns())
        if self._async_video_active:
            return
        if len(self._secondary_frame_timestamps_ns) > 1_200:
            del self._secondary_frame_timestamps_ns[:200]
        if self.isVisible() and callable(getattr(self.parentWidget(), 'publish_compositor_overlay', None)):
            # WM_PAINT is coalesced with the rest of the editor and can run
            # at 30–40Hz even when QVideoSink delivers 60Hz. Native video
            # publication follows decoded frames, independently of Qt paint.
            # 渲染合帧：到达间隔小于 MIN_RENDER_INTERVAL_S 的帧合并为一次
            # 渲染（定时到点补渲最后一次到达），多轨/倍速下渲染+发布次数
            # 与轨数解耦、被钉在显示级速率。
            now = perf_counter()
            elapsed = now - self._last_render_ts
            self._render_dirty = True
            if not self._render_timer.isActive():
                # Sibling decoders are polled in the same event-loop turn.
                # Rendering synchronously on V2's signal delays V3's poll and
                # then throttles its already-ready frame for another 12 ms.
                # A bounded 2 ms handover publishes both latest frames once;
                # subsequent arrivals never postpone the scheduled render.
                self._render_timer.start(
                    int(max(2.0, (self.MIN_RENDER_INTERVAL_S - elapsed) * 1000))
                )
        else:
            self.update()

    def _render_and_publish(self) -> None:
        self._render_dirty = False
        self._last_render_ts = perf_counter()
        self._render_composition()
        self._native_publish_timer.stop()
        self._publish_native_frames()

    def _render_timer_fired(self) -> None:
        if not self._render_dirty:
            return
        self._render_dirty = False
        if not (
            self.isVisible()
            and callable(getattr(self.parentWidget(), 'publish_compositor_overlay', None))
        ):
            return
        self._render_and_publish()

    def reset_performance_samples(self) -> None:
        self._secondary_frame_timestamps_ns.clear()
        self._native_publish_ms.clear()
        self._native_publish_times.clear()
        self._composition_render_ms.clear()

    def performance_snapshot(self) -> dict[str, object]:
        async_samples=list(self._async_compositor.samples) if self._async_compositor else []
        timestamps = self._secondary_frame_timestamps_ns
        intervals = [
            (right - left) / 1_000_000.0
            for left, right in zip(timestamps, timestamps[1:])
            if right > left
        ]
        ordered = sorted(intervals)
        p95 = (
            ordered[max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))]
            if ordered else None
        )
        duration_seconds = (
            (timestamps[-1] - timestamps[0]) / 1_000_000_000.0
            if len(timestamps) >= 2 else 0.0
        )
        fps = (len(timestamps) - 1) / duration_seconds if duration_seconds > 0 else 0.0
        now = perf_counter()
        recent_publishes = [ts for ts in self._native_publish_times if ts >= now - 2.]
        return {
            'composition_thread': 'worker' if self._async_video_active else 'gui',
            'worker_composition_p95_ms': round(float(np.percentile([row['composition_ms'] for row in async_samples],95)),3) if async_samples else None,
            'worker_submitted_frames': len(async_samples),
            "frame_count": len(timestamps),
            "duration_seconds": round(duration_seconds, 3),
            "fps": round(fps, 3),
            "interval_p95_ms": round(p95, 3) if p95 is not None else None,
            "players": len(self._players),
            "layers": len(self._layers),
            "native_publish_count": len(self._native_publish_ms),
            "native_publish_window_seconds": 2.,
            "native_publish_fps": round((len(recent_publishes)-1)/(recent_publishes[-1]-recent_publishes[0]), 3)
            if len(recent_publishes)>1 and now-recent_publishes[-1] < .5 else 0.,
            "native_publish_p95_ms": round(float(np.percentile(self._native_publish_ms, 95)), 3)
            if self._native_publish_ms else None,
            "render_p95_ms": round(float(np.percentile(self._composition_render_ms, 95)), 3)
            if self._composition_render_ms else None,
        }

    def telemetry(self) -> list[dict[str, object]]:
        return [asdict(item) for item in self._samples]

    def prewarm(self, layers: list[Mapping[str, Any]]) -> None:
        """Decode imminent clip entry frames without presenting or playing audio."""
        upcoming = list(layers[:2])
        self._warm_ids = {str(layer['clip_id']) for layer in upcoming}
        for layer in upcoming:
            clip_id = str(layer['clip_id'])
            runtime = self._players.get(clip_id)
            if runtime is None:
                runtime = SecondaryVideoSource(self)
                runtime.frame_updated.connect(self._secondary_frame_arrived)
                self._players[clip_id] = runtime
            runtime.prepare(str(layer['source_path']))
            runtime.request_frame(int(layer['source_ms']), paused=True, seek=True,
                                  seek_token=layer.get('seek_token'),
                                  audio_output_enabled=False, video_output_enabled=True)
        active = {str(layer['clip_id']) for layer in self._layers} | self._warm_ids
        idle = [key for key in self._players if key not in active]
        # Keep a few loaded decoders for backward/forward seeks, bounded by
        # clip count rather than retaining a whole project of native players.
        for key in idle[:-2]:
            runtime = self._players.pop(key)
            runtime.frame_updated.disconnect(self._secondary_frame_arrived)
            runtime.release(); runtime.deleteLater()

    def set_selected_clip(self, clip_id: str) -> None:
        selected = str(clip_id or "") if self._interaction_enabled else ""
        if selected == self._selected_clip_id:
            return
        self._selected_clip_id = selected
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            not bool(self._selected_clip_id),
        )
        self.update()

    def set_interaction_enabled(self, enabled: bool) -> None:
        """Export borrows the canvas for viewing, with no editing handles."""
        self._interaction_enabled = bool(enabled)
        self._drag = None
        if not enabled:
            self.set_selected_clip("")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          not enabled or not bool(self._selected_clip_id))

    def set_video_size(self, width: int, height: int) -> None:
        self._video_aspect = max(1, int(width)) / max(1, int(height))
        self._sync_viewport_geometry()

    def _sync_viewport_geometry(self) -> None:
        owner = self.parentWidget()
        if owner is None:
            return
        width, height = owner.width(), owner.height()
        fitted_w = min(width, height * self._video_aspect)
        fitted_h = fitted_w / self._video_aspect
        target = QRectF((width-fitted_w)/2, (height-fitted_h)/2,
                        fitted_w, fitted_h).toRect()
        if self.geometry() != target:
            self.setGeometry(target)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._sync_viewport_geometry()
            self.update()
        return super().eventFilter(watched, event)

    def set_composition(
        self,
        layers: list[Mapping[str, Any]],
        *,
        paused: bool,
        rate: float,
        audio_master_track_id: str,
        base_track_id: str,
        volume: float,
        solo_track_ids: tuple[str, ...] = (),
        audio_decision: AudioPlaybackDecision | None = None,
        audio_layers: list[Mapping[str, Any]] | None = None,
        seeking: bool = False,
        project_ms: int = 0,
        mpv_path: str = "",
        seek_generation: int | None = None,
        mpv_binding: tuple[str, str, str] | None = None,
    ) -> None:
        all_layers = [dict(layer) for layer in layers]
        self._project_ms = int(project_ms)
        self._paused = bool(paused)
        if not all_layers:
            self.suspend()
            return
        base_id = str(base_track_id or all_layers[0].get("track_id") or "")
        self.audio_graph.configure(
            master_track_id=str(audio_master_track_id or ""),
            solo_track_ids=solo_track_ids,
        )
        routing_layers = [dict(layer) for layer in (audio_layers or all_layers)]
        self.audio_decision = audio_decision or self.audio_graph.decide(
            routing_layers,
            base_track_id=base_id,
            volume=volume,
        )
        mpv_source = str(mpv_path or "").strip()
        overlays: list[dict[str, Any]] = []
        self._base_layer = None
        for layer in all_layers:
            source = str(layer.get("source_path") or "")
            # 四十八轮（用户"V2 完全不显示"根因）：旧判定有 `elif track_id ==
            # base_id and mpv_source: served_by_mpv = True` 的启发式——当层列
            # 表里没有主轨层（播放头落在 V1 剪辑空隙 / 主轨 clips 未物化）时，
            # 叠加层顶替成为 base，被误判"mpv 正在承载它"而直接跳过，叠加轨
            # 永不渲染。改为只认显式 primary_media 标记或源路径与 mpv 相等。
            served_by_mpv = bool(layer.get("primary_media"))
            if mpv_binding is not None:
                track_id, clip_id, bound_path = mpv_binding
                served_by_mpv = bool(bound_path and source and
                    str(layer.get('track_id') or '') == track_id and
                    str(layer.get('clip_id') or '') == clip_id and
                    Path(source).resolve() == Path(bound_path).resolve() == Path(mpv_source).resolve())
            elif "primary_media" not in layer and not served_by_mpv and mpv_source and source:
                try:
                    served_by_mpv = Path(source).resolve() == Path(mpv_source).resolve()
                except (OSError, ValueError):
                    served_by_mpv = source == mpv_source
            if not served_by_mpv:
                overlays.append(layer)
            elif self._base_layer is None:
                self._base_layer = layer
        # Native mpv pixels are not a QPainter destination. Non-normal blends
        # must include V1 in the same raster; otherwise multiply/screen operate
        # against transparency and differ from the exported composite.
        base_effects = (self._base_layer or {}).get("effects") or {}
        base_transform = _transform_dict((self._base_layer or {}).get("transform"))
        default_transform = dict(position_x=.5, position_y=.5, scale_x=1., scale_y=1.,
                                 rotation=0., opacity=1., anchor_x=.5, anchor_y=.5, fit_mode="contain")
        self._composes_base = bool(
            any((layer.get("effects") or {}).get("blendMode", "normal") != "normal" for layer in all_layers)
            or (base_effects.get("chromaKey") or {}).get("enabled")
            or any(base_transform.get(key, value) != value for key, value in default_transform.items())
        )
        if self._composes_base:
            overlays = all_layers
        base_selected = (
            self._base_layer is not None
            and str(self._base_layer.get("clip_id") or "") == self._selected_clip_id
        )
        if not overlays and not base_selected:
            self.suspend()
            return
        decoder_layers = list(overlays)
        active_ids = {str(layer["clip_id"]) for layer in decoder_layers}
        for clip_id in tuple(self._players):
            if clip_id not in active_ids and clip_id not in self._warm_ids:
                self._players[clip_id].suspend()
        for layer in decoder_layers:
            clip_id = str(layer["clip_id"])
            runtime = self._players.get(clip_id)
            if runtime is None:
                runtime = SecondaryVideoSource(self)
                runtime.frame_updated.connect(self._secondary_frame_arrived)
                self._players[clip_id] = runtime
            transform = _transform_dict(layer.get('transform'))
            # 1.25x screen sampling retains detail through rotation/resizing
            # without piping two full-HD rasters for tiny picture-in-picture.
            scale = max(abs(float(transform.get('scale_x',1))),abs(float(transform.get('scale_y',1))))
            dpr = self.devicePixelRatioF()
            runtime.set_preview_size(self.width()*dpr*scale*1.25,self.height()*dpr*scale*1.25)
            source_path = str(layer.get("source_path") or "")
            if source_path and runtime.state in {SourceState.IDLE, SourceState.FAILED, SourceState.RELEASED}:
                runtime.prepare(source_path)
            elif source_path and runtime._pending_path != str(Path(source_path)):
                runtime.prepare(source_path)
            runtime.request_frame(
                int(layer.get("source_ms") or 0),
                paused=paused,
                rate=rate * float(layer.get("playback_rate") or 1.0),
                volume=0.0,
                audio_output_enabled=False,
                video_output_enabled=True,
                seek=bool(seeking),
                seek_token=seek_generation,
            )
        self._layers = overlays
        owner = self.parentWidget()
        self._async_video_active = bool(not paused and overlays and callable(getattr(owner,'queue_video_raster',None)))
        if self._async_video_active:
            if self._async_compositor is None:
                from .video_composition_worker import VideoCompositionWorker
                self._async_compositor=VideoCompositionWorker(owner.queue_video_raster)
            owner._ensure_video_overlay_publisher()
            dpr=owner.devicePixelRatioF();rect=self.geometry()
            state=dict(size=(self.width(),self.height()),base=self._composes_base,project_ms=self._project_ms,
                publication_epoch=int(owner._video_overlay_epoch),
                display_rect=(round(rect.x()*dpr),round(rect.y()*dpr),round(rect.width()*dpr),round(rect.height()*dpr)),
                layers=[])
            for layer in overlays:
                runtime=self._players.get(str(layer['clip_id']))
                if runtime is None or runtime._pipe is None:continue
                copied=dict(layer)
                copied.update(path=runtime._pending_path,generation=runtime.generation,decode_epoch=runtime._epoch,
                              transform=_transform_dict(layer.get('transform')),effects=dict(layer.get('effects') or {}))
                state['layers'].append(copied)
                runtime._pipe.on_frame=lambda frame,key=str(layer['clip_id']),worker=self._async_compositor:worker.receive(key,frame)
            self._async_compositor.configure(state)
        elif self._async_compositor is not None:
            self._async_compositor.configure(None)
        self.setVisible(bool(overlays) or base_selected)
        # 五十轮：合成决策落 trace（签名变化时一次）——EXE 内叠加层黑盒五轮，
        # 现在从日志直接可见"哪些层进合成/谁被 mpv 服务/选了谁"。
        signature = (
            tuple((str(l.get("track_id")), str(l.get("clip_id"))) for l in overlays),
            str((self._base_layer or {}).get("clip_id") or ""),
            self._selected_clip_id,
            bool(overlays),
            base_selected,
        )
        if signature != getattr(self, "_last_composition_trace", None):
            self._last_composition_trace = signature
            from .runtime_trace import GLOBAL_STUDIO_TRACE

            GLOBAL_STUDIO_TRACE.emit(
                "COMPOSITION",
                {
                    "overlays": len(overlays),
                    "base_clip": str((self._base_layer or {}).get("clip_id") or ""),
                    "selected": self._selected_clip_id,
                    "visible": bool(overlays) or base_selected,
                    "project_ms": self._project_ms,
                },
            )
        if paused or not overlays:
            self.update()

    def suspend(self) -> None:
        self._async_video_active=False
        if self._async_compositor is not None:self._async_compositor.configure(None)
        for key, runtime in self._players.items():
            if key not in self._warm_ids:
                runtime.suspend()
        self._layers.clear()
        self._layer_polygons.clear()
        self._base_layer = None
        self._drag = None
        self.hide()

    def clear(self) -> None:
        self._async_video_active=False
        if self._async_compositor is not None:
            self._async_compositor.close();self._async_compositor=None
        probe = self._close_probe
        for runtime in self._players.values():
            probe("clear-before-disconnect")
            try:
                runtime.frame_updated.disconnect(self._secondary_frame_arrived)
            except (RuntimeError, TypeError):
                pass
            probe("clear-before-release")
            runtime.release()
            probe("clear-after-release")
            delete_later = getattr(runtime, "deleteLater", None)
            if callable(delete_later):
                delete_later()
            probe("clear-after-deleteLater")
        self._players.clear()
        self._warm_ids.clear()
        self._layers.clear()
        self._layer_polygons.clear()
        self._base_layer = None
        self._drag = None
        self._secondary_frame_timestamps_ns.clear()
        probe("clear-before-hide")
        self.hide()
        probe("clear-after-hide")

    def _close_probe(self, step: str) -> None:
        import os

        if os.environ.get("TWOBYTEASR_CLOSE_GIL_PROBE") != "1":
            return
        try:
            from time import perf_counter

            with open(
                os.path.join(os.environ["LOCALAPPDATA"], "close-gil-probe.log"),
                "a", encoding="utf8",
            ) as fh:
                fh.write(f"gui step={step} t={perf_counter():.3f}\n")
        except OSError:
            pass

    def _layer_geometry(self, layer, source_w=0., source_h=0.):
        return layer_geometry(self.width(), self.height(), layer, source_w, source_h)

    def paintEvent(self, event) -> None:
        if self._paused or not self._layers or self._rendered_frames is None:
            self._render_composition()
        if self._rendered_frames is not None:
            painter = QPainter(self)
            for frame in self._rendered_frames:
                if not frame.isNull(): painter.drawImage(self.rect(), frame)
        if not self._native_publish_timer.isActive():
            self._native_publish_timer.start(0)

    def _render_composition(self) -> None:
        render_start = perf_counter()
        # Native --wid video bypasses Qt's backing store. Render once into
        # shared rasters, then mirror them to mpv at a bounded cadence.
        # Do not rasterize a 1080p overlay into a 4K bitmap only to write it to
        # disk sixty times a second. mpv scales the preview to the viewport;
        # editing coordinates and export resolution remain unchanged.
        raster_size = self.size()
        if raster_size.width() > 1920 or raster_size.height() > 1080:
            raster_size = raster_size.scaled(1920, 1080, Qt.AspectRatioMode.KeepAspectRatio)
        raster_scale = QTransform.fromScale(raster_size.width()/max(1, self.width()),
                                           raster_size.height()/max(1, self.height()))
        frame = QImage(raster_size, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(Qt.GlobalColor.black if self._composes_base else Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        selected_polygon = None
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._layer_polygons.clear()
        now = perf_counter()
        painted_overlays = 0
        for layer in self._layers:
            clip_id = str(layer.get("clip_id") or "")
            runtime = self._players.get(clip_id)
            requested = int(layer.get("source_ms") or 0)
            fps = float(layer.get("fps") or 30.0)
            tolerance = frame_tolerance_ms(fps)
            visible = False
            pts = -1
            age = 0.0
            generation = 0
            image = getattr(runtime, "image", None) if runtime is not None else None
            if runtime is not None and isinstance(image, QImage) and not image.isNull():
                pts = int(getattr(runtime, "pts_ms", requested))
                generation = int(getattr(runtime, "generation", 0) or 0)
                age = float(getattr(runtime, "frame_age_ms", 0.0) or 0.0)
                delta = abs(pts - requested) if pts >= 0 else 0
                # 四十六轮（用户 1080p60 素材实录"只有声音没有画面"根因）：
                # 播放中解码出帧天然滞后于请求的源时刻（大帧可达数百 ms），
                # 此前 42ms 硬容差把这类帧恒判不可见。帧龄判据区分两态：
                # 播放中帧流恒新鲜（age 小）→ 可见；暂停静止时无新帧、age
                # 增长 → 回落到 pts 精确匹配（冻结帧位置准确）。delta 上限
                # 防止跨剪辑点错帧。
                frame_fresh = 0.0 <= age <= 600.0 and delta <= 1500
                # 五十轮 EXE：暂停收敛帧可能落在 42-500ms 窗（就近暂停保底），
                # 暂停态放宽到 500ms 兜底显示，避免"解出帧却恒不可见"。
                paused_fallback = bool(getattr(self, "_paused", False)) and delta <= 500
                holding_seek = getattr(runtime, "_image_generation", generation) != generation
                if delta <= max(tolerance, 42) or pts < 0 or frame_fresh or paused_fallback or holding_seek:
                    visible = True
                    painted_overlays += 1
                    local, matrix = self._layer_geometry(layer, image.width(), image.height())
                    polygon = matrix.map(QPolygonF(local))
                    self._layer_polygons[clip_id] = polygon
                    transform = _transform_dict(layer.get("transform"))
                    effects = layer.get("effects") if isinstance(layer.get("effects"), Mapping) else {}
                    chroma = effects.get("chromaKey") if isinstance(effects, Mapping) else None
                    if isinstance(chroma, Mapping) and chroma.get("enabled"):
                        image = self._chroma_keyed_image(clip_id, image, chroma, pts)
                    painter.save()
                    painter.setOpacity(max(0.0, min(1.0, float(transform.get("opacity", 1.0)))))
                    blend = _BLEND_COMPOSITION_MODES.get(
                        str((effects or {}).get("blendMode") or "normal")
                    )
                    if blend is not None and blend != QPainter.CompositionMode.CompositionMode_SourceOver:
                        painter.setCompositionMode(blend)
                    painter.setTransform(matrix * raster_scale, combine=False)
                    painter.drawImage(local, image)
                    painter.restore()
                    if clip_id == self._selected_clip_id:
                        selected_polygon = polygon
            self._samples.append(
                CompositionSample(
                    project_ms=self._project_ms,
                    track_id=str(layer.get("track_id") or ""),
                    clip_id=clip_id,
                    source_ms=requested,
                    frame_pts_ms=pts,
                    frame_age_ms=round(age or (now * 1000.0), 3),
                    decoder_generation=generation,
                    visible=visible,
                )
            )
        # 五十轮：选中的主轨片段（mpv 承载，不在叠加绘制循环里）也画变换框
        # ——否则只有最上层叠加层能在画布上拖拽/缩放（用户"下层的解锁了
        # 也不能使用"）。几何按层自带的源尺寸 + transform 计算。
        # 每秒至多一条绘制摘要：EXE 侧"有层无帧/有帧不画"从此可从日志分辨。
        if now - getattr(self, "_last_paint_trace", 0.0) >= 1.0:
            self._last_paint_trace = now
            from .runtime_trace import GLOBAL_STUDIO_TRACE

            GLOBAL_STUDIO_TRACE.emit(
                "COMPOSITION_PAINT",
                {
                    "layers": len(self._layers),
                    "painted": painted_overlays,
                    "players": len(self._players),
                    "visible": self.isVisible(),
                    "w": int(self.width()),
                    "h": int(self.height()),
                    "poly_w": int(self._layer_polygons[self._selected_clip_id].boundingRect().width()) if (self._selected_clip_id and self._selected_clip_id in self._layer_polygons) else -1,
                    "project_ms": self._project_ms,
                },
            )
        base = self._base_layer
        if base is not None and str(base.get("clip_id") or "") == self._selected_clip_id:
            if not bool(base.get("track_locked")):
                local, matrix = self._layer_geometry(
                    base, float(base.get("source_w") or 0.0), float(base.get("source_h") or 0.0)
                )
                polygon = matrix.map(QPolygonF(local))
                self._layer_polygons[self._selected_clip_id] = polygon
                selected_polygon = polygon
        painter.end()
        handle_key = (self.width(), self.height(), self._selected_clip_id,
                      tuple((point.x(), point.y()) for point in selected_polygon) if selected_polygon else ())
        if handle_key != getattr(self, '_handle_raster_key', None):
            handles = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied) if selected_polygon else QImage()
            if not handles.isNull():
                handles.fill(Qt.GlobalColor.transparent)
                gizmo = QPainter(handles)
                gizmo.setPen(QPen(QColor("#50E3A4"), 2.0))
                gizmo.setBrush(Qt.BrushStyle.NoBrush)
                gizmo.drawPolygon(selected_polygon)
                handle = selected_polygon.boundingRect().bottomRight()
                gizmo.fillRect(QRectF(handle.x()-self.HANDLE_SIZE/2, handle.y()-self.HANDLE_SIZE/2,
                                     self.HANDLE_SIZE, self.HANDLE_SIZE), QColor("#50E3A4"))
                gizmo.end()
            self._handle_raster_key, self._handle_raster = handle_key, handles
        handles = self._handle_raster
        self._native_frames = (
            frame if painted_overlays else QImage(),
            handles,
        )
        self._rendered_frames = self._native_frames
        self._composition_render_ms.append((perf_counter() - render_start) * 1000)

    def _selected_layer(self) -> dict[str, Any] | None:
        for layer in self._layers:
            if str(layer.get("clip_id")) == self._selected_clip_id:
                return layer
        base = self._base_layer
        if base is not None and str(base.get("clip_id") or "") == self._selected_clip_id:
            return base
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._interaction_enabled or event.button() != Qt.MouseButton.LeftButton:
            return
        layer = self._selected_layer()
        polygon = self._layer_polygons.get(self._selected_clip_id)
        if layer is None or polygon is None:
            return
        if bool(layer.get("track_locked")):
            return
        point = event.position()
        bounds = polygon.boundingRect()
        handle = bounds.bottomRight()
        handle_rect = QRectF(
            handle.x() - self.HANDLE_SIZE,
            handle.y() - self.HANDLE_SIZE,
            self.HANDLE_SIZE * 2,
            self.HANDLE_SIZE * 2,
        )
        if handle_rect.contains(point):
            mode = "resize"
        elif polygon.containsPoint(point, Qt.FillRule.WindingFill):
            mode = "move"
        else:
            return
        self._drag = {
            "mode": mode,
            "start": QPointF(point),
            "transform": _transform_dict(layer.get("transform")),
            "bounds": QRectF(bounds),
            "track_id": str(layer.get("track_id") or ""),
            "clip_id": str(layer.get("clip_id") or ""),
        }
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag is None:
            return
        values = dict(self._drag["transform"])
        delta = event.position() - self._drag["start"]
        if self._drag["mode"] == "move":
            values["position_x"] = float(values.get("position_x", 0.5)) + delta.x() / max(1, self.width())
            values["position_y"] = float(values.get("position_y", 0.5)) + delta.y() / max(1, self.height())
        else:
            bounds = self._drag["bounds"]
            values["scale_x"] = max(0.01, float(values.get("scale_x", 1.0)) * (bounds.width() + delta.x()) / max(1.0, bounds.width()))
            values["scale_y"] = max(0.01, float(values.get("scale_y", 1.0)) * (bounds.height() + delta.y()) / max(1.0, bounds.height()))
        layer = self._selected_layer()
        if layer is not None:
            layer["transform"] = values
        self.transform_preview.emit(self._drag["track_id"], self._drag["clip_id"], values)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag is None or event.button() != Qt.MouseButton.LeftButton:
            return
        layer = self._selected_layer()
        values = _transform_dict(layer.get("transform")) if layer else dict(self._drag["transform"])
        track_id = self._drag["track_id"]
        clip_id = self._drag["clip_id"]
        self._drag = None
        self.releaseMouse()
        self.transform_committed.emit(track_id, clip_id, values)
        event.accept()

    def closeEvent(self, event) -> None:
        self.clear()
        super().closeEvent(event)


__all__ = ["CompositionSample", "VideoCompositionScene"]
