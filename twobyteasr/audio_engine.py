"""One clock-following PCM decoder and one Windows audio sink for Studio."""

from __future__ import annotations

from collections import deque
from array import array
from dataclasses import dataclass
from pathlib import Path
import math
import os
import subprocess
import threading
import time
import numpy as np
from typing import Any, Mapping

from PySide6.QtCore import QCoreApplication, QIODevice, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from .runtime_paths import get_runtime_paths
from .runtime_trace import GLOBAL_STUDIO_TRACE


SAMPLE_RATE = 48_000
CHANNELS = 2
BYTES_PER_SAMPLE = 2
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE
PREBUFFER_SECONDS = 0.08
PREBUFFER_BYTES = round(BYTES_PER_SECOND * PREBUFFER_SECONDS)

DRIFT_RESTART_THRESHOLD_PAUSED_MS = 80.0
DRIFT_RESTART_THRESHOLD_PLAYING_MS = 280.0


def decoder_restart_required(
    *,
    process_alive: bool,
    same_source: bool,
    same_rate: bool,
    drift_ms: float,
    paused: bool,
    previous_drift_ms: float | None,
    decoder_ready: bool = True,
    allow_drift_restart: bool = True,
) -> bool:
    """Decide whether the ffmpeg decoder must be restarted.

    Hard conditions (dead process, source/rate change) restart immediately.
    Drift must exceed the threshold on two consecutive synchronize samples in
    the *audio-lagging* direction.  ``drift_ms`` is ``requested - estimated``:
    a positive value means the sink is behind the project clock and a restart
    can catch it up.  A negative value means the sink is already ahead;
    restarting at the earlier requested position would replay old audio and,
    on a long FLV seek, discard the only decoder that has begun producing PCM.
    """
    if not process_alive or not same_source or not same_rate:
        return True
    if not decoder_ready:
        return False
    if not allow_drift_restart:
        return False
    threshold = (
        DRIFT_RESTART_THRESHOLD_PAUSED_MS if paused else DRIFT_RESTART_THRESHOLD_PLAYING_MS
    )
    if drift_ms <= threshold:
        return False
    return previous_drift_ms is not None and previous_drift_ms > threshold


@dataclass(frozen=True)
class AudioOutputSpec:
    sample_rate: int
    channels: int
    sample_format: QAudioFormat.SampleFormat
    bytes_per_sample: int
    ffmpeg_format: str

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.bytes_per_sample

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.bytes_per_frame


def _audio_output_spec(audio_format: QAudioFormat) -> AudioOutputSpec | None:
    mapping = {
        QAudioFormat.SampleFormat.UInt8: (1, "u8"),
        QAudioFormat.SampleFormat.Int16: (2, "s16le"),
        QAudioFormat.SampleFormat.Int32: (4, "s32le"),
        QAudioFormat.SampleFormat.Float: (4, "f32le"),
    }
    sample_format = audio_format.sampleFormat()
    encoded = mapping.get(sample_format)
    if encoded is None or audio_format.sampleRate() <= 0 or audio_format.channelCount() <= 0:
        return None
    return AudioOutputSpec(
        sample_rate=int(audio_format.sampleRate()),
        channels=int(audio_format.channelCount()),
        sample_format=sample_format,
        bytes_per_sample=encoded[0],
        ffmpeg_format=encoded[1],
    )


def _pcm_rms(payload: bytes, sample_format: QAudioFormat.SampleFormat) -> float:
    """Normalized RMS for the exact PCM representation written to the sink."""

    if not payload:
        return 0.0
    try:
        if sample_format == QAudioFormat.SampleFormat.UInt8:
            values = ((value - 128) / 128.0 for value in payload)
            count = len(payload)
        elif sample_format == QAudioFormat.SampleFormat.Int16:
            usable = len(payload) - len(payload) % 2
            samples = array("h")
            samples.frombytes(payload[:usable])
            values = (value / 32768.0 for value in samples)
            count = len(samples)
        elif sample_format == QAudioFormat.SampleFormat.Int32:
            usable = len(payload) - len(payload) % 4
            samples = array("i")
            samples.frombytes(payload[:usable])
            values = (value / 2147483648.0 for value in samples)
            count = len(samples)
        elif sample_format == QAudioFormat.SampleFormat.Float:
            usable = len(payload) - len(payload) % 4
            samples = array("f")
            samples.frombytes(payload[:usable])
            values = (max(-1.0, min(1.0, float(value))) for value in samples)
            count = len(samples)
        else:
            return 0.0
        if not count:
            return 0.0
        return math.sqrt(sum(value * value for value in values) / count)
    except (OverflowError, ValueError):
        return 0.0


def studio_ffmpeg_path() -> Path:
    from .platform_media import ffmpeg_tool
    return ffmpeg_tool(root=get_runtime_paths().install_root)


def _atempo_chain(rate: float) -> str:
    remaining = max(0.125, min(8.0, float(rate or 1.0)))
    if abs(remaining-1.) < .000001:
        return "anull"
    values: list[float] = []
    while remaining > 2.0:
        values.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        values.append(0.5)
        remaining /= 0.5
    values.append(remaining)
    return ",".join(f"atempo={value:.6f}" for value in values)


def build_audio_decode_command(
    ffmpeg: str | os.PathLike[str],
    source: str | os.PathLike[str],
    *,
    source_ms: int,
    rate: float,
    sample_rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
    pcm_format: str = "s16le",
    gain_db: float = 0.,
    source_out_ms: int | None = None,
    av_sync_map=None,
) -> list[str]:
    from .studio_track_gain import gain_amplitude
    # Window positions are audio-content ms; a gappy recording's file
    # timestamps need the AV sync map translation before the input seek.
    seek_ms = int(source_ms)
    if av_sync_map is not None and not av_sync_map.is_identity and seek_ms >= 250:
        seek_ms = int(av_sync_map.content_to_source_ms(seek_ms))
    filters = []
    # Input -ss at/near zero skips AAC priming twice in the bundled FFmpeg.
    # Decode the short head normally and trim samples after decoding instead.
    head_ms = max(0, int(source_ms)) if source_ms < 250 else 0
    if head_ms:
        filters.extend((f"atrim=start={head_ms/1000:.6f}", "asetpts=PTS-STARTPTS"))
    if source_out_ms is not None:
        filters.append(f"atrim=duration={max(0, source_out_ms-source_ms)/1000.0:.6f}")
    if source_out_ms is not None and abs(rate-1.) > .000001:
        filters.append("apad=pad_dur=0.1")
    filters.append(_atempo_chain(rate))
    if gain_db:
        filters.append(f"volume={gain_amplitude(gain_db):.9f}")
    if source_out_ms is not None:
        filters.append(f"atrim=duration={max(0, source_out_ms-source_ms)/1000.0/max(.125,rate):.6f}")
    return [
        str(Path(ffmpeg)), "-hide_banner", "-loglevel", "error", "-nostdin",
        *(["-ss", f"{max(0, seek_ms) / 1000.0:.6f}"] if seek_ms >= 250 else []),
        "-i", str(Path(source)),
        "-vn", "-sn", "-dn", "-af", ",".join(filters),
        "-f", str(pcm_format), "-ac", str(max(1, int(channels))),
        "-ar", str(max(1, int(sample_rate))), "pipe:1",
    ]


def build_audio_mix_command(ffmpeg, layers, *, transport_rate=1.0,
                            sample_rate=SAMPLE_RATE, channels=CHANNELS, pcm_format="s16le", separate=False,
                            av_sync_map=None):
    """Align each input at the same project instant before a single PCM mix."""
    from .studio_track_gain import gain_amplitude
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin"]
    filters = []
    durations = []
    rates = [max(.125, float(x.get('playback_rate') or 1.) * transport_rate) for x in layers]
    # A common WSOLA state preserves relative phase of correlated recordings.
    # Independent states selected different overlap offsets even when both
    # clocks/start positions were correct. Do not collapse legitimate clips.
    joint_rate = rates[0] if len(rates) > 1 and max(rates)-min(rates) < 1e-8 else None
    # amerge ends at its shortest input. Pad each lane to the *longest*
    # bounded clip duration so one short audio stream cannot silence V1+V2.
    mix_duration = max((max(0, int(x['source_out_ms'])-int(x.get('source_ms',0)))/1000/
                        max(.125,float(x.get('playback_rate') or 1.)*transport_rate)
                        for x in layers),default=0.) if all(x.get('source_out_ms') is not None for x in layers) else None
    for index, layer in enumerate(layers):
        source_ms = max(0, int(layer.get('source_ms', 0)))
        seek_ms = source_ms
        if av_sync_map is not None and not av_sync_map.is_identity and seek_ms >= 250:
            seek_ms = int(av_sync_map.content_to_source_ms(seek_ms))
        command += (["-ss", f"{seek_ms/1000:.6f}"] if seek_ms >= 250 else [])
        command += ["-i", str(layer['source_path'])]
        head = f"atrim=start={source_ms/1000:.6f},asetpts=PTS-STARTPTS," if 0 < source_ms < 250 else ""
        rate = max(.125, float(layer.get('playback_rate') or 1.) * transport_rate)
        if layer.get('source_out_ms') is not None:
            durations.append(max(0, int(layer['source_out_ms'])-int(layer.get('source_ms', 0)))/1000/rate)
        limit = (f"atrim=duration={max(0, int(layer['source_out_ms'])-int(layer.get('source_ms', 0)))/1000:.6f},"
                 if layer.get('source_out_ms') is not None else "")
        lane_rate = 1. if joint_rate is not None else rate
        tail = (f"atrim=duration={max(0, int(layer['source_out_ms'])-int(layer.get('source_ms',0)))/1000/lane_rate:.6f},"
                if limit else "")
        pad = "apad=pad_dur=0.1," if limit and abs(lane_rate-1.) > .000001 else ""
        pad_duration = mix_duration * joint_rate + .1 if joint_rate is not None and mix_duration is not None else mix_duration
        filters.append(f"[{index}:a:0]{head}{limit}asetpts=PTS-STARTPTS,{pad}{_atempo_chain(lane_rate)},{tail}"
                       f"volume={1. if separate else gain_amplitude(layer.get('gain_db', 0.)):.9f},"
                       f"aresample={sample_rate},aformat=sample_fmts=flt:channel_layouts={channels}c,"
                       +(f"apad=whole_dur={pad_duration:.6f}" if (separate or joint_rate is not None) and pad_duration is not None else "apad=pad_dur=0.1")+f"[a{index}]")
    inputs = ''.join(f"[a{i}]" for i in range(len(layers)))
    finish = f",atrim=duration={max(durations):.6f}" if len(durations) == len(layers) else ""
    combine = f"amerge=inputs={len(layers)}" if separate else f"amix=inputs={len(layers)}:duration=longest:dropout_transition=0:normalize=0"
    shared_tempo = ',' + _atempo_chain(joint_rate) if joint_rate is not None else ''
    filters.append(f"{inputs}{combine}{shared_tempo}{finish}[mix]")
    return command + ["-filter_complex_threads", "1", "-filter_complex", ';'.join(filters),
                      "-map", "[mix]", "-vn", "-sn", "-dn", "-f", pcm_format,
                      "-ac", str(channels*len(layers) if separate else channels), "-ar", str(sample_rate), "pipe:1"]


def trim_startup_pcm(
    payload: bytes, *, chunk_source_ms: float, requested_source_ms: float,
    effective_rate: float, bytes_per_second: int, bytes_per_frame: int,
) -> tuple[bytes, float]:
    """Discard decoded startup audio that is already behind the media clock."""
    source_ms_per_byte = max(0.125, float(effective_rate)) * 1000.0 / max(1, int(bytes_per_second))
    trim_bytes = int(
        max(0.0, float(requested_source_ms) - float(chunk_source_ms)) / source_ms_per_byte
    )
    trim_bytes = min(len(payload), trim_bytes)
    frame_bytes = max(1, int(bytes_per_frame))
    trim_bytes -= trim_bytes % frame_bytes
    retained_source_ms = float(chunk_source_ms) + trim_bytes * source_ms_per_byte
    return payload[trim_bytes:], retained_source_ms


class _PcmRingDevice(QIODevice):
    data_available = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        sample_format: QAudioFormat.SampleFormat = QAudioFormat.SampleFormat.Int16,
        capacity_bytes: int = BYTES_PER_SECOND,
    ) -> None:
        super().__init__(parent)
        self._condition = threading.Condition()
        self._wake_lock = threading.Lock()
        self._wake_pending = False
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._generation = 0
        self._sample_format = sample_format
        self._capacity_bytes = max(4096, int(capacity_bytes))
        self.produced_bytes = 0
        self.consumed_bytes = 0
        self.producer_rms = 0.0
        self.consumed_rms = 0.0
        self.append_count = 0
        self.read_calls = 0
        self.read_nonempty_calls = 0
        self.last_read_bytes = 0
        self.wake_emit_count = 0
        self.wake_suppressed_count = 0
        # ``None`` means the current decoder has not produced its first PCM
        # frame yet.  Zero is a valid source timestamp and must not be used as
        # the "not ready" sentinel.
        self.stream_source_start_ms: float | None = None
        self._mix_spec = None
        self._mix_ids = ()
        self._mix_gains = np.ones(1, dtype=np.float32)
        self._mix_previous = self._mix_gains.copy()
        self._raw_ratio = 1
        self.empty_reads = 0
        self.callback_gaps_ms = deque(maxlen=4096)
        self._last_callback = 0.
        self.end_of_stream = False
        self.starvation_episodes = 0
        self._starved = False
        self.mix_cost_ms = deque(maxlen=4096)
        self.publish_enabled = True
        self.last_pcm_write_at = 0.
        self.input_metrics = []
        # QIODevice's own read-ahead buffer has no transport generation.
        # The Python ring must be the ONLY queue, or stopped/preroll PCM can
        # survive a reset and be replayed by the next native sink session.
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)

    def configure_mix(self, ids, spec, gains):
        with self._condition:
            self._mix_spec = spec
            self._mix_ids = tuple(ids)
            self._raw_ratio = len(ids)*4/spec.bytes_per_sample
            self._mix_gains = np.array(gains,dtype=np.float32)
            self._mix_previous = self._mix_gains.copy()
            self.publish_enabled = False

    def set_gains(self, gains):
        with self._condition:
            self._mix_gains = np.array([gains.get(key,1.) for key in self._mix_ids],dtype=np.float32)

    def _mix_output(self, payload):
        spec = self._mix_spec
        if spec is None:
            return payload
        values = np.frombuffer(payload,dtype='<f4').reshape(-1,len(self._mix_ids),spec.channels)
        frames = len(values)
        gains = self._mix_gains
        ramp = min(frames, max(1, round(spec.sample_rate*.005)))
        mixed = np.einsum('nlc,l->nc',values,gains)
        if not np.array_equal(gains,self._mix_previous):
            delta = np.linspace(1.,0.,ramp,dtype=np.float32)[:,None,None]
            mixed[:ramp] += (values[:ramp]*delta*(self._mix_previous-gains)[None,:,None]).sum(axis=1)
        self._mix_previous = gains.copy()
        mixed = np.clip(mixed,-1.,1.)
        if spec.ffmpeg_format == 's16le': return (mixed*32767).astype('<i2').tobytes()
        if spec.ffmpeg_format == 's32le': return (mixed.astype(np.float64)*2147483647).astype('<i4').tobytes()
        if spec.ffmpeg_format == 'u8': return ((mixed+1.)*127.5).astype('u1').tobytes()
        return mixed.astype('<f4').tobytes()

    def reset_stream(self) -> int:
        with self._condition:
            self._generation += 1
            self._chunks.clear()
            self._size = 0
            self.produced_bytes = 0
            self.consumed_bytes = 0
            self.producer_rms = 0.0
            self.consumed_rms = 0.0
            self.input_metrics = []
            self.append_count = 0
            self.read_calls = 0
            self.read_nonempty_calls = 0
            self.last_read_bytes = 0
            self.last_pcm_write_at = 0.
            self.wake_emit_count = 0
            self.wake_suppressed_count = 0
            self.stream_source_start_ms = None
            self.end_of_stream = False
            self.starvation_episodes = self.empty_reads = 0
            self._starved = False
            self._last_callback = 0.
            self.callback_gaps_ms.clear()
            self.mix_cost_ms.clear()
            self._condition.notify_all()
            return self._generation

    def source_start_snapshot(self) -> tuple[int, float | None]:
        """Return the source timestamp published by the current ring owner."""
        with self._condition:
            return self._generation, self.stream_source_start_ms

    def has_produced_pcm(self) -> bool:
        """Report PCM production for the currently owned decoder stream."""
        with self._condition:
            return self.produced_bytes > 0

    def append(
        self, payload: bytes, generation: int, stop_event: threading.Event,
        *, source_start_ms: float | None = None,
    ) -> bool:
        if not payload:
            return False
        with self._condition:
            while (
                generation == self._generation
                and self._size >= self._capacity_bytes*self._raw_ratio
                and not stop_event.is_set()
            ):
                self._condition.wait(0.05)
            if generation != self._generation or stop_event.is_set():
                return False
            if self.produced_bytes == 0 and source_start_ms is not None:
                self.stream_source_start_ms = max(0.0, float(source_start_ms))
            self._chunks.append(bytes(payload))
            self._size += len(payload)
            self.produced_bytes += round(len(payload)/self._raw_ratio)
            self.append_count += 1
            if self._mix_spec is None:
                self.producer_rms = _pcm_rms(payload, self._sample_format)
            elif self.append_count == 1 or self.append_count % 12 == 0:
                # These are the real interleaved decoder lanes, before gain
                # and summing. Keep input silence separate from sink silence.
                values=np.frombuffer(payload,dtype='<f4').reshape(-1,len(self._mix_ids),self._mix_spec.channels)
                self.input_metrics=[dict(track_id=key,rms=float(np.sqrt(np.mean(values[:,i,:]**2))),
                    peak=float(np.max(np.abs(values[:,i,:]))),nonzero_samples=int(np.count_nonzero(values[:,i,:])),
                    samples=int(values[:,i,:].size),sample_format='f32le',sample_rate=self._mix_spec.sample_rate,
                    channels=self._mix_spec.channels,monotonic=time.monotonic()) for i,key in enumerate(self._mix_ids)]
                mixed=np.einsum('nlc,l->nc',values,self._mix_gains)
                self.producer_rms=float(np.sqrt(np.mean(mixed**2)))
        self.readyRead.emit()
        # Decoder chunks can arrive much faster than the Qt worker can service
        # them. Keep at most one queued wakeup so control messages (especially
        # shutdown) cannot be starved behind thousands of redundant resumes.
        with self._wake_lock:
            should_wake = not self._wake_pending
            if should_wake:
                self._wake_pending = True
                self.wake_emit_count += 1
            else:
                self.wake_suppressed_count += 1
        if should_wake:
            self.data_available.emit()
        return True

    def readData(self, maxlen: int) -> bytes:
        with self._condition:
            self.read_calls += 1
            if not self.publish_enabled:
                return b''
            now = time.perf_counter()
            if self._last_callback:
                self.callback_gaps_ms.append((now-self._last_callback)*1000)
            self._last_callback = now
            output_frame = self._mix_spec.bytes_per_frame if self._mix_spec else 1
            wanted = int((max(0,int(maxlen))//output_frame)*output_frame*self._raw_ratio)
            if wanted <= 0 or not self._chunks:
                self.last_read_bytes = 0
                self.empty_reads += 1
                if wanted > 0 and not self.end_of_stream and self.produced_bytes > 0 and not self._starved:
                    self.starvation_episodes += 1
                    self._starved = True
                return b""
            self._starved = False
            mix_started = time.perf_counter()
            result = bytearray()
            while self._chunks and len(result) < wanted:
                chunk = self._chunks.popleft()
                take = min(len(chunk), wanted - len(result))
                result.extend(chunk[:take])
                if take < len(chunk):
                    self._chunks.appendleft(chunk[take:])
                self._size -= take
            self._condition.notify_all()
            payload = self._mix_output(bytes(result))
            self.consumed_bytes += len(payload)
            self.last_read_bytes = len(payload)
            if payload:
                self.read_nonempty_calls += 1
            self.consumed_rms = _pcm_rms(payload, self._sample_format)
            self.mix_cost_ms.append((time.perf_counter()-mix_started)*1000)
            return payload

    def writeData(self, _data: bytes) -> int:
        return -1

    def isSequential(self) -> bool:
        return True

    def bytesAvailable(self) -> int:
        with self._condition:
            return round(self._size/self._raw_ratio) + super().bytesAvailable()


class _AudioEngineWorker(QObject):
    telemetry = Signal(object)
    synchronize_complete = Signal()
    shutdown_complete = Signal()

    def __init__(self, ffmpeg_path: Path) -> None:
        super().__init__()
        self.ffmpeg_path = Path(ffmpeg_path)
        self.device: _PcmRingDevice | None = None
        self.sink: QAudioSink | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self._feeder: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._source_path = ""
        self._source_start_ms = 0
        self._av_sync_map = None
        self._decoder_command_start_ms = 0
        self._startup_requested_source_ms = 0
        self._requested_source_ms = 0
        self._effective_rate = 1.0
        self._paused = True
        self._active = False
        self._sink_started = False
        self._decode_started_at = 0.0
        self._first_pcm_at = 0.0
        self._underruns = 0
        self._drift_ms = 0.0
        self._previous_drift_ms: float | None = None
        self._output_spec: AudioOutputSpec | None = None
        self._output_device = ""
        self._output_device_id = b''
        self._endpoint_generation = 0
        self._last_device_check = 0.
        self._decode_recoveries = deque(maxlen=3)
        self._clock_sequence = 0
        self._source_generation = 0
        self._ring_generation = 0
        self._session_generation = 0
        self._transport_generation = None
        self._last_state = "IDLE"
        self._decoder_command: list[str] = []
        self._decoder_read_count = 0
        self._decoder_first_read_at = 0.0
        self._decoder_first_read_bytes = 0
        self._decoder_trim_attempts = 0
        self._decoder_trimmed_bytes = 0
        self._decoder_last_trim_bytes = 0
        self._decoder_startup_pending = False
        self._decoder_eof = False
        self._decoder_error = ""
        self._decoder_returncode: int | None = None
        self._audio_wakeup_count = 0
        self._audio_gate_trace_count = 0
        self._mix_layers = ()
        self._mix_identity = ()
        self._transport_rate = 1.0
        self._gain_db = 0.
        self._source_out_ms = None
        self._track_id = ''
        self._drain_timer = None

    def _ensure_sink(self) -> bool:
        if self.sink is not None and self.device is not None:
            return True
        output = QMediaDevices.defaultAudioOutput()
        if output.isNull():
            self._emit("NO_OUTPUT_DEVICE")
            return False
        audio_format = QAudioFormat()
        audio_format.setSampleRate(SAMPLE_RATE)
        audio_format.setChannelCount(CHANNELS)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not output.isFormatSupported(audio_format):
            audio_format = output.preferredFormat()
        spec = _audio_output_spec(audio_format)
        if spec is None:
            self._emit("UNSUPPORTED_OUTPUT_FORMAT")
            return False
        self._output_spec = spec
        self._output_device = str(output.description() or "default")
        self._output_device_id = bytes(output.id())
        self._endpoint_generation += 1
        self.device = _PcmRingDevice(
            self,
            sample_format=spec.sample_format,
            capacity_bytes=spec.bytes_per_second,
        )
        # This is the queue -> native sink handoff. Without the connection the
        # decoder and ring are healthy but QAudioSink.start(device) is never
        # called, producing the former logical-PASS / physically-silent state.
        self.device.data_available.connect(
            self._audio_data_available,
            Qt.ConnectionType.QueuedConnection,
        )
        self.sink = QAudioSink(output, audio_format, self)
        # The endpoint now has its own process/GIL; it does not need to queue
        # hundreds of milliseconds to survive GUI paints or accessibility.
        self.sink.setBufferSize(round(spec.bytes_per_second * PREBUFFER_SECONDS))
        # PySide 6.9 on Windows cannot marshal QAudio::State through its Python
        # meta-call layer reliably. Playback does not depend on this advisory
        # signal; queue depth/processed bytes provide the underrun evidence.
        return True

    @Slot()
    def _audio_data_available(self) -> None:
        device = self.device
        self._audio_wakeup_count += 1
        if device is not None:
            with device._wake_lock:
                device._wake_pending = False
        ring_generation, source_start_ms = (
            device.source_start_snapshot() if device is not None else (None, None)
        )
        has_pcm = bool(
            device is not None
            and ring_generation == self._ring_generation
            and device.has_produced_pcm()
        )
        wakeup_fields = {
            "wakeup_count": self._audio_wakeup_count,
            "has_pcm": has_pcm,
            "paused": self._paused,
            "active": self._active,
            "sink_started": self._sink_started,
            "ring_available": int(device.bytesAvailable()) if device is not None else 0,
            "ring_produced": int(device.produced_bytes) if device is not None else 0,
            "ring_consumed": int(device.consumed_bytes) if device is not None else 0,
            "ring_size": int(device._size) if device is not None else 0,
            "ring_wake_pending": bool(device._wake_pending) if device is not None else False,
            "ring_append_count": int(device.append_count) if device is not None else 0,
            "ring_wake_emit_count": int(device.wake_emit_count) if device is not None else 0,
            "ring_wake_suppressed_count": int(device.wake_suppressed_count) if device is not None else 0,
            "ring_read_calls": int(device.read_calls) if device is not None else 0,
            "ring_read_nonempty_calls": int(device.read_nonempty_calls) if device is not None else 0,
            "ring_last_read_bytes": int(device.last_read_bytes) if device is not None else 0,
            "ring_generation": ring_generation,
            "source_start_metadata_ms": source_start_ms,
        }
        if self._audio_wakeup_count <= 16:
            self._trace_decoder("AUDIO_SINK_WAKE", **wakeup_fields)
        if has_pcm and not self._first_pcm_at and source_start_ms is not None:
            self._source_start_ms = round(source_start_ms)
        # A queued wakeup from the previous decoder may arrive after the ring
        # has been reset. It must not start the sink or mark this generation
        # ready before its own feeder has produced PCM.
        if has_pcm and self._paused:
            self._emit("BUFFERED")
        if self.sink is None or device is None or not has_pcm or self._paused or not self._active:
            return
        if not self._sink_started:
            spec = self._output_spec
            prebuffer_bytes = round(
                (spec.bytes_per_second if spec is not None else BYTES_PER_SECOND) * PREBUFFER_SECONDS
            )
            available = int(device.bytesAvailable())
            if available < prebuffer_bytes and not self._decoder_eof:
                self._audio_gate_trace_count += 1
                if self._audio_gate_trace_count <= 8:
                    self._trace_decoder(
                        "AUDIO_SINK_PREBUFFER_WAIT",
                        available=available,
                        required=prebuffer_bytes,
                        **wakeup_fields,
                    )
                return
            device.publish_enabled = True
            self.sink.start(device)
            self._sink_started = True
            # Drift samples collected while the decoder was waiting for its
            # first PCM/prebuffer belong to startup, not steady state.
            self._previous_drift_ms = None
            self._trace_decoder(
                "AUDIO_SINK_START",
                prebuffer_bytes=prebuffer_bytes,
                ring_available=int(device.bytesAvailable()),
            )
        else:
            device.publish_enabled = True
            self.sink.resume()
            if self._audio_wakeup_count <= 16:
                self._trace_decoder("AUDIO_SINK_RESUME", **wakeup_fields)
        if not self._first_pcm_at:
            self._first_pcm_at = time.perf_counter()
        self._emit("PLAYING")

    def _sink_state_changed(self, state) -> None:
        name = getattr(state, "name", str(state))
        if name == "IdleState" and self._active and not self._paused:
            self._underruns += 1
        self._emit(name)

    def _estimated_source_ms(self) -> float:
        processed = float(self.sink.processedUSecs()) / 1000.0 if self.sink is not None and self._sink_started else 0.0
        # WASAPI processedUSecs already excludes queued native PCM. In the
        # 320 ms headed probe: 2.414 s submitted, 2.094 s processed, 0.320 s
        # queued. Subtracting the queue again manufactured a rate-scaled lag.
        return float(self._source_start_ms) + max(0.0, processed) * self._effective_rate

    def _adopt_source_start_metadata(self) -> float | None:
        """Publish first-PCM timing before evaluating a sync request.

        The feeder thread writes this snapshot under the ring condition while
        the queued wakeup is delivered later.  Synchronize can therefore run
        first; reading the generation-scoped snapshot closes that ordering
        gap without making the worker wait or polling the queue.
        """
        device = self.device
        if device is None:
            return None
        generation, source_start_ms = device.source_start_snapshot()
        if generation != self._ring_generation or source_start_ms is None:
            return None
        if not self._first_pcm_at:
            self._source_start_ms = round(source_start_ms)
        return source_start_ms

    def _trace_decoder(self, event: str, **fields: object) -> None:
        """Emit bounded decoder evidence only for an explicit audit run."""
        if os.environ.get("TWOBYTEASR_AUDIO_TRACE") != "1":
            return
        GLOBAL_STUDIO_TRACE.emit(
            event,
            {
                "source_generation": self._source_generation,
                "session_generation": self._session_generation,
                "pid": int(self.process.pid) if self.process is not None else None,
                "source_path": self._source_path,
                "decoder_command_start_ms": self._decoder_command_start_ms,
                "startup_requested_source_ms": self._startup_requested_source_ms,
                "requested_source_ms": self._requested_source_ms,
                "read_count": self._decoder_read_count,
                "trim_attempts": self._decoder_trim_attempts,
                "trimmed_bytes": self._decoder_trimmed_bytes,
                "startup_pending": self._decoder_startup_pending,
                "elapsed_ms": round(
                    (time.perf_counter() - self._decode_started_at) * 1000.0,
                    3,
                ) if self._decode_started_at else None,
                **fields,
            },
        )

    def _emit(self, state: str) -> None:
        self._last_state = str(state)
        self._clock_sequence += 1
        process = self.process
        process_returncode = process.poll() if process is not None else None
        device = self.device
        spec = self._output_spec
        self.telemetry.emit({
            "state": str(state),
            "transport_generation": self._transport_generation,
            "source_path": self._source_path,
            "source_start_ms": self._source_start_ms,
            "decoder_command_start_ms": self._decoder_command_start_ms,
            "requested_source_ms": self._requested_source_ms,
            "startup_requested_source_ms": self._startup_requested_source_ms,
            "startup_trim_ms": max(0, self._source_start_ms - self._decoder_command_start_ms),
            "source_generation": self._source_generation,
            "ring_generation": self._ring_generation,
            "source_start_metadata_ms": (
                self.device.source_start_snapshot()[1]
                if self.device is not None else None
            ),
            "session_generation": self._session_generation,
            "estimated_source_ms": round(self._estimated_source_ms(), 3),
            "effective_rate": round(self._effective_rate, 4),
            "drift_ms": round(self._drift_ms, 3),
            "buffer_bytes": int(device.bytesAvailable()) if device is not None else 0,
            "decoded_bytes": int(device.produced_bytes) if device is not None else 0,
            "sink_consumed_bytes": int(device.consumed_bytes) if device is not None else 0,
            "decoded_rms": round(float(device.producer_rms), 6) if device is not None else 0.0,
            "pre_sink_rms": round(float(device.producer_rms), 6) if device is not None else 0.0,
            "sink_consumed_rms": round(float(device.consumed_rms), 6) if device is not None else 0.0,
            "decoder_inputs": list(device.input_metrics) if device is not None else [],
            "pcm_transport": "decoder stdout -> process-local ring -> QAudioSink callback; IPC carries control and telemetry only",
            "processed_us": int(self.sink.processedUSecs()) if self.sink is not None and self._sink_started else 0,
            "elapsed_us": int(self.sink.elapsedUSecs()) if self.sink is not None and self._sink_started else 0,
            "sink_bytes_free": int(self.sink.bytesFree()) if self.sink is not None else 0,
            "sink_buffer_bytes": int(self.sink.bufferSize()) if self.sink is not None else 0,
            "output_device": self._output_device,
            "output_device_id": self._output_device_id.decode('utf8', errors='replace'),
            "sink_volume": self.sink.volume() if self.sink is not None else None,
            "device_endpoint_generation": self._endpoint_generation,
            "last_pcm_write_monotonic": device.last_pcm_write_at if device is not None else 0.,
            "active_sources": [dict(x) for x in self._mix_layers] or ([{'source_path':self._source_path,'track_id':self._track_id,'gain_db':self._gain_db}] if self._source_path else []),
            "sink_state": self.sink.state().name if self.sink is not None else None,
            "sink_error": self.sink.error().name if self.sink is not None else None,
            "output_format": {
                "sample_rate": spec.sample_rate,
                "channels": spec.channels,
                "sample_format": getattr(spec.sample_format, "name", str(spec.sample_format)),
                "bytes_per_sample": spec.bytes_per_sample,
                "bytes_per_frame": spec.bytes_per_frame,
                "bytes_per_second": spec.bytes_per_second,
                "ffmpeg_format": spec.ffmpeg_format,
            } if spec is not None else {},
            "underruns": device.starvation_episodes if device is not None else 0,
            "underrun_measurement": "non-EOF empty device callback episodes",
            "device_empty_reads": device.empty_reads if device is not None else 0,
            "callback_gaps_ms": list(device.callback_gaps_ms)[-16:] if device is not None else [],
            "callback_max_ms": max(device.callback_gaps_ms, default=0.) if device is not None else 0.,
            "mix_cost_ms": list(device.mix_cost_ms)[-16:] if device is not None else [],
            "decode_lateness_ms": round((self._first_pcm_at - self._decode_started_at) * 1000.0, 3) if self._first_pcm_at else None,
            "ffmpeg_pid": int(process.pid) if process is not None and process_returncode is None else None,
            "ffmpeg_process_alive": bool(process is not None and process_returncode is None),
            "ffmpeg_returncode": process_returncode,
            "decoder_command": list(self._decoder_command),
            "decoder_read_count": self._decoder_read_count,
            "decoder_first_read_ms": round(
                (self._decoder_first_read_at - self._decode_started_at) * 1000.0, 3
            ) if self._decoder_first_read_at and self._decode_started_at else None,
            "decoder_first_read_bytes": self._decoder_first_read_bytes,
            "decoder_trim_attempts": self._decoder_trim_attempts,
            "decoder_trimmed_bytes": self._decoder_trimmed_bytes,
            "decoder_last_trim_bytes": self._decoder_last_trim_bytes,
            "decoder_startup_pending": self._decoder_startup_pending,
            "decoder_eof": self._decoder_eof,
            "decoder_error": self._decoder_error,
            "decoder_returncode": self._decoder_returncode,
            "audio_wakeup_count": self._audio_wakeup_count,
            "audio_gate_trace_count": self._audio_gate_trace_count,
            "ring_size": int(device._size) if device is not None else 0,
            "ring_append_count": int(device.append_count) if device is not None else 0,
            "ring_wake_emit_count": int(device.wake_emit_count) if device is not None else 0,
            "ring_wake_suppressed_count": int(device.wake_suppressed_count) if device is not None else 0,
            "ring_read_calls": int(device.read_calls) if device is not None else 0,
            "ring_read_nonempty_calls": int(device.read_nonempty_calls) if device is not None else 0,
            "ring_last_read_bytes": int(device.last_read_bytes) if device is not None else 0,
            "windows_sink_count": 1 if self.sink is not None else 0,
            "paused": self._paused,
            "clock_sequence": self._clock_sequence,
            "clock_monotonic_ts": time.monotonic(),
            # AudioEngine is an external/secondary sink only.  It never owns
            # the Studio presentation clock, so there is deliberately no
            # timer-based clock sampler here.
            "clock_timer_alive": False,
        })

    def _stop_decoder(self) -> None:
        self._stop_event.set()
        if self.device is not None:
            self.device.reset_stream()
        process = self.process
        self.process = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=0.35)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=0.35)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        feeder = self._feeder
        self._feeder = None
        if feeder is not None and feeder is not threading.current_thread():
            feeder.join(timeout=0.4)
        for stream in (
            getattr(process, "stdout", None),
            getattr(process, "stderr", None),
        ) if process is not None else ():
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def prepare_shutdown(self) -> None:
        """Stop producer-side work before the queued Qt teardown slot runs.

        This method intentionally touches only the thread-safe ring/process
        control plane. Native Qt multimedia objects remain owned and stopped
        by ``shutdown`` on the audio worker thread.
        """
        self._active = False
        self._paused = True
        self._stop_event.set()
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _start_decoder(self, source_path: str, source_ms: int, effective_rate: float) -> None:
        if self._drain_timer is not None:
            self._drain_timer.stop()
        if not self._ensure_sink() or self.device is None:
            return
        if self.sink is not None:
            if self._sink_started:
                self.sink.suspend()
                self.sink.stop()
            self._sink_started = False
        # The native pull callback is now quiescent, so clearing the Python
        # ring and joining the previous decoder cannot race QAudioSink.
        self._stop_decoder()
        self._stop_event = threading.Event()
        generation = self.device.reset_stream()
        from .studio_track_gain import gain_amplitude
        inputs = self._mix_layers or ({'track_id': self._track_id, 'gain_db': self._gain_db},)
        self.device.configure_mix([x.get('audio_track_id') or x.get('track_id','') for x in inputs],
            self._output_spec, [gain_amplitude(x.get('gain_db',0.)) for x in inputs])
        self._ring_generation = generation
        self._source_path = str(source_path)
        self._source_generation += 1
        self._source_start_ms = max(0, int(source_ms))
        self._decoder_command_start_ms = self._source_start_ms
        self._startup_requested_source_ms = self._source_start_ms
        self._requested_source_ms = self._source_start_ms
        self._effective_rate = max(0.125, min(8.0, float(effective_rate)))
        self._decode_started_at = time.perf_counter()
        self._first_pcm_at = 0.0
        self._sink_started = False
        self._decoder_command = []
        self._decoder_read_count = 0
        self._decoder_first_read_at = 0.0
        self._decoder_first_read_bytes = 0
        self._decoder_trim_attempts = 0
        self._decoder_trimmed_bytes = 0
        self._decoder_last_trim_bytes = 0
        self._decoder_startup_pending = True
        self._decoder_eof = False
        self._decoder_error = ""
        self._decoder_returncode = None
        self._audio_wakeup_count = 0
        self._audio_gate_trace_count = 0
        command = build_audio_decode_command(
            self.ffmpeg_path,
            self._source_path,
            source_ms=self._source_start_ms,
            rate=self._effective_rate,
            sample_rate=self._output_spec.sample_rate if self._output_spec is not None else SAMPLE_RATE,
            channels=self._output_spec.channels if self._output_spec is not None else CHANNELS,
            pcm_format="f32le",
            gain_db=0., source_out_ms=self._source_out_ms,
            av_sync_map=self._av_sync_map,
        )
        if len(self._mix_layers) > 1:
            command = build_audio_mix_command(
                self.ffmpeg_path, self._mix_layers, transport_rate=self._transport_rate,
                sample_rate=self._output_spec.sample_rate, channels=self._output_spec.channels,
                pcm_format="f32le", separate=True,
                av_sync_map=self._av_sync_map,
            )
        self._decoder_command = list(command)
        from .processes import popen_hidden_subprocess
        self.process = popen_hidden_subprocess(
            command,
            purpose='Studio audio PCM decoder',
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process = self.process
        self._trace_decoder("AUDIO_DECODER_START", command=list(command))
        stop_event = self._stop_event
        device = self.device
        spec = self._output_spec
        raw_ratio = device._raw_ratio
        def errors():
            from .provider_diagnostics import redact_diagnostics
            for line in iter(process.stderr.readline, b''):
                if self.process is not process or stop_event.is_set():return
                self._decoder_error = redact_diagnostics(line.decode('utf8',errors='replace').strip())[-600:]
        threading.Thread(target=errors, name='studio-audio-errors', daemon=True).start()

        def feed() -> None:
            stream = process.stdout
            if stream is None:
                return
            decoded_source_ms = float(self._decoder_command_start_ms)
            startup_requested_source_ms = float(self._startup_requested_source_ms)
            startup_pending = True
            startup_target_captured = False
            # QAudioFormat may negotiate 6 channels. Decoder input must stay
            # on complete interleaved frames, including short pipe reads.
            raw_frame_bytes = round(spec.bytes_per_frame * raw_ratio)
            read_bytes = max(raw_frame_bytes, (int(4096*raw_ratio)//raw_frame_bytes)*raw_frame_bytes)
            remainder = b''
            try:
                while not stop_event.is_set():
                    read_started = time.perf_counter()
                    incoming = stream.read(read_bytes)
                    payload = remainder + incoming
                    complete_bytes = len(payload)//raw_frame_bytes*raw_frame_bytes
                    payload, remainder = payload[:complete_bytes], payload[complete_bytes:]
                    read_finished = time.perf_counter()
                    if self.process is not process or stop_event.is_set() or generation!=device._generation:return
                    self._decoder_read_count += 1
                    if not self._decoder_first_read_at:
                        self._decoder_first_read_at = read_finished
                        self._decoder_first_read_bytes = len(payload)
                    if not payload and incoming:
                        continue
                    if not payload:
                        self._decoder_eof = True
                        self._decoder_returncode = process.poll()
                        self._trace_decoder(
                            "AUDIO_DECODER_EOF",
                            read_block_ms=round((read_finished - read_started) * 1000.0, 3),
                        )
                        # Short tails can be smaller than the startup buffer.
                        device.data_available.emit()
                        break
                    chunk_source_ms = decoded_source_ms
                    decoded_source_ms += (
                        len(payload) * self._effective_rate * 1000.0 /
                        max(1, spec.bytes_per_second*raw_ratio if spec is not None else BYTES_PER_SECOND)
                    )
                    retained_source_ms = None
                    if startup_pending:
                        # Keep the requested first sample. Playback waits for
                        # this generation's prebuffer instead of skipping PCM.
                        # The metadata helper remains frame aligned.
                        if not startup_target_captured:
                            # The transport waits for this buffer before play.
                            # Preserve the requested first sample, including
                            # rate changes; never chase a running video clock
                            # by silently deleting the start of the audio.
                            self._startup_requested_source_ms = round(
                                startup_requested_source_ms
                            )
                            startup_target_captured = True
                        before_trim_bytes = len(payload)
                        self._decoder_trim_attempts += 1
                        payload, retained_source_ms = trim_startup_pcm(
                            payload, chunk_source_ms=chunk_source_ms,
                            requested_source_ms=startup_requested_source_ms,
                            effective_rate=self._effective_rate,
                            bytes_per_second=round(spec.bytes_per_second*raw_ratio) if spec else BYTES_PER_SECOND,
                            bytes_per_frame=round(spec.bytes_per_frame*raw_ratio) if spec else CHANNELS * BYTES_PER_SAMPLE,
                        )
                        self._decoder_last_trim_bytes = before_trim_bytes - len(payload)
                        self._decoder_trimmed_bytes += self._decoder_last_trim_bytes
                        self._decoder_startup_pending = not bool(payload)
                        if self._decoder_read_count <= 8:
                            self._trace_decoder(
                                "AUDIO_DECODER_READ",
                                bytes_read=before_trim_bytes,
                                bytes_retained=len(payload),
                                chunk_source_ms=round(chunk_source_ms, 3),
                                read_block_ms=round((read_finished - read_started) * 1000.0, 3),
                            )
                        if not payload:
                            continue
                        startup_pending = False
                        self._decoder_startup_pending = False
                    elif self._decoder_read_count <= 8:
                        self._trace_decoder(
                            "AUDIO_DECODER_READ",
                            bytes_read=len(payload),
                            bytes_retained=len(payload),
                            chunk_source_ms=round(chunk_source_ms, 3),
                            read_block_ms=round((read_finished - read_started) * 1000.0, 3),
                        )
                    appended = device.append(
                        payload, generation, stop_event, source_start_ms=retained_source_ms,
                    )
                    if appended:device.last_pcm_write_at=time.monotonic()
                    if os.environ.get("TWOBYTEASR_AUDIO_TRACE") == "1" and (
                        device.append_count <= 12 or not appended
                    ):
                        self._trace_decoder(
                            "AUDIO_RING_APPEND",
                            appended=bool(appended),
                            bytes_appended=len(payload),
                            ring_size=int(device._size),
                            ring_produced=int(device.produced_bytes),
                            ring_wake_pending=bool(device._wake_pending),
                            ring_wake_emit_count=int(device.wake_emit_count),
                            ring_wake_suppressed_count=int(device.wake_suppressed_count),
                        )
                    if not appended:
                        break
            except (OSError, RuntimeError):
                self._decoder_error = "stream_read_or_append"
                self._decoder_returncode = process.poll()
                self._trace_decoder("AUDIO_DECODER_ERROR", error=self._decoder_error)
                pass
            finally:
                with device._condition:
                    if generation == device._generation:
                        device.end_of_stream = True
                if self.process is not process or generation!=device._generation:return
                self._decoder_returncode = process.poll()
                self._trace_decoder(
                    "AUDIO_DECODER_EXIT",
                    returncode=self._decoder_returncode,
                    stop_requested=stop_event.is_set(),
                )

        self._feeder = threading.Thread(target=feed, name="studio-audio-decoder", daemon=True)
        self._feeder.start()
        self._emit("DECODING")

    @Slot(object)
    def synchronize(self, payload: object) -> None:
        try:
            request = dict(payload) if isinstance(payload, Mapping) else {}
            map_payload = request.get("av_sync_map")
            if map_payload:
                from .avsync import AVSyncMap
                try:
                    self._av_sync_map = AVSyncMap.from_dict(map_payload)
                except (ValueError, KeyError, TypeError):
                    self._av_sync_map = None
            else:
                self._av_sync_map = None
            request_generation = int(request.get("session_generation") or 0)
            if request_generation < self._session_generation:
                return
            if request.get("drain"):
                self._begin_drain()
                return
            if self._drain_timer is not None:
                self._drain_timer.stop()
            self._session_generation = request_generation
            transport_generation = request.get('transport_generation')
            discontinuity = transport_generation is not None and transport_generation != self._transport_generation
            self._transport_generation = transport_generation
            mix_layers = tuple(request.get("mix_layers") or ())
            mix_identity = tuple((item.get("clip_id"), item.get("source_path"), item.get("playback_rate", 1.0), item.get("source_out_ms"))
                                 for item in mix_layers)
            discontinuity = discontinuity or mix_identity != self._mix_identity
            self._mix_layers, self._mix_identity = mix_layers, mix_identity
            self._transport_rate = float(request.get("transport_rate") or 1.)
            gain_db = float(request.get("gain_db", 0.))
            source_out_ms = request.get("source_out_ms")
            discontinuity = discontinuity or source_out_ms != self._source_out_ms
            self._gain_db, self._source_out_ms = gain_db, source_out_ms
            self._track_id = str(request.get('audio_track_id') or request.get('track_id') or '')
            if self.device is not None:
                from .studio_track_gain import gain_amplitude
                inputs = mix_layers or (request,)
                self.device.set_gains({x.get('audio_track_id') or x.get('track_id',''):gain_amplitude(x.get('gain_db',0.)) for x in inputs})
            source_path = str(request.get("source_path") or "")
            audible = bool(request.get("audible", False) and source_path)
            self._paused = bool(request.get("paused", True))
            if self.device is not None:
                self.device.publish_enabled = not self._paused and self._sink_started
            if not audible:
                self._active = False
                self._paused = True
                self._stop_decoder()
                # The decoder is gone, so the project-owned source identity
                # must not survive in SILENT telemetry: the persistent
                # thread/sink actor stays, but the next emit must not report
                # the closed project as the current source.
                self._source_path = ""
                self._source_start_ms = 0
                self._decoder_command_start_ms = 0
                self._requested_source_ms = 0
                self._effective_rate = 1.0
                self._drift_ms = 0.0
                self._previous_drift_ms = None
                self._decode_started_at = 0.0
                self._first_pcm_at = 0.0
                if self.sink is not None:
                    self.sink.suspend()
                self._emit("SILENT")
                return
            source_ms = max(0, int(request.get("source_ms") or 0))
            self._requested_source_ms = source_ms
            effective_rate = max(
                0.125,
                min(8.0, float(request.get("clip_rate") or 1.0) * float(request.get("transport_rate") or 1.0)),
            )
            self._active = True
            now=time.monotonic()
            if self.sink is not None and now-self._last_device_check>.5:
                self._last_device_check=now
                output=QMediaDevices.defaultAudioOutput()
                failed=self.sink.error().name in {'IOError','FatalError','OpenError'}
                changed=bytes(output.id())!=self._output_device_id
                if failed or changed:
                    # Recreate only the failed audio endpoint, never video lanes.
                    self._stop_decoder();self.sink.stop();self.sink.deleteLater()
                    if self.device is not None:self.device.close();self.device.deleteLater()
                    self.sink=self.device=None;self._sink_started=False
                    discontinuity=True
            if self.sink is not None:
                self.sink.setVolume(max(0.0, min(1.0, float(request.get("volume") or 0.0))))
            source_start_metadata_ms = self._adopt_source_start_metadata()
            self._drift_ms = source_ms - self._estimated_source_ms()
            ring_generation = (
                self.device.source_start_snapshot()[0]
                if self.device is not None else None
            )
            decoder_ready = bool(
                self._sink_started
                and self.device is not None
                and ring_generation == self._ring_generation
                and self.device.has_produced_pcm()
            )
            restart = discontinuity or decoder_restart_required(
                # Successful decode EOF means buffered PCM is still valid.
                # Restarting here discarded/replayed the tail every UI tick.
                process_alive=self.process is not None and self.process.poll() in (None, 0),
                same_source=self._source_path == source_path,
                same_rate=abs(self._effective_rate - effective_rate) <= 0.001,
                drift_ms=self._drift_ms,
                paused=self._paused,
                previous_drift_ms=self._previous_drift_ms,
                # ``_first_pcm_at`` is a sink-start timestamp and can be set
                # by a stale queued wakeup. Readiness belongs to this ring
                # generation and is true only after its feeder produced PCM.
                decoder_ready=decoder_ready,
                # Every seek/source/rate change already owns a generation.
                # Timer latency or native buffer depth must never replay/drop
                # PCM via periodic drift-triggered decoder replacement.
                allow_drift_restart=False,
            )
            self._trace_decoder(
                "AUDIO_DECODER_SYNC_DECISION",
                process_alive=bool(self.process is not None and self.process.poll() is None),
                same_source=self._source_path == source_path,
                same_rate=abs(self._effective_rate - effective_rate) <= 0.001,
                drift_ms=round(self._drift_ms, 3),
                previous_drift_ms=(
                    round(self._previous_drift_ms, 3)
                    if self._previous_drift_ms is not None else None
                ),
                decoder_ready=decoder_ready,
                ring_generation=ring_generation,
                source_start_metadata_ms=source_start_metadata_ms,
                sink_started=bool(self._sink_started),
                ring_produced_bytes=(
                    int(self.device.produced_bytes) if self.device is not None else 0
                ),
                ring_consumed_bytes=(
                    int(self.device.consumed_bytes) if self.device is not None else 0
                ),
                sink_processed_us=(
                    int(self.sink.processedUSecs())
                    if self.sink is not None and self._sink_started else 0
                ),
                sink_elapsed_us=(
                    int(self.sink.elapsedUSecs())
                    if self.sink is not None and self._sink_started else 0
                ),
                restart=bool(restart),
            ) if restart else None
            if restart or not decoder_ready:
                self._previous_drift_ms = None
            else:
                self._previous_drift_ms = self._drift_ms
            if restart:
                failed_decoder = self.process is not None and self.process.poll() not in (None,0)
                if failed_decoder and not discontinuity:
                    if len(self._decode_recoveries)==3 and now-self._decode_recoveries[0]<30.:
                        self._emit('DECODER_FAILED');return
                    self._decode_recoveries.append(now)
                self._start_decoder(source_path, source_ms, effective_rate)
                if self.sink is not None:
                    self.sink.setVolume(max(0.0, min(1.0, float(request.get("volume") or 0.0))))
            if self.sink is not None and self._sink_started:
                if self.device is not None:
                    self.device.publish_enabled = not self._paused
                self.sink.suspend() if self._paused else self.sink.resume()
            elif not self._paused:
                self._audio_data_available()
            self._emit("PAUSED" if self._paused else "SYNCED")
        finally:
            self.synchronize_complete.emit()

    @Slot()
    def _begin_drain(self) -> None:
        if self.sink is None or self.device is None or not self._active:
            return
        self._paused = False
        self._audio_data_available()
        if self._drain_timer is None:
            self._drain_timer = QTimer(self)
            self._drain_timer.setInterval(10)
            self._drain_timer.timeout.connect(self._drain_tick)
        if not self._drain_timer.isActive():
            self._drain_started_at = time.monotonic()
            self._drain_empty_deadline = None
            self._drain_timer.start()
        self._emit("DRAINING")

    def _drain_tick(self) -> None:
        spec = self._output_spec
        now = time.monotonic()
        if self._decoder_eof and self.device.bytesAvailable() == 0 and self._drain_empty_deadline is None:
            submitted_ms = self.device.consumed_bytes * 1000 / spec.bytes_per_second
            remaining_ms = max(0., submitted_ms-self.sink.processedUSecs()/1000.)
            remaining_ms += self.sink.bufferSize() * 1000 / spec.bytes_per_second + 30
            self._drain_empty_deadline = now + remaining_ms/1000.
        if (self._drain_empty_deadline is not None and now >= self._drain_empty_deadline) or now-self._drain_started_at > 2:
            self._drain_timer.stop()
            self.sink.suspend()
            self._paused = True
            self._active = False
            self._emit("DRAINED")

    @Slot()
    def shutdown(self) -> None:
        if self._drain_timer is not None:
            self._drain_timer.stop()
        self._emit("SHUTDOWN_BEGIN")
        self._active = False
        self._paused = True
        if self.sink is not None:
            self._emit("SHUTDOWN_SINK_SUSPEND_BEGIN")
            # QAudioSink.stop() can enter the Windows WASAPI teardown path
            # while its feeder callback is still unwinding. Suspend first and
            # drain deferred deletes on the owning thread before quitting it.
            self.sink.suspend()
            if self._sink_started:
                self.sink.stop()
            self._sink_started = False
            self._emit("SHUTDOWN_SINK_SUSPENDED")
        self._stop_decoder()
        self._emit("SHUTDOWN_DECODER_STOPPED")
        if self.device is not None:
            self._emit("SHUTDOWN_DEVICE_CLOSE_BEGIN")
            self.device.close()
            self._emit("SHUTDOWN_DEVICE_CLOSED")
        owner_thread = QThread.currentThread()
        if self.sink is not None:
            self._emit("SHUTDOWN_SINK_STOP_BEGIN")
            try:
                self.sink.stop()
            except Exception as exc:  # native backend may already be idle
                self._emit(f"SHUTDOWN_SINK_STOP_FAILED:{type(exc).__name__}")
            self._emit("SHUTDOWN_SINK_STOPPED")
        self._emit("SHUTDOWN")
        self.deleteLater()
        owner_thread.quit()
        self.shutdown_complete.emit()


class StudioAudioEngine(QObject):
    """GUI facade; the Project PlaybackClock remains the only time owner."""

    _sync_call = Signal(object)
    _shutdown_call = Signal()
    _capture_call = Signal(object)

    def __init__(self, parent: QObject | None = None, *, ffmpeg_path: Path | None = None, isolated: bool = True) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._thread.setObjectName("StudioAudioEngine")
        self._thread.setParent(self)
        if isolated:
            from .audio_process import AudioProcessBridge
            self._worker = AudioProcessBridge(ffmpeg_path or studio_ffmpeg_path())
            self._capture_call.connect(self._worker.capture)
        else:
            self._worker = _AudioEngineWorker(ffmpeg_path or studio_ffmpeg_path())
        self._worker.moveToThread(self._thread)
        self._sync_call.connect(self._worker.synchronize)
        self._shutdown_call.connect(self._worker.shutdown)
        self._worker.telemetry.connect(self._capture_telemetry)
        self._worker.synchronize_complete.connect(self._synchronize_complete)
        # Finish native multimedia teardown on the audio worker thread.
        self._thread.finished.connect(self._worker.deleteLater)
        self._telemetry: dict[str, Any] = {"state": "IDLE", "windows_sink_count": 0}
        self._session_generation = 0
        self._shutdown_requested = False
        self._sync_inflight = False
        self._pending_sync: dict[str, Any] | None = None
        self._last_source_request = None
        self._av_sync_map_payload = None
        # 7c4fb89 只在 set_av_sync_map 里初始化这组状态：synchronize
        # 先到（未设置过映射的工程）就 AttributeError。__init__ 兜底。
        self._draining = False
        self._request_generation = 0
        self._last_payload: dict[str, Any] = {}
        # A caller without an AV-sync map still owns a live audio worker.
        # Starting only in set_av_sync_map left synchronize signals queued
        # forever in standalone playback/recovery paths.
        self._thread.start()

    def set_av_sync_map(self, sync_map) -> None:
        """Carry the AV sync map inside every synchronize payload.

        Kept as a plain dict so the isolated audio endpoint process
        reconstructs it after the pipe crossing without pickle coupling.
        """
        if sync_map is not None and not sync_map.is_identity:
            self._av_sync_map_payload = sync_map.to_dict()
        else:
            self._av_sync_map_payload = None
        self._request_generation = 0
        self._last_payload = {}
        self._draining = False

    @Slot(object)
    def _capture_telemetry(self, payload: object) -> None:
        if isinstance(payload, Mapping):
            generation = int(payload.get("session_generation") or 0)
            if generation == self._session_generation:
                expected=getattr(self,'_last_payload',{}).get('transport_generation')
                actual=payload.get('transport_generation')
                if expected is not None and actual is not None and tuple(expected)!=tuple(actual):return
                self._telemetry = dict(payload)
                now=time.monotonic()
                self._telemetry['received_monotonic']=now
                if now-getattr(self,'_last_diagnostic_at',0.)>=1.:
                    self._last_diagnostic_at=now
                    owner=self.parent()
                    if owner is not None and hasattr(owner,'video'):
                        from .studio_performance import performance_snapshot
                        GLOBAL_STUDIO_TRACE.emit('PLAYBACK_HEALTH',performance_snapshot(owner,compact=True))
                if str(payload.get('state')) in {'ENDPOINT_FAILED','DECODER_FAILED','NO_OUTPUT_DEVICE'}:
                    hint=getattr(self.parent(),'_show_studio_hint',None)
                    if callable(hint) and now-getattr(self,'_last_failure_hint',0.)>3.:
                        self._last_failure_hint=now
                        hint(str(payload.get('decoder_error') or '音频输出设备不可用，请检查设备后暂停/继续'))
                if payload.get('system_session_muted') and not payload.get('paused',True):
                    hint=getattr(self.parent(),'_show_studio_hint',None)
                    if callable(hint) and now-getattr(self,'_last_system_mute_hint',0.)>15.:
                        self._last_system_mute_hint=now
                        hint('Windows 音量混音器已将 2ByteASR 音频会话静音，请在系统混音器中取消静音；程序内播放音量正常。')
                if (
                    str(payload.get("state") or "").upper() == "PLAYING"
                    and int(payload.get("sink_consumed_bytes") or 0) > 0
                ):
                    owner = self.parent()
                    marker = getattr(owner, "_studio_mark_startup_milestone", None)
                    if callable(marker):
                        marker(
                            "FIRST_AUDIO_READY",
                            decoded_bytes=int(payload.get("decoded_bytes") or 0),
                            sink_consumed_bytes=int(payload.get("sink_consumed_bytes") or 0),
                            source_path=str(payload.get("source_path") or ""),
                        )

    def synchronize_mix(self, layers, *, paused: bool, transport_rate: float, volume: float) -> None:
        audible = [dict(layer) for layer in layers if layer.get("source_path")]
        anchor = dict(audible[0]) if audible else {}
        anchor["mix_layers"] = audible
        self.synchronize(anchor, audible=bool(audible), paused=paused,
                         transport_rate=transport_rate, volume=volume)

    def synchronize(
        self,
        layer: Mapping[str, Any] | None,
        *,
        audible: bool,
        paused: bool,
        transport_rate: float,
        volume: float,
    ) -> None:
        payload = dict(layer or {})
        if self._av_sync_map_payload is not None:
            payload["av_sync_map"] = self._av_sync_map_payload
        if self._draining and not audible:
            return
        self._draining = False
        now = time.monotonic()
        target = int(payload.get('source_ms') or 0)
        identity = (str(payload.get('source_path') or ''), str(payload.get('clip_id') or ''),
                    payload.get('source_out_ms'),
                    tuple((item.get('clip_id'), item.get('source_out_ms'))
                          for item in payload.get('mix_layers', ())))
        effective_rate = float(payload.get('playback_rate') or 1.) * float(transport_rate)
        previous = self._last_source_request
        if previous is not None:
            prev_identity, prev_target, prev_at, prev_paused, prev_rate = previous
            expected = prev_target + (0. if prev_paused else (now-prev_at)*1000*prev_rate)
            # Explicit PlaybackClock generations identify seeks. A GUI timer
            # arriving late at 4x is not a seek and must not reset PCM.
            if identity != prev_identity:
                self._request_generation += 1
        self._last_source_request = (identity, target, now, bool(paused), effective_rate)
        owner = self.parent()
        clock = getattr(getattr(owner, 'video', None), '_playback_clock', None)
        # Clip changes and source discontinuities can precede the optimistic
        # clock seek by one UI callback. Carry both epochs, persistently, so
        # coalescing and source remaps cannot keep old queued PCM alive.
        payload['transport_generation'] = (int(clock.generation) if clock is not None else 0, self._request_generation)
        payload.update({
            "audible": bool(audible),
            "paused": bool(paused),
            "transport_rate": float(transport_rate),
            "clip_rate": float(payload.get("playback_rate") or 1.0),
            "volume": max(0.0, min(1.0, float(volume))),
            "session_generation": self._session_generation,
            "submitted_monotonic": time.monotonic(),
        })
        if self._shutdown_requested:
            return
        self._last_payload = payload
        self._pending_sync = payload
        self._flush_sync()

    def unload(self) -> int:
        """Fence the old project and asynchronously silence its only sink.

        The QThread and QAudioSink are intentionally reused by the next
        project; generations prevent queued telemetry/PCM ownership from the
        previous project from crossing that boundary.
        """
        if self._shutdown_requested:
            return self._session_generation
        self._draining = False
        self._last_payload = {}
        self._session_generation += 1
        generation = self._session_generation
        self._telemetry = {
            "state": "SILENT",
            "source_path": "",
            "session_generation": generation,
            "source_generation": 0,
            "windows_sink_count": int(self._telemetry.get("windows_sink_count") or 0),
            "clock_sequence": 0,
            "clock_timer_alive": False,
            "paused": True,
        }
        self._pending_sync = {
            "source_path": "",
            "audible": False,
            "paused": True,
            "transport_rate": 1.0,
            "clip_rate": 1.0,
            "volume": 0.0,
            "session_generation": generation,
        }
        self._flush_sync()
        return generation

    def _flush_sync(self) -> None:
        if self._sync_inflight or self._pending_sync is None or self._shutdown_requested:
            return
        payload = self._pending_sync
        self._pending_sync = None
        self._sync_inflight = True
        self._sync_call.emit(payload)

    @Slot()
    def _synchronize_complete(self) -> None:
        self._sync_inflight = False
        self._flush_sync()

    def telemetry_snapshot(self) -> dict[str, Any]:
        return {
            **dict(self._telemetry),
            "engine_thread_alive": bool(self._thread.isRunning()),
            "engine_thread_count": 1 if self._thread.isRunning() else 0,
            "session_generation": self._session_generation,
        }

    def ready_for_playback(self) -> bool:
        request = self._last_payload
        if not request.get("audible"):
            return True
        state = self._telemetry
        if state.get("state") in {"NO_OUTPUT_DEVICE", "UNSUPPORTED_OUTPUT_FORMAT"}:
            return True
        if state.get("source_path") != request.get("source_path") or tuple(state.get("transport_generation") or ()) != tuple(request.get("transport_generation") or ()):
            return False
        rate = request.get("clip_rate", 1.) * request.get("transport_rate", 1.)
        if abs(float(state.get("effective_rate", 1.))-rate) > .001:
            return False
        bps = (state.get("output_format") or {}).get("bytes_per_second", BYTES_PER_SECOND)
        return bool(state.get("decoder_eof") or state.get("buffer_bytes", 0) >= bps * PREBUFFER_SECONDS)

    def finish_playback(self) -> None:
        if self._draining or self._shutdown_requested:
            return
        request = self._last_payload
        clock = getattr(getattr(self.parent(), 'video', None), '_playback_clock', None)
        epoch = request.get('transport_generation', (None,))[0]
        if request.get('paused', True) or (clock is not None and epoch != clock.generation):
            # A paused/end seek must never play old queued sound. Only natural
            # completion of the current transport generation drains its tail.
            self.synchronize(None, audible=False, paused=True, transport_rate=1., volume=0.)
            return
        self._draining = True
        self._pending_sync = {"drain": True, "session_generation": self._session_generation}
        self._flush_sync()

    def clock_observation(self) -> dict[str, Any]:
        """Return the latest worker-owned sink clock sample.

        The GUI never touches QAudioSink directly; this immutable-ish copy is
        the hand-off used by the ProjectClock for audio-only preview.
        """
        return self.telemetry_snapshot()

    def capture_pcm(self, name: str, enabled: bool) -> None:
        """Acceptance-only recording, validated again by the endpoint process."""
        self._capture_call.emit({'name':name,'enabled':bool(enabled)})

    def request_shutdown(self) -> None:
        if not self._shutdown_requested:
            self._shutdown_requested = True
            self._pending_sync = None
            # Quiesce the feeder immediately so the queued worker shutdown is
            # not delayed behind decode wakeups already in the event queue.
            self._worker.prepare_shutdown()
            self._shutdown_call.emit()

    def wait_for_shutdown(self, timeout: float = 2.0) -> bool:
        self.request_shutdown()
        stopped = bool(self._thread.wait(max(0, round(float(timeout) * 1000))))
        return stopped


__all__ = [
    "StudioAudioEngine",
    "build_audio_decode_command",
    "studio_ffmpeg_path",
    "trim_startup_pcm",
]
