"""Advanced LIVE preview canvas plus the pixel-metrics helpers used to
gate fidelity frames against live renders."""

from __future__ import annotations

import threading
import numpy as np
from collections.abc import Mapping
from time import perf_counter

from PySide6.QtCore import QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QWidget

from .advanced_live_renderer import (
    composite_live_scene_layers,
    composition_pivot_for_snapshot,
    render_live_layers,
)
from .live_layer_cache import GLOBAL_LIVE_LAYER_CACHE, live_layer_cache_key
from .visual_design_graph import (
    CompiledLiveScene,
    compile_live_scene_cached,
    cue_motion_phase,
    graph_from_style_recipe,
    motion_phases,
)

def _count_stroke_pixels(pixmap, stroke_colors, *, stride: int = 2) -> int:
    """Count opaque samples within tolerance of any canonical stroke color.

    Canonical stroke colors are ``#AARRGGBB``. Rendered frames keep a
    transparent backdrop, so transparent pixels must not count (a dropped
    stroke ring would otherwise "match" whatever the premultiplied backdrop
    decodes to). RGB distance decides among opaque pixels only — this is a
    parity gate, not a colorimetric audit.
    """
    if pixmap is None or pixmap.isNull():
        return 0
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    references = []
    for color_text in stroke_colors:
        color = QColor(color_text)
        if color.isValid():
            references.append((color.red(), color.green(), color.blue()))
    if not references:
        return 0
    tolerance = 24
    pixels=np.ndarray((image.height(),image.width(),4),dtype=np.uint8,
        buffer=image.constBits(),strides=(image.bytesPerLine(),4,1))[::stride,::stride]
    opaque=pixels[:,:,3]>40
    colors=pixels[:,:,:3].astype(np.int16)
    matched=np.zeros(opaque.shape,dtype=bool)
    for reference in references:
        matched |= np.all(np.abs(colors-np.asarray(reference,dtype=np.int16))<=tolerance,axis=2)
    return int(np.count_nonzero(opaque & matched))


def _pixmap_alpha_metrics(pixmap, *, stride: int = 2) -> dict[str, object]:
    if pixmap is None or pixmap.isNull():
        return {"alpha": 0, "coverage": 0.0, "occupancy": 0.0, "bbox": None}
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    alpha=np.ndarray((height,width,4),dtype=np.uint8,buffer=image.constBits(),
        strides=(image.bytesPerLine(),4,1))[::stride,::stride,3]
    ys,xs=np.nonzero(alpha>40)
    alpha_count=int(len(xs))
    if not alpha_count:
        return {"alpha": 0, "coverage": 0.0, "occupancy": 0.0, "bbox": None}
    min_x,min_y,max_x,max_y=(int(xs.min())*stride,int(ys.min())*stride,int(xs.max())*stride,int(ys.max())*stride)
    bbox_width = max_x - min_x + stride
    bbox_height = max_y - min_y + stride
    canvas_area = max(1, width * height)
    bbox_area = max(1, bbox_width * bbox_height)
    sampled_bbox_area = max(1, (bbox_width // stride + 1) * (bbox_height // stride + 1))
    return {
        "alpha": alpha_count,
        "coverage": bbox_area / canvas_area,
        "occupancy": alpha_count / sampled_bbox_area,
        "bbox": (min_x, min_y, bbox_width, bbox_height),
        "size": (width, height),
    }


def _canonical_fill_colors(fill: object) -> list[str]:
    if isinstance(fill, str):
        return [fill]
    if not isinstance(fill, Mapping):
        return []
    result: list[str] = []
    color = str(fill.get("color") or "").strip()
    if color:
        result.append(color)
    for item in fill.get("stops", ()) if isinstance(fill.get("stops"), (list, tuple)) else ():
        if isinstance(item, Mapping) and str(item.get("color") or "").strip():
            result.append(str(item["color"]))
    return list(dict.fromkeys(result))


def compiled_scene_for_snapshot(snapshot):
    """Shared Card/Studio/timing binding through the one cached scene compiler."""
    if snapshot is None:
        return None
    recipe = getattr(snapshot, "style_recipe", None)
    graph_payload = (
        recipe.get("visualGraph") if isinstance(recipe, Mapping) else None
    )
    if not (isinstance(graph_payload, Mapping) and graph_payload):
        motion = getattr(snapshot, "motion_recipe", None)
        motion = motion if isinstance(motion, Mapping) else {}
        if str(motion.get("mode") or "") != "none" or any(
            motion.get(key) for key in ("entrance", "hold", "exit")
        ):
            source = (
                recipe if isinstance(recipe, Mapping)
                else {"name": "legacy motion", "motion": motion}
            )
            try:
                graph_payload = graph_from_style_recipe(source).to_dict()
            except (TypeError, ValueError):
                graph_payload = None
    if not (isinstance(graph_payload, Mapping) and graph_payload):
        return None
    cue_duration_ms = max(
        1,
        int(getattr(snapshot, "end_ms", 0)) - int(getattr(snapshot, "start_ms", 0)),
    )
    return compile_live_scene_cached(graph_payload, cue_duration_ms=cue_duration_ms)


_UNPREPARED_SCENE = object()


class AdvancedLiveCanvas(QLabel):
    """Non-native child canvas layered in the Studio video surface."""

    live_layers_ready = Signal(int, str, object)

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self._owner = owner
        self._base_rect = QRect()
        self._source = QPixmap()
        self._display_source = QPixmap()
        self._source_image = QImage()
        self._layer_images: dict[str, QImage] = {}
        self._mpv_bounds_hint = QRect()
        self._snapshot = None
        self._compiled_scene = None
        self._composition_pivot = QPointF()
        self._layer_generation = 0
        self._visual_binding = None
        self._layer_pipeline_started_for = -1
        self._layer_render_geometry = (0, 0, 1.0)
        self._last_frame_signature: tuple[int, bool] | None = None
        self._last_sync_profile: dict[str, float] = {}
        self._last_frame_trace_perf = 0.0
        self._last_frame_trace_relative_ms: int | None = None
        self._display_opacity = 1.0
        self._transform_preview = {}
        self._timing_preview = None
        self._publication_revoked = False
        self._last_mpv_publish_signature: tuple[object, ...] | None = None
        self._overlay_reason = "visual_update"
        self._overlay_cue_active = False
        self.setObjectName("advancedLiveCanvas")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(True)
        self.setStyleSheet("background:transparent;border:0")
        self._composition_space = "video-canvas"
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self.live_layers_ready.connect(self._accept_live_layers)

    def set_overlay_lifecycle_context(self, *, reason: str, cue_active: bool) -> None:
        self._overlay_reason, self._overlay_cue_active = str(reason or "sync"), bool(cue_active)

    def _overlay_context(self, caller: str) -> dict[str, object]:
        snapshot = self._snapshot
        scene = self._compiled_scene
        graph_hash = str(getattr(scene, "graph_hash", "") or "")
        return {
            **getattr(self,'_web_frame_context',{}),
            "cue_id": str(getattr(snapshot, "cue_id", "") or ""), "renderer_path": "VISUAL_GRAPH",
            "caller": caller, "reason": self._overlay_reason,
            "cue_active": self._overlay_cue_active, "scene_alive": not self._display_source.isNull(),
            "opacity": float(self._display_opacity), "scene_id": graph_hash, "visualGraph_hash": graph_hash,
        }

    def set_visual(self, pixmap: QPixmap, snapshot, *, animate_graph: bool = True, prepared_scene=_UNPREPARED_SCENE, known_snapshot_hash=None) -> None:
        self._publication_revoked = False
        snapshot_hash = known_snapshot_hash if known_snapshot_hash is not None else snapshot.stable_hash() if snapshot is not None else ""
        binding = (pixmap.cacheKey(), snapshot_hash, bool(animate_graph))
        if (
            not self._source.isNull()
            and self._visual_binding == binding
        ):
            self._publish_to_mpv()
            return
        self._visual_binding = binding
        self._source = QPixmap(pixmap)
        self._display_source = QPixmap(pixmap)
        self._source_image = pixmap.toImage()
        self._mpv_bounds_hint = QRect(self._source_image.rect())
        self._snapshot = snapshot
        self._compiled_scene = self._compile_snapshot_scene() if prepared_scene is _UNPREPARED_SCENE else prepared_scene
        dpr = float(pixmap.devicePixelRatio() or 1.0)
        width = max(1, round(pixmap.width() / dpr))
        height = max(1, round(pixmap.height() / dpr))
        self._layer_render_geometry = (width, height, dpr)
        self._composition_pivot = (
            composition_pivot_for_snapshot(snapshot, width, height)
            if snapshot is not None else QPointF()
        )
        self._layer_images = {}
        self._layer_generation += 1
        # A Fidelity takeover keeps the compiled scene and its live layer
        # pipeline: the static frame is a fill-in until layer rasters arrive,
        # and resumed playback must animate again without a new set_visual.
        if animate_graph and self._compiled_scene is not None:
            self._start_live_layer_pipeline()
        self._last_frame_signature = None
        self._rescale()

    def _start_live_layer_pipeline(self) -> None:
        """Render per-layer rasters for the current snapshot, once per generation.

        The generation guard makes repeated calls (Fidelity takeover followed
        by playback resume) idempotent: at most one pipeline per visual swap.
        """
        snapshot = self._snapshot
        if (
            snapshot is None
            or self._compiled_scene is None
            # Pure static scenes already have their full composite. Effect
            # layers still need their compositor post-processing even when
            # there are no explicit motion tracks (e.g. GLITCH/RGB_SPLIT).
            or (not self._compiled_scene.tracks
                and not self._compiled_scene.graph.effect_layers)
            or self._layer_images
            or self._layer_pipeline_started_for == self._layer_generation
        ):
            return
        self._layer_pipeline_started_for = self._layer_generation
        width, height, dpr = self._layer_render_geometry
        if width < 1 or height < 1:
            return
        generation = self._layer_generation
        snapshot_hash = snapshot.stable_hash()
        cache_key = live_layer_cache_key(
            snapshot, width=width, height=height, device_pixel_ratio=dpr,
        )

        def prepare_layers() -> None:
            try:
                # Cache hit: replay the cue from cropped bbox-local rasters
                # instead of re-running glyph layout / stroke / halo rastering.
                layers = GLOBAL_LIVE_LAYER_CACHE.materialize(
                    cache_key, snapshot=snapshot,
                )
                if layers is None:
                    layers = render_live_layers(
                        snapshot,
                        width=width,
                        height=height,
                        device_pixel_ratio=dpr,
                    )
                    GLOBAL_LIVE_LAYER_CACHE.store(cache_key, layers)
                self.live_layers_ready.emit(generation, snapshot_hash, layers)
            except (RuntimeError, TypeError, ValueError):
                # The already-published composite remains the LIVE fallback.
                pass

        if QApplication.platformName().casefold() == "offscreen":
            prepare_layers()
        else:
            threading.Thread(
                target=prepare_layers,
                daemon=True,
                name="advanced-live-layers",
            ).start()

    def _accept_live_layers(
        self,
        generation: int,
        snapshot_hash: str,
        layers: object,
    ) -> None:
        if (
            self.isHidden()
            or generation != self._layer_generation
            or self._snapshot is None
            or self._snapshot.stable_hash() != snapshot_hash
            or not isinstance(layers, Mapping)
            or not layers
            or self._compiled_scene is None
        ):
            return
        signature = self._last_frame_signature
        absolute_ms = (
            int(signature[0])
            if signature is not None and int(signature[0]) >= 0
            else int(self._snapshot.start_ms)
        )
        relative_ms = max(0, absolute_ms - int(self._snapshot.start_ms))
        duration_ms = max(
            1, int(self._snapshot.end_ms) - int(self._snapshot.start_ms)
        )
        hold_frame, _hold_sample = composite_live_scene_layers(
            layers,
            self._compiled_scene,
            min(900, duration_ms // 2),
            pivot=self._composition_pivot,
        )
        # Keep full-canvas rasters for Qt display so a cropped composition is
        # never stretched across the video frame (the magenta-halftone P0).
        self._layer_images = layers
        # mpv publish geometry: the display raster stays full-canvas, so the
        # overlay must be anchored at the canvas origin; the content bbox is
        # communicated through source_bounds and the publisher crops to it.
        # Anchoring the full-canvas raster AT the bbox offset (the old
        # behavior) pushed the subtitle off-screen the moment background
        # layers arrived — the "1-2 frames then vanish" regression.
        bounds = QRegion(QPixmap.fromImage(hold_frame).mask()).boundingRect()
        if not bounds.isEmpty():
            padding = max(24, round(max(bounds.width(), bounds.height()) * 0.18))
            bounds = bounds.adjusted(
                -padding, -padding, padding, padding
            ).intersected(hold_frame.rect())
        self._mpv_bounds_hint = QRect(bounds) if not bounds.isEmpty() else QRect(hold_frame.rect())
        composite, _sample = composite_live_scene_layers(
            self._layer_images, self._compiled_scene, relative_ms,
            pivot=self._composition_pivot,
        )
        if not composite.isNull():
            self._source_image = composite
            self._source = QPixmap.fromImage(composite)
            self._rescale()

    def _publish_to_mpv(self) -> None:
        if self._publication_revoked:
            return
        publisher = getattr(self._owner, "publish_compositor_overlay", None)
        signature = (
            int(self._display_source.cacheKey()) if not self._display_source.isNull() else 0,
            tuple(self.geometry().getRect()),
            round(float(self._display_opacity), 2),
        )
        if signature == self._last_mpv_publish_signature:
            return
        self._last_mpv_publish_signature = signature
        # Publishing is not gated on Qt visibility: a cue-entry publish must
        # land in the same event-loop turn as set_visual, before the owner
        # arbiter shows the canvas — gating here blanked the first 1-2 frames
        # of every advanced cue. Removal is exclusively owned by hideEvent,
        # which the arbiter triggers synchronously whenever the cue stops
        # owning the foreground, so a hidden canvas cannot ghost the overlay.
        if (
            callable(publisher)
            and not self._display_source.isNull()
            and not self.geometry().isEmpty()
        ):
            # The display raster is always full-canvas and anchored at the
            # canvas rect on screen; source_bounds carries the content bbox
            # and the publisher crops to it. There is deliberately no
            # re-anchoring branch: shifting a full-canvas raster to an
            # in-bitmap offset pushed subtitles off-screen.
            prepared=getattr(self,'_prepared_raw_pixels',None)
            extra={'prepared_pixels':prepared[1]} if prepared and prepared[0]==self._display_source.cacheKey() and self._display_opacity>=.999 else {}
            publisher(
                self._owner.ADVANCED_OVERLAY_ID,
                self._display_source,
                QRect(self.geometry()),
                opacity=self._display_opacity,
                source_bounds=self._mpv_bounds_hint,
                phase=(
                    cue_motion_phase(
                        max(0, int(self._last_frame_signature[0]) - int(self._snapshot.start_ms)),
                        entrance_end_ms=motion_phases(self._compiled_scene.graph).entrance_end_ms,
                        exit_start_ms=motion_phases(self._compiled_scene.graph).exit_start_ms,
                        cue_duration_ms=max(1, int(self._snapshot.end_ms) - int(self._snapshot.start_ms)),
                    )
                    if self._snapshot is not None and self._compiled_scene is not None and self._last_frame_signature is not None
                    else "",
                ),
                context=self._overlay_context("AdvancedLiveCanvas._publish_to_mpv"),
                **extra,
            )

    def publish_web_frame(self, payload, image_size=None) -> bool:
        """二十七轮：web-live 帧的 30fps 快速通道入口。

        ``payload`` 是原始 PNG bytes（worker 不再同步解码）。GUI 线程只算
        全帧显示几何，解码/裁剪/写盘/mpv 投递交给 owner 的发布线程。
        owner 不具备快速通道时回退 set_visual（测试桩）。返回 False 表示
        快速会话已关闭（清场后的迟到帧）——调用方据此重走首帧重开会话。
        """
        owner = self._owner
        fast = getattr(owner, "publish_web_live_overlay", None)
        if not callable(fast):
            # 兜底（测试桩）：在此解码走原路径。
            from .live_web_preview import _decode_frame

            decoded = _decode_frame(payload) if isinstance(payload, (bytes, bytearray)) else None
            if decoded is None:
                return False
            pixmap = QPixmap.fromImage(decoded[0])
            self.set_visual(pixmap, self._snapshot, animate_graph=False)
            return True
        target_rect = QRect(self.geometry())
        if target_rect.isEmpty() or not payload:
            return False
        # QWidget geometry 是设备无关逻辑坐标；mpv overlay-add 寻址物理
        # D3D 输出面——125/150/175/200% Windows 缩放下必须乘 dpr。
        dpr = max(1.0, float(owner.devicePixelRatioF()))
        full_rect = QRect(
            round(target_rect.x() * dpr),
            round(target_rect.y() * dpr),
            max(1, round(target_rect.width() * dpr)),
            max(1, round(target_rect.height() * dpr)),
        )
        return bool(
            fast(
                owner.ADVANCED_OVERLAY_ID,
                payload,
                full_rect,
                context=self._overlay_context("AdvancedLiveCanvas.publish_web_frame"),
            )
        )

    def set_web_mirror_frame(self, pixmap: QPixmap) -> None:
        """二十七轮：web-live 帧的 Qt 侧镜像（降频更新）。

        mpv overlay 才是播放期用户可见的路径；Qt 标签被 mpv 原生窗口盖住，
        只服务 offscreen 测试/诊断，因此不触发 mpv 重发布（省一次全画布拷贝）。
        """
        if pixmap is None or pixmap.isNull():
            return
        self._display_source = pixmap
        self._source = pixmap
        self.setPixmap(pixmap)

    def showEvent(self, event) -> None:
        self._publication_revoked = False
        super().showEvent(event)
        self._last_mpv_publish_signature = None
        QTimer.singleShot(0, self._publish_to_mpv)

    def revoke_publication(self) -> None:
        """Retire published pixels even when the Qt widget is already hidden."""
        self._publication_revoked = True
        remover = getattr(self._owner, "remove_compositor_overlay", None)
        if callable(remover):
            remover(self._owner.ADVANCED_OVERLAY_ID,
                    context=self._overlay_context("AdvancedLiveCanvas.revoke_publication"))
        self._last_mpv_publish_signature = None

    def clear(self) -> None:
        """Discard retained render state, not only QLabel's displayed pixmap."""
        self.revoke_publication()
        self._layer_generation += 1
        self._snapshot = None
        self._compiled_scene = None
        self._source = QPixmap()
        self._display_source = QPixmap()
        self._source_image = QImage()
        self._layer_images = {}
        self._visual_binding = None
        self._last_frame_signature = None
        self._transform_preview = {}
        self._timing_preview = None
        self._mpv_bounds_hint = QRect()
        super().clear()

    def hideEvent(self, event) -> None:
        self.revoke_publication()
        super().hideEvent(event)

    def set_base_geometry(self, rect: QRect) -> None:
        stable_rect = QRect(rect)
        if stable_rect == self._base_rect:
            return
        self._base_rect = stable_rect
        self.setGeometry(stable_rect)
        self._rescale()

    def _rescale(self, scale: float = 1.0, source: QPixmap | None = None) -> None:
        active = source if source is not None else self._source
        if active.isNull() or self._base_rect.isEmpty():
            return
        snapshot = self._snapshot
        override = self._transform_preview
        if override and snapshot is not None:
            # Transform the already rasterized subtitle, not the video. The
            # full-canvas origin stays fixed for mpv's source-bounds contract.
            image = QImage(active.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            sx, sy = active.width() / snapshot.playres_x, active.height() / snapshot.playres_y
            x, y = float(override.get("position_x", snapshot.position_x)), float(override.get("position_y", snapshot.position_y))
            ratio = float(override.get("font_size", snapshot.font_size)) / max(1., snapshot.font_size)
            ax=float(override.get('preview_anchor_x',snapshot.position_x))
            ay=float(override.get('preview_anchor_y',snapshot.position_y))
            painter.translate((ax+x-snapshot.position_x) * sx, (ay+y-snapshot.position_y) * sy)
            painter.scale(ratio, ratio)
            painter.translate(-ax * sx, -ay * sy)
            source_image = active.toImage()
            source_image.setDevicePixelRatio(1.)  # Painter coordinates here are physical pixels.
            painter.drawImage(0, 0, source_image)
            painter.end()
            image.setDevicePixelRatio(active.devicePixelRatio())
            active = QPixmap.fromImage(image)
            self._mpv_bounds_hint = QRect(image.rect())
        self._display_source = QPixmap(active)
        self.setPixmap(active)
        self._publish_to_mpv()

    def set_transform_preview(self, values: dict) -> None:
        self._transform_preview = dict(values)
        self._rescale()

    def set_timing_preview(self, start_ms=None, end_ms=None) -> None:
        value = (int(start_ms), int(end_ms)) if start_ms is not None else None
        if value != self._timing_preview:
            self._timing_preview = value
            self._last_frame_signature = None

    def _compile_snapshot_scene(self):
        return compiled_scene_for_snapshot(self._snapshot)

    def sync_time(self, absolute_ms: int, *, paused: bool = False) -> None:
        snapshot = self._snapshot
        if snapshot is None or self._base_rect.isEmpty():
            return
        if self._compiled_scene is None:
            # Snapshots can be swapped without set_visual (direct assignment
            # in tests and callers); compile lazily through the same owner.
            self._compiled_scene = self._compile_snapshot_scene()
        if self._compiled_scene is None or not self._compiled_scene.tracks:
            # Static scene: recipes with motion compile a graph in set_visual,
            # so no graph here means nothing animates.
            static_signature = (-1, True)
            if self._last_frame_signature == static_signature:
                return
            self._last_frame_signature = static_signature
            self.setGeometry(self._base_rect)
            self._display_opacity = 1.0
            self._opacity.setOpacity(1.0)
            self._rescale(1.0)
            return
        signature = (int(absolute_ms), bool(paused))
        if paused and signature == self._last_frame_signature:
            return
        self._last_frame_signature = signature
        start_ms = self._timing_preview[0] if self._timing_preview else snapshot.start_ms
        relative = max(0, int(absolute_ms) - int(start_ms))
        if self._compiled_scene is not None:
            sync_started = perf_counter()
            # Cue-local time follows PlaybackClock / media timeline. Seek,
            # pause, speed and loop all flow through absolute_ms.
            if self._compiled_scene.tracks and not self._layer_images:
                # A Fidelity takeover (paused) replaced layer rasters with a
                # static frame. The first moving tick must rebuild them or
                # playback stays frozen on that frame forever.
                self._start_live_layer_pipeline()
            frame_image = self._source_image
            sample = None
            composite_started = perf_counter()
            if self._layer_images:
                frame_image, sample = composite_live_scene_layers(
                    self._layer_images,
                    self._compiled_scene,
                    relative,
                    pivot=self._composition_pivot,
                )
            composite_ms = (perf_counter() - composite_started) * 1000.0
            # Keep the overlay locked to the video content rect. Graph
            # motion is sampled inside the compositor around the subtitle
            # pivot so decorations cannot inflate to video-frame scale.
            self.setGeometry(self._base_rect)
            self._display_opacity = 1.0
            self._opacity.setOpacity(1.0)
            convert_started = perf_counter()
            if not frame_image.isNull():
                self._source_image = frame_image
            frame_pixmap = QPixmap.fromImage(self._source_image)
            self._source = QPixmap(frame_pixmap)
            convert_ms = (perf_counter() - convert_started) * 1000.0
            publish_started = perf_counter()
            self._rescale(1.0, frame_pixmap)
            publish_ms = (perf_counter() - publish_started) * 1000.0
            self._last_sync_profile = {
                "composite_ms": round(composite_ms, 3),
                "convert_ms": round(convert_ms, 3),
                "publish_ms": round(publish_ms, 3),
                "total_ms": round((perf_counter() - sync_started) * 1000.0, 3),
            }
            self._trace_frame_sample(
                absolute_ms=int(absolute_ms),
                relative_ms=relative,
                sample=sample,
                frame_image=frame_image,
            )
            return
        # Recipes with motion but no usable graph were routed through
        # graph_from_style_recipe in set_visual; reaching here means the scene
        # is static, which the MOTION_MODE_NONE branch above already rendered.

    def _trace_frame_sample(
        self,
        *,
        absolute_ms: int,
        relative_ms: int,
        sample: object,
        frame_image: QImage,
    ) -> None:
        """Emit bounded packaged evidence for one applied AI cue.

        This is intentionally sampled at 100 ms, independent of the 16 ms
        visual tick, so a transient transparent frame or ownership switch is
        visible in the trace without turning normal playback into a logger.
        """
        owner = self._owner
        trace = getattr(owner, "_studio_trace", None)
        while not callable(trace) and owner is not None:
            owner = owner.parentWidget()
            trace = getattr(owner, "_studio_trace", None) if owner is not None else None
        snapshot = self._snapshot
        scene = self._compiled_scene
        if not callable(trace) or snapshot is None or scene is None:
            return
        now = perf_counter()
        previous = self._last_frame_trace_relative_ms
        if (
            previous is not None
            and abs(int(relative_ms) - previous) < 100
            and now - self._last_frame_trace_perf < 0.1
        ):
            return
        self._last_frame_trace_perf = now
        self._last_frame_trace_relative_ms = int(relative_ms)
        phases = motion_phases(scene.graph)
        cue_duration = max(1, int(snapshot.end_ms) - int(snapshot.start_ms))
        phase = cue_motion_phase(
            int(relative_ms),
            entrance_end_ms=phases.entrance_end_ms,
            exit_start_ms=phases.exit_start_ms,
            cue_duration_ms=cue_duration,
        )
        values = getattr(sample, "values", {}) if sample is not None else {}
        text_target = getattr(getattr(scene, "graph", None), "text_layer", None)
        text_target_id = getattr(text_target, "id", "text")
        def value(target: str, property_name: str, default: float = 1.0) -> float:
            try:
                return round(float(values.get(target, {}).get(property_name, default)), 4)
            except (AttributeError, TypeError, ValueError):
                return float(default)
        try:
            alive = not QRegion(QPixmap.fromImage(frame_image).mask()).boundingRect().isEmpty()
        except (RuntimeError, TypeError):
            alive = not frame_image.isNull()
        active_ids = getattr(self._owner, "active_compositor_overlay_ids", lambda: [])()
        overlay_id = int(getattr(self._owner, "ADVANCED_OVERLAY_ID", 0))
        trace_project = getattr(owner, "project", None)
        trace_media = getattr(trace_project, "media", None)
        trace(
            "ADVANCED_FRAME_TRACE",
            cue_id=str(getattr(snapshot, "cue_id", "")),
            project_id=str(getattr(owner, "project_path", "") or ""),
            studio_session_id=str(getattr(owner, "_studio_session_id", "") or ""),
            media_id=str(getattr(trace_media, "path", "") or ""),
            thread=threading.current_thread().name,
            media_time_ms=int(absolute_ms),
            timeline_time_ms=int(absolute_ms),
            cue_local_time_ms=int(relative_ms),
            cue_duration_ms=cue_duration,
            graph_duration_ms=int(scene.graph.motion_graph.duration_ms),
            motion_phase=phase,
            compiled_scene_id=scene.graph_hash,
            renderer_path="VISUAL_GRAPH",
            text_opacity=value(text_target_id, "opacity"),
            group_opacity=value("group", "opacity"),
            panel_opacity=value(getattr(getattr(scene.graph, "panel_layer", None), "id", "panel"), "opacity"),
            scene_alive=bool(alive),
            overlay_present=overlay_id in active_ids,
            overlay_id=overlay_id,
            visualGraph_hash=scene.graph_hash,
        )
