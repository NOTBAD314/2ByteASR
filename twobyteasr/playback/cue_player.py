"""Cancellable caption audition with a bounded PCM cache and real pause.

The export audio graph owns media/time conversion. One sink owns output;
request IDs fence preparation and paused intent fences late auto-starts.
"""
from __future__ import annotations

import os
import subprocess
import time
import weakref
from collections import OrderedDict

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, QThread, QTimer, Signal

from .cue_audio_preview import (PreviewUnavailable, plan_cue_preview, preview_cache_key,
                                preview_command, record_preview)


class _PreviewThread(QThread):
    decoded = Signal(str, bytes)
    failed = Signal(str, str)

    def __init__(self, request_id, plan, parent=None):
        super().__init__(parent)
        self.request_id, self.plan = request_id, plan
        self._process = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    def run(self):
        from ..studio.studio_video_track import ffmpeg_executable
        started = time.perf_counter()
        row = {"event": "proofread_preview_prepare", **self.plan.diagnostic()}
        try:
            from .recognition_audio_preview import cached_recognition_pcm
            payload = cached_recognition_pcm(self.plan)
            if self._cancelled:
                raise InterruptedError("superseded")
            if payload:
                row.update(outcome="decoded", source="recognition_pcm_cache", pcm_bytes=len(payload),
                           graph_ready_ms=0., elapsed_ms=round((time.perf_counter()-started)*1000, 2))
                record_preview(row)
                self.decoded.emit(self.request_id, payload)
                return
            command, receipts = preview_command(self.plan, ffmpeg_executable(), cancelled=lambda: self._cancelled)
            row.update(layers=self.plan.diagnostic()["layers"],
                       source_clocks={k: {"kind": v.get("kind"), "path": v.get("path")} for k, v in receipts.items()},
                       graph_ready_ms=round((time.perf_counter() - started) * 1000, 2))
            if self._cancelled:
                raise InterruptedError("superseded")
            self._process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             creationflags=0x08000000 if os.name == "nt" else 0)
            # cancel may race the Popen; do not wait on a superseded decoder.
            if self._cancelled:
                self.cancel()
            payload, errors = self._process.communicate(timeout=60)
            if self._cancelled:
                raise InterruptedError("superseded")
            if self._process.returncode or not payload:
                raise PreviewUnavailable(errors.decode("utf-8", "replace").strip()[-240:] or "解码器没有返回声音")
            row.update(outcome="decoded", pcm_bytes=len(payload), elapsed_ms=round((time.perf_counter()-started)*1000, 2))
            record_preview(row)
            self.decoded.emit(self.request_id, payload)
        except InterruptedError:
            record_preview({**row, "outcome": "cancelled"})
        except Exception as exc:
            record_preview({**row, "outcome": "failed", "error": str(exc)[:400]})
            if not self._cancelled:
                self.failed.emit(self.request_id, f"这一句的音频无法读取：{str(exc)[:240]}")
        finally:
            process = self._process
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
                process.communicate()


class CuePlayer(QObject):
    state_changed = Signal(str, str)  # loading | playing | paused | failed | ''
    failed = Signal(str)
    CACHE_BYTES = 24 * 1024 * 1024
    CACHE_ENTRIES = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sink = self._buffer = self._thread = None
        self._threads = set()
        self.request_id = self.cue_id = self.state = ""
        self.last_plan = None
        self.volume = 1.0
        self._expected_ms = 0
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._key = ""
        self._project_ref = None
        self._wants_play = False
        self._payload = None
        self._started_at = self._clicked_at = 0.0
        self._output_started = False
        self._drain_deadline = None
        self._drain_remaining = None
        self._device_id = None
        self._end_timer = QTimer(self)
        self._end_timer.setInterval(20)
        self._end_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._end_timer.timeout.connect(self._check_finished)

    def _state(self, value):
        self.state = value
        self.state_changed.emit(self.cue_id, value)

    def _trace(self, event, **values):
        record_preview({"event": event, "cue_id": self.cue_id, "request_id": self.request_id,
                        "click_elapsed_ms": round((time.perf_counter()-self._clicked_at)*1000, 2), **values})

    def play(self, project, cue_id):
        self.stop()
        self._clicked_at = time.perf_counter()
        self.cue_id = str(cue_id)
        try:
            plan = plan_cue_preview(project, cue_id)
            self._key = preview_cache_key(plan)
        except Exception as exc:
            self._fail(str(exc))
            return
        self._project_ref = weakref.ref(project)
        self._begin_plan(plan, cue_id)

    def play_plan(self, plan, key):
        """Preserve the daily audio-track picker's already-resolved plan API."""
        self.stop()
        self._clicked_at = time.perf_counter()
        self._project_ref = None
        self.cue_id = str(key)
        try:
            self._key = preview_cache_key(plan)
        except Exception as exc:
            self._fail(str(exc))
            return
        self._begin_plan(plan, key)

    def _begin_plan(self, plan, key):
        self.last_plan = plan
        self.request_id = plan.request_id
        self.cue_id = str(key)
        self._wants_play = True
        self._state("loading")
        payload = self._cache.get(self._key)
        self._trace("proofread_preview_click", cache_hit=payload is not None, **plan.diagnostic())
        if payload is not None:
            self._cache.move_to_end(self._key)
            self._start(self.request_id, payload)
            return
        thread = _PreviewThread(plan.request_id, plan, self)
        thread.decoded.connect(self._start)
        thread.failed.connect(self._decode_failed)
        thread.finished.connect(lambda done=thread: self._thread_finished(done))
        self._thread = thread
        self._threads.add(thread)
        thread.start()

    def _thread_finished(self, thread):
        self._threads.discard(thread)
        if self._thread is thread:
            self._thread = None
        thread.deleteLater()

    def _fail(self, message):
        self._trace("proofread_preview_failed", error=message)
        self._wants_play = False
        self.request_id = ""
        self._end_timer.stop()
        self._reset_output()
        self._state("failed")
        self.failed.emit(message)

    def _decode_failed(self, request_id, message):
        if request_id == self.request_id:
            self._fail(message)

    def _still_current(self):
        if self._project_ref is None:
            return True
        project = self._project_ref()
        try:
            return project is not None and preview_cache_key(plan_cue_preview(project, self.cue_id)) == self._key
        except Exception:
            return False

    def _ensure_sink(self):
        from PySide6.QtMultimedia import QAudioFormat, QMediaDevices
        from .audio_output_worker import AudioOutputSink
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            raise PreviewUnavailable("没有可用的音频输出设备，请检查耳机或扬声器连接")
        if self._sink is not None and (device.id() != self._device_id or getattr(self._sink,"closed",False)):
            self._reset_output()
            self._sink.shutdown()
            self._sink.deleteLater()
            self._sink = None
        if self._sink is None:
            fmt = QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isFormatSupported(fmt):
                raise PreviewUnavailable("当前音频设备不支持 48kHz 双声道试听，请选择其他输出设备")
            self._sink = AudioOutputSink(device, fmt, self)
            self._device_id = device.id()
            # A short device queue bounds pause/cancel tails. reset() discards
            # queued output; stop() can drain it on some Qt backends.
        return self._sink

    def _start(self, request_id, payload):
        if request_id != self.request_id:
            return
        if not self._still_current():
            self._fail("字幕时间或素材已改变，请重新点击试听")
            return
        self._payload = payload
        if self._key and len(payload) <= self.CACHE_BYTES:
            previous = self._cache.pop(self._key, None)
            self._cache_bytes -= len(previous) if previous is not None else 0
            self._cache[self._key] = payload
            self._cache_bytes += len(payload)
            while len(self._cache) > self.CACHE_ENTRIES or self._cache_bytes > self.CACHE_BYTES:
                _, old = self._cache.popitem(last=False)
                self._cache_bytes -= len(old)
        self._trace("proofread_preview_ready", pcm_bytes=len(payload), wants_play=self._wants_play)
        if not self._wants_play:
            self._state("paused")
            return
        try:
            sink = self._ensure_sink()
            self._reset_output()
            previous, self._buffer = self._buffer, QBuffer(self)
            self._buffer.setData(QByteArray(payload))
            self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            if previous is not None:
                previous.close()
                previous.deleteLater()
            sink.setVolume(float(self.volume))
            self._expected_ms = len(payload) / 192
            self._output_started = False
            self._drain_deadline = None
            self._started_at = time.perf_counter()
            sink.start(self._buffer)
            self._trace("proofread_preview_sink_start", buffer_bytes=sink.bufferSize())
            self._end_timer.start()
        except Exception as exc:
            self._fail(f"无法打开音频输出：{exc}")

    def _check_finished(self):
        if not self.cue_id or self._sink is None or self.state == "paused":
            return
        from PySide6.QtMultimedia import QAudio
        sink = self._sink
        played = sink.processedUSecs()/1000
        state = sink.state() if hasattr(sink, "state") else None
        error = sink.error() if hasattr(sink, "error") else QAudio.Error.NoError
        if error not in (QAudio.Error.NoError, QAudio.Error.UnderrunError):
            self._fail(f"音频输出失败（{error.name}），请检查默认输出设备")
            return
        if played > 0 and not self._output_started:
            self._output_started = True
            self._trace("proofread_preview_output_progress", processed_ms=played)
            self._state("playing")
        if self._drain_deadline is not None:
            if time.perf_counter() >= self._drain_deadline:
                self._finish_naturally()
            return
        if state == QAudio.State.IdleState or played >= self._expected_ms:
            # EOF means the backend has accepted the last samples, not that
            # the physical queue has played them. reset() here cut ~50ms in
            # the output loopback. Let this finite cue drain naturally; only
            # explicit pause/switch/leave may discard pending output.
            queued_ms = sink.bufferSize()/192 if hasattr(sink, "bufferSize") else 0
            if queued_ms:
                self._drain_deadline = time.perf_counter()+(queued_ms+20)/1000
            else:
                self._finish_naturally()
        elif not self._output_started and time.perf_counter()-self._started_at > 3:
            self._fail("音频设备已打开但没有开始输出，请检查系统输出设备后重试")
        elif not self._end_timer.isActive():
            self._end_timer.start()

    def pause(self):
        if not self.cue_id or self.state in ("paused", "failed"):
            return
        self._wants_play = False
        self._end_timer.stop()
        self._drain_remaining = max(0, self._drain_deadline-time.perf_counter()) if self._drain_deadline is not None else None
        if self._sink is not None and self._buffer is not None:
            self._sink.suspend()
        self._trace("proofread_preview_pause")
        self._state("paused")

    def resume(self):
        if self.state != "paused" or not self.request_id:
            return
        if not self._still_current():
            self._fail("字幕时间或素材已改变，请重新点击试听")
            return
        self._clicked_at = time.perf_counter()
        self._wants_play = True
        self._state("loading")
        if self._buffer is not None and self._sink is not None:
            self._started_at = time.perf_counter()
            self._output_started = False
            if self._drain_remaining is not None:
                self._drain_deadline = time.perf_counter()+self._drain_remaining
            self._sink.resume()
            self._end_timer.start()
        elif self._payload is not None:
            self._start(self.request_id, self._payload)
        # Otherwise preparation still owns this request. It may start only
        # after this explicit resume, never from the earlier paused intent.

    def _reset_output(self):
        if self._sink is not None:
            reset = getattr(self._sink, "reset", None) or self._sink.stop
            reset()

    def _finish_naturally(self):
        self._end_timer.stop()
        self._sink.stop()  # finite PCM has drained; never discard its tail
        self._trace("proofread_preview_finished")
        self._drain_deadline = self._drain_remaining = None
        self.request_id = ""
        self._wants_play = False
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None
        self._payload = None
        self._state("")
        self.cue_id = ""

    def stop(self):
        self._wants_play = False
        self._drain_deadline = self._drain_remaining = None
        self.request_id = ""  # fence before cancelling any asynchronous work
        self._end_timer.stop()
        if self._thread is not None:
            self._thread.cancel()
            self._thread = None
        self._reset_output()
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None
        self._payload = None
        if self.cue_id:
            self._trace("proofread_preview_stop")
            self._state("")
        self.cue_id = ""

    def shutdown(self):
        self.stop()
        for thread in list(self._threads):
            thread.cancel()
        for thread in list(self._threads):
            thread.wait(5000)
        self._cache.clear()
        self._cache_bytes = 0
        if self._sink is not None and hasattr(self._sink,"shutdown"):
            self._sink.shutdown()
