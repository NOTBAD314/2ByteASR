"""Clock-following secondary video sources.

A SecondaryVideoSource never owns the Project PlaybackClock. Studio asks for a
frame at a source timestamp; the decoder prepares, seeks, and publishes only
the latest generation. The control plane (QMediaPlayer/QVideoSink) stays on
the GUI thread; the QVideoFrame.toImage() readback runs on a stateless
converter thread, whose teardown holds no WMF object.
"""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QObject, QThread, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame, QVideoSink


class SourceState:
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    READY = "READY"
    FAILED = "FAILED"
    RELEASED = "RELEASED"


# App-exit parking lot: the MainWindow sets this during the final close so
# secondary players are disconnected but never destroyed (destruction wedges
# the frozen ffmpeg media backend on the GUI thread; os._exit ends the
# process instead). Project switches keep the normal unload+deleteLater.
_DEFER_MEDIA_DESTRUCTION = False
_PARKED_MEDIA_OBJECTS: list[tuple[object, object]] = []


def set_defer_media_destruction(enabled: bool) -> None:
    global _DEFER_MEDIA_DESTRUCTION
    _DEFER_MEDIA_DESTRUCTION = bool(enabled)


@dataclass(frozen=True)
class SecondaryFrame:
    generation: int
    source_ms: int
    pts_ms: int
    image: QImage
    age_ms: float
    path: str


class _FrameConverter(QObject):
    """QVideoFrame→QImage conversion off the GUI thread.

    Pure compute: no Qt Multimedia object lives here, so thread teardown is
    trivial and can never race WMF session finalization against the GIL
    (the close-time wedge observed on 2026-09-07 when the whole decoder,
    player included, lived on a QThread)."""

    converted = Signal(int, int, int, object, str)

    @Slot(int, int, int, object, str)
    def convert(self, generation: int, wanted_ms: int, pts_ms: int, frame: object, path: str) -> None:
        try:
            image = frame.toImage()
        except RuntimeError:
            return
        self.converted.emit(generation, wanted_ms, pts_ms, image, path)



class _DecoderWorker(QObject):
    prepared = Signal(str, bool, str)
    frame_ready = Signal(int, int, int, object, str)
    state_changed = Signal(str)
    playback_probe = Signal(bool, bool, str)
    shutdown_complete = Signal()
    _convert_call = Signal(int, int, int, object, str)

    # 播放中转换速率上限（每播放器）：合成器只需要显示级帧率，倍速播放时
    # WMF 以速率×供帧（2x=120fps/层），全量 toImage 是 GUI/转换线程的主要
    # 开销。暂停与 seek 收敛不受限（需要精确帧）。
    MIN_CONVERT_INTERVAL_S = 1.0 / 62.0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.player: QMediaPlayer | None = None
        self.sink: QVideoSink | None = None
        self.path = ""
        self._generation = 0
        self._wanted_ms = 0
        self._state = SourceState.IDLE
        self._frame_delivery_pending = False
        self._latest_frame: tuple[int, int, int, QImage, str] | None = None
        self._last_request_signature: tuple[object, ...] | None = None
        self._last_seek_attempt = 0.0
        self._pending_pause_after_frame = False
        self._held_pts_ms = None
        self._last_paused = True
        self._source_loaded = False
        self._pending_load_request = None
        self._shutdown_polls = 0
        self._shutdown_final_status = ""
        self._shutdown_on_worker_thread = True
        self._last_convert_ts = 0.0
        # Set by the façade when a conversion thread is wired in; a bare
        # worker (unit tests) converts inline with the original semantics.
        self._conversion_enabled = False

    def _ensure_player(self) -> QMediaPlayer:
        if self.player is not None:
            return self.player
        self.player = QMediaPlayer()
        self.player.playbackStateChanged.connect(self._publish_playback_probe)
        # 五十轮：EXE 内叠加层五轮"不显示"排查全靠外部分析——QMediaPlayer 的
        # 错误与媒体状态从未被记录（dev 正常 EXE 黑盒）。落 trace 换永久白盒。
        self.player.errorOccurred.connect(self._log_player_error)
        self.player.mediaStatusChanged.connect(self._log_media_status)
        return self.player
    def _log_player_error(self, code, message) -> None:
        from .runtime_trace import GLOBAL_STUDIO_TRACE

        GLOBAL_STUDIO_TRACE.emit(
            "SECONDARY_PLAYER_ERROR",
            {
                "path": self.path,
                "code": str(getattr(code, "name", code)),
                "error": str(message),
            },
        )

    def _log_media_status(self, status) -> None:
        from .runtime_trace import GLOBAL_STUDIO_TRACE

        GLOBAL_STUDIO_TRACE.emit(
            "SECONDARY_MEDIA_STATUS",
            {"path": self.path, "status": str(getattr(status, "name", status))},
        )
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) and not self._source_loaded:
            self._source_loaded = True
            self._state = SourceState.READY
            self.state_changed.emit(self._state)
            self.prepared.emit(self.path, True, "")
            pending, self._pending_load_request = self._pending_load_request, None
            if pending is not None:
                # setPosition during LoadingMedia may be discarded by Qt.
                # Apply the newest clock request as soon as the source loads.
                self._last_request_signature = None
                self.request(*pending)

    def _publish_playback_probe(self, *_args) -> None:
        state = self.player.playbackState().name if self.player is not None else "StoppedState"
        self.playback_probe.emit(False, self.sink is not None, state)

    def _set_video_output_enabled(self, enabled: bool) -> None:
        """Decode frames only for visible compositor layers."""

        player = self.player
        if player is None:
            return
        if not enabled:
            sink = self.sink
            self.sink = None
            self._latest_frame = None
            self._frame_delivery_pending = False
            player.setVideoSink(None)
            if sink is not None:
                try:
                    sink.videoFrameChanged.disconnect(self._on_frame)
                except (RuntimeError, TypeError):
                    pass
                sink.deleteLater()
            self._publish_playback_probe()
            return
        if self.sink is None:
            self.sink = QVideoSink()
            self.sink.videoFrameChanged.connect(self._on_frame)
            player.setVideoSink(self.sink)
        self._publish_playback_probe()

    def _set_audio_output_enabled(self, enabled: bool, volume: float = 0.0) -> None:
        """Secondary decoders are permanently video-only."""

        del enabled, volume
        self._publish_playback_probe()

    @Slot(str)
    def prepare(self, path: str) -> None:
        normalized = str(Path(path)) if path else ""
        if not normalized:
            self._state = SourceState.FAILED
            self.state_changed.emit(self._state)
            self.prepared.emit("", False, "empty path")
            return
        self._state = SourceState.PREPARING
        self.state_changed.emit(self._state)
        player = self._ensure_player()
        if normalized != self.path:
            from .runtime_trace import GLOBAL_STUDIO_TRACE

            GLOBAL_STUDIO_TRACE.emit("SECONDARY_PREPARE", {"path": normalized})
            self.path = normalized
            self._last_request_signature = None
            self._source_loaded = False
            self._pending_load_request = None
            self._last_convert_ts = 0.0
            player.stop()
            player.setSource(QUrl.fromLocalFile(normalized))

    @Slot(int, int, bool, float, float, bool, bool)
    def request(
        self,
        source_ms: int,
        generation: int,
        paused: bool,
        rate: float,
        volume: float,
        audio_output_enabled: bool,
        video_output_enabled: bool,
    ) -> None:
        player = self.player
        if player is None or not self.path:
            return
        if not self._source_loaded:
            self._pending_load_request = (source_ms, generation, paused, rate, volume, audio_output_enabled, video_output_enabled)
            self._set_video_output_enabled(bool(video_output_enabled))
            return
        next_generation = int(generation)
        next_wanted_ms = max(0, int(source_ms))
        next_paused = bool(paused)
        next_rate = max(0.25, min(4.0, float(rate)))
        next_volume = max(0.0, min(1.0, float(volume)))
        next_audio_enabled = bool(audio_output_enabled)
        next_video_enabled = bool(video_output_enabled)
        signature = (
            next_generation, next_wanted_ms, next_paused,
            round(next_rate, 4), round(next_volume, 4), next_audio_enabled,
            next_video_enabled,
        )
        first_request = self._last_request_signature is None
        if signature == self._last_request_signature:
            # 五十轮（用户工程暂停态实录）：prepare 刚 setSource 时 WMF 仍在
            # LoadingState，首个 setPosition 会被吞——播放器从 0 开始 1x 播放，
            # 而 signature 去重把后续 request 全部早退，永远到不了目标帧
            # （pts 恒远小于 wanted → 叠加层恒不可见）。同值请求在暂停态不
            # 早退：播放器尚未收敛且上次 seek 已超时则低频重发，保证收敛。
            if not next_paused or self.player is None:
                return
            drift_now = abs(int(self.player.position()) - next_wanted_ms)
            now = perf_counter()
            if drift_now <= 42:
                return
            if self._pending_pause_after_frame and (now - self._last_seek_attempt) < 1.2:
                return
        else:
            self._last_request_signature = signature
        generation_changed = next_generation != self._generation
        target_changed = next_wanted_ms != self._wanted_ms
        pause_changed = next_paused != self._last_paused
        self._last_paused = next_paused
        if not next_paused:
            self._pending_pause_after_frame = False
        self._generation = next_generation
        self._wanted_ms = next_wanted_ms
        if abs(float(player.playbackRate()) - next_rate) > 0.0001:
            player.setPlaybackRate(next_rate)
        if next_audio_enabled or next_volume > 0.0:
            self._set_audio_output_enabled(False, 0.0)
        if (self.sink is not None) != next_video_enabled:
            self._set_video_output_enabled(next_video_enabled)
        drift = abs(int(player.position()) - self._wanted_ms)
        if (
            first_request or generation_changed
            or (next_paused and (target_changed or drift > 42))
            or (pause_changed and (not next_paused or drift > 42))
            or (not next_paused and drift > 160 and perf_counter() - self._last_seek_attempt > 0.8)
        ):
            self._last_seek_attempt = perf_counter()
            self._held_pts_ms = None
            player.setPosition(self._wanted_ms)
            if next_paused:
                # 四十五轮首次尝试 play/pause 立即对——间隔 0ms WMF 来不及
                # 渲染。四十六轮定案（用户 1080p60 实录）：暂停态 seek 改为
                # 播放直到目标帧到达再自动暂停（_on_frame 检查 pts 接近
                # wanted 即 pause）。音频输出恒关，多播的一小段无可闻副作用。
                self._pending_pause_after_frame = True
                self._pending_pause_seek_attempts = 0
                player.play()
        if next_paused:
            if (
                player.playbackState() != QMediaPlayer.PlaybackState.PausedState
                and not self._pending_pause_after_frame
            ):
                player.pause()
        elif player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            player.play()

    @Slot()
    def cancel(self) -> None:
        self._generation += 1
        self._latest_frame = None
        self._last_request_signature = None
        self._pending_pause_after_frame = False

    @Slot()
    def suspend(self) -> None:
        self._generation += 1
        self._latest_frame = None
        self._last_request_signature = None
        self._pending_pause_after_frame = False
        self._pending_load_request = None
        self._last_convert_ts = 0.0
        if self.player is not None:
            self.player.pause()
        self._set_audio_output_enabled(False)

    @Slot()
    def shutdown(self) -> None:
        self._generation += 1
        self._latest_frame = None
        self._frame_delivery_pending = False
        self._last_request_signature = None
        player = self.player
        sink = self.sink
        self.player = None
        self.sink = None
        if sink is not None:
            try:
                sink.videoFrameChanged.disconnect(self._on_frame)
            except (RuntimeError, TypeError):
                pass
        if player is not None:
            try:
                player.playbackStateChanged.disconnect(self._publish_playback_probe)
            except (RuntimeError, TypeError):
                pass
        if _DEFER_MEDIA_DESTRUCTION and player is not None:
            # 2026-09-07（打包关停滞留，ffmpeg 后端）：会话卸载（stop/setSource）
            # 与 DeferredDelete 析构都会在 GUI 线程上楔进媒体后端/显卡驱动
            # （native 栈：~QMediaPlayer→QThread::wait / av_hwframe_ctx→
            # D3D11CreateDevice→OpenAdapter10）。应用退出路径改为"停放"：
            # 只断信号、保引用，进程由 os._exit 终止；工程切换不受影响。
            _PARKED_MEDIA_OBJECTS.append((sink, player))
            self._shutdown_final_status = "ParkedForProcessExit"
        else:
            if player is not None:
                # Unload the session before the deferred delete — destroying
                # a loaded player wedges its destructor in QThread::wait.
                try:
                    player.pause()
                    player.setVideoSink(None)
                    player.stop()
                    player.setSource(QUrl())
                except RuntimeError:
                    pass
            for media_object in (sink, player):
                if media_object is not None:
                    media_object.deleteLater()
            self._shutdown_final_status = "DeferredDelete" if player is not None else "NoPlayer"
        self._shutdown_polls = 1 if player is not None else 0
        self.path = ""
        self._state = SourceState.RELEASED
        self.state_changed.emit(self._state)
        self.shutdown_complete.emit()

    def _on_frame(self, frame: QVideoFrame) -> None:
        generation = self._generation
        if not frame.isValid():
            return
        start = int(frame.startTime())
        pts_ms = (
            start // 1000
            if start >= 0
            else int(self.player.position() if self.player is not None else self._wanted_ms)
        )
        # A backend may deliver old queued frames after setPosition. Do not
        # relabel them as the new generation or spend a readback on them.
        if abs(pts_ms - self._wanted_ms) > 500 and perf_counter() - self._last_seek_attempt < 1.0:
            return
        if self._last_paused and not self._pending_pause_after_frame and self._held_pts_ms is not None:
            # pause() does not retract frames already queued by the backend.
            # Keep the nearest target frame instead of drifting several frames
            # forward while the user sees a stationary playhead.
            if abs(pts_ms-self._wanted_ms) >= abs(self._held_pts_ms-self._wanted_ms):
                return
            self._held_pts_ms = pts_ms
        # 播放中转换限速（多轨倍速卡顿主因之一）：WMF 在 2x/4x 下以 2x/4x
        # 速率供帧，全量 toImage 转换（~4-8ms/帧·层）直接吃满 GUI/转换线程。
        # 合成器消费不超过显示速率，超限帧在转换前丢弃（零成本）。暂停态与
        # seek 收敛（_last_paused=True 且 _pending_pause_after_frame）需要
        # 精确帧，不受限。
        if not self._last_paused:
            now = perf_counter()
            if 0.0 < self._last_convert_ts and (now - self._last_convert_ts) < self.MIN_CONVERT_INTERVAL_S:
                return
            self._last_convert_ts = now
        if self._conversion_enabled:
            # 2026-09-07（双轨轮）：1440p60 的 toImage 回读在 GUI 线程是
            # 心跳 p95 40ms+ 的主因；下沉到纯计算转换线程，控制面不动。
            self._convert_call.emit(generation, self._wanted_ms, pts_ms, frame, self.path)
            return
        self._on_converted_frame(generation, self._wanted_ms, pts_ms, frame.toImage(), self.path)

    def _on_converted_frame(self, generation: int, wanted_ms: int, pts_ms: int, image: object, path: str) -> None:
        if int(generation) != self._generation:
            return
        if not isinstance(image, QImage) or image.isNull():
            return
        if getattr(self, "_pending_pause_after_frame", False):
            # 五十轮 EXE 实证：暂停判据 500ms 与绘制可见判据（帧精确 ~42ms）
            # 不一致——落进 42-500 窗的帧一暂停就恒不可见。暂停只认帧精确；
            # 达不到就继续重试（WMF LoadingState 期间 setPosition 会被吞，
            # 播放器从 0 开始 1x 播放，帧持续到达但 pts 永不接近 wanted）。
            if abs(pts_ms - self._wanted_ms) <= 42:
                self._pending_pause_after_frame = False
                self._held_pts_ms = pts_ms
                if self.player is not None:
                    self.player.pause()
            else:
                # EXE 实证（五十轮 trace）：固定 1.2s 重发=活锁——冷解码到首帧
                # 需 >1.2s，下一次重发恰在帧到来前重启管线（媒体状态每秒循环
                # Loaded→Buffering→Buffered）。递增退避给每次 seek 真正的
                # 出帧窗口：2.5s → 5s → 7.5s → 8s 封顶。
                now = perf_counter()
                attempts = getattr(self, "_pending_pause_seek_attempts", 0)
                backoff = min(2.5 * max(1, attempts + 1), 8.0)
                if now - self._last_seek_attempt >= backoff and attempts < 10:
                    self._pending_pause_seek_attempts = attempts + 1
                    self._last_seek_attempt = now
                    if self.player is not None:
                        self.player.setPosition(self._wanted_ms)
                        self.player.play()
                elif attempts >= 10:
                    # 就近暂停保底（有近似帧总比黑着强；compositor 暂停态
                    # 的 500ms 兜底可见窗会把它显示出来）。
                    self._pending_pause_after_frame = False
                    if self.player is not None:
                        self.player.pause()
        payload = (int(generation), self._wanted_ms, int(pts_ms), image, str(path))
        if self._frame_delivery_pending:
            self._latest_frame = payload
            return
        self._frame_delivery_pending = True
        self.frame_ready.emit(*payload)

    @Slot()
    def frame_consumed(self) -> None:
        payload = self._latest_frame
        self._latest_frame = None
        if payload is None:
            self._frame_delivery_pending = False
            return
        self.frame_ready.emit(*payload)


class SecondaryVideoSource(QObject):
    """GUI façade over the native video backend."""

    frame_updated = Signal()
    prepared = Signal(str, bool)
    _prepare_call = Signal(str)
    _request_call = Signal(int, int, bool, float, float, bool, bool)
    _cancel_call = Signal()
    _suspend_call = Signal()
    _shutdown_call = Signal()
    _frame_consumed_call = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: _DecoderWorker | None = None
        self._converter: _FrameConverter | None = None
        self._convert_thread: QThread | None = None
        self._started = False
        self.path = ""
        self.state = SourceState.IDLE
        self.generation = 0
        self.image = QImage()
        self._image_generation = -1
        self.pts_ms = -1
        self.requested_ms = 0
        self.frame_interval_ms = 0.0
        self.audio_output_attached = False
        self.video_output_attached = False
        self.playback_state = "StoppedState"
        self._last_frame_ts = 0.0
        self._pending_path = ""
        self.samples: deque[dict[str, object]] = deque(maxlen=256)
        self.shutdown_acknowledged = False
        self.thread_stopped = True
        self.thread_forced_termination = False

    def _ensure_thread(self) -> None:
        if self._started:
            return
        # Control plane (QMediaPlayer/QVideoSink and the seek/pause state
        # machine) stays on the GUI thread — the teardown model proven over
        # fifty rounds. Cross-thread frame.toImage() keeps WMF-backed samples
        # alive past their session unless teardown DRAINS the converter first
        # (2026-09-07 close hang; release() enforces that order: stop routing
        # → drop queued conversions → join the converter thread → only then
        # unload the WMF session). The converter stays on by default for the
        # ~8ms/frame readback offload; TWOBYTEASR_INLINE_FRAME_CONVERT=1
        # forces the fully inline path as an escape hatch.
        worker = _DecoderWorker(self)
        self._worker = worker
        worker._conversion_enabled = os.environ.get("TWOBYTEASR_INLINE_FRAME_CONVERT") != "1"
        if worker._conversion_enabled:
            thread = QThread(self)
            thread.setObjectName("studio-frame-convert")
            converter = _FrameConverter()
            converter.moveToThread(thread)
            self._convert_thread = thread
            self._converter = converter
            worker._convert_call.connect(converter.convert)
            converter.converted.connect(worker._on_converted_frame)
            thread.finished.connect(converter.deleteLater)
            thread.start(QThread.Priority.HighPriority)
        self._prepare_call.connect(worker.prepare, Qt.ConnectionType.DirectConnection)
        self._request_call.connect(worker.request, Qt.ConnectionType.DirectConnection)
        self._cancel_call.connect(worker.cancel, Qt.ConnectionType.DirectConnection)
        self._suspend_call.connect(worker.suspend, Qt.ConnectionType.DirectConnection)
        self._shutdown_call.connect(worker.shutdown, Qt.ConnectionType.DirectConnection)
        self._frame_consumed_call.connect(
            worker.frame_consumed, Qt.ConnectionType.DirectConnection
        )
        worker.prepared.connect(self._on_prepared, Qt.ConnectionType.DirectConnection)
        worker.frame_ready.connect(self._on_frame, Qt.ConnectionType.DirectConnection)
        worker.playback_probe.connect(
            self._on_playback_probe, Qt.ConnectionType.DirectConnection
        )
        worker.shutdown_complete.connect(self._on_shutdown_complete, Qt.ConnectionType.DirectConnection)
        self.shutdown_acknowledged = False
        self.thread_stopped = False
        self.thread_forced_termination = False
        self._started = True

    @Slot()
    def _on_shutdown_complete(self) -> None:
        self.shutdown_acknowledged = True

    @Slot(bool, bool, str)
    def _on_playback_probe(
        self,
        audio_attached: bool,
        video_attached: bool,
        state: str,
    ) -> None:
        self.audio_output_attached = bool(audio_attached)
        self.video_output_attached = bool(video_attached)
        self.playback_state = str(state or "StoppedState")

    def _on_prepared(self, path: str, ok: bool, _error: str) -> None:
        self.state = SourceState.READY if ok else SourceState.FAILED
        if ok:
            self.path = path
        self.prepared.emit(path, ok)

    def _on_frame(
        self,
        generation: int,
        requested_ms: int,
        pts_ms: int,
        image: object,
        path: str,
    ) -> None:
        try:
            if int(generation) != self.generation:
                return
            if not isinstance(image, QImage) or image.isNull():
                return
            now = perf_counter()
            self.image = image
            self._image_generation = int(generation)
            self.pts_ms = int(pts_ms)
            self.frame_interval_ms = (now - self._last_frame_ts) * 1000.0 if self._last_frame_ts else 0.0
            self._last_frame_ts = now
            self.path = str(path)
            self.samples.append(
                {
                    "generation": int(generation),
                    "requested_ms": int(requested_ms),
                    "pts_ms": int(pts_ms),
                    "interval_ms": round(self.frame_interval_ms, 3),
                    "path": str(path),
                }
            )
            self.frame_updated.emit()
        finally:
            self._frame_consumed_call.emit()

    def prepare(self, path: str) -> None:
        self._ensure_thread()
        normalized = str(Path(path)) if path else ""
        if (
            normalized == self._pending_path
            and self.state in {SourceState.PREPARING, SourceState.READY}
        ):
            return
        if normalized != self._pending_path:
            self.image = QImage()
        self._pending_path = normalized
        self.state = SourceState.PREPARING
        self._prepare_call.emit(normalized)

    @property
    def frame_age_ms(self) -> float:
        return (perf_counter() - self._last_frame_ts) * 1000.0 if self._last_frame_ts else float('inf')

    def request_frame(
        self,
        source_ms: int,
        *,
        paused: bool,
        rate: float = 1.0,
        volume: float = 0.0,
        audio_output_enabled: bool | None = None,
        video_output_enabled: bool = True,
        seek: bool = False,
        seek_token: int | None = None,
    ) -> int:
        self._ensure_thread()
        target_ms = max(0, int(source_ms))
        new_seek = (seek_token != getattr(self, '_seek_token', None)) if seek_token is not None else target_ms != self.requested_ms
        if seek and new_seek:
            self.generation += 1
        self._seek_token = seek_token
        self.requested_ms = target_ms
        self._request_call.emit(
            self.requested_ms,
            self.generation,
            bool(paused),
            float(rate),
            float(volume),
            bool(float(volume) > 0.0 if audio_output_enabled is None else audio_output_enabled),
            bool(video_output_enabled),
        )
        return self.generation

    def cancel_pending(self) -> None:
        self.generation += 1
        self._cancel_call.emit()

    def suspend(self) -> None:
        self.generation += 1
        self.image = QImage()
        if self._started:
            self._suspend_call.emit()

    def release(self) -> None:
        self.generation += 1
        self.image = QImage()
        self.state = SourceState.RELEASED
        self.audio_output_attached = False
        self.video_output_attached = False
        self.playback_state = "StoppedState"
        if not self._started:
            return
        self._started = False
        worker = self._worker
        converter = self._converter
        converter_thread = self._convert_thread
        self._worker = None
        self._convert_thread = None
        self._converter = None
        if worker is not None:
            # 2026-09-07 返回主页楔死根治（顺序即契约）：
            # ① generation 已 bump + 停路由 → 新帧不再进转换队列；
            # ② removePostedEvents 把仍在队列里的转换调用（携带 WMF 样本的
            #    QVideoFrame）在 GUI 线程就地析构——此时会话仍然存活；
            # ③ quit+wait 等**在途**转换完成，样本释放进活会话；
            # ④ 最后才能 worker.shutdown() 卸载 WMF 会话——此后不可能再有
            #    样本越会话存活（原实现 ④ 在 ②③ 之前，转换在途时卸会话 =
            #    会话析构与 GIL 编组互等 = 返回主页/换工程偶发卡死）。
            worker._conversion_enabled = False
            if converter is not None and converter_thread is not None:
                try:
                    from PySide6.QtCore import QCoreApplication

                    QCoreApplication.removePostedEvents(converter)
                except (RuntimeError, AttributeError):
                    pass
                converter_thread.quit()
                converter_thread.wait(1000)
            worker.shutdown()
            self.shutdown_acknowledged = True
            worker.deleteLater()
        elif converter_thread is not None:
            converter_thread.quit()
            converter_thread.wait(1000)
        self.thread_forced_termination = False
        self.thread_stopped = True

    def close(self) -> None:
        if self._started:
            self.release()


def frame_is_stale(generation: int, current: int) -> bool:
    return int(generation) != int(current)


__all__ = [
    "SecondaryFrame",
    "SecondaryVideoSource",
    "SourceState",
    "frame_is_stale",
]
