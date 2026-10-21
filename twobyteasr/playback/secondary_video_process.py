"""GUI façade for clock-following, process-isolated secondary video."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QImage

from .video_decode_pipe import VideoDecodePipe


class SourceState:
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    READY = "READY"
    FAILED = "FAILED"
    RELEASED = "RELEASED"


@dataclass(frozen=True)
class SecondaryFrame:
    generation: int
    source_ms: int
    pts_ms: int
    image: QImage
    age_ms: float
    path: str


def set_defer_media_destruction(enabled: bool) -> None:
    # Compatibility with MainWindow's exit hook. Process decoders always close.
    del enabled


def frame_is_stale(generation: int, current: int) -> bool:
    return int(generation) != int(current)


class SecondaryVideoSource(QObject):
    frame_updated = Signal()
    prepared = Signal(str, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = ""
        self._pending_path = ""
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
        self._pipe: VideoDecodePipe | None = None
        self._preview_size = (1920,1080)
        self._epoch = -1
        self._published_epoch = -1
        self._rejected_regressions = 0
        self._seek_token = None
        self._started = False
        self._suspended = False
        self.samples: deque[dict[str, object]] = deque(maxlen=256)
        self.stall_events = deque(maxlen=256)
        self._last_stall_at = 0.
        self.shutdown_acknowledged = False
        self.thread_stopped = True
        self.thread_forced_termination = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(5)
        self._poll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._poll_timer.timeout.connect(self._poll)

    def _ensure_thread(self) -> None:
        if self._pipe is None:
            pipe = VideoDecodePipe(max_size=self._preview_size)
            self._pipe = pipe
            # Parent deletion must reclaim children even if a caller omits close.
            self.destroyed.connect(lambda *_: pipe.close())
            self._started = True
            self.thread_stopped = False
            self.shutdown_acknowledged = False
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def prepare(self, path: str) -> None:
        normalized = str(Path(path)) if path else ""
        if normalized != self._pending_path:
            self.cancel_pending()
            self.image = QImage()
            self._last_frame_ts = 0.
            self.pts_ms = -1
        elif self.state in {SourceState.PREPARING, SourceState.READY, SourceState.FAILED}:
            return
        self._pending_path = normalized
        self.path = normalized
        self.state = SourceState.PREPARING
        self._ensure_thread()

    @property
    def frame_age_ms(self) -> float:
        return (perf_counter() - self._last_frame_ts) * 1000 if self._last_frame_ts else float("inf")

    def request_frame(self, source_ms: int, *, paused: bool, rate: float = 1.,
                      volume: float = 0., audio_output_enabled: bool | None = None,
                      video_output_enabled: bool = True, seek: bool = False,
                      seek_token: int | None = None) -> int:
        del volume, audio_output_enabled
        if not video_output_enabled:
            self.suspend()
            return self.generation
        self._ensure_thread()
        target = max(0, int(source_ms))
        # Clock generations describe explicit seeks; pause/resume does not.
        # Preserve the token after seeking settles so a pause at the same
        # clock anchor cannot silently restart the decoder from an older PTS.
        new_seek = (seek_token != self._seek_token if seek_token is not None
                    else bool(seek and target != self.requested_ms))
        if new_seek:
            self.generation += 1
        self._seek_token = seek_token
        self.requested_ms = target
        if not paused and self.playback_state != 'PlayingState':
            self._playing_since = perf_counter()
        self._suspended = False
        self.video_output_attached = True
        self.playback_state = "PausedState" if paused else "PlayingState"
        self._epoch = self._pipe.request(self._pending_path, target, self.generation,
                                        bool(paused), max(.25, min(8., float(rate))))
        return self.generation

    def set_preview_size(self, width, height):
        # Fit the BGRA transport to actual screen pixels. Decoding time/epoch,
        # the native V1 and final export resolution are independent of this cap.
        self._preview_size = (max(128,min(1920,int(width))),max(72,min(1080,int(height))))
        if self._pipe is not None: self._pipe.max_size = self._preview_size

    def _poll(self) -> None:
        pipe = self._pipe
        if pipe is None:
            return
        pipe.watchdog()
        frame = pipe.take_frame()
        if frame is None:
            stats = pipe.snapshot()
            now = perf_counter()
            if (not self._suspended and self.playback_state == 'PlayingState'
                    and now-getattr(self,'_playing_since',now) > .25
                    and self.frame_age_ms > 250 and now-self._last_stall_at > .25):
                self._last_stall_at = now
                self.stall_events.append(dict(at=now, requested_ms=self.requested_ms,
                    pts_ms=self.pts_ms, frame_age_ms=self.frame_age_ms,
                    reason='heartbeat_missing' if stats.get('heartbeat_age_ms',0)>5000 else
                           'worker_failed' if stats['state']=='FAILED' else 'awaiting_current_frame',
                    decoder={k:stats.get(k) for k in ('pid','state','epoch','queue_frames','decoded',
                        'converted','read_ms','write_ms','decode_ms','error','heartbeat_age_ms')}))
            if stats["state"] == "FAILED" and self.state != SourceState.FAILED:
                self.state = SourceState.FAILED
                self.prepared.emit(self.path, False)
            return
        if self._suspended or frame.epoch != self._epoch or frame.generation != self.generation or frame.path != self._pending_path:
            return
        if frame.generation == self._image_generation and frame.pts_ms <= self.pts_ms:
            self._rejected_regressions += 1
            return
        # The receiver thread already owns immutable pixels; no GUI copy.
        image = QImage(frame.pixels, frame.width, frame.height, frame.width * 4,
                       QImage.Format.Format_ARGB32)
        if image.isNull():
            return
        ready = self.state != SourceState.READY
        self.state = SourceState.READY
        now = perf_counter()
        self.image = image
        self._image_pixels = frame.pixels
        self._image_generation = frame.generation
        self.pts_ms = frame.pts_ms
        self._published_epoch = frame.epoch
        self.frame_interval_ms = (now - self._last_frame_ts) * 1000 if self._last_frame_ts else 0.
        self._last_frame_ts = now
        self.samples.append(dict(generation=frame.generation, requested_ms=frame.requested_ms,
                                 epoch=frame.epoch, published_at=now, pts_ms=frame.pts_ms,
                                 raw_pts=frame.raw_pts, raw_dts=frame.raw_dts, time_base=frame.time_base,
                                 decoded_at=frame.decoded_at, received_at=frame.received_at,
                                 interval_ms=round(self.frame_interval_ms, 3), path=self.path))
        if ready:
            self.prepared.emit(self.path, True)
        self.frame_updated.emit()

    def performance_snapshot(self) -> dict:
        stats = self._pipe.snapshot() if self._pipe else {"backend": "ffmpeg-pipe", "state": self.state, "pid": None}
        age = self.frame_age_ms
        return {**stats, "generation": self.generation, "requested_ms": self.requested_ms,
                "stall_events": list(self.stall_events)[-4:],
                "presented_pts_ms": self.pts_ms, "frame_age_ms": round(age, 2) if self._last_frame_ts else None,
                "clock_error_ms": self.pts_ms - self.requested_ms if self.pts_ms >= 0 else None,
                "frame_interval_ms": round(self.frame_interval_ms, 3)}

    def cancel_pending(self) -> None:
        self.generation += 1
        if self._pipe:
            self._pipe.cancel()

    def suspend(self) -> None:
        if not self._suspended:
            self.cancel_pending()
        self._suspended = True
        self.image = QImage()
        self.video_output_attached = False
        self.playback_state = "StoppedState"
        self._poll_timer.stop()

    def release(self) -> None:
        self._poll_timer.stop()
        self.generation += 1
        self.image = QImage()
        self.state = SourceState.RELEASED
        self.audio_output_attached = self.video_output_attached = False
        self.playback_state = "StoppedState"
        pipe, self._pipe = self._pipe, None
        self.thread_stopped = pipe.close() if pipe else self.thread_stopped
        self.shutdown_acknowledged = self.thread_stopped
        self._started = False

    def close(self) -> None:
        self.release()
