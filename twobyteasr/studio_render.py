"""Shared FFmpeg ASS burn-in pipeline for preview and final Studio renders."""

from __future__ import annotations

import os
import queue
import json
import math
import re
import subprocess
import threading
import time
import uuid
from dataclasses import replace
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable
from .export_validation import record_completion, publish_output, notify_after_publication, published_output_path

from .processes import (
    hidden_subprocess_kwargs,
    popen_hidden_subprocess,
    run_hidden_subprocess,
)


VIDEO_ENCODERS = {
    "h264": ("h264_nvenc", "h264_qsv", "h264_amf", "libx264"),
    "hevc": ("hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"),
    "av1": ("av1_nvenc", "av1_qsv", "av1_amf", "libsvtav1", "libaom-av1"),
}
HARDWARE_ENCODERS = {
    name for names in VIDEO_ENCODERS.values() for name in names if not name.startswith("lib")
}
PROBE_FRAME_SIZE = "640x360"
CAPABILITY_SCHEMA = 3
CONTAINER_CODECS = {
    "mp4": ("h264", "hevc", "av1"),
    "mkv": ("h264", "hevc", "av1"),
    "mov": ("h264", "hevc"),
    "webm": ("av1",),
    "flv": ("h264",),
}

STAGE_PREPARE_PROJECT = "prepare_project"
STAGE_COMPOSE_VIDEO = "compose_video"
STAGE_PREPARE_SUBTITLES = "prepare_subtitles"
STAGE_ADVANCED_RENDER = "advanced_render"
STAGE_ENCODE = "encode"
STAGE_MUX = "mux"
STAGE_ORDER = (
    STAGE_PREPARE_PROJECT,
    STAGE_COMPOSE_VIDEO,
    STAGE_PREPARE_SUBTITLES,
    STAGE_ADVANCED_RENDER,
    STAGE_ENCODE,
    STAGE_MUX,
)
STAGE_LABELS = {
    STAGE_PREPARE_PROJECT: "准备工程",
    STAGE_COMPOSE_VIDEO: "视频轨合成",
    STAGE_PREPARE_SUBTITLES: "准备字幕",
    STAGE_ADVANCED_RENDER: "高级样式渲染",
    STAGE_ENCODE: "视频编码",
    STAGE_MUX: "封装文件",
}


def export_progress(
    stage: str,
    *,
    message: str = "",
    percent: float | None = None,
    indeterminate: bool | None = None,
    out_time_us: int | str | None = None,
    duration_seconds: float | None = None,
    frame: str = "",
    fps: str = "",
    speed: str = "",
    **extra: object,
) -> dict[str, str]:
    """Build a stage-aware export progress payload.

    Encode is the only stage that should carry a media-time percentage.
    Earlier stages prefer an explicit busy/indeterminate flag over a fake 0%.
    """
    busy = bool(indeterminate) if indeterminate is not None else (
        percent is None and out_time_us is None
    )
    payload: dict[str, str] = {
        "stage": str(stage),
        "stage_label": STAGE_LABELS.get(str(stage), str(stage)),
        "message": str(message or ""),
        "indeterminate": "1" if busy else "0",
    }
    if percent is not None:
        payload["percent"] = f"{max(0.0, min(100.0, float(percent))):.3f}"
    if out_time_us is not None:
        payload["out_time_ms"] = str(out_time_us)
    if duration_seconds is not None:
        payload["duration_seconds"] = f"{float(duration_seconds):.6f}"
    if frame:
        payload["frame"] = str(frame)
    if fps:
        payload["fps"] = str(fps)
    if speed:
        payload["speed"] = str(speed)
    for key, value in extra.items():
        if value is not None:
            payload[str(key)] = str(value)
    return payload


def parse_ffmpeg_out_time_seconds(payload: dict) -> float | None:
    """Parse FFmpeg ``out_time_ms`` / ``out_time`` into seconds, or None."""
    raw = str(payload.get("out_time_us") or payload.get("out_time_ms") or payload.get("out_time") or "")
    if not raw:
        return None
    try:
        if ":" in raw:
            parts = raw.split(":")
            while len(parts) < 3:
                parts.insert(0, "0")
            hours, minutes, seconds = (float(part) for part in parts[:3])
            return hours * 3600.0 + minutes * 60.0 + seconds
        return float(raw) / 1_000_000.0
    except (TypeError, ValueError):
        return None


def windows_subprocess_kwargs() -> dict:
    """Return no-console subprocess flags shared by every FFmpeg probe."""
    return {"shell": False, **hidden_subprocess_kwargs()}


def _capability_cache_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return root / "2ByteASR" / "SubtitleStudio" / "encoder-capabilities.json"


def _ffmpeg_signature(ffmpeg_path: str | os.PathLike[str]) -> dict[str, int | str]:
    path = Path(ffmpeg_path).resolve()
    stat = path.stat()
    return {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _run_probe(command: list[str], *, timeout: float = 20) -> subprocess.CompletedProcess:
    return run_hidden_subprocess(
        command,
        purpose="ffmpeg capability probe",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


@dataclass
class RenderSettings:
    container: str = "mp4"
    codec: str = "h264"
    encoder: str = "auto"
    quality_mode: str = "crf"
    quality: int = 20
    bitrate_kbps: int = 8000
    max_bitrate_kbps: int = 12000
    width: int = 0
    height: int = 0
    fps: float = 0.0
    audio_codec: str = "copy"
    audio_bitrate_kbps: int = 192
    audio_sample_rate: int = 0
    audio_channels: int = 0
    preset: str = "medium"
    profile: str = ""
    level: str = ""
    pixel_format: str = "yuv420p"
    gop: int = 0
    b_frames: int = -1
    font_directory: str = ""

    def validate(self) -> None:
        self.container = self.container.lower()
        self.codec = self.codec.lower()
        self.quality_mode = self.quality_mode.lower()
        if self.container not in CONTAINER_CODECS:
            raise ValueError("unsupported container")
        if self.codec not in VIDEO_ENCODERS:
            raise ValueError("codec must be h264, hevc or av1")
        if self.codec not in CONTAINER_CODECS[self.container]:
            raise ValueError(f"{self.codec} is not supported in {self.container}")
        if self.quality_mode not in {"crf", "cq", "vbr", "cbr", "target", "limited"}:
            raise ValueError("unsupported quality mode")
        if self.quality_mode in {"crf", "cq"}:
            if self.quality is None or not 0 <= int(self.quality) <= 63:
                raise ValueError("quality must be between 0 and 63")
        if self.quality_mode in {"vbr", "cbr", "target", "limited"}:
            if self.bitrate_kbps is None or int(self.bitrate_kbps) <= 0:
                raise ValueError("bitrate must be positive")
        if self.quality_mode in {"vbr", "limited"}:
            if self.max_bitrate_kbps is None or int(self.max_bitrate_kbps) <= 0:
                raise ValueError("maximum bitrate must be positive")
        if self.width is None or self.height is None:
            raise ValueError("width and height use 0 for source dimensions, not None")
        if (int(self.width) < 0 or int(self.height) < 0) or bool(self.width) != bool(self.height):
            raise ValueError("width and height must both be source or positive")
        if self.audio_codec not in {"copy", "aac", "opus", "none"}:
            raise ValueError("unsupported audio codec")
        if int(self.audio_bitrate_kbps) <= 0:
            raise ValueError("audio bitrate must be positive")
        if int(self.audio_sample_rate) not in {0, 32000, 44100, 48000, 96000}:
            raise ValueError("unsupported audio sample rate")
        if int(self.audio_channels) not in {0, 1, 2, 6, 8}:
            raise ValueError("unsupported audio channel count")


@dataclass
class RenderJob:
    media_path: str
    ass_path: str
    output_path: str
    settings: RenderSettings = field(default_factory=RenderSettings)
    start_seconds: float | None = None
    duration_seconds: float | None = None
    overwrite_existing: bool = False
    # Source (in, out) seconds in edited play order. Empty = original file.
    edit_segments: tuple[tuple[float, float], ...] = ()
    # Immutable job-owned media graph; queued jobs never reread a live editor.
    video_graph: dict | None = None
    direct_video_graph: dict | None = None
    composition_resolved: bool = False
    completion_preview_path: str = ''
    completion_metadata: dict = field(default_factory=dict, repr=False)
    preview_callback: Callable | None = field(default=None, repr=False)
    preview_url: str = ''
    # Serialized immutable subtitle/style dependencies for queued exports.
    export_project_data: dict | None = None


def validate_export_config(job: RenderJob) -> None:
    """Validate required values while preserving None for optional full-range fields."""
    job.settings.validate()
    for name, value in (("start_seconds", job.start_seconds), ("duration_seconds", job.duration_seconds)):
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric or None") from exc
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        if name == "start_seconds" and number < 0:
            raise ValueError("start_seconds must not be negative")
        if name == "duration_seconds" and number <= 0:
            raise ValueError("duration_seconds must be positive")


@lru_cache(maxsize=8)
def available_encoders(ffmpeg_path: str | os.PathLike[str]) -> set[str]:
    completed = _run_probe(
        [str(ffmpeg_path), "-hide_banner", "-encoders"],
        timeout=20,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-1200:])
    names = set()
    for line in completed.stdout.splitlines():
        match = re.match(r"^\s*[A-Z\.]{6}\s+(\S+)", line)
        if match:
            names.add(match.group(1))
    return names


def cached_encoder_choices(
    ffmpeg_path: str | os.PathLike[str], codec: str
) -> list[str] | None:
    """Cache-only encoder lookup. ``None`` means no capability cache yet."""
    cached = load_encoder_capabilities(ffmpeg_path)
    if cached is None:
        return None
    values = cached.get("available_by_codec", {}).get(str(codec).lower(), [])
    if not isinstance(values, list):
        return None
    return [str(value) for value in values]


def encoder_choices(ffmpeg_path: str | os.PathLike[str], codec: str) -> list[str]:
    cached = cached_encoder_choices(ffmpeg_path, codec)
    if cached is not None:
        return cached
    available = available_encoders(ffmpeg_path)
    return [
        name
        for name in VIDEO_ENCODERS[str(codec).lower()]
        if name in available and probe_encoder(str(Path(ffmpeg_path).resolve()), name)
    ]


def _nvidia_driver_info(
    cancelled: Callable[[], bool] | None = None,
) -> str:
    if cancelled is not None and cancelled():
        raise InterruptedError("encoder capability scan cancelled")
    try:
        completed = _run_probe(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"], timeout=8)
        if completed.returncode == 0:
            return (completed.stdout or "").strip().splitlines()[0] if completed.stdout else ""
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    return ""


def probe_encoder_detail(
    ffmpeg_path: str,
    encoder: str,
    *,
    listed: bool = True,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Functional encoder probe. Hardware tests use 640x360, never 64x64."""
    if cancelled is not None and cancelled():
        raise InterruptedError("encoder capability scan cancelled")
    null_target = "NUL" if os.name == "nt" else "/dev/null"
    command = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c=black:s={PROBE_FRAME_SIZE}:r=24",
        "-frames:v", "8", "-an", "-pix_fmt", "yuv420p",
        "-c:v", encoder, "-f", "null", null_target,
    ]
    result: dict[str, object] = {
        "encoder": encoder,
        "listed": bool(listed),
        "functional": False,
        "returncode": None,
        "stderr": "",
        "pixel_format": "yuv420p",
        "frame_size": PROBE_FRAME_SIZE,
        "command": command,
        "elapsed_ms": 0,
        "driver": (
            _nvidia_driver_info(cancelled)
            if encoder.endswith("_nvenc")
            else ""
        ),
    }
    if not listed:
        result["stderr"] = "not listed by this FFmpeg build"
        return result
    if encoder.startswith("lib"):
        result["functional"] = True
        result["returncode"] = 0
        return result
    started = time.perf_counter()
    try:
        if cancelled is not None and cancelled():
            raise InterruptedError("encoder capability scan cancelled")
        completed = run_hidden_subprocess(
            command,
            purpose="ffmpeg encoder probe",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            shell=False,
        )
        result["returncode"] = completed.returncode
        result["stderr"] = (completed.stderr or "")[-2000:]
        result["functional"] = completed.returncode == 0
        if cancelled is not None and cancelled():
            raise InterruptedError("encoder capability scan cancelled")
    except subprocess.TimeoutExpired as exc:
        result["returncode"] = -1
        result["stderr"] = f"timeout: {exc}"
    except OSError as exc:
        result["returncode"] = -1
        result["stderr"] = str(exc)
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


@lru_cache(maxsize=32)
def probe_encoder(ffmpeg_path: str, encoder: str) -> bool:
    return bool(probe_encoder_detail(ffmpeg_path, encoder).get("functional"))


def load_encoder_capabilities(
    ffmpeg_path: str | os.PathLike[str],
) -> dict | None:
    """Load a cache only when it belongs to this exact FFmpeg binary."""
    try:
        payload = json.loads(_capability_cache_path().read_text(encoding="utf-8"))
        if payload.get("schema") == CAPABILITY_SCHEMA and payload.get("ffmpeg") == _ffmpeg_signature(ffmpeg_path):
            return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return None


def scan_encoder_capabilities(
    ffmpeg_path: str | os.PathLike[str],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Detect listed and genuinely usable encoders, then persist the result."""
    def ensure_active() -> None:
        if cancelled is not None and cancelled():
            raise InterruptedError("encoder capability scan cancelled")

    path = str(Path(ffmpeg_path).resolve())
    ensure_active()
    version = _run_probe([path, "-hide_banner", "-version"])
    if version.returncode != 0:
        raise RuntimeError(version.stderr[-1200:])
    ensure_active()
    muxers = _run_probe([path, "-hide_banner", "-muxers"])
    ensure_active()
    encoders = available_encoders(path)
    ensure_active()
    hwaccels = _run_probe([path, "-hide_banner", "-hwaccels"])
    available_by_codec: dict[str, list[str]] = {}
    failures: dict[str, str] = {}
    probes: dict[str, dict[str, object]] = {}
    for codec, candidates in VIDEO_ENCODERS.items():
        working = []
        for encoder in candidates:
            ensure_active()
            detail = probe_encoder_detail(
                path,
                encoder,
                listed=encoder in encoders,
                cancelled=cancelled,
            )
            probes[encoder] = detail
            if detail["functional"]:
                working.append(encoder)
            else:
                failures[encoder] = str(detail.get("stderr") or "functional probe failed")[:400]
        available_by_codec[codec] = working
    audio_encoders = sorted(
        name for name in encoders if name in {"aac", "libopus", "opus", "flac", "pcm_s16le"}
    )
    payload = {
        "schema": CAPABILITY_SCHEMA,
        "scanned_at": int(time.time()),
        "ffmpeg": _ffmpeg_signature(path),
        "ffmpeg_version": (version.stdout.splitlines() or [""])[0],
        "muxers": sorted(set(re.findall(r"^\s*[D\.][E\.]\s+(\S+)", muxers.stdout, re.MULTILINE))),
        "video_encoders": sorted(encoders),
        "audio_encoders": audio_encoders,
        "hwaccels": [line.strip() for line in hwaccels.stdout.splitlines()[1:] if line.strip()],
        "available_by_codec": available_by_codec,
        "probe_failures": failures,
        "probes": probes,
        "probe_frame_size": PROBE_FRAME_SIZE,
        "nvidia_driver": _nvidia_driver_info(cancelled),
    }
    ensure_active()
    target = _capability_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return payload


def start_encoder_capability_scan(
    ffmpeg_path: str | os.PathLike[str],
    *,
    cancel_event: threading.Event | None = None,
) -> threading.Thread | None:
    """Warm the persistent cache without delaying first paint."""
    if load_encoder_capabilities(ffmpeg_path) is not None:
        return None

    cancellation = cancel_event or threading.Event()

    def work() -> None:
        try:
            scan_encoder_capabilities(
                ffmpeg_path,
                cancelled=cancellation.is_set,
            )
        except (InterruptedError, OSError, RuntimeError, subprocess.TimeoutExpired):
            pass

    worker = threading.Thread(target=work, daemon=True, name="encoder-capability-scan")
    worker.cancel_event = cancellation
    worker.start()
    return worker


def select_encoder(ffmpeg_path: str | os.PathLike[str], settings: RenderSettings) -> str:
    choices = encoder_choices(ffmpeg_path, settings.codec)
    if settings.encoder != "auto":
        if settings.encoder not in choices:
            raise RuntimeError(f"encoder is not available: {settings.encoder}")
        return settings.encoder
    if not choices:
        raise RuntimeError(f"no FFmpeg encoder is available for {settings.codec}")
    return choices[0]


def media_has_audio(ffmpeg_path: str | os.PathLike[str], media_path: str | os.PathLike[str]) -> bool:
    probe = Path(ffmpeg_path).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not probe.is_file():
        return True
    completed = _run_probe(
        [
            str(probe), "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0", str(media_path),
        ]
    )
    return bool(str(getattr(completed, "stdout", "") or "").strip())


def build_concat_filter_complex(
    slices: list[tuple[float, float]],
    ass_filter: str,
    *,
    has_audio: bool,
    scale: str = "",
    ass_origin: float = 0.0,
) -> tuple[str, str, str | None]:
    """One-graph trim/setpts/concat + ASS. Never re-encodes each slice first."""
    if not slices:
        raise ValueError("edit slices must not be empty")
    parts: list[str] = []
    for index, (start, end) in enumerate(slices):
        start = max(0.0, float(start))
        end = max(start + 0.05, float(end))
        parts.append(
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{index}]"
        )
        if has_audio:
            parts.append(
                f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]"
            )
    count = len(slices)
    if has_audio:
        interleaved = "".join(f"[v{index}][a{index}]" for index in range(count))
        parts.append(f"{interleaved}concat=n={count}:v=1:a=1[vcat][acat]")
        audio_label = "[acat]"
    else:
        video_refs = "".join(f"[v{index}]" for index in range(count))
        parts.append(f"{video_refs}concat=n={count}:v=1:a=0[vcat]")
        audio_label = None
    chain = []
    if ass_origin and ass_origin > 0.001:
        chain.append(f"setpts=PTS+{float(ass_origin):.6f}/TB")
    chain.append(ass_filter)
    if ass_origin and ass_origin > 0.001:
        chain.append("setpts=PTS-STARTPTS")
    if scale:
        chain.append(scale)
    parts.append(f"[vcat]{','.join(chain)}[vout]")
    return ";".join(parts), "[vout]", audio_label


def _filter_path(path: str | os.PathLike[str]) -> str:
    value = str(Path(path).resolve()).replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return f"'{value}'"


def _quality_arguments(encoder: str, settings: RenderSettings) -> list[str]:
    mode = settings.quality_mode
    if encoder.endswith("_nvenc"):
        if mode in {"cq", "crf"}:
            return ["-rc", "vbr", "-cq", str(settings.quality), "-b:v", "0"]
        if mode in {"vbr", "limited"}:
            return [
                "-rc", "vbr", "-b:v", f"{settings.bitrate_kbps}k",
                "-maxrate", f"{settings.max_bitrate_kbps}k",
            ]
        return ["-rc", "cbr", "-b:v", f"{settings.bitrate_kbps}k"]
    if encoder.endswith("_qsv"):
        if mode in {"cq", "crf"}:
            return ["-global_quality", str(settings.quality)]
        if mode == "cbr":
            return ["-b:v", f"{settings.bitrate_kbps}k", "-maxrate", f"{settings.bitrate_kbps}k"]
        return ["-b:v", f"{settings.bitrate_kbps}k", "-maxrate", f"{settings.max_bitrate_kbps}k"]
    if encoder.endswith("_amf"):
        if mode in {"cq", "crf"}:
            return ["-rc", "cqp", "-qp_i", str(settings.quality), "-qp_p", str(settings.quality)]
        if mode == "cbr":
            return ["-rc", "cbr", "-b:v", f"{settings.bitrate_kbps}k"]
        return ["-rc", "vbr_peak", "-b:v", f"{settings.bitrate_kbps}k", "-maxrate", f"{settings.max_bitrate_kbps}k"]
    if mode in {"crf", "cq"}:
        return ["-crf", str(settings.quality)]
    if mode == "target":
        return ["-b:v", f"{settings.bitrate_kbps}k"]
    if mode == "cbr":
        return ["-b:v", f"{settings.bitrate_kbps}k", "-maxrate", f"{settings.bitrate_kbps}k", "-bufsize", f"{int(settings.bitrate_kbps) * 2}k"]
    return ["-b:v", f"{settings.bitrate_kbps}k", "-maxrate", f"{settings.max_bitrate_kbps}k", "-bufsize", f"{int(settings.max_bitrate_kbps) * 2}k"]


def build_render_command(
    ffmpeg_path: str | os.PathLike[str],
    job: RenderJob,
) -> list[str]:
    settings = job.settings
    validate_export_config(job)
    media = Path(job.media_path).resolve()
    ass = Path(job.ass_path).resolve()
    output = Path(job.output_path).resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    if not ass.is_file():
        raise FileNotFoundError(ass)
    if output.suffix.lower() != f".{settings.container}":
        raise ValueError("output extension does not match container")
    encoder = select_encoder(ffmpeg_path, settings)
    command = [str(Path(ffmpeg_path).resolve()), "-hide_banner", "-loglevel", "warning", "-y"]
    slices = [(float(start), float(end)) for start, end in (job.edit_segments or ())]
    ass_filter = f"ass=filename={_filter_path(ass)}"
    # Qt's application fonts are process-local. libass in FFmpeg cannot see
    # them unless the same bundled bytes are explicitly supplied here.
    font_directory = settings.font_directory or str(Path(__file__).resolve().parents[1] / 'assets/fonts')
    ass_filter += f":fontsdir={_filter_path(font_directory)}"
    scale = f"scale={settings.width}:{settings.height}" if settings.width and settings.height else ""
    if job.direct_video_graph:
        from .export_filtergraph import compile_video_filtergraph
        command.extend(compile_video_filtergraph(ffmpeg_path, job, ass_filter))
    elif slices:
        command.extend(["-i", str(media)])
        has_audio = settings.audio_codec != "none" and media_has_audio(ffmpeg_path, media)
        graph, video_label, audio_label = build_concat_filter_complex(
            slices,
            ass_filter,
            has_audio=has_audio,
            scale=scale,
            ass_origin=float(job.start_seconds or 0.0),
        )
        command.extend(["-filter_complex", graph, "-map", video_label])
        if audio_label and settings.audio_codec != "none":
            command.extend(["-map", audio_label])
        elif settings.audio_codec == "none" or not has_audio:
            command.append("-an")
        if job.duration_seconds is not None:
            command.extend(["-t", f"{max(0.05, float(job.duration_seconds)):.3f}"])
    else:
        if job.start_seconds is not None and not job.composition_resolved:
            command.extend(["-ss", f"{max(0.0, float(job.start_seconds)):.3f}"])
        command.extend(["-i", str(media)])
        if job.duration_seconds is not None:
            command.extend(["-t", f"{max(0.05, float(job.duration_seconds)):.3f}"])
        # Input seeking resets the encoded segment to a zero-based timeline. Put
        # the original media timestamp back while libass evaluates cue times, then
        # normalize again for the output container. This keeps In/Out exports in
        # subtitle sync without rewriting the canonical ASS file.
        filters = []
        if job.start_seconds is not None and float(job.start_seconds) > 0:
            filters.append(f"setpts=PTS+{float(job.start_seconds):.3f}/TB")
        filters.append(ass_filter)
        if job.start_seconds is not None and float(job.start_seconds) > 0:
            filters.append("setpts=PTS-STARTPTS")
        if scale:
            filters.append(scale)
        if job.preview_url:
            chain = '[0:v]' + ','.join(filters) + ',split=2[vfinal][previewfull];[previewfull]fps=2:round=up:start_time=0:eof_action=pass,scale=640:-2[exportpreview]'
            command.extend(['-filter_complex', chain, '-map', '[vfinal]', '-map', '0:a?'])
        else:
            command.extend(["-map", "0:v:0", "-map", "0:a?", "-vf", ",".join(filters)])
    command.extend(["-c:v", encoder, *_quality_arguments(encoder, settings)])
    if settings.preset:
        command.extend(["-preset", settings.preset])
    if settings.profile:
        command.extend(["-profile:v", settings.profile])
    if settings.level:
        command.extend(["-level:v", settings.level])
    if settings.pixel_format:
        command.extend(["-pix_fmt", settings.pixel_format])
    if settings.fps > 0:
        command.extend(["-r", f"{settings.fps:g}"])
    if settings.gop > 0:
        command.extend(["-g", str(settings.gop)])
    if settings.b_frames >= 0:
        command.extend(["-bf", str(settings.b_frames)])
    audio_codec = ("opus" if settings.container == "webm" else "aac") if (slices or job.direct_video_graph) and settings.audio_codec == "copy" else settings.audio_codec
    if audio_codec == "none" or (slices and "-an" in command):
        if "-an" not in command:
            command.append("-an")
    elif audio_codec == "copy":
        command.extend(["-c:a", "copy"])
    else:
        command.extend(["-c:a", "libopus" if audio_codec == "opus" else audio_codec, "-b:a", f"{settings.audio_bitrate_kbps}k"])
        if settings.audio_sample_rate:
            command.extend(["-ar", str(settings.audio_sample_rate)])
        if settings.audio_channels:
            command.extend(["-ac", str(settings.audio_channels)])
    if settings.container in {"mp4", "mov"}:
        command.extend(["-movflags", "+faststart"])
    command.extend(["-progress", "pipe:1", "-nostats", str(output)])
    if job.preview_url:
        if job.duration_seconds:
            command.extend(['-t', f'{job.duration_seconds:.9f}'])
        command.extend(['-map', '[exportpreview]', '-an', '-c:v', 'rawvideo', '-pix_fmt', 'bgra',
                        '-threads', '1', '-f', 'nut', job.preview_url])
    return command


def _software_encoder(codec: str) -> str:
    return {"h264": "libx264", "hevc": "libx265", "av1": "libsvtav1"}[codec]


def hardware_encoders_for(codec: str, ffmpeg_path: str | os.PathLike[str]) -> list[str]:
    return [name for name in encoder_choices(ffmpeg_path, codec) if not name.startswith("lib")]


def render_fallback_job(job: RenderJob, error: BaseException) -> tuple[RenderJob, str] | None:
    """Return one conservative retry for a known encoder or audio-copy failure."""
    message = str(error).lower()
    encoder = str(job.settings.encoder or "")
    hardware_markers = (
        "nvenc", "qsv", "amf", "no capable", "device setup", "cannot load",
        "initializing output stream", "function not implemented",
    )
    if encoder.endswith(("_nvenc", "_qsv", "_amf")) and any(
        marker in message for marker in hardware_markers
    ):
        software = _software_encoder(job.settings.codec)
        return (
            replace(job, settings=replace(job.settings, encoder=software,
                preset='fast' if str(job.settings.preset).startswith('p') and str(job.settings.preset)[1:].isdigit() else job.settings.preset)),
            f"硬件编码不可用，已自动改用 {software}。",
        )
    audio_markers = (
        "codec not currently supported", "could not find tag", "muxer does not support",
        "audio codec", "incorrect codec parameters",
    )
    if job.settings.audio_codec == "copy" and any(marker in message for marker in audio_markers):
        return (
            replace(job, settings=replace(job.settings, audio_codec="aac")),
            "源音频不能直接复制，已自动改用 AAC。",
        )
    return None


def _run_render_attempt(
    ffmpeg_path: str | os.PathLike[str],
    job: RenderJob,
    *,
    progress: Callable[[dict[str, str]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    trace: Callable[[str, object], None] | None = None,
) -> Path:
    output = Path(job.output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(
        f".{output.stem}.{uuid.uuid4().hex}.partial{output.suffix}"
    )
    if progress:
        progress(export_progress(
            STAGE_PREPARE_SUBTITLES,
            message="正在准备 Native ASS 字幕烧录…",
        ))
    command = build_render_command(
        ffmpeg_path,
        replace(job, output_path=str(temporary)),
    )
    if trace:
        trace("command_created", command)
    process = popen_hidden_subprocess(
        command,
        purpose="ffmpeg studio render",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if trace:
        trace("process_started", {"pid": process.pid})
    if progress:
        progress(export_progress(
            STAGE_ENCODE,
            message="正在初始化编码器…",
            duration_seconds=float(job.duration_seconds or 0.0) or None,
        ))
    current: dict[str, str] = {}
    stderr_chunks: list[str] = []
    first_stderr_seen = [False]

    def drain_stderr() -> None:
        first = True
        if process.stderr:
            for line in process.stderr:
                if first and trace:
                    trace("first_stderr_line", line.rstrip())
                    first_stderr_seen[0] = True
                    first = False
                stderr_chunks.append(line)
                if len(stderr_chunks) > 400:
                    del stderr_chunks[:100]

    stderr_thread = threading.Thread(
        target=drain_stderr, daemon=True, name="studio-render-stderr"
    )
    stderr_thread.start()
    stdout_lines = queue.Queue()
    def drain_stdout():
        try:
            if process.stdout:
                for value in process.stdout:
                    stdout_lines.put(value)
        finally:
            stdout_lines.put(None)
    stdout_thread = threading.Thread(target=drain_stdout, daemon=True, name='studio-render-progress')
    stdout_thread.start()
    try:
        while True:
            if cancelled and cancelled():
                raise InterruptedError("render cancelled")
            try:
                line = stdout_lines.get(timeout=.1)
            except queue.Empty:
                continue
            if line is None:
                break
            key, separator, value = line.strip().partition("=")
            if separator:
                current[key] = value
                if key == "progress" and progress:
                    current["stage"] = STAGE_ENCODE
                    current["stage_label"] = STAGE_LABELS[STAGE_ENCODE]
                    current["indeterminate"] = "0"
                    current["message"] = "正在编码视频…"
                    if trace:
                        trace("progress_received", dict(current))
                    progress(dict(current))
                    current.clear()
        return_code = process.wait()
        if trace:
            trace("exit_code", return_code)
        stderr_thread.join(timeout=2.0)
        if trace and not first_stderr_seen[0]:
            trace("first_stderr_line", "")
        if return_code != 0:
            raise RuntimeError(f"FFmpeg render failed: {''.join(stderr_chunks)[-2000:]}")
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    if not temporary.is_file() or temporary.stat().st_size <= 0:
        raise RuntimeError("FFmpeg completed without a playable output file")
    if progress:
        progress(export_progress(STAGE_MUX, message="校验完整视频与音频后发布文件…"))
    try:
        from .export_validation import validate_output
        metadata = validate_output(ffmpeg_path,temporary,duration=job.duration_seconds,fps=job.settings.fps,cancelled=cancelled,preview_path=job.completion_preview_path)
        if trace: trace('validated_output',metadata)
        publish_output(temporary, output, job, metadata, cancelled=cancelled)
    finally:
        temporary.unlink(missing_ok=True)
    if progress:
        notify_after_publication(job, progress, export_progress(
            STAGE_MUX,
            message="封装完成",
            percent=100,
            indeterminate=False,
        ))
    if trace:
        notify_after_publication(job, trace, "output_verified", {"exists": output.is_file(), "size": output.stat().st_size})
    return output


@record_completion
def run_render_job(
    ffmpeg_path: str | os.PathLike[str],
    job: RenderJob,
    *,
    progress: Callable[[dict[str, str]], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    trace: Callable[[str, object], None] | None = None,
) -> Path:
    if job.video_graph:
        validate_export_config(job)
        from .media_availability import export_sources, probe_sources, require_available
        start_ms = (job.start_seconds or 0) * 1000
        end_ms = start_ms + job.duration_seconds * 1000 if job.duration_seconds else float('inf')
        sources = export_sources(job.video_graph, start_ms, end_ms)
        require_available(probe_sources(sources, decode=True, timeout=6, cancel_check=cancelled))
        if Path(job.output_path).exists() and not job.overwrite_existing:
            raise FileExistsError(f"输出文件已存在: {job.output_path}")
        from .export_filtergraph import simple_video_clips
        if simple_video_clips(job.video_graph) is not None:
            if trace:
                trace('export_route', {'route': 'direct_filtergraph', 'intermediate_video': False})
            graph = job.video_graph
            source_fps = graph.get('fps')
            if not source_fps and not job.settings.fps:
                from fractions import Fraction
                result = _run_probe([str(Path(ffmpeg_path).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')),
                    '-v','error','-select_streams','v:0','-show_entries','stream=avg_frame_rate','-of','json',job.media_path])
                source_fps = float(Fraction(json.loads(result.stdout)['streams'][0]['avg_frame_rate']))
            prepared = replace(job, direct_video_graph=graph, video_graph=None, edit_segments=(),
                               duration_seconds=job.duration_seconds or graph['duration_ms']/1000-(job.start_seconds or 0),
                               settings=replace(job.settings, fps=job.settings.fps or source_fps))
            return run_render_job(ffmpeg_path, prepared, progress=progress, cancelled=cancelled, trace=trace)
        from .video_export import prepared_video_job
        with prepared_video_job(ffmpeg_path, job, cancelled=cancelled, progress=progress) as prepared:
            return run_render_job(ffmpeg_path, prepared, progress=progress, cancelled=cancelled, trace=trace)
    output = Path(job.output_path).resolve()
    if output.exists() and not job.overwrite_existing:
        raise FileExistsError(f"输出文件已存在: {output}")
    if progress and not job.composition_resolved:
        progress(export_progress(
            STAGE_PREPARE_PROJECT,
            message="正在解析工程并检查输入文件…",
        ))
    current = job
    if current.settings.encoder == 'auto':
        current = replace(current, settings=replace(current.settings,
            encoder=select_encoder(ffmpeg_path, current.settings)))
    attempted: set[tuple[str, str]] = set()
    while True:
        key = (current.settings.encoder, current.settings.audio_codec)
        if key in attempted:
            raise RuntimeError("render fallback repeated the same settings")
        attempted.add(key)
        try:
            preview = None
            try:
                if current.preview_callback and not current.edit_segments:
                    from .export_preview import ExportPreview
                    preview = ExportPreview(current.preview_callback, current.start_seconds or 0)
                    current = replace(current, preview_url=preview.url)
                return _run_render_attempt(
                    ffmpeg_path, current, progress=progress, cancelled=cancelled, trace=trace
                )
            finally:
                if preview:
                    preview.close()
        except InterruptedError:
            raise
        except Exception as exc:
            if published_output_path(current) is not None:
                raise  # The outer receipt owner reports success; never encode again.
            fallback = render_fallback_job(current, exc)
            if fallback is None:
                raise
            current, notice = fallback
            if trace:
                trace('encoder_or_audio_fallback', {'reason':str(exc), 'notice':notice,
                    'encoder':current.settings.encoder, 'preset':current.settings.preset})
            if progress:
                progress({"notice": notice})


def preview_job(
    media_path: str,
    ass_path: str,
    output_path: str,
    settings: RenderSettings,
    playhead_seconds: float,
    media_duration_seconds: float = 0.0,
) -> RenderJob:
    duration = 10.0 if media_duration_seconds <= 0 else min(10.0, media_duration_seconds)
    start = max(0.0, float(playhead_seconds) - duration / 2)
    if media_duration_seconds > 0:
        start = min(start, max(0.0, media_duration_seconds - duration))
    return RenderJob(
        media_path,
        ass_path,
        output_path,
        settings,
        start,
        duration,
        overwrite_existing=True,
    )
