"""Shared media metadata and optional cancellable proxy preparation."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from .processes import popen_hidden_subprocess, run_hidden_subprocess
from .resource_governor import GLOBAL_RESOURCE_GOVERNOR, ResourceGovernor, ResourceKind
from .runtime_cache import CacheIdentity, GLOBAL_RUNTIME_CACHE, RuntimeCacheManager


MEDIA_METADATA_SCHEMA = 3
PROXY_MANIFEST_SCHEMA = 1


def _rate(value: object) -> float:
    text = str(value or "0/1")
    try:
        numerator, denominator = text.split("/", 1)
        return float(numerator) / max(float(denominator), 1.0)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _seconds_to_ms(value: object) -> int:
    try:
        seconds = float(value or 0.0)
    except (TypeError, ValueError):
        return 0
    if seconds <= 0:
        return 0
    return round(seconds * 1000)


def _stream_duration_ms(stream: Mapping) -> int:
    direct = _seconds_to_ms(stream.get("duration"))
    if direct:
        return direct
    try:
        timestamp = float(stream.get("duration_ts") or 0.0)
        text = str(stream.get("time_base") or "")
        numerator, denominator = text.split("/", 1)
        seconds = timestamp * float(numerator) / max(float(denominator), 1.0)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0
    return _seconds_to_ms(seconds)


def _timestamp_ms(value: object, time_base: object = "") -> float:
    """Convert a stream timestamp to milliseconds while preserving negatives."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    text = str(time_base or "")
    try:
        numerator, denominator = text.split("/", 1)
        seconds = number * float(numerator) / max(float(denominator), 1.0)
    except (TypeError, ValueError, ZeroDivisionError):
        seconds = number
    return seconds * 1000.0


def _stream_start_time_ms(value: object) -> float:
    """Convert ffprobe's stream ``start_time`` field, which is in seconds.

    Unlike ``start_pts`` and ``best_effort_timestamp``, ffprobe reports
    ``stream.start_time`` as a seconds string. Applying the stream timebase a
    second time turns a 998 ms FLV start into 0.998 ms.
    """
    try:
        return float(value) * 1000.0
    except (TypeError, ValueError):
        return 0.0


def probe_duration_ms(format_info: Mapping, streams: object) -> int:
    """Prefer container duration, then the longest video/audio stream duration.

    Some game recordings and phone captures leave ``format.duration`` empty
    while still carrying a valid stream duration. Treating that as 0 ms is
    what made Recognition projects show MediaAsset ``00:00``.
    """

    duration = _seconds_to_ms(format_info.get("duration") if isinstance(format_info, Mapping) else 0)
    if duration:
        return duration
    best = 0
    for stream in streams if isinstance(streams, list) else ():
        if isinstance(stream, Mapping):
            best = max(best, _stream_duration_ms(stream))
    return best


@dataclass(frozen=True)
class MediaMetadataSnapshot:
    source_path: str
    source_size: int
    source_mtime_ns: int
    duration_ms: int
    has_video: bool
    has_audio: bool
    video_codec: str = ""
    audio_codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    video_timebase: str = ""
    audio_timebase: str = ""
    sample_rate: int = 0
    channels: int = 0
    rotation: int = 0
    fingerprint: str = ""
    audio_stream_index: int = 0
    container_start_ms: float = 0.0
    source_start_ms: float = 0.0
    video_start_ms: float = 0.0
    audio_start_ms: float = 0.0
    video_first_pts_ms: float = 0.0
    audio_first_pts_ms: float = 0.0
    video_best_effort_timestamp_ms: float = 0.0
    audio_best_effort_timestamp_ms: float = 0.0
    sample_timeline_origin_ms: float = 0.0
    schema_version: int = MEDIA_METADATA_SCHEMA

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.update(
            size=self.source_size,
            mtime_ns=self.source_mtime_ns,
            timebase=self.video_timebase or self.audio_timebase,
            format_start_ms=self.container_start_ms,
        )
        return payload


@dataclass(frozen=True)
class ProxySettings:
    max_height: int = 720
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 23
    preset: str = "veryfast"

    def normalized(self) -> "ProxySettings":
        return ProxySettings(
            max_height=max(240, min(2160, int(self.max_height))),
            video_codec=str(self.video_codec or "libx264"),
            audio_codec=str(self.audio_codec or "aac"),
            crf=max(0, min(51, int(self.crf))),
            preset=str(self.preset or "veryfast"),
        )


@dataclass(frozen=True)
class ProxyManifest:
    identity_key: str
    source: Mapping[str, object]
    settings: Mapping[str, object]
    state: str
    proxy_path: str = ""
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    schema_version: int = PROXY_MANIFEST_SCHEMA

    @property
    def switch_ready(self) -> bool:
        return self.state == "READY" and bool(self.proxy_path) and Path(self.proxy_path).is_file()


class ProxyJob:
    def __init__(self, worker: Callable[["ProxyJob"], ProxyManifest]) -> None:
        self._worker = worker
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._process = None
        self.result: ProxyManifest | None = None
        self.error: BaseException | None = None
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="studio-proxy")

    def start(self) -> "ProxyJob":
        self._thread.start()
        return self

    def _run(self) -> None:
        try:
            self.result = self._worker(self)
        except BaseException as exc:
            self.error = exc
        finally:
            self._done.set()

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.kill()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def wait(self, timeout: float | None = None) -> ProxyManifest | None:
        self._done.wait(timeout)
        if self.error is not None:
            raise self.error
        return self.result


class MediaService:
    def __init__(
        self,
        *,
        ffprobe_path: str | os.PathLike[str] | None = None,
        ffmpeg_path: str | os.PathLike[str] | None = None,
        cache_root: str | os.PathLike[str] | None = None,
        cache_manager: RuntimeCacheManager | None = None,
        governor: ResourceGovernor | None = None,
        probe_runner: Callable[..., object] | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        from .platform_media import ffmpeg_tool
        self.ffprobe_path = Path(ffprobe_path or ffmpeg_tool("ffprobe", root=root))
        self.ffmpeg_path = Path(ffmpeg_path or ffmpeg_tool(root=root))
        if os.name == "nt":
            default_cache = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "2ByteASR" / "cache" / "media"
        else:
            from .runtime_paths import user_data_root
            default_cache = user_data_root() / "cache" / "media"
        self.cache_root = Path(cache_root or default_cache).resolve()
        self.cache_manager = cache_manager or GLOBAL_RUNTIME_CACHE
        self.governor = governor or GLOBAL_RESOURCE_GOVERNOR
        self._probe_runner = probe_runner or run_hidden_subprocess
        self._proxy_jobs_lock = threading.Lock()
        self._proxy_jobs: dict[str, ProxyJob] = {}

    def metadata(self, path: str | os.PathLike[str], *, refresh: bool = False) -> MediaMetadataSnapshot:
        source = Path(path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if not self.ffprobe_path.is_file():
            raise FileNotFoundError(f"FFprobe missing: {self.ffprobe_path}")
        identity = CacheIdentity.for_file(
            "media-metadata", source, schema=MEDIA_METADATA_SCHEMA,
            settings={"ffprobe": str(self.ffprobe_path)},
        )
        if refresh:
            return self._probe(source)
        value, _produced = self.cache_manager.get_or_create(
            identity,
            lambda: self._probe(source),
            cache_result=lambda _snapshot: (2048, False),
        )
        return value

    def _probe(self, source: Path) -> MediaMetadataSnapshot:
        completed = self._probe_runner(
            [
                str(self.ffprobe_path), "-v", "error", "-show_entries",
                "format=duration,size,start_time:stream=index,codec_type,codec_name,width,height,sample_rate,channels,avg_frame_rate,r_frame_rate,time_base,start_time,start_pts,best_effort_timestamp,duration,duration_ts:stream_tags=rotate:stream_side_data=rotation",
                "-of", "json", str(source),
            ],
            purpose="shared media metadata",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if int(getattr(completed, "returncode", 1)) != 0:
            raise RuntimeError(str(getattr(completed, "stderr", "")).strip() or "unable to probe media")
        payload = json.loads(str(getattr(completed, "stdout", "{}")))
        format_info = payload.get("format", {}) if isinstance(payload, Mapping) else {}
        streams = payload.get("streams", []) if isinstance(payload, Mapping) else []
        video = next((item for item in streams if item.get("codec_type") == "video"), {})
        audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
        container_start_ms = _timestamp_ms(format_info.get("start_time"))
        video_start_ms = _stream_start_time_ms(video.get("start_time")) if video else 0.0
        audio_start_ms = _stream_start_time_ms(audio.get("start_time")) if audio else 0.0
        video_first_pts_ms = _timestamp_ms(video.get("start_pts"), video.get("time_base")) if video else 0.0
        audio_first_pts_ms = _timestamp_ms(audio.get("start_pts"), audio.get("time_base")) if audio else 0.0
        video_best_effort_timestamp_ms = _timestamp_ms(video.get("best_effort_timestamp"), video.get("time_base")) if video else 0.0
        audio_best_effort_timestamp_ms = _timestamp_ms(audio.get("best_effort_timestamp"), audio.get("time_base")) if audio else 0.0
        rotation = (video.get("tags") or {}).get("rotate", 0) if isinstance(video, Mapping) else 0
        for side in video.get("side_data_list", []) if isinstance(video, Mapping) else []:
            if isinstance(side, Mapping) and side.get("rotation") is not None:
                rotation = side.get("rotation")
                break
        stat = source.stat()
        core = {
            "path": str(source),
            "size": int(format_info.get("size") or stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "duration_ms": probe_duration_ms(format_info, streams),
            "video_codec": str(video.get("codec_name") or ""),
            "audio_codec": str(audio.get("codec_name") or ""),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "fps": _rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            "video_timebase": str(video.get("time_base") or ""),
            "audio_timebase": str(audio.get("time_base") or ""),
            "sample_rate": int(audio.get("sample_rate") or 0),
            "channels": int(audio.get("channels") or 0),
            "rotation": int(float(rotation or 0)),
            "container_start_ms": container_start_ms,
            "source_start_ms": container_start_ms,
            "video_start_ms": video_start_ms,
            "audio_start_ms": audio_start_ms,
            "video_first_pts_ms": video_first_pts_ms,
            "audio_first_pts_ms": audio_first_pts_ms,
            "video_best_effort_timestamp_ms": video_best_effort_timestamp_ms,
            "audio_best_effort_timestamp_ms": audio_best_effort_timestamp_ms,
            "sample_timeline_origin_ms": audio_start_ms,
        }
        fingerprint = hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        return MediaMetadataSnapshot(
            source_path=core["path"],
            source_size=core["size"],
            source_mtime_ns=core["mtime_ns"],
            duration_ms=core["duration_ms"],
            has_video=bool(video),
            has_audio=bool(audio),
            video_codec=core["video_codec"],
            audio_codec=core["audio_codec"],
            width=core["width"],
            height=core["height"],
            fps=core["fps"],
            video_timebase=core["video_timebase"],
            audio_timebase=core["audio_timebase"],
            sample_rate=core["sample_rate"],
            channels=core["channels"],
            rotation=core["rotation"],
            fingerprint=fingerprint,
            audio_stream_index=int(audio.get("index") or 0) if audio else 0,
            container_start_ms=container_start_ms,
            source_start_ms=container_start_ms,
            video_start_ms=video_start_ms,
            audio_start_ms=audio_start_ms,
            video_first_pts_ms=video_first_pts_ms,
            audio_first_pts_ms=audio_first_pts_ms,
            video_best_effort_timestamp_ms=video_best_effort_timestamp_ms,
            audio_best_effort_timestamp_ms=audio_best_effort_timestamp_ms,
            sample_timeline_origin_ms=audio_start_ms,
        )

    def start_proxy(
        self,
        path: str | os.PathLike[str],
        *,
        settings: ProxySettings | None = None,
    ) -> ProxyJob:
        source = Path(path).resolve()
        normalized = (settings or ProxySettings()).normalized()
        identity = self._proxy_identity(source, normalized)
        with self._proxy_jobs_lock:
            existing = self._proxy_jobs.get(identity.key)
            if existing is not None and not existing.done:
                self.cache_manager.telemetry.record(
                    "wait_existing", key=identity.key, tier="proxy_job",
                )
                return existing

            def run(job: ProxyJob) -> ProxyManifest:
                try:
                    return self._build_proxy(source, normalized, job)
                finally:
                    with self._proxy_jobs_lock:
                        if self._proxy_jobs.get(identity.key) is job:
                            self._proxy_jobs.pop(identity.key, None)

            created = ProxyJob(run)
            self._proxy_jobs[identity.key] = created
        return created.start()

    def cancel_all(self) -> int:
        """Cancel active proxy jobs without blocking the caller."""
        with self._proxy_jobs_lock:
            jobs = tuple(self._proxy_jobs.values())
        for job in jobs:
            job.cancel()
        return len(jobs)

    def wait_for_idle(self, timeout: float = 2.0) -> bool:
        """Wait a bounded interval for proxy workers to release their jobs."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            with self._proxy_jobs_lock:
                jobs = tuple(self._proxy_jobs.values())
            if not jobs:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return False
            jobs[0]._done.wait(min(0.05, remaining))

    def proxy_manifest(self, path: str | os.PathLike[str], *, settings: ProxySettings | None = None) -> ProxyManifest | None:
        identity = self._proxy_identity(Path(path).resolve(), (settings or ProxySettings()).normalized())
        manifest_path = self._proxy_dir(identity) / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            return ProxyManifest(**json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, TypeError, ValueError):
            return None

    def _proxy_identity(self, source: Path, settings: ProxySettings) -> CacheIdentity:
        return CacheIdentity.for_file(
            "media-proxy", source, schema=PROXY_MANIFEST_SCHEMA,
            settings=asdict(settings), renderer="ffmpeg-proxy-v1",
        )

    def _proxy_dir(self, identity: CacheIdentity) -> Path:
        return self.cache_root / "proxy" / identity.key

    @staticmethod
    def _write_manifest(path: Path, manifest: ProxyManifest) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _build_proxy(self, source: Path, settings: ProxySettings, job: ProxyJob) -> ProxyManifest:
        metadata = self.metadata(source)
        identity = self._proxy_identity(source, settings)
        target_dir = self._proxy_dir(identity)
        manifest_path = target_dir / "manifest.json"
        target = target_dir / "proxy.mp4"
        existing = self.proxy_manifest(source, settings=settings)
        if existing and existing.switch_ready:
            return existing
        target_dir.mkdir(parents=True, exist_ok=True)
        started = time.time()
        running = ProxyManifest(
            identity_key=identity.key,
            source=metadata.to_dict(),
            settings=asdict(settings),
            state="RUNNING",
            started_at=started,
        )
        self._write_manifest(manifest_path, running)
        partial = target_dir / f"proxy.{uuid.uuid4().hex}.partial.mp4"
        scale = f"scale=-2:'min({settings.max_height},ih)'"
        command = [
            str(self.ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
            "-copyts", "-start_at_zero", "-i", str(source),
            "-map", "0:v:0?", "-map", "0:a:0?", "-vf", scale,
            "-c:v", settings.video_codec, "-preset", settings.preset,
            "-crf", str(settings.crf), "-c:a", settings.audio_codec,
            "-movflags", "+faststart", str(partial),
        ]
        try:
            with self.governor.lease(ResourceKind.PROXY, cancelled=lambda: job.cancelled) as allowed:
                if not allowed or job.cancelled:
                    raise InterruptedError("proxy cancelled")
                process = popen_hidden_subprocess(command, purpose="ffmpeg studio proxy")
                with job._lock:
                    job._process = process
                while process.poll() is None:
                    if job.cancelled:
                        process.kill()
                        raise InterruptedError("proxy cancelled")
                    time.sleep(0.05)
                if process.returncode != 0 or not partial.is_file() or partial.stat().st_size <= 0:
                    raise RuntimeError(f"ffmpeg proxy failed ({process.returncode})")
            proxy_metadata = self.metadata(partial, refresh=True)
            tolerance = max(100, round(1000 / max(metadata.fps, 1.0)))
            if abs(proxy_metadata.duration_ms - metadata.duration_ms) > tolerance:
                raise RuntimeError("proxy duration/timebase validation failed")
            if (
                proxy_metadata.has_video != metadata.has_video
                or proxy_metadata.has_audio != metadata.has_audio
            ):
                raise RuntimeError("proxy stream validation failed")
            if (
                metadata.has_video
                and metadata.fps > 0
                and proxy_metadata.fps > 0
                and abs(proxy_metadata.fps - metadata.fps) > max(0.05, metadata.fps * 0.02)
            ):
                raise RuntimeError("proxy frame-rate validation failed")
            os.replace(partial, target)
            ready = ProxyManifest(
                identity_key=identity.key,
                source=metadata.to_dict(),
                settings=asdict(settings),
                state="READY",
                proxy_path=str(target),
                started_at=started,
                completed_at=time.time(),
            )
            self._write_manifest(manifest_path, ready)
            self.cache_manager.register_artifact(identity, target)
            return ready
        except BaseException as exc:
            state = "CANCELLED" if isinstance(exc, InterruptedError) or job.cancelled else "FAILED"
            failed = ProxyManifest(
                identity_key=identity.key,
                source=metadata.to_dict(),
                settings=asdict(settings),
                state=state,
                error=str(exc),
                started_at=started,
                completed_at=time.time(),
            )
            self._write_manifest(manifest_path, failed)
            if job.cancelled:
                self.cache_manager.record_cancel(identity)
            raise
        finally:
            with job._lock:
                job._process = None
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass


GLOBAL_MEDIA_SERVICE = MediaService()


__all__ = [
    "MediaMetadataSnapshot", "ProxySettings", "ProxyManifest", "ProxyJob",
    "MediaService", "GLOBAL_MEDIA_SERVICE",
]
